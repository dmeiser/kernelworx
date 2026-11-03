/**
 * Leaf 1.7.5 — static CI guards for the Show & Sell Stage 1 surface.
 *
 * Two guards, both read against the on-disk SDL through the shared parser (and,
 * for the reporting seam, the AppSync resolver wiring). These are the
 * "from day one" security guards the delivery checklist requires before any
 * resolver, table, or UI ships:
 *
 *   1. TENANT AUTHORIZATION (AUTH-U / AUTH-P / AUTH-C + AC-45)
 *        - every Stage 1 operation has a Cognito-only auth path (present and
 *          directive-free); a missing operation or a directive on it is a hole;
 *        - no Show & Sell operation re-exposes an `@aws_api_key` surface;
 *        - no participant-safe type leaks an administrative field;
 *        - AC-45: administrative access is granted only by `createUnit` and
 *          `redeemUnitInvite` (a single-use credential), never by a
 *          self-service claim off legacy metadata - the SDL carries no
 *          claim/adopt/migrate/transfer/recover/import Unit-admin path;
 *        - passing (clean) and failing (malicious SDL) fixtures exercise the
 *          same detectors the live schema is checked with.
 *
 *   2. BROWSER-ONLY REPORTING (WEB-MIG-04)
 *        - no new server-side report / document / ICS path; the two legacy
 *          report paths (`getUnitReport` and the S3 campaign-report family) are
 *          the only report-shaped names allowed, and the only pre-signed
 *          (AWSURL) output is the legacy `CampaignReport.reportUrl`;
 *        - QR image GETs (`qrCodeUrl`, `unitPaymentMethodQrDownloadUrl`) are
 *          narrowly recognized as NON-reporting;
 *        - passing (clean) and failing (malicious SDL) fixtures exercise the
 *          same detector the live schema is checked with.
 *
 * The detector for each guard lives next to the fixture that proves it, so a
 * future SDL edit is rejected by the guard that owns the rule.
 */
import { describe, test, expect } from "vitest";
import {
  loadCodeOnlySchema,
  parseDefinitions,
  parseFields,
  returnTypeName,
  rootFields,
  urlFields,
  API_KEY,
  type Definition,
  type Field,
} from "./show_and_sell_schema";

const SCHEMA = loadCodeOnlySchema();
const DEFINITIONS: Definition[] = parseDefinitions(SCHEMA);
const BY_NAME = new Map(DEFINITIONS.map((d) => [d.name, d]));

function rootFieldByName(rootName: "Query" | "Mutation", name: string): Field | undefined {
  const def = BY_NAME.get(rootName);
  if (!def) return undefined;
  return parseFields(def.body).find((f) => f.name === name);
}

function definition(name: string): Definition {
  const found = BY_NAME.get(name);
  expect(found, `schema.graphql must define ${name}`).toBeDefined();
  return found as Definition;
}

// --- The Stage 1 operation surface (the auth paths that must exist) ---

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

/**
 * Fields that are administrative or audit-bearing and must never appear on a
 * participant-safe projection. A participant (a caller with a bare join code or
 * a READ grant) sees the join preview / participant facts only — never the
 * identity/tenancy/admin bookkeeping of the types it participates in.
 */
const ADMIN_FIELDS = new Set([
  "joinCode",
  "inviteCode",
  "metadataKey",
  "adminCount",
  "isAdmin",
  "version",
  "expectedVersion",
  "expectedMembershipVersion",
  "expectedGuardVersion",
  "createdByAccountId",
  "updatedByAccountId",
  "joinedByAccountId",
  "removedByAccountId",
  "ownerAccountId",
  "adminAccountId",
  "createdAt",
  "updatedAt",
  "unitId",
  "unitCampaignId",
  "catalogId",
  "profileId",
  "campaignId",
  "accountId",
]);

/** The participant-safe types Stage 1 ships (the join preview). */
const PARTICIPANT_TYPES: string[] = ["UnitCampaignJoinPreview"];

/** AC-45: verbs that mark a self-service admin-grant path off legacy metadata. */
const LEGACY_CLAIM_RE = /(claim|adopt|transfer|recover|restore|migrate|import|sync|promote|reassign|assign)/i;

/**
 * The Show & Sell object types: no API-key reachability allowed on any of
 * them either (the seam a server-only report surface would ride).
 */
const SS_TYPE_NAMES: string[] = DEFINITIONS.filter(
  (d) =>
    /^[A-Z]/.test(d.name) &&
    (d.name.startsWith("Unit") ||
      d.name === "CreateUnitPayload" ||
      d.name.startsWith("UnitCampaign") ||
      d.name.startsWith("CreateUnitInvite")),
).map((d) => d.name);

