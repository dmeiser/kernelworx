/**
 * Leaf 1.7.5 — static CI guards for the Show & Sell Stage 1 surface.
 *
 * Two guards, both read against the on-disk SDL through the shared parser (and,
 * for the reporting seam, the AppSync resolver wiring, the Lambda handlers, and
 * the frontend callers). These are the "from day one" security guards the
 * delivery checklist requires before any resolver, table, or UI ships:
 *
 *   1. TENANT AUTHORIZATION (AUTH-U / AUTH-P / AUTH-C + AC-45)
 *        - every Stage 1 Unit operation AND every existing Profile-scoped
 *          operation has a Cognito-only auth path (present and directive-free);
 *          a missing operation or a directive on it is a hole;
 *        - the @aws_api_key rule is whole-schema, not list-bound: the only
 *          names that may carry it are the explicit legacy public-orders set;
 *        - no participant-safe type leaks an administrative field; the
 *          participant set is DERIVED from the `# participant-safe` marker in
 *          the SDL, so a new participant type must opt in to be checked;
 *        - AC-45: administrative access is granted only by `createUnit` and
 *          `redeemUnitInvite` (a single-use credential), never by a
 *          self-service claim off legacy metadata - the SDL carries no
 *          claim/adopt/migrate/transfer/recover/import Unit-admin path;
 *        - passing (clean) and failing (malicious SDL) fixtures exercise the
 *          same detectors the live schema is checked with.
 *
 *   2. BROWSER-ONLY REPORTING (WEB-MIG-04)
 *        - no new server-side report / document / ICS path. A complete new
 *          server document path is SDL field + real AppSync resolver block +
 *          handler writing the artifact to S3 + frontend caller, so the seam
 *          guard reads ALL FOUR legs; the only live legacy path is
 *          `getUnitReport` (in-response, no S3), and the only pre-signed
 *          (AWSURL) output is `CampaignReport.reportUrl`;
 *        - `reportId` / `reportUrl` are scoped to the `CampaignReport` owner
 *          type - the same bare names on any other type are a new surface;
 *        - QR image GETs (`qrCodeUrl`, `unitPaymentMethodQrDownloadUrl`) are
 *          recognized by exact name as NON-reporting;
 *        - passing (clean) and failing (malicious) fixtures exercise the same
 *          detectors the live repo is checked with.
 *
 * The detector for each guard lives next to the fixture that proves it, so a
 * future SDL edit is rejected by the guard that owns the rule.
 */
import { describe, test, expect } from "vitest";
import { readFileSync, readdirSync } from "fs";
import { join, relative } from "path";
import { fileURLToPath } from "url";
import {
  loadCodeOnlySchema,
  loadSchema,
  codeOnly,
  parseDefinitions,
  parseFields,
  returnTypeName,
  rootFields,
  rootFieldsByName,
  urlFields,
  API_KEY,
  type Definition,
  type Field,
} from "./show_and_sell_schema";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const REPO_ROOT = join(__dirname, "..", "..");
const APPSYNC_MODULE_DIR = join(REPO_ROOT, "tofu", "application", "modules", "appsync");
const HANDLERS_DIR = join(REPO_ROOT, "src", "handlers");
const FRONTEND_SRC_DIR = join(REPO_ROOT, "frontend", "src");

const SCHEMA = loadCodeOnlySchema();
const RAW_SCHEMA = loadSchema();
const DEFINITIONS: Definition[] = parseDefinitions(SCHEMA);
const BY_NAME = new Map(DEFINITIONS.map((d) => [d.name, d]));

function* walkFiles(dir: string, extensions: string[]): Generator<string> {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      yield* walkFiles(full, extensions);
    } else if (extensions.some((ext) => entry.name.endsWith(ext))) {
      yield full;
    }
  }
}

function rootFieldByName(rootName: "Query" | "Mutation", name: string): Field | undefined {
  // Across ALL definitions of the root, extend blocks included: a field
  // declared only in `extend type Query` is still a real auth path.
  return rootFieldsByName(SCHEMA, rootName).find((f) => f.name === name);
}

