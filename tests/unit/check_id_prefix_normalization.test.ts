import { describe, test, expect } from "vitest";
import { readFileSync, readdirSync } from "fs";
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

// #534: every non-test resolver in this directory. The write-permission pair
// (#650) was the pilot; this guard now owns the tree-wide sweep so a
// re-inlined ternary anywhere is caught.
const ALL_RESOLVERS = readdirSync(JS_RESOLVERS_DIR).filter(
  (f) => f.endsWith(".js") && !f.includes(".test."),
);

// The ID prefixes resolvers normalize. Derived from the prefixes the DynamoDB
// tables actually use, plus ORDER: the ORDER#<campaign>#<suffix> order-id
// grammar has a single owner in lib/order_keys.js (buildOrderKey), and both
// minters now route through it (#534), so a re-inlined order key in a resolver
// is caught. SHARE# is deliberately NOT swept: share ids are minted from the
// target account id with no shared helper owning that grammar yet, so sweeping
// it would flag mint sites rather than protect a canonical owner.
const PREFIXES = ["ACCOUNT", "PROFILE", "CATALOG", "CAMPAIGN", "ORDER"];

// Helpers that legitimately own a prefix literal as an argument. Derived from
// the actual exports of lib/ so a new helper is covered without editing this
// list.
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
 * True when a template literal interpolates something other than an autoId()
 * call, i.e. it embeds an id that already exists rather than minting a fresh
 * one. Such a literal builds a grammar (e.g. an ORDER#<campaign>#<suffix>
 * order key) out of a normalized id, so it is a normalization site and the
 * minting exemption must not cover it (#534).
 */
function interpolatesExistingId(raw: string): boolean {
  if (!raw.startsWith("`")) return false;
  return [...raw.matchAll(/\$\{([^}]*)\}/g)].some((m) => !m[1].includes("autoId("));
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
  isMinting: boolean;
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
    const match = new RegExp(`^(${PREFIXES.join("|")})#`).exec(lit.value);
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
      } else if (code[p] === "?" || code[p] === ":") {
        // Operator boundary (ternary / ??): the literal is a sibling operand,
        // not an argument of the call to the left.
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

    // Is this literal minting a brand-new id (e.g. 'CAMPAIGN#' + util.autoId())
    // rather than normalizing an existing one? Minting legitimately owns the
    // prefix literal; only normalization must route through the helper. A
    // template literal that interpolates an id that already exists is not pure
    // minting even when autoId() sits on the same line: the pre-#534 order-id
    // mint interpolated the campaign id, duplicating the grammar that
    // lib/order_keys.js buildOrderKey owns.
    const isMinting = text.includes("autoId(") && !interpolatesExistingId(lit.raw);

    found.push({
      line: source.slice(0, lit.start).split("\n").length,
      prefix: match[1],
      text,
      inHelperCall,
      isMinting,
    });
  }

  return found;
}

describe("ID-prefix normalization has a single owner (#534)", () => {
  for (const name of ALL_RESOLVERS) {
    const source = readFileSync(join(JS_RESOLVERS_DIR, name), "utf8");

    test(`${name} builds every ACCOUNT#/PROFILE# prefix through lib/ids.js`, () => {
      const offenders = findPrefixLiterals(source)
        .filter((f) => !f.inHelperCall && !f.isMinting)
        .map((f) => `line ${f.line}: ${f.text}`);

      expect(
        offenders,
        `${name} still hand-rolls an ID prefix. Route it through ` +
          `normalizeId from lib/ids.js so the normalization rule has one ` +
          `owner:\n  ${offenders.join("\n  ")}`,
      ).toEqual([]);
    });
  }
});

describe("the guard catches the duplication it exists to prevent", () => {
  // The review that prompted this guard re-introduced the exact duplication
  // and every behavioral test stayed green. These cases assert the guard
  // itself fires, so it cannot silently degrade into a no-op.
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
      // The order-id grammar buildOrderKey owns. No autoId() on the line, so
      // the minting exemption does not cover it; a resolver that re-inlines
      // the grammar fails here.
      name: "an inlined ORDER#<campaign>#<suffix> order key",
      code: "const orderId = `ORDER#${campaignIdWithoutPrefix}#${suffix}`;",
    },
    {
      // The shape the #534 sweep replaced: autoId() sits on the line, but the
      // literal also interpolates an existing campaign id, so the minting
      // exemption must not excuse it.
      name: "an ORDER# mint that interpolates an existing campaign id alongside autoId()",
      code:
        "const orderId = `ORDER#${campaignIdWithoutPrefix}#${util.autoId()}`;",
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

  test("does not flag a prefix passed to normalizeIdOrPrefix", () => {
    const code = "const id = normalizeIdOrPrefix(value, 'ACCOUNT#');";
    expect(findPrefixLiterals(code).filter((f) => !f.inHelperCall)).toEqual([]);
  });

  test("treats an ORDER# mint that interpolates an existing campaign id as a normalization site", () => {
    const found = findPrefixLiterals(
      "const orderId = `ORDER#${campaignIdWithoutPrefix}#${util.autoId()}`;",
    );
    expect(found.length).toBe(1);
    expect(found[0].isMinting).toBe(false);
  });

  test("still exempts a fresh id minted by concatenating autoId()", () => {
    const found = findPrefixLiterals("const campaignId = 'CAMPAIGN#' + util.autoId();");
    expect(found.length).toBe(1);
    expect(found[0].isMinting).toBe(true);
  });

  test("does not flag a prefix that only appears in a comment", () => {
    const code = [
      "// ownerAccountId already has 'ACCOUNT#' prefix from the profile",
      "/* the PROFILE# form is documented in lib/ids.js */",
      "export const x = 1;",
    ].join("\n");
    expect(findPrefixLiterals(code).filter((f) => !f.inHelperCall)).toEqual([]);
  });

  test("does not flag an ACCOUNT# prefix used in a name, not a string", () => {
    const code = "const ACCOUNT_COUNT = 3;";
    expect(findPrefixLiterals(code)).toEqual([]);
  });
});
