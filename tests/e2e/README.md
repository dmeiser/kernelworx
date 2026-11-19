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

Show & Sell journeys also need the signed-in fixture identities
(`qa-show-sell-*@dev.kernelworx.app`). Create or refresh them with
`uv run python scripts/qa_fixture.py up` and load the passwords it writes; see
[docs/QA_FIXTURE_RUNBOOK.md](../docs/QA_FIXTURE_RUNBOOK.md).

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

### Record the flow a run exercised (QA evidence)

```bash
uv run pytest tests/e2e/ -m smoke --video=on -v
```

The CLI `--video=on` overrides the default from `tests/e2e/pytest.ini`
(`--video=retain-on-failure`) and keeps every recording. After the session
they are collected under `test-results/video/`:

- each test's own context (provided by pytest-playwright) →
  `test-results/video/<slugified test id>.webm`. The plugin also keeps a
  per-test artifact folder `test-results/<test id>/`, which always holds
  `video.webm`; the trace and screenshot in it belong to a *failed* test only,
  because `--tracing` and `--screenshot` stay `retain-on-failure`;
- the fixture flows that `conftest.py` runs in hand-built contexts →
  `ensure_owner_profile.webm`, `ensure_owner_catalog.webm`,
  `ensure_readonly_share_owner.webm`, `ensure_readonly_share_readonly.webm`.
  Those fixtures are session-scoped, so each files one recording per run;
