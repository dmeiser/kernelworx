# Slot-start quantization — named input constraint (r2 W4-1b ruling, option a)

Status: DECIDED + ENFORCED (wave-4 fix commit; cited to r2's W4-1b ruling;
reversible — the grid is a single named constant).

## The constraint

`upsertShowAndSellSlot` rejects `startAt` values off the 30-minute grid
(UTC) with `INVALID_INPUT` naming the constraint. Durations stay fully
arbitrary — 90/120/180-minute slots all remain legal; only the START is
quantized.

## Why (r2's rationale, adopted)

- The spec mandates arbitrary durations and event-bounded intervals, not
  arbitrary start times; every oracle in the smoke plan and FIX-AC is
  grid-aligned already.
- Adjacency becomes EXACT at aligned boundaries: back-to-back slots share
  no SIGNUPWINDOW bucket, so the atomic overlap proof has no false
  positives at the boundary.
- Bucket counts stay bounded for the wave-6 8.10 accounting.
- One validation line; the grid is one named constant
  (`WINDOW_BUCKET_SECONDS`) if finer granularity is ever needed.

## Interaction with the overlap machinery

The 1-minute-overlap and concurrent-overlap oracles live at the
SIGNUPWINDOW layer (fixed-grid buckets an interval touches): overlapping
intervals always share at least one bucket regardless of alignment, so the
atomic prevention stays exact for any interval the machinery ever sees
(e.g. legacy or cross-campaign rows); slot CREATION is where alignment is
required.

## Oracle set (pinned in tests)

- Aligned back-to-back slots: both signups succeed.
- Unaligned-quantized back-to-back (window layer): no shared bucket.
- 1-minute overlap (window layer): shared bucket -> blocked.
- Concurrent overlap: identical bucket sets -> blocked.
- Cross-campaign back-to-back (same profile): succeeds.
- Off-grid slot start: INVALID_INPUT naming the W4-1b constraint.
