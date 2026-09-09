# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.

## Ephemeral PR environments

Ephemeral per-PR stacks live in `tofu/application/environments/ephemeral` and are managed by `scripts/ephemeral-env.sh`. The `.github/workflows/ephemeral-test.yml` workflow has two jobs: `ephemeral-test` deploys the stack for same-repo pull requests only (it needs a PR number to form the run-id), and `sweep` runs on the nightly schedule to tear down leaked `pr-*` stacks; both jobs use the `ephemeral` environment so they can assume the AWS role.

- `scripts/ephemeral-env.sh up <run-id>` creates/updates a stack; `down <run-id>` destroys it. State is stored in S3 under `s3://kernelworx-tofu-state-us-east-1-dev/application/ephemeral/<run-id>/terraform.tfstate`.
- `scripts/ephemeral-env.sh` detects and removes stale S3 `.tflock` objects left by crashed or cancelled CI runners. A lock is removed only when it is older than `EPHEMERAL_LOCK_STALE_SECONDS` (default 600). Hostname is logged for diagnostics but is not a deletion signal: a different hostname may still belong to an active CI runner holding a fresh lock.
- If the current state object is missing but a previous S3 version exists, `ephemeral-env.sh down`, `recover-deploy.sh`, and `recover-destroy.sh` restore the latest version before proceeding, so resources are tracked.
- `ephemeral-env.sh down` and `recover-destroy.sh` automatically empty ephemeral S3 buckets (purging all object versions and delete markers) prior to `tofu destroy` to prevent `BucketNotEmpty` errors.
- Recovery imports in `scripts/ephemeral-recover-common.sh` continue on error across all resources and are dynamically verified against all declared OpenTofu modules in `tests/unit/test_ephemeral_reliability.py`.

### Recovery workflows

Manual intervention runs through two standalone `workflow_dispatch` workflows:

- **Manual teardown for PR** (`.github/workflows/manual-teardown.yml`, `pr_number` input): runs `scripts/ephemeral-env.sh down pr-<n>` for an arbitrary PR number. Use this when a PR's merge teardown fails or when you need to clean up a leaked environment safely through Terraform.
- **Recover deploy for PR** (`.github/workflows/recover-environment.yml`, `pr_number` and `mode: recover-deploy` inputs): runs `scripts/recover-deploy.sh pr-<n>`. It restores the latest S3 state version if the current object is missing, then discovers existing AWS resources for the run-id and imports them into state with individual `tofu import` commands (each allowed to fail). Use this when a PR test fails to apply because resources already exist from a previous partial run.
- **Recover destroy for PR** (`.github/workflows/recover-environment.yml`, `pr_number` and `mode: recover-destroy` inputs): runs `scripts/recover-destroy.sh pr-<n>`. It restores the latest S3 state version if the current object is missing, then imports whatever resources still exist, then runs `tofu destroy` and cleans up leftover state/log groups. Use this when state is missing/corrupt but AWS resources remain.

Recovery scripts share helpers in `scripts/ephemeral-recover-common.sh`.

### Lambda log-group `for_each` gotcha

`aws_cloudwatch_log_group` resources for Lambda functions must use static `for_each` keys (e.g. `local.functions`) rather than `aws_lambda_function.*`. Basing keys on computed attributes such as `function_name` makes them unknown during planning, which breaks import-based recovery and can break fresh applies. See commit `f5b4e0e` and `tofu/application/modules/lambda/main.tf`.

### Per-domain Lambda execution roles — #326 IAM role split (#351+)

