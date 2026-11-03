# Browser-only reporting and document generation

**Status:** Confirmed global architecture decision  
**Last updated:** 2026-10-30  
**Applies to:** All existing and future KernelWorx reports, exports, printable report documents, and ICS calendar invites

## 1. Decision

All reporting and document generation happens in the browser.

The browser is responsible for:

- assembling report datasets from authorized GraphQL data;
- grouping, filtering, sorting, and aggregating report rows;
- rendering report tables and summaries;
- calculating display formulas such as Council Needs;
- generating CSV and XLSX files;
- generating printable HTML and invoking browser print workflows;
- generating and downloading ICS calendar invites; and
- naming downloaded files and displaying generation timestamps.

The server is responsible only for:

- authenticating and authorizing every data request;
- enforcing tenant, Unit, SellerProfile, and field-level security;
- providing authoritative domain data and operational state;
- enforcing mutations, inventory, credit, and finalization invariants; and
- supplying paginated data suitable for browser report assembly.

There must be no server-side report generator, report-generation Lambda, S3 report output, pre-signed report-download URL, server-generated printable report document, or server-generated ICS file.

## 2. Security boundary

Browser-only reporting does not move authorization into the browser.

- Every GraphQL data query independently enforces the caller's current Unit/Profile access.
- Cross-tenant data returns `NOT_FOUND`; disallowed actions return `FORBIDDEN`.
- Participant data projections remain free of administrative actor, buyer, payment-detail, cash, and audit fields.
- Administrative data projections are available only to Unit Admins for the relevant Unit.
- Browser code is untrusted. Client-selected filters, Unit IDs, product IDs, and Campaign IDs never expand server authorization.
- Exported files may contain only data the caller is already authorized to view in the application.
- No report or ICS artifact is publicly reachable by default; files exist in the browser until the user downloads them.

Removing S3 report output also removes an entire class of stale/pre-signed URL disclosure and report-bucket lifecycle concerns.

## 3. Browser reporting engine

Use one shared frontend reporting engine rather than independent implementations per page. Its exact module layout is an implementation decision, but it has these logical components:

| Component | Responsibility |
| --- | --- |
| Data loader | Execute the authorized GraphQL queries, follow every cursor, report progress, and support cancellation/retry |
| Dataset validator | Reject incomplete pages, mismatched versions, missing required detail, and cross-scope identifiers rather than silently producing a partial report |
| Report assembler | Group/filter/sort rows and calculate report summaries using integer quantities and integer cents |
| View renderer | Display current and historical reports with clear scope, status, and generated-at metadata |
| CSV/XLSX writer | Generate sanitized CSV/XLSX artifacts in the browser, building on `frontend/src/lib/reportExport.ts` and dynamically loaded spreadsheet tooling |
| Printable-document writer | Generate accessible print-ready HTML and invoke browser printing; no HTML document resolver |
| ICS writer | Serialize one VEVENT per selected slot signup with correct escaping, line folding, UID, timestamps, timezone, location, and description |
| Download helper | Create/revoke browser object URLs and trigger downloads without a server report URL |

Report formulas live in tested pure frontend functions shared by screen and file output. The same function must drive CSV, XLSX, printable, and rendered totals so outputs cannot diverge.

## 4. GraphQL data contract

GraphQL endpoints return domain facts, not generated reports. Examples include:

- inventory balances, allocations, custody balances, and movements;
- individual Order lines and fulfilled quantities;
- Show & Sell events, slots, signups, sales, and finalization snapshots;
- We Owe obligations and fulfillments;
- Scout credit allocations and finalization versions;
- Unit Campaign roster and catalog/product metadata; and
- the event/slot/location data needed for printable documents and ICS.

Dedicated report-generation and document-generation resolvers are not part of the target architecture. In particular, the new feature does not expose:

- `showAndSellReport`
- `inventoryReport`
- `councilNeedsReport`
- `unitSellerReport`
- `weOweReport`
- `scoutCampaignSalesSummary` as a report-building endpoint
- `showAndSellSalesSheet`
- `showAndSellPaymentHelpSheet`
- `showAndSellSignupCalendar` returning an ICS document
- `requestUnitReportExport`
- `ReportDownload` or pre-signed report URLs

Instead, paginated data queries such as `unitCampaignOrderLines`, `unitCampaignCreditAllocations`, `scoutCampaignCreditAllocations`, `scoutCampaignPendingAllocations`, and `eventInventoryAllocations` provide the missing raw datasets. Administrative and participant fact types remain separate. `showAndSellSignupCalendarData` supplies authorized calendar input data only; the browser creates the file.

Operational server calculations remain valid when they protect a mutation or return current domain state—for example stock versions, finalization previews, allocation warnings, and approved-credit projections. Their use as input data does not constitute server-side report generation.

## 5. Report consistency and completeness

- Every report records its Unit/Unit Campaign, filters, generation timestamp, and relevant source/finalization versions.
- The data loader must fetch every page required for the selected scope or fail visibly. Never silently truncate a report.
- A failed/forbidden page fails the report rather than presenting a shortened result as authoritative.
- Current inventory and Council Needs use the same balance/allocation/custody/obligation versions throughout the assembled dataset. If versions change during assembly, the browser offers a refresh rather than mixing them silently.
- Historical event reports select one finalization version and use its immutable sale/work/return/credit snapshots.
- Pending and approved credit are distinct in every report.
- CSV, XLSX, print, and screen output reconcile to the same detail rows and totals in tests.

