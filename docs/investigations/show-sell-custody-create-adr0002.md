# Custody createOrder — ADR-0002 on the custody path + spec 8.5 min-consumption

Status: RECORDED (wave 3, r2 C-1v + QA divergence, fixed in commit
7213531f..HEAD on kw-ss-wave2; QA re-runs probes, r2 re-verifies).

## What was wrong (r2 C-1v, HIGH)

The first custody implementation drew Scout custody at order creation but
wrote **no `order_fulfillments` rows** and left `fulfilledQuantity` at 0.
That silently reverted ADR 0002 (the fulfilledQuantity judgment) on the
custody path:

- consumed custody was invisible on both projections (order + fulfillments);
- the pinned reversal path had nothing to reverse — consumed stock could
  never be restored;
- spec 5.19 (conservation) broke: stock left custody without a record.

Re-expression had silently dropped a ruling the clean room spent stages
2–4 hardening — exactly the class r2's verification rubric exists to catch.

## The corrected contract

Consuming Scout custody at creation **is** a fulfillment, in the SAME
transaction:

- every line that consumed stock gets a `SCOUT_CUSTODY` fulfillment record
  (quantity = consumed amount);
- `lineItems[i].fulfilledQuantity` equals the consumed amount;
- the response carries the participant-safe `Order.fulfillments` projection
  (parent-supplied field; no admin-only attributes);
- the committed-replay marker stores the full response (projection
  included), computed deterministically before commit;
- reversing a create-time custody fulfillment returns stock to with-Scout
  custody (`REVERSAL_RETURN` movement) — conservation runs both directions;
- the legacy NONE writer refuses `CONSUME_SCOUT_CUSTODY` loudly and
  parent-supplies `fulfillments: []` (r2 C-3v), and a terraform test pins
  the custody router BEFORE `create_order_fn` in the pipeline.

## Spec 8.5 min-consumption (QA divergence, folded into the same fix)

The first implementation conditioned the whole order on FULL with-Scout
coverage (CONFLICT on shortfall). Spec 8.5 mandates **min(ordered,
available)** consumption with the unfulfilled remainder — a shortfall never
blocks the order:

- per product, consumption = min(ordered total, available);
- lines consume deterministically in order against remaining availability;
- the consumed portion fulfills (records above); the remainder stays
  unfulfilled (`fulfilledQuantity` < `quantity`);
- custody never goes negative; the conditioned draw remains as a race
  guard (`withScoutQty >= :consumed`), with cancel-races mapped to a named
  CONFLICT;
- SS-SM-04 partial-sale oracle pinned exactly: custody 2, ordered 4 →
  consumed 2, fulfilled 2, remainder 2, zero CONFLICT.

The pre-transaction `INSUFFICIENT_CUSTODY` block was removed — it encoded
the divergent semantics.

## The corruption-direction probes

QA's planted probes (`TestQACorruptionDirectionProbe`) originally pinned
the divergent behavior. Per the lead's ruling they now pin the corrected
contract (updated in the fix commit, mechanics adapted to the shipped
surface: fulfillments resolved from `order_fulfillments`, the SDL argument
name `expectedFulfillmentVersion`, the actor as the profile owner). They
are kept, not skipped — future regressions fail here.
