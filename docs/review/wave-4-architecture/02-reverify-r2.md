# Wave-4 Fix Re-verification — W4-1/W4-2 on the fixed head (review-r2)

- **Reviewer:** review.r2
- **Target:** kw-ss-wave2 @ 5be4be27 (fix 16c98e71 + coverage 5be4be27)
- **Method:** full read of the fixed signup/cancel paths, the window-bucket
  machinery, the 8.10 decision record; empirical bucket-math probes;
  suites 101/101 on the wave-4 files.

## Verdict: CHANGES — one item (W4-1's bucket guard false-blocks
## back-to-back slots); W4-2 CONFIRMED; the rest of W4-1 CONFIRMED.

---

## W4-1 (partially confirmed — one HIGH defect remains)

**Confirmed landed:**
- The signup is a six-write transaction again: signup row, conditioned
  slot counter, CONDITIONED MEMBERSHIP update (version + ACTIVE — the
  cancel mapping names the membership-condition race explicitly, DM-AC-19
  closed), event version bump, the SIGNUPWINDOW proof Puts, and the marker
  — one `execute_transaction` (the plan comment itself counts the order:
  "window_start = 4, after signup, slot, membership, event bump").
- Overlap prevention is EXACT and ATOMIC in the prevention direction: my
  probe of `_window_buckets` — overlapping intervals always share at least
  one fixed-grid bucket (1-minute overlap shares; cross-bucket overlaps
  share), one `attribute_not_exists` Put per touched bucket, so two
  concurrent overlapping signups cannot both commit (an upgrade over the
  clean room's friendly-check-only race). Cancel releases exactly the
  non-shared buckets (shared-bucket retention tested at sweep :2459 and
  :2802).
- The friendly pre-read (`_profile_active_intervals`) improves the error
  message; the atomic guard is the buckets, as designed.

**CHANGES — W4-1b (HIGH): the bucket math false-blocks back-to-back
slots.** The grid is 30 minutes; `_window_buckets` writes every bucket
the half-open interval touches. Two ADJACENT (non-overlapping) intervals
whose shared boundary is NOT grid-aligned touch the same bucket, and the
same Scout's second signup hard-cancels. Probe output (same profile):

```
slot A [10:20, 10:50) -> buckets [10:00, 10:30]
slot B [10:50, 11:20) -> buckets [10:30, 11:00]
SHARED: 10:30            <- false block (no overlap; half-open adjacency)
aligned adjacency [10:00,10:30)+[10:30,11:00) -> shared: none  <- allowed
```

Because wave-4 slots accept arbitrary start times (no grid validation in
`_resolve_slot_input`), unaligned adjacency is the COMMON case: a Scout
working two consecutive booth shifts — the entirely normal volunteer
pattern, and the exact scenario the SS-SM-06 doctrine pins as ALLOWED
(adjacency, strict inequalities; verified in my stage-3 review) — is
hard-blocked unless the shift boundary lands on a 30-minute grid line.
No adjacency oracle exists in the suite (grep: zero back-to-back/adjacency
tests), so this is green-tested while wrong.

The tension is real and needs a ruling, not a patch: a fixed-grid bucket
scheme cannot distinguish "adjacent inside one bucket" from "overlapping
inside one bucket" — exactness in BOTH directions requires key resolution
at the boundary itself. Candidate resolutions:
(a) Quantize slot STARTS to the bucket grid (or a finer grid, e.g. 5-min
    buckets with 5-min-aligned starts): adjacency at any aligned boundary
    is exact; overlap always shares a bucket; durations stay arbitrary;
    bucket count = ceil(duration/G)+1, which the wave-6 accounting must
    bound. Smallest product surface, one validation line.
(b) Finer grid (1-min) with a duration cap for atomic eligibility and a
    ruled fallback (friendly-check + named exposure) for over-cap slots —
    two-tier guarantee, more machinery.
(c) Keep 30-min buckets and re-adjacency to "different-day or grid-aligned
    only" — silently rewrites the SS-SM-06 contract; NOT recommended.
Regardless of the ruling: add the adjacency oracle (aligned AND unaligned
back-to-back signups succeed; 1-minute overlap fails; concurrent overlap
fails) — the test gap is how this shipped.

## W4-2 CONFIRMED

The decision record at `docs/investigations/show-sell-8.10-feasibility-preflight.md`
matches the prescribed shape exactly: the two plan-time formulas (`assign:
4 + 3×products ≤ 90`; `signup: 4 + 3×products + 2×(confirmed + active +
1) ≤ 90`), the wave-6 START-precondition registration, the named-
remediation backstop at finalize (named CONFLICT naming the remediation,
never a bare limit error), and — correctly — a note that the SIGNUPWINDOW
bucket Puts must be counted in the wave-6 formula (or slot durations
bounded). The interim exposure is named, not hidden.

## Suites

101/101 across the wave-4 files (event operations, coverage sweep,
terraform drift guard).

## W4-1b closed — re-verification at 079244ad (r2 third pass)

**CONFIRMED.** Option (a) landed exactly as ruled:
- Named input constraint: off-grid `startAt` → INVALID_INPUT naming the
  W4-1b ruling (event_operations.py:1066-1070), deterministic input
  validation before any marker (convention rule 1); durations stay
  arbitrary (endAt only validated after startAt); single grid constant
  (`WINDOW_BUCKET_SECONDS`) shared by `_is_grid_aligned` and
  `_window_buckets`.
- My exhaustive sweep (8 quantized starts × 5 durations × 8 starts × 4
  durations): **0 false blocks on adjacency, 0 missed real overlaps** —
  with quantized starts the bucket guard is exact in both directions.
- The adjacency oracle set is pinned exactly as specified
  (test_wave4_coverage_sweep.py:2912-2990): aligned and
  unaligned-quantized back-to-back succeed, 1-minute overlap fails at the
  window layer (shared bucket), concurrent overlap fails.
- Decision record cites the ruling (docs/investigations/
  show-sell-slot-start-quantization.md).
- Suites: 110/110 across the wave-4 files including the planner/slot
  tests with grid-aligned fixtures.

**Wave 4 complete: W4-1 (six-write signup + window proofs + quantization)
and W4-2 (8.10 decision record, wave-6 precondition) both closed.**

## Disposition

One ruling needed (W4-1b resolution a/b) + the adjacency oracle; then the
wave-4 fix is complete. W4-2's wave-6 precondition stands as recorded.
