import { describe, test, expect } from "vitest";
import { readdirSync, readFileSync, statSync } from "fs";
import { join } from "path";
import { fileURLToPath } from "url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

const JS_RESOLVERS_DIR = join(
  __dirname,
  "..",
  "..",
  "tofu",
  "application",
  "appsync",
  "js-resolvers",
);
const LIB_DIR = join(JS_RESOLVERS_DIR, "lib");

// The ID prefixes the DynamoDB key scheme uses.
const PREFIXES = ["ACCOUNT", "PROFILE", "CATALOG", "CAMPAIGN", "ORDER"];

// Helpers that legitimately own a prefix literal as an argument. Derived from
// the actual exports of lib/ so a new helper is covered without editing this
// list. A prefix may also appear inside lib/ itself - that is where the scheme
// is defined.
const SHARED_HELPERS = new Set(
  readdirSync(LIB_DIR)
    .filter((f) => f.endsWith(".js"))
    .flatMap((f) => {
      const source = readFileSync(join(LIB_DIR, f), "utf8");
      return [...source.matchAll(/export function (\w+)/g)].map((m) => m[1]);
    }),
);

/**
 * Replaces every comment in `source` with equivalent-length whitespace, keeping
 * all other characters and their offsets intact. A prefix mentioned in a
 * comment is documentation, not a second implementation, and must not trip this
 * guard - but a prefix in real code must.
 */
function blankComments(source: string): string {
  const out = source.split("");
  let i = 0;
  // Tracks the last significant character, so a `/` can be told apart as a
  // regex literal start from a division operator without a full JS parser.
  let lastSignificant = "";
  while (i < source.length) {
    const ch = source[i];
    const next = source[i + 1];

    if (ch === "/" && next === "/") {
      while (i < source.length && source[i] !== "\n") {
        out[i] = " ";
        i += 1;
      }
      continue;
    }

    if (ch === "/" && next === "*") {
      const end = source.indexOf("*/", i + 2);
      const stop = end === -1 ? source.length : end + 2;
      for (let j = i; j < stop; j += 1) {
        if (source[j] !== "\n") out[j] = " ";
      }
      i = stop;
      continue;
    }

    if (ch === '"' || ch === "'" || ch === "`") {
      const quote = ch;
      i += 1;
      while (i < source.length) {
        if (source[i] === "\\") {
          i += 2;
          continue;
        }
        if (source[i] === quote) {
          i += 1;
          break;
        }
        i += 1;
      }
      lastSignificant = "literal";
      continue;
    }

    if (ch === "/" && canStartRegex(lastSignificant)) {
      // Skip a regex literal wholesale so a `/` inside it is not mistaken for
      // a comment start.
      i += 1;
      let inClass = false;
      while (i < source.length) {
        if (source[i] === "\\") {
          i += 2;
          continue;
        }
        if (source[i] === "[") inClass = true;
        else if (source[i] === "]") inClass = false;
        else if (source[i] === "/" && !inClass) {
          i += 1;
          break;
        } else if (source[i] === "\n") break;
        i += 1;
      }
      while (i < source.length && /[a-z]/.test(source[i])) i += 1;
      lastSignificant = "literal";
      continue;
    }

    if (!/\s/.test(ch)) lastSignificant = ch;
    i += 1;
  }
  return out.join("");
}

// True when a `/` following `last` must be a regex literal rather than a
// division operator, using the standard lexical heuristic.
function canStartRegex(last: string): boolean {
  if (last === "") return true;
  if (/[)\]}\w$'"`]/.test(last)) return false;
  return true;
}

/**
 * Yields every prefix literal in `source` (comments removed) together with the
 * statement text around it, so the guard can report a usable location.
 */
