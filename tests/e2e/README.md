# E2E Smoke Tests

End-to-end smoke tests that exercise the running app from a browser using
[Playwright for Python](https://playwright.dev/python/) (Chromium).  Tests
target the **dev environment** (`https://dev.kernelworx.app`) for local runs.
In CI, these smoke tests are also run against **production** after successful
prod deploys (with explicit guardrails in workflow validation).

---

## Prerequisites

### 1. Dev environment deployed

`https://dev.kernelworx.app` must be live before running any tests.  Deploy
with:

```bash
./tofu/application/scripts/deploy.sh dev apply
```

### 2. `.env` configuration

Copy `.env.example` to `.env` in the repository root and populate the
e2e-specific fields:

```
# Target URL
E2E_BASE_URL=https://dev.kernelworx.app

# Test user credentials
TEST_OWNER_EMAIL=owner@example.com
TEST_OWNER_PASSWORD=<password>

TEST_CONTRIBUTOR_EMAIL=contributor@example.com
TEST_CONTRIBUTOR_PASSWORD=<password>

TEST_READONLY_EMAIL=readonly@example.com
TEST_READONLY_PASSWORD=<password>

# Cognito (used by cleanup fixture)
TEST_USER_POOL_ID=us-east-1_XXXXXXXXX
TEST_REGION=us-east-1

# AppSync endpoint + API_KEY-mode key (optional). Only the API-key reachability
# check in test_smoke_auth_boundary.py needs these; the ephemeral stack exports
# them, and the check skips with a reason when they are unset.
# TEST_APPSYNC_ENDPOINT=https://<api-id>.appsync-api.us-east-1.amazonaws.com/graphql
# TEST_APPSYNC_API_KEY=<key>

# DynamoDB table names are resolved automatically from E2E_BASE_URL + TEST_REGION.
# Convention: kernelworx-{type}-{region_abbrev}-{environment}
# Example for dev: kernelworx-accounts-ue1-dev
# Override only if your table names deviate from the convention:
# ACCOUNTS_TABLE_NAME=
# PROFILES_TABLE_NAME=
# CAMPAIGNS_TABLE_NAME=
# ORDERS_TABLE_NAME=
# SHARES_TABLE_NAME=
# CATALOGS_TABLE_NAME=
# INVITES_TABLE_NAME=
# SHARED_CAMPAIGNS_TABLE_NAME=
```

### 3. Test users in Cognito

Create the three test users in the dev User Pool (idempotent — safe to
re-run if users already exist):

```bash
bash scripts/create-test-users.sh
```

### 4. Admin-managed catalog

At least one product catalog must exist before campaign-creation tests run.
The smoke tests use the `/create-campaign` page flow; without an admin catalog
its catalog dropdown is empty and tests fail with:

> `AssertionError: No enabled catalog options found in dev environment.`

**To create a catalog:** log in to the dev app as an admin user, navigate to
**Admin → Catalogs**, and click **Create Catalog**.  This is a one-time
step per environment.

### 5. AWS credentials

Active AWS credentials are required for the post-suite DynamoDB cleanup
fixture.  If credentials are unavailable the cleanup step is skipped with a
warning and test data remains in the tables.

### 6. Install Playwright browsers (first time only)

```bash
uv run playwright install chromium
```

---

## Running tests

### Run the full suite

```bash
uv run pytest tests/e2e/ --ignore=tests/unit -v
```

### Run with the `smoke` marker

```bash
uv run pytest tests/e2e/ -m smoke -v
```

### Run a single file

```bash
uv run pytest tests/e2e/test_smoke_campaign.py -v
```

### Run with a visible browser (headed mode)

```bash
uv run pytest tests/e2e/ --headed -v
```

### Run slowly (for debugging)

```bash
uv run pytest tests/e2e/ --headed --slowmo=500 -v
```

---

## Test file overview

| File | What it covers |
|---|---|
| `test_smoke_auth.py` | Login / logout flow |
| `test_smoke_auth_boundary.py` | Unauthenticated redirect; profile access control; public order route stays public; API key cannot reach Cognito-only fields |
| `test_smoke_profile.py` | Owner dashboard shows a seller profile |
| `test_smoke_campaign.py` | Campaign list visible; create a campaign |
| `test_smoke_order.py` | Create an order; order persists on reload |
| `test_smoke_sharing.py` | Invite → accept → revoke share; read-only restriction |
| `test_smoke_signup.py` | New-user sign-up flow |
| `test_smoke_public_orders.py` | Public order share link end to end: seller enable + acknowledgements + share view + rotate + disable, anonymous buyer offer render, QR link safety, not-available states. The buyer submit/receipt tests are skipped with a reason until the `publicCreateOrder`/`publicGetOrderReceipt` resolvers ship. |
| `test_smoke_campaign_reports.py` | Shared-campaign report views + Excel exports; carries a skip-marked placeholder for the pending `customerEmail` Order Details column (slice-plan item 9) |
| `test_smoke_settings.py` | Basic settings page flow (view and update settings) |
| `test_smoke_reports.py` | Reports page smoke: load and request/download report |
| `test_smoke_account_deletion.py` | Account deletion flow (gated by RUN_ACCOUNT_DELETION; runs disposable-user test in CI) |

---

## Structure

```
tests/e2e/
├── conftest.py               # Session fixtures (incl. public_orders_setup); test-user loading; post-suite cleanup
├── pytest.ini                # strict-markers, no-randomly, screenshot/video on failure
├── test_smoke_*.py           # One suite per flow — see the "Test file overview" table above
├── fixtures/                 # Static assets uploaded during tests (QR images)
├── pages/                    # One page object per app surface (e.g. public_order_page.py)
└── utils/                    # Shared helpers (auth.py, public_orders.py, ...)
```

---

## Cleanup

After every test session the `global_cleanup` autouse fixture
(`conftest.py`) sweeps all DynamoDB records owned by the test users:
profiles, campaigns, orders, shares, and invites.

**What is preserved:**
- Cognito user accounts
- DynamoDB `Account` records

This allows the same test users to be reused across runs without
re-running `create-test-users.sh`.  If AWS credentials are unavailable,
cleanup is skipped with a warning.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `AssertionError: Owner must have at least one seller profile` | Profile fixture failed | Check screenshot in `test-results/`; verify Cognito login credentials |
| `AssertionError: No enabled catalog options found` | No admin catalog in dev | Follow prerequisite step 4 above |
| `TimeoutError` navigating to app | Dev environment not deployed | Run `./tofu/application/scripts/deploy.sh dev apply` from the repo root |
| Tests skip with `campaign_id not set` | `test_create_order` was not run | Run the full `test_smoke_order.py` file (tests must run in order) |
| Cleanup skipped with warning | No active AWS credentials | Run `aws sts get-caller-identity` to verify; re-authenticate if needed |
