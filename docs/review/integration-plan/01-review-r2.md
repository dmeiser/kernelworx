# Independent Review — Show & Sell Integration Plan, fresh-eyes sweep (review-r2)

- **Reviewer:** review.r2 (independent; author of none of the survey)
- **Target:** `docs/SHOW_SELL_INTEGRATION_PLAN.md` @ 09f3d9c (branch
  kw-ss-integration, base origin/main f3c8a77). Survey-only branch; no
  feature code exists to probe, so this review verifies the plan's measured
  claims against the application as built and hunts whole-integration
  invariants the survey may have missed.
- **Authorization:** captain ruling 2026-11-09 — clean room closed;
  reading the application is authorized. Clean-room tree preserved at
  `show-sell-cleanroom` (a567675), which I also used as the spec/impact-map
  source of truth.
- **Method:** every "measured, not estimated" claim re-measured; every
  convention claim read in the actual modules; impact map
  (§3/§4/§5/§10/§11) cross-checked line by line against the plan.

## Verdict: CHANGES REQUESTED — four specifics; everything measured in the
## plan checks out

The survey is genuinely good: the measured numbers are exact (SDL 1347
lines / 57 constructs ✓, 314 js-resolver files ✓, `dynamodb.py` 297 /
`auth.py` 426 ✓, vitest thresholds 99/97/96/97 with a "do not lower"
comment ✓, codegen drift gate in CI ✓), the file-by-file map matches the
impact map, the risk list is honest, and the schedule candor (risk 5: days
not hours; "wave 1 is a multi-day gated effort") is real. The four items
below are the invariants a fresh pass catches that an incremental survey
could not — one is an architecture impossibility the plan currently
instructs wave 3 to attempt.

---

## C-1 (the headline): the custody transaction cannot live in an AppSync
## JS pipeline — risk 3 as written is architecturally impossible

The plan (§2.1, §3 step 3, risk 3) says the custody `createOrder` redesign
is "a JS rewrite" of our Python, with our probes as oracles. Their
`createOrder` today is `create_order_pipeline_resolver.js` +
`create_order_fn.js` — an **AppSync JS pipeline resolver on a DynamoDB
data source**. AppSync DynamoDB data sources (VTL or JS, unit or pipeline)
support GetItem/PutItem/UpdateItem/DeleteItem/Query/BatchGet — **not
`TransactWriteItems`**. Our custody design is a five-table atomic
transaction (order row + custody conditional update + movement +
fulfillment + idempotency marker, under the 90-action preflight, bounded
race retry, and committed-replay semantics the factory spent stages 2-4
hardening). A JS-pipeline "port" can only be sequential single-item ops —
which reintroduces the exact partial-write class the clean room exists to
prevent, on the highest-stakes money/stock path in the product.

**Fix the plan, not the product:** custody mode executes in **Lambda** —
either a direct Lambda resolver (extend their Python
`src/handlers/order_operations.py`, their Lambda-module convention) or a
Lambda function step inside the AppSync pipeline (AppSync pipelines
support Lambda functions as steps; the JS pipeline keeps NONE-mode and
delegates CONSUME_SCOUT_CUSTODY to the transaction Lambda). Keep the
plan's correct parts: golden oracles FIRST (the 53-case committed-retry
pin — the plan says 43; the number drifted), then implement. Wave 3's
estimate and review plan should assume a new Lambda function + domain-role
entry + wiring tests, not a resolver-only change.

## C-2: role granularity is a wave-1 org decision, and the plural
## "scoped roles" framing will not survive contact with our transactions

Impact map §4.2 and the plan say "scoped Unit/Unit Campaign/inventory/
Show & Sell roles." Their IAM convention is real least-privilege per-domain
roles (the campaign role names its tables explicitly:
`campaign_table_keys = ["campaigns", "orders", "profiles", "shares"]`,
read actions + one scoped write, `arn/index/*`, no Scan — verified in
`modules/iam/main.tf`). But a single `TransactWriteItems` executes under
ONE role, and our transactions routinely span 3-5 of the new tables plus
legacy tables: join writes `unit_campaigns` + `campaigns` + marker;
custody order writes `orders` + `inventory` + `order_fulfillments` +
marker; signup/finalization spans `show_and_sells` + `unit_campaigns` +
`inventory`. Four scoped roles means every shared table grant duplicated
four ways — and the no-fallback `lambda_domain_role_arns` wiring fails
loudly (good) but at the worst time. Also: **`TransactWriteItems` appears
in NO current policy** (verified — item-level actions only, plus
`ConditionCheckItem` on the AppSync service role); it is a new grant
everywhere, including the AppSync-direct paths the map names.

**Fix:** decide in wave 1 — recommendation: ONE `show-and-sell` domain
role owning the five-table family + explicit statements for the legacy
tables its transactions touch (`campaigns`, `orders`, `profiles`,
`public_order_throttles`, `shares` as needed), with the map's
"actual-TransactItems-table capture" test as the acceptance pin. This is
the same class of "org decision, not product" the plan itself flags for
the finalization module split — it deserves the same explicit marking.