- a test that drives a context of its own because it must not carry a session
  (the buyer flows in `test_smoke_public_orders.py`, and the account-deletion
  happy path) records through the same `conftest` helpers → `test_<name>-<browser>.webm`
  (the `[chromium]` parametrization pytest-playwright adds to every test that
  asks for `browser` is folded into the file name, exactly as it is in the
  plugin's own per-test names).

Two smoke tests make no browser calls (they assert on GraphQL responses), so
they have no flow to record. Where a test opens a second context for another
persona, the recording covers its main flow, not that extra context.

The default retention (`make test-e2e`) keeps video only when the run fails —
alongside screenshots and the trace — and prunes a passing run's recordings so
routine runs leave nothing behind. Note that every new session wipes
`test-results/` before running: copy the videos you want to keep before
re-running.

Playwright records webm; convert for review like this:

```bash
ffmpeg -i <in>.webm -c:v libx264 -pix_fmt yuv420p -movflags +faststart <out>.mp4
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
| `test_smoke_show_sell_stage2.py` | Show & Sell Stage 2 acceptance journey — stock, Scout custody, Order fulfillment (same fixture identities; not a `smoke` test) |

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

`scripts/qa_fixture.py` is the **only** thing that creates, refreshes, or deletes
those identities and their group membership — it lands with WORK-201. The four
accounts exist on the dev pool; this harness only reads what the environment
gives it. It never calls a Cognito admin API and holds no AWS
credentials — that is structural, not a style choice: a second script provisioning
the same accounts is how the dev pool accumulated eighteen app clients named
`KernelWorx-Web`, only one of which allows `USER_PASSWORD_AUTH`.

The Scout holds the preview group because `frontend/src/ShowSellRoutes.tsx` gates
the **whole** `/show-sell/*` tree, including `/show-sell/join`. A Scout outside the
group cannot open its own join page, so the join step cannot run. `outside` is what
carries the closed half of the gate assertion, and it never joins anything.

**Landed with WORK-201:** that table used to place `qa-show-sell-scout` **outside**
`show-sell-preview`, and that is the state the pool held when this journey was
first run — the Scout was redirected off `/show-sell/join`, `outside` was redirected
off it too. `up` now asserts the Scout as a member and keeps only `outside` out, so
running it repairs this journey's step-2 precondition instead of removing it. Do
not move the Scout back out: no `up` and no manual `admin-remove-user-from-group`
may take the group away from it.

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
- **`Username` is not the address for these accounts.** The pool declares
  `username_attributes = ["email"]`, and every stored `Username` read back from it
  on 2026-11-16 is a UUID equal to that user's `sub` (the pool's one exception is a
  `Google_<id>` federated row). Sign-in and Cognito admin lookups take the address
  and resolve it, but code that treats the stored `Username` as an address matches
  nothing. Group membership is what the app reads (`cognito:groups`), and the
  fixture script is what sets it.
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

### Stage 2 lane: `test_smoke_show_sell_stage2.py`

`test_smoke_show_sell_stage2.py` is checklist §2.8.5: the Stage 2 journey — inventory receipt and
stock-only adjustments, issue into Scout custody, a door-to-door sale that consumes custody,
fulfillment from Kernel stock and from the Council, a reversal, a custody return — asserted against
the deployed GraphQL reads and the three §2.6 screens, with the movement trail read back after the
writes. It writes what the stack answered into `evidence.md`, and it stops with words rather than a
pass when the stack cannot carry it. Same fixture identities as Stage 1, same loader above, same
`slow` marker, and no CI workflow runs it or holds its passwords:

```bash
SS_DATA_ID=stage2-1118013 uv run pytest tests/e2e/test_smoke_show_sell_stage2.py -v
```

| Variable | Meaning |
| --- | --- |
| `SS_DATA_ID` | the lane's `DATA_ID`. The Unit number, campaign name, seller name and every idempotency key are derived from it. Unset, the run generates one — which is what a run meant as fresh evidence needs, because the keys mean a pinned re-run *replays* the writes (the idempotency layer answers the original payload) instead of performing them |
| `SS_SHARED_CATALOG` | the admin-managed catalog both Campaigns are created on, by name. Unset, the run takes the first `ADMIN_MANAGED` catalog that carries products |
| `SS_ACCEPTANCE_EVIDENCE_DIR` | where `evidence.json`, `evidence.md`, the traces and the masked screenshots go (default `test-results/show-sell-stage2-<SS_DATA_ID>`) |
| `SS_SWEEP_PRIOR` | comma-separated `DATA_ID`s of earlier runs of this lane whose leftovers should be taken back before the record is written. Selection is by that lane's own naming templates — the Unit number derived from the id, the campaign name, the seller name — so a row the lane did not create cannot be caught by it, and the current run's id is excluded by the caller and again inside the sweep. That derivation is the lane's own rule, so a sibling lane whose Unit number does not follow it (the canary's Unit is the lane's number plus one) is not a valid value. The tokens handed to the sweeper come from reads of that run: its Unit from `myUnits`, its Unit Campaigns from `unitCampaigns`, those Campaigns' Scout Campaign ids from `unitCampaignRoster` (the active-join guard rule needs that exact id — a `profile` token names only one of the four shared fixture identities, and that identity has a guard per Campaign), and its seller profile from `listMyProfiles`. Each named id is reported as found / removed / left, and every one of them is handed to `scripts/qa_fixture.py sweep` even when those reads answer nothing, because that run's idempotency markers are keyed on its `DATA_ID` alone and are reachable after its Unit row is gone; a `DATA_ID` that turns out to have left nothing says so and counts as swept, one whose rows are still there fails the run, a sweep that left a row it could not attribute fails the run, and a sweep that could not read a table is recorded as blocked, naming the permission that table is missing, rather than as cleaned. An earlier run gets no residue census — its Unit Campaign rows are already gone, so no Stage 2 read can count what it left in an unreadable table — and its record says that plainly instead of claiming the residue is gone |
| `SS_STRICT_CLEANUP` | `1` reverses the two residues checklist §2.8.7 accepts as amended (WORK-162, Amendment B) and makes them fail the run: the lane's own retained append-only movement rows (`HISTORY`, which the product has no path to delete), and a `BLOCKED <table>: <action> is not granted to this identity …` whose rows the record counted through a product read instead of a scan. `LEFT`, `FAILED` and `UNKNOWN` fail the run either way. Off by default on shared `dev`, where no supported path deletes an inventory balance or an audit movement and `kernelworx-qa-ue1-dev` is denied `dynamodb:Scan` on the Stage 2 tables; the acceptance is a switch rather than a default, so a reviewer can see it taken back |

**One catalog has to serve both Campaigns, and only an app admin can create it.** Unit Campaign
balances key on the Unit Campaign's own `catalogId` while `createOrder` prices the sale in the Scout
Campaign's catalog, so a lane whose two Campaigns sit on different catalogs gets its custody sale
refused with no Order written (AGENTS.md, "A joined Scout Campaign and its Unit Campaign can sell
from different catalogs"). The create-campaign picker offers a caller their own catalogs plus
`listManagedCatalogs`, and that query filters `catalogType = ADMIN_MANAGED`: a `createCatalog`
catalog is `USER_CREATED` and the other identity never sees it, measured on dev on 2026-11-18, and
`createManagedCatalog` answers the fixture Unit admin `FORBIDDEN` ("Admin access required"). So the
lane uses the managed catalog the stack already carries — on dev, `E2E Test Catalog`
(`CATALOG#e2e-test-catalog`) — and skips with those words when the stack carries none.

**Line identities belong to the write.** `createOrder` mints each line's `lineItemId` (§5.19) and
dev answers the sale with one; every fulfillment, reversal and screen row keys on that value, so the
lane reads it out of the answer instead of naming its own. The same is true of the door-to-door
sale's place in the trail: the custody it consumed is traced by an `INDIVIDUAL_FULFILL` movement
naming the Order and its `SCOUT_CUSTODY` fulfillment, because the `SCOUT_SALE_CONSUME` type requires
a Show & Sell event `saleId` the door-to-door path does not have.

**Cleanup is a gate, not a log.** Every step runs in the `finally` and reports a verdict, the evidence is
written first, and only then does `assert_cleanup_clean` turn an unmet step into a failed run. A mutation the
server refused, a read-back that still answers the row it was meant to remove, or a canary the sweep disturbed
is recorded as `failed` and always fails the run: before this shape a refused `deleteOrder` was filed as an
ordinary observation and the suite exited 0, which is how a mandatory cleanup gate stops meaning anything. A
step the *environment* made impossible is recorded as `blocked`, with the error that says why — the sweep's
`BLOCKED <table>: …` line — and under checklist §2.8.7 as amended (WORK-162, Amendment B) that is accepted rather
than fixed, because shared `dev` gives no path to delete a balance or an audit movement: the row still stands in
the record with its counts, and `SS_STRICT_CLEANUP=1` turns it back into a failure. Either way a cleanup the run
did not achieve is never presented as one it achieved. The sweep's survivors are judged by which class they belong
to, and the classes are not interchangeable: a row a reviewed rule attributed to another tenant (`kept`) survives
and the sweep still passes — that survival is the proof the sweep was narrow enough; a row this lane's tokens named
that no rule can attribute (`UNKNOWN`) is residue nobody reviewed and fails the run; the lane's own append-only
movement rows (`HISTORY`) and a table this identity cannot read (`BLOCKED`) are the two residues the amendment
accepts, counted and attributed rather than reported as cleaned. A `BLOCKED` table is accepted only where the
record can name what sits in it: the lane counts its own rows there with the application's own reads first
(`_residue_census`, over the `inventory`, `orders` and `order-fulfillments` tables), and a blocked table no read
answers stays `blocked` instead of passing. A sweeper exit code the record cannot account for is itself a `failed`
row. The verdict rule lives in `tests/e2e/utils/show_sell_stage2_support.py` (`run_cleanup_step`,
`assert_cleanup_clean`, `sweep_verdict`), so the unit suite can execute it without a deployed stack.

**The lane cleans up after itself in the `finally`, not on the happy path.** It returns held custody, zeroes
the balances it wrote (as compensating rows: `inventoryMovements` is append-only, and the inventory model's
only correction is another movement), deletes the Orders it wrote — `deleteOrder` takes the whole fulfillment
partition with the Order, and the Order is the seller profile's own record, so the teardown sends it with the
Scout's token rather than the Unit Admin's — revokes the share it granted, removes the roster membership, then
deletes the Scout Campaign and the seller profile. Every removal is read back through the endpoint the
acceptance assertions use, because a mutation that answered `true` is not evidence that a row is gone. What it
cannot remove is the Unit and Unit Campaign rows and the Stage 2 inventory partitions: the shipped SDL carries
no `deleteUnit` and no `deleteUnitCampaign`. Its deactivation step is limited to the Campaigns this run created
— lane construction reuses a Unit that already carries the run's tenant key, so the Unit's campaign list is not
the lane's own set — and the record says how many Campaigns on that Unit it left alone. Those go through the one sanctioned fixture sweeper,
`scripts/qa_fixture.py sweep --lane data-id=<DATA_ID> --lane unit=<unitId> --lane unit-campaign=<id> … --yes`,
which the lane calls as a subprocess — project memory (AGENTS.md, "Show & Sell QA login fixture on the dev
pool") says the harness holds no AWS credentials, so the lane never opens a DynamoDB client of its own. Every
token names its kind (`data-id`, `unit`, `unit-campaign`, `campaign`, `profile`, `join-code`, `order`) and has
to match the shape the application stores for it: the sweeper refuses free text, a prefix of an id, or a kind
it does not know, because `--yes` is already given and a token with no kind is a sweep that guesses. The sweeper
then applies one reviewed rule per key shape — Unit metadata and grants, Unit Campaign metadata, roster
membership, active-join guard, join-code pointer, idempotency marker, inventory balance / custody / allocation
/ movement, Order and fulfillment — and deletes only the rows a rule says belong to this lane, keeping a third
party's grant, membership, custody, movement or marker that happens to sit on a lane partition and reporting
each one as refused. Attribution alone was the old test, and it was not enough: a balance or custody row
carries no account at all and a join-code pointer carries only a campaign id and a timestamp, which are exactly
the rows a lane leaves behind (`docs/QA_FIXTURE_RUNBOOK.md` carries the rule table). The sweep then re-scans and
applies the same rules, because a `delete_item` that returned without an error is not evidence, and prints
`LEFT` for a lane row it did not take. A table the fixture identity cannot read is printed as
`BLOCKED <table>: …` and fails the sweep: measured on dev on 2026-11-19, `kernelworx-qa-ue1-dev` is denied
`dynamodb:Scan` on `kernelworx-inventory-ue1-dev`, `kernelworx-orders-ue1-dev` and
`kernelworx-order-fulfillments-ue1-dev`, and no `iam:` call that would read or change its own policies is granted
either, so no lane run can wait on a grant. Checklist §2.8.7 as amended (WORK-162, Amendment B) therefore accepts
those three tables as residue the record must *name*: the lane counts its own rows in them through the
application's reads (`inventoryPositions`, `scoutCustodyBalances`, `inventoryMovements`,
`unitScoutCampaignOrders`, `orderFulfillments`) before the teardown and the sweep hide them, and a blocked table no
read answers is reported as residue nobody can prove and stays blocked
(`docs/QA_FIXTURE_RUNBOOK.md`, "Known gap: which tables the sweep can even read").

**The canary is a second lane, not a second campaign.** Acceptance item 5 asks for proof that *another lane's*
data is untouched, and a campaign this run made for show proves nothing: this run's sweep is free to define it
out of the set. So the run first builds a whole second lane under its own `DATA_ID` (`stage2can-<digits>`, never a string that contains the lane's own id) — Unit,
Unit Campaign, seller profile, Scout Campaign, roster join — seeds it with a receipt, a custody issue and a
sale, snapshots it, and only then starts the acceptance lane. After the acceptance lane's teardown the snapshot
has to answer identically: position rows, movement row count, Orders with their real line quantities,
fulfillment records, custody, roster status and the Unit Campaign's `isActive` — the last because the teardown's
closing step is a deactivation, and a deactivation of a campaign this run does not own would otherwise read as an
untouched canary. An order quantity the query never selected reads as missing, and `or 0` turns that into a
number, so the snapshot sums the `lineItems` the document does select and refuses an Order that answers none. The same teardown and the same sweep are then pointed at the canary's own ids, so the
record also shows a whole lane's rows being removed when the sweeper is told to remove them.

**Not every clause of §2.8.5 is executable yet.** The raw-data half names
`unitCampaignOrderLines` / `scoutCampaignOrderLines` (§2.5) and the §6 reporting reads, which the
shipped SDL does not carry. The run reads `__schema` before it builds anything and reports the
Stage 2 fields the deployed API answers, so a build that is missing them cannot read as a pass.

---

## Structure

```
tests/e2e/
├── conftest.py               # Session fixtures; test-user loading; post-suite cleanup; recording retention
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
