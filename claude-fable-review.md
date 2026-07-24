# KernelWorx Comprehensive Review

**Date:** 2026-07-24 · **Reviewed at:** `c70efd1` (branch `fix/dynamodb-aws-owned-key`)

Conducted by eight specialist reviews run in parallel: Python standards, TypeScript standards, OpenTofu standards, security, SRE/infrastructure reliability, dead code, correctness bugs, and documentation accuracy + maintainability. All findings below were verified against the actual code (linters, `tofu validate`, `tsc`, and pytest were run where applicable). Findings that multiple reviewers independently reported are merged and noted.

**Headline:** the product code is in decent shape (auth checks are consistent, IAM is well-scoped, no XSS/IDOR found, the DynamoDB encryption commit `c70efd1` is correct), but three systemic problems cut across everything: (1) **silently truncated DynamoDB pagination** corrupts deletes and money reports at scale; (2) **the CI quality gates are largely illusory** — frontend typecheck checks 0 files, the test wrapper can exit 0 on a hung suite, and several guard tests are never executed by any runner; (3) **the documentation actively misleads** — it describes a single-table/7-Lambda/CDK architecture that doesn't exist and routes developers to a stale, broken tofu root.

---

## Must Fix

### MF-1. DynamoDB queries silently truncate at 1 MB — data loss in deletes, wrong totals in money reports
`src/handlers/admin_operations.py:819-828, 851-858, 884-900, 935-942, 968-975, 1109-1113, 1122-1127` · `src/handlers/report_generation.py:170-182` · `src/handlers/campaign_reporting.py:99-102, 184` · `src/handlers/profile_sharing.py:225` · `src/handlers/list_unit_catalogs.py:35-39, 86-90, 170-174`
*(found independently by the Python, bugs, and SRE reviews)*

None of these queries (and the profiles-table `scan` in `list_unit_catalogs`) follow `LastEvaluatedKey`. Consequences once any result set exceeds 1 MB:

- `deleteMyAccount` / admin GDPR-style deletes remove only the first page of orders/campaigns/shares, then delete the account — permanently orphaned rows with no owner and no way to reach them again.
- Excel/CSV campaign exports and unit financial reports silently omit orders — **understated `totalSales`/`orderCount` presented as successful reports**, with no error signal.
- Units whose profiles land past the first scan page get incomplete/empty catalog lists non-deterministically.

The codebase already contains the correct pattern (`_query_all_items` in `src/handlers/delete_profile_cascade.py:25-54`, `_handle_pagination` in `src/handlers/list_catalogs_in_use.py:40`) — it just isn't used in these paths.

### MF-2. Cascade delete reports success on partial failure, leaving unreachable orphans
`src/handlers/delete_profile_cascade.py:63-73, 208-220` *(Python + SRE + bugs reviews)*

`_batch_delete_keys` catches every exception per batch, logs, and continues; the handler then deletes the profile metadata (line 213) and returns `True` unconditionally. A throttled batch mid-cascade leaves orphaned orders/campaigns/shares/invites; the client sees success, and because `_get_profile_owner_id` (lines 79-88) raises NOT_FOUND once the profile row is gone, a retry can never reach the orphans. Track batch failures and either fail before deleting the metadata row or retry unprocessed items.

### MF-3. Profile ownership transfer can permanently lose the profile record
`src/handlers/transfer_profile_ownership.py:54-59` *(Python + bugs reviews)*

`_transfer_ownership` is an unconditional `delete_item` followed by `put_item` (the owner is the partition key). A throttle, network error, or Lambda timeout between the two permanently destroys the profile row while its campaigns/orders/shares remain; a concurrent double-submit can interleave the two operations. Use `transact_write_items` — the codebase already uses it in `scout_operations` and `campaign_operations`.

### MF-4. Shared-campaign `campaignYear` is written as a DynamoDB String, silently excluding the campaign from queries
`src/handlers/campaign_operations.py:392-394` (via `_extract_campaign_values_from_shared` at `:112`; contrast `validate_unit_fields` int-conversion at `:312-319`)

`campaignYear` read from a shared campaign arrives as a boto3 `Decimal`, which is neither `int` nor `float`, so `_dynamo_value_for_scalar` falls through to `{"S": str(value)}`. Joining a shared campaign persists `campaignYear = {"S": "2026"}` while manually created campaigns store a Number. `list_unit_catalogs._collect_catalog_ids` (`src/handlers/list_unit_catalogs.py:37-38`) filters `campaignYear = :year` with an Int — Number ≠ String, so the joined campaign is silently excluded from unit catalog results. Handle `Decimal` explicitly (map to `N`).

### MF-5. Campaign dates display one day early for every US user
`frontend/src/lib/date-utils.ts:8` and `frontend/src/hooks/useCreateCampaignSubmit.ts:112-113` (root cause) · `frontend/src/pages/CampaignLayout.tsx:50-56` · `frontend/src/pages/UserDataPage.tsx:510-511, 646-649` (display sites)

