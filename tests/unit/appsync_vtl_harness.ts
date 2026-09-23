/**
 * Minimal evaluator for the AppSync request-mapping-template VTL subset used by
 * the DynamoDB mapping templates under tofu/application/appsync/mapping-templates.
 *
 * It parses and executes real template source so unit tests can assert the
 * emitted DynamoDB request JSON and raised $util.error values instead of
 * grepping template text. AppSync VTL is not standard Apache Velocity (it
 * extends it with map/list literals in #set, $util.qr, $util.dynamodb, ...),
 * so off-the-shelf Velocity engines cannot execute these templates.
 *
 * Supported subset: ## comments, #if/#else/#end, #set, #foreach, #end,
 * string literals with $reference interpolation, map/list literals,
 * $prop chains, method calls, and the operators || && == != >= <= > < !.
 * Unsupported directives fail loudly with an explicit error.
 */

export class VtlError extends Error {
  readonly errorType: string;

  constructor(message: string, errorType: string) {
    super(message);
    this.name = 'VtlError';
    this.errorType = errorType;
  }
}

const QUIET: unique symbol = Symbol('vtl-quiet-return');
const FIXED_NOW = '2025-01-01T00:00:00.000Z';

let idCounter = 0;

function nextAutoId(): string {
  idCounter += 1;
  return `00000000-0000-4000-8000-${String(idCounter).padStart(12, '0')}`;
}

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

function toDynamoDB(value: unknown): Json {
  if (value === null || value === undefined) return { NULL: true };
  if (typeof value === 'string') return { S: value };
  if (typeof value === 'number') return { N: String(value) };
  if (typeof value === 'boolean') return { BOOL: value };
  if (Array.isArray(value)) return { L: value.map(toDynamoDB) };
  const map: { [key: string]: Json } = {};
  for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
    map[key] = toDynamoDB(entry);
  }
  return { M: map };
}

const utilDynamodb = {
  toDynamoDBJson: (value: unknown) => JSON.stringify(toDynamoDB(value)),
};

const utilTime = {
  nowISO8601: () => FIXED_NOW,
};

const util = {
  isString: (value: unknown) => typeof value === 'string',
  isNumber: (value: unknown) => typeof value === 'number' && !Number.isNaN(value),
  isBoolean: (value: unknown) => typeof value === 'boolean',
  isMap: (value: unknown) =>
    typeof value === 'object' && value !== null && !Array.isArray(value),
  isList: (value: unknown) => Array.isArray(value),
  isNull: (value: unknown) => value === null || value === undefined,
  isNullOrBlank: (value: unknown) => {
    if (value === null || value === undefined) return true;
    if (typeof value !== 'string') return false;
    return value.trim().length === 0;
  },
  error: (message: unknown, errorType: unknown) => {
    throw new VtlError(String(message), String(errorType));
  },
  qr: () => QUIET,
  autoId: () => nextAutoId(),
  time: utilTime,
  dynamodb: utilDynamodb,
};

const UTIL_NAMESPACES = new Set<unknown>([util, utilTime, utilDynamodb]);

function callMethod(target: unknown, name: string, args: unknown[]): unknown {
  if (Array.isArray(target)) {
    if (name === 'size') return target.length;
    if (name === 'isEmpty') return target.length === 0;
    if (name === 'add') {
      target.push(args[0]);
      return null;
    }
    if (name === 'contains') return target.includes(args[0]);
  } else if (target !== null && typeof target === 'object') {
    const map = target as Record<string, unknown>;
    if (name === 'put') {
      map[String(args[0])] = args[1];
      return null;
    }
    if (name === 'get') return map[String(args[0])];
    if (name === 'containsKey') return Object.hasOwn(map, String(args[0]));
  }
  throw new Error(`Unsupported VTL method .${name} on ${JSON.stringify(target)}`);
}

class Cursor {
  constructor(
    readonly source: string,
    public index = 0
  ) {}

  peek(offset = 0): string | undefined {
    return this.source[this.index + offset];
  }

  startsWith(text: string): boolean {
    return this.source.startsWith(text, this.index);
  }

  eof(): boolean {
    return this.index >= this.source.length;
  }
}

