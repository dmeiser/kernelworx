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
  rootFieldsByName,
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
  // `guardVersion` is part of the contract because the removal write conditions on
  // two rows (the roster row and the Scout Campaign's join guard) and takes both
  // versions from the caller: a roster that answers only one cannot offer the write.
  // The three display fields are what makes a roster actionable: a Scout is picked by
  // name, and `scoutCampaignCatalogId` is the other half of the catalog comparison a
  // door-to-door sale needs (API contract §10.4).
  UnitCampaignMembership: [
    "unitCampaignId", "unitId", "campaignId", "profileId", "scoutName", "campaignName",
    "scoutCampaignCatalogId", "status", "joinedByAccountId", "joinedAt", "removedByAccountId",
    "removedAt", "version", "guardVersion",
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
  // Across ALL definitions of the root, extend blocks included: a field
  // declared only in `extend type Query` is still served.
  return rootFieldsByName(SCHEMA, rootName).find((f) => f.name === name);
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

// --- Stage 2 (§2.1/§2.2): the inventory balance surface -----------------------

/** DATA_MODEL §5.8 movement taxonomy: the closed set, and only those values. */
const SS2_ENUMS: Record<string, string[]> = {
  InventoryMovementType: [
    "RECEIPT",
    "STOCK_ADJUSTMENT",
    "COUNCIL_ON_ORDER_ADJUST",
    "EVENT_ASSIGN",
    "EVENT_MANUAL_REDUCE",
    "EVENT_AUTO_REDUCE",
    "EVENT_IMMEDIATE_SALE",
    "EVENT_RELEASE",
    "EVENT_RETURN_RECONCILE",
    "EVENT_RE_FINALIZE_ADJUST",
    "SCOUT_ISSUE",
    "SCOUT_SALE_CONSUME",
    "SCOUT_RETURN",
    "INDIVIDUAL_FULFILL",
    "WE_OWE_RESERVE",
    "WE_OWE_RELEASE",
    "WE_OWE_FULFILL",
    "REVERSAL",
  ],
};

const SS2_OUTPUT_TYPES: string[] = [
  "InventoryPosition",
  "InventoryMovement",
  "InventoryMovementConnection",
  "InventoryPositionConnection",
  "ScoutCustodyBalance",
  "ScoutCustodyBalanceConnection",
  "IssueStockToScoutPayload",
  "ReturnStockFromScoutPayload",
];

const SS2_INPUT_TYPES: string[] = [
  "DateRangeFilter",
  "RecordInventoryReceiptInput",
  "AdjustInventoryInput",
  "AdjustCouncilOnOrderInput",
  "ProductQuantityInput",
  "IssueStockToScoutInput",
  "ReturnStockFromScoutInput",
];

const SS2_QUERY_FIELDS: string[] = [
  "inventoryPositions",
  "inventoryMovements",
  "scoutCustodyBalances",
  "myScoutCustody",
];

const SS2_MUTATION_FIELDS: string[] = [
  "recordInventoryReceipt",
  "adjustInventory",
  "adjustCouncilOnOrder",
  "issueStockToScout",
  "returnStockFromScout",
];

const SS2_CONNECTION_ITEMS: Record<string, string> = {
  InventoryMovementConnection: "InventoryMovement",
  InventoryPositionConnection: "InventoryPosition",
  ScoutCustodyBalanceConnection: "ScoutCustodyBalance",
};

const SS2_LIST_QUERY_RETURN: Record<string, string> = {
  inventoryMovements: "InventoryMovementConnection",
  scoutCustodyBalances: "ScoutCustodyBalanceConnection",
};

/**
 * The exact field set of each Stage 2 type (GRAPHQL_API §5.1/§5.2, DATA_MODEL
 * §5.7-§5.8, §7). The six derived quantities are part of the contract: a board
 * that re-computes `unassignedKernelQty` in the browser is a second source of
 * truth for what may be sold.
 */
const SS2_TYPE_FIELDS: Record<string, string[]> = {
  InventoryPosition: [
    "unitCampaignId",
    "productId",
    "kernelPhysicalQty",
    "soldInPossessionQty",
    "councilOnOrderQty",
    "version",
    "createdAt",
    "updatedAt",
    "sellableKernelQty",
    "assignedOpenQty",
    "unassignedKernelQty",
    "assignmentOverageQty",
    "withScoutQty",
    "totalUnitOwnedUndeliveredQty",
  ],
  InventoryMovement: [
    "movementId",
    "unitCampaignId",
    "productId",
    "movementType",
    "kernelPhysicalDelta",
    "soldPossessionDelta",
    "withScoutDelta",
    "assignedDelta",
    "councilOnOrderDelta",
    "profileId",
    "showAndSellId",
    "saleId",
    "orderId",
    "weOweId",
    "fulfillmentId",
    "finalizationId",
    "reason",
    "actorAccountId",
    "occurredAt",
    "inventoryVersion",
    "idempotencyKey",
  ],
  InventoryMovementConnection: ["items", "pageInfo"],
  InventoryPositionConnection: ["items", "pageInfo"],
  ScoutCustodyBalance: [
    "unitCampaignId",
    "productId",
    "profileId",
    "campaignId",
    "withScoutQty",
    "version",
    "createdAt",
    "updatedAt",
  ],
  ScoutCustodyBalanceConnection: ["items", "pageInfo", "totalWithScoutQty"],
  IssueStockToScoutPayload: ["inventoryPosition", "custodyBalance"],
  ReturnStockFromScoutPayload: ["inventoryPositions", "custodyBalances"],
  DateRangeFilter: ["startAt", "endAt"],
  RecordInventoryReceiptInput: ["unitCampaignId", "productId", "quantity", "occurredAt", "idempotency"],
  AdjustInventoryInput: ["unitCampaignId", "productId", "quantityDelta", "reason", "occurredAt", "idempotency"],
  AdjustCouncilOnOrderInput: ["unitCampaignId", "productId", "quantityDelta", "reason", "occurredAt", "idempotency"],
  ProductQuantityInput: ["productId", "quantity"],
  IssueStockToScoutInput: ["unitCampaignId", "campaignId", "profileId", "productId", "quantity", "occurredAt", "idempotency"],
  ReturnStockFromScoutInput: ["unitCampaignId", "campaignId", "profileId", "items", "occurredAt", "idempotency"],
};

describe("Show & Sell Stage 2 inventory SDL (schema.graphql)", () => {
  test("the movement type enum carries exactly the DATA_MODEL §5.11 values", () => {
    for (const [name, values] of Object.entries(SS2_ENUMS)) {
      const def = definition(name);
      expect(def.kind, `${name} must be an enum`).toBe("enum");
      const found = def.body.split("\n").map((l) => l.trim()).filter((l) => /^[A-Z][A-Z0-9_]*$/.test(l));
      expect(found, `${name} values`).toEqual(values);
    }
  });

  test("every Stage 2 type and input is present with exactly the contract fields", () => {
    for (const name of [...SS2_OUTPUT_TYPES, ...SS2_INPUT_TYPES]) {
      const def = definition(name);
      expect(["type", "input"].includes(def.kind), `${name} must be a type or input`).toBe(true);
    }
    for (const [name, expected] of Object.entries(SS2_TYPE_FIELDS)) {
      expect([...fieldNameSet(definition(name))], `${name} fields`).toEqual(expected);
    }
  });

  test("every Stage 2 query and mutation root field is present", () => {
    for (const name of SS2_QUERY_FIELDS) {
      expect(rootFieldByName("Query", name), `Query.${name} is missing`).toBeDefined();
    }
    for (const name of SS2_MUTATION_FIELDS) {
      expect(rootFieldByName("Mutation", name), `Mutation.${name} is missing`).toBeDefined();
    }
  });

  test("the Stage 2 connections and list query keep the shared pagination contract", () => {
    const positions = rootFieldByName("Query", "inventoryPositions")!;
    for (const [conn, element] of Object.entries(SS2_CONNECTION_ITEMS)) {
      const def = definition(conn);
      const items = fieldsOf(def).find((f) => f.name === "items");
      expect(returnTypeName(items!.text), `${conn}.items element`).toBe(element);
      const pageInfo = fieldsOf(def).find((f) => f.name === "pageInfo");
      expect(returnTypeName(pageInfo!.text), `${conn}.pageInfo type`).toBe("PageInfo");
    }
    for (const [query, conn] of Object.entries(SS2_LIST_QUERY_RETURN)) {
      const field = rootFieldByName("Query", query)!;
      expect(field.text, `${query} takes a PageInput`).toMatch(/page\s*:\s*PageInput/);
      expect(returnTypeName(field.text), `${query} return type`).toBe(conn);
      expect(field.text, `${query} returns a non-null connection`).toMatch(new RegExp(`\\):\\s*${conn}!`));
    }
    // `inventoryPositions` is a bounded read of one campaign's rows, so it is a
    // connection too: a Pack with hundreds of catalog products has no unbounded
    // list to hand a browser.
    expect(positions.text).toMatch(/page\s*:\s*PageInput/);
    expect(returnTypeName(positions.text)).toBe("InventoryPositionConnection");
    // A range that has not ended yet is open-ended, and the whole window is
    // optional, so both instants are nullable.
    const range = fieldsOf(definition("DateRangeFilter"));
    expect(range.find((f) => f.name === "startAt")!.text).toMatch(/startAt\s*:\s*AWSDateTime(?!!)/);
    expect(range.find((f) => f.name === "endAt")!.text).toMatch(/endAt\s*:\s*AWSDateTime(?!!)/);
    // Every history filter of GRAPHQL_API §5.1 has to exist, or the browser has
    // no way to ask for one event's or one Scout's movements.
    const movements = rootFieldByName("Query", "inventoryMovements")!;
    for (const arg of ["unitCampaignId: ID!", "productId: ID", "movementType: InventoryMovementType", "showAndSellId: ID", "profileId: ID", "dateRange: DateRangeFilter", "page: PageInput"]) {
      expect(movements.text, `inventoryMovements(${arg}) is missing`).toContain(arg);
    }
    expect(positions.text).toContain("productIds: [ID!]");
  });

  test("every Stage 2 mutation is idempotent and carries no client version", () => {
    for (const name of SS2_MUTATION_FIELDS) {
      const field = rootFieldByName("Mutation", name)!;
      expect(field.text, `${name} takes its input`).toMatch(/input\s*:\s*\w+Input!/);
    }
    // §5.2: "Balance versions are server-managed and returned for subsequent
    // retry/verification" - a caller that could send an expectedVersion would be
    // asserting a number it cannot have read atomically with its write.
    for (const name of ["RecordInventoryReceiptInput", "AdjustInventoryInput", "AdjustCouncilOnOrderInput", "IssueStockToScoutInput", "ReturnStockFromScoutInput"]) {
      const input = definition(name);
      const idem = fieldsOf(input).find((f) => f.name === "idempotency");
      expect(idem!.text, `${name}.idempotency is required`).toMatch(/idempotency\s*:\s*IdempotencyInput!/);
      expect(fieldNameSet(input).has("version"), `${name} must not carry a version`).toBe(false);
      expect(fieldNameSet(input).has("movementType"), `${name} must not choose the movement type`).toBe(false);
    }
    const receipt = fieldsOf(definition("RecordInventoryReceiptInput"));
    expect(receipt.find((f) => f.name === "quantity")!.text).toMatch(/quantity\s*:\s*Int!/);
    expect(receipt.some((f) => f.name === "reason"), "a receipt needs no reason").toBe(false);
    const adjust = fieldsOf(definition("AdjustInventoryInput"));
    expect(adjust.find((f) => f.name === "quantityDelta")!.text).toMatch(/quantityDelta\s*:\s*Int!/);
    expect(adjust.find((f) => f.name === "reason")!.text, "a stock adjustment must be explained").toMatch(/reason\s*:\s*String!/);
    const council = fieldsOf(definition("AdjustCouncilOnOrderInput"));
    expect(council.find((f) => f.name === "reason")!.text, "an on-order note is optional").toMatch(/reason\s*:\s*String(?!!)/);
  });

  test("the Scout custody reads and writes keep the §2.3.3 and §5.9 contract", () => {
    // CUST-02: the inventory board shows With Scout per Scout and in aggregate, and the
    // aggregate covers the whole filtered set, so it travels on the connection.
    const connection = fieldsOf(definition("ScoutCustodyBalanceConnection"));
    expect(connection.find((f) => f.name === "totalWithScoutQty")!.text).toMatch(/totalWithScoutQty\s*:\s*Int!/);
    const custodyRead = rootFieldByName("Query", "scoutCustodyBalances")!;
    for (const arg of ["unitCampaignId: ID!", "profileId: ID", "productId: ID", "page: PageInput"]) {
      expect(custodyRead.text, `scoutCustodyBalances(${arg}) is missing`).toContain(arg);
    }

    // §5.1: the participant read is one Scout's own rows in one campaign, so it is
    // addressed by both ids and is not a paged list.
    const mine = rootFieldByName("Query", "myScoutCustody")!;
    for (const arg of ["profileId: ID!", "unitCampaignId: ID!"]) {
      expect(mine.text, `myScoutCustody(${arg}) is missing`).toContain(arg);
    }
    expect(mine.text, "myScoutCustody is not a paged list").not.toMatch(/page\s*:\s*PageInput/);
    expect(mine.text).toMatch(/\):\s*\[ScoutCustodyBalance!\]!/);

    // DATA_MODEL §5.9: the custody row is stock, not audit. The same projection answers
    // the admin board and the Scout, so it carries no actor, reason, or owner field —
    // INV-Q-05 refuses a participant custody read any part of the audit trail.
    const custody = fieldsOf(definition("ScoutCustodyBalance"));
    for (const forbidden of ["actorAccountId", "reason", "ownerAccountId", "email", "name", "idempotencyKey"]) {
      expect(custody.some((f) => f.name === forbidden), `ScoutCustodyBalance.${forbidden} would leak`).toBe(false);
    }
    expect(custody.find((f) => f.name === "withScoutQty")!.text).toMatch(/withScoutQty\s*:\s*Int!/);

    // §2.3.2: a return is one atomic batch over distinct products, so its input names a
    // list of product/quantity pairs; §2.3.1 issues one product at a time.
    const batch = fieldsOf(definition("ReturnStockFromScoutInput"));
    expect(batch.find((f) => f.name === "items")!.text).toMatch(/items\s*:\s*\[ProductQuantityInput!\]!/);
    const pair = fieldsOf(definition("ProductQuantityInput"));
    expect([...fieldNameSet(definition("ProductQuantityInput"))]).toEqual(["productId", "quantity"]);
    expect(pair.find((f) => f.name === "quantity")!.text).toMatch(/quantity\s*:\s*Int!/);
    // Both writes name the roster identity as a profile/Campaign pair, so a request
    // cannot re-point an existing custody row at another Scout Campaign.
    for (const name of ["IssueStockToScoutInput", "ReturnStockFromScoutInput"]) {
      const input = fieldsOf(definition(name));
      expect(input.some((f) => f.name === "campaignId"), `${name}.campaignId`).toBe(true);
      expect(input.some((f) => f.name === "profileId"), `${name}.profileId`).toBe(true);
    }
    // The payload is the pair of balances that moved, never a recomputed board.
    const issuePayload = fieldsOf(definition("IssueStockToScoutPayload"));
    expect(returnTypeName(issuePayload.find((f) => f.name === "inventoryPosition")!.text)).toBe("InventoryPosition");
    expect(returnTypeName(issuePayload.find((f) => f.name === "custodyBalance")!.text)).toBe("ScoutCustodyBalance");
    const returnPayload = fieldsOf(definition("ReturnStockFromScoutPayload"));
    expect(returnPayload.find((f) => f.name === "inventoryPositions")!.text).toMatch(/:\s*\[InventoryPosition!\]!/);
    expect(returnPayload.find((f) => f.name === "custodyBalances")!.text).toMatch(/:\s*\[ScoutCustodyBalance!\]!/);
  });

  test("AUTH: no Stage 2 field or type carries an auth directive (Cognito-only)", () => {
    for (const name of [...SS2_QUERY_FIELDS, ...SS2_MUTATION_FIELDS]) {
      const field = rootFieldByName("Query", name) ?? rootFieldByName("Mutation", name);
      expect(field, `${name} is missing`).toBeDefined();
      expect(field!.directives, `${name} must be directive-free`).toEqual([]);
      expect(field!.directives).not.toContain(API_KEY);
    }
    for (const name of [...SS2_OUTPUT_TYPES, ...SS2_INPUT_TYPES]) {
      expect(definition(name).directives, `${name} must carry no auth directive`).toEqual([]);
    }
  });

  test("no Stage 2 type or field name is a reserved or invalid GraphQL token", () => {
    const RESERVED = new Set([
      "query", "mutation", "subscription", "type", "input", "interface", "enum", "union",
      "scalar", "implements", "extend", "directive", "schema", "fragment", "on", "repeatable",
    ]);
    const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
    const names = [
      ...SS2_QUERY_FIELDS,
      ...SS2_MUTATION_FIELDS,
      ...SS2_OUTPUT_TYPES,
      ...SS2_INPUT_TYPES,
      ...Object.keys(SS2_ENUMS),
    ];
    for (const name of names) {
      expect(NAME.test(name), `${name} must be a valid GraphQL Name`).toBe(true);
      expect(RESERVED.has(name), `${name} is a reserved GraphQL keyword`).toBe(false);
    }
  });
});

