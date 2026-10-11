import { describe, test, expect } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";
import { fileURLToPath } from "url";

/**
 * Contract guard for the public order API-key surface - the schema half.
 *
 * Harness split (public-orders spec §10.4): the `.tf` half of this contract is
 * pinned in Python by tests/unit/test_public_api_key_surface.py; this file owns
 * the schema-directive half. There is no GraphQL parser in this repo that knows
 * the AppSync directives, so the schema is read as TEXT with anchored patterns -
 * never a naive substring search, because this very schema discusses
 * `@aws_api_key` and `@aws_cognito_user_pools` in comments and field
 * descriptions (and order ids contain `#`), all of which must be blanked before
 * anything is matched.
 *
 * DEFERRED ON PURPOSE: only one thing is. Whether input types genuinely need no
 * directive is still unverified and is asserted nowhere here (the multi-auth
 * spike measured the field/type rules, not the input rule). Everything else the
 * spike left open is now MEASURED and pinned: directive exclusivity (a Cognito
 * caller is refused on an `@aws_api_key`-only field), the converse rule (a
 * no-directive field or type is reachable only through the default Cognito mode),
 * and the rule that marking the ROOT FIELD is not sufficient - a marked root
 * returning an unmarked object type resolves the root but DENIES its sub-fields.
 * The live assertions for the first two live in
 * `tests/integration/resolvers/publicAuthModes.integration.test.ts`; the closure
 * walk below is what makes the third rule enforced statically.
 */

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const SCHEMA_PATH = join(__dirname, "..", "..", "tofu", "application", "schema", "schema.graphql");

const API_KEY = "aws_api_key";
const COGNITO = "aws_cognito_user_pools";

/** The three root fields an API-key caller may invoke. */
const PUBLIC_ROOT_FIELDS = new Set([
  "publicGetOrderOffer",
  "publicCreateOrder",
  "publicGetOrderReceipt",
]);

/**
 * Every object type reachable from a public root field must carry the directive
 * at TYPE level - that is the rule, not a hand-listed count. PublicProduct and
 * PublicLineItem exist precisely because Catalog/Product carry
 * `@aws_cognito_user_pools` and LineItem carries nothing.
 */
const PUBLIC_TYPES = new Set([
  "PublicOrderOffer",
  "PublicProduct",
  "PublicPaymentMethod",
  "PublicLineItem",
  "PublicOrderReceipt",
  "PublicOrderReceiptLookup",
]);

/** Owner-only settings fields: explicit Cognito directive so a future third auth
 * mode cannot silently widen them. */
const OWNER_SETTINGS_FIELDS = new Set([
  "getProfilePublicOrderSettings",
  "updateProfilePublicOrderSettings",
]);

/** Types that must never expose the settings blob or the tokens. */
const PRIVATE_BEARING_TYPES = [
  "Account",
  "SellerProfile",
  "SharedProfile",
  "Order",
  "UnitOrderDetail",
  "UnitSellerSummary",
  "UnitReport",
  "CampaignReport",
];
const NEVER_EXPOSED_FIELDS = [
  "publicOrders",
  "shareToken",
  "publicOrderCount",
  "receiptToken",
];

/** Replaces a matched run with equivalent-length whitespace, newlines intact. */
function blank(match: string): string {
  return match.replace(/[^\n]/g, " ");
}

/**
 * Blanks every block docstring and line comment so directive names that appear
 * in prose cannot be matched, while keeping every real token's position.
 */
function codeOnly(source: string): string {
  return source.replace(/"""[\s\S]*?"""/g, blank).replace(/#[^\n]*/g, "");
}

const SCHEMA = codeOnly(readFileSync(SCHEMA_PATH, "utf8"));

/** Base type name of a field's return type, with `!` and list brackets stripped. */
function returnTypeName(entry: string): string | null {
  const tail = entry.match(/\):\s*([\w![\]]+)/) ?? entry.match(/^ {2}[a-z]\w*:\s*([\w![\]]+)/m);
  if (!tail) {
    return null;
  }
  return tail[1].replace(/[![\]]/g, "");
}

/**
 * Every object type reachable from one public root field, transitively. The
 * measured rule this serves is stricter than it looks: a root field marked
 * `@aws_api_key` that returns an UNMARKED object type resolves the root and then
 * DENIES the sub-fields, so the directive is required on the whole closure.
 */