function skipWs(cursor: Cursor): void {
  while (!cursor.eof() && /\s/.test(cursor.peek()!)) cursor.index += 1;
}

function readIdent(cursor: Cursor): string {
  const start = cursor.index;
  while (!cursor.eof() && /[A-Za-z0-9_]/.test(cursor.peek()!)) cursor.index += 1;
  const ident = cursor.source.slice(start, cursor.index);
  if (!ident) throw new Error(`Expected identifier at offset ${start}`);
  return ident;
}

function expectChar(cursor: Cursor, char: string): void {
  if (cursor.peek() !== char) {
    throw new Error(`Expected '${char}' at offset ${cursor.index}`);
  }
  cursor.index += 1;
}

/** Reads source up to a depth-0 ')' or ','; nested (), {}, [] are balanced. */
function readBalanced(cursor: Cursor): string {
  const start = cursor.index;
  let depth = 0;
  while (!cursor.eof()) {
    const char = cursor.peek()!;
    if (char === '(' || char === '{' || char === '[') depth += 1;
    else if (char === ')' || char === '}' || char === ']') {
      if (depth === 0) break;
      depth -= 1;
    } else if (char === ',' && depth === 0) break;
    cursor.index += 1;
  }
  return cursor.source.slice(start, cursor.index);
}

type RefOp =
  | { kind: 'prop'; name: string }
  | { kind: 'call'; name: string; argSources: string[] };

interface Ref {
  base: string;
  ops: RefOp[];
}

function parseRef(cursor: Cursor): Ref {
  expectChar(cursor, '$');
  const base = readIdent(cursor);
  const ops: RefOp[] = [];
  while (cursor.peek() === '.') {
    cursor.index += 1;
    const name = readIdent(cursor);
    if (cursor.peek() === '(') {
      cursor.index += 1;
      const argSources: string[] = [];
      skipWs(cursor);
      if (cursor.peek() !== ')') {
        for (;;) {
          argSources.push(readBalanced(cursor));
          skipWs(cursor);
          if (cursor.peek() === ',') {
            cursor.index += 1;
            continue;
          }
          break;
        }
      }
      expectChar(cursor, ')');
      ops.push({ kind: 'call', name, argSources });
    } else {
      ops.push({ kind: 'prop', name });
    }
  }
  return { base, ops };
}

type StrPart = string | { ref: Ref };

type Expr =
  | { k: 'or'; l: Expr; r: Expr }
  | { k: 'and'; l: Expr; r: Expr }
  | { k: 'eq'; l: Expr; r: Expr }
  | { k: 'neq'; l: Expr; r: Expr }
  | { k: 'ge'; l: Expr; r: Expr }
  | { k: 'gt'; l: Expr; r: Expr }
  | { k: 'le'; l: Expr; r: Expr }
  | { k: 'lt'; l: Expr; r: Expr }
  | { k: 'not'; e: Expr }
  | { k: 'num'; v: number }
  | { k: 'bool'; v: boolean }
  | { k: 'str'; parts: StrPart[] }
  | { k: 'map'; entries: Array<[string, Expr]> }
  | { k: 'list'; items: Expr[] }
  | { k: 'ref'; ref: Ref };

function parseOr(cursor: Cursor): Expr {
  let left = parseAnd(cursor);
  for (;;) {
    skipWs(cursor);
    if (cursor.startsWith('||')) {
      cursor.index += 2;
      left = { k: 'or', l: left, r: parseAnd(cursor) };
    } else return left;
  }
}

function parseAnd(cursor: Cursor): Expr {
  let left = parseEquality(cursor);
  for (;;) {
    skipWs(cursor);
    if (cursor.startsWith('&&')) {
      cursor.index += 2;
      left = { k: 'and', l: left, r: parseEquality(cursor) };
    } else return left;
  }
}

function parseEquality(cursor: Cursor): Expr {
  let left = parseRelational(cursor);
  for (;;) {
    skipWs(cursor);
    if (cursor.startsWith('==')) {
      cursor.index += 2;
      left = { k: 'eq', l: left, r: parseRelational(cursor) };
    } else if (cursor.startsWith('!=')) {
      cursor.index += 2;
      left = { k: 'neq', l: left, r: parseRelational(cursor) };
    } else return left;
  }
}

