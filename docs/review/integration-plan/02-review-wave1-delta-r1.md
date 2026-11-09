# Independent Review — wave-1 delta, PR 922 (review-r1)

- **Reviewer:** review.r1 (independent; no authorship)
- **Target:** kw-ss-integration @ 9bbf96b5 (db96ce8..9bbf96b) vs
  origin/main, plan revision b628f17
- **Method:** adversarial read of the delta against the kernelworx tree
  (clean room closed); scoped per dispatch to the six wave-1 items; their
  gates run locally in a detached worktree (now removed).

## Verdict: APPROVE on all six items. Their gates are genuinely met, not
## asserted.

### 1. Error-vocabulary decision record — APPROVE
`docs/investigations/show-sell-error-vocabulary.md` lands exactly what
r1-1 demanded, with better guardrails than asked: **D-1** adds
`RATE_LIMIT_EXCEEDED` as a new code with the throttle-vs-lifetime-cap
semantics table (retry-after-window vs never-retry, counter scope,
storage) and a `retryAfterHint` authorized detail — the design decision
r1 said was missing, made correctly. **D-2** is per-path suppression
(profile invites keep their codes; the Unit-invite path answers NOT_FOUND
for every non-success outcome per §5.3) — including the explicit
"do not tidy this duplication later" guard against re-opening the
existence oracle. **D-3** is the authorized-details contract table with
the rules (reasons are contract, messages may change, new reasons land in
the same commit). The `errors.py` diff matches: the new code commented
with its semantics, the legacy codes marked as must-not-surface.

### 2. ADR records + acceptance probes — APPROVE
`docs/investigations/show-sell-idempotency-convention.md` ports the
convention as five numbered rules (deterministic-validation-first with
the replay-class rationale; marker+effect in ONE transaction;
committed-replay equality; F1 bounded race retries with full-plan
rebuild; 90-item preflight) and states the acceptance mechanism verbatim:
"Re-expression silently reverts them; per-wave probes check them." The
tick-traceability owner row and the two-backend suite home are named in
§5.4. This is the anti-silent-reversion home r1-2 asked for.

### 3. One show-and-sell domain role — APPROVE
Recorded org decision (§2.4): ONE `show-and-sell` domain role owning the
five-table family plus explicit legacy-table statements, with the
deciding rationale — one `TransactWriteItems` executes under one role and
the transactions span 3–5 tables; `TransactWriteItems` appears in no
current policy (new grant everywhere); no Scan anywhere; capture tests
as the acceptance pin. The lambda env diff adds the five table names to
the handler environment; no fallback role.

### 4. AppSync write-hole reconciliation — APPROVE
Named in §2.4 and §5.5 (r2 N-5): the AppSync service role can
Put/Update/Delete ALL tables via field resolvers; wave 1 reconciles the
write surface — field resolvers limited to reads and legacy, new writes
go through Lambda under the domain role. Schema-side: 964 added SDL
lines, **zero** api-key directives (the single `aws_api_key` match in
the diff is the "no @aws_api_key" comment); Cognito-only inheritance is
correct for their API (Cognito default + API_KEY additional provider
used only by the self-checking public-order surface).

### 5. Short-lived-event time strategy — APPROVE
C-3 RULED (§2.6): clock-independent assertions are the CI default; a
guarded test-only clock is built ONLY if a scenario truly needs it,
env-flagged, under the D4 purity doctrine (dev/ephemeral only,
structural purity test, bounded offset). The right lesson from the
clean room — the clock was always a stand-in — codified as their
convention.

### 6. Custody-in-Lambda plan text — APPROVE
C-1 as architecture (§2.1/§3.3/risk 3): AppSync JS/VTL resolvers on
DynamoDB sources have no `TransactWriteItems`; a JS "port" would be
sequential single-writes on the top money/stock path — the partial-write
class the factory hardened against. Custody executes in Python Lambda;
oracles-first with the corrected 53-case pin. Wave 3 budget honestly
restated (function + role + wiring, not resolver-only).

## Their gates, run locally (detached worktree at the PR head)
- Full unit suite: **1931 passed, 3 skipped, 100.00% coverage** (their
  gate is whole-project per run; the wave-1 subset alone was 131/131).
- `ruff check`: clean. `mypy` on the new utils: clean.
- `tofu validate`: clean. `tofu fmt -check` flags
  `application/modules/iam/main.tf` — **pre-existing on main** (this PR
  does not touch the file; their CI does not enforce fmt). INFO for
  their hygiene backlog, not this PR.
- The complexity-gate split (`f7848981`, execute_transaction below their
  Xenon gate) and the two CI-only coverage-gap commits show the gates
  being honored from the inside, including the awkward parts.

## Disposition
Wave-1 delta APPROVED from my seat. The plan revision's §6 review trail
(r1 folded, r2 folded with ruled items recorded as org decisions) is the
right shape — the wave delivered what the revised plan promised, in
their conventions, with their gates green.