function reachableTypes(byName: Map<string, Definition>, root: Field): string[] {
  const seen = new Set<string>();
  const queue: string[] = [];
  const first = returnTypeName(root.text);
  if (first) {
    queue.push(first);
  }
  while (queue.length > 0) {
    const name = queue.shift() as string;
    if (seen.has(name)) {
      continue;
    }
    seen.add(name);
    const definition = byName.get(name);
    if (!definition) {
      continue; // a scalar (String, Float, AWSDateTime, ...) or an enum
    }
    for (const field of parseFields(definition.body)) {
      const nested = returnTypeName(field.text);
      if (nested) {
        queue.push(nested);
      }
    }
  }
  return [...seen];
}

type Definition = {
  kind: string;
  name: string;
  directives: string[];
  body: string;
};

type Field = {
  name: string;
  directives: string[];
  /** Raw source of the field entry, so its return type can be recovered. */
  text: string;
};

/**
 * Parses top-level `type` / `input` / `enum` / `interface` definitions: the
 * header is anchored at column 0, and the body runs to the closing brace at
 * column 0 (field arguments use parentheses, so braces never nest in this
 * schema).
 */
function parseDefinitions(source: string): Definition[] {
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

/**
 * Parses the fields of one object definition body. A field entry starts at two
 * spaces of indentation with an identifier followed by `(` or `:`; its closing
 * `): Type! @directive` line starts with `)` and so never starts a new entry.
 */
function parseFields(body: string): Field[] {
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

const DEFINITIONS = parseDefinitions(SCHEMA);
const ROOT_FIELDS = DEFINITIONS.filter((d) => d.name === "Query" || d.name === "Mutation").flatMap(
  (d) => parseFields(d.body),
);

function definition(name: string): Definition {
  const found = DEFINITIONS.find((d) => d.name === name);
  expect(found, `schema.graphql must define ${name}`).toBeDefined();
  return found as Definition;
}

describe("public API key directive surface (schema.graphql)", () => {
  test("exactly the three public root fields carry @aws_api_key", () => {
    const marked = ROOT_FIELDS.filter((f) => f.directives.includes(API_KEY));
    expect(new Set(marked.map((f) => f.name))).toEqual(PUBLIC_ROOT_FIELDS);
    expect(marked).toHaveLength(PUBLIC_ROOT_FIELDS.size);
  });

  test("each public root field carries @aws_api_key and nothing else", () => {
    for (const name of PUBLIC_ROOT_FIELDS) {
      const field = ROOT_FIELDS.find((f) => f.name === name);
      expect(field, `root field ${name} is missing`).toBeDefined();
      expect(field?.directives).toEqual([API_KEY]);
    }
  });

  test("exactly the six public object types carry @aws_api_key at type level", () => {
    const marked = DEFINITIONS.filter((d) => d.directives.includes(API_KEY));
    expect(marked.map((d) => d.name).sort()).toEqual([...PUBLIC_TYPES].sort());
    for (const type of marked) {
      expect(type.kind).toBe("type");
      expect(type.directives).toEqual([API_KEY]);
    }
  });

  test("every object type reachable from a public root field carries @aws_api_key", () => {
    // Measured: a marked root returning an unmarked type resolves the root and
    // DENIES the sub-fields, so the directive is an obligation on the whole
    // closure, not a style preference. A new public field returning Product,
    // LineItem, or any other unmarked type fails here.
    const byName = new Map(DEFINITIONS.map((d) => [d.name, d]));
    for (const name of PUBLIC_ROOT_FIELDS) {
      const root = ROOT_FIELDS.find((f) => f.name === name);
      expect(root, `root field ${name} is missing`).toBeDefined();
      const closure = reachableTypes(byName, root as Field);
      expect(closure.length, `${name} resolves to no named type`).toBeGreaterThan(0);
      for (const typeName of closure) {
        const type = byName.get(typeName);
        if (!type || type.kind !== "type") {
          continue; // scalar or enum: no directive needed
        }
        expect(
          type.directives.includes(API_KEY),
          `${name} reaches ${typeName}, which must carry @aws_api_key`,
        ).toBe(true);
      }
    }
  });

  test("nothing else in the schema carries @aws_api_key", () => {
    const occurrences = [...SCHEMA.matchAll(/@aws_api_key/g)].length;
    // 6 type-level + 3 root fields. A seventh occurrence anywhere - including on
    // an existing type or a new field added later - fails this guard.
    expect(occurrences).toBe(PUBLIC_TYPES.size + PUBLIC_ROOT_FIELDS.size);
  });

  test("the owner-side settings fields carry @aws_cognito_user_pools explicitly", () => {
    for (const name of OWNER_SETTINGS_FIELDS) {
      const field = ROOT_FIELDS.find((f) => f.name === name);
      expect(field, `root field ${name} is missing`).toBeDefined();
      expect(field?.directives).toEqual([COGNITO]);
    }
  });

  test("PublicOrderSettings itself carries no auth directive", () => {
    // It is reachable only from the two Cognito-gated root fields; giving it
    // @aws_api_key would publish the share token to anonymous callers.
    const settings = definition("PublicOrderSettings");
    expect(settings.directives).toEqual([]);
    expect(parseFields(settings.body).flatMap((f) => f.directives)).toEqual([]);
  });

  test("the pre-existing Cognito directive surface is unchanged", () => {
    // #71 posture: only these pre-existing spots name Cognito explicitly. The
    // two settings fields are the only additions; a new @aws_cognito_user_pools
    // elsewhere means someone moved authorization into the schema.
    const markedTypes = DEFINITIONS.filter((d) => d.directives.includes(COGNITO)).map((d) => d.name);
    expect(markedTypes.sort()).toEqual(["Catalog", "Product"]);
    const markedFields = ROOT_FIELDS.filter((f) => f.directives.includes(COGNITO)).map((f) => f.name);
    expect(markedFields.sort()).toEqual(
      [...OWNER_SETTINGS_FIELDS, "getCatalog", "getSharedCampaign", "listManagedCatalogs"].sort(),
    );
  });

  test("no profile, order, or report type exposes the settings blob or a token", () => {
    for (const typeName of PRIVATE_BEARING_TYPES) {
      const type = definition(typeName);
      const fields = new Set(parseFields(type.body).map((f) => f.name));
      for (const forbidden of NEVER_EXPOSED_FIELDS) {
        expect(
          fields.has(forbidden),
          `${typeName}.${forbidden} would hand the capability token to the authenticated audience`,
        ).toBe(false);
      }
    }
  });

  test("the public types are the only ones naming the settings blob fields", () => {
    // PublicOrderSettings is the single owner of shareToken/publicOrderCount.
    const naming = DEFINITIONS.filter((d) =>
      parseFields(d.body).some((f) => NEVER_EXPOSED_FIELDS.includes(f.name)),
    ).map((d) => d.name);
    expect(naming).toEqual(["PublicOrderSettings"]);
  });

  test("the order enums exist and carry no directive", () => {
    // Only object types need a directive; enums and inputs do not.
    for (const name of ["OrderSource", "OrderStatus"]) {
      const enumType = definition(name);
      expect(enumType.kind).toBe("enum");
      expect(enumType.directives).toEqual([]);
    }
    const statuses = [...definition("OrderStatus").body.matchAll(/^ {2}(\w+)/gm)].map((m) => m[1]);
    expect(statuses).toEqual(["NEW", "CONFIRMED"]);
    const sources = [...definition("OrderSource").body.matchAll(/^ {2}(\w+)/gm)].map((m) => m[1]);
    expect(sources).toEqual(["PUBLIC"]);
  });

  test("the Order-side public fields are deliberately absent from this slice", () => {
    // Order.customerEmail/customerFirstName/customerLastName/orderSource/status
    // land with the resolvers that write them, so no input accepts a value
    // nothing honors yet. If one of these appears here, that ordering broke.
    const orderFields = new Set(parseFields(definition("Order").body).map((f) => f.name));
    for (const deferred of ["customerEmail", "customerFirstName", "customerLastName", "orderSource", "status"]) {
      expect(orderFields.has(deferred), `Order.${deferred} must land with its resolver`).toBe(false);
    }
    const updateInput = new Set(parseFields(definition("UpdateOrderInput").body).map((f) => f.name));
    expect(updateInput.has("status")).toBe(false);
  });

  test("the public root fields are declared inside the root types, never via extend", () => {
    // Measured sharp edge: `extend type Query` does NOT merge fields onto the
    // root type on this AppSync + provider combination - the apply succeeds and
    // the added fields are silently dropped. Public root fields must be edited
    // into the existing `type Query` / `type Mutation` blocks.
    expect(SCHEMA).not.toMatch(/^\s*extend\s+type\s+(Query|Mutation)\b/m);
  });

  // GAP - do not fill in with an assumption. The multi-auth spike measured the
  // field and type rules (pinned above and in
  // tests/integration/resolvers/publicAuthModes.integration.test.ts) but NOT the
  // input-type rule, so it stays unpinned until someone verifies it.
  test.skip("input types need no auth directive (still unverified)", () => {});
});