function definition(name: string): Definition {
  const found = BY_NAME.get(name);
  expect(found, `schema.graphql must define ${name}`).toBeDefined();
  return found as Definition;
}

// --- The operation surface whose auth paths must exist (Unit + Profile) ---

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
 * The Profile-scoped seam: leaf 1.7.5 says "Unit/Profile auth paths", and
 * these are the pre-existing Profile-domain operations a regression could
 * re-directive (profile reads/writes, sharing, invites, ownership transfer).
 */
const PROFILE_QUERY_FIELDS: string[] = [
  "getProfile",
  "listMyProfiles",
  "listSharesByProfile",
  "listInvitesByProfile",
  "paymentMethodsForProfile",
];

const PROFILE_MUTATION_FIELDS: string[] = [
  "createSellerProfile",
  "updateSellerProfile",
  "deleteSellerProfile",
  "createProfileInvite",
  "deleteProfileInvite",
  "redeemProfileInvite",
  "shareProfileDirect",
  "revokeShare",
  "transferProfileOwnership",
];

const ALL_WATCHED_FIELDS: string[] = [
  ...SS_QUERY_FIELDS,
  ...SS_MUTATION_FIELDS,
  ...PROFILE_QUERY_FIELDS,
  ...PROFILE_MUTATION_FIELDS,
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

/**
 * The participant-safe set is DERIVED from the SDL, not hardcoded: a type
 * opts in by carrying a `# participant-safe` marker comment directly above
 * its declaration, and every marked type is then rejected if it exposes an
 * administrative field. A new participant type without the marker is not
 * checked at all - which the marker-existing test below makes loud.
 */
export function participantTypes(source: string): string[] {
  const names: string[] = [];
  // Marker comment lines may be followed by the type's docstring before the
  // header, so the optional docstring block sits between the two.
  const marked = /((?:^[ \t]*#[^\n]*\n)+)(?:"""[\s\S]*?"""[ \t]*\n)?^type\s+(\w+)[^\n]*\{/gm;
  for (const match of source.matchAll(marked)) {
    if (match[1].includes("participant-safe")) {
      names.push(match[2]);
    }
  }
  return names;
}

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
 * The ONLY names that may carry `@aws_api_key`: the pre-Show & Sell anonymous
 * public-orders surface. The rule is whole-schema - a NEW field or type with
 * the directive is an offender no matter which list it would or would not
 * have been on. A compliant schema returns [].
 */
const LEGACY_API_KEY_SURFACE = new Set([
  "publicGetOrderOffer",
  "publicGetOrderReceipt",
  "publicCreateOrder",
  "PublicOrderOffer",
  "PublicProduct",
  "PublicPaymentMethod",
  "PublicLineItem",
  "PublicOrderReceipt",
  "PublicOrderReceiptLookup",
]);

export function apiKeyOffenders(source: string): string[] {
  const offenders: string[] = [];
  for (const field of rootFields(source)) {
    if (field.directives.includes(API_KEY) && !LEGACY_API_KEY_SURFACE.has(field.name)) {
      offenders.push(field.name);
    }
  }
  for (const def of parseDefinitions(source)) {
    if (def.directives.includes(API_KEY) && !LEGACY_API_KEY_SURFACE.has(def.name)) {
      offenders.push(def.name);
    }
  }
  // Field-level directives inside non-root object types: the legacy allowance
  // is type-level on the six Legacy Public* types plus the three legacy root
  // fields ONLY, so ANY field-level @aws_api_key on a non-root type is an
  // offender no matter which list its owner type would sit on. (Root fields
  // are covered by the first loop above.)
  for (const def of parseDefinitions(source)) {
    if (def.kind !== "type" || def.name === "Query" || def.name === "Mutation") {
      continue;
    }
    for (const field of parseFields(def.body)) {
      if (field.directives.includes(API_KEY)) {
        offenders.push(`${def.name}.${field.name}`);
      }
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
  test("every Unit and Profile operation has a Cognito-only auth path (present and directive-free)", () => {
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
    // The Profile-scoped seam (leaf 1.7.5 says Unit/Profile auth paths).
    for (const name of PROFILE_QUERY_FIELDS) {
      const field = rootFieldByName("Query", name);
      expect(field, `Query.${name} auth path is missing`).toBeDefined();
      expect(field!.directives, `${name} must be Cognito-only (directive-free)`).toEqual([]);
    }
    for (const name of PROFILE_MUTATION_FIELDS) {
      const field = rootFieldByName("Mutation", name);
      expect(field, `Mutation.${name} auth path is missing`).toBeDefined();
      expect(field!.directives, `${name} must be Cognito-only (directive-free)`).toEqual([]);
    }
  });

  test("the only @aws_api_key surface anywhere is the legacy public-orders set", () => {
    // Whole-schema rule: an offender is any @aws_api_key field or type outside
    // the explicit legacy set, no matter which list it sits on.
    expect(apiKeyOffenders(SCHEMA)).toEqual([]);
    // None of the watched Unit/Profile auth paths or Show & Sell types is
    // API-key reachable either.
    for (const name of ALL_WATCHED_FIELDS) {
      const field = rootFieldByName("Query", name) ?? rootFieldByName("Mutation", name);
      expect(field, `${name} is missing`).toBeDefined();
      expect(field!.directives, `${name} must not be API-key reachable`).not.toContain(API_KEY);
    }
    for (const typeName of SS_TYPE_NAMES) {
      expect(definition(typeName).directives).not.toContain(API_KEY);
    }
  });

  test("any new @aws_api_key surface is rejected (failing fixture)", () => {
    const bad = [
      "type Query {",
      "  unit(id: ID!): Unit @aws_api_key",
      "}",
      "type Unit @aws_api_key {",
      "  unitId: ID!",
      "}",
    ].join("\n");
    expect(apiKeyOffenders(bad)).toEqual(["unit", "Unit"]);
  });

  test("a field-level @aws_api_key inside any non-root type is rejected, even inside a legacy Public* type", () => {
    const bad = [
      "type PublicOrderReceipt @aws_api_key {",
      "  orderId: ID!",
      "  joinCode: String @aws_api_key",
      "}",
      "type Unit {",
      "  unitId: ID!",
      "  secret: String @aws_api_key",
      "}",
    ].join("\n");
    expect(apiKeyOffenders(bad)).toEqual([
      "PublicOrderReceipt.joinCode",
      "Unit.secret",
    ]);
  });

  test("a participant-safe type never exposes administrative fields (and a leaking schema is rejected)", () => {
    const derived = participantTypes(RAW_SCHEMA);
    // The marker is load-bearing: exactly the join preview opts in, and the
    // check set cannot silently drift away from what the SDL declares.
    expect(derived).toEqual(["UnitCampaignJoinPreview"]);
    for (const typeName of derived) {
      expect(BY_NAME.get(typeName), `participant type ${typeName} is missing`).toBeDefined();
    }
    expect(adminFieldLeaks(SCHEMA, derived)).toEqual([]);
    const bad = [
      "# participant-safe: bare join code callers see this preview",
      "type UnitJoinPreview {",
      "  unitDisplayName: String!",
      "  joinCode: String!",
      "  ownerAccountId: ID!",
      "}",
      "type UnitCampaign {",
      "  unitCampaignId: ID!",
      "  adminAccountId: ID!",
      "}",
    ].join("\n");
    const leaks = adminFieldLeaks(codeOnly(bad), participantTypes(bad));
    expect(leaks).toEqual(["UnitJoinPreview.joinCode", "UnitJoinPreview.ownerAccountId"]);
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
 * The report-shaped names the schema may carry, and why each is there. Of the
 * two legacy paths only getUnitReport is LIVE: it answers in-response with no
 * S3 (the browser renders the UnitReport from data). The CampaignReport /
 * reportId / reportUrl type family is pre-existing schema surface whose
 * producing mutation (requestCampaignReport) was removed in #905; it stays
 * allowlisted so dead legacy types do not trip the guard - it is NOT
 * permission to extend the server-report surface. Any NEW report/document/ICS
 * artifact must be browser-generated (WEB-MIG-04).
 */
const LEGACY_REPORT_NAMES = new Set(["getUnitReport", "UnitReport", "CampaignReport"]);

/**
 * The ONLY pre-signed (AWSURL) output the schema may carry, owner-scoped:
 * `reportUrl`/`reportId` are exempt from the report-shaped-name check only on
 * the CampaignReport owner type; the same bare names on ANY other type are a
 * new server report surface.
 */
const LEGACY_REPORT_URL = { owner: "CampaignReport", field: "reportUrl" } as const;

/**
 * Narrow QR image-GET recognition: the exact two names only (a regex such as
 * /[Qq]r(Code|Download)Url$/ is an escape hatch - unitSalesReportQrDownloadUrl
 * must NOT pass).
 */
const QR_GET_NAMES = new Set(["qrCodeUrl", "unitPaymentMethodQrDownloadUrl"]);

function isReportArtifact(name: string): boolean {
  if (LEGACY_REPORT_NAMES.has(name) || QR_GET_NAMES.has(name)) {
    return false;
  }
  if (REPORT_BAD_ENDPOINTS.has(name)) {
    return true;
  }
  const n = name.toLowerCase();
  // "sheet"/"document"/"invoice"/"export" catch the printable-artifact names;
  // "calendar"/"ics"/"pdf"/"workbook" catch the ICS and document formats; the
  // ICS calendar endpoint named in REPORT_BAD_ENDPOINTS and, when it is served
  // as a pre-signed URL, the AWSURL seam below cover the rest.
  return (
    n.includes("report") ||
    n.includes("export") ||
    n.includes("sheet") ||
    n.includes("document") ||
    n.includes("invoice") ||
    n.includes("calendar") ||
    n.includes("pdf") ||
    n.includes("workbook") ||
    // An `ics` calendar artifact: the bare token, or a name ENDING in it
    // (councilNeedsIcs) - no live field name ends in `ics`, and metrics-like
    // collisions would be a loud, deliberate addition.
    n.endsWith("ics") ||
    /(?:^|[^a-z])ics(?:[^a-z]|$)/.test(n)
  );
}

/**
 * Every report/document/ICS-shaped name in a schema source that is not on the
 * legacy allowlist, plus every pre-signed (AWSURL) output field that is not
 * the legacy CampaignReport.reportUrl. A compliant schema returns [].
 */
function reportOffenders(source: string): string[] {
  const offenders: string[] = [];
  for (const def of parseDefinitions(source)) {
    if (isReportArtifact(def.name)) {
      offenders.push(def.name);
    }
    for (const field of parseFields(def.body)) {
      // Owner-scoped exemption: reportId/reportUrl exist only on CampaignReport.
      if (def.name === "CampaignReport" && (field.name === "reportUrl" || field.name === "reportId")) {
        continue;
      }
      if (isReportArtifact(field.name)) {
        offenders.push(`${def.name}.${field.name}`);
      }
    }
  }
  for (const entry of urlFields(source)) {
    if (!(entry.owner === LEGACY_REPORT_URL.owner && entry.field.name === LEGACY_REPORT_URL.field)) {
      offenders.push(`${entry.owner}.${entry.field.name}`);
    }
  }
  return offenders;
}

// --- The reporting seam detectors (SDL + IaC + Lambda + frontend) ---

/**
 * Every `field = "<name>"` an AppSync resolver block wires (root or object
 * field). This is the IaC leg of the reporting seam: a new server document
 * path must be wired here before anything can call it.
 */
export function wiredResolverFields(tfSource: string): string[] {
  return [...tfSource.matchAll(/\bfield\s*=\s*"(\w+)"/g)].map((match) => match[1]);
}

/** Report-shaped resolver wirings outside the one live legacy path. */
export function reportResolverWiring(tfSource: string): string[] {
  // Only getUnitReport may be wired: it is the live legacy in-response report
  // (no S3). requestCampaignReport's wiring died with #905 and must not return.
  return wiredResolverFields(tfSource).filter((name) => isReportArtifact(name) && name !== "getUnitReport");
}

/** True when a Lambda handler source writes an object into S3 (the artifact store). */
export function handlerWritesS3Object(pySource: string): boolean {
  return /\b(?:put_object|upload_fileobj|upload_file)\s*\(/.test(pySource);
}

/** Every GraphQL operation name declared in gql-tagged documents. */
export function graphQLOperations(tsSource: string): string[] {
  const names: string[] = [];
  for (const doc of tsSource.matchAll(/gql`([\s\S]*?)`/g)) {
    for (const op of doc[1].matchAll(/\b(?:query|mutation)\s+(\w+)/g)) {
      names.push(op[1]);
    }
  }
  return names;
}

/** Report-shaped GraphQL operations outside the one live legacy client. */
export function reportFrontendOperations(tsSource: string): string[] {
  // GetUnitReport is the live legacy client: the browser renders the report
  // from the in-response data (no download URL is involved).
  return graphQLOperations(tsSource).filter(
    (name) => isReportArtifact(name) && name.toLowerCase() !== "getunitreport",
  );
}

describe("Show & Sell Stage 1 - browser-only reporting (WEB-MIG-04)", () => {
  test("the on-disk schema exposes no new report/document/ICS path", () => {
    expect(reportOffenders(SCHEMA), "a new server report/document/ICS path has appeared").toEqual([]);
  });

  test("the reporting seam is guarded across SDL, resolver wiring, Lambda handlers, and frontend callers", () => {
    // SDL leg (above) plus the three implementation legs: a complete new
    // server document path cannot reach production with any leg unguarded.
    const tfSources = ["resolvers_queries.tf", "resolvers_mutations.tf"].map((file) =>
      readFileSync(join(APPSYNC_MODULE_DIR, file), "utf8"),
    );
    for (const source of tfSources) {
      expect(reportResolverWiring(source), "a report-shaped AppSync resolver is wired").toEqual([]);
    }

    const handlerOffenders = [...walkFiles(HANDLERS_DIR, [".py"])]
      .filter((file) => handlerWritesS3Object(readFileSync(file, "utf8")))
      .map((file) => relative(REPO_ROOT, file));
    expect(handlerOffenders, "a Lambda handler writes a report artifact to S3").toEqual([]);

    // The generated type mirror is owned by the SDL guard; scan the hand-written
    // client surface for report-shaped operations.
    const frontendOffenders = [...walkFiles(FRONTEND_SRC_DIR, [".ts", ".tsx"])]
      .filter((file) => !file.endsWith(join("types", "graphql-generated.ts")))
      .flatMap((file) =>
        reportFrontendOperations(readFileSync(file, "utf8")).map(
          (name) => `${relative(FRONTEND_SRC_DIR, file)}:${name}`,
        ),
      );
    expect(frontendOffenders, "a frontend caller uses a new server report operation").toEqual([]);
  });

  test("a complete new server document path is rejected at every seam (failing fixtures)", () => {
    // SDL leg.
    const badSdl = [
      "type Query {",
      "  councilNeedsReport: CouncilNeedsReport",
      "}",
      "type CouncilNeedsReport {",
      "  rows: [String!]",
      "}",
    ].join("\n");
    expect(reportOffenders(badSdl)).toContain("Query.councilNeedsReport");
    expect(reportOffenders(badSdl)).toContain("CouncilNeedsReport");

    // IaC leg: the resolver wiring for the new path.
    const badTf = [
      'resource "aws_appsync_resolver" "council_needs_report" {',
      '  field = "councilNeedsReport"',
      "}",
    ].join("\n");
    expect(reportResolverWiring(badTf)).toEqual(["councilNeedsReport"]);

    // Lambda leg: the handler that uploads the artifact.
    const badHandler = "def handler(event, context):\n    s3_client.put_object(Bucket=bucket, Key=key, Body=body)\n";
    expect(handlerWritesS3Object(badHandler)).toBe(true);
    expect(handlerWritesS3Object("def handler(event, context):\n    return table.get_item(Key=key)\n")).toBe(false);

    // Frontend leg: the caller of the new operation.
    const badClient = [
      "export const GET_COUNCIL_NEEDS_REPORT = gql`",
      "  query CouncilNeedsReport {",
      "    councilNeedsReport { rows }",
      "  }",
      "`;",
    ].join("\n");
    expect(reportFrontendOperations(badClient)).toEqual(["CouncilNeedsReport"]);
  });

  test("the only pre-signed (AWSURL) output is the legacy campaign reportUrl", () => {
    const urls = urlFields(SCHEMA).map((e) => `${e.owner}.${e.field.name}`);
    expect(urls).toEqual(["CampaignReport.reportUrl"]);
  });

  test("reportUrl/reportId are scoped to the CampaignReport owner type (failing fixture)", () => {
    // The same bare names on any OTHER type are a new server report surface.
    const bad = [
      "type Unit {",
      "  unitId: ID!",
      "  reportUrl: String",
      "}",
      "type SharedCampaign {",
      "  reportId: ID!",
      "}",
    ].join("\n");
    const offenders = reportOffenders(bad);
    expect(offenders).toContain("Unit.reportUrl");
    expect(offenders).toContain("SharedCampaign.reportId");
  });

  test("QR image GETs are recognized as non-reporting (not flagged)", () => {
    expect(isReportArtifact("qrCodeUrl")).toBe(false);
    expect(isReportArtifact("unitPaymentMethodQrDownloadUrl")).toBe(false);
    // The old regex escape hatch stays shut: a report name ending in a QR-ish
    // suffix is still a report.
    expect(isReportArtifact("unitSalesReportQrDownloadUrl")).toBe(true);
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

  test("the ICS/calendar/pdf/workbook formats are recognized (failing fixture)", () => {
    const bad = [
      "type Query {",
      "  showAndSellSignupCalendar: String",
      "  councilNeedsIcs: String",
      "  unitSalesWorkbook: String",
      "  priceListPdf: String",
      "}",
    ].join("\n");
    const offenders = reportOffenders(bad);
    expect(offenders).toContain("Query.showAndSellSignupCalendar");
    expect(offenders).toContain("Query.councilNeedsIcs");
    expect(offenders).toContain("Query.unitSalesWorkbook");
    expect(offenders).toContain("Query.priceListPdf");
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

  test("the parser sees extended roots and four-space fields, so smuggling there is caught", () => {
    // A hostile edit hiding the new path in an `extend type` block or behind
    // four-space indentation must still parse - both shapes are legal SDL.
    const bad = [
      "extend type Query {",
      "    councilNeedsReport: CouncilNeedsReport",
      "}",
      "type CouncilNeedsReport {",
      "  rows: [String!]",
      "}",
    ].join("\n");
    const code = codeOnly(bad);
    expect(rootFieldsByName(code, "Query").map((f) => f.name)).toContain("councilNeedsReport");
    expect(reportOffenders(code)).toContain("Query.councilNeedsReport");
    expect(reportOffenders(code)).toContain("CouncilNeedsReport");
  });

  test("the parser sees zero-indent fields, so smuggling there is caught", () => {
    // A field at column 0 is legal SDL too: a zero-indent pre-signed report
    // URL (AWSURL output seam) and a zero-indent @aws_api_key field must both
    // surface to their guards instead of parsing as invisible.
    const badReport = ["type Unit {", "reportUrl: AWSURL", "}"].join("\n");
    expect(reportOffenders(codeOnly(badReport))).toContain("Unit.reportUrl");
    const badApiKey = ["type Unit {", "joinCode: String @aws_api_key", "}"].join("\n");
    expect(apiKeyOffenders(codeOnly(badApiKey))).toContain("Unit.joinCode");
  });

  test("the parser sees capitalized fields, so smuggling there is caught", () => {
    // A capitalized field name is legal SDL too; the guards see every field
    // of every definition, whatever case its name begins with.
    const badReport = ["type Unit {", "  ReportUrl: AWSURL", "}"].join("\n");
    expect(reportOffenders(codeOnly(badReport))).toContain("Unit.ReportUrl");
    const badApiKey = ["type Unit {", "  JoinCode: String @aws_api_key", "}"].join("\n");
    expect(apiKeyOffenders(codeOnly(badApiKey))).toContain("Unit.JoinCode");
  });
});
