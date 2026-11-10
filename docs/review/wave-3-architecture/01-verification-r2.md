# Wave-3 Architecture Verification — custody createOrder (review-r2 close-out of C-1)

- **Reviewer:** review.r2 (author of the C-1 ruling under trial)
- **Target:** kw-ss-wave2 @ 7213531f (wave-3 custody chain
  7f91bc31 → e27c68c7 → 52b8cf7c → f5bce68f → 7213531f, plan rev 1 b628f172)
- **Method:** full read of `src/handlers/order_operations.py` (915 lines),
  `custody_router_fn.js`, the createOrder pipeline wiring, the wave-1
  transaction helpers in `src/utils/dynamodb.py`, the show-and-sell IAM
  role, and the wave-3 test suites; spot-run of the five relevant test
  files (75 passed, 1 failed — the failure is finding 2).

## Verdict: ARCHITECTURE CONFIRMED on the C-1 core, with three CHANGES —
## one of them (ADR-0002) is a live doctrine reversion the mission's own
## acceptance probe is catching red-handed.

### Confirmed (the claims as stated)

1. **Router answers NONE without touching custody.** `custody_create_order`
   returns `{"__continue__": True}` for absent/NONE mode before any table
   read or write (order_operations.py:468-471); the pipeline then runs the
   legacy steps exactly as the golden oracles pin (verified in
   `custody_router_fn.js` and the pipeline order in
   `resolvers_mutations.tf`).
2. **CONSUME mode is exactly one TransactWriteItems.** One plan built by
   `_custody_create_plan` — order Put (`attribute_not_exists`), per-product
   custody Update (`ADD withScoutQty :neg` with `withScoutQty >= :min`
   sufficiency condition), movement Put, campaign-totals Update — plus the
   idempotency marker Put appended to the SAME plan; a single
   `execute_transaction(plan)` call site (line 522). Duplicate same-product
   lines aggregate into ONE custody update (the S2-3 over-draw lesson is
   carried). Fulfill/reverse likewise build one plan per call (single
   `execute_transaction` funnel with client-side preflight: 100-item cap,
   duplicate-key rejection, `CancellationReasons` classification, bounded
   throttling retries).
3. **No JS-path sequential writes on the money/stock path.** The custody
   early-return (`runtime.earlyReturn`) skips `create_order_fn` AND
   `sync_campaign_totals` — the totals ride inside the transaction (the
   #746 counter invariant is preserved by construction, and the existing
   `test_order_write_pipelines_sync_campaign_totals` still passes).