// --- Stage 3 wave 3 (§5.19/§10.2): the Order fulfillment history ---------------

/**
 * DATA_MODEL §5.19 fulfillment taxonomy: closed sets, and only those values.
 * The SDL prefixes the enum names with `Order` so they cannot collide with a
 * later Show-and-Sell sale-level fulfillment concept.
 */
const SS3_ENUMS: Record<string, string[]> = {
  OrderFulfillmentSource: ["KERNEL_STOCK", "SCOUT_CUSTODY", "EXTERNAL_COUNCIL"],
  OrderFulfillmentRecordType: ["FULFILL", "REVERSAL"],
};

/**
 * The two projections of one append-only row. `OrderFulfillment` is the full
 * administrative audit (actor account + inventory movement id) reachable only
 * through the §2.4.5 `orderFulfillments` Unit-Admin query;
 * `ParticipantOrderFulfillment` is what `Order.fulfillments` answers to every
 * caller and must never carry either audit field (§10.2).
 */
const SS3_TYPE_FIELDS: Record<string, string[]> = {
  OrderFulfillment: [
    "fulfillmentId",
    "orderId",
    "campaignId",
    "profileId",
    "unitId",
    "unitCampaignId",
    "lineItemId",
    "productId",
    "recordType",
    "quantity",
    "source",
    "inventoryMovementId",
    "reversalOfFulfillmentId",
    "actorAccountId",
    "createdAt",
  ],
  ParticipantOrderFulfillment: [
    "fulfillmentId",
    "lineItemId",
    "productId",
    "recordType",
    "quantity",
    "source",
    "reversalOfFulfillmentId",
    "createdAt",
  ],
  FulfillIndividualOrderLinePayload: ["order", "fulfillment", "inventoryPosition"],
  ReverseIndividualOrderFulfillmentPayload: ["order", "reversal", "inventoryPosition"],
  OrderFulfillmentConnection: ["items", "pageInfo"],
  // FUNC-5: the participant's own history is paginated on the participant's own field,
  // so a long history is reachable in full without the Unit-Admin audit.
  ParticipantOrderFulfillmentConnection: ["items", "pageInfo"],
  // §2.6.3: the Order projection a Unit Admin fulfills from. It is deliberately narrower
  // than the legacy `Order` type — no phone, address, notes, payment method, or amount —
  // because administering stock needs the Order's identity, its origin scope, and its
  // lines, and a projection that carries nothing cannot disclose the difference.
  UnitOrder: [
    "orderId",
    "profileId",
    "campaignId",
    "unitId",
    "unitCampaignId",
    "customerName",
    "orderDate",
    "fulfillmentVersion",
    "lineItems",
  ],
  UnitOrderLine: ["lineItemId", "productId", "productName", "quantity", "fulfilledQuantity"],
  UnitOrderConnection: ["items", "pageInfo"],
};

