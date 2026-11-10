# Independent Review — wave-5 delta, kw-ss-wave2 @ 6d45208a (review-r1)

- **Reviewer:** review.r1 (independent; no authorship)
- **Target:** 5be4be27..6d45208a (stacked on the reviewed wave-4 fix
  boundary)
- **Method:** scoped per dispatch; handlers, JS router, and reporting
  engine read in a detached worktree (removed after); their gates run at
  the head.

## Verdict: CHANGES on item 3 (a real §8.6.1 defect) AND on the coverage
## gate (99.74% at the head — their own 100% gate fails). APPROVE on items
## 1, 2, 4.

### 1. Payment methods + QR — APPROVE
Built-ins computed, never stored (`BUILTIN_CODES` + projections; 50-active
cap; reserved-name guard); the prefix contract `payment-qr-codes/units/
<unitId>/<paymentMethodId>/<filename>` on the EXISTING exports bucket;
inactive-blocked uploads (CONFLICT/ACTIVE_GUARD, an authorized D-3
reason). The request path's no-effect marker (pins the presigned response
for replay, nothing to commit) is documented inline — a reasoned
application of the convention, and correct for the retry semantics (a
same-key retry inside the 5-minute URL window gets the working URL).

### 2. Sales backend — APPROVE
Immediate-handoff arithmetic as conditioned per-product Updates (remaining
down, sold up); We Owe consumes NO allocation (the ADR comment is
explicit); corrections apply the NET immediate delta with `SALEREV#`
append-only prior-revision snapshots (history never rewritten); voids
return all immediate stock and cancel uncovered obligation remainders;
marker-race mappings present (pin grew by the wave's mutations).

### 3. We-Owe corrected-obligation retargeting — CHANGES (HIGH)
`_adjust_obligation` (sale_operations.py:1063) implements the
decrease half of §8.6.1 wrong:

```python
outstanding_target = max(target_we_owe - fulfilled, 0)
...
new_cancelled = original - outstanding_target
```

For a decrease on an obligation with fulfilled > 0, the cancelled
quantity over-counts by exactly `fulfilled`. Spec §8.6.1:
`target_remaining = correctedQty − fulfilled`;
`target_cancelled = original − fulfilled − target_remaining` ≡
`original − correctedQty`. Worked example (original 5, fulfilled 2,
correct to 3): the spec requires cancelled 2 / remaining 1; the code
writes **cancelled 4**, `remaining = max(5−2−4, 0) = 0` (the max-floor
masks it), status FULFILLED — the buyer's one remaining owed unit
vanishes, and the §5.15 invariant `original ≥ fulfilled + cancelled` is
violated (5 < 6) on the persisted row. The increase half is correct
(original extends; total matches the clean-room supplemental shape).

Second sub-defect on the same lines: a correction below the fulfilled
quantity silently clamps (`max(target − fulfilled, 0)`) instead of
rejecting — §8.6.1 requires the correction to FAIL for explicit Kernel
reconciliation ("only the unfulfilled portion may be voided/reduced";
"a correction that would overtake an already fulfilled quantity ... fails").

Coverage evidence: no test exercises decrease-with-fulfilled (the
correction tests all run at fulfilled 0). This is the W8-H1/W10-H3
equation class again — the port drifted on the exact branch the oracles
exist for. Fix: `new_cancelled = original - fulfilled - outstanding_target`
with an explicit `target_we_owe >= fulfilled` rejection, plus the
decrease-with-fulfilled oracle test.

### 4. Reporting engine — APPROVE
The loader realizes the architecture §5 contract with named error classes
(follow-every-page-or-fail-visibly, never silently truncate,
version-drift → refresh); the parity manifest implements absence-is-truth
as EXPLICIT ZERO ROWS per 8.2.4(a) (sellers/products the source does not
enumerate appear as zero rows, never omitted), with rules per row and
production-shaped fixtures. One-assembler-drives-all and the writer
sanitization live in `assembler.ts`/`writers.ts` with their own test
files.

## Gates — FAIL at the head
`pytest tests/unit`: 2322 passed, 3 skipped, but **coverage 99.74% —
their 100% gate fails**. The miss is localized: `sale_operations.py`
97.06% (10 statements + 11 partial branches: the naive-timestamp guard,
missing-allocation conflict, marker-race fallbacks, void guards,
kernel-insufficiency). The wave's part-2 coverage commit does not hold at
the head. Must be green before merge; several of the missed branches are
error surfaces that deserve the oracle treatment anyway.

## Disposition
Two closes: (a) the `_adjust_obligation` decrease formula + below-fulfilled
rejection + the decrease-with-fulfilled oracle; (b) the coverage gate back
to 100% with the missed error branches pinned. Items 1, 2, 4 are approved
as landed.
