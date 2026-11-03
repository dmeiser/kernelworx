# Show & Sell and inventory: existing-application impact map

**Status:** Codebase-derived integration and migration plan  
**Last updated:** 2026-10-30  
**Purpose:** Map the proposed feature onto the actual KernelWorx codebase, including required changes, dependencies, security constraints, migration order, and affected tests.

## 1. Current-state summary

The feature is greenfield. The current application has no standalone Unit, Unit Campaign, inventory, Scout custody, Show & Sell, We Owe, finalization, or fulfillment records.

Current architecture is centered on:

```text
Account → SellerProfile → Campaign → Order → LineItem
                    Campaign → Catalog → Product
```

Current “unit” reporting is based on denormalized `unitType`, `unitNumber`, city/state, and `unitCampaignKey` metadata. That is not a stable ownership or authorization root and must not be reused as one.

The target adds:

```text
Unit → Unit Campaign → joined Scout Campaigns
     → Unit-scoped payment methods/defaults
     → Inventory/custody/Show & Sell/finalization
```

Five new DynamoDB tables are required: `units`, `unit_campaigns`, `inventory`, `show_and_sells`, and `order_fulfillments`. There is deliberately no standalone idempotency or coordinator table.

The current DynamoDB module has nine tables when `public_order_throttles` is included, so the target has 14 application tables before legacy report cleanup.

## 2. Highest-risk integration findings

1. **Current `createOrder` is not atomic enough for Scout custody.** It is an AppSync JS pipeline ending in a single `PutItem`. Adding custody writes as more pipeline steps would permit partial sales. Custody mode needs one cross-table transaction or a Lambda transaction with all authoritative reads.
2. **IAM currently lacks `dynamodb:TransactWriteItems`.** Both the AppSync DynamoDB policy and the broad admin Lambda policy omit it. Every role that invokes transactions needs it explicitly, with no Scan permission added.
3. **Legacy unit metadata is not authorization.** Stable Unit access must come from `UnitAccessGrant`, never `unitCampaignKey`, global ADMIN, SharedCampaign creator, or SellerProfile Share.
4. **Existing cleanup knows nothing about the new records.** Order fulfillment, membership, commitments, custody, event sales, obligations, finalization versions, Unit grants, and Unit QR objects all need explicit lifecycle handling.
5. **Final-Unit-admin account deletion is unresolved.** Removing the last grant would orphan a Unit and violate `adminCount >= 1`. Production needs an explicit policy, not an incidental side effect of account deletion.
6. **Existing Order edits can erase fulfillment identity.** `updateOrder` replaces line items. It needs stable-ID and fulfilled-quantity preservation rules before fulfillment is introduced.
7. **Current report pagination is incomplete.** Several frontend pages consume only the first Order page. Browser-only reporting requires complete cursor loading and visible failure on any missing page.
8. **Legacy report retirement has shared dependencies.** `list_catalogs_in_use.py` imports constants from `campaign_reporting.py`, and historical report cleanup still needs some S3 delete/list behavior after report generation is retired.
9. **Test cleanup is currently global and account-wide.** It is incompatible with parallel lanes and must remain separate from lane-scoped cleanup.
10. **Global ADMIN is not Unit Admin.** Frontend `requireAdmin`, `account.isAdmin`, and Cognito groups must not be reused for Unit access.

## 3. GraphQL and backend impact

### 3.1 Schema and generated API artifacts

| File | Current behavior | Required change | Tests/validation |
| --- | --- | --- | --- |
| `tofu/application/schema/schema.graphql` | Legacy Account/Profile/Campaign/Order/Catalog models; `getUnitReport` and `requestCampaignReport` provide server aggregation/export | Add all Unit/Unit Campaign/inventory/event/sale/We Owe/finalization/raw-data models and operations. Extend Campaign/Order/LineItem with origin and fulfillment fields. Add participant-safe projections. Keep all new fields Cognito-only. Deprecate legacy reports before later removal | `check_public_api_key_surface.test.ts`, `test_public_api_key_surface.py`, generated-schema/codegen drift, new API contract tests |
| `frontend/codegen.ts` | Generates frontend types from schema | Run through one codegen owner after SDL changes | `frontend/src/types/graphql-generated.ts` must be regenerated, never hand-edited |
| `frontend/src/types/graphql-generated.ts` | Checked-in generated types | Regenerate for every schema/operation change | CI codegen drift check |
| `frontend/src/lib/graphql.ts` | Central operations/fragments; legacy Order fragment lacks origin/fulfillment | Add new operations/fragments and update Order fields. Keep legacy `nextToken` separate from new `items/pageInfo` cursors | Frontend operation/type tests and `AUTH-C` behavior |
| `tofu/application/modules/appsync/api.tf` | Depth/resolver-limit rationale references `getUnitReport` | Recompute depth/fan-out for finalization children and paginated report facts; update comments and measured limits | Query-depth and resolver-limit validation |
| `tofu/application/modules/appsync/resolvers_queries.tf` | Existing query wiring, including `getUnitReport` | Add every contracted query. Do not map `unitCampaignCatalog` to legacy `listUnitCampaignCatalogs`. Remove `getUnitReport` only after browser parity | `test_lambda_unit_resolver_wiring.py`, pipeline/auth contract tests, live resolver tests |
| `tofu/application/modules/appsync/resolvers_mutations.tf` | Existing mutation wiring, including single-write `createOrder` and `requestCampaignReport` | Add all new mutations. Use direct Lambda unit resolvers for complex transactions. Redesign custody-mode `createOrder`. Remove legacy report mutation only after parity | `test_appsync_pipeline_functions.py`, `test_appsync_resolver_order.py`, live security/concurrency tests |
| `tofu/application/modules/appsync/resolvers_fields.tf` | Existing field resolvers | Add `Order.fulfillments` only if not supplied by the parent; independently enforce Profile READ or originating-Unit Admin. Avoid N+1 report reads | Field authorization and pagination tests |
| `tofu/application/modules/appsync/datasources_lambda.tf` | Existing Lambda data sources | Add new domain handlers; remove legacy report sources only after parity | Invoke-policy and resolver wiring tests |
| `tofu/application/modules/appsync/datasources_dynamodb.tf` | One source per existing table | Add sources only for tables used directly by AppSync JS/VTL. Lambda-only tables do not need AppSync data sources | `test_iam_appsync_dynamodb_policy.py`, no-Scan invariant |
| `tofu/application/appsync/js-resolvers/lambda_unit_resolver.js` and `lambda_passthrough_resolver.js` | Forward `__isError` and `errorCode` | Forward only explicitly authorized conflict details/subcodes such as `OPERATION_TOO_LARGE`; do not leak internal data | Resolver tests and safe error-extension tests |