/**
 * The §2.4.3/§2.4.4 inputs. Neither carries a Unit id, a campaign id, a profile
 * id, a product id, or a price: §5.19 makes the Order row itself the source of
 * the immutable originating scope and of the product the line sells, so a caller
 * that could name them could draw stock from a Unit the Order never belonged to.
 */
const SS3_INPUT_FIELDS: Record<string, string[]> = {
  FulfillIndividualOrderLineInput: ["orderId", "lineItemId", "quantity", "source", "expectedFulfillmentVersion", "idempotency"],
  ReverseIndividualOrderFulfillmentInput: ["orderId", "fulfillmentId", "expectedFulfillmentVersion", "idempotency"],
};

const SS3_MUTATION_FIELDS: string[] = ["fulfillIndividualOrderLine", "reverseIndividualOrderFulfillment"];

// §2.4.2 extends the EXISTING createOrder rather than adding a second order mutation, so
// the mode enum and the two new input fields are pinned against the input's full field
// set: a mode that could be spelled any of four ways, or a key the resolver could not
// echo back, both make a retried sale consume custody twice.
const SS3_MODE_ENUM = "OrderFulfillmentMode";
const SS3_MODE_VALUES: string[] = ["NONE", "CONSUME_SCOUT_CUSTODY"];
const SS3_CREATE_ORDER_NEW_FIELDS: string[] = ["fulfillmentMode", "idempotencyKey"];

