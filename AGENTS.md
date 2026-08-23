# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.

## Ephemeral PR environments

Ephemeral per-PR stacks live in `tofu/application/environments/ephemeral` and are managed by `scripts/ephemeral-env.sh`. The workflow is `.github/workflows/ephemeral-test.yml`.

- `scripts/ephemeral-env.sh up <run-id>` creates/updates a stack; `down <run-id>` destroys it. State is stored in S3 under `s3://kernelworx-tofu-state-us-east-1-dev/application/ephemeral/<run-id>/terraform.tfstate`.
- The script detects and removes stale S3 `.tflock` objects left by crashed or cancelled CI runners (different hostname = always stale; same hostname = stale after `EPHEMERAL_LOCK_STALE_SECONDS`, default 600).
- If `down` finds the state object missing but a previous S3 version exists, it restores the latest version before destroying so resources are tracked.

### Recovery workflows

The same workflow file exposes three `workflow_dispatch` jobs for manual intervention:

- **Manual teardown for PR** (`mode: down`): runs `scripts/ephemeral-env.sh down pr-<n>` for an arbitrary PR number. Use this when a PR's merge teardown fails or when you need to clean up a leaked environment safely through Terraform.
- **Recover deploy for PR** (`mode: recover-deploy`): runs `scripts/recover-deploy.sh pr-<n>`. It discovers existing AWS resources for the run-id and imports them into state with individual `tofu import` commands (each allowed to fail). Use this when a PR test fails to apply because resources already exist from a previous partial run.
- **Recover destroy for PR** (`mode: recover-destroy`): runs `scripts/recover-destroy.sh pr-<n>`. It imports whatever resources still exist, then runs `tofu destroy` and cleans up leftover state/log groups. Use this when state is missing/corrupt but AWS resources remain.

Recovery scripts share helpers in `scripts/ephemeral-recover-common.sh`.

### Lambda log-group `for_each` gotcha

`aws_cloudwatch_log_group` resources for Lambda functions must use static `for_each` keys (e.g. `local.functions`) rather than `aws_lambda_function.*`. Basing keys on computed attributes such as `function_name` makes them unknown during planning, which breaks import-based recovery and can break fresh applies. See commit `f5b4e0e` and `tofu/application/modules/lambda/main.tf`.
