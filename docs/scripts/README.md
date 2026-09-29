# 📋 Operational and Utility Scripts

This document centralizes documentation for the repo's operational and utility scripts
found in `scripts/` and repo-root tooling. Each entry documents what the script does,
when to run it, and its key flags/arguments. All flag descriptions are verified against
the script's actual `--help` output or usage text.

---

## Scripts Reference

### Run identifiers (ephemeral runs)

The `<run-id>` argument accepted by `scripts/ephemeral-env.sh`,
`scripts/recover-deploy.sh`, `scripts/recover-destroy.sh`, and
`scripts/create-ephemeral-test-users.sh` is governed by this single contract —
those four per-script argument lists all point here rather than restating it:

- **Format** — must match `[A-Za-z0-9._-]+`.
- **Provenance** — the `pr-<number>` value derived from the `pull_request` /
  `workflow_dispatch` inputs (`pr_number`) of `ephemeral-test.yml`,
  `manual-teardown.yml`, and `recover-environment.yml`.
- **Enforcement** — `validate_run_id` in
  `scripts/ephemeral-recover-common.sh` is the single owner of the rule. All four
  shell entry points call it before any AWS call, so a traversal-shaped id such
  as `../prod` or `pr-1/x` fails instead of reaching another environment's S3
  state key (`application/ephemeral/<run-id>/terraform.tfstate`) or its
  `-var="environment=$RUN_ID"` value.
- **Python side** — `scripts/generate_integration_env.py` applies the identical
  regex to its `ephemeral/<run-id>` stack selector before it runs `tofu init`.

A new entry point that takes a run-id must validate it the same way before its
first AWS call.

### `scripts/ephemeral-env.sh`

**Manage ephemeral per-run test environments.**

- **`up <run-id>`** — Builds the Lambda layer, initializes the OpenTofu backend, plans
  and applies the ephemeral stack, creates Cognito test users, and exports environment
  variables for the run.
- **`env <run-id>`** — Outputs environment variable exports for an existing ephemeral
  stack (without re-applying).
- **`down <run-id>`** — Destroys the ephemeral environment, cleans up S3 buckets and
  CloudWatch log groups, and tears down AWS resources.

**Key flags/arguments:**

