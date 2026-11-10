# Independent Review — wave-4 delta, kw-ss-wave2 @ 26bf06c0 (review-r1)

- **Reviewer:** review.r1 (independent; no authorship)
- **Target:** 7213531f..26bf06c0 (stacked on the reviewed wave-3 boundary;
  includes the wave-3 C-1v fixes 902728e8 and the wave-2 GSI decision
  record)
- **Method:** scoped per dispatch; handlers, planner, router, and pins
  read in a detached worktree (removed after); their gates run at the
  head.

## Verdict: CHANGES on two in-scope defects; APPROVE on the other four
## scope items. Gates green: 2237 passed / 3 skipped at 100.00% coverage;
## ruff + mypy clean. The two defects are the kind the green suite cannot
## see: no test asserts what is missing.

### CHANGES-1 (HIGH) — cancel is event-row-only; the §8.8 cascade is absent
`_cancel_show_and_sell` (event_operations.py:551) builds
`plan = [event_update, marker]` and executes one transaction — the event
row becomes CANCELLED with audit fields, and nothing else. Spec §8.8
mandates ONE versioned workflow: in the SAME transaction, set every
allocation CANCELLED with `releasedQty += remaining`, cancel
signups/commitments, zero slot counters, and write release movements.
None of that happens. The tests pin only `test_cancel_marks_status` —
the status transition reads correct while the world stays wrong:
allocations remain OPEN and keep reserving stock in the §7 formulas and
the auto-reduce evaluator (a cancelled event's boxes stay "assigned"),
signups remain ACTIVE, slot counters stay nonzero. This is precisely the
partial-product shape the clean room's wave-6 review probed ("cancel §8.8
end-to-end: one transaction — event CANCELLED+audit, allocation released,
signup+commitment CANCELLED, slot counter zeroed, EVENT_RELEASE movement")
and the dispatch scoped ("cancel atomicity"). Fix: extend the cancel plan
with the allocation releases (conditioned, with EVENT_RELEASE movements),
signup cancellations, and slot zeroing — all version-conditioned, one
`execute_transaction` — and add the cascade assertions to the cancel
tests.

### CHANGES-2 (MEDIUM) — the signup plan misses the §8.3 membership
### condition; the removal race is open
`_signup_write_plan` conditions the signup row (absent-or-cancelled) and
the slot counter (`activeSignupCount < capacity AND version = slotVersion`
— the conditioned-capacity half is right), but does NOT condition the
membership row. `_require_active_membership` is a read-only pre-check; a
removal (`removeUnitCampaignMembership` writes the MEMBER# row in the
unit_campaigns table, which the signup transaction never touches)
committing between the read and the transaction leaves an ACTIVE signup on
a removed member. Spec §8.3 is explicit: "condition on membership.version
with membership.status = ACTIVE." The transaction already spans tables
elsewhere in the wave; adding one ConditionCheck on the MEMBER# row is
the fix, plus a removal-race test (the clean room's DM-AC-19 probe is the
oracle).

### APPROVE — 9.1 state machine exactness (derivation half)
`_derive_status` returns stored CANCELLED/FINALIZED/REOPENED and derives
SCHEDULED/ACTIVE/ENDED from the immutable interval (half-open, no
RESCHEDULED anywhere). Update rejects cancelled events; the allocation
write uses if_not_exists(createdAt) for audit preservation.

### APPROVE — allocation planner port
`src/utils/allocation.py` is the exact clean-room semantics: TARGETS never
deltas (omitted products unwritten, zero releases, sold-stock floor),
and `max_concurrent_assigned` evaluates at the target start + competitor
start boundaries with strict-inequality covering — hard-block at every
covered instant, sequential warn otherwise, with the 16.3A/16.3B
warning/block shapes. ADR 0003's per-campaign semantics are carried in
the module docstring.

### APPROVE — signup sequence contract (the halves that landed)
Caller-controlled campaign: the caller names campaignId, authorized via
share/WRITE on the campaign + campaign-profile match; the membership row
is keyed by profile — identity stays server-side, feasibility is the
membership check, exactly the recorded contract. Conditioned capacity as
above. Removal-race per CHANGES-2.

### APPROVE — marker-scope fix
`_marker_scope_key` separates flat (`args.idempotencyKey`) from
input-wrapped (`args.input.idempotencyKey`) keys with the rationale
recorded ("treating both as one namespace would replay unrelated requests
against each other — found by the wave-4 slot race probe"); per-mutation
scope namespaces throughout; the pin grew by the ten wave-4 mutations
with exact-set equality intact.

## Also verified
The wave-3 C-1v fixes (min-consumption per product at line 285, ADR-0002
custody rows, reversal restore, C-3v guards) and the wave-2 GSI decision
record land in this delta — r2's C-1 trial caught what my wave-3 pass
missed, and the loop closed both. The 2,132-line wave-4 coverage sweep
and the 885-line event test file show the gates honored from the inside —
which is why the two missing conditions matter: 100% coverage of what
exists says nothing about what §8.3/§8.8 require.

## Gates (run at the head)
`pytest tests/unit`: **2237 passed, 3 skipped, 100.00% coverage**. ruff +
mypy clean.

## Disposition
Two fixes close wave 4: the §8.8 cancel cascade (plan extension + cascade
tests) and the §8.3 membership ConditionCheck (one entry + a
removal-race test). Both are small against the 1,739-line handler. The
planner, derivation, signup authorization shape, and marker namespaces
are approved as landed.
