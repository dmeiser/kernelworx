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

### Lambda IAM role isolation for Cognito admin actions (#121)

Destructive Cognito actions (`AdminDeleteUser`, `AdminResetUserPassword`, `AdminLinkProviderForUser`, `ListUsers`) are isolated on a dedicated `aws_iam_role.lambda_admin_execution` role, assigned only to the `admin-operations`, `delete-account`, and `pre-signup` functions. When adding a new handler that needs these APIs, add its logical key to `local.admin_function_keys` or `local.admin_trigger_keys` in `tofu/application/modules/lambda/main.tf` so it receives the admin role. The shared Lambda execution role no longer grants any Cognito admin permissions.

### AppSync pipeline function deletion ordering (#198)

AWS rejects deleting an AppSync pipeline function that is still referenced by a resolver. The AWS provider does not always order resolver updates before function deletions, so deployments that remove functions from a pipeline can fail with `BadRequestException: Cannot delete a function which is currently used by a resolver`. The deploy paths use `scripts/appsync-ensure-resolver-order.sh` to detect planned function deletions and apply the affected resolver(s) first. When collapsing or removing functions from a pipeline, add the resolver target to the script invocations in `scripts/ephemeral-env.sh` and `.github/workflows/deploy-shared.yml`.

Tainting shared pipeline functions via `lifecycle { replace_triggered_by = ... }` hits the same ordering problem, because a shared function may be referenced by several resolvers at once. The current pilot taints only the `createOrder` resolver itself (via its pipeline JS code hash in `tofu/application/modules/appsync/resolver_code_hashes.tf` and `resolvers_mutations.tf`); do not add function-level taint for shared functions without also updating the resolver ordering targets.

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

### Edge security architecture: one distribution, one WAF (#165/#166)

One CloudFront distribution (`tofu/application/modules/cloudfront/`) serves everything for dev/prod; exactly one CLOUDFRONT-scope web ACL (`tofu/application/modules/waf/`) is attached via `web_acl_id`. There are deliberately no regional WAFs and no `aws_wafv2_web_acl_association` anywhere — do not add them.

- `/graphql` behavior → AppSync **default endpoint hostname** (`<api-id>.appsync-api.us-east-1.amazonaws.com`). The served TLS cert matches only this hostname; the custom-domain name (`api.<env>.kernelworx.app`) does not work as an origin name and its Route53 record was removed. Forwarded headers: `Authorization`, `Content-Type`, `Accept`; caching disabled.
- `/login`, `/logout`, `/oauth2/*`, `/.well-known/*`, `/favicon.ico` behaviors → Cognito custom domain `login.<env>.kernelworx.app` as a custom origin. The `login.<env>` Route53 record is load-bearing origin plumbing (CloudFront reaches Cognito's AWS-managed distribution with SNI/Host of that name) — never remove it. The `aws_cloudfront_function.auth_location_rewrite` viewer-response function rewrites absolute `Location: https://login.<env>.../...` redirects to the site origin; without it every login redirect bounces off the distribution.
- The frontend is same-origin: Apollo falls back to `/graphql` and Amplify's `oauth.domain` falls back to the site host when `VITE_APPSYNC_ENDPOINT`/`VITE_COGNITO_DOMAIN` are unset. Dev/prod builds leave both unset; ephemeral and local `vite dev` set absolute values (ephemeral has no CloudFront).
- Ephemeral instantiates the waf module with `create = false` (the count-equals-zero opt-out): zero WAF objects, zero cost. Keep that pattern when adding edge resources.
- #269: the per-IP rate rule (2000 req/300s) is scoped down with a not-statement over the GitHub Actions IP set built at deploy time from `api.github.com/meta` — CI ranges skip only the rate rule, not the managed rules, and there is deliberately no terminal allow rule. The deploy fails loudly if the feed lacks the `actions` key or the (IPv4-only) list exceeds the 10000-entry WAF IP-set cap; the list ages between deploys, so drifted ranges mean intermittent CI smoke failures until the next deploy. Contract tests: `tests/unit/test_edge_security.py`.
- #166 ships via `aws_cloudfront_response_headers_policy.security` on the default behavior (CSP incl. `frame-ancestors 'none'`, XFO DENY, nosniff, Referrer-Policy, HSTS max-age=300). The frontend `<meta>` CSP stays until a later tightening phase.
- The GitHub deploy role (`arn:aws:iam::750620721302:role/GitHubActionsKernelworxDev`, managed outside this repo) needs `wafv2:*` and CloudFront function permissions for deploys to succeed.
