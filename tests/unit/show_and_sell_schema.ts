/**
 * Shared, pure SDL parser for the Show & Sell and inventory static guards.
 *
 * There is no GraphQL parser in this repo that knows the AppSync directives, so
 * the schema is read as TEXT with anchored patterns and matched after every
 * docstring and `#` comment is blanked (this very schema discusses
 * `@aws_api_key` / `@aws_cognito_user_pools` in prose, and order ids contain
 * `#`). This module is deliberately PARSER-ONLY: it exposes the structural
 * primitives the guards need (definitions, fields, return types, directive sets)
 * and nothing semantic. Each guard file keeps its own assertions and its own
 * detection logic so a failing fixture exercises the detector that lives next
 * to it.
 *
 * The parser is anchored, not substring-based:
 *   - a definition header is `type|input|enum|interface <Name>` at column 0,
 *     and its body runs to the closing `}` at column 0 (field arguments use
 *     parentheses, so braces never nest in this schema);
 *   - a field entry starts at two spaces of indentation with an identifier
 *     followed by `(` or `:`; its closing `): Type! @directive` line starts
 *     with `)` and so never starts a new entry.
 */
import { readFileSync } from "fs";
import { join } from "path";
import { fileURLToPath } from "url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

export const SCHEMA_PATH = join(__dirname, "..", "..", "tofu", "application", "schema", "schema.graphql");

/** The AppSync auth directives this schema may carry. */
export const API_KEY = "aws_api_key";
export const COGNITO = "aws_cognito_user_pools";

export interface Definition {
  kind: string;
  name: string;
  directives: string[];
  /** Raw source of the definition body (between the `{` and the closing `}`). */
  body: string;
}

export interface Field {
  name: string;
  directives: string[];
  /** Raw source of the field entry, so its return type can be recovered. */
  text: string;
}

/** Replaces a matched run with equivalent-length whitespace, newlines intact. */
function blank(match: string): string {
  return match.replace(/[^\n]/g, " ");
}

/**
 * Blanks every block docstring and line comment so directive names or field
 * names that appear in prose cannot be matched, while keeping every real
 * token's position.
 */
export function codeOnly(source: string): string {
  return source.replace(/"""[\s\S]*?"""/g, blank).replace(/#[^\n]*/g, "");
}

/** Reads the raw schema file. */
export function loadSchema(): string {
  return readFileSync(SCHEMA_PATH, "utf8");
}

/** The code-only form of the on-disk schema. */
export function loadCodeOnlySchema(): string {
  return codeOnly(loadSchema());
}

/**
 * Parses top-level `type` / `input` / `enum` / `interface` definitions: the
 * header is anchored at column 0, and the body runs to the closing brace at
 * column 0. A well-formed schema never leaves a definition unterminated, so a
 * missing close is a structural defect the guards must treat as a failure.
 */
export function parseDefinitions(source: string): Definition[] {
  const definitions: Definition[] = [];
  const header = /^(type|input|enum|interface)\s+(\w+)([^\n]*)$/gm;
  for (const match of source.matchAll(header)) {
    const [, kind, name, rest] = match;
    const start = (match.index ?? 0) + match[0].length;
    const close = source.indexOf("\n}", start);
    if (close === -1) {
      throw new Error(`unterminated ${kind} ${name} in schema.graphql`);
    }
    definitions.push({
      kind,
      name,
      directives: [...rest.matchAll(/@(\w+)/g)].map((m) => m[1]),
      body: source.slice(start, close),
    });
  }
  return definitions;
}

/** Parses the fields of one object definition body (see module header). */
export function parseFields(body: string): Field[] {
  const fields: Field[] = [];
  const starts: { name: string; index: number }[] = [];
  for (const match of body.matchAll(/^ {2}([a-z]\w*)(?=[(:])/gm)) {
    starts.push({ name: match[1], index: match.index ?? 0 });
  }
  starts.forEach((entry, i) => {
    const end = i + 1 < starts.length ? starts[i + 1].index : body.length;
    const text = body.slice(entry.index, end);
    fields.push({
      name: entry.name,
      directives: [...text.matchAll(/@(\w+)/g)].map((m) => m[1]),
      text,
    });
  });
  return fields;
}

/** Base type name of a field's return type, with `!` and list brackets stripped. */
export function returnTypeName(entry: string): string | null {
  const tail = entry.match(/\):\s*([\w![\]]+)/) ?? entry.match(/^ {2}[a-z]\w*:\s*([\w![\]]+)/m);
  if (!tail) {
    return null;
  }
  return tail[1].replace(/[![\]]/g, "");
}

/** The `input <Name>` / `type <Name>` definitions only (no enum/interface). */
export function parseDefinitionsByKind(source: string, kind: string): Definition[] {
  return parseDefinitions(source).filter((d) => d.kind === kind);
}

/**
 * Every (type name, field) pair in the schema, for a whole-schema scan. This is
 * how a guard finds a report-download field or an admin field leaked onto any
 * type, without hand-listing the types.
 */
export function allFields(source: string): { owner: string; kind: string; field: Field }[] {
  return parseDefinitions(source).flatMap((d) =>
    parseFields(d.body).map((field) => ({ owner: d.name, kind: d.kind, field })),
  );
}

/** The root `Query` and `Mutation` fields, in declaration order. */
export function rootFields(source: string): Field[] {
  return parseDefinitions(source)
    .filter((d) => d.name === "Query" || d.name === "Mutation")
    .flatMap((d) => parseFields(d.body));
}

/**
 * Every field whose return type is the `AWSURL` scalar. A pre-signed report /
 * ICS / document download URL is the one shape a server-side artifact endpoint
 * must take, so this is the seam the browser-only reporting guard watches. QR
 * image GETs are a plain `String` (see `qrCodeUrl`) and never carry `AWSURL`,
 * so they do not surface here and are recognized as non-reporting separately.
 */
export function urlFields(source: string): { owner: string; field: Field }[] {
  return allFields(source).filter((entry) => (returnTypeName(entry.field.text) ?? "") === "AWSURL");
}
