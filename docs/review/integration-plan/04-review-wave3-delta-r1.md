# Independent Review — wave-3 delta, kw-ss-wave2 @ 7213531f (review-r1)

- **Reviewer:** review.r1 (independent; no authorship)
- **Target:** 79f804c3..7213531f (stacked on the reviewed wave-2 boundary)
- **Method:** scoped per dispatch; handlers, JS router, and pins read in a
  detached worktree (removed after); their gates run at the head.

## Verdict: APPROVE on all six items. Gates green: 2142 passed / 3 skipped
## at 100.00% coverage; ruff + mypy clean. The wave-2 CHANGES item (GSI
## decision record) is also landed and verified.

### 1. Read-then-plan concurrency with named cancel mappings — APPROVE
`execute_transaction`: preflight (dup-key + size), `TransactionCanceledException`
→ `TransactionCancelledError` carrying failed item indexes for domain
mapping, transient-only bounded retries with exponential backoff, and a
moto/real wire-form split documented inline. Handlers map cancels to named
errors (`_raise_removal_cancel`, `FULFILLMENT_INVALIDATED` with its D-3
authorized reason). The subtle one is handled explicitly:
`from_dynamodb_json` normalizes Decimal → int/float deep-copy so a stored
committed-replay result compares EQUAL to the live result — the
marker-comparison correctness point most ports get wrong.

### 2. Section 7 derived formulas verbatim — APPROVE
`inventory_derived.py` reproduces all ten §7 formulas literally (probed
line-by-line against the spec table): sellable, assigned-open, unassigned
with the max(0,…) floor, overage, with-Scout, total-owned, both council-need
forms with the §7 exclusions (with-Scout/on-order never reduce need; covered
We Owe is not demand) in the docstring. Pure functions over plain ints —
wave-4 allocations plug in as inputs without formula changes.

### 3. Custody as ONE transaction — APPROVE
The custody plan is exactly one `TransactWriteItems`: order Put (additive
origin shape, fulfillmentVersion 0, stable line ids), per-line conditioned
custody Updates (sufficiency + version), movement Put, campaign-totals
Update (because the router early-return skips the JS totals sync), and the
idempotency marker. The router (`custody_router_fn.js`) makes the
double-write ban structural: custody results take `runtime.earlyReturn` —
the legacy `create_order_fn` and sync steps cannot run; NONE answers
`{"__continue__": true}` and proceeds to the legacy steps exactly as the
phase-A golden oracles pin them. Oracles-first was honored in the commit
order (7f91bc31 before the implementation).

### 4. Fulfill/reverse invariants — APPROVE
At-most-once: fulfillment Puts conditioned `attribute_not_exists`, reversals
on deterministic `REVERSAL#<originalId>`; `fulfilledQuantity + quantity >
ordered` → CONFLICT with the authorized `FULFILLMENT_INVALIDATED` reason
(D-3 table); `fulfillmentVersion` optimistic concurrency inside the same
transaction as the fulfillment row and the source-specific inventory
entries; append-only fulfillment history never rewritten (the update-path
guard enforces the same).

### 5. update_order line-identity preservation — APPROVE
`preserveLineIdentity` in their `update_order_fn.js`: product-matched lines
keep `lineItemId` and `fulfilledQuantity`; an edit below the fulfilled
quantity is rejected (`CONFLICT`) — the impact-map edit policy; genuinely
new lines mint ids at zero fulfilled; legacy id-less lines gain one (the
enabling step for fulfillment on updated orders). The shared-path test pins
the interplay with the custody enrichment.

### 6. Schema-derived pin — APPROVE
`test_committed_replay_pin.py` enforces three structural contracts:
DISPATCH ⊆ SCHEMA (seam-only drift fails), PIN_CASES == DISPATCH with
exact-set equality (a new mutation cannot land without its probe; this is
what caught the wave's 7 undeclared mutations), and every named probe
resolves at import. The NONE-path marker-lessness is an explicit recorded
contract (`test_none_create_order_has_no_marker_by_design`), not an
accident.

## Wave-2 CHANGES item — verified landed
`docs/investigations/show-sell-invite-discovery-consistency.md` names the
§6.1 deviation, the layout-forced rationale, the residual (NOT_FOUND burns
a throttle attempt; per-account-hour decay; no-Scan invariant intact), and
the standing-acknowledgment stance.

## Gates (run at the head)
`pytest tests/unit`: **2142 passed, 3 skipped, 100.00% coverage**. ruff +
mypy clean on the new modules. The 1,123-line order test file and the
golden JS oracle complement show the gates honored from the inside.

## Disposition
Wave 3 APPROVED from my seat. The highest-risk wave of the integration
(custody on the money/stock path) landed as oracles-first, one
transaction, structural double-write ban, and a schema-derived pin that
makes the replay contract un-skippable. Wave 4 (events — the largest
volume, our replay/corruption probes as the acceptance bar) is next.
