# Independent Review — adapter wave (W16 AppSync/Cognito/Lambda) (review-r1)

- **Reviewer:** review.r1 (independent; no authorship)
- **Target:** 08cb16f..05babc1 on tip 05babc1 (tree clean), deploy run
  42502275891 green (authenticated AppSync via Cognito, SPA shell,
  3m deploy + 19s smoke).
- **Scope per dispatch:** the two root causes, merge determinism/CI
  pinning, dev-only auth surface, direct-Lambda wire contract.
- **Verification:** backend 600 passed / 6 skipped; merge + handler
  tests run directly; CI wiring read from ci.yml; the deploy evidence is
  the run record cited in-tree.

## Verdict: APPROVE — one MEDIUM recorded as a hard precondition of the
## full-resolver-map pass, one INFO. Both root causes are correctly
## diagnosed and durably fixed.

### Root cause 1 — get-schema-creation-status: correctly diagnosed
`get-graphql-api` has no schemaStatus field (verified by the run-42492121227
record dump); `get-schema-creation-status` is the only status surface and
carries `details` on failure. The apply loop polls it 90×10s, prints
status+detail every poll, dumps the full record on FAILED or timeout. ✓

### Root cause 2 — extend-type fields dropped: correctly diagnosed, durably fixed
`merge_sdl.py` merges `extend type` blocks into base definitions via
graphql-core AST manipulation (deterministic: parse → merge → print_ast),
raises on orphan extensions, and is pinned by `test_merge_sdl.py` (no
extensions remain; `listMyProfiles`/`createSellerProfile` land in the base
types). CI runs it (ci.yml `python -m pytest -q`). The deploy applies
**`merge_sdl.py` default output — the production schema only**:
`graphql/dev_schema.graphql` (the test clock) is never composed, so the
dev surface cannot ride into AppSync. `triggers_replace` =
sha256(schema) + sha256(merge_sdl.py) + "merge-ext-v2", so drift in either
file re-applies — the exact lesson of run 42494938462 baked into the
trigger set. ✓

### Dev-only auth surface — contained
`ALLOW_USER_PASSWORD_AUTH` + the persona-password trigger live in the
dev deploy (workflow `deploy-dev.yml`, dev OIDC role, sensitive
`persona_password` var with per-run derivation `${run_id}-ShowSell-dev!`
or a secret override; runbook documents the dev boundary and the separate
prod role). No production terraform exists to leak into. INFO: the app
client's `explicit_auth_flows` would inherit to a future prod client —
add a runbook line when the prod stack appears.

### Direct-Lambda wire contract — half verified, half deferred with a
### hard precondition
- **Field value, not envelope — verified.** The handler unwraps
  `(result.data or {}).get(field)` (root cause documented from run
  42499565655: the envelope made AppSync see items=null); the response
  template emits `$util.toJson($ctx.result.data)`; unit-pinned
  (`test_direct_shape_returns_field_value_not_envelope`).
- **Handler errors to util.error — diverges from the §3.3 contract
  (MEDIUM, deferred-by-design, precondition recorded).** The template's
  `$util.error($ctx.result.error[0], "Handler")` sets message +
  errorType "Handler", but AppSync VTL's `$util.error` cannot carry
  arbitrary extensions — so `extensions.errorCode` is lost and the
  frontend `ApiError` (and every error-driven flow: stale-version
  dialogs, duplicate-confirm, throttle copy) collapses to
  INTERNAL_ERROR on the adapter. Unreachable in v1 (the two wired fields
  are non-erroring queries), so the smoke is genuinely green; it bites
  the moment the next pass wires mutations — which the wave's own
  resolvers.tf scopes as the follow-on. **Precondition: the
  full-resolver-map pass ships with the code preserved** — e.g. the
  handler returns the AppError code and the template calls
  `$util.error(message, code)` (errorType carries the code; bridge to
  `extensions.errorCode` in the client or a documented adapter mapping),
  pinned by a handler+template test per error class.

## Suites
backend 600 passed / 6 skipped (merge + Lambda handler tests included);
tofu fmt-check + validate and the report-guard job all run in ci.yml.