**Schema compatibility:** there are no production users, so there is no production data migration or backfill. Create all new rows natively and discard/recreate pre-production test data as needed. Output defaults are needed only for any retained development/test fixtures. Existing money `Float` behavior remains unchanged for legacy Orders; new Show & Sell money uses integer cents.

### 3.2 Existing Order creation and update files

| File | Current behavior | Required change | Tests/validation |
| --- | --- | --- | --- |
| `tofu/application/appsync/js-resolvers/create_order_fn.js` | Validates input/enriches catalog and performs one Order Put | Default `fulfillmentMode = NONE`; stamp origin and fulfillmentVersion; create stable line IDs/zero fulfilled counts; custody mode uses one atomic cross-table write, not additional independent pipeline writes; use new `FORBIDDEN`/`NOT_FOUND` semantics | `create_order_fn.test.js`, `create_order_fn.guard.test.ts`, `create_order_fn.sanitize.test.ts`, integration order tests |
| `tofu/application/appsync/js-resolvers/get_campaign_for_order_fn.js` | Finds Campaign through GSI | Follow with strongly consistent `{profileId, campaignId}` read before using origin/catalog/membership | Authoritative-origin and cross-catalog tests |
| `tofu/application/appsync/js-resolvers/lib/line_items.js` | Shared create/update/public line enrichment | Add line IDs/zero fulfillment for new rows while preserving existing-line IDs/counts on update; keep legacy money semantics | `lib/line_items.test.js`, `order_line_items_shared_path.test.ts`, public-order parity |
| `tofu/application/appsync/js-resolvers/update_order_fn.js` | Replaces lineItems wholesale | Preserve stable IDs and fulfilled counts for unchanged lines; reject/reconcile edits that invalidate existing fulfillment; non-line edits leave origin/history unchanged | `update_order_fn.test.js`, `update_order_fn.guard.test.ts`, `update_order_fn.expression_names.test.ts`, post-fulfillment edit policy tests |
| `tofu/application/appsync/js-resolvers/create_public_order_fn.js` | Public two-action transaction using shared helper | Give new public rows native line IDs/zero fulfillment/version and capture immutable origin from the already validated joined Campaign (or null for an independent Campaign); never expose custody mode or consume inventory anonymously. Origin retention keeps unfulfilled public Orders in the correct Council demand without exposing new API-key fields | `create_public_order_fn.test.js`, `test_public_order_write_path.py`, public integration tests |
| `tofu/application/appsync/js-resolvers/query_order_fn.js`, `return_order_fn.js`, `query_orders_by_campaign_fn.js` | Authorized raw Order reads | Return new fields with backward-compatible defaults and participant-safe fulfillment data | `orderQueries.integration.test.ts` and participant output tests |
| `tofu/application/modules/appsync/functions_orders.tf`, `resolver_code_hashes.tf` | Existing createOrder pipeline/hash triggers | Update for the chosen atomic createOrder implementation; preserve resolver-only hash triggers and avoid shared-function taint | `test_appsync_pipeline_functions.py`, `test_ephemeral_deploy_resolver_parity.py` |

**Catalog invariant to enforce:** a joined Scout Campaign and its Unit Campaign must have a defined catalog relationship. Prefer enforcing catalog identity at join time; otherwise joined sales could use product IDs/prices from one catalog while originating in another. Do not leave this to a frontend assumption.

### 3.3 Catalog identity and usage integrity

Current catalog editing also threatens the stable-product-ID requirement and must be changed before inventory records reference products:

| File | Current behavior | Required change | Tests/validation |
| --- | --- | --- | --- |
| `tofu/application/schema/schema.graphql` (`ProductInput`) | Product update input has no productId | Add optional `productId` for existing products and define server behavior for unknown IDs; creation of a genuinely new product still generates an ID | Schema/input contract tests |
| `frontend/src/components/CatalogEditorDialog.tsx` | Omits product IDs from update payloads | Preserve existing product IDs in hidden update fields and include IDs only for existing products | Catalog editor update/preservation tests |
| `tofu/application/appsync/mapping-templates/update_catalog_request.vtl` | Replaces the product list and generates replacement IDs | Preserve IDs for existing products and generate IDs only for new products; reject an unknown productId rather than silently reidentifying a product | `tests/unit/catalog_request_vtl.test.ts`, catalog update integration tests |
| `tofu/application/appsync/js-resolvers/update_campaign_fn.js` | Writes a changed `catalogId` unconditionally | For a joined Scout Campaign, reject catalog changes that would violate the Unit Campaign catalog relationship; a join-time check alone is insufficient | `update_campaign_fn.test.js`, post-join catalog-drift tests |
| `tofu/application/appsync/js-resolvers/check_catalog_usage_fn.js` and `check_shared_campaign_usage_fn.js` | Check only legacy Campaigns/SharedCampaigns before catalog soft deletion | Add UnitCampaign usage checks using the new `catalogId-index`; a catalog referenced by any Unit Campaign cannot be soft-deleted as unused | `test_admin_catalog_operations.py`, `check_catalog_usage` and UnitCampaign-reference tests |
| `tofu/application/modules/dynamodb/main.tf` (`unit_campaigns`) | Initial proposed indexes omit catalog usage | Add `catalogId-index` to support the soft-delete usage guard without a Scan | `test_table_schemas.py`, IAM/query contract, `test_ephemeral_reliability.py` |

Stable `productId` is now an explicit backward-compatibility constraint: current update behavior can orphan future inventory/custody/allocation/fulfillment rows. Existing `productName` remains display text only and is never the identity key.

### 3.4 Backend helper layer

| File | Required change | Tests/validation |
| --- | --- | --- |
| `src/utils/dynamodb.py` | Add five table accessors/environment mappings. Add or pair with focused transaction helpers for 90-action plans, conditional idempotency markers, retries, and transaction-specific error classification | `test_dynamodb_utils.py`, environment override/reset tests, transaction/fault-injection tests |
| `src/utils/pagination.py` | Add default-50/max-100 opaque scope/filter-bound cursor pagination. Account for DynamoDB `Limit` before filter expressions and never silently truncate | `test_pagination.py`, cursor tamper/replay/isolation tests |
| `src/utils/errors.py` | Add `RATE_LIMIT_EXCEEDED` and authorized `OPERATION_TOO_LARGE` detail semantics while preserving canonical codes | `test_errors.py`, safe-details tests |
| `src/utils/handlers.py` | Preserve safe conflict details if required; never serialize arbitrary internals | `test_handlers.py`, error-shape/fallback tests |
| `src/utils/appsync_types.py` | Add strict integer, cents, version, timestamp, timezone, idempotency, bounded-text validators instead of loose coercion | `test_appsync_types.py` |
| `src/utils/auth.py` | Preserve current Profile authorization; add a focused `src/utils/unit_auth.py` for consistent Unit-grant checks and resource-derived tenancy | `test_auth.py`, new `test_unit_auth.py`, cross-Unit/global-ADMIN isolation |
| `src/utils/ids.py` | Keep `build_unit_campaign_key` for legacy reporting only. Add stable-ID validation for new entities; never derive Unit identity from metadata | ID normalization and identity-retention tests |
| `src/utils/payment_methods.py` | Reuse QR type/size/signature helpers but add Unit-scoped ownership/key handling rather than substituting Unit IDs for account IDs | `test_payment_methods.py`, `test_payment_methods_handlers.py`, Unit QR scope tests |

### 3.5 Suggested new backend modules

These are new responsibilities, not existing files:

- `src/handlers/unit_operations.py`: Units, grants, invites, settings, payment methods, QR operations.
- `src/handlers/unit_campaign_operations.py`: Unit Campaigns, join previews, roster, catalog.
- `src/handlers/inventory_operations.py`: balances, movements, custody, issue/return, individual fulfillment/reversal.
- `src/handlers/show_and_sell_operations.py`: events, allocations, slots/signups, sales, We Owe, finalization/reopening.
- `src/handlers/participant_data.py`: participant-safe opportunities, commitments, custody, credit/pending, calendar data.

Each new handler must use existing structured logging, error decorator behavior, domain-role IAM, and 100% coverage requirements. New role-scope tests must record actual botocore calls, including table names nested inside `TransactItems`.

## 4. DynamoDB, Lambda, IAM, and environment impact

### 4.1 Tables and outputs

`tofu/application/modules/dynamodb/main.tf` currently has nine tables. Add:

| Table | Required contents/indexes |
| --- | --- |
| `units` | Unit metadata/grants/payment methods/invites/bootstrap markers; `accountId-unitId-index`, `unitId-createdAt-index`, `metadataKey-createdAt-index`; UnitInvite TTL on `expiresAtEpoch` |
| `unit_campaigns` | Metadata/membership/join pointers/commitments/guards/Scout totals; `unitId-createdAt-index`, `campaignId-index`, `profileId-unitCampaignId-index`, `catalogId-index` |
| `inventory` | Balances/allocations/custody/movements; `showAndSellId-index`, `profileId-unitCampaignId-index`, optional `movementType-occurredAt-index` |
| `show_and_sells` | Events/slots/signups/sales/revisions/finalizations/credits/We Owe/fulfillments; `unitCampaignId-startAt-index`, `saleId-index`, `weOweId-index`, `campaignId-status-index`, `unitCampaignId-status-index` |
| `order_fulfillments` | Fulfillment/reversal records with deterministic `REVERSAL#<originalId>`; optional `campaignId-createdAt-index` |

Also:

- Add all five to `table_arns` and `table_names`.
- Add individual outputs `units_table_name`, `unit_campaigns_table_name`, `inventory_table_name`, `show_and_sells_table_name`, `order_fulfillments_table_name`.
- Reuse existing PITR, deletion protection, encryption, tagging, and lifecycle variables. Prod PITR must remain enabled through the existing input.
- Add a common seven-day idempotency-marker TTL convention, using a numeric epoch attribute; do not confuse it with UnitInvite TTL.