4. **Typed-wire serialization holds the moto-hidden class.** Real clients
   receive boto3 `TypeSerializer` per-attribute form (`{"S": "unit-1"}`,
   pinned by `test_success_sends_typed_wire_form` on a non-moto mock);
   moto is bypassed by detection, never by default. Money is Decimal
   dollars on the wire (legacy shape, `Decimal(str(cents/100))`), so the
   client-rejects-float class cannot fire; markers embed results as JSON
   strings (moto's Decimal-map limitation) and `from_dynamodb_json`
   normalizes both paths so committed-replay equality is payload-exact
   (`test_replay_returns_same_order`: `second == first`, custody drawn
   once).
5. **IAM surface is least-privilege under their conventions.** One
   `show-and-sell` domain role (the C-2 ruling, recorded in the plan);
   reads are GetItem/Query/BatchGetItem with NO Scan; item writes scoped;
   `TransactWriteItems` appears ONLY as an explicit 7-table allow-list
   (five family + campaigns + orders) with per-table ARNs — the only
   wildcard is `arn/index/*` per the repo's own GSI convention. The
   monolithic shared role is retired (#355), so the function carries
   exactly this role; `order-operations` entries exist in all three
   environment `lambda_domain_role_arns` maps; the acceptance pin
   (`test_iam_show_and_sell_role`) exists.

### CHANGES

**C-1v: ADR-0002 silently reverted on the custody path (HIGH).** The
custody transaction draws Scout custody but records NO order_fulfillments
rows and writes line `fulfilledQuantity: 0` (order_operations.py:265, and
the module docstring states it outright: "fulfilledQuantity 0 — the
wave-3 additive shape"). That is exactly the silent reversion the plan's
own revision-1 ruling-semantics row was written to prevent ("ADR 0002
fulfilledQuantity … each get a wave-1 record plus a per-wave acceptance
probe — otherwise re-expression silently reverts them"). Consequences,
all pinned by the doctrine our factory verified across stages 2/4:
consumed custody is invisible on the order (participant and admin
`fulfillments` projections show nothing for handed-over stock); the
pinned reversal path cannot restore it (reversal looks up fulfillment rows
that were never written); order-line facts report fulfilled 0 against a
real draw; and §5.19 conservation (`consumed = fulfilled` is the only
reading that keeps the books closed) breaks. Fix: the custody transaction
carries the fulfillment Put(s) (`source: SCOUT_CUSTODY`, quantity =
consumed) and the order row's line `fulfilledQuantity = consumed` — same
transaction, capacity accounted (3 actions per consumed line, the
preflight already counts) — and the response exposes `fulfillments`, per
the oracle.

**C-2v: a failing acceptance probe is committed at HEAD (CI is red).**
`tests/unit/test_order_operations.py::TestQACorruptionDirectionProbe::test_qa_custody_reversal_restores_only_custody_source`
fails deterministically (`KeyError: 'fulfillments'` — it asserts the
ADR-0002 shape), no skip marker, 1 failed / 38 in the file at HEAD
(7213531f). Under this repo's own gates (AGENT.md: 100% coverage, all
tests green) the wave-3 branch cannot be green; any green claim made for
it is false. The probe is doing exactly the job the plan assigned it —
the disposition is to satisfy it (implement C-1v), not to delete or skip
it. If it was committed red knowingly as a placeholder, that needed to be
said in the commit, not discoverable by review.

**C-3v: the continue-ban guard, as claimed, does not exist yet (MEDIUM).**
"Cannot be bypassed by a later edit" is currently enforced by nothing:
no test pins `custody_router` before `create_order_fn` in the
`create_order` pipeline (the sibling invariant `sync_campaign_totals
after the write step` IS pinned — the pattern exists in
`test_order_write_pipelines_sync_campaign_totals`), and
`create_order_fn.js` does not refuse a custody-mode input. Consequences
if a later edit removes or reorders the router step: CONSUME orders flow
into the legacy write path and are persisted as plain NONE orders — no
custody draw, no marker, no origin, no error (silent money/stock
corruption); ordered the other way, the legacy write commits and the
custody transaction then cancels — a loud error with a committed orphan.
Fix (both cheap, both conventional): a terraform test asserting
`pipeline.index(custody_router) < pipeline.index(create_order)` and
`create_order_fn` raising on any `fulfillmentMode` other than absent/NONE.

## Re-verification — fix landed 902728e8 (+c8b4fb9e) (r2 second pass)

**Verdict: ARCHITECTURE CONFIRMED — all three CHANGES closed by effect.**
Suites: 82/82 across the six wave-3-relevant files (order operations 42/42,
transactions, IAM role, pipeline functions, resolver wiring, and the NEW
`test_create_order_pipeline_order.py`).

### C-1v closed — ADR-0002 restored on the custody path
- `_create_time_fulfillments` writes one SCOUT_CUSTODY fulfillment PER
  CONSUMED LINE, in the SAME transaction: the plan is built as order Put +
  custody Update + movement Put + totals Update, then
  `plan.extend(_fulfillment_puts(...))`, then the marker — one
  `execute_transaction` call site (order_operations.py:620).
- Line `fulfilledQuantity` equals the consumed amount via
  `_allocate_consumption`: deterministic spec-8.5 min-consumption, lines
  consume in order against per-product remaining availability, shortfall
  NEVER blocks, custody NEVER negative.
- The response carries the participant-safe `Order.fulfillments`
  projection, and the marker stores the FULL response (idemResultJson
  includes fulfillments) — committed-replay equality by construction.
- My independent plan-capture probe (monkeypatched executor, swallowed
  write): exactly ONE transaction; 4 Puts (order, movement, fulfillment,
  marker) + 2 Updates (custody with `withScoutQty >=` condition, campaign
  totals); fulfillment Put in-plan with quantity = consumed,
  source SCOUT_CUSTODY. My independent effect probe: ordered 4 with custody
  2 → fulfilledQuantity 2, response fulfillments [2], custody row 0,
  order_fulfillments row persisted.

### C-2v closed — the red probe is green
`TestQACorruptionDirectionProbe` (all of it, including
`test_qa_custody_reversal_restores_only_custody_source`) passes: custody
reversal restores only the custody source; custody drawn exactly once,
never negative; kernel untouched.

### C-3v closed — the continue-ban guard now exists
- `tests/unit/test_create_order_pipeline_order.py`: custody_router present,
  strictly BEFORE the legacy `create_order` write step, AND the
  auth/load steps strictly before the router (both directions).
- `create_order_fn.js` refuses `CONSUME_SCOUT_CUSTODY` loudly — even a
  router removal degrades to a loud error, never a silent NONE write.

### Residual note (non-blocking)
The custody plan-size guard is the wave-1 `MAX_TRANSACT_ITEMS` (100, the
DynamoDB hard limit) via `execute_transaction` preflight. The clean-room
§8.10 business cap (90, finalization headroom) is a wave-4 concern when
finalization lands on this stack; noted for that wave's acceptance bar.

**Close-out: the mission's largest single risk is closed.** The C-1
architecture shipped as ruled and now carries the doctrine layer (ADR
0002, spec-8.5, committed-replay) with guards against its own regression.