## 6. Browser-generated file requirements

### 6.1 CSV and XLSX

- Reuse the existing frontend export/sanitization patterns.
- Generate files locally and download through browser object URLs.
- Use integer cents converted to display currency only at presentation time.
- Do not send the dataset to a third-party conversion service.

### 6.2 Printable documents

- Generate HTML in the frontend with Unit, Unit Campaign, event identity/location/time, and generation timestamp rendered in the document.
- Sales sheets include products/prices, blank rows, payment methods, Other details area, and We Owe indicator where enabled.
- Payment help includes active Unit methods, QR references/instructions, and Other/split-payment guidance.
- Printing uses the browser's native print flow; there is no server-generated PDF or HTML payload.

### 6.3 ICS calendar invites

The frontend obtains `showAndSellSignupCalendarData` and generates a `.ics` file containing:

- `BEGIN:VCALENDAR` / `END:VCALENDAR` and one `VEVENT` per selected signup;
- stable UID derived from the signup/commitment identity and application host;
- `DTSTAMP` generation time;
- timezone-correct `DTSTART`/`DTEND` for the arbitrary slot duration;
- Show & Sell and slot summary;
- short location name and optional address; and
- Unit and Unit Campaign context in description.

The file is a snapshot. No automatic email, notification, subscription, or later calendar update occurs. ICS text escaping, line folding, injection prevention, and timezone conversion are tested in the frontend.

## 7. Performance and usability

- Data queries remain paginated at 50 by default and 100 maximum.
- The loader displays fetch/assembly progress and supports cancellation.
- Large datasets are assembled incrementally where practical; the UI must remain responsive.
- The browser must not silently cap rows. If a dataset is too large for a reliable interactive report, require a narrower filter and explain why before generation.
- Spreadsheet libraries remain dynamically imported only when XLSX output is requested.
- Printable and ICS downloads work without internet after the required data has already loaded; sale entry remains online-only and paper sheets are the offline fallback.

## 8. Existing application migration

The global rule includes existing campaign and unit reporting.

### Phase 1 — Establish the engine

- Build the shared browser loader, report assembly, CSV/XLSX, print, and ICS components.
- Use the engine for all new Show & Sell/inventory reporting.
- Add raw data queries needed by those reports.
- Add a static schema/IaC/frontend CI guard immediately. Temporarily allowlist only the legacy `getUnitReport` and `requestCampaignReport` paths awaiting migration, and fail on every additional report/document/ICS resolver, report-download type/URL, Lambda report writer, or S3 report output.

### Phase 2 — Migrate existing reports

- Replace `getUnitReport`-provided aggregation in `CampaignReportsPage` with authorized raw campaign/order data and browser grouping.
- Preserve the existing authorization semantics and discovery path exactly: use `listMyProfiles` and `listMyShares` to discover every caller-readable Scout, `listCampaignsByProfile` to fetch every Campaign page, and `listOrdersByCampaign` to fetch every Order page. Browser filters/grouping uses the existing unit metadata/catalog keys. Owner and READ collaborators receive the same records they can read today; revoked collaborators disappear immediately; cross-tenant callers receive no data.
- Use the existing authorized Campaign/Order fields for seller display, customer/contact, product snapshots, payment, and Order Details rather than widening the new participant-safe Show & Sell fact types.
- Keep the existing browser CSV/XLSX behavior in `ReportsPage`, but route it through the shared engine.
- Reach parity for Unit Summary, Seller Report, Order Details, current exports, filtering, complete multi-Campaign/multi-Order pagination, and report security tests for owners, READ collaborators, revoked collaborators, and cross-tenant callers.
- Mark `getUnitReport` and `requestCampaignReport` as deprecated for new development and stop adding callers.

### Phase 3 — Retire server reporting

After parity and migration verification:

- remove `getUnitReport` and `requestCampaignReport` from the public schema;
- retire their Lambda resolvers, S3 report writes, pre-signed download URLs, and unneeded IAM permissions;
- remove obsolete tests and report-download infrastructure; and
- update documentation and CI to reject new server report-generation paths.

Deprecation is not a reason to remove an existing report before browser parity is demonstrated.

## 9. Testing requirements

- Pure frontend tests cover grouping, filters, formulas, rounding, currency, and every smoke-test numerical oracle.
- Loader tests cover pagination, cancellation, failed pages, version mismatches, and no-silent-truncation behavior.
- Browser tests parse generated CSV/XLSX/HTML/ICS content rather than merely checking for a button.
- Authorization tests call raw data queries as removed Unit Admins, READ-only collaborators, non-owner WRITE collaborators, cross-Unit users, and anonymous/API-key callers.
- Report tests confirm participant datasets cannot be used to reconstruct administrative audit, buyer, payment-detail, or cash data.
- Migration tests assert no browser code calls `getUnitReport`, `requestCampaignReport`, `requestUnitReportExport`, or any new server report/document-generation endpoint.
- Tests verify CSV, XLSX, print, and rendered reports reconcile to identical source rows.