function findPrefixLiterals(source: string): {
  line: number;
  prefix: string;
  text: string;
  inHelperCall: boolean;
}[] {
  const code = blankComments(source);
  const found: ReturnType<typeof findPrefixLiterals> = [];

  // Every string or template literal, with its offsets.
  const literals: { start: number; end: number; raw: string; value: string }[] = [];
  let i = 0;
  while (i < code.length) {
    const ch = code[i];
    if (ch === '"' || ch === "'" || ch === "`") {
      const quote = ch;
      const start = i;
      i += 1;
      let value = "";
      while (i < code.length) {
        if (code[i] === "\\") {
          value += code[i + 1];
          i += 2;
          continue;
        }
        if (code[i] === quote) {
          i += 1;
          break;
        }
        value += code[i];
        i += 1;
      }
      literals.push({ start, end: i, raw: source.slice(start, i), value });
      continue;
    }
    i += 1;
  }

  for (const lit of literals) {
    const match = /^(ACCOUNT|PROFILE|CATALOG|CAMPAIGN|ORDER)#/.exec(lit.value);
    if (!match) continue;

    // Walk left to the nearest statement boundary to get a readable excerpt.
    const lineStart = source.lastIndexOf("\n", lit.start) + 1;
    const lineEnd = source.indexOf("\n", lit.end);
    const text = source
      .slice(lineStart, lineEnd === -1 ? source.length : lineEnd)
      .trim();

    // Is this literal an argument to one of the shared helpers? Walk left to
    // the enclosing call's `(` - the literal may be any argument, not just the
    // first - then read the callee's name.
    let p = lit.start - 1;
    let depth = 0;
    while (p >= 0) {
      if (code[p] === ")") depth += 1;
      else if (code[p] === "(") {
        if (depth === 0) break;
        depth -= 1;
      } else if (code[p] === ";" || code[p] === "{" || code[p] === "}") {
        // Statement boundary: no enclosing call from here.
        p = -1;
        break;
      }
      p -= 1;
    }

    let inHelperCall = false;
    if (p >= 0 && code[p] === "(") {
      let q = p - 1;
      while (q >= 0 && /\s/.test(code[q])) q -= 1;
      const nameEnd = q;
      while (q >= 0 && /[\w$]/.test(code[q])) q -= 1;
      if (SHARED_HELPERS.has(code.slice(q + 1, nameEnd + 1))) inHelperCall = true;
    }

    found.push({
      line: source.slice(0, lit.start).split("\n").length,
      prefix: match[1],
      text,
      inHelperCall,
    });
  }

  return found;
}

function walkJsFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...walkJsFiles(full));
    } else if (entry.endsWith(".js")) {
      out.push(full);
    }
  }
  return out;
}

const resolverFiles = walkJsFiles(JS_RESOLVERS_DIR).filter(
  (f) => !f.endsWith(".test.js") && !f.startsWith(LIB_DIR),
);

describe("ID-prefix normalization has a single owner", () => {
  test("the guard set is not empty - a guard that scans nothing proves nothing", () => {
    expect(resolverFiles.length).toBeGreaterThan(40);
  });

  for (const file of resolverFiles) {
    const name = file.slice(JS_RESOLVERS_DIR.length + 1);
    const source = readFileSync(file, "utf8");

    test(`${name} builds every ID prefix through lib/ids.js or lib/owner_key.js`, () => {
      const offenders = findPrefixLiterals(source)
        .filter((f) => !f.inHelperCall)
        .map((f) => `line ${f.line}: ${f.text}`);

      expect(
        offenders,
        `${name} still hand-rolls an ID prefix. Route it through ` +
          `normalizeId/expectedOwnerKey from lib/ids.js or lib/owner_key.js ` +
          `so the normalization rule has one owner:\n  ${offenders.join("\n  ")}`,
      ).toEqual([]);
    });
  }
});

describe("the guard catches the duplication it exists to prevent", () => {
  // The review that prompted this guard re-introduced the exact duplication in
  // two files and every behavioral test stayed green. These cases assert the
  // guard itself fires, so it cannot silently degrade into a no-op.
  const reintroduced = [
    {
      name: "the inline startsWith ternary #534 removed",
      code: [
        "import { util } from '@aws-appsync/utils';",
        "export function request(ctx) {",
        "  const value = ctx.args.profileId;",
        "  return value.startsWith('PROFILE#') ? value : 'PROFILE#' + value;",
        "}",
      ].join("\n"),
    },
    {
      name: "an inline ACCOUNT# concatenation",
      code: "const accountId = 'ACCOUNT#' + ctx.identity.sub;",
    },
    {
      name: "an inline ACCOUNT# template literal",
      code: "const accountId = `ACCOUNT#${ctx.identity.sub}`;",
    },
    {
      name: "an inline composite ORDER# build",
      code: "const orderId = `ORDER#${campaignId}#${util.autoId()}`;",
    },
  ];

  for (const { name, code } of reintroduced) {
    test(`flags ${name}`, () => {
      const offenders = findPrefixLiterals(code).filter((f) => !f.inHelperCall);
      expect(offenders.length).toBeGreaterThan(0);
    });
  }

  test("does not flag a prefix passed to normalizeId", () => {
    const code = "const id = normalizeId(value, 'PROFILE#');";
    expect(findPrefixLiterals(code).filter((f) => !f.inHelperCall)).toEqual([]);
  });

  test("does not flag a prefix that only appears in a comment", () => {
    const code = [
      "// ownerAccountId already has 'ACCOUNT#' prefix from the profile",
      "/* the ORDER# format is documented in lib/ids.js */",
      "export const x = 1;",
    ].join("\n");
    expect(findPrefixLiterals(code).filter((f) => !f.inHelperCall)).toEqual([]);
  });

  test("does not flag an ACCOUNT# prefix used in a name, not a string", () => {
    const code = "const ACCOUNT_COUNT = 3;";
    expect(findPrefixLiterals(code)).toEqual([]);
  });
});