### 4.2 Lambda and IAM wiring

| File | Required change | Constraints/tests |
| --- | --- | --- |
| `tofu/application/modules/lambda/main.tf` | Add function entries/handler paths and five table-name environment variables. Map every new non-admin function to a domain role; keep static log-group keys | `test_monolithic_role_retirement.py`, `test_iam_appsync_lambda_policy.py`, no fallback role |
| `tofu/application/modules/iam/main.tf` | Add scoped Unit/Unit Campaign/inventory/Show & Sell roles and inline policies. Add `dynamodb:TransactWriteItems` wherever transactions execute, including AppSync direct paths and account purge if needed | `test_iam_appsync_dynamodb_policy.py`, domain role-scope tests, actual `TransactItems` table capture, no Scan |
| `tofu/application/environments/dev/main.tf`, `prod/main.tf`, `ephemeral/main.tf` | Add five entries to Lambda `table_names` and all required `lambda_domain_role_arns` entries. Existing map-driven AppSync plumbing already supplies table maps/function ARNs | All three environments must plan successfully with no missing role |
| `src/utils/dynamodb.py` | Add five accessors matching environment variables | `test_dynamodb_utils.py` |
| `scripts/ephemeral-env.sh` | Export the five names in `up` and `env` branches for direct-SDK cleanup | Script/env contract tests and shellcheck |
| `tofu/application/modules/appsync/datasources_dynamodb.tf` | Add only data sources needed by direct AppSync resolvers | No-Scan IAM contract and resolver wiring |

IAM notes:

- Adding tables to `table_arns` expands broad admin/AppSync resource lists automatically, but does not expand scoped domain-role lists.
- `ConditionCheckItem` is not permission to invoke `TransactWriteItems`.
- The existing public-order path already emits transactions and should be revalidated when the AppSync policy is updated; do not assume the current action list is correct.
- Unit QR roles need scoped Get/Put/Delete permissions on a dedicated Unit QR prefix, not `reports/*`.
- No new Cognito admin permissions are needed, and global ADMIN is not a Unit access mechanism.

### 4.3 Unit QR storage

Current account QR keys use `payment-qr-codes/<accountId>/...`. Unit methods need a separate explicitly authorized scheme, for example:

```text
payment-qr-codes/units/<unitId>/<paymentMethodId>/<filename>
```

That is an implementation key contract, not a Unit authorization mechanism by itself. Every upload/confirm/delete/download must still load the method and check the current Unit grant.

Reuse the existing exports bucket so `frontend/index.html` CSP requires no change. `tests/unit/test_exports_bucket_lifecycle.py` must distinguish QR retention from retired `reports/` output.

### 4.4 Unit-invite redemption throttle persistence

Reuse `public_order_throttles` with a separate key contract rather than creating a new table or sharing the public-order share-token counter:

```text
key = UNIT_INVITE_REDEMPTION#<accountId>#WINDOW#<yyyy-MM-ddTHH>
```

This uses the table's actual single `key` hash-key and existing `expiresAt` TTL attribute. Store `attempts`, `createdAt`, `updatedAt`, and `expiresAt` with at least a one-hour TTL. Only failed redemption attempts increment the counter; attempt 11 in the same UTC hour returns `RATE_LIMIT_EXCEEDED`. Successful redemption and a valid replay of an already-completed idempotent request do not increment it. Unit-invite handler roles need scoped read/update access to this table, while public-order handlers and existing throttle keys remain unchanged. Add fixed-window, attempt-11, success-not-counted, retry-not-counted, TTL, IAM-scope, and concurrent-increment tests.

Also add `PUBLIC_ORDER_THROTTLES_TABLE_NAME` to `tofu/application/modules/lambda/main.tf` `local.common_env`, add the individual output to `tofu/application/modules/dynamodb/main.tf` and the manually enumerated environment `table_names` maps, add `tables.public_order_throttles` to `src/utils/dynamodb.py`, and update `tests/unit/conftest.py`, `tests/unit/test_dynamodb_utils.py`, and `.env.example` with the new optional override. Environment-variable visibility does not replace scoped IAM permissions.

## 5. Frontend impact

### 5.1 Routes, navigation, and authorization

| File | Required change | Tests/validation |
| --- | --- | --- |
| `frontend/src/AuthedRoutes.tsx` | Add lazy Cognito-protected Unit/Unit Campaign/inventory/Show & Sell/We Owe/finalization/report routes using stable IDs | New route and nested-route tests, protected anonymous behavior |
| `frontend/src/components/AppLayout.tsx` | Add new navigation. During Stage 8, stop gating Campaign Reports solely on the caller having created a SharedCampaign | `AppLayout.test.tsx`, mobile/navigation E2E |
| `frontend/src/pages/HomePage.tsx` and `SettingsPage.tsx` | Add Unit/inventory/event quick actions only where appropriate for the caller's current grants | `HomePage.test.tsx`, `SettingsPage.test.tsx` |
| `frontend/src/contexts/AuthContext.tsx` and `types/auth.ts` | Keep global `isAdmin` separate from new Unit access. Load Unit grants separately; never add Unit roles to the JWT or use global ADMIN as a shortcut | `AuthContext.test.tsx`, grant-revocation and Account-switch tests |
| `frontend/src/components/ProtectedRoute.tsx` | Continue enforcing Cognito authentication/global-admin behavior only; do not use it as a Unit Admin guard | `ProtectedRoute.test.tsx` |
| `frontend/src/lib/apollo.ts` | Use `network-only` for grant/report data and inspect Apollo `error` as well as thrown errors. Consider clearing the store on sign-out/Account change so revoked data cannot survive | `lib/apollo.test.ts`, cache/revocation tests |
| `frontend/src/lib/ids.ts` | Follow current `ensure*Id`/`toUrlId` pattern for stable route IDs | ID/route validation tests |