Chunk 1 (#351) established the pattern the remaining chunks (#352–#354) reuse; the final chunk #355 narrows/removes the monolithic role:

- Each domain role lives in `tofu/application/modules/iam/main.tf` next to `lambda_execution`, named `${var.name_prefix}-lambda-<domain>-exec${local.role_suffix}`, with its own scoped inline DynamoDB policy. Scope must be verified against the actual handler source **including shared helpers** (`src/utils/auth.py` touches profiles/shares via every access check; `utils.dynamodb.tables` helpers may add tables). Note boto3 resource-style `batch_writer` issues `BatchWriteItem`, which cannot be restricted to delete-only at the IAM action level — scope it to the one table instead.
- The lambda module's reusable wiring is the `lambda_domain_role_arns` map variable (function key -> role ARN) consumed by `local.app_role_arn` in `tofu/application/modules/lambda/main.tf`. Precedence: admin role (#121) > domain role > shared role. Each follow-up chunk adds one iam-module output and entries in the `lambda_domain_role_arns` map in all three environments (`dev`, `prod`, `ephemeral`). The campaign role's entry maps the function keys `delete-campaign-orders` and `unit-reporting` (keys are kebab-case; they do not match the python module names).
- Any new IAM resource must also get an import line in `scripts/ephemeral-recover-common.sh` — `tests/unit/test_ephemeral_reliability.py::test_dynamic_resource_import_coverage` parses every resource out of the iam module and fails if recovery lacks a matching `import_resource`.

### Lambda IAM role isolation for Cognito admin actions (#121)

Destructive Cognito actions (`AdminDeleteUser`, `AdminResetUserPassword`, `AdminLinkProviderForUser`, `ListUsers`) are isolated on a dedicated `aws_iam_role.lambda_admin_execution` role, assigned only to the `admin-operations`, `delete-account`, and `pre-signup` functions. When adding a new handler that needs these APIs, add its logical key to `local.admin_function_keys` or `local.admin_trigger_keys` in `tofu/application/modules/lambda/main.tf` so it receives the admin role. The shared Lambda execution role no longer grants any Cognito admin permissions.

### AppSync pipeline function/datasource deletion ordering (#198, #298–#301)

AWS rejects deleting an AppSync pipeline function that is still referenced by a resolver, and also rejects deleting a data source while any resolver or function still references it. The AWS provider does not always order these updates before deletions. The deploy paths use `scripts/appsync-ensure-resolver-order.sh` to detect planned **function or datasource** deletions and apply the affected resolver(s)/function(s) first. When collapsing or removing functions from a pipeline, **or when migrating a resolver from a Lambda datasource to a direct/DynamoDB datasource** (which removes the old Lambda datasource), add the affected resolver/function target to the script invocations in `scripts/ephemeral-env.sh` and `.github/workflows/deploy-shared.yml`.

Tainting shared pipeline functions via `lifecycle { replace_triggered_by = ... }` hits the same ordering problem, because a shared function may be referenced by several resolvers at once. The current pilot taints only the `createOrder` resolver itself (via its pipeline JS code hash in `tofu/application/modules/appsync/resolver_code_hashes.tf` and `resolvers_mutations.tf`); do not add function-level taint for shared functions without also updating the resolver ordering targets.

The `deletePaymentMethod` pipeline (`get_payment_method_for_delete` → `delete_payment_method_qr_code` → `delete_payment_method_from_prefs`) invokes the `delete-qr-code` Lambda via `delete_payment_method_qr_code_fn.js` to purge the QR S3 object. That function must stay ordered BEFORE `delete_payment_method_from_prefs`: the Lambda re-reads preferences and verifies the method still exists, and it is best-effort (swallows `ctx.error`, logs via `console.error`) so a QR purge failure never blocks the method deletion.

### AppSync resolver bundling prerequisite (#277/#282/#288)

`tofu/application/modules/appsync` reads resolver code from `tofu/application/appsync/dist/` (gitignored), not from `js-resolvers/` (the source that tests run against). `dist/` is produced by `npm run build:resolvers` (esbuild bundles `js-resolvers/*.js`, inlining `lib/`, keeping `@aws-appsync/utils` external). Root `package.json` pins `esbuild` to an exact version (#282) to prevent output differences across environments from triggering spurious `resolver_code_hashes.tf` taints (`tests/unit/check_esbuild_pinning.test.ts`). `scripts/build-resolvers.mjs` resolves `srcDir`/`outDir` relative to the script (not cwd), validates the source dir before wiping `dist/`, and fails with an explicit "run `npm ci`" message when esbuild is absent (#281), so direct local invocation from any directory is safe. Every `tofu plan`, `apply`, `import`, or `destroy` fails with `Invalid function argument` from `file()` when `dist/` is missing, so run the build first for local tofu commands; `deploy.sh` (including on `init`, #288), `scripts/ephemeral-env.sh` (both `up` and `down`), and the recover scripts do it automatically, and CI workflows run a root `npm ci` before any tofu step. A stale `dist/` silently desyncs `resolver_code_hashes.tf`, so re-run the build after editing resolver sources.


### AppSync resolver-only authorization posture (#71)

KernelWorx uses Amazon Cognito User Pools for AppSync authentication and `default_action = "ALLOW"` on the user pool config. AppSync therefore admits any authenticated Cognito user to every field by default; schema-level directives do not enforce ownership or share-based access control.

The schema currently uses `@aws_cognito_user_pools` only to require Cognito authentication on selected types and fields (for example `Catalog`, `Product`, and a few queries). It does not perform owner, share, or admin authorization. All such authorization is implemented in resolvers:

- VTL/JS direct data-source resolvers in `tofu/application/appsync/js-resolvers/` and VTL mapping templates in `tofu/application/appsync/mapping-templates/`
- Lambda resolvers in `src/handlers/`

Consequences for new resolvers:

- Every new query, mutation, or field that returns sensitive data or performs a mutation must implement its own owner/share/admin check.
- There is no schema-level safety net; a resolver that omits its check exposes the field to all authenticated users.
- Do not rely on `@aws_cognito_user_pools` for authorization; use it only to require a Cognito-authenticated caller.

This is a conscious, documented security posture. If schema-level owner authorization is added later, update this entry and the API comment in `tofu/application/modules/appsync/api.tf` accordingly.

### Lambda exception-handling decorator (#294)

`src/utils/handlers.py` provides the `lambda_handler` decorator (imported in handler modules as `with_error_handling`): it re-raises `AppError` unchanged and converts any other unexpected `Exception` to `AppError(ErrorCode.INTERNAL_ERROR, ...)` after an error-level log naming the function. Use `@lambda_handler(error_message="...")` to preserve the handler's client-facing failure message. Only the generic unexpected-exception path is covered — handler-specific typed errors (e.g. retryable `RESOURCE_BUSY` in `_raise_batch_lookup_error`) must stay in the handler/helpers. Migration is incremental: `src/handlers/admin_operations.py` is the exemplar; `account_operations.py`, `campaign_operations.py`, and `profile_sharing.py` still carry the manual `except AppError: raise` / `except Exception` boilerplate and migrate in follow-up PRs. Overload stub lines in `src/utils/handlers.py` carry `pragma: no cover` (type-checking-only); the module must stay at 100% coverage.

### Edge security architecture: one distribution, one WAF (#165/#166)

One CloudFront distribution (`tofu/application/modules/cloudfront/`) serves everything for dev/prod; exactly one CLOUDFRONT-scope web ACL (`tofu/application/modules/waf/`) is attached via `web_acl_id`. There are deliberately no regional WAFs and no `aws_wafv2_web_acl_association` anywhere — do not add them.

- `/graphql` behavior → AppSync **default endpoint hostname** (`<api-id>.appsync-api.us-east-1.amazonaws.com`). The served TLS cert matches only this hostname; the custom-domain name (`api.<env>.kernelworx.app`) does not work as an origin name and its Route53 record was removed. Forwarded headers: `Authorization`, `Content-Type`, `Accept`; caching disabled.
- `/login`, `/logout`, `/oauth2/*`, `/.well-known/*`, `/favicon.ico` behaviors → Cognito custom domain `login.<env>.kernelworx.app` as a custom origin. The `login.<env>` Route53 record is load-bearing origin plumbing (CloudFront reaches Cognito's AWS-managed distribution with SNI/Host of that name) — never remove it. The `aws_cloudfront_function.auth_location_rewrite` viewer-response function rewrites absolute `Location: https://login.<env>.../...` redirects to the site origin; without it every login redirect bounces off the distribution.
- The frontend is same-origin: Apollo falls back to `/graphql` and Amplify's `oauth.domain` falls back to the site host when `VITE_APPSYNC_ENDPOINT`/`VITE_COGNITO_DOMAIN` are unset. Dev/prod builds leave both unset; ephemeral and local `vite dev` set absolute values (ephemeral has no CloudFront).
- Ephemeral instantiates the waf module with `create = false` (the count-equals-zero opt-out): zero WAF objects, zero cost. Keep that pattern when adding edge resources.
- #269: the per-IP rate rule (2000 req/300s) is scoped down with a not-statement over the GitHub Actions IP set built at deploy time from `api.github.com/meta` — CI ranges skip only the rate rule, not the managed rules, and there is deliberately no terminal allow rule. The deploy fails loudly if the feed lacks the `actions` key or the (IPv4-only) list exceeds the 10000-entry WAF IP-set cap; the list ages between deploys, so drifted ranges mean intermittent CI smoke failures until the next deploy. Contract tests: `tests/unit/test_edge_security.py`.
- #166 ships via `aws_cloudfront_response_headers_policy.security` on the default behavior (CSP incl. `frame-ancestors 'none'`, XFO DENY, nosniff, Referrer-Policy, HSTS max-age=300). The frontend `<meta>` CSP stays until a later tightening phase.
- The GitHub deploy role (`arn:aws:iam::750620721302:role/GitHubActionsKernelworxDev`, managed outside this repo) needs `wafv2:*` and CloudFront function permissions for deploys to succeed.