describe("Show & Sell Stage 3 order-fulfillment SDL (schema.graphql)", () => {
  test("the two fulfillment enums carry exactly the DATA_MODEL §5.19 values", () => {
    for (const [name, values] of Object.entries(SS3_ENUMS)) {
      const def = definition(name);
      expect(def.kind, `${name} must be an enum`).toBe("enum");
      const found = def.body.split("\n").map((l) => l.trim()).filter((l) => /^[A-Z][A-Z0-9_]*$/.test(l));
      expect(found, `${name} values`).toEqual(values);
    }
  });

  test("OrderFulfillment is the full audit and ParticipantOrderFulfillment the projection", () => {
    for (const [name, expected] of Object.entries(SS3_TYPE_FIELDS)) {
      expect([...fieldNameSet(definition(name))], `${name} fields`).toEqual(expected);
    }
    // The audit fields exist exactly once: on the admin type.
    for (const audit of ["actorAccountId", "inventoryMovementId"]) {
      expect(fieldNameSet(definition("OrderFulfillment")).has(audit), `OrderFulfillment.${audit} is the audit`).toBe(true);
    }
  });

  test("the participant projection never carries either administrative audit field (§10.2)", () => {
    // INV-Q/output separation: a Scout reading `Order.fulfillments` sees the
    // custody/quantity history of their own Order, never who recorded it or
    // which inventory movement moved stock.
    const participant = fieldNameSet(definition("ParticipantOrderFulfillment"));
    for (const forbidden of ["actorAccountId", "inventoryMovementId"]) {
      expect(participant.has(forbidden), `ParticipantOrderFulfillment.${forbidden} would leak the audit`).toBe(false);
    }
  });

  test("Order.fulfillments answers a paginated page of the participant projection, not the audit type", () => {
    const field = fieldsOf(definition("Order")).find((f) => f.name === "fulfillments");
    expect(field, "Order.fulfillments is missing").toBeDefined();
    expect(returnTypeName(field!.text), "Order.fulfillments page type").toBe("ParticipantOrderFulfillmentConnection");
    // FUNC-5 (re-review): the field takes the shared PageInput and returns a page with a
    // cursor. A plain list can only ever show one page, and the only way to see the
    // omitted tail would then be the Unit-Admin `orderFulfillments` audit — a surface a
    // participant cannot query, so her own Order's history would be partly unreachable
    // to her.
    expect(field!.text, "Order.fulfillments takes the shared PageInput").toMatch(/page\s*:\s*PageInput/);
    expect(field!.text, "Order.fulfillments is a non-null connection").toMatch(/\)\s*:\s*ParticipantOrderFulfillmentConnection!/);

    const connection = definition("ParticipantOrderFulfillmentConnection");
    expect(connection.kind, "the page is a type").toBe("type");
    const items = fieldsOf(connection).find((f) => f.name === "items");
    expect(items, "the page carries items").toBeDefined();
    // The item type is still the projection: pagination must not widen what a participant
    // may read, so the audit fields stay behind the admin query (§10.2).
    expect(returnTypeName(items!.text), "ParticipantOrderFulfillmentConnection.items element type").toBe("ParticipantOrderFulfillment");
    expect(items!.text, "items is [ParticipantOrderFulfillment!]!").toMatch(/items\s*:\s*\[ParticipantOrderFulfillment!\]!/);
    expect(fieldNameSet(connection).has("pageInfo"), "the page carries a cursor for the next page").toBe(true);
    expect(connection.body, "pageInfo is the shared PageInfo type").toMatch(/pageInfo\s*:\s*PageInfo!/);
  });

  test("§2.4.3/§2.4.4: the inputs carry exactly the fields a caller may choose", () => {
    for (const [name, fields] of Object.entries(SS3_INPUT_FIELDS)) {
      expect(fieldNameSet(definition(name)), `${name} field set`).toEqual(new Set(fields));
    }
    for (const name of SS3_MUTATION_FIELDS) {
      const field = rootFieldByName("Mutation", name)!;
      expect(field.text, `${name} takes its input`).toMatch(/input\s*:\s*\w+Input!/);
      expect(returnTypeName(field.text), `${name} return type`).toMatch(/Payload$/);
      expect(field.text, `${name} returns a non-null payload`).toMatch(/\):\s*\w+Payload!/);
    }
  });

  test("§2.4.3/§2.4.4: nothing the server derives is a caller argument", () => {
    // No unitId, unitCampaignId, campaignId, profileId or productId: the Order row's own
    // immutable origin scope decides both whose admin may act and whose stock is drawn
    // (AUTH-U), and the line names the product it sells.
    for (const name of Object.keys(SS3_INPUT_FIELDS)) {
      const input = fieldNameSet(definition(name));
      for (const forbidden of ["unitId", "unitCampaignId", "campaignId", "profileId", "productId", "pricePerUnit"]) {
        expect(input.has(forbidden), `${name}.${forbidden} would let the caller choose the scope`).toBe(false);
      }
      const idem = fieldsOf(definition(name)).find((f) => f.name === "idempotency");
      expect(idem!.text, `${name}.idempotency is required`).toMatch(/idempotency\s*:\s*IdempotencyInput!/);
      const version = fieldsOf(definition(name)).find((f) => f.name === "expectedFulfillmentVersion");
      expect(version!.text, `${name}.expectedFulfillmentVersion is required`).toMatch(/expectedFulfillmentVersion\s*:\s*Int!/);
    }
    // The source is the Kernel's choice when fulfilling and the record's fact when
    // reversing: a reversal that took a source argument could restore stock the
    // fulfillment never consumed (§2.4.4, AC-06).
    const fulfill = fieldsOf(definition("FulfillIndividualOrderLineInput"));
    expect(fulfill.find((f) => f.name === "source")!.text).toMatch(/source\s*:\s*OrderFulfillmentSource!/);
    expect(fulfill.find((f) => f.name === "quantity")!.text).toMatch(/quantity\s*:\s*Int!/);
    const reversal = fieldNameSet(definition("ReverseIndividualOrderFulfillmentInput"));
    expect(reversal.has("source"), "a reversal inherits its source").toBe(false);
    expect(reversal.has("quantity"), "a reversal inherits its quantity").toBe(false);
  });

  test("§2.4.3/§2.4.4: the payload answers the Order, the record, and a position only when stock moved", () => {
    for (const [payload, record] of [["FulfillIndividualOrderLinePayload", "fulfillment"], ["ReverseIndividualOrderFulfillmentPayload", "reversal"]]) {
      const order = fieldsOf(definition(payload)).find((f) => f.name === "order");
      expect(returnTypeName(order!.text), `${payload}.order`).toBe("Order");
      expect(order!.text, `${payload}.order is non-null`).toMatch(/order\s*:\s*Order!/);
      const row = fieldsOf(definition(payload)).find((f) => f.name === record);
      expect(returnTypeName(row!.text), `${payload}.${record}`).toBe("OrderFulfillment");
      expect(row!.text, `${payload}.${record} is non-null`).toMatch(new RegExp(`${record}:\\s*OrderFulfillment!`));
      // Nullable, and absent exactly when no Kernel balance moved: an external-Council
      // fulfillment that answered a position would read as though stock had left it.
      const position = fieldsOf(definition(payload)).find((f) => f.name === "inventoryPosition");
      expect(returnTypeName(position!.text), `${payload}.inventoryPosition`).toBe("InventoryPosition");
      expect(position!.text, `${payload}.inventoryPosition is nullable`).toMatch(/inventoryPosition\s*:\s*InventoryPosition\s*$/);
    }
  });

  test("§2.4.5: orderFulfillments is a paged read of the full audit type", () => {
    const field = rootFieldByName("Query", "orderFulfillments")!;
    expect(field.text, "orderFulfillments takes orderId").toMatch(/orderId\s*:\s*ID!/);
    expect(field.text, "orderFulfillments takes a PageInput").toMatch(/page\s*:\s*PageInput/);
    expect(returnTypeName(field.text), "orderFulfillments return type").toBe("OrderFulfillmentConnection");
    expect(field.text, "orderFulfillments returns a non-null connection").toMatch(/\):\s*OrderFulfillmentConnection!/);
    const items = fieldsOf(definition("OrderFulfillmentConnection")).find((f) => f.name === "items");
    expect(returnTypeName(items!.text), "the audit page is the full audit type").toBe("OrderFulfillment");
    expect(items!.text, "items is [OrderFulfillment!]!").toMatch(/items\s*:\s*\[OrderFulfillment!\]!/);
    // The participant projection is never a connection element: the audit fields belong
    // to the Unit-Admin query alone, and `Order.fulfillments` stays the only answer
    // every caller gets (§10.2).
    expect(items!.text, "the audit page carries no participant projection").not.toMatch(/Participant/);
  });

  test("§2.4.2: createOrder gains the custody mode and its key, and nothing else (§10.1)", () => {
    const mode = definition(SS3_MODE_ENUM);
    expect(mode.kind, `${SS3_MODE_ENUM} must be an enum`).toBe("enum");
    const found = mode.body.split("\n").map((l) => l.trim()).filter((l) => /^[A-Z][A-Z0-9_]*$/.test(l));
    expect(found, `${SS3_MODE_ENUM} values`).toEqual(SS3_MODE_VALUES);

    const input = definition("CreateOrderInput");
    const fields = fieldsOf(input);
    const names = fieldNameSet(input);
    for (const name of SS3_CREATE_ORDER_NEW_FIELDS) {
      expect(names.has(name), `CreateOrderInput.${name} is missing`).toBe(true);
      // Both optional: an absent mode is NONE, which is every Order this pipeline wrote
      // before Wave 3, and a NONE order needs no key because it moves no stock.
      const field = fields.find((f) => f.name === name)!;
      expect(field.text, `${name} is optional`).not.toMatch(/:\s*\w+!\s*$/);
    }
    expect(fields.find((f) => f.name === "fulfillmentMode")!.text).toMatch(/fulfillmentMode\s*:\s*OrderFulfillmentMode/);
    expect(fields.find((f) => f.name === "idempotencyKey")!.text).toMatch(/idempotencyKey\s*:\s*String/);

    // The mode is the only new decision the caller makes. Nothing here lets a caller name
    // the scope the sale consumes from, the amount it consumes, or the Scout: the guard
    // read answers whose campaign this is and min(ordered, available) decides the rest.
    for (const forbidden of ["unitId", "unitCampaignId", "consumedQuantity", "source", "expectedVersion"]) {
      expect(names.has(forbidden), `CreateOrderInput.${forbidden} would let the caller choose it`).toBe(false);
    }

    // createOrder keeps its existing shape: one input, the Order payload it had. A second
    // custody mutation would be a second order write owner, and §2.4 names one.
    const mutation = rootFieldByName("Mutation", "createOrder")!;
    expect(mutation.text, "createOrder takes CreateOrderInput").toMatch(/input\s*:\s*CreateOrderInput!/);
    expect(returnTypeName(mutation.text), "createOrder still answers the Order it wrote").toBe("Order");
  });

  test("§2.6.3: the Order list a Unit Admin fulfills from is its own read, and a narrow one", () => {
    // FUNC-1: the legacy `listOrdersByCampaign`/`getOrder` pipelines authorize Profile
    // ownership and READ shares, so the admin who owes the stock those Orders sold reads
    // nothing through them. The fulfillment screen reads Orders whose authorization is the
    // Order's immutable Unit origin — the same scope §2.4.3 and §2.4.4 demand.
    const field = rootFieldByName("Query", "unitScoutCampaignOrders");
    expect(field, "Query.unitScoutCampaignOrders is missing").toBeDefined();
    expect(field!.text, "the read names the Unit Campaign whose admin is asking").toMatch(/unitCampaignId\s*:\s*ID!/);
    expect(field!.text, "the read names the Scout Campaign the Orders were placed under").toMatch(/campaignId\s*:\s*ID!/);
    expect(field!.text, "the read takes the shared PageInput").toMatch(/page\s*:\s*PageInput/);
    expect(returnTypeName(field!.text), "the read answers a page of Orders").toBe("UnitOrderConnection");
    expect(field!.text, "the read returns a non-null connection").toMatch(/\)\s*:\s*UnitOrderConnection!/);

    const connection = definition("UnitOrderConnection");
    const items = fieldsOf(connection).find((f) => f.name === "items");
    expect(returnTypeName(items!.text), "UnitOrderConnection.items element type").toBe("UnitOrder");
    expect(connection.body, "pageInfo is the shared PageInfo type").toMatch(/pageInfo\s*:\s*PageInfo!/);

    // The projection is what a fulfillment write needs and nothing else. The legacy `Order`
    // type can carry the customer's contact details; this one cannot, so the fulfillment
    // screen has nothing to disclose from them.
    const order = fieldNameSet(definition("UnitOrder"));
    for (const forbidden of ["customerPhone", "phone", "address", "notes", "paymentMethod", "totalAmount", "status", "createdAt"]) {
      expect(order.has(forbidden), `UnitOrder.${forbidden} is not part of administering stock`).toBe(false);
    }
    for (const needed of ["orderId", "unitId", "unitCampaignId", "fulfillmentVersion", "lineItems"]) {
      expect(order.has(needed), `UnitOrder.${needed} is what the next fulfillment carries`).toBe(true);
    }
    const line = fieldNameSet(definition("UnitOrderLine"));
    for (const needed of ["lineItemId", "productId", "quantity", "fulfilledQuantity"]) {
      expect(line.has(needed), `UnitOrderLine.${needed} is what a fulfillment names`).toBe(true);
    }
    for (const forbidden of ["pricePerUnit", "subtotal"]) {
      expect(line.has(forbidden), `UnitOrderLine.${forbidden} is money this wave does not touch`).toBe(false);
    }

    // `lineItemId` and `fulfilledQuantity` are nullable in exactly one direction: a line
    // written before Wave 3 has no identity to name, and the screen withholds the control
    // rather than guessing the line from its position.
    const lineItemId = fieldsOf(definition("UnitOrderLine")).find((f) => f.name === "lineItemId");
    expect(lineItemId!.text, "a pre-Wave-3 line answers no identity").not.toMatch(/lineItemId\s*:\s*ID!/);
    expect(lineItemId!.text, "the line identity is the field a fulfillment names").toMatch(/lineItemId\s*:\s*ID/);
  });

  test("AUTH: no Stage 3 fulfillment type, input, enum, or field carries an auth directive", () => {
    for (const name of [...Object.keys(SS3_TYPE_FIELDS), ...Object.keys(SS3_INPUT_FIELDS), ...Object.keys(SS3_ENUMS), SS3_MODE_ENUM]) {
      expect(definition(name).directives, `${name} must carry no auth directive`).toEqual([]);
    }
    for (const name of [...SS3_MUTATION_FIELDS, "orderFulfillments", "unitScoutCampaignOrders"]) {
      const field = rootFieldByName("Mutation", name) ?? rootFieldByName("Query", name);
      expect(field, `${name} is missing`).toBeDefined();
      expect(field!.directives, `${name} must be directive-free`).toEqual([]);
    }
  });
});

