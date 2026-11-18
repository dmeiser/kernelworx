"""Show & Sell Stage 2 journey — stock, Scout custody, Order fulfillment — against a deployed stack.

This is §2.8.5 of ``docs/specs/show_sell/SHOW_AND_SELL_DELIVERY_CHECKLIST.md``: ``SS-SM-03``
(stock-only adjustments, no financial side effect), ``SS-SM-04`` (issue, door-to-door sale,
return), ``SS-SM-10`` (the inventory list and both Council Needs numbers), the ``INV-Q`` read-backs,
and ``ORD-API-02-04`` (a sale keeps the scope it was sold in after the Campaign moves).  It drives
the browser for the screens §2.6 ships and asserts the numbers through GraphQL with the same
identities, because the acceptance descriptions are explicit that a visible button is not evidence:
*“Use direct GraphQL calls for both allowed and denied paths.”*

What it deliberately is not: QA's verdict, or a checklist box.  §2.8.5 asks for the run to happen
*after the merge SHA's* ``Deploy Dev`` *run is green*, so a green run of this file is a recorded
observation about the stack it was pointed at — the artifact is ``evidence.md``.

It stops, in words, rather than reporting success, when the stack cannot carry it:

* **No Stage 2 endpoints.**  The run reads ``__schema`` first.  An API that answers none of
  ``recordInventoryReceipt`` / ``inventoryPositions`` / ``issueStockToScout`` skips with
  :data:`tests.e2e.utils.show_sell_stage2_support.MISSING_ENDPOINT_NOTE` and the field names, so a
  pre-Stage-2 build can never read as a pass.
* **Two catalogs.**  ``createOrder`` prices its lines in the Scout Campaign's catalog while Unit
  Campaign inventory keys on the Unit Campaign's own ``catalogId``, so a lane whose Scout Campaign
  sits on another catalog has its custody sale refused with no Order written (AGENTS.md, “A joined
  Scout Campaign and its Unit Campaign can sell from different catalogs”).  The lane creates both
  Campaigns on one catalog and compares the two ids, through the ``scoutCampaignCatalogId`` the
  roster answers, before it sells.

Identities are the standing fixture (``qa-show-sell-{admin,admin2,scout,outside}``), published only
by ``scripts/qa_fixture.py``; this file holds no credential and makes no Cognito admin call.  The
runbook is ``tests/e2e/README.md``.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, BrowserContext, Locator, Page

from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.show_sell_page import (
    ID_TAB_CUSTODY,
    ID_TAB_INVENTORY,
    ID_TAB_ORDERS,
    ShowSellPage,
    code_mask_locators,
    profile_key,
)
from tests.e2e.utils import show_sell_graphql as api
from tests.e2e.utils import show_sell_stage2_support as stage2
from tests.e2e.utils.auth import login
from tests.e2e.utils.show_sell_evidence import redact_and_scan

pytestmark = pytest.mark.slow

UNIT_TYPE = "Pack"
UNIT_CITY = "Denver"
UNIT_STATE = "CO"
CAMPAIGN_YEAR = "2026"

#: The product the lane sells, if the shared catalog carries it.  The lane never invents a product
#: id: balances are keyed ``(unitCampaignId, productId)`` and no product id crosses catalogs
#: (``UNIT-06``), so the id always comes from ``unitCampaignCatalog`` for the Campaign being sold,
#: and this name only decides which of that catalog's products the run prefers so the evidence reads
#: the same way twice.  The smoke plan's scenarios speak in Butter Popcorn; dev's shared catalog
#: carries Caramel Corn, Cheese Popcorn and Microwave Popcorn, and the record names whichever one
#: the run used.
PREFERRED_PRODUCT = "Cheese Popcorn"

#: The balances ``SS-SM-10`` arranges for the traded product: 2 received, 2 issued to the Scout, 3 on
#: order to the Council.  Issuing less than the sale asks for is deliberate — ``ORD-API-02`` is the
#: sale that consumes what the Scout actually carries and stays owing the rest, never a sale that
#: blocks because the Scout is short.  Two received rather than a shelf full is deliberate too: the
#: lane ends with the shelf at zero and a line still owed, so the two Council Needs numbers are
#: non-zero and a reader can see them move, instead of reading two zeroes that any arithmetic would
#: have produced.
RECEIVED_QTY = 2
ISSUED_QTY = 2
ON_ORDER_QTY = 3
SALE_QTY = 4
COUNCIL_FILL = 1
STOCK_FILL = 1

#: A second product, so the return leg has something to return.  ``CONSUME_SCOUT_CUSTODY`` takes
#: everything the Scout carries up to the line quantity, so a sale that leaves an owed line has by
#: construction emptied that Scout's custody for that product — a return of the sold product would
#: be refused for going below zero, which is a real rule (§ INV-M-05) but not the one ``SS-SM-04``
#: step 3 asks to see.  The lane therefore issues and returns a product it never sells.
RETURN_PRODUCT = "Caramel Corn"
RETURN_RECEIVED = 4
RETURN_ISSUED = 2
RETURN_QTY = 1

SCOUT_NAME_TEMPLATE = "Avery Stage2 {data_id}"
CAMPAIGN_TEMPLATE = "Stage 2 Stock {data_id}"
SALE_CUSTOMER = "Taylor Door"


def _data_id() -> str:
    """Return this run's DATA_ID, or the one the caller pinned.

    A pinned id lets a re-run reuse the rows a previous run created, which is the only way to
    re-sell a lane whose sale was refused by the catalog mismatch without building a second Unit; a
    generated one keeps an unattended run out of another run's rows.
    """
    pinned = os.environ.get("SS_DATA_ID", "").strip()
    if pinned:
        return pinned
    return f"stage2-{datetime.datetime.now(datetime.timezone.utc).strftime('%m%d%H%M%S')}"


def _unit_number(data_id: str) -> str:
    """A Unit number this run can own.

    A Unit's tenant key is type + number + city + state, so the number varies per run: a fixed one
    collides with the Unit an earlier acceptance run left on dev, and Stage 1 ships no Unit delete.
    """
    digits = "".join(character for character in data_id if character.isdigit())
    return (digits or "900001")[-6:]


@pytest.fixture(scope="session", autouse=True)
def global_setup() -> None:
    """Skip the pool-wide cleanup the ordinary smoke suite runs before it.

    The Show & Sell lane is named by ``DATA_ID``, and that pass writes DynamoDB and Cognito
    directly, which this run holds no credentials for — the same reason Stage 1 overrides it.
    """
    return None


@pytest.fixture(scope="session", autouse=True)
def global_cleanup() -> None:
    """Skip the pool-wide cleanup after the run, for the same reason as :func:`global_setup`.

    The lane's own teardown is inside the journey: the membership is removed and re-joined, because
    that pair is what ``ORD-API-02-04`` is about.  The rows Stage 2 cannot delete — Unit, Unit
    Campaign, catalog — are the fixture's, and ``scripts/qa_fixture.py down`` is the only
    attribution-safe way to take them, exactly as for Stage 1.
    """
    return None


@pytest.fixture(scope="session", autouse=True)
def target_origin() -> str:
    """Resolve the deployment once and publish it for the page objects."""
    return api.publish_base_url()


@pytest.fixture(scope="session")
def identities() -> dict[str, dict[str, str]]:
    """The standing fixture identities, read from the environment."""
    return api.qa_identities()


@pytest.fixture(scope="session")
def lane() -> dict[str, str]:
    """DATA_ID-suffixed names for this run's lane.

    One catalog serves both Campaigns on purpose: ``createOrder`` prices in the Scout Campaign's
    catalog while Unit Campaign inventory keys on the Unit Campaign's, so the Stage 2 journey only
    runs when they are the same catalog.
    """
    data_id = _data_id()
    return {
        "data_id": data_id,
        "unit_number": _unit_number(data_id),
        "unit_display_name": f"Stage 2 Pack {data_id}",
        "campaign_name": CAMPAIGN_TEMPLATE.format(data_id=data_id),
        "scout_name": SCOUT_NAME_TEMPLATE.format(data_id=data_id),
    }


@pytest.fixture(scope="session")
def evidence_dir(lane: dict[str, str]) -> Path:
    """Artifact directory for this run."""
    configured = os.environ.get("SS_ACCEPTANCE_EVIDENCE_DIR", "").strip()
    path = Path(configured) if configured else Path("test-results") / f"show-sell-stage2-{lane['data_id']}"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Screenshots, failures, sessions — the Stage 1 conventions, on the Stage 2 screens
# ---------------------------------------------------------------------------


def _screenshot(page: Page, name: str, evidence_dir: Path, masks: list[Locator]) -> str:
    """Capture one step screenshot and return its file name.

    Args:
        page: the page to capture.
        name: step name, used as the file stem.
        evidence_dir: artifact directory.
        masks: locators whose pixels are replaced.  Required on purpose: the Unit Campaign
            workspace renders its live join code on every tab, the Stage 2 ones included, and
            pixels survive a text scan (:meth:`tests.e2e.pages.show_sell_page.ShowSellPage.code_mask_locators`).

    Returns:
        The screenshot's file name.
    """
    path = evidence_dir / f"{name}.png"
    page.screenshot(path=str(path), full_page=True, mask=masks)
    return path.name


def _record_failure(page: Page, label: str, exc: Exception, evidence_dir: Path) -> None:
    """Write what the page showed at the moment *label* stopped, with the same code masks."""
    record: dict[str, Any] = {"step": label, "error": f"{type(exc).__name__}: {exc}", "url": page.url}
    with contextlib.suppress(Exception):
        record["alerts"] = page.locator("[role='alert']").all_inner_texts()
        path = evidence_dir / f"failure-{label}.png"
        page.screenshot(path=str(path), full_page=True, mask=code_mask_locators(page))
        record["screenshot"] = path.name
    (evidence_dir / f"failure-{label}.json").write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")


@contextlib.contextmanager
def _persona_session(
    browser: Browser,
    label: str,
    identity: dict[str, str],
    evidence_dir: Path,
) -> Iterator[tuple[Page, str]]:
    """Open one authenticated context for one persona, tracing from login onward.

    Args:
        browser: the session Playwright browser.
        label: names this session's trace and failure files.
        identity: the persona's ``{"email": ..., "password": ...}`` pair.
        evidence_dir: artifact directory.

    Yields:
        A ``(page, id_token)`` pair: the page for browser steps, the ID token for the server-side
        assertions made with the same identity.
    """
    context: BrowserContext = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    tracing = False
    try:
        login(page, identity["email"], identity["password"])
        token = api.sign_in(identity["email"], identity["password"], api.client_id(), api.region())
        context.tracing.start(title=f"show-sell-stage2-{label}", screenshots=True, snapshots=True, sources=False)
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


def _token_for(identity: dict[str, str]) -> str:
    """A fresh ID token for one persona, without opening a browser."""
    return api.sign_in(identity["email"], identity["password"], api.client_id(), api.region())


# ---------------------------------------------------------------------------
# The two gates that decide whether the lane is runnable at all
# ---------------------------------------------------------------------------


def _endpoint_gate(token: str) -> dict[str, Any]:
    """What the deployed API answers for Stage 2, before any lane is built.

    Args:
        token: the Unit admin's ID token.

    Returns:
        The Stage 2 fields this API carries, and the ones it does not.

    Raises:
        pytest.skip: the deployed build carries no Stage 2 endpoint at all.  Skipping is the right
            report — the finding is about the stack, and a failure would read as a defect here.
    """
    schema = api.gql(token, "query { __schema { queryType { fields { name } } mutationType { fields { name } } } }")
    answered = stage2.stage_two_fields_in_schema(schema)
    absent = [field for field in (*stage2.STAGE_TWO_WRITES, *stage2.STAGE_TWO_READS) if field not in answered]
    if answered and not absent:
        return {"answered": answered, "absent": absent}
    raise pytest.skip(
        f"{stage2.MISSING_ENDPOINT_NOTE}; this API answers {answered or 'none of them'} and is missing {absent}"
    )


def _roster_row(token: str, unit_campaign_id: str, profile_id: str) -> dict[str, Any]:
    """The admin's roster row for one Scout, with both versions the removal conditions on.

    ``unitCampaignRoster`` answers ``scoutCampaignCatalogId`` precisely so a caller can compare the
    two catalogs before sending a write the server would refuse, and ``version`` / ``guardVersion``
    are what ``removeUnitCampaignMembership`` conditions on.
    """
    data = api.gql(token, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["roster"], {"unitCampaignId": unit_campaign_id})
    rows = list((data.get("unitCampaignRoster") or {}).get("items") or [])
    wanted = profile_key(profile_id)
    matches = [row for row in rows if profile_key(str(row.get("profileId", ""))) == wanted]
    assert matches, f"the roster does not list {profile_id!r}; it lists {[row.get('profileId') for row in rows]}"
    return matches[0]


def _campaign_identities(token: str, unit_campaign_id: str) -> dict[str, str]:
    """The Unit Campaign's own catalog — the one its inventory and custody key on."""
    data = api.gql(token, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["campaignCatalogIdentity"], {"unitCampaignId": unit_campaign_id})
    campaign = data.get("unitCampaign") or {}
    return {
        "catalogId": str(campaign.get("catalogId") or ""),
        "campaignName": str(campaign.get("campaignName") or ""),
    }


