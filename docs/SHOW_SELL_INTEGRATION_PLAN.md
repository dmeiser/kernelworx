# Show & Sell Integration Plan — survey wave deliverable

Status: SURVEY + PLAN only (no feature code). Author: dev.build.
Basis: captain ruling 2026-11-09 (option (b) — fold our clean-room Show & Sell
into this application); clean room closed by captain call; our proven tree
preserved at branch `show-sell-cleanroom` (a567675, 137/281 checklist items
gate-verified, 10/11 evidence recordings).
Spec input: `docs/specs/show_sell/` (ten documents) +
`SHOW_AND_SELL_EXISTING_APPLICATION_IMPACT.md` (the impact map; section 3
file-by-file, section 10 order, section 11 decisions).

---

## 1. What exists on each side (measured, not estimated)

### The application (this branch, kw-ss-integration @ origin/main f3c8a77)

- Backend: Python 3.14 Lambda handlers under `src/handlers/` (23 modules,
  e.g. `campaign_operations.py`, `campaign_reporting.py`, admin suite), utils
  under `src/utils/` (`dynamodb.py` 297 lines with singleton table accessors +
  `tables` registry, `auth.py` 426 lines, `errors.py`, `handlers.py` error
  decorator, `pagination.py`, `appsync_types.py`).
- API: single SDL `tofu/application/schema/schema.graphql` (1347 lines,
  57 types/inputs/enums), JS pipeline resolvers in
  `tofu/application/appsync/js-resolvers/` (314 files incl. tests), VTL
  mapping templates, modules under `tofu/application/modules/`
  (appsync/lambda/iam/dynamodb[9 tables]/cognito/s3/cloudfront/route53/ses/waf
  /alarms/certificates).
- Frontend: React+TS+Vite+MUI+Apollo, `frontend/src/` with pages/components,
  codegen from SDL, coverage gates ~99/97/96/97 + Playwright.
- CI: `.github/workflows/` (ci, deploy-dev/prod/shared, ephemeral
  test/teardown, recover). AGENT.md: PRs only, 100% Python coverage, ruff,
  mypy, uv.
- Ephemeral environments + `scripts/ephemeral-env.sh`; domain/Cognito/
  CloudFront already live (dev.kernelworx.app).

### Our clean-room build (branch show-sell-cleanroom)

- `src/handlers/`: unit_operations (735 lines), unit_campaign_operations
  (514), inventory_operations (1069), event_operations (1436),
  sale_operations (1255), finalization_operations (832), order_operations
  (309, custody design), profile/campaign/catalog legacy surface,
  legacy_reporting (305, parity reference only).
- `src/utils/`: production boto3 layer `dynamodb_boto3.py` (424, proven
  against REAL DynamoDB incl. transactions), in-memory table layer
  `dynamodb.py` (379, drives 625 fast tests), `idempotency.py` (287,
  committed-retry marker framework), `gsi.py` registry (drift-pinned),
  `unit_auth.py`, `pagination.py`, `errors.py`.
- `graphql/schema.graphql` 1726 lines / 121 types+inputs, `merge_sdl.py`
  (AppSync silently drops extend-type fields — merge before apply).
- Frontend: 23 feature pages (Units, UnitCampaigns, Inventory, Custody,
  Events/Slots/Allocation/Sales/WeOwe/Finalize, Fulfillment, Reports,
  Join/Redeem invites, Login per design 25).
- Proof assets: 625-test pytest suite, wire-test doctrine, guard/pin
  conventions, recorder evidence kit.

---

## 2. File-by-file landing map

### 2.1 Backend handlers — new files in THEIR conventions

| Our file (cleanroom) | Lands as | Adaptation required |
| --- | --- | --- |
| `handlers/unit_operations.py` | NEW `src/handlers/unit_operations.py` (impact map 3.5) | Re-express on their `tables` accessors, `with_error_handling` decorator, their `AppError` codes (`RATE_LIMITED`→`RATE_LIMIT_EXCEEDED` rename), structured logging; drop our in-memory layer imports; add unit-invite throttle via `public_order_throttles` key contract (impact map 4.4) instead of our throttle approach |
| `handlers/unit_campaign_operations.py` | NEW `src/handlers/unit_campaign_operations.py` | Same; join-time catalog identity enforcement maps to their `update_campaign_fn.js` guard coordination |
| `handlers/inventory_operations.py` | NEW `src/handlers/inventory_operations.py` | Custody/issue/return semantics port directly; GSI names come from their table module (see risk 4) |
| `handlers/event_operations.py` + `sale_operations.py` | NEW `src/handlers/show_and_sell_operations.py` (~2700 lines) | Consider splitting events vs sales if review objects; impact map names one module |
| `handlers/finalization_operations.py` | NEW `src/handlers/finalization_operations.py` | Impact map groups this under show_and_sell_operations; recommend separate module (finalization is its own transaction family) — org decision, not product |
| participant-safe projections (inside our handlers) | NEW `src/handlers/participant_data.py` (impact map 3.5) | Extract our participant filters into the dedicated module the map requires |
| `handlers/order_operations.py` (custody design) | NOT landed as a file — reference for their `create_order_fn.js` custody redesign (impact map 3.2) | Their createOrder is a JS pipeline; our Python custody/transaction plan becomes golden-test oracles + spec for the JS rewrite (risk 3) |
| `handlers/legacy_reporting.py` | NOT landed — parity oracle for stage 5/7 | Drives golden-parity tests until browser parity, then retires with `campaign_reporting.py` |

