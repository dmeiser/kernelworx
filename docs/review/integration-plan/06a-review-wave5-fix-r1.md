# Independent Re-Review — wave-5 fix, kw-ss-wave2 @ e4b76805 (review-r1)

- **Reviewer:** review.r1 (independent; no authorship)
- **Target:** 6d45208a..e4b76805 (CHANGES-3 fix; also carries r2 W5-1, the
  executable parity gate gating getUnitReport retirement)
- **Scope:** the two wave-5 CHANGES items.

## Verdict: APPROVE on both. Wave 5 closes from my seat.

### CHANGES-3 (the §8.6.1 obligation-decrease defect) — CLOSED
`_adjust_obligation` now implements the spec doctrine with the
reconciliation recorded in the comment (outstanding_target = corrected −
fulfilled; cancelled = original − corrected; remaining = corrected −
fulfilled; totals net to the corrected demand):

- **Below-fulfilled rejection first**: `target < fulfilled` → CONFLICT
  naming spec 8.6.1 ("only the unfulfilled portion may be reduced") with
  authorized details — the silent clamp is gone.
- **Decrease**: `new_cancelled = cancelled + (outstanding_current −
  outstanding_target)` — for original 5 / fulfilled 2 / correct to 3:
  cancelled 2, remaining 1, status OPEN, and the §5.15 invariant holds on
  the persisted row. Exactly the spec equations.
- **Increase**: extends original so totals net — unchanged from the
  approved wave-5 shape.
- **Oracles**: `test_r1_worked_example_original5_fulfilled2_correct_to3`
  (my review's worked example, with the invariant asserted on the row and
  the OPEN-not-FULFILLED status), `test_qa_worked_example_original5_
  fulfilled1_correct_to4` (QA's complement), and
  `test_below_fulfilled_correction_rejects_per_861`. Both worked examples
  from the reconciliation are executable pins, not prose.

### CHANGES-GATE (the 100% coverage gate) — CLOSED
`pytest tests/unit` at e4b76805: **2335 passed, 3 skipped, 100.00%
coverage** (lead's count said 2336 — one-test count drift, zero failures;
the gate is what matters). ruff + mypy clean on the touched module. The
previously missed error branches (naive-timestamp, missing-allocation,
marker-race fallbacks, void guards, kernel-insufficiency) are pinned —
the wrong-reason version-guard tests corrected per the fix commit.

## Note
The same head carries r2 W5-1 (the executable parity gate gating
`getUnitReport` retirement) — adjacent to my scope; r2's verification
owns it, as the wave-3/wave-4 pattern holds.

## Disposition
Wave 5 APPROVED from my seat. The wave closes on this verdict plus QA's.
Remaining per the plan: wave 6 (lifecycle integration), wave 7
(retirement after parity — now gated by r2's executable parity gate),
wave 8 (scale readiness).