/**
 * Show & Sell names (root fields and object types) carrying an
 * `@aws_api_key` directive - the API-key-only path the surface must never
 * offer. A compliant schema returns [].
 */
export function apiKeyOffenders(source: string, seams: string[]): string[] {
  const seamSet = new Set(seams);
  const offenders: string[] = [];
  for (const field of rootFields(source)) {
    if (seamSet.has(field.name) && field.directives.includes(API_KEY)) {
      offenders.push(field.name);
    }
  }
  for (const def of parseDefinitions(source)) {
    if (seamSet.has(def.name) && def.directives.includes(API_KEY)) {
      offenders.push(def.name);
    }
  }
  return offenders;
}

/** The `(typeName, fieldName)` pairs leaked onto a participant-safe type. */
export function adminFieldLeaks(source: string, participantTypes: string[]): string[] {
  const leaks: string[] = [];
  for (const def of parseDefinitions(source)) {
    if (!participantTypes.includes(def.name)) {
      continue;
    }
    for (const field of parseFields(def.body)) {
      if (ADMIN_FIELDS.has(field.name)) {
        leaks.push(`${def.name}.${field.name}`);
      }
    }
  }
  return leaks;
}

/**
 * The watched Mutation fields that violate AC-45: a self-service claim/
 * adopt/migrate-style verb, or a grant-credentialed return type from a
 * mutation outside the credentials' allowlist. Scope is the Show & Sell
 * mutation names (``watchNames``) - legacy mutations predate AC-45. A
 * compliant schema returns [].
 */
export function legacyAdminClaimMutations(
  source: string,
  allowedGrantReturners: string[],
  watchNames: string[],
): string[] {
  const allowed = new Set(allowedGrantReturners);
  const offenders: string[] = [];
  for (const def of parseDefinitions(source)) {
    if (def.kind !== "type" || def.name !== "Mutation") {
      continue;
    }
    for (const field of parseFields(def.body)) {
      if (!watchNames.includes(field.name)) {
        continue;
      }
      const ret = returnTypeName(field.text) ?? "";
      const returnsGrant = ret === "UnitAccessGrant" || ret === "CreateUnitPayload";
      if (LEGACY_CLAIM_RE.test(field.name) || (returnsGrant && !allowed.has(field.name))) {
        offenders.push(field.name);
      }
    }
  }
  return offenders;
}