function parseRelational(cursor: Cursor): Expr {
  let left = parseUnary(cursor);
  for (;;) {
    skipWs(cursor);
    const two = cursor.source.slice(cursor.index, cursor.index + 2);
    if (two === '>=' || two === '<=') {
      cursor.index += 2;
      left = { k: two === '>=' ? 'ge' : 'le', l: left, r: parseUnary(cursor) };
    } else if (cursor.peek() === '>' || cursor.peek() === '<') {
      const char = cursor.peek()!;
      cursor.index += 1;
      left = { k: char === '>' ? 'gt' : 'lt', l: left, r: parseUnary(cursor) };
    } else return left;
  }
}

function parseUnary(cursor: Cursor): Expr {
  skipWs(cursor);
  if (cursor.peek() === '!') {
    cursor.index += 1;
    return { k: 'not', e: parseUnary(cursor) };
  }
  return parsePrimary(cursor);
}

function parseInterpolatedString(cursor: Cursor): Expr {
  expectChar(cursor, '"');
  const parts: StrPart[] = [];
  let buffer = '';
  while (!cursor.eof()) {
    const char = cursor.peek()!;
    if (char === '"') {
      cursor.index += 1;
      break;
    }
    if (char === '\\') {
      const next = cursor.peek(1);
      buffer += next === '"' ? '"' : next!;
      cursor.index += 2;
      continue;
    }
    if (char === '$') {
      const ref = parseRef(cursor);
      if (buffer) {
        parts.push(buffer);
        buffer = '';
      }
      parts.push({ ref });
      continue;
    }
    buffer += char;
    cursor.index += 1;
  }
  if (buffer) parts.push(buffer);
  return { k: 'str', parts };
}

function parsePrimary(cursor: Cursor): Expr {
  skipWs(cursor);
  const char = cursor.peek();
  if (char === '(') {
    cursor.index += 1;
    const inner = parseOr(cursor);
    skipWs(cursor);
    expectChar(cursor, ')');
    return inner;
  }
  if (char === '"') return parseInterpolatedString(cursor);
  if (char !== undefined && /[0-9]/.test(char)) {
    const start = cursor.index;
    while (!cursor.eof() && /[0-9.]/.test(cursor.peek()!)) cursor.index += 1;
    return { k: 'num', v: Number(cursor.source.slice(start, cursor.index)) };
  }
  if (char === '{') {
    cursor.index += 1;
    const entries: Array<[string, Expr]> = [];
    for (;;) {
      skipWs(cursor);
      if (cursor.peek() === '}') {
        cursor.index += 1;
        break;
      }
      const key = parseInterpolatedString(cursor);
      if (key.k !== 'str' || key.parts.length !== 1 || typeof key.parts[0] !== 'string') {
        throw new Error('Map literal keys must be plain strings');
      }
      skipWs(cursor);
      expectChar(cursor, ':');
      entries.push([key.parts[0] as string, parseOr(cursor)]);
      skipWs(cursor);
      if (cursor.peek() === ',') {
        cursor.index += 1;
        continue;
      }
      expectChar(cursor, '}');
      break;
    }
    return { k: 'map', entries };
  }
  if (char === '[') {
    cursor.index += 1;
    const items: Expr[] = [];
    for (;;) {
      skipWs(cursor);
      if (cursor.peek() === ']') {
        cursor.index += 1;
        break;
      }
      items.push(parseOr(cursor));
      skipWs(cursor);
      if (cursor.peek() === ',') {
        cursor.index += 1;
        continue;
      }
      expectChar(cursor, ']');
      break;
    }
    return { k: 'list', items };
  }
  if (char === '$') return { k: 'ref', ref: parseRef(cursor) };
  if (char !== undefined && /[A-Za-z_]/.test(char)) {
    const word = readIdent(cursor);
    if (word === 'true') return { k: 'bool', v: true };
    if (word === 'false') return { k: 'bool', v: false };
    throw new Error(`Unexpected identifier '${word}' in expression`);
  }
  throw new Error(`Unexpected character '${char}' at offset ${cursor.index}`);
}

function parseExpr(source: string): Expr {
  const cursor = new Cursor(source);
  const expr = parseOr(cursor);
  skipWs(cursor);
  if (!cursor.eof()) {
    throw new Error(`Unexpected trailing input at offset ${cursor.index} in expression: ${source}`);
  }
  return expr;
}