**CloudFront constraint:** no SPA route or public asset may begin with lowercase `/l`; CloudFront `/l*` belongs to Cognito. Do not use `/locations`, `/ledger`, or similar routes. `/units`, `/inventory`, `/show-and-sells`, and `/we-owe` are safe examples.

### 5.2 Existing frontend behavior to extend or preserve

| File | Required change | Tests/validation |
| --- | --- | --- |
| `frontend/src/pages/OrderEditorPage.tsx` and `hooks/useOrderForm.ts` | Add custody mode only for eligible joined Campaigns, display advisory custody, preserve stable line IDs, show fulfilled/unfulfilled results, and handle idempotency/version errors | `OrderEditorPage.test.tsx`, `OrderEditorPage.interactions.test.tsx`, `useOrderForm.test.ts`, `test_smoke_order.py` |
| `frontend/src/pages/OrdersPage.tsx` | Show fulfilled/unfulfilled quantities and participant-safe history; keep public-order payment behavior unchanged | `OrdersPage.rowActions.test.tsx`, `OrdersPage.confirmPayment.test.tsx`, order integration tests |
| `frontend/src/pages/CampaignSummaryPage.tsx` and `components/CampaignSummaryTiles.tsx` | Stop assuming the first Order page is complete. Clearly distinguish individual summaries from approved Show & Sell credit; do not mix personal and Unit payment methods without a product decision | `CampaignSummaryPage.test.tsx`, campaign-tab E2E |
| `frontend/src/pages/CreateCampaignPage.tsx` and `components/CatalogSelect.tsx` | Add limited Unit Campaign join preview and post-create `joinUnitCampaign`; keep independent Campaign creation and catalog selection working | CreateCampaign component/hook tests and `test_smoke_campaign.py` |
| `frontend/src/pages/ScoutManagementPage.tsx` | Preserve SellerProfile invites; do not reuse them for Unit Admin grants | Existing profile-sharing tests |
| `frontend/src/pages/AcceptInvitePage.tsx` | Add a distinct Unit redemption flow or explicit invite-type choice, with idempotency and `RATE_LIMIT_EXCEEDED`; Unit output is a grant, not a Share | New Unit invite acceptance tests, consumed/expired/revoked/throttle cases |
| `frontend/src/pages/PaymentMethodsPage.tsx` and `lib/paymentMethodValidation.ts` | Keep personal payment methods unchanged. Build a separate Unit payment UI with Other reserved, 100-character names, 50 active methods, active/inactive state, stable IDs, and Unit QR flow | Existing personal-payment tests plus new Unit payment tests |
| `frontend/src/components/QrCodeImage.tsx` | Support online fetch/data-URL embedding for offline print snapshots and expiry/error handling; do not leave only a pre-signed URL in printed output | `QrCodeImage.test.tsx`, offline QR tests |
| `frontend/src/pages/ReportsPage.tsx` | Replace one-page loading with shared complete loading while preserving current table/export behavior | `reportExport.test.ts`, `test_smoke_reports.py`, `test_smoke_report_download.py` |
| `frontend/src/pages/CampaignReportsPage.tsx` | Replace `getUnitReport` aggregation with `listMyProfiles`/`listMyShares` discovery and complete Campaign/Order pagination. Preserve Unit Summary, Seller Report, and Order Details parity | `CampaignReportsPage.xlsx-sanitize.test.tsx`, `test_smoke_campaign_reports.py`, legacy golden-parity tests |
| `frontend/src/lib/reportExport.ts` | Reuse sanitization/export approach but normalize through shared browser report models/writers | Parsed CSV/XLSX content, formula sanitization, URL cleanup tests |
| `frontend/index.html` | No CSP change if the existing exports bucket is reused. A new image host would require explicit CSP/test changes | `test_edge_security.py`, `test_index_html_carries_the_only_site_csp` |

### 5.3 Frontend test/coverage constraints

`frontend/vite.config.ts` currently enforces approximately 99% lines, 97% functions, 96% branches, and 97% statements. New report loaders/assemblers/writers and pages must be covered by pure tests plus Playwright for browser-unreachable flows. Do not paper over gaps with ignore comments. Frontend complexity controls also apply.

## 6. Reporting migration and retirement impact

### 6.1 Legacy files to deprecate and later retire

| File/resource | Required change |
| --- | --- |
| `src/handlers/campaign_reporting.py` | Deprecate for new development; retire after browser parity. Do not turn it into the new Unit Admin raw-data API |
| `src/handlers/report_generation.py` | Deprecate Python CSV/XLSX generation/S3 output; retire after parity |
| `src/utils/report_limits.py` | Retire with the two legacy handlers if no other user remains |
| `tofu/application/modules/appsync/resolvers_queries.tf` / `resolvers_mutations.tf` | Remove `getUnitReport` and `requestCampaignReport` only after parity |
| `tofu/application/modules/appsync/datasources_lambda.tf` | Remove legacy data sources only after their resolvers are gone |
| `tofu/application/modules/lambda/main.tf` and all environment role maps | Remove `request-report` and `unit-reporting` only after parity |
| `tofu/application/modules/iam/main.tf` | Remove genuinely obsolete report write/presign permissions while retaining necessary historical report deletion and all QR permissions |
| `tofu/application/modules/s3/main.tf` | Remove report-only current-object expiration only if no report artifacts remain; retain the bucket and QR lifecycle/cleanup |
| `pyproject.toml` and `uv.lock` | Reassess `openpyxl` after backend generation retires; move to dev if Python E2E still parses browser XLSX |
| `tests/integration/resolvers/requestCampaignReport.integration.test.ts` and report smoke tests | Preserve until parity, then remove/replace with browser parity tests |

