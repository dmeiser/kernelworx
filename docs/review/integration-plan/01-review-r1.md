# Independent Review — Show & Sell Integration Plan (review-r1)

- **Reviewer:** review.r1 (independent; no authorship)
- **Target:** `docs/SHOW_SELL_INTEGRATION_PLAN.md`, branch kw-ss-integration
  @ 09f3d9c (base origin/main f3c8a77)
- **Method:** adversarial read of the plan against the real kernelworx
  tree (clean room closed by captain call 2026-11-09). Convention claims
  verified by direct file reads; completeness checked against our
  gate-proven surface (137/281 ticks, 10/11 recordings at a567675).

## Verdict: CHANGES — the architecture is sound (theirs-over-ours
## throughout, wave order matches the impact map, the risk list is
## honest) but four specifics must land before this plan dispatches:
## one misdiagnosed risk, two completeness gaps (R78-class), two risk
## additions.

---

## 1. Risk 1's example is wrong; the vocabulary work is misdiagnosed
The plan frames the mapping as "we have `RATE_LIMITED`, they want
`RATE_LIMIT_EXCEEDED`" — backwards. Our `RATE_LIMIT_EXCEEDED` is
spec-mandated (§6.6, wave 1 of the clean room); **their Python has no
RATE_LIMIT code at all** (verified: `src/utils/errors.py` ErrorCode has
FORBIDDEN/UNAUTHORIZED/MFA_REQUIRED/NOT_FOUND/ALREADY_EXISTS/
INVALID_*/PUBLIC_ORDER_LIMIT_EXCEEDED/INVITE_EXPIRED/
INVITE_ALREADY_USED/CAMPAIGN_READ_ONLY/INSUFFICIENT_PERMISSIONS/
CONFLICT/INTERNAL_ERROR/DATABASE_ERROR/RESOURCE_BUSY). CONFLICT and
RESOURCE_BUSY exist on both sides; the real table entries are:

- **Our `RATE_LIMIT_EXCEEDED` (invite-redemption throttle) → decision
  needed.** Their `PUBLIC_ORDER_LIMIT_EXCEEDED` is a lifetime-cap
  concept, not a throttle. This is a design entry, not a rename.
- **Bidirectional narrowing, not renaming.** Their `INVITE_EXPIRED` /
  `INVITE_ALREADY_USED` are exactly the distinct codes our spec forbids
  (§5.3: expired/deleted/used codes are indistinguishable → NOT_FOUND).
  The ported redemption path must SUPPRESS their convenience codes, or
  the Show & Sell surface leaks an existence oracle through their
  vocabulary. Same class for any of their codes our spec doesn't have.
- **CONFLICT detail reasons** (STALE_VERSION/LAST_GRANT/
  OPERATION_TOO_LARGE) forward per impact-map 3.1's authorized-details
  rule — their CONFLICT exists but their detail conventions need the
  explicit table entry.

The wave-1 placement of the table is correct (it gates waves 2–4, and
nothing can precede wave 1). The table's content spec must be rewritten
per above.

## 2. Completeness gaps (unmapped proven surface — R78-class)

**(a) ADR / ruling semantics have no landing row — the highest-risk
omission.** Our decision records are load-bearing semantics with
probes: ADR 0001 tombstones (FORBIDDEN vs NOT_FOUND), ADR 0002
custody-consumption counts as fulfilledQuantity, ADR 0003 auto-reduce
consumes per-campaign stock (not interval overlap), the W10
return-baseline/union-key ruling, the W13 omission-means-zero ruling.
Re-expressing handlers against their five-table layout (risk 4 rightly
fears this) silently reverts these without them. Land in wave 1 as
ported decision records plus per-wave acceptance probes (the
auto-reduce retightening is the canonical example of what goes wrong).

**(b) The replay pin as a general suite convention has no home.** Risk 3
names the 43-case custody pin; §2.6 says "race/idempotency probes port
as oracles." But the schema-derived committed-retry pin (both-direction
coverage equality, every mutation) is a CONVENTION, not a probe set — it
deserves an explicit wave-1 test-infrastructure row or it dies with the
clean-room branch. Same for (c) the two-backend (real-DynamoDB)
contract suite — named as a bug class in risk 4, given no §2.6 home.

**(d) Tick traceability is unowned.** QA R78 makes an unmapped tick a
defect; the plan maps files and tests but not how the 281-tick evidence
chain maps onto their PR/issue conventions. Name the home (a tracking
doc per wave, tick references in PRs).

## 3. Risk-list additions
- **(e) Live-table additive schema.** §2.3 extends Campaign/Order/
  LineItem on a live application. Nullability/default audit for existing
  rows (origin/fulfillmentVersion defaults) is unnamed; say "no backfill
  needed, additive-nullable, defaults in from_item" or name the
  reconcile.
- **(f) MFA surface.** Their pool is MFA-OPTIONAL (software_token +
  SMS role, `modules/cognito/main.tf:220`) with an `MFA_REQUIRED` admin
  code path (#451). Persona smoke automation must confirm lane users
  stay MFA-unenrolled, and any admin-surface automation must handle the
  code. One paragraph in risk 6.
- **(g) Review bandwidth.** The ~2700-line show_and_sell_operations
  module needs a decided split or a named review strategy; the plan
  mentions it as an aside. Logistics risk, one line.

## 4. Verified sound (the adversarial read's negative space)
- **Conventions: theirs over ours, everywhere checked** — `tables`
  registry accessors, `with_error_handling`, co-located JS-resolver
  tests, PR-only AGENT.md (no agent approvals/merges), branch coverage
  with `omit = []`, MUI/Apollo/codegen rewrite (not merge). All verified
  in-tree.
- **Their JS error forwarding solves our adapter-wave precondition.** 
  `batch_qr_urls_fn.js:79`: `util.error(message, errorCode, null,
  { errorCode })` — the four-arg form carries errorCode through. Route
  this pattern back to the adapter wave as the recorded fix direction
  for the deferred MEDIUM.
- **Wave-1 scoping** is right; the error table is correctly the gate;
  nothing should move earlier than wave 1 (it IS first), and within
  wave 1 the order (schema → tables → mapping table → helpers) holds.
- **Basis facts** verified: a567675 exists, 137/281 + 10/11 recordings
  match the record; the impact-map §10 order is honored with our wave
  experience annotated rather than substituted.

## Disposition
Rewrite risk 1's table spec (§1 above); add rows (a)–(d) to §2 with
wave-1 homes; add risks (e)–(g). Then this plan is dispatch-ready — the
skeleton (file map, wave order, conventions, honest risks) is the right
shape and I found no wrong wave and no convention inversion.
