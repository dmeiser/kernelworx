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
| `handlers/event_operations.py` + `sale_operations.py` | NEW `src/handlers/event_operations.py` + NEW `src/handlers/sale_operations.py` (module split DECIDED per r1 item 3 — recorded org decision; one ~2700-line module rejected) | Impact map names show_and_sell_operations.py; we land two modules with the map's full responsibility set split events vs sales |
| `handlers/finalization_operations.py` | NEW `src/handlers/finalization_operations.py` | Impact map groups this under show_and_sell_operations; recommend separate module (finalization is its own transaction family) — org decision, not product |
| participant-safe projections (inside our handlers) | NEW `src/handlers/participant_data.py` (impact map 3.5) | Extract our participant filters into the dedicated module the map requires |
| `handlers/order_operations.py` (custody design) | NOT landed as a file — spec + golden oracles for a NEW Lambda custody path (r2 C-1) | **Architecture correction (r2 C-1):** AppSync JS pipeline resolvers on DynamoDB data sources support single-item ops only — NO `TransactWriteItems`. Custody mode (five-table atomic write under the 90-action preflight, bounded race retry, committed-replay semantics) MUST execute in Lambda: either a direct Lambda resolver extending their `src/handlers/order_operations.py`, or a Lambda function step in the AppSync pipeline (JS keeps NONE-mode, delegates CONSUME_SCOUT_CUSTODY). Wave 3 assumes a new function + domain-role entry + wiring tests. Golden oracles FIRST (53-case committed-replay pin — count corrected from 43), then implement |
| `handlers/legacy_reporting.py` | NOT landed — parity oracle for stage 5/7 | Drives golden-parity tests until browser parity, then retires with `campaign_reporting.py` |

### 2.2 Backend utils — extend THEIR files

| Our asset | Lands in | Notes |
| --- | --- | --- |
| `dynamodb_boto3.py` transaction lessons (90-action plans, bounded self-retry MAX_RACE_RETRIES, condition-error classification, client-side dup-key rejection) | `src/utils/dynamodb.py` additions per impact map 3.4 | Their utils are boto3-resource based already; our production-proven transaction helpers are the design source |
| `idempotency.py` (deterministic-input validation, committed-retry pin, 366-day cap as CONDITION) | `src/utils/dynamodb.py` transaction/idempotency helpers | Align TTL to the impact map 7-day numeric-epoch convention (decision already recommended in map §11) |
| `pagination.py` opaque cursors | `src/utils/pagination.py` | Ours is scope/filter-bound; theirs needs DynamoDB-Limit-before-filter care per map |
| `errors.py` codes | `src/utils/errors.py` | **Rewritten per r1 item 1:** our vocabulary IS the spec vocabulary — no rename. Their `errors.py` has no RATE_LIMIT code at all; their `PUBLIC_ORDER_LIMIT_EXCEEDED` is a lifetime cap, NOT a throttle, so spec 5.3 throttle semantics (attempt-11 fixed window on `public_order_throttles`) need a DESIGN DECISION record in wave 1. **Bidirectional narrowing:** their `INVITE_EXPIRED`/`INVITE_ALREADY_USED` are distinct codes the spec 5.3 forbids — the ported redemption path must SUPPRESS them into NOT_FOUND indistinguishability (no existence oracle through their vocabulary). CONFLICT detail reasons carry an authorized-details table (forward only contracted reasons, never internals) |
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
  role. IAM: **role granularity DECIDED in wave 1 (r2 C-2, recorded org
  decision):** ONE `show-and-sell` domain role owning the five-table family
  plus explicit statements for the legacy tables its transactions touch
  (`campaigns`, `orders`, `profiles`, `public_order_throttles`, `shares` as
  needed) — one `TransactWriteItems` executes under ONE role and our
  transactions span 3-5 tables, so four scoped roles would duplicate every
  shared grant. `TransactWriteItems` appears in NO current policy: it is a
  new grant everywhere, including AppSync-direct paths. No Scan anywhere;
  actual-TransactItems-table capture tests are the acceptance pin. Wave 1
  also reconciles the AppSync service-role write surface (it can
  Put/Update/Delete ALL tables via field resolvers; complex writes go
  through Lambda under the domain role — r2 N-5).
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
- **Ruling semantics must land as records, not habits (r1 item 2):** ADR
  0002 fulfilledQuantity, ADR 0003 per-campaign auto-reduce, W10
  return-baseline/union-key, W13 omission-zero, and the tombstone
  authorization semantics each get a wave-1 record plus a per-wave
  acceptance probe — otherwise re-expression silently reverts them.
- **Replay-pin convention gets a wave-1 test-infra home (r1 item 2):**
  schema-derived committed-retry pin (53 mutations), not custody-only.
- **Two-backend real-DynamoDB suite gets a §2.6 home (r1 item 2):** the
  contract suite that ran our layer against REAL DynamoDB (zero skips,
  leak-check) is ported as the integration's live-table contract suite.
- **Tick traceability owner row (r1 item 2):** checklist ticks map onto
  their PR conventions; the owner column is recorded in wave 1.