def _scout_campaign_catalog(token: str, campaign_id: str) -> str:
    """The catalog the Scout Campaign sells from, read by its own owner."""
    data = api.gql(token, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["scoutCampaignCatalog"], {"campaignId": campaign_id})
    return str((data.get("getCampaign") or {}).get("catalogId") or "")


def _catalog_product_ids(token: str, unit_campaign_id: str) -> dict[str, str]:
    """Product name to product id for the catalog a Unit Campaign's stock can name.

    A Stage 2 balance is keyed ``(unitCampaignId, productId)`` and no product id crosses catalogs,
    so the suite reads its product ids here rather than inventing them.
    """
    data = api.gql(token, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["catalogProducts"], {"unitCampaignId": unit_campaign_id})
    products = ((data.get("unitCampaignCatalog") or {}).get("products")) or []
    return {str(product["productName"]): str(product["productId"]) for product in products}


def _traded_product(products: dict[str, str]) -> str:
    """The product name this lane sells, chosen from the campaign's own catalog."""
    if PREFERRED_PRODUCT in products:
        return PREFERRED_PRODUCT
    return sorted(products)[0]


# ---------------------------------------------------------------------------
# Stage 2 GraphQL steps
# ---------------------------------------------------------------------------


def _write(token: str, field: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Send one Stage 2 mutation and return its payload."""
    data = api.gql(token, stage2.STAGE_TWO_DOCUMENTS[field], variables)
    payload = data.get(field)
    assert isinstance(payload, dict), f"{field} answered {payload!r}"
    return payload


def _read(token: str, field: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Send one Stage 2 query and return its payload."""
    data = api.gql(token, stage2.STAGE_TWO_DOCUMENTS[field], variables)
    payload = data.get(field)
    assert isinstance(payload, dict), f"{field} answered {payload!r}"
    return payload


def _positions(token: str, unit_campaign_id: str) -> dict[str, dict[str, Any]]:
    """``inventoryPositions`` keyed by product id, with the §5.2 formulas checked on the way in.

    The formula check is not decoration.  The deployed read recomputes ``sellableKernelQty`` and the
    other §7 quantities from the balance, allocation and custody rows on every request, so an answer
    that disagrees with them is a persisted-balance defect — which is what §2.8.5 asks this suite to
    catch on a live stack rather than in a handler test.
    """
    payload = _read(token, "inventoryPositions", {"unitCampaignId": unit_campaign_id})
    rows = list(payload.get("items") or [])
    assert stage2.position_arithmetic_violations(rows) == [], f"the deployed positions break §5.2: {rows}"
    return {str(row["productId"]): row for row in rows}


def _trail(token: str, unit_campaign_id: str) -> list[dict[str, Any]]:
    """One lane's whole ``inventoryMovements`` trail."""
    return list(_read(token, "inventoryMovements", {"unitCampaignId": unit_campaign_id}).get("items") or [])


def _custody(token: str, unit_campaign_id: str) -> list[dict[str, Any]]:
    """``scoutCustodyBalances`` items for the campaign."""
    return list(_read(token, "scoutCustodyBalances", {"unitCampaignId": unit_campaign_id}).get("items") or [])


def _my_custody(token: str, unit_campaign_id: str, profile_id: str) -> list[dict[str, Any]]:
    """The Scout's own custody read — the participant-facing half of ``INV-Q-05``."""
    data = api.gql(
        token,
        stage2.STAGE_TWO_DOCUMENTS["myScoutCustody"],
        {"unitCampaignId": unit_campaign_id, "profileId": profile_id},
    )
    return list(data.get("myScoutCustody") or [])


def _fulfillments(token: str, order_id: str) -> list[dict[str, Any]]:
    """An Order's fulfillment records, in the order the deployed read answers them."""
    return list(_read(token, "orderFulfillments", {"orderId": order_id}).get("items") or [])


def _scout_orders(token: str, unit_campaign_id: str, campaign_id: str) -> list[dict[str, Any]]:
    """``unitScoutCampaignOrders`` items — the Orders whose tenancy is the sale's own origin."""
    payload = _read(
        token, "unitScoutCampaignOrders", {"unitCampaignId": unit_campaign_id, "campaignId": campaign_id}
    )
    return list(payload.get("items") or [])


def _refused(token: str, field: str, variables: dict[str, Any]) -> list[dict[str, str]]:
    """Run a Stage 2 read that must fail and return the codes it answered.

    The code can arrive in four places depending on which kind of resolver refused
    (``tests/e2e/utils/show_sell_graphql.py`` reads all four), so the assertion is on the set this
    helper collects, never on one slot.
    """
    payload = api.gql_raw(token, stage2.STAGE_TWO_DOCUMENTS[field], variables)
    return api.error_summaries(payload)


def _demand(orders: list[dict[str, Any]], product_id: str) -> dict[str, int]:
    """Actual demand for one product across the Orders the caller already read.

    ``SS-SM-10`` starts from actual unfulfilled individual demand, which is a per-line number: a
    line of four with one fulfilled still asks for three.
    """
    ordered = fulfilled = 0
    for order in orders:
        for line in order.get("lineItems") or []:
            if str(line.get("productId")) != product_id:
                continue
            ordered += int(line.get("quantity") or 0)
            fulfilled += int(line.get("fulfilledQuantity") or 0)
    return {"orderedQty": ordered, "fulfilledQty": fulfilled, "unfulfilledQty": ordered - fulfilled}


# ---------------------------------------------------------------------------
# The lane's own fixture rows, built the way Stage 1 builds them
# ---------------------------------------------------------------------------


def _shared_catalog(token: str) -> dict[str, Any]:
    """The catalog both of the lane's Campaigns can be created on.

    A Stage 2 lane needs one catalog shared by a Unit Campaign and a Scout Campaign owned by
    different identities: the Unit Campaign's stock keys on its own ``catalogId`` while
    ``createOrder`` prices the sale in the Scout Campaign's, so two catalogs means a custody sale
    refused with no Order written.  The create-campaign picker offers a caller their own catalogs
    plus ``listManagedCatalogs``, which filters ``catalogType = ADMIN_MANAGED`` — measured on dev on
    2026-11-18, a ``createCatalog`` catalog is ``USER_CREATED`` and stays invisible to the other
    identity even with ``isPublic: true``, and ``createManagedCatalog`` answers the fixture Unit
    admin ``FORBIDDEN`` ("Admin access required").  So the lane uses the shared catalog the stack
    already carries.

    Returns:
        ``catalogId``, ``catalogName``, and the products it offers, for the evidence record.

    Raises:
        pytest.skip: the stack offers no ``ADMIN_MANAGED`` catalog with products, which is a stack
            prerequisite rather than a Stage 2 defect.
    """
    data = api.gql(token, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["managedCatalogs"], {})
    rows = list(data.get("listManagedCatalogs") or [])
    named = os.environ.get("SS_SHARED_CATALOG", "").strip()
    usable = [row for row in rows if (row.get("products") or [])]
    if named:
        usable = [row for row in usable if str(row.get("catalogName")) == named]
    if not usable:
        raise pytest.skip(
            "no ADMIN_MANAGED catalog with products on this stack: a Stage 2 lane needs one catalog "
            "both Campaigns are created on, createCatalog writes a USER_CREATED catalog the other "
            "identity cannot select, and createManagedCatalog is FORBIDDEN for a Unit admin"
        )
    chosen = usable[0]
    return {
        "catalogId": str(chosen["catalogId"]),
        "catalogName": str(chosen["catalogName"]),
        "products": [str(product["productName"]) for product in chosen["products"]],
    }


def _ensure_scout_profile(page: Page, name: str) -> str:
    """Return *name*, creating the Scout profile through the app when it is absent."""
    dashboard = DashboardPage(page)
    dashboard.goto()
    dashboard.wait_for_loading()
    with contextlib.suppress(Exception):
        dashboard.wait_for_profiles_loaded(timeout=10_000)
    if name in dashboard.get_owned_profile_names():
        return "reused"
    dashboard.create_profile(name)
    return "created"


def _profile_id_for(token: str, seller_name: str, *, seconds: float = 60.0) -> str:
    """The profile id of *seller_name*, re-read until the server lists it.

    A profile the UI just created is written and then read through an index, so the first read can
    answer without it; failing on that answer reports a fixture problem that does not exist.
    """
    deadline = time.monotonic() + seconds
    names: list[str] = []
    while True:
        profiles = api.my_profiles(token)
        names = [str(profile.get("sellerName")) for profile in profiles]
        matches = [profile for profile in profiles if profile.get("sellerName") == seller_name]
        if matches:
            return str(matches[0]["profileId"])
        if time.monotonic() >= deadline:
            raise AssertionError(f"no owned profile is named {seller_name!r}; the server lists {names}")
        time.sleep(2.0)


def _scout_campaign_id_for(token: str, profile_id: str, name: str) -> str:
    """The Scout Campaign id named *name*, read from its owner's campaign list."""
    data = api.gql(token, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["scoutCampaigns"], {"profileId": profile_id})
    campaigns = ((data.get("listCampaignsByProfile") or {}).get("campaigns")) or []
    matches = [campaign for campaign in campaigns if campaign.get("campaignName") == name]
    assert matches, f"no campaign is named {name!r}; the server lists {[c.get('campaignName') for c in campaigns]}"
    return str(matches[0]["campaignId"])


def _unit_for_key(token: str, unit_number: str) -> str | None:
    """The caller's Unit that already carries this run's tenant key, if any."""
    wanted = int(unit_number)
    for unit in api.my_units(token):
        if (
            str(unit.get("unitType")) == UNIT_TYPE
            and int(unit.get("unitNumber", 0)) == wanted
            and str(unit.get("city")) == UNIT_CITY
            and str(unit.get("state")) == UNIT_STATE
        ):
            return str(unit["unitId"])
    return None


def _write_evidence(
    evidence_dir: Path,
    evidence: dict[str, Any],
    steps: list[dict[str, Any]],
    passwords: list[str],
    codes: list[str],
) -> None:
    """Write ``evidence.json`` / ``evidence.md`` and run the artifact hygiene pass.

    The steps are a parameter, not a key of *evidence*, on purpose: this runs in a ``finally``
    block, and the run that stops halfway is exactly the one whose partial record matters.
    """
    evidence = {**evidence, "steps": steps}
    (evidence_dir / "evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Show & Sell Stage 2 acceptance record",
        "",
        f"- target: `{evidence['target']}`",
        f"- DATA_ID: `{evidence['data_id']}`",
        f"- started: `{evidence['started']}`",
        f"- unitCampaignId: `{evidence['lane']['unitCampaignId']}`",
        "",
        "| # | acceptance | result | observations |",
        "| --- | --- | --- | --- |",
    ]
    for step in evidence["steps"]:
        lines.append(f"| {step['order']} | {step['acceptance']} | {step['result']} | {step['summary']} |")
    (evidence_dir / "evidence.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    redact_and_scan(evidence_dir, passwords=passwords, codes=codes)


# ---------------------------------------------------------------------------
# The journey
# ---------------------------------------------------------------------------


def test_show_sell_stage2_journey(
    browser: Browser,
    identities: dict[str, dict[str, str]],
    lane: dict[str, str],
    evidence_dir: Path,
) -> None:
    """Run the Stage 2 lane end to end and record what each acceptance id observed.

    The steps are ordered the way the smoke plan writes them, because the balances each one asserts
    are the previous one's result: receipt, stock-only adjustments, issue, door-to-door sale,
    fulfillment and reversal, return, then the read-backs the screens and the queries have to agree
    on.  The scope-retention and authorization legs come last, because they read a lane that has
    already done everything.

    Args:
        browser: the session Playwright browser.
        identities: the standing fixture identities.
        lane: DATA_ID-suffixed row names for this run.
        evidence_dir: artifact directory for this run.
    """
    steps: list[dict[str, Any]] = []
    codes: list[str] = []
    passwords: list[str] = [identity["password"] for identity in identities.values()]
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    built: dict[str, Any] = {}

    def record(acceptance: str, summary: str) -> None:
        """Append one acceptance observation to the record."""
        steps.append({"order": len(steps) + 1, "acceptance": acceptance, "result": "observed", "summary": summary})

    try:
        # --- Gate 1: the deployed build has to carry Stage 2 -----------------------
        admin_token = _token_for(identities["admin"])
        gate = _endpoint_gate(admin_token)
        record("§2.8.5 runnable gate", f"the API answers {len(gate['answered'])} Stage 2 fields")

        # --- Gate 1b: a catalog both Campaigns can be created on -----------------
        shared = _shared_catalog(admin_token)
        catalog_name = shared["catalogName"]
        built["sharedCatalog"] = shared
        record("UNIT-06 / shared catalog", f"{shared['catalogId']} ({catalog_name}) offers {shared['products']}")

        # --- The lane: Unit, Unit Campaign, Scout profile, Scout Campaign, join ---

        with _persona_session(browser, "02-admin", identities["admin"], evidence_dir) as (admin_page, _):
            admin = ShowSellPage(admin_page)
            admin.goto_units()
            existing = _unit_for_key(admin_token, lane["unit_number"])
            if existing:
                unit_id, unit_creation = existing, "reused"
            else:
                unit_id, duplicate_confirm = admin.create_unit(
                    unit_type=UNIT_TYPE,
                    unit_number=lane["unit_number"],
                    city=UNIT_CITY,
                    state=UNIT_STATE,
                    display_name=lane["unit_display_name"],
                )
                unit_creation = "separate-duplicate" if duplicate_confirm else "created"
            admin.open_unit(unit_id)
            admin.open_tab("tab-campaigns")
            campaign_id, join_code = admin.create_campaign(
                name=lane["campaign_name"], year=CAMPAIGN_YEAR, catalog_name=catalog_name
            )
            codes.append(join_code)
            built.update({"unitId": unit_id, "unitCampaignId": campaign_id, "unitCreation": unit_creation})
            record("API-FIX-01", f"{UNIT_TYPE} {lane['unit_number']} → Unit {unit_id}, Unit Campaign {campaign_id}")

        with _persona_session(browser, "01-scout", identities["scout"], evidence_dir) as (scout_page, scout_token):
            _ensure_scout_profile(scout_page, lane["scout_name"])
            scout_profile_id = _profile_id_for(scout_token, lane["scout_name"])
            campaigns = CampaignPage(scout_page)
            campaigns.goto(scout_profile_id)
            if not campaigns.has_campaign(lane["campaign_name"]):
                campaigns.create_campaign_on_catalog(
                    lane["campaign_name"], profile_id=scout_profile_id, catalog_name=catalog_name
                )
            scout_campaign_id = _scout_campaign_id_for(scout_token, scout_profile_id, lane["campaign_name"])
            built.update({"scoutProfileId": scout_profile_id, "scoutCampaignId": scout_campaign_id})
            record("API-FIX-01/02", f"Scout profile {scout_profile_id} holds campaign {scout_campaign_id}")

        with _persona_session(browser, "03-scout-join", identities["scout"], evidence_dir) as (scout_page, _):
            scout = ShowSellPage(scout_page)
            scout.goto_join()
            scout.join_unit_campaign(join_code, scout_profile_id)
            record("API-FIX-02", f"Scout Campaign {scout_campaign_id} joined Unit Campaign {campaign_id}")

        # --- Gate 2: both Campaigns sell from one catalog -------------------------
        unit_catalog = _campaign_identities(admin_token, campaign_id)
        roster_row = _roster_row(admin_token, campaign_id, scout_profile_id)
        scout_catalog = _scout_campaign_catalog(scout_token, scout_campaign_id)
        assert unit_catalog["catalogId"] == str(roster_row.get("scoutCampaignCatalogId") or "") == scout_catalog, (
            f"the lane's Scout Campaign sells from {scout_catalog!r} while the Unit Campaign's stock keys on "
            f"{unit_catalog['catalogId']!r}: createOrder prices in the first and the balances live in the second, "
            "so the custody sale is refused with no Order written (AGENTS.md, 'A joined Scout Campaign and its "
            "Unit Campaign can sell from different catalogs')"
        )
        products = _catalog_product_ids(admin_token, campaign_id)
        traded = _traded_product(products)
        product_id = products[traded]
        others = [name for name in sorted(products) if name != traded]
        if not others:
            raise pytest.skip(
                f"{unit_catalog['catalogId']} carries one product only: the sale consumes every unit "
                "of custody it can reach, so the return leg needs a second product to give back"
            )
        returned_name = RETURN_PRODUCT if RETURN_PRODUCT in others else others[0]
        return_product_id = products[returned_name]
        built.update({
            "catalogId": unit_catalog["catalogId"],
            "product": traded,
            "productId": product_id,
            "returnedProduct": returned_name,
            "returnedProductId": return_product_id,
        })
        record(
            "UNIT-06 / catalog identity",
            f"both Campaigns sell from {unit_catalog['catalogId']}; the lane trades {traded} ({product_id})",
        )

        # --- SS-SM-03: receipt and stock-only adjustments, with no money ----------
        receipt = _write(
            admin_token,
            "recordInventoryReceipt",
            {"input": stage2.receipt_input(campaign_id, product_id, RECEIVED_QTY, idempotency_key=f"{lane['data_id']}-receipt")},
        )
        raise_adjust = _write(
            admin_token,
            "adjustInventory",
            {
                "input": stage2.adjust_input(
                    campaign_id,
                    product_id,
                    2,
                    "Trade with Troop 7150; money settled outside app",
                    idempotency_key=f"{lane['data_id']}-raise",
                )
            },
        )
        lower_adjust = _write(
            admin_token,
            "adjustInventory",
            {
                "input": stage2.adjust_input(
                    campaign_id,
                    product_id,
                    -1,
                    "Gift to outgoing volunteer",
                    idempotency_key=f"{lane['data_id']}-lower",
                )
            },
        )
        council = _write(
            admin_token,
            "adjustCouncilOnOrder",
            {
                "input": stage2.council_on_order_input(
                    campaign_id, product_id, ON_ORDER_QTY, idempotency_key=f"{lane['data_id']}-council"
                )
            },
        )
        assert receipt["kernelPhysicalQty"] == RECEIVED_QTY, receipt
        assert raise_adjust["kernelPhysicalQty"] == RECEIVED_QTY + 2, raise_adjust
        assert lower_adjust["kernelPhysicalQty"] == RECEIVED_QTY + 1, lower_adjust
        assert lower_adjust["soldInPossessionQty"] == 0, lower_adjust
        assert council["councilOnOrderQty"] == ON_ORDER_QTY, council
        assert council["kernelPhysicalQty"] == RECEIVED_QTY + 1, (
            f"the Council-on-order adjustment moved physical stock: {council}"
        )
        record(
            "SS-SM-03 steps 4-6",
            f"receipt {receipt['kernelPhysicalQty']}, adjustments +2/-1 → {lower_adjust['kernelPhysicalQty']}, "
            f"on-order {council['councilOnOrderQty']} with kernelPhysicalQty unchanged",
        )

        # --- IDEM-01: the same key replays the answer, it does not write again -----
        #
        # The replay answers the *first* call's payload — same version, same
        # ``kernelPhysicalQty`` — while the persisted position keeps the later adjustments.  Both
        # halves matter: an answer that re-ran the write would double the stock, and an answer that
        # matched the current row would mean the write ran again and only its response was rebuilt.
        # The idempotency keys are derived from ``DATA_ID``, so a pinned re-run of this lane replays
        # every write below and changes nothing on the stack — which is why a run meant as fresh
        # evidence takes a fresh ``DATA_ID``.
        replay = _write(
            admin_token,
            "recordInventoryReceipt",
            {"input": stage2.receipt_input(campaign_id, product_id, RECEIVED_QTY, idempotency_key=f"{lane['data_id']}-receipt")},
        )
        assert replay == receipt, f"the replay answered something other than the first call: {replay!r} != {receipt!r}"
        after_replay = _positions(admin_token, campaign_id)[product_id]
        assert after_replay["kernelPhysicalQty"] == lower_adjust["kernelPhysicalQty"], (
            f"the replayed receipt wrote stock again: {after_replay}"
        )
        assert after_replay["version"] > receipt["version"], (
            f"the position's version did not advance past the replay's write: {after_replay}"
        )
        record(
            "IDEM-01",
            f"replayed receipt key answers the original v{receipt['version']} payload "
            f"(kernel {receipt['kernelPhysicalQty']}) while the row stays at v{after_replay['version']} "
            f"kernel {after_replay['kernelPhysicalQty']}",
        )

        # --- SS-SM-04 step 1: issue into Scout custody ----------------------------
        issue = _write(
            admin_token,
            "issueStockToScout",
            {
                "input": stage2.issue_input(
                    campaign_id,
                    scout_campaign_id,
                    scout_profile_id,
                    product_id,
                    ISSUED_QTY,
                    idempotency_key=f"{lane['data_id']}-issue",
                )
            },
        )
        custody_rows = _custody(admin_token, campaign_id)
        assert stage2.custody_by_product(custody_rows).get(product_id) == issue["custodyBalance"]["withScoutQty"], custody_rows
        assert issue["inventoryPosition"]["withScoutQty"] == ISSUED_QTY, issue
        record(
            "SS-SM-04 step 1",
            f"issued {ISSUED_QTY} of {traded}: withScoutQty={issue['custodyBalance']['withScoutQty']}, "
            f"kernelPhysicalQty={issue['inventoryPosition']['kernelPhysicalQty']}",
        )

        # The return leg's product, received and issued to the same Scout.  A custody balance is
        # keyed (unitCampaignId, productId, profileId), so this also shows the two balances do not
        # share a number a sale of one product would consume — and the receipt first is not ceremony:
        # a campaign holds no Kernels for a product until one is written, and issuing past them is
        # refused ("quantity exceeds the 0 unassigned Kernels this campaign holds for that product",
        # measured on dev on 2026-11-18).
        second_receipt = _write(
            admin_token,
            "recordInventoryReceipt",
            {
                "input": stage2.receipt_input(
                    campaign_id, return_product_id, RETURN_RECEIVED, idempotency_key=f"{lane['data_id']}-receipt-second"
                )
            },
        )
        assert second_receipt["kernelPhysicalQty"] == RETURN_RECEIVED, second_receipt
        assert second_receipt["councilOnOrderQty"] == 0, (
            f"the second product's receipt came with a Council-on-order balance attached: {second_receipt}"
        )
        second_issue = _write(
            admin_token,
            "issueStockToScout",
            {
                "input": stage2.issue_input(
                    campaign_id,
                    scout_campaign_id,
                    scout_profile_id,
                    return_product_id,
                    RETURN_ISSUED,
                    idempotency_key=f"{lane['data_id']}-issue-return-product",
                )
            },
        )
        assert second_issue["custodyBalance"]["productId"] == return_product_id, second_issue
        after_issues = _positions(admin_token, campaign_id)
        assert after_issues[return_product_id]["withScoutQty"] == RETURN_ISSUED, after_issues[return_product_id]
        assert after_issues[return_product_id]["kernelPhysicalQty"] == RETURN_RECEIVED - RETURN_ISSUED, (
            after_issues[return_product_id]
        )
        assert after_issues[product_id]["withScoutQty"] == ISSUED_QTY, after_issues[product_id]
        record(
            "INV-M-04-01",
            f"received {RETURN_RECEIVED} and issued {RETURN_ISSUED} of {returned_name} as a second custody balance: "
            f"withScoutQty {after_issues[product_id]['withScoutQty']} / {after_issues[return_product_id]['withScoutQty']} "
            "per product, kernelPhysicalQty falls by what each issue moved",
        )

        # --- INV-Q-01: the balances, and the formulas they have to satisfy --------
        positions = _positions(admin_token, campaign_id)
        traded_position = positions.get(product_id)
        assert traded_position, f"inventoryPositions answers {sorted(positions)}, not {product_id!r}"
        built["tradedPosition"] = traded_position

        # --- The three §2.6 screens, read by the browser that renders them -------
        with _persona_session(browser, "04-admin-screens", identities["admin"], evidence_dir) as (admin_page, _):
            admin = ShowSellPage(admin_page)
            admin.goto_unit_campaign(unit_id, campaign_id)
            admin.open_stage_two_tab(ID_TAB_INVENTORY)
            screen = admin.wait_for_inventory_position(product_id)
            shot = _screenshot(admin_page, "01-stock-screen", evidence_dir, masks=admin.code_mask_locators())
            for quantity, value in (
                ("kernelPhysicalQty", traded_position["kernelPhysicalQty"]),
                ("sellableKernelQty", traded_position["sellableKernelQty"]),
                ("withScoutQty", traded_position["withScoutQty"]),
                ("councilOnOrderQty", traded_position["councilOnOrderQty"]),
            ):
                assert screen.get(quantity) == int(value), (
                    f"the Stock tab shows {quantity}={screen.get(quantity)} where the server answers {value}"
                )
            record("INV-Q-01 / §2.6.1", f"screen and server agree on {sorted(screen)}; {shot}")

            admin.open_stage_two_tab(ID_TAB_CUSTODY)
            held = admin.wait_for_custody_held(scout_profile_id)
            shot = _screenshot(admin_page, "02-custody-screen", evidence_dir, masks=admin.code_mask_locators())
            lines = {
                name: admin.custody_line_qty(scout_profile_id, ids)
                for name, ids in ((traded, product_id), (returned_name, return_product_id))
            }
            assert held == ISSUED_QTY + RETURN_ISSUED, (
                f"the custody tab shows {held} held for the Scout, the two balances answer "
                f"{ISSUED_QTY} + {RETURN_ISSUED}"
            )
            assert lines == {traded: ISSUED_QTY, returned_name: RETURN_ISSUED}, (
                f"the custody tab's per-product lines read {lines}, the balances are "
                f"{traded}={ISSUED_QTY}, {returned_name}={RETURN_ISSUED}"
            )
            record("INV-Q-04 / §2.6.2", f"Scout holds {held} across {sorted(lines)}; {shot}")

            admin.open_stage_two_tab(ID_TAB_ORDERS)
            shot = _screenshot(admin_page, "03-orders-screen", evidence_dir, masks=admin.code_mask_locators())
            record("§2.6.3", f"fulfillment tab open, notes={admin.stage_two_notes()}; {shot}")

        # --- INV-Q-05: the Scout's own custody read, and nothing else -------------
        scout_custody = _my_custody(scout_token, campaign_id, scout_profile_id)
        assert stage2.custody_by_product(scout_custody) == {product_id: ISSUED_QTY, return_product_id: RETURN_ISSUED}, (
            scout_custody
        )
        record(
            "INV-Q-05-01",
            f"myScoutCustody answers {len(scout_custody)} line(s) for the Scout's own profile and no other's",
        )

        # --- ORD-API-02: the door-to-door sale that consumes what the Scout carries
        sale = _write(
            admin_token,
            "createOrder",
            {
                "input": stage2.custody_sale_input(
                    scout_profile_id,
                    scout_campaign_id,
                    product_id,
                    SALE_QTY,
                    SALE_CUSTOMER,
                    idempotency_key=f"{lane['data_id']}-sale",
                )
            },
        )
        order_id = str(sale["orderId"])
        sale_lines = [item for item in sale["lineItems"] or [] if str(item.get("productId")) == product_id]
        assert len(sale_lines) == 1, f"the sale answered {len(sale_lines)} lines for {product_id}: {sale!r}"
        sale_line = sale_lines[0]
        line_item_id = str(sale_line.get("lineItemId") or "")
        assert line_item_id, f"the sale answered no line identity; §5.19 says the write mints it: {sale!r}"
        assert str(sale["unitCampaignId"]) == campaign_id, sale
        assert int(sale_line["quantity"]) == SALE_QTY, sale_line
        assert int(sale_line["fulfilledQuantity"] or 0) == ISSUED_QTY, (
            f"the sale consumed {sale_line['fulfilledQuantity']} of the {ISSUED_QTY} the Scout carried: {sale_line}"
        )
        after_sale = _positions(admin_token, campaign_id)[product_id]
        assert after_sale["withScoutQty"] == 0, f"custody survived the sale that consumed it: {after_sale}"
        assert after_sale["kernelPhysicalQty"] == traded_position["kernelPhysicalQty"], (
            f"a custody sale changed Kernel stock: {after_sale}"
        )
        built.update(
            {
                "orderId": order_id,
                "lineItemId": line_item_id,
                "orderedQty": SALE_QTY,
                "custodyFulfilled": int(sale_line["fulfilledQuantity"] or 0),
            }
        )
        record(
            "ORD-API-02-01/02",
            f"sale {order_id} in unitCampaignId={sale['unitCampaignId']}: ordered {SALE_QTY}, "
            f"fulfilled {sale_line['fulfilledQuantity']} from custody on line {line_item_id} "
            f"(the write minted that id, §5.19), Kernel stock untouched",
        )

        # --- INV-M-06-02: the owed line, filled from the Council ------------------
        #
        # ``fulfillmentVersion`` starts at 0 on a door-to-door Order even though the sale itself
        # writes the custody fulfillment(s): the data model creates the Order with version 0 and
        # consumes custody in the same operation (SHOW_AND_SELL_DATA_MODEL.md §806), so the version
        # the first fulfillment conditions on is the one the sale answered, not a number the sale
        # advanced.
        version = int(sale["fulfillmentVersion"] or 0)
        council_fill = _write(
            admin_token,
            "fulfillIndividualOrderLine",
            {
                "input": stage2.fulfill_input(
                    order_id,
                    line_item_id,
                    COUNCIL_FILL,
                    version,
                    source="EXTERNAL_COUNCIL",
                    idempotency_key=f"{lane['data_id']}-council-fill",
                )
            },
        )
        council_record = council_fill["fulfillment"]
        assert council_record["inventoryMovementId"] is None, (
            f"a Council fulfillment named an inventory movement: {council_record}"
        )
        after_council_fill = _positions(admin_token, campaign_id)[product_id]
        assert after_council_fill["councilOnOrderQty"] == ON_ORDER_QTY, (
            f"an external-Council fulfillment consumed the Council-on-order balance: {after_council_fill}. "
            "councilOnOrderQty is expected Council supply and is never subtracted automatically "
            "(SHOW_AND_SELL_DATA_MODEL.md, the balance table)"
        )
        assert after_council_fill["kernelPhysicalQty"] == after_sale["kernelPhysicalQty"], (
            f"an external-Council fulfillment moved Kernel stock: {after_council_fill}"
        )
        assert after_council_fill["version"] == after_sale["version"], (
            f"an external-Council fulfillment wrote the balance row anyway: {after_council_fill}"
        )
        council_version = int(council_fill["order"]["fulfillmentVersion"] or version + 1)
        assert council_version > version, f"the fulfillment did not advance the Order version: {council_fill['order']}"
        record(
            "INV-M-06-02",
            f"EXTERNAL_COUNCIL fulfillment {council_record['fulfillmentId']} names no movement and writes no "
            f"inventory row at all: kernelPhysicalQty {after_council_fill['kernelPhysicalQty']} and "
            f"councilOnOrderQty {after_council_fill['councilOnOrderQty']} both unchanged, balance still at "
            f"v{after_council_fill['version']}, while the Order's version moved to {council_version}",
        )

        # --- INV-M-07-01: the reversal puts the demand back and only that source ---
        reversal = _write(
            admin_token,
            "reverseIndividualOrderFulfillment",
            {
                "input": stage2.reverse_input(
                    order_id, str(council_record["fulfillmentId"]), council_version, idempotency_key=f"{lane['data_id']}-reverse"
                )
            },
        )
        reversal_record = reversal["reversal"]
        assert str(reversal_record["reversalOfFulfillmentId"]) == str(council_record["fulfillmentId"]), reversal_record
        after_reversal = _positions(admin_token, campaign_id)[product_id]
        assert after_reversal["councilOnOrderQty"] == ON_ORDER_QTY, (
            f"a reversal of a Council fulfillment touched the Council-on-order balance: {after_reversal}"
        )
        assert after_reversal["version"] == after_council_fill["version"], (
            f"reversing a Council fulfillment wrote the balance row: {after_reversal}"
        )
        assert after_reversal["kernelPhysicalQty"] == after_sale["kernelPhysicalQty"], (
            f"a reversal of a Council fulfillment touched Kernel stock: {after_reversal}"
        )
        version = int(reversal["order"]["fulfillmentVersion"] or council_version + 1)
        record(
            "INV-M-07-01",
            f"reversal {reversal_record['fulfillmentId']} names {council_record['fulfillmentId']}, restores the "
            f"line's demand, and leaves both balances exactly where they were "
            f"(kernel {after_reversal['kernelPhysicalQty']}, on-order {after_reversal['councilOnOrderQty']}, "
            f"balance v{after_reversal['version']})",
        )

        # --- VER-01: the version the reversal already spent is now stale ----------
        stale = api.gql_raw(
            admin_token,
            stage2.STAGE_TWO_DOCUMENTS["fulfillIndividualOrderLine"],
            {
                "input": stage2.fulfill_input(
                    order_id, line_item_id, STOCK_FILL, council_version, idempotency_key=f"{lane['data_id']}-stale"
                )
            },
        )
        stale_codes = [item["code"] for item in api.error_summaries(stale)]
        assert stale_codes, f"the version the reversal spent was accepted: order v{council_version} then v{version}"
        after_stale = _positions(admin_token, campaign_id)[product_id]
        assert after_stale["unassignedKernelQty"] == after_reversal["unassignedKernelQty"], (
            f"the refused fulfillment moved stock: {after_stale}"
        )
        assert after_stale["version"] == after_reversal["version"], (
            f"the refused fulfillment wrote the position anyway: {after_stale}"
        )
        stale_line = _demand(_scout_orders(admin_token, campaign_id, scout_campaign_id), product_id)
        assert stale_line["fulfilledQty"] == ISSUED_QTY, (
            f"the refused fulfillment, or the reversal, changed what the line reports fulfilled: {stale_line}"
        )
        record(
            "VER-01",
            f"fulfillment pinned to the spent v{council_version} refused with {stale_codes}, position v"
            f"{after_stale['version']} and line {stale_line['fulfilledQty']}/{SALE_QTY} unchanged",
        )

        # --- INV-M-06-01: the same line, filled from unassigned Kernel stock ------
        stock_fill = _write(
            admin_token,
            "fulfillIndividualOrderLine",
            {
                "input": stage2.fulfill_input(
                    order_id, line_item_id, STOCK_FILL, version, idempotency_key=f"{lane['data_id']}-stock-fill"
                )
            },
        )
        stock_record = stock_fill["fulfillment"]
        assert stock_record["inventoryMovementId"], f"a KERNEL_STOCK fulfillment names no movement: {stock_record}"
        filled_line = next(item for item in stock_fill["order"]["lineItems"] if str(item.get("lineItemId")) == line_item_id)
        assert int(filled_line["fulfilledQuantity"] or 0) == ISSUED_QTY + STOCK_FILL, filled_line
        after_stock_fill = _positions(admin_token, campaign_id)[product_id]
        assert after_stock_fill["kernelPhysicalQty"] == after_reversal["kernelPhysicalQty"] - STOCK_FILL, (
            f"a Kernel-stock fulfillment did not take the stock it handed over: {after_stock_fill}"
        )
        assert after_stock_fill["totalUnitOwnedUndeliveredQty"] == (
            after_reversal["totalUnitOwnedUndeliveredQty"] - STOCK_FILL
        ), f"the unit's owned-and-undelivered total did not follow the sale: {after_stock_fill}"
        assert after_stock_fill["unassignedKernelQty"] == after_reversal["unassignedKernelQty"] - STOCK_FILL, (
            f"the fulfillment did not consume unassigned stock: {after_stock_fill}"
        )
        version = int(stock_fill["order"]["fulfillmentVersion"] or version + 1)
        record(
            "INV-M-06-01",
            f"KERNEL_STOCK fulfillment {stock_record['fulfillmentId']} names movement "
            f"{stock_record['inventoryMovementId']}; line now {filled_line['fulfilledQuantity']}/{SALE_QTY}, "
            f"unassignedKernelQty {after_stock_fill['unassignedKernelQty']}",
        )

        # --- The fulfillment tab shows the line the server just wrote ------------
        with _persona_session(browser, "06-admin-orders", identities["admin"], evidence_dir) as (admin_page, _):
            admin = ShowSellPage(admin_page)
            admin.goto_unit_campaign(unit_id, campaign_id)
            admin.open_stage_two_tab(ID_TAB_ORDERS)
            admin.select_fulfillment_campaign(lane["campaign_name"])
            screen_line = admin.order_block_ids()
            shot = _screenshot(admin_page, "04-orders-after-fulfillment", evidence_dir, masks=admin.code_mask_locators())
            assert order_id in screen_line, (
                f"the fulfillment tab lists orders {screen_line} for {lane['campaign_name']!r}, not {order_id}; "
                f"the tab says {admin.fulfillment_notes() or 'nothing about being empty'}"
            )
            fulfilled, owed = admin.wait_for_order_line(line_item_id, campaign_name=lane["campaign_name"])
            assert (fulfilled, owed) == (ISSUED_QTY + STOCK_FILL, SALE_QTY - ISSUED_QTY - STOCK_FILL), (
                f"the tab shows line {line_item_id} as {fulfilled} fulfilled / {owed} owed, the server says "
                f"{ISSUED_QTY + STOCK_FILL}/{SALE_QTY}"
            )
            record(
                "INV-Q-03 / §2.6.3",
                f"the fulfillment tab shows line {line_item_id} at {fulfilled} fulfilled and {owed} owed; {shot}",
            )

        # --- SS-SM-04 step 3 / INV-M-05: the return, one batch, one atomic result -
        before_return = _positions(admin_token, campaign_id)
        returned = _write(
            admin_token,
            "returnStockFromScout",
            {
                "input": stage2.return_input(
                    campaign_id,
                    scout_campaign_id,
                    scout_profile_id,
                    [{"productId": return_product_id, "quantity": RETURN_QTY}],
                    idempotency_key=f"{lane['data_id']}-return",
                )
            },
        )
        assert len(returned["custodyBalances"]) == 1, returned
        assert len(returned["inventoryPositions"]) == 1, returned
        after_return = _positions(admin_token, campaign_id)
        moved = after_return[return_product_id]
        unchanged = after_return[product_id]
        assert moved["withScoutQty"] == RETURN_ISSUED - RETURN_QTY, moved
        assert moved["kernelPhysicalQty"] == before_return[return_product_id]["kernelPhysicalQty"] + RETURN_QTY, moved
        assert unchanged["withScoutQty"] == 0, f"the sale left custody that the return then moved: {unchanged}"
        assert unchanged["kernelPhysicalQty"] == before_return[product_id]["kernelPhysicalQty"], unchanged
        record(
            "INV-M-05-01 / SS-SM-04 step 3",
            f"return of {RETURN_QTY} of {returned_name} answered 1 position and 1 custody row: "
            f"kernelPhysicalQty {before_return[return_product_id]['kernelPhysicalQty']}→{moved['kernelPhysicalQty']}, "
            f"withScoutQty {RETURN_ISSUED}→{moved['withScoutQty']}; {traded} untouched at "
            f"kernel {unchanged['kernelPhysicalQty']}, custody {unchanged['withScoutQty']}",
        )

        # --- INV-Q-02: the audit trail every one of those writes owes -------------
        trail = _trail(admin_token, campaign_id)
        expected_trail = [
            {"movementType": "RECEIPT", "productId": product_id, "kernelPhysicalDelta": RECEIVED_QTY},
            {"movementType": "STOCK_ADJUSTMENT", "productId": product_id, "kernelPhysicalDelta": 2},
            {"movementType": "STOCK_ADJUSTMENT", "productId": product_id, "kernelPhysicalDelta": -1},
            {"movementType": "COUNCIL_ON_ORDER_ADJUST", "productId": product_id, "councilOnOrderDelta": ON_ORDER_QTY},
            {
                "movementType": "SCOUT_ISSUE",
                "productId": product_id,
                "kernelPhysicalDelta": -ISSUED_QTY,
                "withScoutDelta": ISSUED_QTY,
            },
            # The sale's custody consumption is recorded as the fulfillment it wrote, not as a
            # ``SCOUT_SALE_CONSUME`` row: that type exists for a Show & Sell event sale and its
            # required source link is the event's ``saleId`` (``src/utils/inventory_models.py``,
            # ``MOVEMENT_REQUIRED_SOURCE_LINKS``), which a door-to-door sale does not have.  Measured
            # on dev on 2026-11-18, the custody the door-to-door sale consumed is traced by an
            # ``INDIVIDUAL_FULFILL`` row naming the Order and the ``SCOUT_CUSTODY`` fulfillment.
            {
                "movementType": "INDIVIDUAL_FULFILL",
                "productId": product_id,
                "withScoutDelta": -ISSUED_QTY,
                "kernelPhysicalDelta": 0,
                "profileId": scout_profile_id,
                "orderId": order_id,
            },
            {"movementType": "RECEIPT", "productId": return_product_id, "kernelPhysicalDelta": RETURN_RECEIVED},
            {
                "movementType": "SCOUT_ISSUE",
                "productId": return_product_id,
                "kernelPhysicalDelta": -RETURN_ISSUED,
                "withScoutDelta": RETURN_ISSUED,
            },
            {
                "movementType": "SCOUT_RETURN",
                "productId": return_product_id,
                "kernelPhysicalDelta": RETURN_QTY,
                "withScoutDelta": -RETURN_QTY,
            },
            {"movementType": "INDIVIDUAL_FULFILL", "productId": product_id, "kernelPhysicalDelta": -STOCK_FILL},
        ]
        violations = stage2.movement_trail_violations(trail, expected_trail)
        assert violations == [], f"the trail does not hold the lane's writes: {violations}\n{trail}"
        linked = [
            row
            for row in trail
            if str(row.get("orderId") or "") == order_id and str(row.get("fulfillmentId") or "") == str(stock_record["fulfillmentId"])
        ]
        assert linked, f"no movement names the fulfillment that filled the line: {order_id}"
        record(
            "INV-Q-02 / AC-03",
            f"{len(trail)} movements cover both receipts, both adjustments, the on-order adjustment, both issues, "
            f"the custody the sale consumed and the Kernel the fulfillment handed over; {len(linked)} names "
            f"fulfillment {stock_record['fulfillmentId']}, and every stock adjustment carries its reason",
        )

        # --- SS-SM-10: actual demand, and both Council Needs numbers together -----
        orders = _scout_orders(admin_token, campaign_id, scout_campaign_id)
        demand = _demand(orders, product_id)
        final_position = _positions(admin_token, campaign_id)[product_id]
        needs = stage2.council_need_positions(
            demand=demand["unfulfilledQty"],
            sellable=int(final_position["sellableKernelQty"]),
            unassigned=int(final_position["unassignedKernelQty"]),
        )
        assert demand["orderedQty"] == SALE_QTY, orders
        assert demand["fulfilledQty"] == ISSUED_QTY + STOCK_FILL, demand
        assert demand["unfulfilledQty"] == SALE_QTY - ISSUED_QTY - STOCK_FILL, demand
        assert final_position["sellableKernelQty"] == 0, (
            f"the lane was meant to end with the traded product's shelf empty: {final_position}"
        )
        owed = SALE_QTY - ISSUED_QTY - STOCK_FILL
        assert needs == {"physicalStockNeed": owed, "afterAssignmentsNeed": owed}, (
            f"with {owed} still owed and no Kernel left to sell, both Council Needs numbers must read {owed}: {needs}"
        )
        built.update({"needs": needs, "demand": demand, "finalPosition": final_position})
        record(
            "SS-SM-10 steps 2, 5-6",
            f"demand {demand['orderedQty']} for {traded}, {demand['unfulfilledQty']} still unfulfilled against "
            f"sellableKernelQty {final_position['sellableKernelQty']}; physical-stock need {needs['physicalStockNeed']} "
            f"and after-assignments need {needs['afterAssignmentsNeed']} both computed from that one read",
        )

        # --- ORD-API-02-04 / API-FIX-05: the Campaign moves, the sale does not ----
        roster_row = _roster_row(admin_token, campaign_id, scout_profile_id)
        removed = api.gql(
            admin_token,
            stage2.STAGE_TWO_SUPPORT_DOCUMENTS["removeMembership"],
            {
                "input": stage2.remove_membership_input(
                    campaign_id,
                    scout_campaign_id,
                    int(roster_row.get("version") or 1),
                    int(roster_row.get("guardVersion") or 1),
                    idempotency_key=f"{lane['data_id']}-remove",
                )
            },
        )
        assert str((removed.get("removeUnitCampaignMembership") or {}).get("status")) == "REMOVED", removed
        with _persona_session(browser, "05-scout-rejoin", identities["scout"], evidence_dir) as (scout_page, _):
            scout = ShowSellPage(scout_page)
            scout.goto_join()
            scout.join_unit_campaign(join_code, scout_profile_id)
        still_there = _scout_orders(admin_token, campaign_id, scout_campaign_id)
        assert [str(row["orderId"]) for row in still_there] == [order_id], (
            f"the sale did not stay with the Unit Campaign it was sold in: {still_there}"
        )
        assert _demand(still_there, product_id)["orderedQty"] == SALE_QTY, still_there
        history = _fulfillments(admin_token, order_id)
        assert history, f"the Order's fulfillment records vanished: {order_id}"
        assert {str(row["unitCampaignId"]) for row in history} == {campaign_id}, history
        assert {str(row["campaignId"]) for row in history} == {scout_campaign_id}, history
        still_linked = _trail(admin_token, campaign_id)
        assert [row for row in still_linked if str(row.get("orderId") or "") == order_id], (
            "the sale's movements stopped answering the Unit Campaign they were written under"
        )
        record(
            "ORD-API-02-04 / API-FIX-05",
            f"after the removal and rejoin the Order, its {len(history)} fulfillment record(s) and its "
            f"{SALE_QTY} of demand still answer {campaign_id}, and the trail still names the sale",
        )

        # --- AUTH-U: the right arguments from the wrong account answer nothing ---
        outside_token = _token_for(identities["outside"])
        other_admin_token = _token_for(identities["admin2"])
        for label, token in (("outside", outside_token), ("admin with no grant on this Unit", other_admin_token)):
            codes_answered = [item["code"] for item in _refused(token, "inventoryPositions", {"unitCampaignId": campaign_id})]
            assert codes_answered, f"{label} read {campaign_id}'s balances"
            codes_moved = [item["code"] for item in _refused(token, "scoutCustodyBalances", {"unitCampaignId": campaign_id})]
            assert codes_moved, f"{label} read {campaign_id}'s custody balances"
        after_refusals = _positions(admin_token, campaign_id)[product_id]
        assert after_refusals["kernelPhysicalQty"] == final_position["kernelPhysicalQty"], (
            "a refused read changed a balance"
        )
        record("AUTH-U-03/05", "outside and an admin with no grant here were refused on both reads, with no balance change")

        built["finished"] = True
    finally:
        _write_evidence(
            evidence_dir,
            {
                "data_id": lane["data_id"],
                "target": api.base_url(),
                "started": started,
                "lane": {
                    "unitCampaignId": built.get("unitCampaignId", ""),
                    "unitId": built.get("unitId", ""),
                    "catalogName": built.get("sharedCatalog", {}).get("catalogName", ""),
                    "catalogId": built.get("catalogId", ""),
                },
                "stoppedEarly": not built.get("finished", False),
                **{key: value for key, value in built.items() if key not in ("finished", "steps")},
            },
            steps,
            passwords,
            codes,
        )