interface EvalState {
  ctx: unknown;
  scope: Record<string, unknown>;
}

function truthy(value: unknown): boolean {
  return Boolean(value);
}

function vtlStringify(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function evalRef(ref: Ref, state: EvalState): unknown {
  let value: unknown = Object.hasOwn(state.scope, ref.base)
    ? state.scope[ref.base]
    : ref.base === 'ctx'
      ? state.ctx
      : ref.base === 'util'
        ? util
        : undefined;
  for (const op of ref.ops) {
    if (op.kind === 'prop') {
      value = (value as Record<string, unknown> | undefined)?.[op.name];
    } else {
      const args = op.argSources.map((src) => evalExpr(parseExpr(src), state));
      if (UTIL_NAMESPACES.has(value)) {
        const fn = (value as Record<string, unknown>)[op.name];
        if (typeof fn !== 'function') throw new Error(`Unknown $util method ${op.name}`);
        value = (fn as (...a: unknown[]) => unknown)(...args);
      } else {
        value = callMethod(value, op.name, args);
      }
    }
  }
  return value;
}

function evalExpr(expr: Expr, state: EvalState): unknown {
  switch (expr.k) {
    case 'or':
      return truthy(evalExpr(expr.l, state)) || truthy(evalExpr(expr.r, state));
    case 'and':
      return truthy(evalExpr(expr.l, state)) && truthy(evalExpr(expr.r, state));
    case 'eq': {
      const left = evalExpr(expr.l, state);
      const right = evalExpr(expr.r, state);
      return left === right || (left === null && right === undefined) || (left === undefined && right === null);
    }
    case 'neq': {
      const left = evalExpr(expr.l, state);
      const right = evalExpr(expr.r, state);
      return !(left === right || (left == null && right == null));
    }
    case 'ge':
      return (evalExpr(expr.l, state) as number) >= (evalExpr(expr.r, state) as number);
    case 'gt':
      return (evalExpr(expr.l, state) as number) > (evalExpr(expr.r, state) as number);
    case 'le':
      return (evalExpr(expr.l, state) as number) <= (evalExpr(expr.r, state) as number);
    case 'lt':
      return (evalExpr(expr.l, state) as number) < (evalExpr(expr.r, state) as number);
    case 'not':
      return !truthy(evalExpr(expr.e, state));
    case 'num':
      return expr.v;
    case 'bool':
      return expr.v;
    case 'str':
      return expr.parts
        .map((part) =>
          typeof part === 'string' ? part : vtlStringify(evalRef(part.ref, state))
        )
        .join('');
    case 'map': {
      const map: Record<string, unknown> = {};
      for (const [key, value] of expr.entries) map[key] = evalExpr(value, state);
      return map;
    }
    case 'list':
      return expr.items.map((item) => evalExpr(item, state));
    case 'ref':
      return evalRef(expr.ref, state);
  }
}

type Node =
  | { k: 'text'; value: string }
  | { k: 'set'; target: string; expr: Expr }
  | { k: 'if'; branches: Array<{ cond: Expr | null; body: Node[] }> }
  | { k: 'foreach'; varName: string; iterable: Expr; body: Node[] };

const KNOWN_DIRECTIVES = new Set(['#if', '#set', '#foreach', '#else', '#end', '#elseif']);

function readDirectiveWord(cursor: Cursor): string | null {
  if (cursor.peek() !== '#') return null;
  const next = cursor.peek(1);
  if (next === undefined || !/[A-Za-z]/.test(next)) return null;
  const start = cursor.index;
  cursor.index += 1;
  const word = '#' + readIdent(cursor);
  if (!KNOWN_DIRECTIVES.has(word)) {
    cursor.index = start;
    return null;
  }
  return word;
}

function readParensBody(cursor: Cursor): string {
  skipWs(cursor);
  expectChar(cursor, '(');
  const body = readBalanced(cursor);
  expectChar(cursor, ')');
  return body;
}

function parseNodes(cursor: Cursor): {
  nodes: Node[];
  terminator: '#else' | '#end' | null;
} {
  const nodes: Node[] = [];
  let textBuffer = '';
  const flushText = () => {
    if (textBuffer) {
      nodes.push({ k: 'text', value: textBuffer });
      textBuffer = '';
    }
  };

  while (!cursor.eof()) {
    if (cursor.startsWith('##')) {
      flushText();
      while (!cursor.eof() && cursor.peek() !== '\n') cursor.index += 1;
      continue;
    }
    const word = readDirectiveWord(cursor);
    if (word === null) {
      textBuffer += cursor.peek();
      cursor.index += 1;
      continue;
    }
    flushText();
    if (word === '#if') {
      const cond = parseExpr(readParensBody(cursor));
      const branches: Array<{ cond: Expr | null; body: Node[] }> = [];
      let branch = parseNodes(cursor);
      branches.push({ cond, body: branch.nodes });
      while (branch.terminator === '#else') {
        branch = parseNodes(cursor);
        branches.push({ cond: null, body: branch.nodes });
      }
      if (branch.terminator !== '#end') {
        throw new Error('Unbalanced #if: missing #end');
      }
      nodes.push({ k: 'if', branches });
    } else if (word === '#set') {
      const inner = readParensBody(cursor);
      const eq = inner.indexOf('=');
      if (eq < 0) throw new Error(`Malformed #set: ${inner}`);
      const target = inner.slice(0, eq).trim();
      if (!/^\$[A-Za-z_][A-Za-z0-9_]*$/.test(target)) {
        throw new Error(`Unsupported #set target: ${target}`);
      }
      nodes.push({ k: 'set', target: target.slice(1), expr: parseExpr(inner.slice(eq + 1)) });
    } else if (word === '#foreach') {
      const inner = readParensBody(cursor);
      const match = /^\s*\$([A-Za-z_][A-Za-z0-9_]*)\s+in\s+([\s\S]+)$/.exec(inner);
      if (!match) throw new Error(`Malformed #foreach: ${inner}`);
      const body = parseNodes(cursor);
      if (body.terminator !== '#end') throw new Error('Unbalanced #foreach: missing #end');
      nodes.push({
        k: 'foreach',
        varName: match[1],
        iterable: parseExpr(match[2]),
        body: body.nodes,
      });
    } else {
      return { nodes, terminator: word as '#else' | '#end' };
    }
  }
  flushText();
  return { nodes, terminator: null };
}

function renderText(text: string, state: EvalState): string {
  let output = '';
  const cursor = new Cursor(text);
  while (!cursor.eof()) {
    if (cursor.peek() === '$' && cursor.peek(1) !== undefined && /[A-Za-z_]/.test(cursor.peek(1)!)) {
      const value = evalRef(parseRef(cursor), state);
      if (value !== QUIET) output += vtlStringify(value);
    } else {
      output += cursor.peek();
      cursor.index += 1;
    }
  }
  return output;
}

function renderNodes(nodes: Node[], state: EvalState, output: string[]): void {
  for (const node of nodes) {
    if (node.k === 'text') {
      output.push(renderText(node.value, state));
    } else if (node.k === 'set') {
      state.scope[node.target] = evalExpr(node.expr, state);
    } else if (node.k === 'if') {
      for (const branch of node.branches) {
        if (branch.cond === null || truthy(evalExpr(branch.cond, state))) {
          renderNodes(branch.body, state, output);
          break;
        }
      }
    } else {
      const items = evalExpr(node.iterable, state);
      if (!Array.isArray(items)) {
        throw new VtlError('#foreach iterable evaluated to a non-list', 'INTERNAL_ERROR');
      }
      for (const item of items) {
        state.scope[node.varName] = item;
        renderNodes(node.body, state, output);
      }
    }
  }
}

/**
 * Executes an AppSync request mapping template against the given AppSync
 * context ({ ctx }) and returns the rendered template body — for DynamoDB
 * data sources that is the request JSON document.
 */
export function renderVtlTemplate(templateSource: string, ctx: unknown): string {
  idCounter = 0;
  const parsed = parseNodes(new Cursor(templateSource));
  if (parsed.terminator !== null) throw new Error(`Unexpected ${parsed.terminator}`);
  const output: string[] = [];
  renderNodes(parsed.nodes, { ctx, scope: {} }, output);
  return output.join('');
}