describe("Show & Sell Stage 1 - tenant authorization (AUTH)", () => {
  test("every Stage 1 operation has a Cognito-only auth path (present and directive-free)", () => {
    for (const name of SS_QUERY_FIELDS) {
      const field = rootFieldByName("Query", name);
      expect(field, `Query.${name} auth path is missing`).toBeDefined();
      expect(
        field!.directives,
        `${name} must be Cognito-only (directive-free); a directive would change who may call it`,
      ).toEqual([]);
    }
    for (const name of SS_MUTATION_FIELDS) {
      const field = rootFieldByName("Mutation", name);
      expect(field, `Mutation.${name} auth path is missing`).toBeDefined();
      expect(field!.directives, `${name} must be Cognito-only (directive-free)`).toEqual([]);
    }
  });

  test("no Show & Sell operation re-exposes an @aws_api_key surface", () => {
    for (const name of SS_QUERY_FIELDS) {
      expect(rootFieldByName("Query", name)!.directives, `${name} must not be API-key reachable`).not.toContain(
        API_KEY,
      );
    }
    for (const name of SS_MUTATION_FIELDS) {
      expect(rootFieldByName("Mutation", name)!.directives, `${name} must not be API-key reachable`).not.toContain(
        API_KEY,
      );
    }
    // No Show & Sell object type is API-key reachable either.
    for (const typeName of SS_TYPE_NAMES) {
      expect(definition(typeName).directives).not.toContain(API_KEY);
    }
    expect(apiKeyOffenders(SCHEMA, [...SS_QUERY_FIELDS, ...SS_MUTATION_FIELDS, ...SS_TYPE_NAMES])).toEqual([]);
  });

  test("a Show & Sell seam carrying @aws_api_key is rejected (failing fixture)", () => {
    const bad = [
      "type Query {",
      "  unit(id: ID!): Unit @aws_api_key",
      "}",
      "type Unit @aws_api_key {",
      "  unitId: ID!",
      "}",
    ].join("\n");
    expect(apiKeyOffenders(bad, ["unit", "Unit"])).toContain("unit");
    expect(apiKeyOffenders(bad, ["unit", "Unit"])).toContain("Unit");
  });

  test("a participant-safe type never exposes administrative fields (and a leaking schema is rejected)", () => {
    for (const typeName of PARTICIPANT_TYPES) {
      expect(BY_NAME.get(typeName), `participant type ${typeName} is missing`).toBeDefined();
    }
    expect(adminFieldLeaks(SCHEMA, PARTICIPANT_TYPES)).toEqual([]);
    const bad = [
      "type Unit {",
      "  unitId: ID!",
      "  joinCode: String!",
      "  ownerAccountId: ID!",
      "  createdAt: AWSDateTime!",
      "}",
      "type UnitCampaign {",
      "  unitCampaignId: ID!",
      "  adminAccountId: ID!",
      "}",
      "type UnitShare {",
      "  shareId: ID!",
      "  joinCode: String!",
      "}",
    ].join("\n");
    const leaks = adminFieldLeaks(bad, ["Unit", "UnitCampaign", "UnitShare"]);
    expect(leaks).toContain("Unit.joinCode");
    expect(leaks).toContain("Unit.ownerAccountId");
    expect(leaks).toContain("Unit.createdAt");
    expect(leaks).toContain("UnitCampaign.adminAccountId");
    expect(leaks).toContain("UnitShare.joinCode");
  });

  test("AC-45: admin is granted only by createUnit/redeemUnitInvite, never from legacy metadata", () => {
    // (a) The only mutations that hand back an admin grant are the two
    // credential/creation paths - no other mutation returns a UnitAccessGrant
    // or a CreateUnitPayload.
    const grantReturners = SS_MUTATION_FIELDS.filter((name) => {
      const ret = returnTypeName(rootFieldByName("Mutation", name)!.text);
      return ret === "UnitAccessGrant" || ret === "CreateUnitPayload";
    });
    expect([...grantReturners].sort()).toEqual(["createUnit", "redeemUnitInvite"].sort());

    // (b) No self-service claim path: no Stage 1 mutation name is a
    // claim/adopt/transfer/recover/migrate/import of admin access, and the
    // grant-credentialed return types come only from the two credentials.
    expect(legacyAdminClaimMutations(SCHEMA, [...grantReturners], SS_MUTATION_FIELDS)).toEqual([]);

    // (c) redeemUnitInvite is credential-based: it requires the invite code and
    // carries no unit metadata (it cannot claim a unit by name/number/city/state).
    const redeemInput = new Set(parseFields(definition("RedeemUnitInviteInput").body).map((f) => f.name));
    expect(redeemInput.has("inviteCode"), "redeemUnitInvite requires the invite credential").toBe(true);
    for (const meta of ["unitType", "unitNumber", "city", "state", "metadataKey", "unitId"]) {
      expect(redeemInput.has(meta), `redeemUnitInvite must not accept ${meta}`).toBe(false);
    }

    // (d) createUnit is gated: an exact metadata match requires duplicateConfirmed,
    // so it is not a silent self-claim on legacy metadata.
    const createInput = new Set(parseFields(definition("CreateUnitInput").body).map((f) => f.name));
    expect(createInput.has("duplicateConfirmed"), "createUnit must gate on duplicateConfirmed").toBe(true);
  });

  test("a self-service legacy-metadata claim mutation is rejected (failing fixture)", () => {
    const bad = [
      "type Mutation {",
      "  claimUnitAdmin(input: LegacyMetadataKey!): UnitAccessGrant!",
      "}",
      "input LegacyMetadataKey {",
      "  metadataKey: String!",
      "}",
      "type UnitAccessGrant {",
      "  role: UnitRole!",
      "}",
    ].join("\n");
    const offenders = legacyAdminClaimMutations(bad, ["createUnit"], ["claimUnitAdmin"]);
    expect(offenders).toEqual(["claimUnitAdmin"]);
  });
});

// --- Browser-only reporting (WEB-MIG-04) ---

/**
 * Endpoints the target architecture explicitly does not expose
 * (BROWSER_REPORTING_ARCHITECTURE §4). Named so they are rejected unambiguously
 * regardless of return type.
 */
const REPORT_BAD_ENDPOINTS = new Set([
  "showAndSellReport",
  "inventoryReport",
  "councilNeedsReport",
  "unitSellerReport",
  "weOweReport",
  "showAndSellSalesSheet",
  "showAndSellPaymentHelpSheet",
  "showAndSellSignupCalendar",
  "requestUnitReportExport",
  "ReportDownload",
]);

/**
 * The two legacy report paths awaiting browser-only migration, expressed as the
 * only report-shaped names the schema may carry:
 *   1. getUnitReport -> UnitReport (live, in-response, no S3);
 *   2. the S3 campaign-report family (CampaignReport + reportId + reportUrl).
 */
const LEGACY_REPORT_ALLOWLIST = new Set([
  "getUnitReport",
  "UnitReport",
  "CampaignReport",
  "reportId",
  "reportUrl",
]);

/** Narrow QR image-GET recognition: these are file GETs, not reports. */
const QR_GET_RE = /[Qq]r(Code|Download)Url$/;

