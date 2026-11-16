"""Show & Sell Stage 1 journey, driven end to end against a deployed stack.

This is the regression harness for the Stage 1 journey (§1.8.4 of
``docs/specs/show_sell/SHOW_AND_SELL_DELIVERY_CHECKLIST.md``): the preview gate
both ways, Unit creation, invite and redemption, Unit Campaign with its join
code, Scout join, roster removal and Unit Campaign close, plus the server-side
refusal for an account that holds no Unit grant.  It runs in a real browser
against the deployed app with the standing QA fixture identities and writes
everything it observes into one artifact directory
(``SS_ACCEPTANCE_EVIDENCE_DIR``): per-step screenshots, one Playwright trace per
persona session, and ``evidence.json`` / ``evidence.md``.

What it deliberately is not: QA's verdict.  QA executes the acceptance criteria
itself, against the deployed environment.  This file is what makes that journey
re-runnable in one command, and what shows a re-run what the deployed build
answered.

Identities come from the environment — the standing fixture
``qa-show-sell-{admin,admin2,scout,outside}@dev.kernelworx.app`` — and this spec
never creates, resets, or deletes a user.  The fixture has one owner:
``scripts/qa_fixture.py``, which WORK-201 is bringing into the repository.  Until
that lands the identities still exist on the dev pool, and this spec only reads
them.  A second way to provision the same identities is how the dev pool
collected eighteen app clients named ``KernelWorx-Web``.

Persona roles:

* ``admin`` — gate open; creates the Unit, its invite, and the Unit Campaign
  with its join code; reads the roster, removes the Scout, closes the campaign,
  and revokes the second admin grant on the way out.
* ``admin2`` — redeems the invite and becomes a second Unit admin.
* ``scout`` — holds the catalog, Scout profile, and Scout Campaign the join
  needs; joins the Unit Campaign by code and appears on the roster.
* ``outside`` — never joins.  It is the closed half of the gate and the
  server-side refusal for an account with no Unit grant.

Sharp edges this module has to respect:

* **The preview gate covers ``/show-sell/join``, not only the admin screens.**
  ``frontend/src/ShowSellRoutes.tsx`` gates the whole route tree, so the Scout
  persona must hold the ``show-sell-preview`` group or the join step cannot open
  its own page.  ``outside`` is what carries the closed half of the assertion.
* **One persona session at a time.**  Each session is its own ``BrowserContext``,
  which is what keeps four authenticated sessions apart; sessions are opened in
  the order the journey needs them rather than nested, so no step depends on
  bringing a background tab forward.
* **Tracing starts *after* login.**  A Playwright trace records request and
  response bodies, and the login flow posts the Cognito password to the user
  pool: a trace that covers login puts a password in an uploaded artifact.
  Fixture codes (the Unit invite and the Unit Campaign join code) are masked in
  screenshots and redacted inside traces by
  :func:`tests.e2e.utils.show_sell_evidence.redact_and_scan`, which fails the run
  if any password survived anywhere.
* **One origin drives both halves of the run.**  The page objects navigate
  ``E2E_BASE_URL`` (default: a local Vite server) while the GraphQL probes read
  ``TEST_QA_SHOW_SELL_BASE_URL``.  The session fixture :func:`target_origin`
  publishes the resolved origin into ``E2E_BASE_URL`` before anything navigates,
  so a run that sets only the card's variable drives the deployed app with a
  browser and with queries.  Without it, the browser opens ``localhost:5173`` and
  the journey stops before step 1.
* This spec never uses the ``page`` fixture, and it overrides the session-scoped
  ``global_setup``/``global_cleanup`` fixtures from ``tests/e2e/conftest.py``:
  it creates no shared-persona data, and that cleanup would be the only reason
  this run needs DynamoDB write credentials it never otherwise uses.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import time
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, BrowserContext, Locator, Page

from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.catalogs_page import CatalogsPage
from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.show_sell_page import JOIN_ROUTE, UNIT_ROUTE, ShowSellPage, code_mask_locators, profile_key
from tests.e2e.utils import show_sell_evidence as artifacts
from tests.e2e.utils import show_sell_graphql as api
from tests.e2e.utils.auth import login

pytestmark = pytest.mark.slow

# Fixture data from SHOW_AND_SELL_SMOKE_TEST_PLAN.md §2.1, suffixed with the
# run's DATA_ID so a re-run never reads another run's rows.  The identities
# themselves are standing fixture accounts; only the rows they hold here are
# per-run.
UNIT_TYPE = "Pack"
UNIT_CITY = "Denver"
UNIT_STATE = "CO"
CAMPAIGN_YEAR = "2026"
SCOUT_NAME_TEMPLATE = "Avery Scout {data_id}"
ADMIN_CATALOG_TEMPLATE = "Smoke Popcorn Catalog {data_id}"
SCOUT_CATALOG_TEMPLATE = "Smoke Popcorn Scout Catalog {data_id}"
CAMPAIGN_TEMPLATE = "Fall Popcorn 2026 {data_id}"
PRODUCTS: list[dict[str, object]] = [
    {"productName": "Caramel", "price": 30.0},
    {"productName": "Butter", "price": 20.0},
    {"productName": "Chocolate", "price": 25.0},
]


def _data_id() -> str:
    """Return the run's DATA_ID, or the one the caller pinned.

    A pinned id is what lets a re-run reuse the fixture rows a previous run
    created; a generated one is what keeps an unattended run from reading another
    run's rows.
    """
    pinned = os.environ.get("SS_DATA_ID", "").strip()
    if pinned:
        return pinned
    return datetime.datetime.now(datetime.timezone.utc).strftime("%m%d%H%M%S")


def _unit_number(data_id: str) -> str:
    """Return a Unit number this run can own.

    A Unit's tenant key is type + number + city + state, so the number has to vary
    per run: a fixed one collides with the Unit a previous run left on dev, and the
    duplicate-confirm path that would resolve it does not open in the shipped UI
    (see :func:`lane`).  The schema's ``unitNumber`` is an ``Int`` and the create
    form demands a whole number at least 1, so the value is the tail of the
    DATA_ID's digits — a UTC timestamp, so unique per run and inside range.  A
    pinned DATA_ID with too few digits falls back to a digest of itself, which
    keeps the promise that pinning an id reuses the same rows.
    """
    digits = "".join(character for character in data_id if character.isdigit())
    if len(digits) >= 4:
        return str(int(digits[-9:]))
    return str(zlib.crc32(data_id.encode("utf-8")) % 900_000_000 + 100_000_000)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def global_setup() -> Iterator[None]:
    """Skip the shared-persona pre-suite cleanup for this run.

    Overrides the autouse fixture of the same name in ``tests/e2e/conftest.py``.
    This suite creates only fixture-persona data; running the shared cleanup
    would add a credential requirement and could disturb rows other suites own.
    """
    yield


@pytest.fixture(scope="session", autouse=True)
def global_cleanup() -> Iterator[None]:
    """Skip the shared-persona post-suite cleanup; this run cleans up in-test."""
    yield


@pytest.fixture(scope="session", autouse=True)
def target_origin() -> str:
    """Publish the deployment origin before any browser touches it.

    The GraphQL helper reads ``TEST_QA_SHOW_SELL_BASE_URL``, but the page objects
    navigate whatever ``E2E_BASE_URL`` holds and fall back to a local Vite server
    when it is unset.  Writing the resolved origin here is what lets a lane that
    holds only the card's variables run the documented command and drive the
    deployed app, rather than opening a browser at ``localhost:5173`` and stopping
    before the first step.
    """
    return api.publish_base_url()


@pytest.fixture(scope="session")
def identities() -> dict[str, dict[str, str]]:
    """Return the four standing fixture identities, read from the environment."""
    return api.qa_identities()


@pytest.fixture(scope="session")
def lane() -> dict[str, str]:
    """Return the DATA_ID-suffixed row names for this run.

    The Unit number is part of this set rather than a constant: a Unit's tenant
    key is type + number + city + state, so a fixed number collides with the Unit
    a previous run left on dev.  The collision is answerable only through the
    "A Unit with these details already exists" confirm, and that confirm does not
    open in the shipped UI today — ``createUnit`` reports the duplicate as a plain
    ``INVALID_INPUT`` with no ``details``, while
    ``frontend/src/lib/units.ts:isDuplicateUnitError`` keys off
    ``details.subcode`` and its fallback reads ``extensions`` rather than
    AppSync's top-level ``errorType``.  So the harness varies the key, and
    ``create_unit`` still takes the confirm if the shipped build ever answers it.
    """
    data_id = _data_id()
    return {
        "data_id": data_id,
        "unit_number": _unit_number(data_id),
        "unit_display_name": f"Denver-{data_id}",
        "campaign_name": CAMPAIGN_TEMPLATE.format(data_id=data_id),
        "scout_name": SCOUT_NAME_TEMPLATE.format(data_id=data_id),
        "admin_catalog": ADMIN_CATALOG_TEMPLATE.format(data_id=data_id),
        "scout_catalog": SCOUT_CATALOG_TEMPLATE.format(data_id=data_id),
    }


@pytest.fixture(scope="session")
def evidence_dir(lane: dict[str, str]) -> Path:
    """Return a clean artifact directory for this run.

    Wiped on purpose: an artifact left over from an earlier run is the one thing
    that can make a failed journey look like it reached a step it never did.
    """
    path = Path(os.environ.get("SS_ACCEPTANCE_EVIDENCE_DIR", f"test-results/show-sell-{lane['data_id']}"))
    if path.is_dir():
        for stale in path.rglob("*"):
            if stale.is_file():
                stale.unlink()
    path.mkdir(parents=True, exist_ok=True)
    print(f"show & sell acceptance record: {path.resolve()}")
    return path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _screenshot(page: Page, name: str, evidence_dir: Path, masks: list[Locator]) -> str:
    """Capture one step screenshot and return its file name.

    Args:
        page: the page to capture.
        name: step name, used as the file stem.
        evidence_dir: artifact directory.
        masks: locators whose pixels are replaced.  Required on purpose: the
            evidence directory outlives the run, and any screenshot of a Unit
            Campaign page shows its live 16-character join code
            (``frontend/src/pages/UnitCampaignWorkspacePage.tsx:138``), which no
            text scan can take back out of pixels.

    Returns:
        The screenshot's file name.
    """
    path = evidence_dir / f"{name}.png"
    page.screenshot(path=str(path), full_page=True, mask=masks)
    return path.name


def _masked_code_elements(page: Page) -> int:
    """Count the fixture-code elements on screen that a screenshot is masking.

    The record claims fixture codes are absent from the evidence, and pixels are
    the one channel no after-the-fact scan can redact.  Saying how many code
    elements were on screen is what makes that claim checkable: a step on a Unit
    Campaign page reports a non-zero count, so an unmasked screenshot there
    cannot hide behind a mask list that matched nothing.

    Args:
        page: the persona's page, at the moment its screenshot was taken.

    Returns:
        How many elements the mask list matched.
    """
    return sum(locator.count() for locator in code_mask_locators(page))


@contextlib.contextmanager
def _persona_session(
    browser: Browser,
    label: str,
    identity: dict[str, str],
    evidence_dir: Path,
) -> Iterator[tuple[Page, str]]:
    """Open one authenticated context for one persona, tracing from login on.

    A stopped step also gets a screenshot and the page's own error text: the
    assertion says what was expected, only the page says what it answered, and
    without that the next reader re-runs the journey to find out.

    Args:
        browser: the session browser.
        label: names this session's trace and failure files, e.g. ``03-admin``.
        identity: the persona's ``{"email": ..., "password": ...}`` pair.
        evidence_dir: artifact directory.

    Yields:
        A ``(page, id_token)`` pair: the page for browser steps, the ID token for
        the server-side assertions made with the same identity.
    """
    context: BrowserContext = browser.new_context(viewport={"width": 1280, "height": 1000})
    page = context.new_page()
    tracing = False
    try:
        login(page, identity["email"], identity["password"])
        token = api.sign_in(identity["email"], identity["password"], api.client_id(), api.region())
        context.tracing.start(title=f"show-sell-{label}", screenshots=True, snapshots=True, sources=False)
        tracing = True
        yield page, token
    except Exception as exc:
        _record_failure(page, label, exc, evidence_dir)
        raise
    finally:
        if tracing:
            with contextlib.suppress(Exception):
                context.tracing.stop(path=str(evidence_dir / f"trace-{label}.zip"))
        context.close()


def _record_failure(page: Page, label: str, exc: Exception, evidence_dir: Path) -> None:
    """Write what the page showed at the moment *label* stopped.

    The screenshot carries the same code masks as the step screenshots.  A step
    most often stops while it is waiting on something the code it just read was
    supposed to make true, so an unmasked failure shot is the likeliest artifact
    to photograph a live 16-character invite or join code — and pixels survive
    :func:`tests.e2e.utils.show_sell_evidence.redact_and_scan`, which only reads
    text.

    Args:
        page: the persona's page, still on the step that failed.
        label: the step's label, used as the file stem.
        exc: the exception that ended the step.
        evidence_dir: artifact directory.
    """
    record: dict[str, Any] = {"step": label, "error": f"{type(exc).__name__}: {exc}", "url": page.url}
    with contextlib.suppress(Exception):
        record["alerts"] = page.locator("[role='alert']").all_inner_texts()
        path = evidence_dir / f"failure-{label}.png"
        page.screenshot(path=str(path), full_page=True, mask=code_mask_locators(page))
        record["screenshot"] = path.name
    (evidence_dir / f"failure-{label}.json").write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")


def _token_for(identity: dict[str, str]) -> str:
    """Return a fresh ID token for one persona, without opening a browser.

    The server-side probes run late in the journey, long after the persona's
    browser session closed; signing in again is what makes the probe read the
    state the journey just wrote rather than a token that may have expired.

    Args:
        identity: the persona's ``{"email": ..., "password": ...}`` pair.
    """
    return api.sign_in(identity["email"], identity["password"], api.client_id(), api.region())


def _ensure_catalog(page: Page, name: str) -> str:
    """Return *name*, creating the catalog through the app when it is absent.

    Args:
        page: an authenticated page for the catalog's owner.
        name: catalog name to ensure.

    Returns:
        ``"reused"`` or ``"created"``, for the evidence record.
    """
    catalogs = CatalogsPage(page)
    catalogs.goto()
    catalogs.switch_to_my_catalogs()
    if catalogs.has_catalog(name, timeout=5_000):
        return "reused"
    catalogs.create_catalog(name=name, products=PRODUCTS)
    return "created"


def _ensure_scout_profile(page: Page, name: str) -> str:
    """Return *name*, creating the Scout profile through the app when it is absent.

    Args:
        page: an authenticated page for the profile's owner.
        name: seller name to ensure.

    Returns:
        ``"reused"`` or ``"created"``, for the evidence record.
    """
    dashboard = DashboardPage(page)
    dashboard.goto()
    dashboard.wait_for_loading()
    with contextlib.suppress(Exception):
        dashboard.wait_for_profiles_loaded(timeout=10_000)
    if name in dashboard.get_owned_profile_names():
        return "reused"
    dashboard.create_profile(name)
    return "created"


def _ensure_scout_campaign(page: Page, name: str, profile_id: str) -> str:
    """Return *name*, creating the Scout's own campaign when it is absent.

    A join attaches the Scout's existing campaign to the Unit Campaign, so the
    Scout needs a current campaign before a join code is worth anything.  The
    profile is named by id, not by seller name: a fixture persona persists
    between runs and may hold more than one profile.

    Args:
        page: an authenticated page for the campaign's owner.
        name: campaign name to ensure.
        profile_id: the Scout profile that must own it.

    Returns:
        ``"reused"`` or ``"created"``, for the evidence record.
    """
    campaigns = CampaignPage(page)
    campaigns.goto(profile_id)
    if campaigns.has_campaign(name):
        return "reused"
    campaigns.create_campaign_first_catalog(name, profile_id=profile_id)
    return "created"


def _unit_for_key(token: str, unit_type: str, unit_number: str, city: str, state: str) -> str | None:
    """Return the caller's Unit that already carries this tenant key, if any.

    ``createUnit`` refuses an exact type + number + city + state match with a
    second-intent question, and the shipped UI does not currently surface that
    question (see :func:`lane`).  Recognizing the Unit this run's DATA_ID already
    created is what keeps a pinned re-run moving, and it is a read of the caller's
    own ``myUnits``, so it can never reach another tenant's row.

    Args:
        token: the Unit admin's ID token.
        unit_type: the Unit type this run asks for.
        unit_number: the Unit number this run asks for.
        city: the city this run asks for.
        state: the state this run asks for.
    """
    wanted = int(unit_number)
    for unit in api.my_units(token):
        if (
            str(unit.get("unitType")) == unit_type
            and int(unit.get("unitNumber", 0)) == wanted
            and str(unit.get("city")) == city
            and str(unit.get("state")) == state
        ):
            return str(unit["unitId"])
    return None


def _profile_id_for(token: str, seller_name: str, *, deadline: float = 60.0) -> str:
    """Return the profile id of *seller_name* as the server knows it.

    The read is polled, not taken once: a profile the UI just created is written
    by the app and then read through an index, so the first read can answer
    without it.  Failing on that first answer reports a fixture problem that does
    not exist, so the loop reports the names it does see and gives the row a
    bounded chance to appear.

    Args:
        token: the profile owner's ID token.
        seller_name: the seller name the UI created.
        deadline: how long to keep re-reading, in seconds.

    Returns:
        The profile id.

    Raises:
        AssertionError: if no owned profile carries that name before *deadline*.
    """
    waiter_deadline = time.monotonic() + deadline
    observed: list[str] = []
    while time.monotonic() < waiter_deadline:
        profiles = api.my_profiles(token)
        observed = [str(profile.get("sellerName", "")) for profile in profiles]
        matches = [profile for profile in profiles if profile.get("sellerName") == seller_name]
        if matches:
            return str(matches[0]["profileId"])
        time.sleep(2.0)
    raise AssertionError(
        f"no owned profile named {seller_name!r} appeared within {deadline:.0f}s; this account holds {observed}"
    )


def _account_id_for(token: str) -> str:
    """Return the caller's own account id.

    Args:
        token: the caller's ID token.
    """
    data = api.gql(token, "query { getMyAccount { accountId } }")
    return str((data.get("getMyAccount") or {}).get("accountId") or "")


def _refuse_without_a_grant(token: str, unit_id: str, unit_campaign_id: str) -> dict[str, Any]:
    """Probe the Unit reads with an account that holds no grant.

    Each probe is read as a whole response rather than through a raising helper:
    a refusal is the expected answer, and the evidence has to say which form it
    took (an error, or a null with no data).  The error code is recorded wherever
    the resolver happened to put it — see :func:`tests.e2e.utils.show_sell_graphql.error_summaries`.

    Args:
        token: an authenticated caller with no Unit grant.
        unit_id: a Unit the caller must not read.
        unit_campaign_id: a Unit Campaign whose roster must not be readable.

    Returns:
        The evidence record: what each read answered.
    """
    units = api.gql_raw(token, "query { myUnits(page: {limit: 50}) { items { unitId } } }")
    unit = api.gql_raw(
        token,
        "query Unit($unitId: ID!) { unit(unitId: $unitId) { unitId unitType } }",
        {"unitId": unit_id},
    )
    roster = api.gql_raw(
        token,
        "query Roster($unitCampaignId: ID!) { unitCampaignRoster(unitCampaignId: $unitCampaignId) { items { profileId } } }",
        {"unitCampaignId": unit_campaign_id},
    )
    return {
        "myUnits": [str(item["unitId"]) for item in ((units.get("data") or {}).get("myUnits") or {}).get("items", [])],
        "myUnitsErrors": api.error_summaries(units),
        "unit": {"data": (unit.get("data") or {}).get("unit"), "errors": api.error_summaries(unit)},
        "unitCampaignRoster": {
            "data": (roster.get("data") or {}).get("unitCampaignRoster"),
            "errors": api.error_summaries(roster),
        },
    }


def _active_roster_rows(token: str, unit_campaign_id: str) -> list[dict[str, Any]]:
    """Return the ACTIVE roster rows on a Unit Campaign.

    Args:
        token: a Unit admin's ID token.
        unit_campaign_id: the Unit Campaign to read.
    """
    return [row for row in api.unit_campaign_roster(token, unit_campaign_id) if row.get("status") == "ACTIVE"]


def _roster_after_removal(
    token: str, unit_campaign_id: str, profile_id: str, *, deadline: float = 60.0
) -> list[dict[str, Any]]:
    """Return the roster once the server reports *profile_id* as no longer ACTIVE.

    The removal writes the membership row and the read goes through an index, so an
    immediate read can still answer the old status — which would read as a removal
    that never happened.  The rows are re-read until that profile has no ACTIVE row,
    and the failure names the statuses that were actually seen.

    Args:
        token: a Unit admin's ID token.
        unit_campaign_id: the Unit Campaign whose roster is read.
        profile_id: the profile whose removal is awaited.
        deadline: how long to keep re-reading, in seconds.

    Returns:
        The roster rows, removed history included.

    Raises:
        AssertionError: if *profile_id* keeps an ACTIVE row until *deadline*.
    """
    wanted = profile_key(profile_id)
    waiter_deadline = time.monotonic() + deadline
    rows: list[dict[str, Any]] = []
    while time.monotonic() < waiter_deadline:
        rows = api.unit_campaign_roster(token, unit_campaign_id)
        mine = [row for row in rows if profile_key(str(row.get("profileId", ""))) == wanted]
        if mine and all(str(row.get("status")) != "ACTIVE" for row in mine):
            return rows
        time.sleep(2.0)
    raise AssertionError(
        f"the roster never dropped {profile_id!r} from ACTIVE within {deadline:.0f}s; "
        f"this is what it answers: {[(row.get('profileId'), row.get('status')) for row in rows]}"
    )


def _await_grants_without(
    token: str, unit_id: str, revoked_account_ids: list[str], *, deadline: float = 60.0
) -> list[dict[str, Any]]:
    """Return the Unit's grants once none of *revoked_account_ids* holds one.

    The grant table is read through an index, so a revocation that succeeded can
    still be listed — and a teardown that leaves a second admin in place is exactly
    what this journey is supposed to catch, so it gets the same bounded re-read as
    every other write here.

    Args:
        token: a Unit admin's ID token.
        unit_id: the Unit whose grants are read.
        revoked_account_ids: the grants this run revoked.
        deadline: how long to keep re-reading, in seconds.

    Returns:
        The grant rows as the server answers them.

    Raises:
        AssertionError: naming the grants still present when *deadline* passes.
    """
    revoked = {artifacts.bare_account_id(account) for account in revoked_account_ids}
    waiter_deadline = time.monotonic() + deadline
    rows: list[dict[str, Any]] = []
    while time.monotonic() < waiter_deadline:
        rows = api.unit_admins(token, unit_id)
        present = {artifacts.bare_account_id(str(row.get("accountId", ""))) for row in rows}
        if not (present & revoked):
            return rows
        time.sleep(2.0)
    raise AssertionError(
        f"these grants were still listed within {deadline:.0f}s of being revoked: {sorted(revoked)}; "
        f"the table answers {sorted(present)}"
    )


def _write_evidence(evidence_dir: Path, evidence: dict[str, Any]) -> None:
    """Write the machine-readable and human-readable evidence records.

    Args:
        evidence_dir: artifact directory.
        evidence: the collected facts, one entry per journey step.
    """
    (evidence_dir / "evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Show & Sell Stage 1 journey — harness record",
        "",
        "A re-runnable record of what the deployed build answered.  This is not the",
        "acceptance verdict: QA executes the criteria itself.  See the runbook in",
        "`tests/e2e/README.md` for how to run it.",
        "",
        f"- DATA_ID: `{evidence['dataId']}`",
        f"- Base URL: `{evidence['baseUrl']}`",
        f"- Browser origin: `{evidence['browserOrigin'] or 'unset — the page objects would have driven localhost'}`",
        f"- User pool: `{evidence['poolId'] or 'not configured'}` ({evidence['region']})",
        f"- Preview group: `{evidence['previewGroup']}`",
        f"- Identities: {', '.join(f'`{email}`' for email in evidence['identities'])}",
        "",
        "Ordering: the closed half of the gate is read from `outside`, which never",
        "joins anything, and the open half from the three personas that do.  The Scout",
        "holds the preview group because the gate covers `/show-sell/join` as well as",
        "the admin screens; the grant-denial probe runs last, against the Unit this run",
        "created.",
        "",
        "Fixture codes (the Unit invite and the Unit Campaign join code) are deliberately",
        "absent: the checklist requires that they do not appear in evidence.  Every screenshot",
        "passes the page object's code-mask selectors, and `maskedCodeElements` on a step is",
        "how many of those surfaces were on screen and painted out; traces carry same-length",
        "redactions in their place.",
        "",
    ]
    for step in evidence["steps"]:
        lines.append(f"## {step['order']}. {step['name']}")
        lines.append(f"- Result: {step['result']}")
        for key, value in step["facts"].items():
            lines.append(f"- {key}: `{value}`")
        lines.append("")
    if evidence.get("stopped"):
        lines += [
            "## Stopped",
            f"- After: `{evidence['stopped']['lastStep'] or 'no step recorded'}`",
            f"- Error: `{evidence['stopped']['error']}`",
            "- A `failure-<step>.png` and `failure-<step>.json` pair holds what the page showed.",
            "",
        ]
    lines += [
        "## What is left behind, and why",
        f"- {evidence['leftBehind']['what']}",
        f"- {evidence['leftBehind']['reason']}",
        "",
    ]
    (evidence_dir / "evidence.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Journey
# ---------------------------------------------------------------------------


def test_show_sell_stage1_journey(
    browser: Browser,
    identities: dict[str, dict[str, str]],
    lane: dict[str, str],
    evidence_dir: Path,
) -> None:
    """Run the Stage 1 journey end to end and record what each step answered.

    Args:
        browser: the session Playwright browser.
        identities: the standing fixture identities.
        lane: DATA_ID-suffixed row names for this run.
        evidence_dir: artifact directory for this run.
    """
    steps: list[dict[str, Any]] = []
    codes: list[str] = []
    passwords: list[str] = [identity["password"] for identity in identities.values()]
    created: dict[str, str] = {}
    stopped: dict[str, Any] | None = None

    def record(name: str, result: str, facts: dict[str, Any]) -> None:
        """Append one journey step to the record."""
        steps.append({"order": len(steps) + 1, "name": name, "result": result, "facts": facts})

    try:
        # --- Step 1: the gate is closed for `outside`, which holds no group ----
        with _persona_session(browser, "01-outside", identities["outside"], evidence_dir) as (outside_page, _):
            outside = ShowSellPage(outside_page)
            units_closed = not outside.gate_opens(UNIT_ROUTE, "create-unit")
            join_closed = not outside.gate_opens(JOIN_ROUTE, "lookup-join-code")
            shot = _screenshot(outside_page, "01-gate-closed-outside", evidence_dir, masks=outside.code_mask_locators())
            assert units_closed, "the units route opened for an account outside the preview group"
            assert join_closed, "the join route opened for an account outside the preview group"
            record(
                "Preview gate refuses an account outside the group",
                "passed",
                {"unitsRouteClosed": units_closed, "joinRouteClosed": join_closed, "screenshot": shot},
            )

        # --- Step 2: the Scout's fixtures, and its gate is open ---------------
        # The join attaches a Scout Campaign that already exists, so the Scout's
        # own catalog, profile, and campaign are arranged before any code exists.
        with _persona_session(browser, "02-scout", identities["scout"], evidence_dir) as (scout_page, scout_token):
            scout = ShowSellPage(scout_page)
            join_open = scout.gate_opens(JOIN_ROUTE, "lookup-join-code")
            assert join_open, (
                "the join route is closed for the Scout: the preview gate covers /show-sell/join "
                "(frontend/src/ShowSellRoutes.tsx), so the fixture Scout must hold show-sell-preview"
            )
            scout_catalog_state = _ensure_catalog(scout_page, lane["scout_catalog"])
            profile_state = _ensure_scout_profile(scout_page, lane["scout_name"])
            scout_profile_id = _profile_id_for(scout_token, lane["scout_name"])
            campaign_state = _ensure_scout_campaign(scout_page, lane["campaign_name"], scout_profile_id)
            shot = _screenshot(scout_page, "02-scout-fixtures", evidence_dir, masks=scout.code_mask_locators())
            record(
                "The Scout holds the preview gate and the fixtures the join needs",
                "passed",
                {
                    "joinRouteOpened": join_open,
                    "scoutCatalog": scout_catalog_state,
                    "scoutProfile": f"{lane['scout_name']} ({profile_state})",
                    "scoutCampaign": f"{lane['campaign_name']} ({campaign_state})",
                    "scoutProfileId": scout_profile_id,
                    "screenshot": shot,
                },
            )

        # --- Step 3: the admin creates the Unit, invite, and Unit Campaign ----
        with _persona_session(browser, "03-admin", identities["admin"], evidence_dir) as (admin_page, admin_token):
            admin = ShowSellPage(admin_page)
            units_open = admin.gate_opens(UNIT_ROUTE, "create-unit")
            assert units_open, "the units route did not open for an account inside the preview group"
            admin_catalog_state = _ensure_catalog(admin_page, lane["admin_catalog"])

            # The catalog step navigated away, so return to the Unit list before
            # using its controls.
            admin.goto_units()
            existing_unit = _unit_for_key(admin_token, UNIT_TYPE, lane["unit_number"], UNIT_CITY, UNIT_STATE)
            if existing_unit:
                unit_id, duplicate_confirm_taken, unit_creation = existing_unit, False, "reused"
            else:
                unit_id, duplicate_confirm_taken = admin.create_unit(
                    unit_type=UNIT_TYPE,
                    unit_number=lane["unit_number"],
                    city=UNIT_CITY,
                    state=UNIT_STATE,
                    display_name=lane["unit_display_name"],
                )
                unit_creation = "separate-duplicate" if duplicate_confirm_taken else "created"
            created["unitId"] = unit_id
            admin.open_unit(unit_id)
            admin.open_tab("tab-settings")
            shot = _screenshot(admin_page, "03-unit-created", evidence_dir, masks=admin.code_mask_locators())
            record(
                "The gate opens for the admin, who creates the Unit",
                "passed",
                {
                    "unitsRouteOpened": units_open,
                    "adminCatalog": admin_catalog_state,
                    "unitId": unit_id,
                    "unit": f"{UNIT_TYPE} {lane['unit_number']}, {UNIT_CITY}, {UNIT_STATE}",
                    "displayName": lane["unit_display_name"],
                    "unitCreation": unit_creation,
                    "duplicateConfirmTaken": duplicate_confirm_taken,
                    "screenshot": shot,
                },
            )

            admin.open_tab("tab-access")
            invite_code = admin.create_invite()
            codes.append(invite_code)
            shot = _screenshot(admin_page, "04-invite-created", evidence_dir, masks=admin.code_mask_locators())
            record(
                "The admin creates a Unit invite",
                "passed",
                {
                    "maskedCodeElements": _masked_code_elements(admin_page),
                    "inviteCode": "redacted, 16 characters",
                    "inviteCodeLength": len(invite_code),
                    "screenshot": shot,
                },
            )

            admin.open_tab("tab-campaigns")
            campaign_id, join_code = admin.create_campaign(
                name=lane["campaign_name"],
                year=CAMPAIGN_YEAR,
                catalog_name=lane["admin_catalog"],
            )
            created["unitCampaignId"] = campaign_id
            codes.append(join_code)
            status_after_create = admin.wait_for_campaign_status(campaign_id, "Active")
            shot = _screenshot(admin_page, "05-unit-campaign-created", evidence_dir, masks=admin.code_mask_locators())
            assert status_after_create == "Active", f"a new Unit Campaign should be Active, got {status_after_create!r}"
            record(
                "The admin creates the Unit Campaign on a fixed catalog",
                "passed",
                {
                    "maskedCodeElements": _masked_code_elements(admin_page),
                    "unitCampaignId": campaign_id,
                    "campaign": f"{lane['campaign_name']} {CAMPAIGN_YEAR}",
                    "catalog": lane["admin_catalog"],
                    "statusAfterCreate": status_after_create,
                    "joinCode": "redacted, 16 characters",
                    "joinCodeLength": len(join_code),
                    "screenshot": shot,
                },
            )

        # --- Step 4: the second admin redeems the invite ----------------------
        with _persona_session(browser, "04-admin2", identities["admin2"], evidence_dir) as (admin2_page, _):
            admin2 = ShowSellPage(admin2_page)
            admin2.goto_units()
            admin2.redeem_invite(invite_code)
            admin2_page.get_by_test_id(f"open-unit-{unit_id}").wait_for(state="visible", timeout=20_000)
            shot = _screenshot(
                admin2_page, "06-invite-redeemed-admin2", evidence_dir, masks=admin2.code_mask_locators()
            )
            record(
                "The second admin redeems the invite and becomes a Unit admin",
                "passed",
                {"unitVisibleToAdmin2": unit_id, "redeemConfirmationVisible": True, "screenshot": shot},
            )

        # --- Step 5: the Scout joins with its own profile ---------------------
        with _persona_session(browser, "05-scout-join", identities["scout"], evidence_dir) as (scout_page, _):
            scout = ShowSellPage(scout_page)
            scout.goto_join()
            scout.join_unit_campaign(join_code, scout_profile_id)
            shot = _screenshot(scout_page, "07-scout-joined", evidence_dir, masks=scout.code_mask_locators())
            record(
                "The Scout joins the Unit Campaign with the Scout profile",
                "passed",
                {
                    "maskedCodeElements": _masked_code_elements(scout_page),
                    "scoutProfileId": scout_profile_id,
                    "joinConfirmationVisible": True,
                    "screenshot": shot,
                },
            )

        # --- Step 6: roster, roster removal, close, then teardown -------------
        with _persona_session(browser, "06-admin-teardown", identities["admin"], evidence_dir) as (
            admin_page,
            admin_token,
        ):
            admin = ShowSellPage(admin_page)
            admin.goto_units()
            admin.open_unit(unit_id)
            admin.open_tab("tab-campaigns")
            admin.open_campaign_roster(campaign_id)
            roster_rows = admin.wait_for_roster_row(scout_profile_id)
            active_before_removal = _active_roster_rows(admin_token, campaign_id)
            shot = _screenshot(admin_page, "08-roster-shows-scout", evidence_dir, masks=admin.code_mask_locators())
            assert any(profile_key(row) == profile_key(scout_profile_id) for row in roster_rows), (
                f"the roster does not list {scout_profile_id}: {roster_rows}"
            )
            record(
                "The roster lists the joined Scout",
                "passed",
                {
                    "maskedCodeElements": _masked_code_elements(admin_page),
                    "rosterRows": roster_rows,
                    "activeRosterRows": len(active_before_removal),
                    "screenshot": shot,
                },
            )

            roster_row = admin.remove_roster_member(scout_profile_id)
            status_after_removal = admin.wait_for_roster_removal(scout_profile_id)
            still_removable = admin.roster_can_remove(scout_profile_id)
            rows_after_removal = _roster_after_removal(admin_token, campaign_id, scout_profile_id)
            active_after_removal = [row for row in rows_after_removal if row.get("status") == "ACTIVE"]
            removed_rows = [row for row in rows_after_removal if row.get("status") == "REMOVED"]
            shot = _screenshot(admin_page, "09-roster-removal", evidence_dir, masks=admin.code_mask_locators())
            assert not still_removable, "the removed row still offers a removal control"
            assert not active_after_removal, f"the roster still holds ACTIVE rows: {active_after_removal}"
            assert any(
                profile_key(str(row.get("profileId"))) == profile_key(scout_profile_id) for row in removed_rows
            ), f"removal left no REMOVED history row for {scout_profile_id}: {rows_after_removal}"
            record(
                "The admin removes the Scout from the roster",
                "passed",
                {
                    "maskedCodeElements": _masked_code_elements(admin_page),
                    "activeRowsBeforeRemoval": len(active_before_removal),
                    "rosterStatusAfterRemoval": status_after_removal,
                    "activeRowsAfterRemoval": len(active_after_removal),
                    "removedHistoryRows": len(removed_rows),
                    "removedRow": roster_row,
                    "removedHistoryStillListed": True,
                    "screenshot": shot,
                },
            )

            # The roster lives on the Unit Campaign's own page.  Going back to the
            # Unit workspace is what makes the campaigns and access tabs reachable
            # again for the close and the teardown.
            admin.goto_unit(unit_id)
            admin.open_tab("tab-campaigns")
            status_after_close = admin.campaign_status(campaign_id)
            if status_after_close != "Closed":
                admin.close_campaign(campaign_id)
            status_after_close = admin.wait_for_campaign_status(campaign_id, "Closed")
            shot = _screenshot(admin_page, "10-campaign-closed", evidence_dir, masks=admin.code_mask_locators())
            assert status_after_close == "Closed", f"the Unit Campaign did not close: {status_after_close!r}"
            record(
                "The admin closes the Unit Campaign",
                "passed",
                {
                    "maskedCodeElements": _masked_code_elements(admin_page),
                    "statusAfterClose": status_after_close,
                    "screenshot": shot,
                },
            )

            admin.open_tab("tab-access")
            grants = admin.admin_account_ids()
            admin_account_id = artifacts.bare_account_id(_account_id_for(admin_token))
            other_grants = [account for account in grants if artifacts.bare_account_id(account) != admin_account_id]
            assert other_grants, f"the second admin's grant is not in the grant table: {grants}"
            grants_after = grants
            for account_id in other_grants:
                admin.revoke_admin_grant(account_id)
                grants_after = admin.wait_for_admin_grant_gone(account_id)
            server_grants = _await_grants_without(admin_token, unit_id, other_grants)
            alerts = admin_page.locator("[role='alert']").all_inner_texts()
            shot = _screenshot(admin_page, "11-grants-after-teardown", evidence_dir, masks=admin.code_mask_locators())
            assert len(grants_after) < len(grants), f"revoking {other_grants} left the grant table at {grants_after}"
            record(
                "Teardown revokes the second admin grant",
                "passed",
                {
                    "grantsBefore": grants,
                    "grantsAfter": grants_after,
                    "serverGrantsAfter": [
                        artifacts.bare_account_id(str(row.get("accountId"))) for row in server_grants
                    ],
                    "accessPanelAlerts": alerts or "none",
                    "activeRosterRowsAfterTeardown": len(active_after_removal),
                    "screenshot": shot,
                },
            )

        # --- Step 7: the account with no grant is refused, server-side --------
        denial = _refuse_without_a_grant(_token_for(identities["outside"]), unit_id, campaign_id)
        assert unit_id not in denial["myUnits"], (
            f"myUnits leaked the Unit to an account with no grant: {denial['myUnits']}"
        )
        assert not denial["unit"]["data"], f"the unit query disclosed Unit {unit_id} to a caller with no grant"
        assert not denial["unitCampaignRoster"]["data"], (
            "the roster query disclosed roster data to a caller with no grant"
        )
        record(
            "An account with no grant is refused Unit data",
            "passed",
            {
                "outsideMyUnits": denial["myUnits"] or "none",
                "myUnitsErrors": denial["myUnitsErrors"] or "none",
                "unitQuery": denial["unit"]["errors"] or "returned no data",
                "rosterQuery": denial["unitCampaignRoster"]["errors"] or "returned no data",
            },
        )
    except Exception as exc:
        # The record has to survive the failure it describes: a stopped journey
        # still says how far it got and what stopped it, which is what turns a
        # re-run into a diagnosis.
        stopped = {"error": f"{type(exc).__name__}: {exc}", "lastStep": steps[-1]["name"] if steps else None}
        raise
    finally:
        _write_evidence(
            evidence_dir,
            {
                "dataId": lane["data_id"],
                "baseUrl": api.base_url(),
                # What the page objects navigated at.  Recording it next to the
                # probe origin is what lets a reader see that both halves of the
                # run drove the same deployment.
                "browserOrigin": os.environ.get("E2E_BASE_URL", ""),
                "poolId": api.pool_id(),
                "region": api.region(),
                "previewGroup": "show-sell-preview",
                "identities": [identity["email"] for identity in identities.values()],
                "lane": lane,
                "steps": steps,
                "stopped": stopped,
                "leftBehind": {
                    "what": (
                        f"Unit {created.get('unitId', 'not created')} and its Unit Campaign "
                        f"{created.get('unitCampaignId', 'not created')}; the fixture Scout profile and its own "
                        "campaign; the two fixture catalogs. Roster rows and the second admin grant are torn down "
                        "by the journey itself, and the Unit Campaign is left Closed."
                    ),
                    "reason": (
                        "Stage 1 ships no Unit or Unit Campaign delete, and catalogs are never deleted by "
                        "product decision. The fixture personas persist between runs and are refreshed by the "
                        "fixture script rather than removed (FIX-AC-09); removing the roster membership and the "
                        "second admin grant is what the application offers, and both are verified above."
                    ),
                },
            },
        )
        redactions = artifacts.redact_and_scan(evidence_dir, passwords=passwords, codes=codes)
        print(f"fixture codes redacted from artifacts: {redactions}")