`list_unit_catalogs.py` is not a report generator and is not removed by the browser-reporting decision. It must not be reused as stable-Unit authorization.

**Hidden dependency:** `list_catalogs_in_use.py` imports `_ORDER_QUERY_CONCURRENCY` and `_PROFILE_BATCH_LIMIT` from `campaign_reporting.py`. Move those constants to a neutral helper before deleting `campaign_reporting.py`, with updates to `test_list_catalogs_in_use.py` and its integration test.

### 6.2 Static architecture guard

Add a Phase 1 guard, for example `tests/unit/check_browser_only_reporting.test.ts`, which:

- temporarily allowlists only `getUnitReport` and `requestCampaignReport`;
- rejects every additional report/document/ICS resolver, report-download type/URL, Lambda report writer, or S3 report output;
- narrowly permits `unitPaymentMethodQrDownloadUrl` and `showAndSellSignupCalendarData` as non-report data;
- fails on synthetic prohibited additions immediately, not only after legacy retirement.

## 7. Deletion and data-lifecycle impact

### 7.1 Order fulfillment must precede Order deletion

Update every hard-delete path:

- `src/handlers/campaign_operations.py` (`delete_orders_for_campaign`)
- `src/handlers/delete_profile_cascade.py` (its independent order collection/deletion)
- `tofu/application/appsync/js-resolvers/delete_order_fn.js` and its pipeline in `resolvers_mutations.tf`
- Account/profile purge code in `deletion_cascade.py` and `admin_account_purge.py`

Append-only `OrderFulfillment` and reversal children must be deleted before the Order, with strongly consistent verification where current code uses it. IAM for `delete-campaign-orders` and `delete-profile-cascade` must include the new table access actually used.

### 7.2 Joined Scout Campaign deletion

The ordinary `deleteCampaign` pipeline in `tofu/application/modules/appsync/resolvers_mutations.tf` currently deletes Orders and the Campaign, then updates legacy latest-campaign state. It has no knowledge of UnitCampaignMembership, ScoutCampaignMembershipGuard, commitments/signups/work, custody, credit projections, or Unit Campaign roster status. Deleting a joined Campaign would otherwise leave an ACTIVE membership/guard pointing at a nonexistent Campaign and could block future joins.

Before changing the pipeline, define one explicit policy: block joined Campaign deletion while any dependent record exists, or implement a complete ordered cascade for those dependents. The safe default is to reject with `CONFLICT` and require the Kernel to reconcile custody and other dependent records first. If only an inert membership remains, cleanup must remove membership and guard state transactionally before deleting the Campaign. Do not use ordinary membership removal as proof that hard-deletion dependencies are gone.

Update `delete_order_fn`/`deleteCampaign` wiring, `test_appsync_pipeline_functions.py`, campaign integration tests, and `test_campaign_operations.py`. Cover ACTIVE membership, commitments, custody, credit history, inert-membership-only cleanup, failure at every step, and non-target Campaign preservation.

### 7.3 Account and profile deletion policy gaps

**Decision required before implementation: final Unit Admin.** If an Account is the sole grant holder for a Unit, deleting the Account/grant would violate the Unit invariant. The design must choose and test one of:

1. **Recommended safe default:** block account deletion with `CONFLICT` until another Unit Admin is added or the Unit is explicitly deleted through a separate, fully defined Unit deletion flow.
2. Transfer administration before continuing account deletion.
3. Delete the Unit through a fully defined production cascade that also handles every dependent record and does not preserve it accidentally.

Do not silently delete the grant, leave `adminCount` stale, or use the test-only Unit cascade in production. Evaluate this preflight before deleting unrelated account data, because the overall account cascade is not globally atomic.

**Also decide:** how profile deletion handles outstanding With Scout stock. The safe default is to require returning/selling custody before profile deletion or to provide an explicit return-to-Unit step before proceeding.

Production membership removal and hard profile deletion are different: removal intentionally preserves history, while hard deletion needs a documented policy for memberships/guards, commitments/signups/work, custody, credit projections, and fulfillments.

### 7.4 Files and tests affected by deletion changes

- `src/handlers/deletion_cascade.py`
- `src/handlers/account_operations.py`
- `src/handlers/admin_account_purge.py`
- `src/handlers/campaign_operations.py`
- `src/handlers/delete_profile_cascade.py`
- `frontend/src/hooks/useAccountDeletion.ts`
- `frontend/src/components/settings/AccountDeletionDialog.tsx`
- `frontend/src/pages/AdminPage.tsx`
- `frontend/src/pages/UserDataPage.tsx` only if global-admin visibility is separately authorized

Tests:

- `tests/unit/test_account_deletion_cascade.py`
- `tests/unit/test_account_operations.py`
- `tests/unit/test_admin_operations.py`
- `tests/unit/test_campaign_operations.py`
- `tests/unit/test_delete_profile_cascade.py`
- `tests/unit/test_campaign_role_dynamodb_scope.py`
- `tests/unit/test_profile_sharing_role_scope.py`
- `frontend/tests/AdminPage.interactions.test.tsx` (currently asserts exact mutation order)
- `frontend/tests/hooks/useAccountDeletion.test.ts`
- `frontend/tests/AccountDeletion.test.tsx`
- `tests/e2e/test_smoke_account_deletion.py`
- `tests/e2e/test_smoke_admin.py`
- `tofu/application/appsync/js-resolvers/delete_order_fn.test.js`
- `tests/integration/resolvers/adminOperations.integration.test.ts`