- `<up|env|down>` — Required action
- `<run-id>` — Required. See
  [Run identifiers](#run-identifiers-ephemeral-runs) above.
- The script sources `./.env` for `TF_VAR_encryption_passphrase` and AWS credentials.

### `scripts/recover-deploy.sh`

**Restore missing S3 state and import existing AWS resources for a run-id into OpenTofu
state.** Does NOT destroy anything. Used when a prior partial run left resources but the
state file is missing.

**Key flags/arguments:**

- `<run-id>` — Required. See
  [Run identifiers](#run-identifiers-ephemeral-runs) above.

### `scripts/recover-destroy.sh`

**Restore missing S3 state from the latest version, import existing AWS resources, then
destroy orphaned resources for a run-id.** Imports whatever still exists, then runs
`tofu destroy`.

**Key flags/arguments:**

- `<run-id>` — Required. See
  [Run identifiers](#run-identifiers-ephemeral-runs) above.

### `scripts/appsync-ensure-resolver-order.sh`

**Work around AWS AppSync provider ordering issues.** When a Terraform plan would destroy
`aws_appsync_function` or `aws_appsync_datasource` resources, this script runs a
targeted apply for the affected resolver(s) first, so the resolver drops its references
to the old functions/data sources before the full apply deletes them.

**Key flags/arguments:**

- `-d <tofu-dir>` — Target OpenTofu directory (defaults to CWD).
- `-t <resolver-target>` — One or more `-target` addresses to apply first (e.g.
  `module.appsync.aws_appsync_resolver.create_order`). Can be specified multiple times.
- `-- <extra-tofu-args>` — Pass additional arguments through to the `tofu` commands
  (plan/apply).

### `scripts/build-resolvers.mjs`

**Build AppSync resolver JavaScript bundles using esbuild.** Reads resolver source from
`tofu/application/appsync/js-resolvers/` and outputs bundled files to
`tofu/application/appsync/dist/`. Must be run before any `tofu plan`/`apply`/`import`
/`destroy` that involves AppSync functions/resolvers.

**Key flags/arguments:** None (pure Node script). Requires `esbuild` installed — run
`npm ci` at repo root first. If esbuild is absent, exits with: "Run `npm ci` at the
repo root first, then retry."

### `scripts/create-ephemeral-test-users.sh`

**Create ephemeral run-scoped test users in a Cognito User Pool.** Creates Owner
(added to ADMIN group), Contributor, Read-only, and Smoke users with emails patterned
as `<run-id>-owner@kernelworx.test` etc. so they never collide with dev/prod users.
The Smoke user is pre-confirmed so smoke suites run without burning Cognito's daily
email quota (#483); its credentials are exported as `TEST_SMOKE_EMAIL`/`TEST_SMOKE_PASSWORD`.

**Key flags/arguments:**

- `<run-id>` — Required. See
  [Run identifiers](#run-identifiers-ephemeral-runs) above; the script rejects a
  non-matching value before its first Cognito call.
- `<user-pool-id>` — Required Cognito User Pool ID.
- `<client-id>` — Required App Client ID.

### `scripts/create-screenshot-user.sh`

**Create the Alex Kernel screenshot/marketing user in Cognito.** Idempotent: safe to
re-run if the user already exists.

**Key flags/arguments:** None. Loads `TEST_USER_POOL_ID`, `TEST_REGION`, `TEST_ALEX_EMAIL`,
`TEST_ALEX_PASSWORD` from `./.env`.

### `scripts/create-test-users.sh`

**Create test users in Cognito for integration tests.** Uses credentials from `./.env`.
Creates Owner, Contributor, and Read-only users, plus a pre-confirmed Smoke user when
`TEST_SMOKE_EMAIL`/`TEST_SMOKE_PASSWORD` are set, so smoke suites don't burn Cognito's
daily email quota (#483).

**Key flags/arguments:** None. Requires `TEST_USER_POOL_ID`, `TEST_OWNER_EMAIL`,
`TEST_OWNER_PASSWORD`, `TEST_REGION` in environment.

### `scripts/delete-screenshot-user.sh`

**Delete the Alex Kernel Cognito user.** Removes only the Cognito user; the DynamoDB
Account record, seller profiles, campaigns, orders, payment methods, and shares are
preserved by default.

**Key flags/arguments:** None. Requires `TEST_USER_POOL_ID`, `TEST_REGION`, `TEST_ALEX_EMAIL`
from `./.env`.

### `scripts/delete-test-catalogs.py`

**Delete managed catalogs owned by test users.** Scans the DynamoDB catalogs table for
items where `GSI1PK` matches `MANAGED_CATALOG#{sub}` for each test user, then deletes
their METADATA items.

**Key flags/arguments:** None. Reads `DYNAMODB_TABLE_NAME`, `AWS_REGION`, `TEST_USER_POOL_ID`,
and test user emails from environment.

### `scripts/migrate_shares_prefix.py`

**One-off migration: add `ACCOUNT#` prefix to `createdByAccountId` in the shares table.**
Scans the shares table and conditionally updates any `createdByAccountId` missing the
prefix. Dev-only script.

**Key flags/arguments:** None. Requires `SHARES_TABLE_NAME` environment variable (or set
via `.env`). Run with: `uv run python scripts/migrate_shares_prefix.py`.

### `scripts/backfill_email_search_key.py`

**One-off backfill: index existing accounts for admin email prefix search.** The accounts
table's `emailSearchIndex` GSI (constant `emailSearchKey` + `email` range key) is sparse,
so an account written before the index existed carries no `emailSearchKey` and would be
invisible to `adminSearchUser` email search. This script conditionally sets the attribute
on every account that is missing it, so re-running it while sign-ins keep writing is safe.

**Deployment order (required):** deploy the account write path (the Cognito bootstrap
trigger sets `emailSearchKey`) → run this script and then `--verify` until it reports zero
remaining accounts → only then apply the table change that creates the index.

**Key flags/arguments:** `--verify` reports accounts still missing the attribute, writes
nothing, and exits non-zero while any remain (use it to gate the index rollout). Requires
the `ACCOUNTS_TABLE_NAME` environment variable (or set via `.env`). Run with:
`uv run python scripts/backfill_email_search_key.py [--verify]`.

### `scripts/provision-user-totp.sh`

**Provision (or re-provision) a Cognito TOTP device for a user and print the base32
secret on stdout.** Re-provisioning always issues a fresh secret, and the script waits out
the current 30-second TOTP window so the next sign-in does not resubmit a consumed code.
Invoked by `create-test-users.sh`, `create-ephemeral-test-users.sh`, and the deploy
smoke's TOTP step — normally you do not call it directly.

**Key flags/arguments:**

- `<user-pool-id>` — Cognito user pool that owns the user.
- `<client-id>` — Pool client; must allow `USER_PASSWORD_AUTH` (see the `KernelWorx-Web`
  client note in `AGENTS.md`).
- `<username>` — User to provision the device for.
- `PROVISION_USER_TOTP_PASSWORD` — **Required** in the environment. Since #569 the
  password is no longer accepted as a fourth positional argument: process argv is
  world-readable via `/proc/<pid>/cmdline` and `ps`, and the script refuses to start
  without the variable rather than falling back to argv.

### `scripts/contrast_check.py`

**WCAG contrast checker for KernelWorx brand colors.** Audits all text/background
combinations defined in the brand palette against AAA and AA thresholds, printing a
pass/fail matrix.

**Key flags/arguments:** None. Run from repo root: `python3 scripts/contrast_check.py`.

### `scripts/sync-to-cloudflare.sh`

**Sync Route53 DNS records to CloudFlare.** Fetches all Route53 resource record sets
(excluding NS/SOA) and creates/updates matching records in a CloudFlare zone.

**Key flags/arguments:**

- `ROUTE53_ZONE_ID` — Required Route53 hosted zone ID.
- `ENVIRONMENT` — Optional environment name, default `prod`. Examples: `dev`, `prod`.

### `scripts/generate_integration_env.py`

**Generate the integration test environment config from OpenTofu outputs.** Reads
`tofu output -json` for the dev or ephemeral stack and writes the managed keys to the
integration test env file (default `./.env`) and, optionally, the frontend env file —
replacing the hand-maintained values that used to be looked up by naming convention.
Existing files are updated in place; every unmanaged line (secrets, test user
credentials, comments) is preserved. A missing target file is created from the matching
committed template (`.env.example` / `frontend/.env.example`). Managed keys:
`TEST_APPSYNC_ENDPOINT`, `TEST_USER_POOL_ID`, `TEST_USER_POOL_CLIENT_ID`, `TEST_REGION`,
`E2E_BASE_URL` (when the stack exposes `site_url`), and the `VITE_*` frontend keys.

**Key flags/arguments:**

- `--env <name>` — Stack to read: `dev` (default) or `ephemeral/<run-id>`.
- `--out <file>` — Integration test env file to write or check (default `.env`).
- `--frontend-out <file>` — Frontend env file to write or check (e.g. `frontend/.env`).
- `--outputs-json <file>` — Read a captured `tofu output -json` document instead of the
  live stack (no AWS access needed).
- `--check` — Verify the existing file(s) without writing: managed keys must be present
  and non-empty; with `--outputs-json`, values must also match the OpenTofu outputs.

The live stack path sources `./.env` for `TF_VAR_encryption_passphrase` and AWS
credentials and only runs `tofu init` (ephemeral backend selection) and
`tofu output -json` — never `tofu apply`/`destroy`.

### `scripts/ephemeral-recover-common.sh`

**Common helpers for ephemeral environment recovery workflows.** Not intended to be run
directly; sourced by `ephemeral-env.sh`, `recover-deploy.sh`, and `recover-destroy.sh`.
Provides functions for env loading, run-id validation, backend initialization, S3 bucket
emptying, stale lock cleanup, state recovery, resource importing, and CloudWatch log
group cleanup.

`validate_run_id` is the single owner of the run-id rule; see
[Run identifiers](#run-identifiers-ephemeral-runs) above for the contract it
enforces and for the entry points that call it.

**Key flags/arguments:** None (sourced library).

---

## Repo-Root Operational Tooling

### `Makefile`

**Build, test, lint, and deployment commands.** Top-level targets include:

- `make all` — Format + lint + typecheck + test (backend + frontend)
- `make ci` — Spellcheck + lint + typecheck + test (backend + frontend) + guards
- `make test` — Python unit tests
- `make test-e2e` — Python E2E smoke tests
- `make test-all` — All tests (unit + guards + frontend + integration + e2e)
- `make lint` — Run all linters
- `make format` — Format all code
- `make tflint` — Run tflint on OpenTofu code
- `make kics` — Run KICS security scan
- `make clean` — Clean generated files
- `make help` — Print this help text

### GitHub Actions workflows (`.github/workflows/`)

- **`ci.yml`** — Standard CI pipeline (spellcheck + lint + typecheck + complexity + test + guards)
- **`deploy-dev.yml`** / **`deploy-prod.yml`** — Environment deployment workflows
- **`deploy-shared.yml`** — Shared infrastructure (Cognito, CloudFront, WAF) deployment
- **`ephemeral-test.yml`** — Ephemeral environment test creation/destruction
- **`ephemeral-teardown-on-merge.yml`** — Automatic teardown of ephemeral stacks on PR merge
- **`manual-teardown.yml`** — Manual teardown for a PR (input: `pr_number`)
- **`recover-environment.yml`** — Recover deploy or destroy for a PR (inputs: `pr_number`,
  `mode: recover-deploy` | `mode: recover-destroy`)

---

## When to Run Which Script

| Goal                                                        | Script                                     |
| ----------------------------------------------------------- | ------------------------------------------ |
| Create/manage a temporary test environment                  | `scripts/ephemeral-env.sh up/down`         |
| Recover from a missing state file                           | `scripts/recover-deploy.sh`                |
| Recover and destroy orphaned resources                      | `scripts/recover-destroy.sh`               |
| Ensure resolver ordering before destructive AppSync changes | `scripts/appsync-ensure-resolver-order.sh` |
| Build resolver JS bundles before any ToFu operation         | `scripts/build-resolvers.mjs`              |
| Create test users for a new ephemeral run                   | `scripts/create-ephemeral-test-users.sh`   |
| Set up the Alex Kernel marketing user                       | `scripts/create-screenshot-user.sh`        |
| Create generic test users for integration tests             | `scripts/create-test-users.sh`             |
| Delete the Alex Kernel Cognito user (preserving data)       | `scripts/delete-screenshot-user.sh`        |
| Delete test user catalogs                                   | `scripts/delete-test-catalogs.py`          |
| Run shares table migration (dev only)                       | `scripts/migrate_shares_prefix.py`         |
| Backfill accounts email prefix-search key                  | `scripts/backfill_email_search_key.py`     |
| Provision a TOTP device for a test user                     | `scripts/provision-user-totp.sh`           |
| Check WCAG contrast of brand colors                         | `scripts/contrast_check.py`                |
| Sync Route53 DNS to CloudFlare                              | `scripts/sync-to-cloudflare.sh`            |
| Generate integration test env config from tofu outputs      | `scripts/generate_integration_env.py`      |

---

## Development Notes

- **Complexity gate (xenon over radon)** — CI fails when the average cyclomatic
  complexity of `src/` exceeds Grade A (<=5) or any single block exceeds Grade B
  (<=10): `uv run xenon --max-average A --max-absolute B --exclude
  '*payment_methods.py,*logging.py' src/`. Two files
  (`src/utils/payment_methods.py`, `src/utils/logging.py`) are excluded because
  they contain legacy Grade C blocks; drop their exclusions as those functions
  are refactored, then tighten `--max-absolute` to A once every function grades
  A.
  Radon remains the analysis engine — run `uv run radon cc src/ -a -s` for
  per-function detail.
- **`build-resolvers.mjs`** must be run (or triggered automatically by deploy scripts) before
  any `tofu` command that references AppSync functions or resolvers, because `file()` calls
  in the OpenTofu configuration evaluate the bundled output.
- **`ephemeral-env.sh`** requires `TF_VAR_encryption_passphrase` in `./.env` and AWS credentials.
- **`sync-to-cloudflare.sh`** requires `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ZONE_ID` in the
  environment.
- Recovery scripts (`recover-deploy.sh`, `recover-destroy.sh`) source `ephemeral-recover-common.sh`
  and will fail loudly if the encryption passphrase is missing.
- The `appsync-ensure-resolver-order.sh` script targets specific resolver/function addresses
  identified in `tofu/application/modules/appsync/resolvers_mutations.tf` and
  `resolvers_queries.tf`. The authoritative, per-target rationale list lives with the two
  invocations: `.github/workflows/deploy-shared.yml` (deploys) and `scripts/ephemeral-env.sh`
  (ephemeral stacks) — read the `-t` targets and their comment blocks there rather than here.
