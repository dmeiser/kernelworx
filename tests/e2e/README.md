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
| `test_smoke_auth_boundary.py` | Unauthenticated redirect; profile access control |
| `test_smoke_profile.py` | Owner dashboard shows a seller profile |
| `test_smoke_campaign.py` | Campaign list visible; create a campaign |
| `test_smoke_order.py` | Create an order; order persists on reload |
| `test_smoke_sharing.py` | Invite → accept → revoke share; read-only restriction |
| `test_smoke_signup.py` | New-user sign-up flow |
| `test_smoke_settings.py` | Basic settings page flow (view and update settings) |
| `test_smoke_reports.py` | Reports page smoke: load and request/download report |
| `test_smoke_account_deletion.py` | Account deletion flow (gated by RUN_ACCOUNT_DELETION; runs disposable-user test in CI) |
| `test_smoke_show_sell.py` | Show & Sell Stage 1 acceptance journey (own lane identities; not a `smoke` test) |

---

## Show & Sell acceptance journey

`test_smoke_show_sell.py` drives the Stage 1 journey from
`docs/specs/show_sell/SHOW_AND_SELL_SMOKE_TEST_PLAN.md` in a real browser against
a deployed stack: preview gate both ways, Unit create, invite and redemption, Unit
Campaign with its join code, Scout join, roster read and removal, Unit Campaign
close, the teardown of the second admin grant, and the server-side refusal for an
account that holds no Unit grant. Everything it observes goes into one artifact
directory: per-step screenshots, one Playwright trace per persona session, a
`failure-<step>` screenshot plus JSON when a step stops, and
`evidence.json` / `evidence.md`.

It is a **regression harness and a reproducible record**, not the acceptance
verdict: QA executes the checklist criteria itself against the deployed
environment. What this file buys is that the journey can be re-run in one command,
and that a re-run shows what the deployed build answered.

It is deliberately **not** marked `smoke` — it carries `slow`. The deploy path runs
`-m smoke` on every push to `dev`, and this journey takes minutes and writes
fixture rows. Nothing in CI runs it, and no workflow holds its passwords.

### The identities are standing fixtures, and they are not provisioned here

The journey signs in as four fixture accounts that already exist on the dev pool
(`us-east-1_sDiuCOarb`):

| Persona | Username | `show-sell-preview` | Role in the journey |
| --- | --- | --- | --- |
| `admin` | `qa-show-sell-admin@dev.kernelworx.app` | yes | creates the Unit, invite, and Unit Campaign; reads the roster; closes and tears down |
| `admin2` | `qa-show-sell-admin2@dev.kernelworx.app` | yes | redeems the invite and becomes a second Unit admin |
| `scout` | `qa-show-sell-scout@dev.kernelworx.app` | **yes** | holds the catalog, Scout profile, and Scout Campaign the join needs; joins by code |
| `outside` | `qa-show-sell-outside@dev.kernelworx.app` | **no** | the closed half of the gate, and the no-grant refusal probe |

`scripts/qa_fixture.py` is the **only** thing that will create, refresh, or delete
those identities and their group membership — and it lands with WORK-201, which is
still in progress. Until that script is in the tree, the four accounts exist on the
dev pool and nothing in this repository provisions them; this harness only reads
what the environment gives it. It never calls a Cognito admin API and holds no AWS
credentials — that is structural, not a style choice: a second script provisioning
the same accounts is how the dev pool accumulated eighteen app clients named
`KernelWorx-Web`, only one of which allows `USER_PASSWORD_AUTH`.

The Scout holds the preview group because `frontend/src/ShowSellRoutes.tsx` gates
the **whole** `/show-sell/*` tree, including `/show-sell/join`. A Scout outside the
group cannot open its own join page, so the join step cannot run. `outside` is what
carries the closed half of the gate assertion, and it never joins anything.

**The correction that has to land before WORK-201's first `up`:** its identity
table still places `qa-show-sell-scout` **outside** `show-sell-preview`. Running
`up` with that table moves the Scout out of the group and silently removes this
journey's step-2 precondition — the join page stops opening. The evidence is this
journey's own steps: the Scout opens `/show-sell/join`, `outside` is redirected off
it. Whoever runs `up` changes the Scout's row to a group member first.

### Environment