Preserve existing semantics: Catalogs are never deleted, account/Cognito purge remains last, failed lookups never produce a partial “successful” cleanup, and global Admin does not automatically have Unit authorization for cleanup.

## 8. Ephemeral recovery, deployment, and CI impact

### 8.1 Recovery and deploy files

| File | Required change | Tests/validation |
| --- | --- | --- |
| `scripts/ephemeral-recover-common.sh` | Add all five table slugs and every new IAM role/attachment/inline-policy import | `test_ephemeral_reliability.py::test_dynamic_resource_import_coverage` |
| `scripts/ephemeral-env.sh` | Export new table names and preserve existing build/deploy behavior | Script/shellcheck tests |
| `scripts/appsync-ensure-resolver-order.sh` | Continue deriving function/data-source deletions automatically; do not reintroduce target lists | `test_ephemeral_deploy_resolver_parity.py` |
| `scripts/build-resolvers.mjs` and `tofu/application/appsync/dist/` | Build source resolvers before every tofu plan/apply/import/destroy; never edit dist manually | `build_resolvers.test.ts`, `check_esbuild_pinning.test.ts`, `check_templatefile_escaping.test.ts` |
| `.github/workflows/ci.yml` | Add static security/browser-reporting guards, OpenTofu validation, and new test jobs. Add any new shell scripts explicitly to shellcheck coverage | CI guard tests and `check_shellcheck_coverage.test.ts` |
| `.github/workflows/ephemeral-test.yml` | Add lane-aware acceptance only after provisioning/leases/cleanup exist; keep legacy serial tests until migrated | Parallel isolation, no cross-lane cleanup, strict cleanup errors |
| `.github/workflows/deploy-shared.yml` | Keep legacy smoke until migrated; production Show & Sell smoke scope requires a separate explicit decision | Production-safe scope review and secret-free evidence |

All new AppSync JS must pass `check_appsync_js_compatibility.test.ts`. New `templatefile()` users must satisfy escaping coverage; prefer `file()` unless table injection is genuinely necessary.

### 8.2 Test cleanup and provisioning files

| File | Required change |
| --- | --- |
| `tests/integration/globalTeardown.ts` | Extend resource coverage for legacy migration but do not use it for active lane-aware suites; it currently has global/account-wide and partly single-page behavior |
| `tests/e2e/conftest.py` | Add an opt-in bypass only for marked lane-aware suites; preserve legacy pre/post cleanup for unmarked tests |
| `tests/integration/vitest.config.ts` | Keep legacy serial behavior. Create a separate lane-aware config/command without globalTeardown rather than enabling parallelism globally |
| `tests/integration/vitest.cleanup.config.ts` | Retain for legacy/manual cleanup |
| `tests/integration/setup/testData.ts` and `resourceTracker.ts` | Extend new resource types and ensure cleanup failures are not swallowed |
| `tests/e2e/utils/auth.py` and `tests/integration/setup/apolloClient.ts` | Add lane persona clients rather than reusing only owner/contributor/readonly fixtures |
| `scripts/create-test-users.sh` and `create-ephemeral-test-users.sh` | Add lane persona provisioning or call a dedicated lane provisioner without changing existing roles or credential-safety rules |
| `tests/integration/setup.ts` | Support lane credentials only through approved secret/env handling; preserve managed/unmanaged key classification in `test_generate_integration_env.py` |
| `.env.example` | Add optional new table overrides and lane configuration only, never credentials |
| `pyproject.toml` and `uv.lock` | Add `pytest-xdist` if selected and update the lock together for CI |
| `AGENTS.md` | After implementation, add only durable non-obvious invariants: five-table cleanup, transaction IAM, final-admin policy, test-only Unit cascade, lane cleanup, and report retirement distinction |

Current E2E ordered module state and integration single-thread settings mean `pytest -n` must not simply be enabled for the whole existing suite.

## 9. Test files requiring direct updates or new fixtures

### 9.1 Existing order/resolver tests

- `tofu/application/appsync/js-resolvers/create_order_fn.test.js`
- `tofu/application/appsync/js-resolvers/update_order_fn.test.js`
- `tofu/application/appsync/js-resolvers/lib/line_items.test.js`
- `tofu/application/appsync/js-resolvers/create_public_order_fn.test.js`
- `tofu/application/appsync/js-resolvers/delete_order_fn.test.js`
- `tests/unit/order_line_items_shared_path.test.ts`
- `tests/unit/create_order_fn.guard.test.ts`
- `tests/unit/create_order_fn.sanitize.test.ts`
- `tests/unit/update_order_fn.guard.test.ts`
- `tests/unit/update_order_fn.expression_names.test.ts`
- `tests/unit/test_public_order_write_path.py`
- `tests/integration/resolvers/orderOperations.integration.test.ts`
- `tests/integration/resolvers/orderQueries.integration.test.ts`
- `tests/integration/resolvers/publicOrders.integration.test.ts`
- `tests/integration/resolvers/run_payload_as_users.integration.test.ts`

### 9.2 Schema, IAM, infrastructure, and helper tests