## C-3: the integrated test stack has no time-arrangement story (our D4
## doctrine has no counterpart here)

Our entire stage-3/4/5 verification leans on the persona seam and
`devAdvanceClock` to arrange SCHEDULED/ACTIVE/ENDED/FINALIZED states
deterministically; event states are derived from interval+clock (9.1), and
finalization/reopen/sale-state gates are all time-gated. The integrated
app has neither seam, and its ephemeral tests run the real stack on real
time. Testing "finalize an ENDED event, reopen it, re-finalize" against
ephemeral requires either real waiting or a new test-only clock. The
plan's risk 6 covers identity (correctly) but not time.

**Fix:** name it in wave 1 — either short-lived real events with
clock-independent assertions, or a guarded test-only clock behind an env
flag with the same purity discipline we used (composed only into the
dev/ephemeral surface, structural purity test, bounded offset). Without
this, wave 4's replay/idempotency acceptance bar (the plan's own words)
has no way to run in CI.

## C-4: wave-1 next steps omit three named CI-fails-late items the impact
## map itself requires

The plan's §5 step 2 says "five tables + env maps in all three
environments." The impact map is more specific, and the plan should be
too: (a) the Lambda `table_names` map is a **hand-maintained per-table
name map in each environment main.tf** (dev lines 289-297 show nine
explicit entries — the plan says "table_arns/outputs" but the names map is
what handlers actually read); (b) `scripts/ephemeral-env.sh` must export
the five names in its `up` and `env` branches (map line 148); (c)
`scripts/ephemeral-recover-common.sh` must import all five table slugs +
every new IAM role/attachment/inline policy, pinned by
`test_ephemeral_reliability.py::test_dynamic_resource_import_coverage`
(map line 322). These are exactly the plan's own risk-8 class ("missing
one fails CI late") — name them in §5 so wave 1's definition of done
includes them.

---

## Verified accurate (the plan's strong side)

- All measured claims re-measured: exact.
- Domain-role no-fallback mechanism exists and matches the plan's "no
  fallback role" (#326/#355 wiring; `lambda_domain_role_arns` required for
  every non-admin function).
- PITR/deletion-protection/encryption flow through existing module
  variables; the five-table change is purely additive Terraform with
  per-environment S3 state + lockfile — no state-migration risk; ephemeral
  instantiates the same dynamodb module with `prevent_destroy = false`.
- AGENT.md/CI: PR-only, 100% Python unit coverage ("No exceptions"), ruff
  + mypy (`mypy src/` only), uv, shellcheck guard, codegen drift check,
  per-PR ephemeral + scheduled re-run. No direct conflict with the plan.
- Public-API-key surface: their app genuinely has one (public orders,
  `PUBLIC_API_KEY_RUNBOOK.md`); the plan's "Cognito-only new fields +
  port the surface guard" matches their existing guard tests.
- `getUnitReport`/`requestCampaignReport` names exist verbatim in their
  schema (line 1029) — the deprecation claim is accurate.
- The six §11 decisions all match our implemented behavior (plan risk 9) —
  consistent with my own stage-1 through stage-5 reviews of that behavior.
- Schedule honesty: risk 5 (coverage doubling, days not hours), risk 7
  (frontend is a rewrite), and the §5 wave-1 estimate are candid.

## Additional notes (non-blocking)

- **N-1:** mypy friction is absent from the risk list. ~5-6k lines of new
  typed Python under `mypy src/` (their gate) will be a real review loop
  beyond the 100%-coverage cost risk 5 names. Add one line to risk 5.
- **N-2:** only wave 1 is estimated. Waves 2-8 have no order of magnitude;
  with coverage + mypy + Playwright + golden-oracle ports, waves 3-4 are
  weeks, and wave 5's parity-then-retirement is gated on browser-engine
  work sized nowhere in the plan. A per-wave order-of-magnitude row makes
  the plan committable.
- **N-3:** AGENT.md's "minimal changes / prefer adding new files" sits
  slightly against §2.2's "extend THEIR files" (dynamodb.py, errors.py,
  pagination.py). Both are fine in intent; say explicitly that extending
  those three files is sanctioned so wave-1 reviews don't relitigate it.
- **N-4:** the replay pin count is stale (plan says 43; the pin is 53
  mutations now). Trivial.
- **N-5:** the AppSync service role already carries `ConditionCheckItem`
  (with an explicit comment naming TransactWriteItems) — evidence the
  transaction question has been touched before; wave 1 should reconcile
  the direct-data-source write surface (the service role can Put/Update/
  Delete ALL tables via field resolvers) with the "complex writes go
  through Lambda under the domain role" rule, or the least-privilege story
  has a hole at the AppSync layer.

## Disposition

C-1 through C-4 are plan-text corrections (three of them name what the
impact map already knows; one corrects wave 3's architecture). No product
code exists, so nothing here blocks implementation start on waves whose
plans are unaffected — but the plan should be amended before dispatch,
with C-1 and C-2 resolved in the text (C-2 as the flagged org decision).
With those amendments this is an APPROVE; re-review of the delta only.