function isReportArtifact(name: string): boolean {
  if (LEGACY_REPORT_ALLOWLIST.has(name) || QR_GET_RE.test(name)) {
    return false;
  }
  if (REPORT_BAD_ENDPOINTS.has(name)) {
    return true;
  }
  const n = name.toLowerCase();
  // "sheet"/"document"/"invoice"/"export" catch the printable-artifact names;
  // the ICS calendar endpoint is caught by REPORT_BAD_ENDPOINTS and, when it is
  // served as a pre-signed URL, by the AWSURL seam below.
  return (
    n.includes("report") ||
    n.includes("export") ||
    n.includes("sheet") ||
    n.includes("document") ||
    n.includes("invoice")
  );
}

/**
 * Every report/document/ICS-shaped name in a schema source that is not on the
 * legacy allowlist, plus every pre-signed (AWSURL) output field that is not the
 * legacy campaign reportUrl. A compliant schema returns [].
 */
function reportOffenders(source: string): string[] {
  const offenders: string[] = [];
  for (const def of parseDefinitions(source)) {
    if (isReportArtifact(def.name)) {
      offenders.push(def.name);
    }
    for (const field of parseFields(def.body)) {
      if (isReportArtifact(field.name)) {
        offenders.push(`${def.name}.${field.name}`);
      }
    }
  }
  for (const entry of urlFields(source)) {
    if (!(entry.owner === "CampaignReport" && entry.field.name === "reportUrl")) {
      offenders.push(`${entry.owner}.${entry.field.name}`);
    }
  }
  return offenders;
}

describe("Show & Sell Stage 1 - browser-only reporting (WEB-MIG-04)", () => {
  test("the on-disk schema exposes no new report/document/ICS path", () => {
    expect(reportOffenders(SCHEMA), "a new server report/document/ICS path has appeared").toEqual([]);
  });

  test("the only pre-signed (AWSURL) output is the legacy campaign reportUrl", () => {
    const urls = urlFields(SCHEMA).map((e) => `${e.owner}.${e.field.name}`);
    expect(urls).toEqual(["CampaignReport.reportUrl"]);
  });

  test("QR image GETs are recognized as non-reporting (not flagged)", () => {
    expect(isReportArtifact("qrCodeUrl")).toBe(false);
    expect(isReportArtifact("unitPaymentMethodQrDownloadUrl")).toBe(false);
    // A schema whose only URL-ish field is a QR GET (a plain String) is clean.
    const qrClean = [
      "type PaymentMethod {",
      "  qrCodeUrl: String",
      "}",
      "type Query {",
      "  unitPaymentMethodQrDownloadUrl: UnitPaymentMethodQrDownloadUrl",
      "}",
      "type UnitPaymentMethodQrDownloadUrl {",
      "  downloadUrl: String",
      "  expiresAt: AWSDateTime",
      "}",
    ].join("\n");
    expect(reportOffenders(qrClean)).toEqual([]);
  });

  test("a new report/query path is rejected (failing fixture)", () => {
    const bad = [
      "type Query {",
      "  councilNeedsReport: CouncilNeedsReport",
      "}",
      "type CouncilNeedsReport {",
      "  rows: [String!]",
      "}",
    ].join("\n");
    const offenders = reportOffenders(bad);
    expect(offenders).toContain("Query.councilNeedsReport");
    expect(offenders).toContain("CouncilNeedsReport");
  });

  test("a pre-signed report/ICS download URL is rejected (failing fixture)", () => {
    // Innocuous names, but the AWSURL output seam is what serves the artifact.
    const bad = [
      "type Query {",
      "  councilNeedsData: CouncilNeedsData",
      "}",
      "type CouncilNeedsData {",
      "  downloadUrl: AWSURL",
      "}",
    ].join("\n");
    expect(reportOffenders(bad)).toContain("CouncilNeedsData.downloadUrl");
  });

  test("a named ICS/document endpoint is rejected (failing fixture)", () => {
    const bad = [
      "type Query {",
      "  showAndSellSignupCalendar: String",
      "}",
    ].join("\n");
    expect(reportOffenders(bad)).toContain("Query.showAndSellSignupCalendar");
  });

  test("the detector also rejects a report name smuggled onto an existing type", () => {
    // The named-bad-endpoint list alone is not the whole guard: an unlisted
    // report-shaped field on any type is still a new server artifact, and a
    // pre-signed report URL is caught by the AWSURL seam even under a benign
    // field name.
    const bad = [
      "type Unit {",
      "  unitId: ID!",
      "  inventoryReportUrl: AWSURL",
      "}",
    ].join("\n");
    expect(reportOffenders(bad)).toContain("Unit.inventoryReportUrl");
  });
});