- **Time arrangement is named (r2 C-3, RULED):** short-lived real events
  with clock-independent assertions are the CI default; a guarded
  test-only clock behind an env flag is built ONLY if a scenario truly
  needs it, under the same D4 purity doctrine (dev/ephemeral surface
  only, structural purity test, bounded offset). Without this, wave 4's
  replay/idempotency bar cannot run in CI.

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
3. **Custody createOrder must move to Lambda (r2 C-1 — architecture, not
   preference).** AppSync JS/VTL resolvers on DynamoDB data sources have no
   `TransactWriteItems`; a JS "port" would be sequential single-writes on
   the top money/stock path — the exact partial-write class the factory
   hardened against. Custody executes in Python Lambda (direct resolver or
   pipeline step); oracles-first stays (53-case committed-replay pin,
   corruption-direction probes). Corrected from the survey's JS-rewrite
   framing; wave 3 budget = new function + role + wiring, not resolver-only.
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
   missing one fails CI late. r2 C-4 names the three specifics: per-table
   NAME env maps in each environment main.tf (their hand-maintained 9-entry
   pattern), `scripts/ephemeral-env.sh` up/env branches, and
   `scripts/ephemeral-recover-common.sh` importing every new table slug +
   IAM role/policy pinned by
   `test_ephemeral_reliability.py::test_dynamic_resource_import_coverage`.
9. **Additive-schema nullability/default audit (r1 item 3).** Legacy rows
   keep existing defaults; every new field on extended types needs an
   explicit nullability/default audit so old rows read coherently.
10. **Cognito MFA posture (r1 item 3).** Lane personas stay unenrolled;
   admin automation handles MFA codes. Recorded so ephemeral automation
   does not fight the pool's MFA settings.
11. **mypy friction (r2 N-1, folded into this list).** ~5-6k lines of new
    typed Python under their `mypy src/` gate is a real review loop beyond
    the coverage cost; budget for it in every backend wave.
9. **Section-11 decisions are pre-answered by the map's recommended defaults
   and all six MATCH our implemented behavior** (final-admin delete block,
   joined-campaign delete block, custody-return before profile deletion,
   post-fulfillment edit policy, join-time catalog identity, 7-day marker
   TTL — we used a 366-day invite cap; markers align to the map). No product
   decisions are open from my side; anything beyond these six = STOP-AND-ASK.

## 5. Immediate next steps (wave 1 — DISPATCHED 02:17Z; this list is the
## definition of done)

1. Schema merge (new types only) + codegen regen + drift guard. IN FLIGHT.
2. Five tables + env maps in all three environments + accessor tests,
   including the r2 C-4 specifics: (a) the hand-maintained per-table NAME
   maps in each environment `main.tf` (their 9-entry pattern — handlers
   read names, not arns); (b) `scripts/ephemeral-env.sh` exports the five
   names in `up` and `env` branches; (c)
   `scripts/ephemeral-recover-common.sh` imports all five table slugs +
   every new IAM role/attachment/inline policy, pinned by
   `test_ephemeral_reliability.py::test_dynamic_resource_import_coverage`.
3. `unit_auth.py` + error-vocabulary DECISION RECORDS (r1 item 1:
   RATE_LIMIT_EXCEEDED throttle-vs-cap design decision; suppression of
   INVITE_EXPIRED/INVITE_ALREADY_USED into NOT_FOUND indistinguishability;
   CONFLICT authorized-details table) + strict validators.
4. Transaction/idempotency/cursor helpers in `src/utils/dynamodb.py` with
   our golden probes translated (53-case replay pin home; two-backend
   real-DynamoDB contract suite home; ADR/ruling records + acceptance
   probes; tick-traceability owner row).
5. CI guard updates (surface, depth, wiring, IAM) so later waves fail fast,
   including the AppSync service-role write-surface reconciliation (r2
   N-5): field resolvers limited to reads and legacy; new writes go through
   Lambda under the show-and-sell domain role.
6. Recorded org decisions in the commit trail: one `show-and-sell` domain
   role (r2 C-2), separate event_operations/sale_operations modules
   (r1 item 3), short-lived-events time arrangement (r2 C-3).
7. Sanction line for reviewers (r2 N-3): extending their
   `dynamodb.py`/`errors.py`/`pagination.py` with minimal diffs is
   sanctioned by this plan; everything else is new files.
8. Recorded note (r1 item 4): their js-resolver `util.error` 4-arg form
   already carries `errorCode` — this is the recorded fix for the
   clean-room adapter-wave MEDIUM; no js-resolver error-shape work needed.

Estimate: wave 1 is a multi-day gated effort; waves 2-8 per §3 with the
risk-5/11 cost multipliers (coverage + mypy) applied.

## 6. Plan reviews

- r1 (`docs/review/integration-plan/01-review-r1.md`): CHANGES — four
  items, all folded above (error-vocabulary rewrite; ADR/ruling +
  replay-pin + two-backend + tick-traceability homes; three new risks +
  module-split decision; js-resolver errorCode note).
- r2 (`docs/review/integration-plan/01-review-r2.md`): CHANGES — C-1
  custody-in-Lambda architecture fix; C-2 one-domain-role decision RULED;
  C-3 time arrangement RULED; C-4 three CI-fails-late items named in §5;
  N-1/N-3/N-5 folded; N-4 pin count corrected; N-2 sizing accepted.
- Disposition: this revision (delta only) returns to r1+r2.