// --- Stage 3.1 (Wave 4.1, §3.1): the event aggregate surface --------------------

/**
 * DATA_MODEL §5.10-§5.13 and GRAPHQL_API §6 for the four §3.1 reads and three
 * §3.1 writes. The event state enum is the whole point of this leaf: three of its
 * values are derived from the immutable interval and three are written by a
 * workflow, so the closed set is what keeps "ENDED" from being stored and later
 * re-opened into "ACTIVE" by a second writer.
 */
const SS31_ENUMS: Record<string, string[]> = {
  ShowAndSellStatus: ["SCHEDULED", "ACTIVE", "ENDED", "CANCELLED", "FINALIZED", "REOPENED"],
};

const SS31_QUERY_FIELDS: string[] = [
  "showAndSell",
  "showAndSells",
  "unitCampaignOpportunities",
  "showAndSellOpportunity",
];

const SS31_MUTATION_FIELDS: string[] = ["createShowAndSell", "updateShowAndSell", "cancelShowAndSell"];

const SS31_INPUTS: string[] = ["CreateShowAndSellInput", "UpdateShowAndSellInput", "CancelShowAndSellInput"];

/** Connection name -> the type its `items` list holds. */
const SS31_CONNECTION_ITEMS: Record<string, string> = {
  ShowAndSellAdminConnection: "ShowAndSellAdmin",
  ShowAndSellOpportunityConnection: "ShowAndSellOpportunity",
};

const SS31_OUTPUT_TYPES: string[] = [
  "ShowAndSellAdmin",
  "ShowAndSellAdminConnection",
  "ShowAndSellOpportunity",
  "ShowAndSellOpportunitySlot",
  "ParticipantSignup",
  "ShowAndSellOpportunityConnection",
  "CancelShowAndSellPayload",
];

