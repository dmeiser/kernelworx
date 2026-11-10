# 8.10 feasibility preflight — interim exposure and the wave-6 hard precondition

Status: RECORDED (r2 W4-2 / r1, wave-4 fix commit; wave-6 START
PRECONDITION — not a wave-4 fix).

## The gap

Spec 8.10 bounds the per-event finalization plan so it stays inside
DynamoDB's transaction limits. The wave-4 signup/assign ports do NOT bind
that bound: a pathological event (20 slots × capacity 100) admits ~2000
signups, and the finalize plan would be irreducible — the finalization
transaction cannot execute.

## Interim exposure (accepted, named)

Until wave 6, events CAN be oversized: nothing at signup or assign time
enforces the feasibility bound. The exposure is bounded in practice by
Unit Admins creating modest events, but the invariant is unenforced — this
record is the standing acknowledgment, per the plan's stop-and-ask /
decision-record doctrine.

## The wave-6 landing (r2's shape — hard precondition for wave-6 start)

Plan-time feasibility checks, in the operations that GROW the plan:

- `assignShowAndSellInventory`: 4 + 3×products ≤ 90.
- `signupScoutForShowAndSellSlot`:
  4 + 3×products + 2×(confirmed + active + 1) ≤ 90.

(`products` = the event's distinct allocated products; `confirmed` =
signups with actualMinutes > 0; `active` = ACTIVE signups; the +1 is the
signup being attempted.)

Plus the named-remediation backstop at finalize: when the bound is
violated at finalize time anyway (e.g. an event grew under an older
build), finalize fails with a named CONFLICT whose detail names the
remediation (remove signups / split the event), never a bare
transaction-limit error.

## Signup-plan note for the wave-6 accounting

The wave-4 signup transaction also writes one SIGNUPWINDOW proof row per
30-minute bucket the slot touches (exact atomic overlap prevention,
DM-AC-14). The bucket count for realistic slots (≤ a few hours) is small,
but the wave-6 plan-time formula must count them — or bound slot
durations — so the 90-action preflight remains truthful.
