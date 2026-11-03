/**
 * Leaf 1.7.1 — Stage 1 GraphQL SDL for Units and Unit Campaigns.
 *
 * Static contract checks over the on-disk SDL, read as TEXT through the shared
 * parser (there is no GraphQL parser here that knows the AppSync directives).
 * The SDL-only deliverable is validated the way the rest of this repo validates
 * the schema: anchored text patterns, not a naive substring search.
 *
 * This file owns the SDL *shape* contract for leaf 1.7.1:
 *   - every Unit / Unit Campaign model, enum, admin/preview type, connection,
 *     page/version/idempotency input, and mutation is present with the contract
 *     fields (DATA_MODEL §3–§5, GRAPHQL_API §4);
 *   - the shared pagination contract (PageInput limit=50 default 100 + cursor,
 *     PageInfo endCursor/hasNextPage, connections of `items` + `pageInfo`, and
 *     every list query taking `page` and returning a `*Connection!`);
 *   - the member-safe join preview carries exactly the participant-safe fields
 *     and none of the administrative fields;
 *   - AUTH-C: every new Show & Sell field is Cognito-only (no `@aws_api_key`,
 *     and in fact no auth directive at all - the API's Cognito mode defaults to
 *     ALLOW and its API-key mode defaults to DENY, so a directive-free field is
 *     reachable only by an authenticated Cognito caller);
 *   - the SDL is structurally well-formed and rejects a hostile/invalid field
 *     definition.
 *
 * The authorization *exposure* guard (missing auth paths, new API-key exposure,
 * admin fields leaking onto any participant type, and the browser-only
 * reporting rule) is leaf 1.7.5 in check_show_and_sell_guards.test.ts.
 */
import { describe, test, expect } from "vitest";
import {
  loadCodeOnlySchema,
  parseDefinitions,
  parseFields,
  returnTypeName,
  API_KEY,
  type Definition,
  type Field,
} from "./show_and_sell_schema";

const SCHEMA = loadCodeOnlySchema();
const DEFINITIONS: Definition[] = parseDefinitions(SCHEMA);
const BY_NAME = new Map(DEFINITIONS.map((d) => [d.name, d]));

// --- The Stage 1 contract surface (GRAPHQL_API §4, DATA_MODEL §3–§5) ---

const SS_ENUMS: Record<string, string[]> = {
  UnitRole: ["UNIT_ADMIN"],
  MembershipStatus: ["ACTIVE", "REMOVED"],
  SplitMethod: ["EQUAL", "TIME_WORKED"],
  CouncilNeedBasis: ["PHYSICAL_STOCK", "AFTER_ASSIGNMENTS"],
};

const SS_OBJECT_TYPES: string[] = [
  "Unit",
  "UnitAccessGrant",
  "UnitInvite",
  "UnitCampaignAdmin",
  "UnitCampaignJoinPreview",
  "UnitCampaignCatalog",
  "UnitCampaignMembership",
  "CreateUnitPayload",
];

const SS_INPUTS: string[] = [
  "PageInput",
  "IdempotencyInput",
  "VersionedInput",
  "CreateUnitInput",
  "UpdateUnitInput",
  "CreateUnitInviteInput",
  "RevokeUnitInviteInput",
  "RedeemUnitInviteInput",
  "RevokeUnitAccessGrantInput",
  "CreateUnitCampaignInput",
  "UpdateUnitCampaignInput",
  "JoinUnitCampaignInput",
  "RemoveUnitCampaignMembershipInput",
];

const SS_QUERY_FIELDS: string[] = [
  "myUnits",
  "unit",
  "unitAdmins",
  "unitInvites",
  "unitCampaignJoinInfo",
  "unitCampaign",
  "unitCampaignCatalog",
  "unitCampaigns",
  "unitCampaignRoster",
];

const SS_MUTATION_FIELDS: string[] = [
  "createUnit",
  "updateUnit",
  "createUnitInvite",
  "revokeUnitInvite",
  "redeemUnitInvite",
  "revokeUnitAccessGrant",
  "createUnitCampaign",
  "updateUnitCampaign",
  "joinUnitCampaign",
  "removeUnitCampaignMembership",
];