/**
 * The exact field set of each §3.1 type, in declaration order.
 *
 * `ShowAndSellAdmin` is the administrative projection: the ten settings, the
 * products the event has ever held, its allocations and slots read through the
 * event's own partition, the finalization pointers, and the full audit of who
 * wrote what. `ShowAndSellOpportunity`, `ShowAndSellOpportunitySlot` and
 * `ParticipantSignup` are the participant projections (SEC-04), and the
 * difference between the two spellings of the same row is the deliverable: the
 * participant type names no inventory, sale, buyer, cash, finalization, actor, or
 * tenancy field, and reports the version a signup conditions on as `eventVersion`
 * rather than as the row's own `version`.
 */
const SS31_TYPE_FIELDS: Record<string, string[]> = {
  ShowAndSellAdmin: [
    "showAndSellId", "unitId", "unitCampaignId", "locationName", "address", "startAt", "endAt",
    "status", "splitMethod", "weOweEnabled", "productIds", "allocations", "slots",
    "approvedFinalizationId", "latestFinalizationId", "version", "createdAt", "updatedAt",
    "createdByAccountId", "updatedByAccountId", "cancelledByAccountId", "cancelledAt",
    "cancellationReason",
  ],
  ShowAndSellAdminConnection: ["items", "pageInfo"],
  ShowAndSellOpportunity: [
    "showAndSellId", "locationName", "address", "startAt", "endAt", "status", "splitMethod",
    "weOweEnabled", "timezone", "eventVersion", "slots", "mySignups",
  ],
  ShowAndSellOpportunitySlot: ["slotId", "label", "startAt", "endAt", "capacity", "openCapacity"],
  ParticipantSignup: ["showAndSellId", "slotId", "startAt", "endAt", "status", "actualMinutes"],
  ShowAndSellOpportunityConnection: ["items", "pageInfo"],
  CancelShowAndSellPayload: ["event", "releasedAllocations", "cancelledSignups"],
  // §5.11-§5.13 rows as §3.1 reads them. The allocation is addressed by the campaign
  // product pair it competes with and names its own event, because the overlap rule is
  // evaluated per product per instant, not per event.
  ShowAndSellAllocation: [
    "unitCampaignId", "productId", "showAndSellId", "startAt", "endAt", "status", "allocatedQty",
    "soldQty", "releasedQty", "remainingQty", "version", "createdAt", "updatedAt",
  ],
  ShowAndSellSlot: [
    "showAndSellId", "slotId", "label", "startAt", "endAt", "capacity", "activeSignupCount",
    "version", "createdAt", "updatedAt",
  ],
  ShowAndSellSignup: [
    "showAndSellId", "slotId", "profileId", "unitCampaignId", "campaignId", "status",
    "actualMinutes", "signedUpByAccountId", "confirmedByAccountId", "confirmedAt", "version",
    "createdAt", "updatedAt",
  ],
};