Dates are stored as UTC midnight (`"2026-09-01T00:00:00.000Z"`) but rendered with `new Date(s).toLocaleDateString(...)`, which shows the previous calendar day in any timezone west of UTC: a campaign starting Sept 1 displays "Aug 31" for all US viewers. Round-trip editing splits the raw string so stored values don't shift — display is wrong everywhere dates appear. Parse the date part timezone-agnostically for display.

### MF-6. Frontend typecheck compiles zero files — the CI type gate is a no-op
`frontend/package.json:19` (`"typecheck": "tsc --noEmit"`) with solution-style `frontend/tsconfig.json` (`"files": []`)

Verified: `tsc --noEmit --extendedDiagnostics` reports **`Files: 0`** and always exits 0, while `-p tsconfig.app.json` checks 1,863 files. The CI type-check gate (`.github/workflows/ci.yml:90`) and `make typecheck` (`Makefile:77,92`) pass regardless of type errors, and CI has no frontend build step to catch them either. Fix: `tsc -b --noEmit` (or `-p tsconfig.app.json`). Related: `frontend/tests/**` is excluded from every tsconfig and has already rotted — compiling tests with the app's strict settings yields **36 real type errors** in 7 files (e.g. 12× passing the removed `addTypename` prop to Apollo v4 `MockedProvider` in `tests/AdminPage.test.tsx`, 10× missing required `campaignYear` prop in `tests/CampaignCard.test.tsx`).

### MF-7. Test wrapper converts a hung/killed test suite into a green CI run
`frontend/run-tests.js:36, 54`

The hang-watchdog kills vitest and then exits 0: `exitCode = code || 0` maps a signal-kill (`code === null`) to 0. If the suite hangs (the exact failure mode the wrapper exists to handle) or is SIGTERM-killed with failures unreported, CI prints "Tests completed with exit code: 0" and passes with tests unrun. Treat `code === null` (signal) and watchdog-triggered kills as failure.

### MF-8. Several "guard" test files are never executed by any runner
- `tests/unit/check_no_return_empty_request.test.ts`, `tests/unit/create_order_fn.sanitize.test.ts`, `tests/integration/check_no_return_empty_request.test.ts` — vitest tests that no configured runner collects: pytest only collects `test_*.py` from `tests/unit`; the integration config (`tests/integration/vitest.config.ts:19`) includes only `**/*.integration.test.ts`; frontend CI runs vitest from `frontend/` only. These claim to guard JS resolvers against empty-request returns and unsanitized `createOrder` input — and silently never run.
- `vitest.workspace.ts`, `vitest.config.ts`, `vitest.global.setup.ts` (repo root) — orphaned harness: nothing invokes them, root package.json has no test script or vitest dependency, `defineWorkspace` was removed in Vitest 4 (installed: 4.1.8), and the include pattern wouldn't match the `.spec.tsx` files that actually run. This dead workspace was the only thing that would ever have run the guard tests above.
- `tests/test_profile_sharing.py`, `tests/test_report_generation.py` (repo root `tests/`) — stale strays outside `testpaths = ["tests/unit"]`; when run manually, all 4 tests fail with `AttributeError` (they monkeypatch `get_invites_table`, removed in a refactor).

Wire the guard tests into a real runner, delete the orphaned root harness, and delete the broken stray Python tests.

### MF-9. Stale duplicate tofu root can fork or destroy dev infrastructure — and docs point at it
`tofu/environments/dev/main.tf` *(found independently by tofu, SRE, dead-code, and docs reviews)*

