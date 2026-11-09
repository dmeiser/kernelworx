# Independent Review — wave-2 delta, PR 923 (review-r1)

- **Reviewer:** review.r1 (independent; no authorship)
- **Target:** kw-ss-wave2 @ 79f804c3 vs base kw-ss-integration @ 9bbf96b5
  (the reviewed wave-1 boundary), plan revision b628f17
- **Method:** scoped per dispatch; handlers and wiring read in a detached
  worktree (removed after); their gates run at the PR head.

## Verdict: CHANGES on one item (a required decision record, not code);
## APPROVE on the other six. Gates green: 2045 passed / 3 skipped at
## 100.00% coverage; ruff + mypy clean.

### 1. Nineteen operations in their conventions — APPROVE
Dispatcher handlers with the wave-1 helpers (`execute_transaction`,
markers, `_check_marker` committed-replay), moto-backed tests in their
fixture style, strict validators, spec-cited docstrings. ruff/mypy clean.

### 2. Invite §5.3 suppression — APPROVE
Every non-success redemption outcome (expired / consumed / revoked /
unknown) raises NOT_FOUND with the §5.3 comment; zero `INVITE_EXPIRED` /
`INVITE_ALREADY_USED` anywhere in the handler; tests named for the
indistinguishability contract (revoked/expired). D-2's per-path
suppression is realized exactly as recorded.

### 3. Attempt-11 throttle — APPROVE on the boundary mechanics; CHANGES on
### the unrecorded spec deviation (documentation, not code)
Boundary exact: the pre-check (`existing >= 10`) rejects attempt 11 with
`RATE_LIMIT_EXCEEDED` + `retryAfterHint` WITHOUT incrementing; the record
path is a server-side atomic `ADD` (no read-modify-write race) with a
post-increment `> 10` belt for concurrent races; key contract per §6.6;
TTL on `expiresAt`. Consumption conditions on `status = ACTIVE AND
expiresAtEpoch > now` atomically; the already-granted path returns the
grant without consuming or burning an attempt.

**The deviation:** invite discovery reads through the `metadataKey`
GSI — eventually consistent. Spec §6.1 directs consistent base-table
reads for invite redemption. Their five-table layout (sanctioned by the
impact map, risk 4) stores invites as items under the unit partition, so
the GSI is the only code-lookup path; everything AFTER discovery
(grant check, consumption) is consistent and conditioned. The residual:
create → immediate-redeem sees NOT_FOUND **and burns a throttle attempt**
— ten spurious misses in one hour lock the account out. Narrow in human
flows (codes travel out-of-band) but real in automation, and the
consequence shape (a consistency lag feeding the throttle counter) is
exactly the kind of interaction the decision trail exists for. Per the
plan's own STOP-AND-ASK rule (anything beyond the six decided items must
be recorded), this needs a wave-2 decision-record paragraph: the §6.1
deviation acknowledged, why the layout forces it, the residual named,
and the monitoring stance. No code change required.

### 4. Join-time catalog identity — APPROVE
Enforced at join (campaign.catalogId must equal unit_campaign.catalogId,
clear conflict message), positioned before any order changes per impact
map 3.3.

### 5. Roster guard versioning — APPROVE
Dual independent versions: the roster read model exposes `guardVersion`
(with the comment explaining participation bumps the membership row only);
removal requires both `expectedMembershipVersion` and
`expectedGuardVersion`, loads with both, and conditions both in the
transaction (`guardVersion = :gv` ADD-guarded). No lockstep anywhere.

### 6. Domain role capture pin — APPROVE
Exactly r2 C-2: real handler flows under moto, botocore event-recorded
ACTUAL `TransactWriteItems` table sets, asserted against the IAM module's
allow-list parsed from terraform source — drift fails the test, not the
deploy. Expected set {units, unit_campaigns, campaigns} matches the
cross-table transactions.

### 7. Nineteen resolvers + depth recompute — APPROVE
Nineteen new `aws_appsync_resolver` blocks verified by count and name
(createUnit through unitCampaignCatalog); the depth/resolver-limit
comment carries the measured basis (existing depth-5 report, new depth-3
queries) and the issue-#328 alias-fan-out rationale per their convention.

## Gates (run at the PR head, detached worktree)
`pytest tests/unit`: **2045 passed, 3 skipped, 100.00% coverage**.
`ruff check` + `mypy` on the new handlers: clean. The wave-2 coverage
sweep (1,266 lines) and the IAM pin show the gates honored from the
inside.

## Disposition
One decision-record paragraph closes item 3 (§6.1 deviation, layout-forced,
residual named). Everything else is approved; wave 2 is otherwise
dispatch-complete.