describe("Show & Sell Stage 3.1 event SDL (schema.graphql)", () => {
  test("the event state enum carries exactly the six §9.1 states", () => {
    for (const [name, values] of Object.entries(SS31_ENUMS)) {
      const def = definition(name);
      expect(def.kind, `${name} must be an enum`).toBe("enum");
      const found = def.body.split("\n").map((l) => l.trim()).filter((l) => /^[A-Z][A-Z0-9_]*$/.test(l));
      expect(found, `${name} values`).toEqual(values);
    }
    // Signup state is its own closed set: a signup is a place that is held or given
    // back, and the decline/declined vocabulary of a signup *request* is not a state
    // this wave's rows can hold.
    const signup = definition("SignupStatus");
    expect(signup.kind).toBe("enum");
    const signupValues = signup.body.split("\n").map((l) => l.trim()).filter((l) => /^[A-Z][A-Z0-9_]*$/.test(l));
    expect(signupValues, "SignupStatus values").toEqual(["ACTIVE", "CANCELLED"]);
  });

  test("every §3.1 type and input is present with exactly the contract fields", () => {
    for (const name of [...SS31_OUTPUT_TYPES, ...SS31_INPUTS]) {
      const def = definition(name);
      expect(["type", "input"].includes(def.kind), `${name} must be a type or input`).toBe(true);
    }
    for (const [name, expected] of Object.entries(SS31_TYPE_FIELDS)) {
      expect([...fieldNameSet(definition(name))], `${name} fields`).toEqual(expected);
    }
  });

  test("the three event writes are declared, take one input, and answer their own result", () => {
    for (const [mutation, input, returns] of [
      ["createShowAndSell", "CreateShowAndSellInput", "ShowAndSellAdmin"],
      ["updateShowAndSell", "UpdateShowAndSellInput", "ShowAndSellAdmin"],
      ["cancelShowAndSell", "CancelShowAndSellInput", "CancelShowAndSellPayload"],
    ] as const) {
      const field = rootFieldByName("Mutation", mutation);
      expect(field, `Mutation.${mutation} is missing`).toBeDefined();
      expect(field!.text, `${mutation} takes ${input}`).toMatch(new RegExp(`input\\s*:\\s*${input}!`));
      expect(returnTypeName(field!.text), `${mutation} return type`).toBe(returns);
      expect(field!.text, `${mutation} returns a non-null result`).toMatch(new RegExp(`\\):\\s*${returns}!`));
    }
    // The cancellation answers the whole workflow in one object: the cancelled event,
    // the allocations whose remainder went back on the shelf, and the signups it
    // released. A payload that named only the event would leave the browser to guess
    // what the commit did.
    const payload = fieldsOf(definition("CancelShowAndSellPayload"));
    expect(returnTypeName(payload.find((f) => f.name === "event")!.text)).toBe("ShowAndSellAdmin");
    expect(payload.find((f) => f.name === "releasedAllocations")!.text).toMatch(/:\s*\[ShowAndSellAllocation!\]!/);
    expect(payload.find((f) => f.name === "cancelledSignups")!.text).toMatch(/:\s*\[ShowAndSellSignup!\]!/);
  });

  test("the times are created once and never edited, and every write is idempotent and versioned", () => {
    const create = fieldsOf(definition("CreateShowAndSellInput"));
    for (const [name, pattern] of [
      ["unitCampaignId", /unitCampaignId\s*:\s*ID!/],
      ["locationName", /locationName\s*:\s*String!/],
      ["startAt", /startAt\s*:\s*AWSDateTime!/],
      ["endAt", /endAt\s*:\s*AWSDateTime!/],
    ] as const) {
      expect(create.find((f) => f.name === name)!.text, `CreateShowAndSellInput.${name}`).toMatch(pattern);
    }
    // The split and We Owe settings are the two things a create may choose, and both
    // are optional: omitting the split inherits the Unit default and omitting We Owe
    // means off (§4.1). A required `splitMethod` would make the Unit default dead code.
    for (const name of ["splitMethod", "weOweEnabled"]) {
      const field = create.find((f) => f.name === name)!;
      expect(field.text, `${name} is chosen, not required`).toMatch(new RegExp(`\\??:\\s*(SplitMethod|Boolean)(?!!)`));
    }

    // §3.1.3 / EVT-M-02-01: the update surface is exactly the four settings. No
    // `startAt`/`endAt` means a wrong time is cancelled and recreated, and no
    // `status`/`productIds` means no caller edits the workflow state or the product
    // history directly.
    const update = fieldNameSet(definition("UpdateShowAndSellInput"));
    for (const forbidden of ["startAt", "endAt", "status", "productIds", "unitCampaignId", "hostProfileId"]) {
      expect(update.has(forbidden), `UpdateShowAndSellInput.${forbidden} would break an immutable fact`).toBe(false);
    }

    for (const name of SS31_INPUTS) {
      const fields = fieldsOf(definition(name));
      const idem = fields.find((f) => f.name === "idempotency");
      expect(idem!.text, `${name}.idempotency is required`).toMatch(/idempotency\s*:\s*IdempotencyInput!/);
      // Optimistic concurrency is a VersionedInput block, never a bare Int: a caller
      // that could send an unlabelled number could also send one it never read.
      const version = fields.find((f) => f.name === "version");
      if (name === "CreateShowAndSellInput") {
        expect(version, "a create carries no version to condition on").toBeUndefined();
      } else {
        expect(returnTypeName(version!.text), `${name}.version is the VersionedInput block`).toBe("VersionedInput");
        expect(version!.text, `${name}.version is required`).toMatch(/version\s*:\s*VersionedInput!/);
      }
    }
    // §3.1.4: the reason is mandatory, because this write releases stock and cancels
    // Scouts, and the audit trail has to say why.
    const cancel = fieldsOf(definition("CancelShowAndSellInput"));
    expect(cancel.find((f) => f.name === "reason")!.text).toMatch(/reason\s*:\s*String!/);
  });

  test("the four §3.1 reads keep the admin/participant split and the paging contract", () => {
    const one = rootFieldByName("Query", "showAndSell")!;
    expect(one.text).toContain("showAndSellId: ID!");
    expect(returnTypeName(one.text)).toBe("ShowAndSellAdmin");

    const list = rootFieldByName("Query", "showAndSells")!;
    for (const arg of ["unitCampaignId: ID!", "status: ShowAndSellStatus", "dateRange: DateRangeFilter", "page: PageInput"]) {
      expect(list.text, `showAndSells(${arg}) is missing`).toContain(arg);
    }
    expect(returnTypeName(list.text)).toBe("ShowAndSellAdminConnection");
    expect(list.text).toMatch(/\):\s*ShowAndSellAdminConnection!/);
    // The state filter is a single state, not a list: the browser filters by the state
    // it renders on, and a list of states has no defined meaning against a state that
    // is partly derived from the clock.
    expect(list.text, "showAndSells filters to one state").not.toMatch(/status:\s*\[/);

    const opportunities = rootFieldByName("Query", "unitCampaignOpportunities")!;
    for (const arg of ["unitCampaignId: ID!", "includePast: Boolean = false", "page: PageInput"]) {
      expect(opportunities.text, `unitCampaignOpportunities(${arg}) is missing`).toContain(arg);
    }
    expect(returnTypeName(opportunities.text)).toBe("ShowAndSellOpportunityConnection");
    // No caller may name the Scout whose opportunities are being read: the answer is
    // built from the Scouts the caller can read on this campaign's roster.
    expect(opportunities.text, "unitCampaignOpportunities takes no profileId").not.toContain("profileId");

    const opportunity = rootFieldByName("Query", "showAndSellOpportunity")!;
    for (const arg of ["showAndSellId: ID!", "profileId: ID!"]) {
      expect(opportunity.text, `showAndSellOpportunity(${arg}) is missing`).toContain(arg);
    }
    expect(opportunity.text, "one event's participant view is not a paged list").not.toMatch(/page\s*:\s*PageInput/);
    expect(returnTypeName(opportunity.text)).toBe("ShowAndSellOpportunity");

    for (const [conn, element] of Object.entries(SS31_CONNECTION_ITEMS)) {
      const def = definition(conn);
      expect(returnTypeName(fieldsOf(def).find((f) => f.name === "items")!.text), `${conn}.items`).toBe(element);
      expect(returnTypeName(fieldsOf(def).find((f) => f.name === "pageInfo")!.text), `${conn}.pageInfo`).toBe("PageInfo");
    }
    // `openCapacity` is computed server-side from the slot's maintained counter
    // (SEC-05): the participant surface hands the browser no capacity number to do
    // its own arithmetic against.
    const slot = fieldsOf(definition("ShowAndSellOpportunitySlot"));
    expect(slot.find((f) => f.name === "openCapacity")!.text).toMatch(/openCapacity\s*:\s*Int!/);
    expect(fieldNameSet(definition("ShowAndSellOpportunitySlot")).has("activeSignupCount"), "a participant must not see the maintained counter itself").toBe(false);
  });

  test("the participant projections carry no administrative field, under any spelling", () => {
    const ADMINISTRATIVE = [
      "unitId", "unitCampaignId", "campaignId", "profileId", "version", "createdAt", "updatedAt",
      "createdByAccountId", "updatedByAccountId", "cancelledByAccountId", "cancelledAt",
      "cancellationReason", "allocatedQty", "soldQty", "releasedQty", "remainingQty",
      "activeSignupCount", "productIds", "approvedFinalizationId", "latestFinalizationId",
      "signedUpByAccountId", "confirmedByAccountId", "confirmedAt", "amountCents", "buyerName",
      "reason", "actorAccountId",
    ];
    for (const type of ["ShowAndSellOpportunity", "ShowAndSellOpportunitySlot", "ParticipantSignup"]) {
      const names = fieldNameSet(definition(type));
      for (const field of ADMINISTRATIVE) {
        expect(names.has(field), `${type}.${field} would disclose an administrative fact`).toBe(false);
      }
    }
    // And the admin projection is the one that carries them, so the two surfaces are
    // genuinely different types rather than one type with a resolver that hopes.
    const admin = fieldNameSet(definition("ShowAndSellAdmin"));
    for (const needed of ["unitId", "unitCampaignId", "version", "productIds", "cancellationReason", "cancelledByAccountId"]) {
      expect(admin.has(needed), `ShowAndSellAdmin.${needed} is the audit the admin surface exists to carry`).toBe(true);
    }
  });

  test("AUTH: no §3.1 type, input, enum, or root field carries an auth directive", () => {
    for (const name of [...SS31_OUTPUT_TYPES, ...SS31_INPUTS, ...Object.keys(SS31_ENUMS)]) {
      expect(definition(name).directives, `${name} must carry no auth directive`).toEqual([]);
    }
    for (const name of [...SS31_QUERY_FIELDS, ...SS31_MUTATION_FIELDS]) {
      const field = rootFieldByName("Query", name) ?? rootFieldByName("Mutation", name);
      expect(field, `${name} is missing`).toBeDefined();
      expect(field!.directives, `${name} must be directive-free (Cognito-only)`).toEqual([]);
    }
  });

  test("no §3.1 type or field name is a reserved or invalid GraphQL token", () => {
    const RESERVED = new Set([
      "query", "mutation", "subscription", "type", "input", "interface", "enum", "union",
      "scalar", "implements", "extend", "directive", "schema", "fragment", "on", "repeatable",
    ]);
    const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
    const names = [
      ...SS31_QUERY_FIELDS, ...SS31_MUTATION_FIELDS, ...SS31_OUTPUT_TYPES, ...SS31_INPUTS,
      ...Object.keys(SS31_ENUMS),
    ];
    for (const name of names) {
      expect(NAME.test(name), `${name} must be a valid GraphQL Name`).toBe(true);
      expect(RESERVED.has(name), `${name} is a reserved GraphQL keyword`).toBe(false);
    }
  });
});

// --- Wave 4.2: event stock assignment (§3.2.3) and the raw allocation read (§3.2.4) ---

const SS32_QUERY_FIELDS: string[] = ["eventInventoryAllocations"];

const SS32_MUTATION_FIELDS: string[] = ["assignShowAndSellInventory"];

const SS32_INPUTS: string[] = ["AssignShowAndSellInventoryInput", "AllocationTargetInput"];

const SS32_OUTPUT_TYPES: string[] = [
  "AssignShowAndSellInventoryPayload",
  "AllocationWarning",
  "EventInventoryAllocationConnection",
];

/**
 * The exact field set of each §3.2 type, in declaration order.
 *
 * The warning carries the four numbers AC-10 asks the screen to state, because a
 * sentence a Kernel cannot act on is not a warning. The connection re-uses
 * `ShowAndSellAllocation` rather than minting a report shape: §3.2.4's whole point is
 * that the browser gets the rows and does its own arithmetic.
 */
