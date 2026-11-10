# Wave-5 Architecture Lens — sales/We-Owe + browser-only reporting (review-r2)

- **Reviewer:** review.r2
- **Target:** kw-ss-wave2 @ 6d45208a (wave 5: 9a39c810 payment methods/QR,
  e8e299f8 sales+We-Owe, f37ffe8a coverage, 6d45208a reporting engine)
- **Method:** full read of the sale/obligation transaction planners in
  `src/handlers/sale_operations.py` (1687 lines), the reporting engine
  (`frontend/src/lib/reporting/` — loader, assembler, writers, validator,
  parity), the schema surface, and the wave-5 tests.
- **Suites:** 54/54 Python (sale ops, sweep, payment methods) + 54/54 TS
  (the five reporting modules) — all real runs.

## Verdict: CHANGES — one item (the parity gate has no caller);
## everything else in the lens CONFIRMED.

---

## Confirmed

### Sale/obligation transaction shapes

1. **Single conditioned allocation Update per product; no read-modify-write
   chains.** `_alloc_net_entry` (:484) is ONE Update per product applying
   the NET immediate delta with server-side `ADD remainingQty :rm,
   soldQty :sd`, triple-conditioned (`attribute_exists AND version = :v
   AND remainingQty >= :draw`). The pre-plan read feeds only the friendly
   message and the version condition; the draw's hard guard is the
   condition inside the transaction — a concurrent correction or assign
   cancels with `remainingQty`/`version` rather than lost-updating.
   Create-time draws (:597) use the same entry. Corrections are
   net-delta-as-absolute-target (W10/INFO-1 doctrine carried).
2. **Corrections: pre-read friendly guards only.** `_plan_immediate_delta`
   (:800) reads the allocation to name INSUFFICIENT_STOCK before the
   transaction; nothing depends on the pre-read's freshness.
3. **Prior-revision snapshots append-only, in the same transaction.**
   `_correct_sale` builds the plan as [snapshot Put (`SALEREV#<id>#
   <revision>`, attribute_not_exists) → merged sale Update (conditioned
   on expectedRevision) → event bump → line/obligation entries → marker]:
   history is written before the row it snapshots, atomically; the
   response's `priorRevisions` is assembled from stored snapshot rows.
4. Reservations (`_set_reservation`) and We-Owe fulfill
   (`_fulfill_we_owe`) follow the same plan-then-one-execute discipline;
   all mutation paths funnel through `execute_transaction`.

### Browser-only reporting integrity

5. **No server report path exists — grep and structural.** The schema's
   entire server-report surface is the ONE legacy `getUnitReport` query
   (their legacy app never had `requestCampaignReport` — synchronous
   oracle only); the wave-5 schema diff adds zero report fields; no
   csv/xlsx/presign/report-url fields exist anywhere. The wave-5 engine
   is frontend-only (`frontend/src/lib/reporting/`).
6. **The loader cannot return an authoritative partial dataset.**
   `loader.ts` has ZERO catch blocks: every failure mode is a typed
   throw — `IncompletePageError` (page without an items array),
   `VersionDriftError` (source version changes mid-assembly),
   `ReportTooLargeError` (page ceiling, default 200), `LoadCancelledError`.
   Pagination follows every `nextToken` to null (`runPages`); a failed or
   forbidden page fails the whole report by construction — there is no
   code path that returns rows without completing all pages.
7. **Object-URL-only downloads.** `writers.ts` builds a Blob +
   `URL.createObjectURL` + anchor download + `revokeObjectURL` — no
   network call exists in the write path ("No server report URL exists
   anywhere in this flow" holds by inspection).

## CHANGES

### W5-1: the parity manifest is executable but nothing GATES on it
### (MEDIUM)

`parity.ts` implements the manifest honestly: `LEGACY_PARITY_MANIFEST`
(declared rules incl. the cents↔dollars conversion boundary and the
absence-is-truth rule 8.2.4(a) as explicit zero rows), `centsToLegacyDollars`,
`matchesLegacyDollars`, `absentSellerZeroRows`, and `reconcileAgainstLegacy`
returning `ReconciliationIssue[]` — all unit-tested (parity.test.ts,
54/54 across the reporting modules). But the reconciler's ONLY callers
are its own test: grep across `frontend/src/`, `scripts/`, and `.github/`
finds no gating consumer, and the docstring says "The caller decides
whether to block retirement on any non-empty result" — **there is no
caller**. The lens claim "reconciliation violations actually gate
retirement" is not yet true: `getUnitReport` could be removed (plan
step 7) with no executable check standing in the way — the gate would
be a human promise, exactly the "habits, not records" class the plan's
own revision-1 doctrine was written to prevent.

Fix (small, do it before step 7 is anywhere near): a
`scripts/reporting-parity-gate.mjs` (or vitest integration config) that
runs `reconcileAgainstLegacy` against production-shaped fixtures —
legacy oracle output vs assembled datasets — and exits non-zero on any
non-empty result; plus one CI assertion that any PR touching the
retirement block (`getUnitReport` removal) includes a passing gate run.
Then the manifest is not just executable but load-bearing.

## W5-1 closed — re-verification at 0d13e317 (r2 second pass)

**CONFIRMED.** The gate landed exactly as prescribed and verified by my own
runs:
- `scripts/reporting-parity-gate.mjs` runs `parity-gate.test.ts`
  (production-shaped fixtures through `reconcileAgainstLegacy`); any
  violation → non-zero exit with the retirement-blocking message. My run:
  `REPORTING PARITY GATE: PASS`.
- Non-vacuity: three named negative controls in the suite — drifted legacy
  total, engine seller missing against a non-zero legacy seller, per-seller
  count drift — each asserts detection; a detection regression flips a
  control to failing and the gate exits non-zero. The controls PASS,
  proving detection is live for every claimed class.
- CI: the gate is a required step on every PR (ci.yml:118-120, no
  continue-on-error) with the explicit retirement-block coupling
  (ci.yml:122-133): a diff removing getUnitReport surface names the gate as
  the MUST-pass precondition in the job summary.
- r1's wave-5 CHANGES-3 (§8.6.1 obligation-decrease doctrine) also landed
  (e4b76805). Suites: 67/67 Python (sale + sweep + payment methods),
  59/59 TS (reporting incl. the gate suite).

**Wave 5 complete: sale/obligation shapes, browser-only reporting
integrity, and the executable (now load-bearing) parity gate all closed
from review.r2.**

## Notes (non-blocking)

- The sale response's `priorRevisions` enumerates stored snapshots — the
  audit chain is read-derived, consistent with the append-only write.
- The payment-method/QR wave (part 1) reuses the conditioned transaction
  discipline; the QR presign flow stays on the existing exports-bucket
  prefix contract per plan §2.4.
- Wave-6 reminder (recorded): the §8.10 preflight is a START
  precondition for that wave per the standing decision record, and the
  SIGNUPWINDOW bucket Puts must be counted in its formula.
