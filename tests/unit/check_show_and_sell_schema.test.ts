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
  UnitCampaignMembership: [
    "unitCampaignId", "unitId", "campaignId", "profileId", "status", "joinedByAccountId",
    "joinedAt", "removedByAccountId", "removedAt", "version", "guardVersion",
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

  test("AUTH: no Stage 3 fulfillment type, input, enum, or field carries an auth directive", () => {
    for (const name of [...Object.keys(SS3_TYPE_FIELDS), ...Object.keys(SS3_INPUT_FIELDS), ...Object.keys(SS3_ENUMS), SS3_MODE_ENUM]) {
      expect(definition(name).directives, `${name} must carry no auth directive`).toEqual([]);
    }
    for (const name of [...SS3_MUTATION_FIELDS, "orderFulfillments"]) {
      const field = rootFieldByName("Mutation", name) ?? rootFieldByName("Query", name);
      expect(field, `${name} is missing`).toBeDefined();
      expect(field!.directives, `${name} must be directive-free`).toEqual([]);
    }
  });
});