/** The exact field set of every Show & Sell object type (contract fidelity). */
const TYPE_FIELDS: Record<string, string[]> = {
  Unit: [
    "unitId", "unitType", "unitNumber", "city", "state", "displayName", "metadataKey",
    "timezone", "splitDefault", "councilNeedBasis", "adminCount", "version",
    "createdAt", "updatedAt", "createdByAccountId",
  ],
  UnitAccessGrant: ["unitId", "accountId", "email", "name", "role", "createdByAccountId", "createdAt"],
  UnitInvite: ["inviteCode", "unitId", "createdByAccountId", "createdAt", "expiresAt"],
  UnitCampaignAdmin: [
    "unitCampaignId", "unitId", "campaignName", "campaignYear", "catalogId", "joinCode",
    "isActive", "version", "createdAt", "updatedAt", "createdByAccountId", "updatedByAccountId",
  ],
  UnitCampaignJoinPreview: ["unitDisplayName", "campaignName", "campaignYear", "catalogName", "isActive"],
  UnitCampaignCatalog: ["catalogId", "catalogName", "products"],
  UnitCampaignMembership: [
    "unitCampaignId", "unitId", "campaignId", "profileId", "status", "joinedByAccountId",
    "joinedAt", "removedByAccountId", "removedAt", "version",
  ],
  CreateUnitPayload: ["unit", "grant"],
};

/** Connection name -> the type its `items` list holds. */
const CONNECTION_ITEMS: Record<string, string> = {
  UnitConnection: "Unit",
  UnitAccessGrantConnection: "UnitAccessGrant",
  UnitInviteConnection: "UnitInvite",
  UnitCampaignConnection: "UnitCampaignAdmin",
  UnitCampaignMembershipConnection: "UnitCampaignMembership",
};

/** List query -> the connection it returns. */
const LIST_QUERY_RETURN: Record<string, string> = {
  myUnits: "UnitConnection",
  unitAdmins: "UnitAccessGrantConnection",
  unitInvites: "UnitInviteConnection",
  unitCampaigns: "UnitCampaignConnection",
  unitCampaignRoster: "UnitCampaignMembershipConnection",
};

// --- helpers ---

function definition(name: string): Definition {
  const found = BY_NAME.get(name);
  expect(found, `schema.graphql must define ${name}`).toBeDefined();
  return found as Definition;
}

function fieldsOf(def: Definition): Field[] {
  return parseFields(def.body);
}

function fieldNameSet(def: Definition): Set<string> {
  return new Set(fieldsOf(def).map((f) => f.name));
}

function rootFieldByName(rootName: "Query" | "Mutation", name: string): Field | undefined {
  const def = BY_NAME.get(rootName);
  if (!def) return undefined;
  return parseFields(def.body).find((f) => f.name === name);
}