| Variable | Why |
| --- | --- |
| `TEST_QA_SHOW_SELL_ADMIN_EMAIL`, `TEST_QA_SHOW_SELL_ADMIN_PASSWORD` | the `admin` persona |
| `TEST_QA_SHOW_SELL_ADMIN2_EMAIL`, `TEST_QA_SHOW_SELL_ADMIN2_PASSWORD` | the `admin2` persona |
| `TEST_QA_SHOW_SELL_SCOUT_EMAIL`, `TEST_QA_SHOW_SELL_SCOUT_PASSWORD` | the `scout` persona |
| `TEST_QA_SHOW_SELL_OUTSIDE_EMAIL`, `TEST_QA_SHOW_SELL_OUTSIDE_PASSWORD` | the `outside` persona |
| `TEST_USER_POOL_CLIENT_ID` | the app client to sign in as (`USER_PASSWORD_AUTH` must be enabled on it). Required — the run never looks the client up by name |
| `TEST_QA_SHOW_SELL_BASE_URL` | the deployed app the journey drives. `target_origin` publishes it into `E2E_BASE_URL`, which is the variable the page objects actually navigate; `E2E_BASE_URL` on its own works too, and this key wins when both are set |
| `TEST_USER_POOL_ID` | recorded in the evidence only; nothing signs in with it |
| `TEST_REGION` | pool region, defaults to `us-east-1` |
| `SS_ACCEPTANCE_EVIDENCE_DIR` | artifact directory; defaults to `test-results/show-sell-<DATA_ID>` and is wiped at the start of a run |
| `SS_DATA_ID` | pins the per-run row names, so a re-run reuses the rows a previous run created |

A missing identity stops the run naming the missing **keys**; no code path prints a
password, and none is ever taken from a command line.

### Run it

The QA runtime is the single source of these variables: the platform writes the
eight identity pairs, the base URL, and the app client id into every QA run. For
that path the command is the whole recipe — nothing to find, nothing to source:

```bash
uv run pytest tests/e2e/test_smoke_show_sell.py -v
```

A human runner holds the same variables in the `0600` file `scripts/qa_fixture.py`
writes. That file is **JSON, not shell**: `write_secrets()` ends in `json.dump`, so
it has to be read by a JSON parser. Sourcing it is the failure a reader hits first —
`.` hands each `"KEY": "value"` line to bash as a command, which answers `command
not found` nine times, exports nothing, and the journey then stops with `the
acceptance run needs the deployed app URL`. A `jq` expression works too; what never
works is treating JSON as a shell script.

The file is `$QA_FIXTURE_SECRETS_FILE`, defaulting to
`~/.kernelworx/qa-fixture-secrets.json` — the location and format the fixture script
defines, with `docs/QA_FIXTURE_RUNBOOK.md` as its runbook. Read it from the
repository root (and never with `set -x`, which would echo the exports):

```bash
export QA_FIXTURE_SECRETS_FILE="${QA_FIXTURE_SECRETS_FILE:-$HOME/.kernelworx/qa-fixture-secrets.json}"
eval "$(uv run python -c '
import json, os, shlex
values = json.load(open(os.environ["QA_FIXTURE_SECRETS_FILE"], encoding="utf-8"))
for key in sorted(values):
    if key.startswith("TEST_QA_SHOW_SELL_"):
        print(f"export {key}={shlex.quote(values[key])}")
')"
```

That loader prints nothing: the `export` lines are captured by `$(…)` and evaluated,
never echoed. Only `TEST_QA_SHOW_SELL_*` keys are exported, and `shlex.quote` is not
decorative — the fixture password alphabet is
`string.ascii_letters + string.digits + "!@#$%^&*-_+="`, so an unquoted value would
be re-parsed by the shell. Then run the journey:

```bash
export TEST_USER_POOL_CLIENT_ID=<the KernelWorx-Web client of the dev pool>
uv run pytest tests/e2e/test_smoke_show_sell.py -v
```

Either way the run needs three things and stops naming the key when one is
missing: the eight `TEST_QA_SHOW_SELL_*` identity values, a base URL, and
`TEST_USER_POOL_CLIENT_ID`. The fixture file carries the first two — its nine keys
include `TEST_QA_SHOW_SELL_BASE_URL` — and the client id is the one id
`uv run python scripts/qa_fixture.py up` prints in its sign-in proof. Nothing in
that list is a repository secret, and nothing needs AWS credentials to run the
journey itself.

`TEST_USER_POOL_CLIENT_ID` sits outside the card's nine-key list and has to be
written into the QA environment alongside them. The dev pool has many clients
named `KernelWorx-Web` and only one enables `USER_PASSWORD_AUTH`, so guessing it
by name is not an option — see the deploy-smoke entry in `AGENTS.md`.

### Sharp edges

- **Trace after login, never across it.** A trace records request bodies and the
  login form posts the Cognito password. Fixture codes (16-character invite and
  join codes) are masked in screenshots and overwritten inside traces by
  `utils/show_sell_evidence.redact_and_scan` with a same-length placeholder — the
  trace is NDJSON with byte offsets, so a different length corrupts it. A password
  found in any artifact **fails the run** instead of being redacted: an artifact
  that carried a credential is compromised, not clean.