### 2.2 Backend utils — extend THEIR files

| Our asset | Lands in | Notes |
| --- | --- | --- |
| `dynamodb_boto3.py` transaction lessons (90-action plans, bounded self-retry MAX_RACE_RETRIES, condition-error classification, client-side dup-key rejection) | `src/utils/dynamodb.py` additions per impact map 3.4 | Their utils are boto3-resource based already; our production-proven transaction helpers are the design source |
| `idempotency.py` (deterministic-input validation, committed-retry pin, 366-day cap as CONDITION) | `src/utils/dynamodb.py` transaction/idempotency helpers | Align TTL to the impact map 7-day numeric-epoch convention (decision already recommended in map §11) |
| `pagination.py` opaque cursors | `src/utils/pagination.py` | Ours is scope/filter-bound; theirs needs DynamoDB-Limit-before-filter care per map |
| `errors.py` codes | `src/utils/errors.py` | Vocabulary mapping table needed (we have `RATE_LIMITED`, they want `RATE_LIMIT_EXCEEDED`; our `OPERATION_TOO_LARGE` handling must forward only authorized details per map 3.1) |
| `unit_auth.py` | NEW `src/utils/unit_auth.py` (map 3.4) | Ports nearly verbatim conceptually: grant checks, resource-derived tenancy, cross-tenant NOT_FOUND vs FORBIDDEN tombstone semantics |
| `gsi.py` registry + drift pin | Their `tofu/application/modules/dynamodb/main.tf` + `tests/unit/table_schemas.py` | Registry-as-source pattern is worth proposing; at minimum our 20-index set lands in their table module with their test conventions |
| `appsync_types.py` strict validators | Their `src/utils/appsync_types.py` | We learned the same lesson (loose coercion causes bugs); our validator set is the checklist |

### 2.3 Schema (`tofu/application/schema/schema.graphql`)

- Merge our 121 SDL constructs into their single file: all Unit/UnitCampaign/
  inventory/event/sale/WeOwe/finalization types + operations; extend
  Campaign/Order/LineItem with origin + fulfillment fields; participant-safe
  projections; deprecate (not remove) `getUnitReport`/`requestCampaignReport`.
- Cognito-only on all new fields; legacy money Float unchanged, new money
  integer cents (dual semantics — risk 2).
- Their codegen regenerates `frontend/src/types/graphql-generated.ts`; our
  `merge_sdl.py` lesson is a comment-level caution (single file here, but
  AppSync extend-type drops bite any split).
- Contract guards to port/translate: public-api-key surface check, query
  depth/resolver-limit recompute, codegen drift.

### 2.4 Infra (their tofu provides; ours is reference-only)

- Five new tables per map §4.1 in `modules/dynamodb/main.tf` with the
  specified GSIs + TTLs; `table_arns`/outputs/environment maps across
  dev/prod/ephemeral; our `terraform/` is NOT landed (step-4 destroy target).
- Lambda: new handler entries + env vars, domain-role mapping, no fallback
  role. IAM: scoped Unit/inventory/Show&Sell roles with `TransactWriteItems`;
  no Scan anywhere; actual-TransactItems-table capture tests.
- AppSync wiring: queries/mutations/fields/data sources per map §3.1; direct
  Lambda unit resolvers for complex transactions; JS resolvers keep
  `__isError`/`errorCode` forwarding with authorized-detail-only additions.
- Unit QR prefix contract `payment-qr-codes/units/<unitId>/...` on the
  EXISTING exports bucket (no CSP change).

### 2.5 Frontend

- Our 23 pages are UX reference (design-gate verified); they are REWRITTEN
  into their MUI/Apollo/codegen conventions — not copied (different styling,
  state, test stacks).
- Login screen: NOT ported — the application already has Cognito sign-in
  (Google + email/password, MFA). Our design-25 work retires with the
  clean-room branch. (If the captain wants its session UX, that is a
  separate product question.)
- Route constraints: no lowercase `/l*` (Cognito reserved); safe set
  `/units`, `/inventory`, `/show-and-sells`, `/we-owe` per map §5.1.
- Auth context: Unit grants loaded separately from global isAdmin; never
  Unit roles in the JWT (map §5.1 — matches our server-side enforcement).
- Coverage gates ~99/97/96/97 + Playwright; our pure-test style (page-sweep,
  guard evasion, structural gates) ports as their test conventions demand.

### 2.6 Tests

- Their gate: 100% Python unit coverage, pytest with botocore-call capture,
  vitest guard/sanitize tests, Playwright E2E, ephemeral deploy parity tests.
- Our 625-test suite value-ranks: pure domain logic and race/idempotency
  probes port as oracles; in-memory-layer tests are rewritten against their
  accessor conventions; wire-test doctrine (every resolver ships a wire test)
  matches their wiring-test suite and should be cited in reviews.