const SS32_TYPE_FIELDS: Record<string, string[]> = {
  AssignShowAndSellInventoryInput: ["showAndSellId", "items", "version", "idempotency"],
  AllocationTargetInput: ["productId", "quantity"],
  AssignShowAndSellInventoryPayload: ["allocations", "inventoryPositions", "warnings"],
  AllocationWarning: ["code", "productId", "currentStockQty", "assignedQty", "overageQty", "message"],
  EventInventoryAllocationConnection: ["items", "pageInfo"],
};

describe("Show & Sell Stage 3.2 stock-assignment SDL (schema.graphql)", () => {
  test("every §3.2 type and input is present with exactly the contract fields", () => {
    for (const name of [...SS32_OUTPUT_TYPES, ...SS32_INPUTS]) {
      const def = definition(name);
      expect(["type", "input"].includes(def.kind), `${name} must be a type or input`).toBe(true);
    }
    for (const [name, expected] of Object.entries(SS32_TYPE_FIELDS)) {
      expect([...fieldNameSet(definition(name))], `${name} fields`).toEqual(expected);
    }
  });

  test("one save names a batch of absolute targets, is versioned and idempotent, and edits no immutable fact", () => {
    const field = rootFieldByName("Mutation", "assignShowAndSellInventory");
    expect(field, "Mutation.assignShowAndSellInventory is missing").toBeDefined();
    expect(field!.text, "the mutation takes one input").toMatch(/input\s*:\s*AssignShowAndSellInventoryInput!/);
    expect(field!.text, "and answers a non-null result").toMatch(/\):\s*AssignShowAndSellInventoryPayload!/);

    const input = fieldsOf(definition("AssignShowAndSellInventoryInput"));
    expect(input.find((f) => f.name === "showAndSellId")!.text).toMatch(/showAndSellId\s*:\s*ID!/);
    // The batch is required and its element type is non-null: an empty or nullable list
    // would make "save nothing" a request the resolver has to guess the meaning of.
    expect(input.find((f) => f.name === "items")!.text, "items is a non-empty list of non-null targets").toMatch(
      /items\s*:\s*\[AllocationTargetInput!\]!/,
    );
    expect(returnTypeName(input.find((f) => f.name === "version")!.text)).toBe("VersionedInput");
    expect(input.find((f) => f.name === "version")!.text).toMatch(/version\s*:\s*VersionedInput!/);
    expect(input.find((f) => f.name === "idempotency")!.text).toMatch(/idempotency\s*:\s*IdempotencyInput!/);

    // A target, not a delta: the request states what the event should hold, so two
    // clients that both read the same snapshot cannot compound a change by each sending
    // "more". And no stock field is an input, because an assignment never moves physical
    // stock, sold quantity, or what a cancellation already released.
    const target = fieldsOf(definition("AllocationTargetInput"));
    expect(target.find((f) => f.name === "productId")!.text).toMatch(/productId\s*:\s*ID!/);
    expect(target.find((f) => f.name === "quantity")!.text).toMatch(/quantity\s*:\s*Int!/);
    const names = fieldNameSet(definition("AssignShowAndSellInventoryInput"));
    names.forEach((name) => expect(name, "the input block carries no quantity").not.toMatch(/Qty$|quantity/i));
    for (const forbidden of [
      "deltaQty",
      "changeQty",
      "kernelPhysicalQty",
      "soldQty",
      "releasedQty",
      "status",
      "startAt",
      "endAt",
      "unitCampaignId",
      "profileId",
    ]) {
      expect(names.has(forbidden), `AssignShowAndSellInventoryInput.${forbidden} would let a caller move what only a workflow moves`).toBe(false);
    }
    expect(fieldNameSet(definition("AllocationTargetInput")).has("status"), "an assignment cannot close or re-open a row").toBe(false);
  });

  test("the answer is the event's rows, its positions, and its warnings — never a verdict or a total", () => {
    const payload = fieldsOf(definition("AssignShowAndSellInventoryPayload"));
    expect(payload.find((f) => f.name === "allocations")!.text).toMatch(/:\s*\[ShowAndSellAllocation!\]!/);
    expect(payload.find((f) => f.name === "inventoryPositions")!.text).toMatch(/:\s*\[InventoryPosition!\]!/);
    expect(payload.find((f) => f.name === "warnings")!.text).toMatch(/:\s*\[AllocationWarning!\]!/);

    // An over-assignment saves and says. There is deliberately no boolean success/allowed
    // flag and no severity: the list being empty is the only "no warning" the caller needs,
    // and a severity ranking would invite the browser to hide the one it rates lower.
    const warning = fieldsOf(definition("AllocationWarning"));
    for (const [name, pattern] of [
      ["productId", /productId\s*:\s*ID!/],
      ["currentStockQty", /currentStockQty\s*:\s*Int!/],
      ["assignedQty", /assignedQty\s*:\s*Int!/],
      ["overageQty", /overageQty\s*:\s*Int!/],
      ["message", /message\s*:\s*String!/],
      ["code", /code\s*:\s*String!/],
    ] as const) {
      expect(warning.find((f) => f.name === name)!.text, `AllocationWarning.${name}`).toMatch(pattern);
    }
    for (const forbidden of ["severity", "allowed", "ok", "isWarning", "clamped"]) {
      expect(fieldNameSet(definition("AllocationWarning")).has(forbidden), `${forbidden} would grade a warning the caller must state`).toBe(false);
    }
  });

  test("the allocation read is raw rows with its three filters and paging, and no server-side aggregate", () => {
    const query = rootFieldByName("Query", "eventInventoryAllocations");
    expect(query, "Query.eventInventoryAllocations is missing").toBeDefined();
    for (const arg of [
      "unitCampaignId: ID!",
      "productId: ID",
      "showAndSellId: ID",
      "status: AllocationStatus",
      "page: PageInput",
    ]) {
      expect(query!.text, `eventInventoryAllocations(${arg}) is missing`).toContain(arg);
    }
    expect(query!.text).toMatch(/\):\s*EventInventoryAllocationConnection!/);
    // One value per filter, never a list: the read answers the rows a screen renders, and
    // a multi-state filter has no defined order against rows a workflow moves.
    for (const name of ["productId", "showAndSellId", "status"]) {
      expect(query!.text, `eventInventoryAllocations.${name} filters to one value`).not.toMatch(new RegExp(`${name}:\\s*\\[`));
    }
    // The caller names the campaign, never the tenant: tenancy comes from the event row.
    expect(query!.text, "the caller does not choose the Unit").not.toMatch(/unitId\s*:/);
    expect(query!.text, "the caller does not choose a Scout").not.toMatch(/profileId\s*:/);

    const connection = fieldsOf(definition("EventInventoryAllocationConnection"));
    expect(connection.find((f) => f.name === "items")!.text).toMatch(/:\s*\[ShowAndSellAllocation!\]!/);
    expect(returnTypeName(connection.find((f) => f.name === "pageInfo")!.text)).toBe("PageInfo");
    // DATA-Q-03: assigned/unassigned/overage totals are the browser's, over every page it
    // fetched. A total on this type would be a report the server built.
    const aggregate = [...fieldNameSet(definition("EventInventoryAllocationConnection"))].filter((name) =>
      /total|summary|report|count|assigned|overage/i.test(name),
    );
    expect(aggregate, "the allocation connection carries no aggregate").toEqual([]);
  });

  test("AUTH: no §3.2 type, input, or root field carries an auth directive", () => {
    for (const name of [...SS32_OUTPUT_TYPES, ...SS32_INPUTS]) {
      expect(definition(name).directives, `${name} must carry no auth directive`).toEqual([]);
    }
    for (const name of [...SS32_QUERY_FIELDS, ...SS32_MUTATION_FIELDS]) {
      const field = rootFieldByName("Query", name) ?? rootFieldByName("Mutation", name);
      expect(field, `${name} is missing`).toBeDefined();
      expect(field!.directives, `${name} must be directive-free (Cognito-only)`).toEqual([]);
    }
  });
});