A second dev root (last touched PR #24) coexists with the live `tofu/application/environments/dev/`. It targets a **different state bucket** (`kernelworx-tofu-state-ue1` vs `kernelworx-tofu-state-us-east-1-dev`) while instantiating the same modules with identical resource names, and it no longer validates (`module "iam"` omits required `cloudfront_distribution_arn`; `module "cognito"` omits `callback_urls`/`logout_urls` — confirmed via `tofu validate`). Meanwhile `docs/DEVELOPER_GUIDE.md:27,54`, `tests/e2e/README.md:19,191`, and `frontend/LOCAL_DEV.md:76` all direct developers to apply from this stale root. Best case: hard validate error. Worst case (if "fixed" in place): an apply against divergent empty state that collides with or destroys live dev resources. Delete the directory and fix the doc references.

### MF-10. Prod Lambdas silently fall back to hardcoded dev table names
`src/handlers/list_catalogs_in_use.py:120-122` · `src/handlers/campaign_operations.py:55-58` *(SRE + Python reviews)*

Table-name env vars fall back to hardcoded dev defaults (`"kernelworx-campaigns-v2-ue1-dev"` etc.) instead of failing fast like `get_required_env` (`src/utils/dynamodb.py:22`) used elsewhere — the two files' defaults are even mutually inconsistent (`-v2-` vs non-v2). A missing env var in a prod deploy silently targets dev tables (cross-environment data bleed) instead of erroring at startup.

### MF-11. Zero production monitoring: no alarms, dashboards, or notifications anywhere
`tofu/application/` (entire tree; Lambda definitions at `tofu/application/modules/lambda/main.tf:241-303`)

No CloudWatch alarm, dashboard, or SNS resource exists for the application (grep-verified). A bad deploy that makes every invocation of a resolver throw is discovered only when a user complains. Minimum viable: alarms on Lambda `Errors`/`Throttles`, AppSync 5xx, and DynamoDB `SystemErrors`, wired to an SNS topic → email.

### MF-12. Core docs describe an architecture that doesn't exist
- `AGENT.md:212`, `README.md:31`, `.github/copilot-instructions.md:53,59` — claim "DynamoDB single-table design with PK/SK + GSI1-3"; the actual design is **8 separate tables** with named indexes (`tofu/application/modules/dynamodb/main.tf`).
- `AGENT.md:216-251` — "Lambda Simplification Initiative" claims 7 Lambda functions and cites GSI6/GSI7; the deployment defines **20 Lambdas** (`tofu/application/modules/lambda/main.tf:72-192`) and no GSI6/GSI7 exists. Agents following this section would delete load-bearing Lambdas.
- `README.md:82-105` — frontend commands documented from repo root, where the only script is `spellcheck`; first step fails with `Missing script: "dev"`.
- `README.md:118-131` + `docs/GETTING_STARTED.md:95-115` — documented deploy path omits the required Lambda-layer build (only `tofu/application/scripts/deploy.sh` creates `.build/lambda-layer`, which `archive_file.lambda_layer` sources) and wrongly claims `tofu apply` reads `.env`; a fresh `tofu plan` fails.
- `docs/DEVELOPER_GUIDE.md:13-14,48,50,61,100-121` — CDK instructions for a `cdk/` directory that doesn't exist, and documents utility APIs (`get_table()`, `normalize_id()`, `generate_unique_id()`) that don't exist — copy-paste raises `ImportError`.
- `frontend/deploy.sh:11,28-32` — fetches config from a CloudFormation stack and CDK logical ID (`UserPool6BA7E5F2`) that don't exist under OpenTofu.
- `.github/copilot-instructions.md:28` — deploy command cited at a path where the script doesn't live (`deploy.sh` is in `tofu/application/scripts/`).
- `AGENT.md:314-318,357`, `README.md:45` — reference `TODO.md`, `TODO_SIMPLIFY_LAMBDA.md`, `docs/VTL_RESOLVER_NOTES.md` — none exist.

This tier is Must Fix because these files are the operating instructions for both humans and AI agents, and following them either fails immediately or produces designs against a phantom data model.

---

## Should Fix

### Correctness

**SF-1. "Don't share with yourself" guard never fires (prefix mismatch).** `src/handlers/campaign_operations.py:189-193` — `shared_campaign["createdBy"]` is stored with the `ACCOUNT#` prefix (`create_shared_campaign_fn.js:36`) but compared against the prefix-stripped owner id, so the comparison is always false: a leader joining their own shared campaign with "share with creator" checked ends up with their own profile listed under "shared with me". Line 205 also writes a double-prefixed `GSI1PK = "ACCOUNT#ACCOUNT#<sub>"` (currently harmless, but a trap).

**SF-2. Campaign rename silently diverges unit reporting.** `tofu/application/appsync/js-resolvers/update_campaign_fn.js:12-15` never recomputes `unitCampaignKey` when `campaignName` changes, but `campaign_reporting.py:183-189` and `list_unit_catalogs.py:170-174` query the `unitCampaignKey-index` with a key that embeds the name. After a rename, reports under the old name keep including the campaign and reports under the new name find nothing.

**SF-3. One orphaned profile kills the whole unit report.** `src/handlers/campaign_reporting.py:55-59` — `check_profile_access` (`src/utils/auth.py:107-108`) raises NOT_FOUND for a missing profile row and `_get_accessible_profiles` doesn't catch it, so a single orphaned campaign (e.g. after `adminDeleteUserProfiles`) makes `getUnitReport` fail for every leader in the unit. Skip missing profiles instead.

**SF-4. Payment-method mutations race and silently lose writes.** `src/handlers/payment_methods_handlers.py:147-175, 246-268` · `src/utils/payment_methods.py:325-348, 392-413, 469-493` — every mutation is an unconditional read-modify-write of the entire `preferences` map (`SET preferences = :prefs`) with no condition expression. A QR-confirm on one device racing a create on another silently erases one of the changes.

**SF-5. Frontend CSV export corrupts on embedded quotes; both exports allow spreadsheet formula injection.** `frontend/src/lib/reportExport.ts:93` wraps cells in quotes without doubling embedded quotes — a customer named `John "JJ" Smith` shifts every subsequent column. Backend: `src/handlers/report_generation.py:238-247, 268-270` writes `customerName`/phone/address into CSV/XLSX with no neutralization of leading `=`, `+`, `-`, `@` — a user with WRITE share access can plant `=HYPERLINK(...)`-style formulas that execute when a unit leader opens the report (`create_order_fn.js` validates phone/address but not name content). Escape quotes and prefix-neutralize formula characters in both paths.

**SF-6. Empty list serializes to invalid `{"SS": []}`.** `src/handlers/campaign_operations.py:370-374` — `_dynamo_value_for_list` maps any all-string list to `SS` (`all([])` is `True`), which DynamoDB rejects with `ValidationException`; `SS` also silently dedupes and unorders. Serialize plain lists as `L`.

**SF-7. Pre-signup control flow branches on exception message substrings.** `src/handlers/pre_signup.py:68-79` — `"already exists" in error_msg` decides whether to block a duplicate signup; any rewording flips behavior to "allow signup and swallow error" (line 79 returns the event for unrecognized errors). Use dedicated exception classes.

**SF-8. `useOrderForm` mutates previous React state.** `frontend/src/hooks/useOrderForm.ts:44-50` — shallow-copies the array then mutates the shared item object in place; memoized consumers see unchanged references and skip re-renders; StrictMode invariants broken. Copy the item object too.

### Security

**SF-9. Federated-account auto-link still skips `email_verified` (prior review SEC-06 — not fixed).** `src/handlers/pre_signup.py:143-154` — links a federated identity to an existing native account on email match alone, never checking the provider's `email_verified` claim before `admin_link_provider_for_user`. Only Google (which verifies) is wired today, so live exploitability is low — but adding any other IdP makes this an account-takeover vector. Also at `:147`: the provider-supplied email is interpolated unvalidated into the Cognito `ListUsers` filter string.

**SF-10. `security_review.md` is stale and misstates current posture.** SEC-01 cites JS resolver files that no longer exist (cascade delete moved to Python); SEC-04 claims `xlsx ^0.18.5` while `frontend/package.json:37` pins 0.20.3 (fixed). Verified current status: SEC-01 fixed, SEC-02 fixed, SEC-04 fixed, SEC-05 partially fixed (resolver still leaks registered-vs-not via success/error — `lookup_account_by_email_fn.js:20-21`), SEC-06 **not** fixed (SF-9), SEC-07 unchanged (accepted trade-off). Update the document so remaining live findings are distinguishable.

### Infrastructure & deployment

**SF-11. Prod frontend deploy breaks open sessions.** `.github/workflows/deploy-prod.yml:157-158` — `aws s3 sync --delete` removes all previously hashed JS/CSS chunks before the CloudFront invalidation, while edges may cache old `index.html` up to `default_ttl=3600s` (`cloudfront/main.tf:106`); the SPA error fallback then serves `index.html` as the "JS" → white screen until force-refresh. Keep N previous asset generations (drop `--delete` or scope it), and/or shorten the HTML TTL.

**SF-12. Prod pipeline: reviewed plan isn't the applied plan; no rollback.** `.github/workflows/deploy-prod.yml:81,124` — `tofu plan` output is informational; `tofu apply -auto-approve` re-plans independently, and smoke tests run only after the old frontend is already deleted. Save the plan artifact and `apply` it (`tofu plan -out` → `tofu apply tfplan`), and define a rollback path.

**SF-13. `deploy.sh` applies stale saved plans and advertises a nonexistent `import` action.** `tofu/application/scripts/deploy.sh:70-73` blindly applies any leftover `tfplan` file (days-old plans revert current code without warning — add a staleness check or always re-plan); `:90` invokes `import-resources.sh`, which doesn't exist, so the documented `import` action dies under `set -e`.

**SF-14. AppSync's 30 s resolver ceiling vs 60 s Lambda timeouts.** `tofu/application/modules/lambda/main.tf:89-96,113-117` — `request-report`, `unit-reporting`, `delete-profile-cascade` may run 30-60 s; AppSync errors out at 30 s while the Lambda completes in the background, prompting user retries and duplicated work. Either fit within 30 s or make these async (mutation returns a job id).

**SF-15. Cognito user pool lacks `deletion_protection = "ACTIVE"`.** `tofu/application/modules/cognito/main.tf:130-226` — `prevent_destroy` only guards the tofu path; a console/CLI mistake irrecoverably destroys all credentials, passkeys, and federated links (no Cognito restore exists).

**SF-16. No managed log groups → unbounded retention; AppSync has no logging; X-Ray dead-ends.** Lambda log groups are auto-created with "Never expire" and unmanaged by tofu (`lambda/main.tf:241-303`); the AppSync API has no `log_config` (`appsync/api.tf:4-26`), so resolver/auth failures leave no trace; `xray_enabled = true` on AppSync but no Lambda sets `tracing_config`, so traces stop at the resolver. Add `aws_cloudwatch_log_group` resources with retention, an AppSync log config, and Lambda tracing.

**SF-17. Vacuous preconditions and inconsistent ACM validation wiring.** `appsync/api.tf:35` and `cloudfront/main.tf:138` — `condition = var.certificate_validation != null ? true : true` is always true; the "certificate validation must complete" guard enforces nothing. Dev roots omit `certificate_validation` entirely (`application/environments/dev/main.tf:217-242`), and prod's `aws_acm_certificate_validation.login` (`prod/main.tf:265-268`) is consumed by nothing, so the Cognito custom domain can be created before its cert is issued (first-apply failure). Fix the conditions and thread the validation dependencies consistently.

**SF-18. route53 module silently drops all but the first ACM validation record.** `tofu/application/modules/route53/main.tf:132-150` — hardcodes `[0]` across three duplicated ternary chains; any cert gaining a SAN stays PENDING_VALIDATION forever. A `for_each` over `merge()` of the record lists is both correct and shorter.

**SF-19. Deprecated `hash_key`/`range_key` on all 8 DynamoDB tables.** `tofu/application/modules/dynamodb/main.tf` (e.g. lines 48, 63, 150-151) — the pinned `~> 6.0` provider emits 18 deprecation warnings (use `key_schema`); a 7.x bump breaks every table at once, and the noise buries real validate output today.

**SF-20. Full-table scan per `listUnitCatalogs` request.** `src/handlers/list_unit_catalogs.py:86-90` — scans the entire profiles table with a filter, then N sequential campaign queries; cost/latency scale with total profiles across all users. Needs a GSI on the unit key.

**SF-21. Tofu hygiene batch.** 10 files fail `tofu fmt -check` (list in tofu review; no fmt/validate target in `make ci`); `route53` and `bootstrap/budgets/modules/budget` have no `terraform {}` version pins (and budgets roots use `>= 1.8` vs `>= 1.7.0` everywhere else); unused module variables (`route53`: `environment`, `cognito_domain`, `api_certificate_arn`, `login_certificate_arn`; `cloudfront`: `environment`; `cognito`: `site_domain`) force callers to thread dead values; hardcoded `sns_region = "us-east-1"` (`cognito/main.tf:158`), local AWS profile names and a 4×-duplicated alert email in the budgets roots; budgets stacks lack the OpenTofu `encryption {}` block the application roots enforce.

### Observability & runtime efficiency

**SF-22. `StructuredLogger` ignores levels and swallows tracebacks.** `src/utils/logging.py:24-42` — sets a stdlib level but emits via unconditional `print()`, so `LOG_LEVEL` (set per-Lambda in `lambda/main.tf:60`) does nothing and `debug()` always ships to CloudWatch. Callers across 6 files pass `exc_info=True`/`extra={...}` (e.g. `scout_operations.py:78,113,123`) which are JSON-serialized as literal fields — **no traceback is ever logged** on exactly the unexpected-error paths. Honor levels and render tracebacks.

**SF-23. Swallowed exceptions falsely documented as logged.** `src/handlers/list_catalogs_in_use.py:100-108` — `asyncio.gather(..., return_exceptions=True)` discards exceptions; the comment claims they're logged, but nothing does. Throttling → silently incomplete catalog list with zero diagnostics.

**SF-24. Fresh boto3 client on every table access.** `src/utils/dynamodb.py:44-46, 68-130` — every `tables.<name>` property access constructs a new resource (the `__new__` singleton caches nothing); same pattern in 4 other files. Defeats warm-invocation connection reuse; cache the resource and table objects at module scope.

**SF-25. Internal error text leaks to GraphQL clients.** `src/handlers/report_generation.py:151` — `f"Failed to generate report: {e}"` sends raw boto3/openpyxl detail (bucket names, key structure) to end users; every other handler returns a generic message.

### CI & tooling

**SF-26. GraphQL codegen is broken.** `frontend/codegen.ts:14` points at `../cdk/schema/schema.graphql`, which no longer exists (schema is at `tofu/application/schema/schema.graphql`); `npm run codegen` fails, so the 2,229-line generated types file silently drifts from the live API.

**SF-27. ESLint isn't type-aware; real floating promises exist.** `frontend/eslint.config.js:12-17` — no `recommendedTypeChecked`, so `no-floating-promises` never runs; unhandled `refetch()` calls in `PaymentMethodsPage.tsx:121,131,141,154,250` and `checkAuthSession()` in `AuthContext.tsx:153` drop rejections and UI updates silently.

**SF-28. Lint/type config claims don't match enforcement.** `pyproject.toml:33-39` declares project-wide strict mypy, but `mypy src tests scripts` yields 238 errors in 24 files; the Makefile runs mypy on `src/` only and ruff on `src/ tests/` only (`scripts/` unchecked, with a real violation), and `ruff format --check` is enforced nowhere (10 files fail). Either scope the config honestly or fix the violations.

**SF-29. Coverage gates are inflated by assertion-free tests.** `frontend/tests/coverage_force_render.spec.tsx:121-129,142` renders 8 pages with all errors caught-and-ignored and asserts only truthiness — the 99% line threshold certifies code that could throw on first render. Python mirror: `tests/unit/test_coverage_fillers.py` (494 lines poking private helpers) plus 45 `# pragma: no cover/no branch` markers satisfy `--cov-fail-under=100`. The 100%/99% numbers overstate behavioral coverage; replace with real assertions or lower the thresholds honestly.

**SF-30. `make ci` requires live AWS.** `Makefile:34` vs `:136` — help says "spellcheck + lint + typecheck + test" but the target also runs `test-integration`, which needs dev AWS credentials and can mutate dev data. Split local CI from integration.

**SF-31. Unit-test env pollution.** `tests/unit/conftest.py:17-38` — the `aws_credentials` fixture mutates `os.environ` with no teardown (use `monkeypatch.setenv`) and sets names identical to real dev resources; combined with the import-time boto3 client in `campaign_operations.py:41-52` (itself a defect: import fails outside AWS-configured environments — make it lazy), a test escaping moto could touch real dev tables.

### Dead code (high-impact)

**SF-32. Dead Python mutation handler duplicating a live feature.** `src/handlers/profile_sharing.py:317-390` — `create_profile_invite` (+ `_validate_invite_inputs`, `generate_invite_code`) is wired to no Lambda; the deployed `createProfileInvite` is a JS pipeline resolver whose behavior has already drifted (fixed 14-day expiry vs the JS resolver's `expiresInDays`). Its unit tests "verify" behavior users never get. Delete it.

**SF-33. Orphaned deployed AWS resources.** `tofu/application/modules/appsync/functions_catalogs.tf:3,42` — `aws_appsync_function.create_catalog` and `update_catalog_fn` appear in no `pipeline_config` (live resolvers are VTL unit resolvers) yet deploy real AppSync functions. Also 14 orphaned JS resolver files and 2 VTL templates in `tofu/application/appsync/` referenced by no `.tf` (full list in the dead-code appendix of this review's source data; includes `get_profile_resolver.js`, `list_my_shares_resolver.js`, `delete_payment_method_pipeline_resolver.js`, `get_my_account_request/response.vtl`).

**SF-34. Dead React code, including an 821-line component with latent bugs.** Zero references (grep-verified, including routes/lazy imports): `frontend/src/components/OrderEditorDialog.tsx` (821 lines; contains a UTC-today default-date bug and hardcoded payment values the live pipeline would reject if ever re-wired), `frontend/src/components/UserDetailsDialog.tsx`, `frontend/src/pages/CampaignForm.tsx`. Kept alive only by their own tests: `CreateCampaignDialog.tsx` (500+ test lines for a component no page renders), `CreateCampaignPageComponents.tsx`, and `useQRUpload.ts` — whose logic `PaymentMethodsPage.tsx:200-258` **reimplements inline** (duplicate S3-upload flows already identical-by-coincidence only). Either wire the hook back in or delete it; delete the rest.

**SF-35. Stray "Coming Soon" page ships in the deploy artifact.** `frontend/public/index.html` — a pre-launch static page in `public/`, copied into `dist/` where it conflicts with the app entry. Delete.

**SF-36. Duplicated helpers that will drift.** `src/handlers/admin_operations.py` — `_get_display_name_from_dynamodb`/`_get_display_name_from_db` (75-88 vs 457-470) are byte-identical; `_build_admin_user_dict`/`_build_admin_user` (91-119 vs 473-508) build the same dict on parallel paths; both variants are live. Frontend: `formatCurrency` defined 7× (shared export in `api-utils.ts:229` plus 6 local copies) and `formatPhoneNumber` 3× with **differing behavior** (OrdersPage leaves 10-digit numbers unformatted; OrderEditorPage formats them). Consolidate.

**SF-37. Self-service account deletion forges ADMIN claims.** `src/handlers/account_operations.py:132-151` — `_delete_all_user_data` fabricates an event with `"cognito:groups": ["ADMIN"]` to satisfy `is_admin()` in the admin handlers. Any future hardening of `is_admin` silently breaks self-deletion. Factor the delete logic into claim-free internals both entry points call.

### Documentation

**SF-38. Conflicting/stale setup facts.** Three conflicting Node requirements ("v22+" in README:54, "20+" in GETTING_STARTED, `>=24.0.0` in engines); README still says "Phase 0 / Installation coming soon / v1 fall 2025" while prod is live; GETTING_STARTED troubleshooting uses pre-rename `psm`/`popcorn-sales-dev` resource names and claims Lambda "not yet deployed"; `frontend/TESTING.md` documents nonexistent vmThreads config and "2 known test failures" directly contradicting the "zero failures" policy in README/AGENT.md; `AGENT.md:181,333,347` points tests/Lambdas/components at wrong directories (`src/**/__tests__/`, `src/lambdas/`, `src/components/`).

**SF-39. Feature claims for services that don't exist.** README:17, AGENT.md:23-26, copilot-instructions:54 claim Facebook login (only Google is configured — `cognito/main.tf:287,330`; `LoginPage.tsx:6` carries the dead `'Facebook'` union branch), SES/SNS email notifications, and a Kinesis Firehose audit pipeline (no such resources in tofu/).

---

## Nit

**Python**
1. `src/utils/validation.py:30-38` — `if not value` treats unit number `0`/`False` as missing; use `value is None or value == ""`.
2. `src/handlers/report_generation.py:110` — second-resolution `reportId` collides for same-campaign requests within 1 s (S3 key overwrite); add a UUID suffix.
3. `src/handlers/transfer_profile_ownership.py:33,41,51` (also `scout_operations.py:124`, `delete_profile_cascade.py:172`) — raise `ValueError`/`PermissionError`/`RuntimeError` where siblings use `AppError` with codes; clients get unstructured errors.
4. `src/utils/auth.py:203-211` — `is_admin` wraps pure dict-gets in `except Exception: return False`; masks future bugs as "not admin".
5. `src/handlers/admin_operations.py:384` — `import re` shadows the module-level import; regex recompiled per call. Also three near-identical `_validate_admin_and_get_*` helpers (261, 757, 1208) in a 1,420-line module mixing four concerns.
6. `src/handlers/validate_payment_method.py:16-18` — third import convention (`from src.utils...`) besides the repo's two.
7. Repo-wide legacy `Dict`/`List`/`Optional` typing on Python ≥3.14; ruff selects only `I` — enabling `UP`, `B` (catches missing `raise ... from e`), `SIM` is one line.
8. `pyproject.toml:41-51` — stale `aws_cdk`/`constructs` mypy overrides (mypy itself reports them unused); `:93-95` radon comments reference the nonexistent `cdk/` dir.
9. `src/handlers/profile_sharing.py:154-163` — `BatchGetItem` `UnprocessedKeys` logged but never retried; throttling silently omits shared profiles.
10. `src/utils/payment_methods.py:443-449` — slug-based QR deletion can't find UUID-keyed uploads; deleting via the utils path orphans S3 objects.
11. `src/handlers/account_operations.py:112-120` vs `frontend/src/lib/graphql.ts:133-148` — `updateMyAccount` response omits `city`/`state`/`unitType`/`unitNumber` that the frontend selection set requests (masked by refetch).
12. `src/utils/appsync_types.py:11-45` — TypedDicts never used as annotations anywhere.

**TypeScript / frontend**
13. `frontend/src/lib/apollo.ts:213` — `defaultOptions` double-cast (`as unknown as ...`) disables all type checking of the options object.
14. `frontend/src/pages/LoginPage.tsx:35` — `err as any`; three typed error-message helpers already exist (`api-utils.ts:46`, `useEmailUpdate.ts:24`, `usePasskeys.ts:37`).
15. `frontend/src/components/OrderEditorDialog.tsx:748` — `dbCampaignId!` non-null assertion can send `campaignId: null` into a mutation (moot if the dead component is deleted per SF-34).
16. Unvalidated `JSON.parse` typed by assertion: `ScoutsPage.tsx:53` (server `preferences`), `useQRUpload.ts:60-66`/`PaymentMethodsPage.tsx:201-204` (S3 policy fields); `AuthContext.tsx:30` casts the `cognito:groups` claim `as string[]` unchecked.
17. `frontend/src/lib/reportExport.ts:98` — blob URL from `URL.createObjectURL` never revoked (QRUploadDialog does it correctly).
18. `frontend/src/pages/PaymentMethodsPage.tsx:102` — success-message `setTimeout` not cleared on unmount (ref+cleanup pattern exists in LoginPage et al.).
19. `frontend/eslint.config.js:24` — `complexity: max 5` evaded by 32 inline disables and one-line indirection helpers (`ScoutsPage.tsx:166-196`); raise the limit and reserve disables for real cases.
20. `frontend/src/hooks/useSharedCampaignDiscovery.ts:59` — `NodeJS.Timeout` in browser code; siblings use `ReturnType<typeof setTimeout>`.
21. `frontend/debug-width.js` committed one-off debug script; stray `frontend/campaign-*.xlsx` artifacts show a test runs `XLSX.writeFile` unmocked.
22. Prettier configured but no `format:check` anywhere in CI/Makefile.
23. `AGENT.md:128` recommends `npm run test -- --watch`, but the wrapper always prepends `run` → contradictory `vitest run --watch`; `test:watch` is the working path.

**Infra / tofu**
24. Dev DynamoDB tables lack PITR (`application/environments/dev/main.tf:126-132`, module default false) — a bad migration against shared dev is unrecoverable.
25. Static-site bucket versions every deploy generation with no noncurrent-version lifecycle (`modules/s3/main.tf:39-44`); contrast the state bucket's 90-day expiry.
26. No WAF/rate limits on AppSync and no Lambda reserved-concurrency caps — one authenticated scripter of the scan-based resolvers can drive unbounded spend and starve the post-auth trigger (partially acknowledged in `tofu/.kics.yml`).
27. `certificate_validation` variables typed `any` as dependency handles (`appsync/variables.tf:28-32`, `cloudfront/main.tf:33-37`); module-local `tags` duplicate provider `default_tags`; no `validation` blocks on enum-like vars (`environment`, `region_abbrev`).
28. ~1,000 lines of copy-paste AppSync datasource/function blocks and ~300-line near-duplicate dev/prod roots (divergence already crept in: prod lacks the `exports_bucket` output) — `for_each` + `moved` blocks (pattern already used in `lambda/main.tf:268-276`) would collapse them.
29. Amplify tokens in `localStorage` (default; `frontend/src/lib/amplify.ts:8-24`) and no CloudFront security headers (CSP/HSTS/X-Content-Type-Options) — defense-in-depth only, no current XSS sink found.
30. `frontend/src/lib/redirect.ts:9-14` — `isSafeRedirect` misses backslash-authority (`/\evil.com`) normalization; hard to seed, but one-line fix.
31. Unused tofu module outputs (e.g. `appsync.api_arn`, `lambda.function_names`, various `route53.*`) — some may be intentional `tofu output` conveniences.

**Dead code / docs (small)**
32. Unused npm dep `@aws-sdk/client-cloudformation` (root `package.json:10`); `@playwright/mcp` likely unused; `@aws-sdk/client-appsync` declared at root and in `tests/integration/package.json`.
33. Env vars going nowhere: `POWERTOOLS_SERVICE_NAME` set on every Lambda but powertools isn't a dependency; `VITE_APPSYNC_REGION` set in `.env*` and CI but never read.
34. Unreferenced scripts (verify with owner, then delete): `scripts/migrate_shares_prefix.py` (completed one-off), `scripts/sync-to-cloudflare.sh`, `scripts/update-integration-env.sh` (CloudFormation-era, prints an unused `STACK_NAME`), `scripts/delete-test-catalogs.py` (targets the retired single-table schema; its `TABLE_NAME` guard is dead code).
35. Dead test infra: `tests/integration/setup/resourceTracker.ts`, `tests/integration/refactor-cleanup.sh`, `tests/unit/fixtures.py` (used only by its own self-referential test), unused conftest fixtures `sample_order_id`/`sample_order`; duplicate `useQRUpload.test.ts` + `.tsx` both run.
36. Frontend scaffold leftovers: `react.svg`, `vite.svg`, `logo-rotating.svg`, unimported `App.css`; `frontend/README.md` is untouched Vite boilerplate.
37. Unused frontend constants/types (`UNIT_TYPES` duplicate and `CAMPAIGN_OPTIONS` in `constants/campaign.ts`, `AdminUserConnection` in `types/entities.ts:221`); unused GraphQL operations (`LIST_UNIT_CATALOGS`, `LIST_UNIT_CAMPAIGN_CATALOGS`, `REQUEST_CAMPAIGN_REPORT`, `SHARE_PROFILE_DIRECT`) — note their backend counterparts are live and integration-tested; the UI just never calls them.
38. Dead lib files: `frontend/src/lib/qrCodeUrls.ts` (hardcoded per-env CDN domains rotting silently), `frontend/src/lib/test-mutation.ts` (debugging leftover).
39. Doc smalls: wrong paths in `AGENT.md:211`/`SCHEMA.md:359-361` (missing `application/` segment, dead anchor); invite code documented as 8-char but implementations generate 10; `DEVELOPER_GUIDE.md:194-206` single-table example reinforces the phantom data model; `LOCAL_DEV.md:119` stale CDK mention; broken mermaid in `SCHEMA.md:342`; `Makefile:1` `.PHONY` declares nonexistent `infra` target; `frontend/.env.example:3` lists the unread `VITE_APPSYNC_REGION`; `AGENT.md:251` duplicates line 250.

---

## Verified clean (for the record)

- **Commit `c70efd1` (DynamoDB AWS-owned keys) is correct**: `server_side_encryption { enabled = false }` selects the no-cost AWS-owned key (encryption at rest remains on), applied uniformly as an in-place update; the companion S3 `bucket_key_enabled`/`blocked_encryption_types` change validates against the pinned provider.
- **Security**: IAM policies are resource-scoped (no unjustified wildcards); write paths enforce owner-or-WRITE-share and fail closed; admin handlers consistently gate on `cognito:groups`; no IDOR, no XSS sinks, no hardcoded secrets; S3 public access fully blocked; presigned URLs appropriately scoped and expiring.
- **Python**: unit suite passes 819/819; the `except ValueError, TypeError:` forms are valid PEP 758 syntax on the Python 3.14 runtime, not bugs; `scripts/migrate_shares_prefix.py` paginates and uses conditional writes correctly.
- **Frontend**: tsconfig strictness itself is well-configured; React hooks dependency arrays and timeout cleanup are consistently correct in the live pages/hooks; ESLint passes clean.
- **Tofu**: live application roots' backend/state config is consistent; `count` gating and `prevent_destroy` coverage on stateful resources are sound.
