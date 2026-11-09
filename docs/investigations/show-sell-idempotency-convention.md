# Show & Sell idempotency + transaction convention — wave-1 record

Status: RECORDED (wave 1, integration plan section 5 step 4; r1 item 2
"ADR/ruling semantics land as records"). Ported from the gate-proven
clean-room build (stages 2-4, review-hardened); helpers live in
`src/utils/dynamodb.py` (`execute_transaction`, `new_marker_item`, and
kin), cursors in `src/utils/pagination.py`.

These rules are the acceptance bar for every Show & Sell mutation handler.
Re-expression silently reverts them; per-wave probes check them.

## The convention

1. **Deterministic validation first.** Input validation that depends only
   on the request runs BEFORE the marker is read. Everything that depends
   on state (existence, guards, balances, versions) lives INSIDE the
   transaction plan. Rationale: a committed retry must replay identically;
   a state check outside the transaction made the first attempt's plan
   unrepeatable (the replay class recurred 3x across clean-room stages
   before this rule existed).

2. **Marker and effect in ONE transaction.** The idempotency marker is a
   Put in the same TransactWriteItems call as the effect. A committed
   marker always means a committed effect; there is no window where one
   exists without the other.

3. **Committed-replay equality.** A marker whose stored request
   fingerprint matches the incoming request replays the stored result —
   equality, never re-execution. A fingerprint mismatch fails the
   transaction's condition on the marker (the caller reused a key with a
   different request: CONFLICT, not an overwrite).

4. **Bounded race retries (F1 ruling).** At most `MAX_RACE_RETRIES` (3)
   attempts, exponential backoff on transient throttling only, and the
   FULL plan re-executes per attempt — plans are rebuilt, never partially
   applied. Unbounded retries turn throttling into a Lambda timeout.

5. **Preflight cap.** Plans are capped at 90 items, leaving headroom under
   DynamoDB's 100-item service limit for ConditionCheck entries the
   planner adds. A plan at the service limit fails opaquely at runtime;
   the cap fails it legibly at build time.

6. **Client-side duplicate-key rejection.** A plan addressing one table
   key twice is rejected before the call (DynamoDB surfaces it only
   opaquely through cancellation reasons).

7. **Marker TTL.** Markers expire seven days after commit via the shared
   numeric-epoch `expiresAtEpoch` TTL attribute on the aggregate tables
   (impact map 4.1). Do not confuse with UnitInvite TTL semantics — same
   attribute, different writers.

8. **Cancellation classification.** `TransactionCancelledError` carries
   the failed plan indexes (from CancellationReasons) so handlers map to
   domain errors (CONFLICT/NOT_FOUND/...) without re-reading the world.

## Probes (per wave, per the plan's acceptance rows)

- committed-replay pin: schema-derived mutation set, result-equality
  replay (the 53-mutation pin gets its test-infra home with the first
  handler wave);
- corruption-direction probes: every repair gets a probe for the
  corruption direction it could introduce, not only the claimed pin;
- race probes: concurrent same-key submissions, one winner, replay-equality
  for the loser;
- throttle probes: attempt-11 fixed-window behavior via
  `public_order_throttles` (map 4.4) for redemption paths.