- Recorder evidence kit: re-run against the integrated app's ephemeral
  environment for the final evidence sweep (recordings target the deployed
  app, steps exist in both variants).

---

## 3. Implementation order (impact map §10, annotated with our wave experience)

1. **Foundation** — schema merge (new constructs only, nothing deprecated
   yet), five tables + env maps, `unit_auth.py`, strict validators,
   transaction/idempotency/cursor helpers, CI guard updates. (Our utils are
   the reference; expect this to be the most review-dense wave.)
2. **Standalone Units** — grants/invites (+ throttle on
   `public_order_throttles`), Unit payment methods/QR, Unit Campaigns,
   roster guards. Join-time catalog invariant + authoritative Campaign reads
   BEFORE order changes. (Our unit/unit_campaign handlers + invite waves
   carry over; the expiry/count CAS-heal lessons are must-port oracles.)
3. **Inventory/custody** — balances/movements, then the atomic custody
   createOrder redesign in their JS pipeline, fulfillment/reversal with
   stable line identity. (Highest-risk wave — risk 3; our order custody
   tests become golden oracles.)
4. **Events** — allocation, slots/signups, sales, We Owe, finalization
   versions + reopen. (Largest volume; our replay/idempotency pin and
   corruption-direction probes are the acceptance bar.)
5. **Raw reporting data + browser engine** — complete pagination, security
   projections, legacy parity, then `getUnitReport` retirement.
   (Our legacy_reporting is the parity oracle; the 8.2.4(a) lesson —
   absence-is-truth in reports — applies.)
6. **Lifecycle integration** — deletion guards per map §11 decisions,
   Unit/grant cleanup, cascade policy.
7. **Retirement after parity** — legacy report schema/handlers/S3/IAM
   removal; clean-room branch archived; parallel `kernelworx-show-sell-*`
   infra destroyed via step-4 cleanup.
8. **Scale readiness** — lanes, concurrency/performance, production smoke.

## 4. Honest risk list

1. **Vocabulary mismatch.** Our error codes differ from the map's
   (`RATE_LIMITED` vs `RATE_LIMIT_EXCEEDED`, detail-forwarding rules). Needs
   an explicit mapping table in wave 1 and contract tests, or every ported
   handler silently drifts.
2. **Dual money semantics.** Legacy Orders stay Float; new money is integer
   cents. Any shared line-item helper (`lib/line_items.js`) must carry both
   without coercion leaks — our strict-validator experience says this bites.
3. **Custody createOrder is a JS rewrite of proven Python.** Our custody +
   idempotency + race-retry logic is battle-tested in Python against real
   DynamoDB; the map puts custody in the JS pipeline. Mitigation: port our
   43-case committed-retry pin and corruption-direction probes as golden
   tests FIRST, then implement. This is the single largest correctness risk
   of the integration.
4. **GSI/table-shape differences.** Their five-table spec differs from our
   11-table build (e.g. no separate `events` table — events live in
   `show_and_sells`; `saleId-index`/`campaignId-status-index` indexes we
   never had). Handlers must be re-expressed against THEIR key layout, not
   ours — direct file ports would encode wrong access patterns. Rebinding
   bugs are exactly the class our two-backend suite caught live.
5. **100% coverage gate.** Our 625 tests do not map 1:1; their coverage
   requirement will roughly double test volume per handler. Schedule impact
   is real (days, not hours, per wave).
6. **Identity model.** Our synthetic `acct-*` ids and identity_map seam
   disappear; everything keys off their real Account/Cognito claims. The
   seed fixtures, lanes, and smoke personas must be re-derived from their
   Cognito bootstrap — persona header seam does not exist here.
7. **Frontend is a rewrite, not a merge.** Different component stack
   conventions; only UX flows and edge-case inventories transfer. Coverage
   thresholds + Playwright add CI weight.
8. **Ephemeral/CI surface.** Schema surface checks, resolver wiring, IAM
   policy tests, codegen drift, shellcheck gates all need updating in wave 1;
   missing one fails CI late.
9. **Section-11 decisions are pre-answered by the map's recommended defaults
   and all six MATCH our implemented behavior** (final-admin delete block,
   joined-campaign delete block, custody-return before profile deletion,
   post-fulfillment edit policy, join-time catalog identity, 7-day marker
   TTL — we used a 366-day invite cap; markers align to the map). No product
   decisions are open from my side; anything beyond these six = STOP-AND-ASK.

## 5. Immediate next steps (wave 1 proposal, awaiting dispatch)

1. Schema merge PR skeleton (new types only) + codegen regen + drift guard.
2. Five tables + env maps in all three environments + accessor tests.
3. `unit_auth.py` + error-vocabulary mapping table + strict validators.
4. Transaction/idempotency/cursor helpers in `src/utils/dynamodb.py` with
   our golden probes translated.
5. CI guard updates (surface, depth, wiring, IAM) so later waves fail fast.

Estimate: wave 1 is a multi-day gated effort; subsequent waves per §3.