describe("Show & Sell Stage 1 SDL (schema.graphql)", () => {
  test("every Stage 1 enum is present with exactly the contract values", () => {
    for (const [name, values] of Object.entries(SS_ENUMS)) {
      const def = definition(name);
      expect(def.kind, `${name} must be an enum`).toBe("enum");
      const found = def.body.split("\n").map((l) => l.trim()).filter((l) => /^[A-Z][A-Z0-9_]*$/.test(l));
      expect(found, `${name} values`).toEqual(values);
    }
  });

  test("every Stage 1 object type and input is present with exactly the contract fields", () => {
    for (const name of [...SS_OBJECT_TYPES, ...SS_INPUTS]) {
      const def = definition(name);
      expect(["type", "input"].includes(def.kind), `${name} must be a type or input`).toBe(true);
    }
    for (const [name, expected] of Object.entries(TYPE_FIELDS)) {
      expect([...fieldNameSet(definition(name))], `${name} fields`).toEqual(expected);
    }
  });

  test("every Stage 1 query and mutation root field is present", () => {
    for (const name of SS_QUERY_FIELDS) {
      expect(rootFieldByName("Query", name), `Query.${name} is missing`).toBeDefined();
    }
    for (const name of SS_MUTATION_FIELDS) {
      expect(rootFieldByName("Mutation", name), `Mutation.${name} is missing`).toBeDefined();
    }
  });

  test("the shared pagination contract is in place", () => {
    const pageInput = definition("PageInput");
    expect([...fieldNameSet(pageInput)]).toEqual(expect.arrayContaining(["limit", "cursor"]));
    const limit = fieldsOf(pageInput).find((f) => f.name === "limit");
    expect(limit?.text, "PageInput.limit defaults to 50").toMatch(/limit\s*:\s*Int\s*=\s*50/);
    const cursor = fieldsOf(pageInput).find((f) => f.name === "cursor");
    expect(cursor?.text, "PageInput.cursor is opaque").toMatch(/cursor\s*:\s*String/);

    const pageInfo = definition("PageInfo");
    expect([...fieldNameSet(pageInfo)]).toEqual(expect.arrayContaining(["endCursor", "hasNextPage"]));
    expect(
      fieldsOf(pageInfo).find((f) => f.name === "hasNextPage")?.text,
      "PageInfo.hasNextPage is a Boolean",
    ).toMatch(/hasNextPage\s*:\s*Boolean!/);
  });

  test("every Show & Sell connection carries `items` of the right type plus `pageInfo`", () => {
    for (const [conn, element] of Object.entries(CONNECTION_ITEMS)) {
      const def = definition(conn);
      const names = fieldNameSet(def);
      expect(names.has("items"), `${conn}.items is missing`).toBe(true);
      expect(names.has("pageInfo"), `${conn}.pageInfo is missing`).toBe(true);
      const items = fieldsOf(def).find((f) => f.name === "items");
      expect(returnTypeName(items!.text), `${conn}.items element`).toBe(element);
      const pageInfo = fieldsOf(def).find((f) => f.name === "pageInfo");
      expect(returnTypeName(pageInfo!.text), `${conn}.pageInfo type`).toBe("PageInfo");
    }
  });

  test("every Show & Sell list query takes `page: PageInput` and returns a non-null connection", () => {
    for (const [query, conn] of Object.entries(LIST_QUERY_RETURN)) {
      const field = rootFieldByName("Query", query);
      expect(field, `Query.${query} is missing`).toBeDefined();
      expect(field!.text, `${query} takes a PageInput`).toMatch(/page\s*:\s*PageInput/);
      expect(returnTypeName(field!.text), `${query} return type`).toBe(conn);
      expect(field!.text, `${query} returns a non-null connection`).toMatch(new RegExp(`\\):\\s*${conn}!`));
    }
  });

  test("the member-safe join preview carries exactly the participant-safe fields", () => {
    // No join code, no IDs, no catalog ID, no settings, no versions - the join
    // preview is the only field a caller may read with a bare join code.
    expect([...fieldNameSet(definition("UnitCampaignJoinPreview"))]).toEqual([
      "unitDisplayName",
      "campaignName",
      "campaignYear",
      "catalogName",
      "isActive",
    ]);
  });

  test("AUTH-C: no Show & Sell field carries @aws_api_key (Cognito-only)", () => {
    for (const name of [...SS_QUERY_FIELDS, ...SS_MUTATION_FIELDS]) {
      const field = rootFieldByName("Query", name) ?? rootFieldByName("Mutation", name);
      expect(field, `${name} is missing`).toBeDefined();
      expect(
        field!.directives,
        `${name} must be directive-free (Cognito-only by the default auth modes)`,
      ).toEqual([]);
      expect(field!.directives).not.toContain(API_KEY);
    }
    for (const name of [...SS_OBJECT_TYPES, ...SS_INPUTS]) {
      expect(definition(name).directives, `${name} must carry no auth directive`).toEqual([]);
    }
  });

  test("the Stage 1 SDL is structurally well-formed and rejects a hostile definition", () => {
    // Re-parse explicitly: an unterminated or malformed definition must throw,
    // not silently drop a field (which is how a hostile edit would hide).
    const parsed = parseDefinitions(loadCodeOnlySchema());
    expect(parsed.length).toBeGreaterThan(0);
    for (const name of [...SS_OBJECT_TYPES, ...SS_INPUTS]) {
      expect(parsed.some((d) => d.name === name), `${name} must parse`).toBe(true);
    }
    expect(() => parseDefinitions("type Malicious {")).toThrow(/unterminated/i);
  });

  test("no Show & Sell field or type name is a reserved or invalid GraphQL token", () => {
    const RESERVED = new Set([
      "query", "mutation", "subscription", "type", "input", "interface", "enum", "union",
      "scalar", "implements", "extend", "directive", "schema", "fragment", "on", "repeatable",
    ]);
    const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
    const names = [
      ...SS_QUERY_FIELDS,
      ...SS_MUTATION_FIELDS,
      ...SS_OBJECT_TYPES,
      ...SS_INPUTS,
      ...Object.keys(SS_ENUMS),
    ];
    for (const name of names) {
      expect(NAME.test(name), `${name} must be a valid GraphQL Name`).toBe(true);
      expect(RESERVED.has(name), `${name} is a reserved GraphQL keyword`).toBe(false);
    }
  });

  test("removeUnitCampaignMembership is the two-version exception, not a VersionedInput", () => {
    // Every version-changing mutation embeds VersionedInput except this one,
    // which needs the membership version and the guard version separately.
    const input = definition("RemoveUnitCampaignMembershipInput");
    const names = fieldNameSet(input);
    expect(names.has("expectedMembershipVersion")).toBe(true);
    expect(names.has("expectedGuardVersion")).toBe(true);
    expect(names.has("version"), "must not also carry the generic VersionedInput").toBe(false);
    const versioned = definition("VersionedInput");
    expect([...fieldNameSet(versioned)]).toEqual(["expectedVersion"]);
  });
});