- `tests/unit/table_schemas.py` and `test_table_schemas.py`: add five mock table definitions and change hardcoded table counts/keys/TTL assertions.
- `tests/unit/conftest.py`: add new table environment values and fixtures.
- `tests/unit/test_dynamodb_utils.py`: add accessors, missing-env/custom-name/override/reset, and transaction-helper coverage.
- `tests/unit/test_pagination.py`: scoped cursor and filtered-page behavior.
- `tests/unit/test_errors.py` and `test_appsync_types.py`: new code/validators.
- `tests/unit/test_iam_appsync_dynamodb_policy.py`: add transaction action while retaining no-Scan.
- `tests/unit/test_iam_appsync_lambda_policy.py`: verify invoke set for new functions with no wildcard.
- `tests/unit/test_monolithic_role_retirement.py`: require every new function to have a domain role in all environments.
- `tests/unit/test_ephemeral_reliability.py`: dynamically require all new imports.
- `tests/unit/check_public_api_key_surface.test.ts` and `test_public_api_key_surface.py`: keep new fields off API-key surface.

### 9.3 Reporting and retirement tests

- `tests/unit/test_campaign_reporting.py`
- `tests/unit/test_report_generation.py`
- `tests/unit/test_report_limits.py`
- `tests/unit/test_list_catalogs_in_use.py`
- `tests/unit/test_account_reporting_role_scope.py`
- `tests/unit/test_exports_bucket_lifecycle.py`
- `tests/integration/resolvers/requestCampaignReport.integration.test.ts`
- `tests/e2e/test_smoke_campaign_reports.py`
- `tests/e2e/test_smoke_reports.py`
- `tests/e2e/test_smoke_report_download.py`
- `frontend/src/lib/reportExport.test.ts`

Preserve these until parity, then remove or replace with raw-data/browser parity tests. Do not delete tests before equivalent security and output coverage exists.

### 9.4 New test suites to add

- `tests/unit/test_unit_operations.py`
- `tests/unit/test_unit_campaign_operations.py`
- `tests/unit/test_inventory_operations.py`
- `tests/unit/test_order_fulfillment.py`
- `tests/unit/test_show_and_sell_operations.py`
- `tests/unit/test_show_and_sell_finalization.py`
- `tests/unit/test_unit_auth.py`
- `tests/unit/test_idempotency.py`
- Domain-specific role-scope tests for Unit, inventory, and Show & Sell handlers
- `tests/integration/resolvers/unitOperations.integration.test.ts`
- `tests/integration/resolvers/unitCampaignOperations.integration.test.ts`
- `tests/integration/resolvers/inventoryOperations.integration.test.ts`
- `tests/integration/resolvers/showAndSellOperations.integration.test.ts`
- `tests/integration/resolvers/browserReportingData.integration.test.ts`
- Lane lease/quarantine/cleanup/scheduler tests
- Browser loader/assembler/writer tests and artifact parsers

## 10. Recommended implementation order

Production data migration is explicitly out of scope. The order below exists to avoid breaking current code and deployment paths, not to migrate production data.

1. **Foundation artifacts:** schema, five tables, environment maps, Unit auth, strict validation, transaction/idempotency/cursor helpers, and CI guards.
2. **Standalone Units:** grants/invites, Unit payment methods/QR, Unit Campaigns, and roster guards. Resolve the joined-Campaign catalog invariant and authoritative Campaign reads before Order changes.
3. **Inventory/custody:** balances and movements, then atomic `createOrder` custody mode and fulfillment/reversal with stable line identity and safe update behavior.
4. **Events:** allocation, slots/commitments, sales, We Owe, finalization versions, and reopening.
5. **Raw reporting data and browser engine:** complete pagination and security projections, followed by legacy report parity.
6. **Lifecycle integration:** Order fulfillment deletion, Unit/grant cleanup, production deletion policy, and test-only Unit cascade.
7. **Retirement after parity:** remove legacy schema/handlers/S3 write/presign/IAM paths and obsolete tests while preserving historical report cleanup and QR behavior.
8. **Scale readiness:** lane provisioning, lane-scoped cleanup, concurrency/performance validation, and explicit production-smoke approval.

Do not add custody writes to the current `createOrder` pipeline as independent post-write steps, use GSIs for authoritative access/stock/membership checks, expose admin fields in participant types, or retire `campaign_reporting.py` before moving its shared constants.

## 11. Remaining decisions to settle before implementation

| Decision | Recommended safe default | Why it matters |
| --- | --- | --- |
| Account deletion when the Account is the final Unit Admin | Block with `CONFLICT` until another admin is added or the Unit is explicitly deleted through a separate governed flow | Prevents orphaned Units and preserves `adminCount >= 1` |
| Joined Scout Campaign deletion | Block with `CONFLICT` while any membership/commitment/custody/credit/fulfillment dependency remains; allow only an inert-membership cleanup or a separately designed complete cascade | Prevents ACTIVE guards and roster/history records referencing a deleted Campaign |
| Profile deletion with outstanding With Scout stock | Require return/sale of custody or an explicit return-to-Unit step before deletion | Prevents stock disappearing with the SellerProfile |
| Editing an individual Order after fulfillment exists | Preserve line IDs and fulfilled counts; reject edits that would make fulfilled quantity invalid or require a separate audited correction path | Prevents accidental fulfillment-history erasure |
| Joined Campaign catalog relationship | Enforce catalog identity at join time rather than allowing product/price identity to drift | Keeps Order origin, inventory product IDs, and prices consistent |
| Idempotency-marker TTL | Use one numeric epoch-seconds attribute representing seven days across all aggregate tables | Allows consistent marker retention and cleanup without a new table |

These are the only decisions in this map that should not be left to accidental resolver behavior. Everything else has a concrete implementation and validation path.
