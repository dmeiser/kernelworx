# Wave-4 Architecture Lens — events/slots/signups/allocation (review-r2)

- **Reviewer:** review.r2 (fresh-eyes architecture pass; no authorship in the
  integration)
- **Target:** kw-ss-wave2 @ 26bf06c0 (wave 4: 642dbb4e + ruff drift
  26bf06c0). Full read of `src/handlers/event_operations.py` (1739 lines),
  `src/utils/allocation.py` (180), the participant-read layer
  (`src/handlers/participant_data.py`), the wave-4 tests (25 event tests +
  54 coverage-sweep tests + the terraform drift guard), and the IAM role.
- **Suites:** 87/87 across the wave-4 files (all real runs).

## Verdict: CHANGES — two items; everything else in the lens CONFIRMED

The allocation architecture is exactly what the survey promised: pure
planner/evaluator, a hard transaction boundary at assign, capacity as a
conditioned counter, and GSI read paths guarded structurally. The signup
path, however, is not the six-write sequence contract the checklist (3.4.1)
and this lens require — commitments were re-expressed as a *derived read
projection* and three write-time invariants were lost with them — and the
§8.10 feasibility preflight does not bind anywhere, which matters now that
wave 4 lets events accumulate unbounded signup volume.

---

## Confirmed

1. **Planner and interval evaluator are pure; the transaction boundary is at
   assign.** `src/utils/allocation.py` is I/O-free (dataclasses + functions:
   `plan_targets` TARGET-not-delta, `validate_plan_line` sold-stock
   protection, `max_concurrent_assigned`/`_peak_at` boundary-exact peak,
   `evaluate_assignment` warning/block shapes). `_assign_show_and_sell_inventory`
   (:799) reads first (existing allocation rows :823, balances :838), plans
   pure, builds entries via `_allocation_entries`, appends the conditioned
   event update + marker, and executes ONCE (:890). No read lives inside the
   plan builder — it consumes the pre-read structures, so plans cannot go
   stale mid-build. Cancellation races map to named CONFLICTs.
2. **Capacity is a conditioned counter — no check-then-act.** The signup
   plan's slot update is `ADD activeSignupCount :one` with
   `ConditionExpression: activeSignupCount < :capacity AND version = :sv`
   (:1229-1238): capacity and slot version are enforced INSIDE the
   transaction; a concurrent pair of signups cannot over-fill. The 20-slot
   cap is enforced at create with the same no-check-then-act discipline
   (:1031). The signup-row Put is `attribute_not_exists OR #status =
   :cancelled` — tombstone re-signup rides the same condition.
3. **GSI read paths: legal shapes, structurally guarded.** Every index
   query audited is hash-equality against its index's declared key
   (`saleId-index`: `saleId = :sid` :264; `campaignId-index`: `campaignId =
   :cid` :1244; `unitCampaignId-startAt-index`: `unitCampaignId` :1612);
   every `begins_with` sits on a base-table RANGE key (`unitCampaignId` hash
   + `itemKey` prefix) — never on a partition key. The defect history this
   guards against is the app's own #576/#586 (HASH-only index +
   `begins_with` on the partition key — rejected by DynamoDB), whose fix is
   structural: a composite `emailSearchKey` HASH + `email` RANGE index plus
   regression tests that drive the REAL handler against moto so every
   emitted key condition is expression-validated, not mock-asserted
   (`test_admin_search_email_index.py`). Wave-4's tests inherit that
   structural guard by running the real handlers on moto (moto validates
   Query key conditions), and `test_show_sell_table_terraform_drift` pins
   terraform ↔ accessor hash/range keys for all five new tables. Wrong-hash
   and illegal-prefix regressions fail at test time, not in production.
4. **9.1 state machine.** Status derived from interval+clock with CANCELLED
   stored (`_derive_status` :249); times immutable by input shape (no
   startAt/endAt on update); optimistic concurrency on every event write;
   slot delete cascades signup rows.

## CHANGES

### W4-1: the signup is not the six-write sequence contract — three pinned
### invariants lost with the stored commitments (HIGH)

The plan re-expressed Scout commitments as a **derived projection**
(`participant_data._commitment_items` resolves ACTIVE signup rows against
slot rows at read time). That is a legitimate simplification for READS —
single source of truth, no drift — but wave 4 dropped the write-time
machinery with it. `_signup_scout_for_slot` (:1277) writes signup + slot
counter + marker; against checklist 3.4.1 ("condition membership/guard/slot/
event versions and write signup + commitment + counters + marker… no
duplicate/global overlap") and the doctrine my stage-3 review pinned:

- **No duplicate/global overlap enforcement at all.** Nothing reads the
  Scout's existing signups or slots at write time: a Scout can sign up for
  two OVERLAPPING slots — same event or cross-campaign — and both commit
  cleanly (same-slot duplicates are blocked by the row key; overlapping
  different slots are not). SIGN-M-01's "no duplicate/global overlap" is
  unmet.
- **The membership removal race (DM-AC-19) is back.** `_require_active_membership`
  (:1262) is a pre-transaction READ; the transaction conditions only the
  signup row and the slot counter. An admin removing the Scout concurrent
  with a signup commits the signup for a no-longer-member Scout — the exact
  race our clean room pinned and fixed by conditioning the membership row's
  `version + ACTIVE` INSIDE the transaction.
- **No event version bump** on signup (minor under this schema, but named in
  the contract).

Fix shape (does not require reviving the full commitment partition): add
two entries to the existing signup transaction — (a) a conditioned
membership Update (`version + status=ACTIVE`, cancels on removal), and (b)
atomic overlap prevention via a derived-proof key written in the same
transaction (e.g. `SIGNUPWINDOW#<profile>#<interval-start>` with
`attribute_not_exists`, established by a pre-read covering the Scout's
ACTIVE signups' slot intervals — friendly message on conflict, the key
condition is the hard guarantee). Reinstatement tests exist verbatim in the
clean room (`TestSignupsAndWork` SIGN-M-01 suite, DM-AC-14/19).

### W4-2: the §8.10 finalization-feasibility preflight does not bind
### (MEDIUM — the wave-6 cap residual, now urgent)

Wave 4 has no numeric feasibility preflight: "feasibility" is the ACTIVE-
membership read, and the volume counters are 20 slots × capacity ≤ 100 —
an event can accumulate **2,000 active signups**, a state no finalization
write set can ever close (2-3 actions per confirmed participant + 3 per
product against the 90 budget), with no counterforce anywhere in wave 4.
Per §8.10 an event must never be allowed to REACH an irreducible state, so
the binding must exist at signup/assign plan time — the clean-room shape
(`4 + 3×products + 2×(confirmed + active + 1) ≤ 90`, checked per mutation)
is the reference. This must land at the START of wave 6 (before finalize
ships), and — because wave-4 events can already be oversized — finalize
needs a one-time backstop check with a named remediation path (admins
cancel signups / zero unconfirm). Naming it "wave 6" is fine; leaving it
implicit is how an event gets stranded in production.

## Notes (non-blocking)

- The cancel-signup path (`_cancel_show_and_sell_signup`) correctly restores
  the conditioned counter (`ADD -1` under version) and tombstones the row
  for re-signup — the derived-commitment read stays consistent through the
  lifecycle.
- The replay pin's schema-derived coverage means the 9 new mutations + 7
  queries are pinned for committed-replay at handler level; the seam layer
  for these fields rides the established wiring tests.