- **Masking is a required argument, not a habit.** `_screenshot` takes `masks` with
  no default, and every step passes `code_mask_locators()` from the page object, so
  one list covers every code surface (`CODE_MASK_SELECTORS`) for step and failure
  screenshots alike. That is because the Unit Campaign page renders
  `Join code: <strong data-testid="join-code">` while the campaign is open
  (`frontend/src/pages/UnitCampaignWorkspacePage.tsx:138`) — the roster steps are on
  that page, so an unmasked screenshot there photographs a live join code, and
  pixels survive a text scan. The code-bearing steps also record
  `maskedCodeElements`, the count of elements the mask matched, so the record says
  what was hidden rather than only claiming nothing was visible.
- **The app client is supplied, never looked up.** See the deploy-smoke entry in
  `AGENTS.md`; the dev pool has many clients named `KernelWorx-Web`.
- **One origin drives the browser and the probes.** `tests/e2e/pages/base_page.py`
  and `tests/e2e/utils/auth.py` read `E2E_BASE_URL` only, and default to
  `https://localhost:5173`; the GraphQL helper prefers
  `TEST_QA_SHOW_SELL_BASE_URL`. The session fixture `target_origin` in the spec
  publishes the resolved origin into `E2E_BASE_URL` before anything navigates, so
  setting the QA key alone is enough. If that fixture is ever removed, the journey
  drives a local Vite server while its queries hit dev, and it fails in step 1 on a
  page that never loaded.
- **`Username` is a UUID for these accounts** — the pool keeps an email *alias*, so
  Cognito-side lookups by address do not match the username. Group membership is
  what the app reads (`cognito:groups`), and the fixture script is what sets it.
- **Ids come back in two spellings.** `listMyProfiles` answers `PROFILE#<uuid>`,
  `getMyAccount` answers `ACCOUNT#<sub>`, Unit ids are bare UUIDs. The page object
  compares them through `profile_key` and `show_sell_evidence.bare_account_id`;
  compared raw, a joined Scout or the caller's own admin grant reads as missing.
- **Keep the record out of `test-results/` if you want to read it afterwards.**
  `pytest-playwright` installs a session-scoped autouse fixture that wipes whatever
  `--output` points at — the whole directory, recursively — whose default is
  `test-results` relative to the working directory. Any pytest run in the same
  tree — even a unit run that never touches a browser — deletes it, journey record
  included. Point `SS_ACCEPTANCE_EVIDENCE_DIR` outside it when the record matters.
- **Read-after-write needs a bounded wait, not a sleep.** A just-created profile,
  campaign status chip, roster row, or admin-grant row is read back through an
  index and can lag, so those reads are polled and the failure names what was
  actually observed. The roster is the sharpest case: after a removal the panel
  refetches and can still answer the old `Joined` status with its Remove button
  still on it, so `wait_for_roster_removal` reloads until the chip reads `Removed`
  and the button is gone (the shipped panel renders `remove-member-*` only for an
  ACTIVE row). The grant table does the same after a revocation, and the record
  keeps the server's own `unitAdmins` answer alongside the panel's.
- **The Unit tenant key varies per run.** A Unit is keyed by type, number, city,
  and state, so a fixed number collides with the Unit a previous run left on dev.
  The number is derived from `DATA_ID`. The collision would be answered by the "A
  Unit with these details already exists" second-intent confirm, and
  `create_unit` still takes that confirm and records `duplicateConfirmTaken` — but
  it does **not** open in the shipped build today: `createUnit` reports the
  duplicate as a bare `INVALID_INPUT` with no `details`, while
  `frontend/src/lib/units.ts:isDuplicateUnitError` keys off
  `extensions.details.subcode`, and its `INVALID_INPUT` + "already exists" fallback
  reads `extensions`, not AppSync's top-level `errorType`. The browser shows the
  raw message in `[role='alert']` instead. That is a product defect, not something
  this harness works around.
- **What is left behind.** Stage 1 ships no Unit or Unit Campaign delete, and
  catalogs are never deleted by product decision, so a run leaves its Unit, its now
  Closed Unit Campaign, the fixture Scout's profile and campaign, and two catalogs
  on dev. The roster membership and the second admin grant *are* removed, and both
  removals are asserted. Re-runs with a fresh `DATA_ID` add rows; pin `SS_DATA_ID`
  to reuse them. `qa_fixture.py down --yes` is what sweeps the pool side.

---

## Structure

```
tests/e2e/
├── conftest.py               # Session fixtures; test-user loading; post-suite cleanup
├── pytest.ini                # strict-markers, no-randomly, screenshot/video on failure
├── test_smoke_settings.py    # Smoke tests for settings flows
├── test_smoke_reports.py     # Smoke tests for reports flows
├── pages/
│   ├── base_page.py
│   ├── login_page.py
│   ├── dashboard_page.py
│   ├── campaign_page.py
│   ├── campaign_settings_page.py
│   ├── manage_page.py
│   ├── order_page.py
│   ├── payment_page.py
│   ├── reports_page.py
│   └── share_page.py
└── utils/
    └── auth.py               # login / logout helpers
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
