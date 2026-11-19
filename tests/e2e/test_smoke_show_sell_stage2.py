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
from collections.abc import Callable, Iterator, Mapping, Sequence
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

#: ``SS-SM-04`` exactly as §2.8.3 and the smoke plan name it, run live on one product: receipt 10,
#: issue 4, sale 3, sale 2 with one unit fulfilled, issue 2, return 1 — ending Kernel 5, With Scout 1
#: and total owned 6, with no double stock decrement.  The lane keeps these numbers on one product so
#: a reader can recompute them from the leaf, and pushes every other leg onto the side product below.
#: ``sale 2`` is the partial sale: it consumes what the Scout still carries (1) and stays owing the
#: rest (1), because ``ORD-API-02`` never blocks a sale for a short Scout.
RECEIVED_QTY = 10
FIRST_ISSUE_QTY = 4
FIRST_SALE_QTY = 3
SECOND_SALE_QTY = 2
SECOND_ISSUE_QTY = 2
RETURN_QTY = 1
EXPECTED_FINAL_KERNEL = 5
EXPECTED_FINAL_WITH_SCOUT = 1
EXPECTED_FINAL_OWNED = 6

#: The second product carries everything the canonical sequence would disturb: the ``SS-SM-03``
#: stock-only legs (a receipt, a +2/-1 adjustment pair, a Council-on-order adjustment that must not
#: move physical stock), the per-product custody line, and the sale that leaves a line the Scout
#: cannot fill from custody at all.  Balances key ``(unitCampaignId, productId)``, so this also shows
#: two custody balances that never share a number a sale of the other product could consume.
SIDE_PRODUCT = "Caramel Corn"
SIDE_RECEIVED_QTY = 4
SIDE_ADJUST_UP = 2
SIDE_ADJUST_DOWN = -1
ON_ORDER_QTY = 3
SIDE_ISSUE_QTY = 1
SIDE_SALE_QTY = 2

#: The ``SS-SM-10`` read needs unfulfilled demand larger than the shelf, or both Council Needs numbers
#: come back zero and prove nothing.  A sale of 8 against a Scout carrying 1 is the same
#: ``ORD-API-02`` path — consume ``min(ordered, available)``, stay owing the rest — and leaves 8
#: units of demand against 5 sellable Kernels.
DEMAND_SALE_QTY = 8
COUNCIL_FILL = 1
STOCK_FILL = 2

#: Stock the lane puts on the *other* Unit Campaign before it moves the Scout there, and never
#: touches again: the destination's own balance, which the move must leave alone.
SECOND_CAMPAIGN_QTY = 3

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


def _data_digits(data_id: str) -> str:
    """The digits of a ``DATA_ID``, which is how a sibling lane gets an id that is not a substring of this one."""
    return "".join(character for character in data_id if character.isdigit()) or "900001"


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
    data = api.gql(
        token, stage2.STAGE_TWO_SUPPORT_DOCUMENTS["campaignCatalogIdentity"], {"unitCampaignId": unit_campaign_id}
    )
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


def _campaign_custody(token: str, unit_campaign_id: str) -> dict[str, int]:
    """Products with custody on one Unit Campaign, read from the balance rows.

    ``withScoutQty`` on the ``InventoryPosition`` is the number §2.6.1 and §2.6.2 render, so the
    lane's custody claims are made on the same value the screens show.  ``scoutCustodyBalances`` is
    the participant-facing view of the same rows and is recorded beside it, but it answers a row per
    product the Scout has ever held — including the products whose custody a sale has emptied — so
    it is not compared to a ``> 0`` view of the balances.
    """
    return {
        product_id: int(row["withScoutQty"] or 0)
        for product_id, row in _positions(token, unit_campaign_id).items()
        if int(row["withScoutQty"] or 0) > 0
    }


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
    payload = _read(token, "unitScoutCampaignOrders", {"unitCampaignId": unit_campaign_id, "campaignId": campaign_id})
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


def _sale_line(sale: dict[str, Any], product_id: str, ordered: int) -> tuple[str, str]:
    """Return one door-to-door sale's ``(orderId, lineItemId)``, refusing an answer with neither.

    §5.19: the write mints the line's identity, so a lane that invents its own id ends up chasing a
    line the Order never stored — which is how the first version of this lane died.  Every later
    fulfillment, reversal and screen row keys on the id the answer carries.
    """
    order_id = str(sale.get("orderId") or "")
    assert order_id, f"the sale answered no Order: {sale!r}"
    lines = [item for item in sale.get("lineItems") or [] if str(item.get("productId")) == product_id]
    assert len(lines) == 1, f"the sale answered {len(lines)} line(s) for {product_id}: {sale!r}"
    assert int(lines[0].get("quantity") or 0) == ordered, lines[0]
    line_item_id = str(lines[0].get("lineItemId") or "")
    assert line_item_id, f"the sale answered no line identity; §5.19 says the write mints it: {sale!r}"
    return order_id, line_item_id


#: Which product reads stand in for a scan of each swept table the fixture identity cannot open.
#: Amendment B to checklist §2.8.7 accepts a table it cannot read only as residue that is named *and*
#: provable, and a DynamoDB scan is not the only way to prove a row exists: the application answers every
#: Stage 2 row class through its own queries, so the rows this lane wrote in an unreadable table are
#: enumerated through those endpoints instead.  That includes the append-only ``InventoryMovement`` rows
#: the amendment keeps on purpose — a sweep that cannot read the table cannot even count them, and
#: ``inventoryMovements`` is what names them.  A blocked table with no entry here cannot be proven either
#: way, so the record keeps that step blocked rather than calling it clean.
_RESIDUE_READS: dict[str, tuple[str, ...]] = {
    "inventory": ("inventoryPositions", "scoutCustodyBalances", "inventoryMovements"),
    "orders": ("unitScoutCampaignOrders",),
    "order-fulfillments": ("orderFulfillments",),
}


def _swept_table_key(table: str) -> str:
    """Which swept table a ``BLOCKED <table>`` line names, or ``""`` when this record cannot say.

    The sweeper prints the physical table name, which carries the environment suffix, so the match is on
    the logical key.  An unrecognized name is not guessed at: it becomes residue the record cannot prove.
    """
    name = table.lower()
    for key in _RESIDUE_READS:
        if key in name:
            return key
    return ""


def _residue_probe(
    identities: dict[str, dict[str, str]],
    unit_campaign_ids: Sequence[str],
    scout_pairs: Sequence[tuple[str, str]],
    order_ids: Sequence[str] = (),
) -> Callable[[str], str]:
    """A read that answers one lane's rows in a table the sweep could not scan.

    Scoped to the ids this lane was answered, never a whole-table read: the point is what *this* lane left
    behind, and a read that spans the stack would report other tenants' rows as this lane's residue.
    Sign-in is lazy, so a sweep that reads every table costs nothing extra, and a read this identity cannot
    make returns no answer rather than an invented one — which leaves that table unproven instead of proven
    absent.
    """
    units = [str(item) for item in unit_campaign_ids if item]
    pairs = [(str(unit), str(scout)) for unit, scout in scout_pairs if unit]
    orders = sorted({str(item) for item in order_ids if item})
    signed_in: list[str] = []

    def read_rows(document: str, variables: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        """One product read as the record states it, plus the rows it answered.

        The statement is empty when the read is refused or cannot run: a probe that failed proves nothing,
        and reporting that as an absence is the false clean this gate exists to prevent.  A ``NOT_FOUND``
        on a Campaign-keyed query means the Campaign row is gone, which says nothing about the rows that
        share its partition key — so it answers nothing here, and the record leaves that table unproven
        rather than reading an absence into it.
        """
        try:
            if not signed_in:
                signed_in.append(_token_for(identities["admin"]))
            payload = api.gql_raw(signed_in[0], stage2.STAGE_TWO_DOCUMENTS[document], variables)
        except Exception:  # noqa: BLE001 - a probe that cannot run proves nothing, and must not invent it
            return "", []
        if api.error_summaries(payload):
            return "", []
        data = (payload.get("data") or {}).get(document)
        items = data.get("items") if isinstance(data, dict) else data
        rows = [row for row in (items or []) if isinstance(row, dict)]
        return f"{document} answered {len(rows)} row(s)", rows

    def probe(table: str) -> str:
        key = _swept_table_key(table)
        if not key:
            return ""
        answers: list[str] = []
        for document in _RESIDUE_READS[key]:
            if document == "unitScoutCampaignOrders":
                for unit, scout in pairs:
                    statement, _ = read_rows(document, {"unitCampaignId": unit, "campaignId": scout})
                    if statement:
                        answers.append(statement)
            elif document == "orderFulfillments":
                # A fulfillment row is partitioned by its Order, so this lane can name one only through an
                # Order read: the Orders it sold, plus any Order its Campaigns still answer.
                named = list(orders)
                for unit, scout in pairs:
                    _, rows = read_rows("unitScoutCampaignOrders", {"unitCampaignId": unit, "campaignId": scout})
                    named += [str(row.get("orderId") or "") for row in rows]
                ids = sorted({item for item in named if item})
                if not ids:
                    answers.append(
                        "unitScoutCampaignOrders answers no Order for this lane, and an Order id is the only "
                        "key an orderFulfillments row can have"
                    )
                for order_id in ids:
                    statement, _ = read_rows(document, {"orderId": order_id})
                    if statement:
                        answers.append(f"{statement} for Order {order_id}")
            else:
                for unit in units:
                    statement, _ = read_rows(document, {"unitCampaignId": unit})
                    if statement:
                        answers.append(statement)
        return "; ".join(answers)

    return probe


def _lane_residue_probe(identities: dict[str, dict[str, str]], built: dict[str, Any]) -> Callable[[str], str]:
    """The same probe, taken from the ids a finished lane was answered — the same scope `_lane_sweep_tokens` names."""
    unit_ids = [str(built.get("unitCampaignId") or ""), *(str(item) for item in built.get("extraCampaignIds") or [])]
    scout = str(built.get("scoutCampaignId") or "")
    return _residue_probe(
        identities,
        [item for item in unit_ids if item],
        [(item, scout) for item in unit_ids if item],
        [str(item) for item in built.get("orderIds") or []],
    )


def _residue_census(identities: dict[str, dict[str, str]], built: dict[str, Any]) -> dict[str, str]:
    """What this lane leaves in each unreadable table, read while a read still answers it.

    Amendment B accepts those tables as residue only where the record can name the rows, and the window for
    naming them is before the teardown, not after the sweep.  The sweep deletes the Unit and Unit Campaign
    rows the Stage 2 reads are keyed on; afterwards ``inventoryPositions`` and ``inventoryMovements`` answer
    ``NOT_FOUND`` for the Campaign, which proves the Campaign row is gone and says nothing at all about the
    append-only movement rows that share its partition key.  So the counts are taken here and carried into
    the sweep's record, which is where a reader needs them.
    """
    probe = _lane_residue_probe(identities, built)
    return {key: probe(key) for key in _RESIDUE_READS}


def _residue_row(lane_label: str, census: Mapping[str, str]) -> dict[str, str]:
    """One record row enumerating the residue Amendment B keeps on purpose, with its counts."""
    return stage2.cleanup_row(
        f"§2.8.7 residue census / {lane_label}",
        "read before the teardown, through the endpoints the application ships for the three tables "
        "``kernelworx-qa-ue1-dev`` cannot Scan: "
        + "; ".join(f"{key}: {value or 'no read answers this lane'}" for key, value in sorted(census.items()))
        + " — the append-only ``InventoryMovement`` rows and the position rows those movements explain stay "
        "by design (``SHOW_AND_SELL_DATA_MODEL.md`` §5.8), and the Orders and fulfillment records in that "
        "count are the ones the ORD-API teardown steps take through ``deleteOrder`` and re-read absent",
    )


def _lane_table_sweep(label: str, tokens: list[str], residue: Mapping[str, str] | None = None) -> list[dict[str, str]]:
    """Remove one lane's rows through the sanctioned fixture sweeper, and record what it reported.

    The product gives a caller nothing here: the SDL carries no ``deleteUnit`` and no
    ``deleteUnitCampaign``, so the Unit and its Unit Campaign rows outlive every GraphQL teardown.
    ``scripts/qa_fixture.py sweep`` is the sanctioned path for exactly those rows.  The lane holds no
    AWS client of its own — project memory (AGENTS.md, "Show & Sell QA login fixture on the dev pool")
    says the acceptance harness has no AWS credentials, and a second path to a fixture row is a path
    that drifts.  So the lane names its own rows with typed tokens (:func:`_lane_sweep_tokens`) and the
    sweeper's per-key-shape rules decide which of them to delete, then re-scan to prove the delete
    landed.  Attribution is not enough on its own, and that was a review finding: an inventory balance
    or Scout custody row carries no account at all, only a Unit Campaign and a product, and a join-code
    pointer carries a campaign id and a timestamp — the shapes a lane actually leaves behind.

    Four classes of surviving row are reported apart, and the lane judges them apart (see
    :func:`tests.e2e.utils.show_sell_stage2_support.sweep_verdict`):

    * ``kept`` — a reviewed rule attributed the row to someone else: another account's grant, another
      profile's roster membership or custody, a marker no fixture identity wrote.  It survives, and that
      survival is the proof another tenant's data is untouched, so it never fails the sweep;
    * ``UNKNOWN`` — a row this lane's tokens named that no rule describes, or that cannot be attributed
      either way (a guard whose Scout Campaign no token names — one profile holds a guard per Campaign
      and every lane shares the fixture identities).  Never deleted, and it fails the run closed: nothing
       may be called clean while a row sits there that no rule has reviewed, amendment or no amendment;
    * ``HISTORY`` — the lane's own append-only ``InventoryMovement`` rows, which the product has no path
      to delete.  Counted and attributed, never reported as cleaned;
    * ``BLOCKED`` — a table this identity cannot read, named with the action it is denied.

    The last two are the residuals checklist §2.8.7 accepts as amended (card WORK-162, 2026-11-19):
    "clean all Stage 2 records" was written for the per-PR stack WORK-76 retired, and on shared ``dev``
    no supported path deletes a balance row or an audit movement, so the only literal satisfaction would
    be raw deletes of immutable rows in the account the stack runs in.  The amendment accepts them only
    as residue that is *named and provable*, so each blocked table is answered here by what a product read
    answers in its place (:data:`_RESIDUE_READS`), carried in from :func:`_residue_census` — which is taken
    before the teardown, because the sweep deletes the Unit and Unit Campaign rows those reads are keyed
    on, and after it a ``NOT_FOUND`` for the Campaign proves the Campaign is gone and says nothing about
    the movement rows under its key.  The sweeper stays fail-closed and exits non-zero over both classes —
    it has no amendment context — and this record says which classes the exit code was arguing about.  A
    non-zero exit that no class in the report explains, or a blocked table no product read names, is the
    lane's failure rather than an accepted residue: nothing is called clean that a re-read still answers.
    """
    argv_tail = " ".join(tokens)
    code, blocked, lines = stage2.fixture_sweep(tokens)
    deleted = sum(1 for line in lines if line.startswith("deleted row"))
    left = [line for line in lines if line.startswith("LEFT")]
    failed_rows = [line for line in lines if line.startswith("FAILED")]
    kept = [line for line in lines if line.startswith("kept")]
    unknown = [line for line in lines if line.startswith("UNKNOWN")]
    history = [line for line in lines if line.startswith("HISTORY")]

    def by_table(prefix: str, index: int) -> str:
        """How many of the sweeper's rows for one verdict fell in each table, by table label only.

        The label is the safe half of the report line: the key half carries a join code on a pointer or
        marker row, which the sweeper masks and this record does not need again.
        """
        counts: dict[str, int] = {}
        for line in lines:
            if not line.startswith(prefix):
                continue
            parts = line.split()
            if len(parts) > index:
                counts[parts[index]] = counts.get(parts[index], 0) + 1
        return ", ".join(f"{label} {count}" for label, count in sorted(counts.items()))

    def shapes() -> str:
        """Which key shapes the sweeper's rules took back, which is the part a count cannot show.

        A balance, a custody row, a join-code pointer, a roster membership and an active-join guard all
        look like nothing to an attribution rule — they carry no fixture identity — so the record names
        the shapes the reviewed rules found, read out of the sweeper's own reason for each row.
        """
        counts: dict[str, int] = {}
        for line in lines:
            if not line.startswith("row ") or "[" not in line:
                continue
            reason = line[line.find("[") + 1 : line.rfind("]")].lower()
            for shape in (
                "metadata",
                "grant",
                "membership",
                "guard",
                "pointer",
                "marker",
                "custody",
                "balance",
                "movement",
                "allocation",
                "fulfillment",
                "order",
            ):
                # Ordered, and one shape per row: a custody row's reason says
                # ``ScoutCustodyBalance``, and counting it twice would inflate the record.
                if shape in reason:
                    counts[shape] = counts.get(shape, 0) + 1
                    break
        return ", ".join(f"{count} {shape}" for shape, count in sorted(counts.items()))

    def unreadable() -> list[tuple[str, str, str]]:
        """Each table the sweep could not read, with the permission it is missing and the read that stands in.

        A count of blocked tables tells the reader the sweep is incomplete; the action in the sweeper's
        own ``BLOCKED`` line is the thing to ask an owner for, and the census answer is what makes the
        residue provable without that grant (WORK-162, Amendment B).  A table no product read answers is
        carried with an empty answer so the record cannot call it clean.
        """
        found: list[tuple[str, str, str]] = []
        for line in blocked:
            table, sep, rest = line[len("BLOCKED") :].strip().partition(": ")
            action = rest.split(" is not granted")[0] if sep else "read failed"
            answer = (residue or {}).get(_swept_table_key(table), "")
            found.append((table, action, answer))
        return found

    blocked_tables = unreadable()
    unproven = [f"{table} ({action})" for table, action, answer in blocked_tables if not answer]
    proven = [f"{table}: {answer}" for table, action, answer in blocked_tables if answer]

    counts = (
        f"{deleted} row(s) deleted ({by_table('deleted row', 2) or 'none'}; shapes: {shapes() or 'none'}), "
        f"{len(left)} left, {len(failed_rows)} delete(s) failed, "
        f"{len(kept)} row(s) reviewed as another tenant's ({by_table('kept', 1) or 'none'}), "
        f"{len(unknown)} unresolved residue row(s) ({by_table('UNKNOWN', 1) or 'none'}), "
        f"{len(history)} lane history row(s) retained ({by_table('HISTORY', 1) or 'none'})"
        + (f", {len(blocked)} table(s) unreadable" if blocked else ", 0 table(s) unreadable")
        + (f" ({'; '.join(f'{table}: {action}' for table, action, _ in blocked_tables)})" if blocked_tables else "")
        + (
            f"; residue counted by the application's own read before the teardown took it down: "
            f"{'; '.join(proven)} (the inventory rows stay by design; the Order and fulfillment counts are "
            "what the ORD-API teardown steps take through ``deleteOrder`` and re-read absent)"
            if proven
            else ""
        )
        + (f"; residue no product read can prove: {'; '.join(unproven)}" if unproven else "")
    )

    verdict = stage2.sweep_verdict(
        left=left,
        failed=failed_rows,
        unknown=unknown,
        history=history,
        blocked=blocked,
        unproven=unproven,
        exit_code=code,
    )

    if verdict == stage2.CLEANUP_OBSERVED:
        return [
            stage2.cleanup_row(
                f"§2.8.7 fixture sweep / {label}",
                f"scripts/qa_fixture.py sweep --lane {argv_tail} exited {code}: {counts}; the re-scan finds no "
                "row these rules call this lane's, and every survivor is a row a reviewed rule attributed to "
                "another tenant or one of the two residues Amendment B accepts, counted above (the report lines "
                "are not echoed here: an idempotency marker's key carries a join code, and the sweeper masks "
                "payloads for the same reason)",
            )
        ]
    detail = "; ".join(
        [
            *(line[:160] for line in (left + failed_rows + unknown)[:4]),
            *(line[:200] for line in (history + blocked)[:4]),
        ]
    )
    why = (
        "a row this lane wrote is still there"
        if left or failed_rows
        else "a row this lane's tokens named could not be attributed either way, so the sweep fails closed"
        if unknown
        else "a table this identity cannot read has no product read standing in for it, so its rows are "
        "neither removed nor provable"
        if unproven
        else "the lane's append-only movement rows are retained by decision (WORK-162, Amendment B) — "
        "counted and attributed here, never reported as cleaned"
        if history
        else "tables this identity cannot scan, with this lane's rows in each one counted by the "
        "application's own read before the teardown took them down (WORK-162, Amendment B)"
    )
    return [
        stage2.cleanup_row(
            f"§2.8.7 fixture sweep / {label}",
            f"scripts/qa_fixture.py sweep --lane {argv_tail} exited {code}: {counts} — {why}"
            + (f"; {detail}" if detail else ""),
            result=verdict,
        )
    ]


def _teardown_lane(lane_key: str, built: dict[str, Any], identities: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    """Take back every record this lane created, and return one row per step with its verdict.

    This runs in the journey's ``finally``: the run that stopped halfway is the one that most needs
    its rows gone, and a lane that only cleans up on the happy path is a lane that litters the
    deployed stack whenever it fails.  Every removal is read back through the same endpoint the
    acceptance assertions use, because a mutation that answered ``true`` is not evidence that a row
    is gone.  Each step is independent — one refusal does not stop the rest — but a refusal is
    recorded as ``failed``, and :func:`tests.e2e.utils.show_sell_stage2_support.assert_cleanup_clean`
    turns any such row into a failed run once the evidence is on disk.  A cleanup gate that can be
    satisfied by writing down a refusal is not a gate.

    What the product path removes: the Orders (whose delete takes the Order's whole fulfillment
    partition with it, ``src/handlers/campaign_operations.py``), the Scout Campaign and the seller
    profile, which cascade their Orders, the roster membership, the READ share the lane granted, and
    every balance the lane put on its Unit Campaign — zeroed, because ``inventoryMovements`` is
    append-only and the only correction the inventory model allows is the compensating row.  What it
    cannot remove — the Unit, the Unit Campaign rows, and the Stage 2 inventory partitions including
    the history — is the fixture sweep's job (``_lane_table_sweep``), and that sweep reports which
    tables it could actually read.
    """
    unit_campaign_id = str(built.get("unitCampaignId") or "")
    if not unit_campaign_id:
        return [
            stage2.cleanup_row(
                "§2.8.7 teardown",
                "nothing to take back: the lane never reached a Unit Campaign",
                result=stage2.CLEANUP_FAILED,
            )
        ]

    admin_token = _token_for(identities["admin"])
    scout_token = _token_for(identities["scout"])
    scout_profile_id = str(built.get("scoutProfileId") or "")
    scout_campaign_id = str(built.get("scoutCampaignId") or "")
    documents = stage2.STAGE_TWO_SUPPORT_DOCUMENTS
    rows: list[dict[str, str]] = []

    def step(acceptance: str, action: Callable[[], str]) -> None:
        """Run one teardown step; a refusal or an unmet read-back is a failed step, never a note.

        The verdict is the support module's (:func:`tests.e2e.utils.show_sell_stage2_support.run_cleanup_step`),
        so the rule that makes cleanup a gate is one rule, testable without a deployed stack, and a
        step that raises cannot leave the teardown early or the run green.
        """
        rows.append(stage2.run_cleanup_step(acceptance, action))

    def return_custody() -> str:
        held = _campaign_custody(admin_token, unit_campaign_id)
        if not held:
            return "no position row on this Unit Campaign carries withScoutQty"
        items = [{"productId": product_id, "quantity": quantity} for product_id, quantity in sorted(held.items())]
        _write(
            admin_token,
            "returnStockFromScout",
            {
                "input": stage2.return_input(
                    unit_campaign_id,
                    scout_campaign_id,
                    scout_profile_id,
                    items,
                    idempotency_key=f"{lane_key}-teardown-return",
                )
            },
        )
        left = _campaign_custody(admin_token, unit_campaign_id)
        assert not left, f"custody balances still hold stock after the teardown return: {left}"
        return (
            f"returned {sum(int(item['quantity']) for item in items)} unit(s) across {len(items)} custody "
            f"line(s); no position row on this Unit Campaign carries withScoutQty, and "
            f"scoutCustodyBalances answers {stage2.custody_by_product(_custody(admin_token, unit_campaign_id))}"
        )

    def zero_balances() -> str:
        cleared: list[str] = []
        for index, (product_id, position) in enumerate(sorted(_positions(admin_token, unit_campaign_id).items())):
            kernel = int(position.get("kernelPhysicalQty") or 0)
            on_order = int(position.get("councilOnOrderQty") or 0)
            if kernel > 0:
                _write(
                    admin_token,
                    "adjustInventory",
                    {
                        "input": stage2.adjust_input(
                            unit_campaign_id,
                            product_id,
                            -kernel,
                            f"Stage 2 acceptance lane {lane_key} teardown",
                            idempotency_key=f"{lane_key}-teardown-kernel-{index}",
                        )
                    },
                )
            if on_order != 0:
                _write(
                    admin_token,
                    "adjustCouncilOnOrder",
                    {
                        "input": stage2.council_on_order_input(
                            unit_campaign_id,
                            product_id,
                            -on_order,
                            idempotency_key=f"{lane_key}-teardown-council-demand-{index}",
                        )
                    },
                )
            cleared.append(product_id)
        standing = {
            product_id: row
            for product_id, row in _positions(admin_token, unit_campaign_id).items()
            if any(
                int(row.get(field) or 0) != 0 for field in ("kernelPhysicalQty", "councilOnOrderQty", "withScoutQty")
            )
        }
        assert not standing, f"the lane left a balance standing: {standing}"
        return (
            f"zeroed kernelPhysicalQty and councilOnOrderQty on {len(cleared)} product row(s) of "
            f"{unit_campaign_id}; every position that Unit Campaign owns now reads 0"
        )

    def delete_orders() -> str:
        order_ids = [str(item) for item in built.get("orderIds") or []]
        if not order_ids:
            return "the lane wrote no Order"
        for order_id in order_ids:
            # deleteOrder is the legacy Order pipeline: it is the seller profile's own record, so the
            # Unit Admin who can see the Order cannot delete it — the profile owner can ("Only profile
            # owner or users with WRITE permission can perform this action", measured on dev on
            # 2026-11-19).  The teardown therefore uses the Scout's own token here.
            answered = api.gql(scout_token, documents["deleteOrder"], {"orderId": order_id})
            assert answered.get("deleteOrder") is True, f"deleteOrder answered {answered!r} for {order_id}"
        left = _scout_orders(admin_token, unit_campaign_id, scout_campaign_id)
        assert not left, f"unitScoutCampaignOrders still answers {[row.get('orderId') for row in left]}"
        history_answers = []
        for order_id in order_ids:
            raw = api.gql_raw(admin_token, stage2.STAGE_TWO_DOCUMENTS["orderFulfillments"], {"orderId": order_id})
            errors = api.error_summaries(raw)
            items = list(((raw.get("data") or {}).get("orderFulfillments") or {}).get("items") or [])
            assert not items, f"orderFulfillments still answers {len(items)} record(s) for {order_id}"
            history_answers.append(errors[0]["code"] if errors else "0 records")
        return (
            f"deleted {len(order_ids)} Order(s) through deleteOrder; unitScoutCampaignOrders is empty and "
            f"orderFulfillments answers {history_answers} for them — the delete takes the whole fulfillment "
            "partition with the Order"
        )

    def revoke_share() -> str:
        account_id = str(built.get("shareAccountId") or "")
        if not account_id:
            return "the lane granted no share to revoke"
        answered = api.gql(
            scout_token, documents["revokeShare"], {"input": stage2.revoke_share_input(scout_profile_id, account_id)}
        )
        assert answered.get("revokeShare") is True, f"revokeShare answered {answered!r}"
        shares = (
            api.gql(scout_token, documents["shares"], {"profileId": scout_profile_id}).get("listSharesByProfile") or []
        )
        assert not shares, f"the profile still carries shares: {shares}"
        return f"revoked the READ share on {account_id}; listSharesByProfile answers none"

    def leave_roster() -> str:
        where = str(built.get("movedCampaignId") or unit_campaign_id)
        roster_row = _roster_row(admin_token, where, scout_profile_id)
        removed = api.gql(
            admin_token,
            documents["removeMembership"],
            {
                "input": stage2.remove_membership_input(
                    where,
                    scout_campaign_id,
                    int(roster_row.get("version") or 1),
                    int(roster_row.get("guardVersion") or 1),
                    idempotency_key=f"{lane_key}-teardown-roster",
                )
            },
        )
        status = str((removed.get("removeUnitCampaignMembership") or {}).get("status"))
        assert status == "REMOVED", removed
        return f"removed the Scout Campaign from {where}: roster row status {status}"

    def delete_scout_campaign() -> str:
        answered = api.gql(scout_token, documents["deleteCampaign"], {"campaignId": scout_campaign_id})
        assert answered.get("deleteCampaign") is True, f"deleteCampaign answered {answered!r}"
        gone = api.gql(scout_token, documents["scoutCampaign"], {"campaignId": scout_campaign_id}).get("getCampaign")
        assert gone is None, f"getCampaign still answers the deleted Scout Campaign: {gone!r}"
        listed = api.gql(scout_token, documents["scoutCampaigns"], {"profileId": scout_profile_id})
        rows_listed = (listed.get("listCampaignsByProfile") or {}).get("campaigns") or []
        assert scout_campaign_id not in {str(row.get("campaignId")) for row in rows_listed}, rows_listed
        return f"deleted Scout Campaign {scout_campaign_id}; getCampaign answers null and the profile lists none"

    def delete_profile() -> str:
        answered = api.gql(scout_token, documents["deleteProfile"], {"profileId": scout_profile_id})
        assert answered.get("deleteProfile") is True or answered.get("deleteSellerProfile") is True, answered
        profiles = api.gql(scout_token, documents["profiles"], {"limit": 200}).get("listMyProfiles") or {}
        names = [str(row.get("sellerName")) for row in profiles.get("profiles") or []]
        assert str(built.get("scoutName") or "") not in names, (
            f"profile {built.get('scoutName')} is still listed: {names}"
        )
        return f"deleted seller profile {scout_profile_id} and with it the Campaigns and Orders under it; listMyProfiles no longer lists it"

    def deactivate_lane_campaigns() -> str:
        # Only the Campaigns this run created.  Lane construction reuses a Unit that already carries
        # this run's tenant key (``unitCreation`` says so), so the Unit's campaign list is not the
        # lane's own: a Campaign another run left on the same Unit is that run's business, and a
        # teardown that switched it off would be a second lane writing to a tenant it does not own.
        created = {unit_campaign_id, *(str(item) for item in built.get("extraCampaignIds") or [])}
        rows_read = (
            api.gql(admin_token, documents["unitCampaigns"], {"unitId": str(built.get("unitId") or "")}).get(
                "unitCampaigns"
            )
            or {}
        ).get("items") or []
        off = 0
        not_ours = sorted(
            str(row.get("unitCampaignId")) for row in rows_read if str(row.get("unitCampaignId")) not in created
        )
        for row in rows_read:
            if str(row["unitCampaignId"]) not in created or not row.get("isActive"):
                continue
            api.gql(
                admin_token,
                documents["deactivateUnitCampaign"],
                {
                    "input": stage2.deactivate_unit_campaign_input(
                        str(row["unitCampaignId"]),
                        int(row.get("version") or 1),
                        idempotency_key=f"{lane_key}-teardown-deactivate-{off}",
                    )
                },
            )
            off += 1
        still_on = [
            str(row.get("unitCampaignId"))
            for row in _read_unit_campaigns(admin_token, built)
            if row.get("isActive") and str(row.get("unitCampaignId")) in created
        ]
        assert not still_on, f"the lane left one of its own Unit Campaigns active: {still_on}"
        left_alone = (
            f", and left {len(not_ours)} Campaign(s) on that Unit this run did not create untouched ({', '.join(not_ours)})"
            if not_ours
            else ", and every Campaign on that Unit belongs to this run"
        )
        return (
            f"deactivated {off} of the {len(created)} Unit Campaign(s) this run created on Unit "
            f"{built.get('unitId')} so nothing here can be picked up by another lane{left_alone}; the rows "
            "themselves go in the table sweep"
        )

    def history_is_immutable() -> str:
        written = int(built.get("movementCount") or 0)
        after = _trail(admin_token, unit_campaign_id)
        assert len(after) >= written, f"the trail shrank from {written} rows to {len(after)}: movements are append-only"
        return (
            f"{len(after)} movement rows answer the Unit Campaign, at or above the {written} the acceptance "
            "steps wrote: the teardown's own corrections were appended as new rows, and no history row vanished"
        )

    step("§2.8.7 teardown / INV-M-05", return_custody)
    step("§2.8.7 teardown / INV-M-02-03", zero_balances)
    step("§2.8.7 teardown / ORD-API", delete_orders)
    step("§2.8.7 teardown / AUTH-P", revoke_share)
    step("§2.8.7 teardown / API-FIX-02", leave_roster)
    step("§2.8.7 teardown / API-FIX-01-02", delete_scout_campaign)
    step("§2.8.7 teardown / API-FIX-01", delete_profile)
    step("§2.8.7 teardown / §2.6.1", deactivate_lane_campaigns)
    step("§2.8.7 audit immutability", history_is_immutable)
    return rows


def _read_unit_campaigns(admin_token: str, built: dict[str, Any]) -> list[dict[str, Any]]:
    """Every Unit Campaign row the finished lane owns."""
    return list(
        (
            api.gql(
                admin_token,
                stage2.STAGE_TWO_SUPPORT_DOCUMENTS["unitCampaigns"],
                {"unitId": str(built.get("unitId") or "")},
            ).get("unitCampaigns")
            or {}
        ).get("items")
        or []
    )


def _bare_id(value: str, prefix: str) -> str:
    """One id with its storage prefix removed (``PROFILE#x`` to ``x``), when it carries one.

    The same identity reaches a caller in two spellings — ``listMyProfiles`` answers ``PROFILE#<uuid>``
    while a Unit id is a bare UUID — and ``sweep`` wants the bare form its token shapes describe.
    """
    head, sep, rest = value.partition("#")
    return rest if sep and head == prefix else value


def _lane_sweep_tokens(data_id: str, built: dict[str, Any]) -> list[str]:
    """The typed tokens one finished lane can honestly name, and the only kind ``sweep`` accepts.

    ``scripts/qa_fixture.py sweep`` refuses a token that names no kind: it runs with ``--yes`` already given, so
    free text like a bare ``DATA_ID`` is a run that deletes rows somebody else named.  A kind is
    compared only to the field it names, which is why the lane hands over every identity its rows are
    keyed on rather than a prefix that happens to appear in their payloads:

    * ``data-id`` — the run's own id, which the Unit display name, every Unit Campaign name, the seller
      profile name and every idempotency key it sent carry;
    * ``unit`` / ``unit-campaign`` / ``campaign`` (Scout) / ``profile`` — the ids the lane was answered,
      including the move leg's destination campaign and the Scout Campaign its Scout joined;
    * ``join-code`` — every code the lane minted, so the pointer row it left is named (the sweeper
      masks the code in its own report, and ``codes`` masks it in the evidence);
    * ``order`` — the Orders the lane sold, in the ``ORDER#<campaign>#<suffix>`` spelling ``build_order_id``
      mints, which is also the fulfillment partition key.

    A prior run's join code is not recoverable once its Unit Campaign rows are gone, and its Scout
    Campaign ids are read from that Campaign's roster before its profile is deleted — which is what
    lets :func:`_sweep_prior_lanes` name an active-join guard exactly.  A guard it cannot name is left
    and reported: matching a guard by ``profileId`` alone would reach every Campaign that shared
    fixture Scout has ever joined, including another lane's.
    """
    tokens: list[str] = []

    def add(kind: str, raw: Any, prefix: str = "") -> None:
        value = _bare_id(str(raw or ""), prefix)
        if value and f"{kind}={value}" not in tokens:
            tokens.append(f"{kind}={value}")

    add("data-id", data_id)
    add("unit", built.get("unitId"), "UNIT")
    add("unit-campaign", built.get("unitCampaignId"), "CAMPAIGN")
    for extra in built.get("extraCampaignIds") or []:
        add("unit-campaign", extra, "CAMPAIGN")
    add("campaign", built.get("scoutCampaignId"), "CAMPAIGN")
    add("profile", built.get("scoutProfileId"), "PROFILE")
    add("join-code", built.get("joinCode"))
    for code in built.get("extraJoinCodes") or []:
        add("join-code", code)
    for order_id in built.get("orderIds") or []:
        add("order", order_id)
    return tokens


def _build_lane_records(
    browser: Browser,
    identities: dict[str, dict[str, str]],
    evidence_dir: Path,
    codes: list[str],
    names: dict[str, str],
    catalog_name: str,
    tag: str,
) -> dict[str, Any]:
    """Build one lane's records through the product's own screens: Unit, Unit Campaign, profile, join.

    Both the acceptance lane and the canary lane are built here, which is the point: the canary is
    not a lighter thing the lane creates for show, it is the same construction under a different
    ``DATA_ID``, so "the teardown left the other lane alone" is a claim about a real lane.

    Args:
        tag: prefix for this lane's persona labels.

    Returns:
        ``unitId``, ``unitCampaignId``, ``joinCode``, ``scoutProfileId``, ``scoutCampaignId``,
        ``scoutName``, ``unitCreation``.
    """
    admin_token = _token_for(identities["admin"])
    with _persona_session(browser, f"{tag}-admin", identities["admin"], evidence_dir) as (admin_page, _):
        admin = ShowSellPage(admin_page)
        admin.goto_units()
        existing = _unit_for_key(admin_token, names["unit_number"])
        if existing:
            unit_id, unit_creation = existing, "reused"
        else:
            unit_id, duplicate_confirm = admin.create_unit(
                unit_type=UNIT_TYPE,
                unit_number=names["unit_number"],
                city=UNIT_CITY,
                state=UNIT_STATE,
                display_name=names["unit_display_name"],
            )
            unit_creation = "separate-duplicate" if duplicate_confirm else "created"
        admin.goto_unit(unit_id)
        admin.open_tab("tab-campaigns")
        campaign_id, join_code = admin.create_campaign(
            name=names["campaign_name"], year=CAMPAIGN_YEAR, catalog_name=catalog_name
        )
        codes.append(join_code)

    with _persona_session(browser, f"{tag}-scout", identities["scout"], evidence_dir) as (scout_page, scout_token):
        _ensure_scout_profile(scout_page, names["scout_name"])
        scout_profile_id = _profile_id_for(scout_token, names["scout_name"])
        campaigns = CampaignPage(scout_page)
        campaigns.goto(scout_profile_id)
        if not campaigns.has_campaign(names["campaign_name"]):
            campaigns.create_campaign_on_catalog(
                names["campaign_name"], profile_id=scout_profile_id, catalog_name=catalog_name
            )
        scout_campaign_id = _scout_campaign_id_for(scout_token, scout_profile_id, names["campaign_name"])

    with _persona_session(browser, f"{tag}-scout-join", identities["scout"], evidence_dir) as (scout_page, _):
        scout = ShowSellPage(scout_page)
        scout.goto_join()
        scout.join_unit_campaign(join_code, scout_profile_id)

    return {
        "unitId": unit_id,
        "unitCampaignId": campaign_id,
        "joinCode": join_code,
        "scoutProfileId": scout_profile_id,
        "scoutCampaignId": scout_campaign_id,
        "scoutName": names["scout_name"],
        "unitCreation": unit_creation,
    }


def _seed_records(data_id: str, built: dict[str, Any], identities: dict[str, dict[str, str]], quantity: int) -> None:
    """Put stock, custody and one sale on a finished lane, so its rows are the shape the sweep must find."""
    admin_token = _token_for(identities["admin"])
    campaign_id = str(built["unitCampaignId"])
    products = _catalog_product_ids(admin_token, campaign_id)
    product_id = products[_traded_product(products)]
    built["productId"] = product_id
    _write(
        admin_token,
        "recordInventoryReceipt",
        {"input": stage2.receipt_input(campaign_id, product_id, quantity, idempotency_key=f"{data_id}-seed-receipt")},
    )
    _write(
        admin_token,
        "issueStockToScout",
        {
            "input": stage2.issue_input(
                campaign_id,
                str(built["scoutCampaignId"]),
                str(built["scoutProfileId"]),
                product_id,
                2,
                idempotency_key=f"{data_id}-seed-issue",
            )
        },
    )
    sale = _write(
        admin_token,
        "createOrder",
        {
            "input": stage2.custody_sale_input(
                str(built["scoutProfileId"]),
                str(built["scoutCampaignId"]),
                product_id,
                1,
                "Canary Door",
                idempotency_key=f"{data_id}-seed-sale",
            )
        },
    )
    built["orderIds"] = [str(sale["orderId"])]


def _lane_snapshot(built: dict[str, Any], identities: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Everything another lane's teardown could disturb, in one comparable value."""
    admin_token = _token_for(identities["admin"])
    campaign_id = str(built["unitCampaignId"])
    positions = {
        product_id: {key: value for key, value in row.items() if key not in ("updatedAt", "version")}
        for product_id, row in _positions(admin_token, campaign_id).items()
    }
    orders = _scout_orders(admin_token, campaign_id, str(built["scoutCampaignId"]))
    # A quantity the read never asked for comes back missing, and ``or 0`` turns that into a number:
    # the first version of this snapshot reported "0 units ordered" for a canary that had a sale, so
    # the sum walks the line items the document does select and refuses an answer that has none.
    ordered = 0
    for row in orders:
        lines = list(row.get("lineItems") or [])
        assert lines, f"unitScoutCampaignOrders answered an Order with no line items: {row!r}"
        for line in lines:
            ordered += int(line.get("quantity") or 0)
    fulfillments = []
    for row in orders:
        fulfillments.extend(_fulfillments(admin_token, str(row["orderId"])))
    active = [str(row.get("unitCampaignId")) for row in _read_unit_campaigns(admin_token, built) if row.get("isActive")]
    return {
        "unitCampaignId": campaign_id,
        # The teardown's last GraphQL step deactivates Unit Campaigns.  A canary whose campaign was
        # switched off would otherwise still answer the same balances, positions and roster row, so
        # the active flag is part of what has to survive.
        "unitCampaignActive": campaign_id in active,
        "positions": positions,
        "custody": stage2.custody_by_product(_custody(admin_token, campaign_id)),
        "movementRows": len(_trail(admin_token, campaign_id)),
        "orders": sorted(str(row["orderId"]) for row in orders),
        "orderedQty": ordered,
        "fulfillmentRows": len(fulfillments),
        "rosterStatus": str(_roster_row(admin_token, campaign_id, str(built["scoutProfileId"])).get("status")),
    }


def _canary_survived(
    before: dict[str, Any], after: dict[str, Any], canary: dict[str, Any], identities: dict[str, dict[str, str]]
) -> dict[str, str]:
    """Compare the canary lane with itself, before the lane's teardown and after it."""
    changed = {key: (before[key], after[key]) for key in before if before[key] != after[key]}
    if changed:
        return stage2.cleanup_row(
            "§2.8.7 independent lane survived",
            f"the teardown disturbed the canary lane {canary['data_id']}: "
            + "; ".join(f"{key}: {value[0]!r} became {value[1]!r}" for key, value in sorted(changed.items())),
            result=stage2.CLEANUP_FAILED,
        )
    return stage2.cleanup_row(
        "§2.8.7 independent lane survived",
        f"canary lane {canary['data_id']} (Unit {canary['unitId']}, Unit Campaign {canary['unitCampaignId']}) "
        f"answers the same {len(before['positions'])} position row(s), {before['movementRows']} movement row(s), "
        f"{len(before['orders'])} Order(s) totalling {before['orderedQty']} units across their line items, "
        f"{before['fulfillmentRows']} fulfillment record(s), roster status {before['rosterStatus']} and "
        f"Unit Campaign isActive {before['unitCampaignActive']} after the lane's teardown as it did before it",
    )


def _sweep_prior_lanes(
    identities: dict[str, dict[str, str]],
    prior_ids: list[str],
    keep: str,
) -> list[dict[str, str]]:
    """Take back what earlier runs of this lane left, by attribution, and prove each one is gone.

    A prior ``DATA_ID`` names the rows its run created: the Unit number is derived from its digits,
    and its Unit Campaign and seller profile carry the id in their names, so the sweep looks for
    exactly those shapes and cannot catch a row it did not create.  That derivation is the lane's own
    naming rule, so a sibling lane whose Unit number does not follow it — the canary's Unit is the
    lane's number plus one — is not a value this takes: it would read for a Unit number that run never
    used.  Each named id is reported in one
    of three honest forms — *removed* (found, taken back, and gone on the re-read), *already gone*
    (nothing in ``myUnits``, the Unit Campaign list or ``listMyProfiles`` names it: verified by
    reading, not assumed), or *failed* (it is still there).  A bare "deactivated 0, deleted 0" is not
    one of them: that is how a sweep that found nothing could once pass for a sweep that cleaned
    something.

    The product path reaches the seller profile (whose cascade takes the Scout Campaign and its
    Orders) and can only deactivate a Unit Campaign; the Unit and Unit Campaign rows, the roster row
    a removal keeps, and the active-join guard a removal keeps go through the fixture sweep, which is
    why the verification read comes after it.  The sweep reaches a guard only by its exact Scout
    Campaign id, so this reads the roster of each prior Unit Campaign while the join still exists and
    names those ids: a guard it cannot name is reported by the sweep as unresolved rather than deleted
    on the strength of a shared fixture profile.  That roster read is also what lets the Stage 2 tables
    the fixture identity cannot scan be answered per prior Campaign by :func:`_residue_probe` — an
    unreadable table is accepted as residue only where a product read names the rows in it.
    """
    admin_token = _token_for(identities["admin"])
    scout_token = _token_for(identities["scout"])
    documents = stage2.STAGE_TWO_SUPPORT_DOCUMENTS
    wanted = [item for item in prior_ids if item and item != keep]
    if not wanted:
        return [stage2.cleanup_row("§2.8.7 prior-lane sweep", "no earlier DATA_IDs named, nothing to sweep")]

    def unit_rows() -> dict[int, str]:
        return {
            int(row.get("unitNumber") or 0): str(row.get("unitId"))
            for row in (api.gql(admin_token, documents["myUnits"], {"page": {"limit": 100}}).get("myUnits") or {}).get(
                "items"
            )
            or []
        }

    def scout_names() -> list[str]:
        listed = api.gql(scout_token, documents["profiles"], {"limit": 200}).get("listMyProfiles") or {}
        return [str(row.get("sellerName")) for row in listed.get("profiles") or []]

    rows: list[dict[str, str]] = []
    for data_id in wanted:
        number = int(_unit_number(data_id))
        wanted_name = SCOUT_NAME_TEMPLATE.format(data_id=data_id)
        campaign_prefix = CAMPAIGN_TEMPLATE.format(data_id=data_id)

        unit_id = unit_rows().get(number)
        campaign_ids: list[str] = []
        scout_campaign_ids: list[str] = []
        found_campaigns = 0
        active_off = 0
        if unit_id:
            campaign_rows = (
                api.gql(admin_token, documents["unitCampaigns"], {"unitId": unit_id}).get("unitCampaigns") or {}
            ).get("items") or []
            for row in campaign_rows:
                if not str(row.get("campaignName") or "").startswith(campaign_prefix):
                    continue
                found_campaigns += 1
                campaign_ids.append(str(row["unitCampaignId"]))
                # The roster of a Unit Campaign this run named holds only that run's joins, and it
                # answers the Scout Campaign id each join used — the exact identity the sweep's
                # active-join guard rule needs.  Read it here, while the join still exists.
                roster_rows = (
                    api.gql(
                        admin_token,
                        documents["roster"],
                        {"unitCampaignId": str(row["unitCampaignId"])},
                    ).get("unitCampaignRoster")
                    or {}
                ).get("items") or []
                scout_campaign_ids += [_bare_id(str(r.get("campaignId") or ""), "CAMPAIGN") for r in roster_rows]
                if not row.get("isActive"):
                    continue
                api.gql(
                    admin_token,
                    documents["deactivateUnitCampaign"],
                    {
                        "input": stage2.deactivate_unit_campaign_input(
                            str(row["unitCampaignId"]),
                            int(row.get("version") or 1),
                            idempotency_key=f"{data_id}-sweep-{row['unitCampaignId']}",
                        )
                    },
                )
                active_off += 1
        profiles = [
            (str(row.get("profileId")), str(row.get("sellerName")))
            for row in (api.gql(scout_token, documents["profiles"], {"limit": 200}).get("listMyProfiles") or {}).get(
                "profiles"
            )
            or []
        ]
        profiles_found = [profile_id for profile_id, seller_name in profiles if seller_name == wanted_name]
        for profile_id in profiles_found:
            api.gql(scout_token, documents["deleteProfile"], {"profileId": profile_id})

        # Those reads are what this run can honestly name about an earlier one: its Unit, the Unit
        # Campaigns under it, those Campaigns' roster joins, and the seller profile whose name carries
        # its DATA_ID.  The roster read names each prior Scout Campaign exactly, which is what the
        # sweep's guard rule needs: ``build_membership_guard_item`` writes one guard per Scout Campaign
        # and every lane shares the four fixture identities, so a ``profile`` token alone cannot say
        # which of that person's Campaigns is joined without reaching another run's guard.
        prior_tokens = _lane_sweep_tokens(data_id, {})
        if unit_id:
            prior_tokens.append(f"unit={_bare_id(unit_id, 'UNIT')}")
        prior_tokens += [f"unit-campaign={_bare_id(uc, 'CAMPAIGN')}" for uc in campaign_ids]
        prior_tokens += [f"campaign={cid}" for cid in dict.fromkeys(scout_campaign_ids) if cid]
        prior_tokens += [f"profile={_bare_id(p, 'PROFILE')}" for p in profiles_found]
        # The sweep runs even when the three reads answer nothing: a prior run's idempotency markers
        # are keyed on that run's DATA_ID alone, and the sweep reaches them when its Unit row is long gone.
        # No residue census is possible for an earlier run: its Unit Campaign rows are already gone, so no
        # Stage 2 read can count what it left in a table this identity cannot Scan, and the record says that
        # rather than calling the step clean.
        swept = _lane_table_sweep(f"prior lane {data_id}", prior_tokens, None)
        rows.extend(swept)
        unmet = [row for row in swept if row["result"] != stage2.CLEANUP_OBSERVED]
        if any(row["result"] == stage2.CLEANUP_FAILED for row in unmet):
            rows.append(
                stage2.cleanup_row(
                    "§2.8.7 prior-lane sweep",
                    f"{data_id}: Unit {unit_id} carried {found_campaigns} Unit Campaign(s) and {len(profiles_found)} "
                    "seller profile(s); the fixture sweep reported a row it could not remove",
                    result=stage2.CLEANUP_FAILED,
                )
            )
            continue
        if unmet:
            rows.append(
                stage2.cleanup_row(
                    "§2.8.7 prior-lane sweep",
                    f"{data_id}: the sweep could not read every Stage 2 table for this identity, so that part is "
                    "recorded as blocked rather than cleaned; the reads below still show what this run removed",
                    result=stage2.CLEANUP_BLOCKED,
                )
            )

        unit_after = unit_rows().get(number)
        name_after = wanted_name in scout_names()
        if unit_after or name_after:
            rows.append(
                stage2.cleanup_row(
                    "§2.8.7 prior-lane sweep",
                    f"{data_id}: still present after the sweep — Unit number {number} answers "
                    f"{unit_after or 'nothing'} and listMyProfiles answers "
                    f"{wanted_name if name_after else 'no such seller name'}",
                    result=stage2.CLEANUP_FAILED,
                )
            )
            continue
        if not unit_id and not found_campaigns and not profiles_found:
            rows.append(
                stage2.cleanup_row(
                    "§2.8.7 prior-lane sweep",
                    f"{data_id}: nothing to remove — no Unit row for number {number}, no Unit Campaign named "
                    f"{campaign_prefix!r}, no seller profile named {wanted_name!r}, and the re-read confirms all "
                    "three are still absent (this lane's rows were taken back earlier, and that is verified, not assumed)",
                )
            )
            continue
        rows.append(
            stage2.cleanup_row(
                "§2.8.7 prior-lane sweep",
                f"{data_id}: found {found_campaigns} Unit Campaign(s) on Unit {unit_id or 'no row for number ' + str(number)} "
                f"({active_off} deactivated, the rest already inactive), {len(dict.fromkeys(scout_campaign_ids))} "
                f"roster join(s) naming those Campaigns' Scout Campaigns, and {len(profiles_found)} seller "
                f"profile(s) named {wanted_name}; the profile delete cascaded that Scout Campaign and its Orders, "
                "the fixture sweep took the Unit, Unit Campaign, roster and named active-join guard rows, and the "
                "re-read answers no Unit for that number and no such seller name",
            )
        )
    return rows


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

    Two fixtures frame the journey.  An **independent canary lane** — its own Unit, Unit Campaign,
    seller profile, Scout Campaign and roster join under its own ``DATA_ID`` — is built before this
    lane writes a single row, and the record proves the lane's teardown left it standing, then takes
    it down with the same teardown so nothing is left behind.  And the **cleanup gate** is a gate:
    every teardown step reports a verdict, the evidence is written before any of it is judged, and a
    refused deletion or a disturbed canary fails the run rather than being filed as an observation.

    Args:
        browser: the session Playwright browser.
        identities: the standing fixture identities.
        lane: DATA_ID-suffixed row names for this run.
        evidence_dir: artifact directory for this run.
    """
    steps: list[dict[str, Any]] = []
    cleanup: list[dict[str, str]] = []
    codes: list[str] = []
    passwords: list[str] = [identity["password"] for identity in identities.values()]
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    built: dict[str, Any] = {}
    canary: dict[str, Any] = {}
    canary_before: dict[str, Any] = {}

    def record(acceptance: str, summary: str, result: str = "observed") -> None:
        """Append one acceptance observation to the record."""
        steps.append({"order": len(steps) + 1, "acceptance": acceptance, "result": result, "summary": summary})

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

        # --- A second lane, standing on its own, before this one writes anything ---
        #
        # Acceptance item 5 asks for a canary that proves *another lane's* data is untouched.  A
        # second Unit Campaign inside this lane proves nothing of the kind: it is this lane's row,
        # made by this run, and this run's sweep is free to define it out of the set.  So the canary
        # is built the same way a lane is built — its own Unit, Unit Campaign, seller profile, Scout
        # Campaign, roster join — under its own DATA_ID, seeded with a receipt, a custody issue and a
        # sale, then snapshotted.  The teardown later has to leave that snapshot standing, and the
        # canary is then torn down by the same teardown so the record can also show the sweep takes
        # its own lane's rows when it is pointed at them.
        # The canary's id must not contain the lane's id as a substring, and its Unit number is the
        # lane's plus one.  The first run of this shape named the canary ``<data_id>-can``, and the
        # sweep then matched a lane token as a substring of any string in a row, so the lane's own
        # sweep defined the canary out of existence and the survival read answered ``Unit Campaign
        # not found``: the gate worked, on a canary that was never independent.  ``sweep`` matches a
        # kind only against the field that kind names now, and the ids stay disjoint by construction,
        # because a canary the lane's tokens can name is a canary the lane can take back.
        canary_id = f"stage2can-{_data_digits(lane['data_id'])}"
        canary_names = {
            "data_id": canary_id,
            "unit_number": str(int(lane["unit_number"]) + 1),
            "unit_display_name": f"Stage 2 Pack {canary_id}",
            "campaign_name": CAMPAIGN_TEMPLATE.format(data_id=canary_id),
            "scout_name": SCOUT_NAME_TEMPLATE.format(data_id=canary_id),
        }
        canary.update(
            _build_lane_records(browser, identities, evidence_dir, codes, canary_names, catalog_name, "00-canary")
        )
        canary["data_id"] = canary_names["data_id"]
        _seed_records(canary_names["data_id"], canary, identities, 4)
        canary_before = _lane_snapshot(canary, identities)
        built["canaryLane"] = {
            key: canary.get(key, "") for key in ("data_id", "unitId", "unitCampaignId", "scoutProfileId")
        }
        record(
            "§2.8.7 independent lane standing",
            f"canary lane {canary['data_id']}: Unit {canary['unitId']}, Unit Campaign {canary['unitCampaignId']}, "
            f"Scout Campaign {canary['scoutCampaignId']}; seeded with a receipt, a custody issue and one sale — "
            f"{canary_before['movementRows']} movement row(s), {canary_before['orderedQty']} unit(s) ordered",
        )

        # --- The lane: Unit, Unit Campaign, Scout profile, Scout Campaign, join ---
        built.update(_build_lane_records(browser, identities, evidence_dir, codes, lane, catalog_name, "01-lane"))
        unit_id = str(built["unitId"])
        campaign_id = str(built["unitCampaignId"])
        scout_profile_id = str(built["scoutProfileId"])
        scout_campaign_id = str(built["scoutCampaignId"])
        scout_token = _token_for(identities["scout"])
        record(
            "API-FIX-01",
            f"{UNIT_TYPE} {lane['unit_number']} → Unit {unit_id}, Unit Campaign {campaign_id} ({built['unitCreation']})",
        )
        record(
            "API-FIX-01/02",
            f"Scout profile {scout_profile_id} holds campaign {scout_campaign_id}",
        )
        record(
            "API-FIX-02",
            f"Scout Campaign {scout_campaign_id} joined Unit Campaign {campaign_id} on the roster screen using "
            f"join code {built['joinCode']} (this record is redacted before it is written)",
        )

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
                f"{unit_catalog['catalogId']} carries one product only: the SS-SM-03 stock-only legs have "
                "to sit on a different product, or the canonical SS-SM-04 ending numbers stop being the "
                "smoke plan's"
            )
        side_name = SIDE_PRODUCT if SIDE_PRODUCT in others else others[0]
        side_product_id = products[side_name]
        built.update(
            {
                "catalogId": unit_catalog["catalogId"],
                "product": traded,
                "productId": product_id,
                "sideProduct": side_name,
                "sideProductId": side_product_id,
            }
        )
        record(
            "UNIT-06 / catalog identity",
            f"both Campaigns sell from {unit_catalog['catalogId']}; the lane trades {traded} ({product_id}) "
            f"and runs its stock-only legs on {side_name} ({side_product_id})",
        )

        # --- SS-SM-03: stock-only writes, on the side product ---------------------
        #
        # The receipt, the +2/-1 adjustment pair and the Council-on-order adjustment all sit on a
        # product the canonical SS-SM-04 sequence never touches.  That is deliberate: §2.8.3 names
        # the ending balances of that sequence, and an adjustment landing on the same product would
        # replace the leaf's numbers with arithmetic of the lane's own making.
        side_receipt = _write(
            admin_token,
            "recordInventoryReceipt",
            {
                "input": stage2.receipt_input(
                    campaign_id, side_product_id, SIDE_RECEIVED_QTY, idempotency_key=f"{lane['data_id']}-side-receipt"
                )
            },
        )
        raise_adjust = _write(
            admin_token,
            "adjustInventory",
            {
                "input": stage2.adjust_input(
                    campaign_id,
                    side_product_id,
                    SIDE_ADJUST_UP,
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
                    side_product_id,
                    SIDE_ADJUST_DOWN,
                    "Gift to outgoing volunteer",
                    idempotency_key=f"{lane['data_id']}-lower",
                )
            },
        )
        council_adjust = _write(
            admin_token,
            "adjustCouncilOnOrder",
            {
                "input": stage2.council_on_order_input(
                    campaign_id, side_product_id, ON_ORDER_QTY, idempotency_key=f"{lane['data_id']}-council"
                )
            },
        )
        assert side_receipt["kernelPhysicalQty"] == SIDE_RECEIVED_QTY, side_receipt
        assert raise_adjust["kernelPhysicalQty"] == SIDE_RECEIVED_QTY + SIDE_ADJUST_UP, raise_adjust
        assert lower_adjust["kernelPhysicalQty"] == SIDE_RECEIVED_QTY + SIDE_ADJUST_UP + SIDE_ADJUST_DOWN, lower_adjust
        assert lower_adjust["soldInPossessionQty"] == 0, lower_adjust
        assert council_adjust["councilOnOrderQty"] == ON_ORDER_QTY, council_adjust
        assert council_adjust["kernelPhysicalQty"] == SIDE_RECEIVED_QTY + SIDE_ADJUST_UP + SIDE_ADJUST_DOWN, (
            f"the Council-on-order adjustment moved physical stock: {council_adjust}"
        )
        half_positions = _positions(admin_token, campaign_id)
        assert product_id not in half_positions, (
            f"the traded product answered a balance row before any stock was received for it: {half_positions[product_id]}"
        )
        record(
            "SS-SM-03 steps 4-6",
            f"{side_name}: receipt {side_receipt['kernelPhysicalQty']}, adjustments +{SIDE_ADJUST_UP}"
            f"/{SIDE_ADJUST_DOWN} → {lower_adjust['kernelPhysicalQty']}, on-order "
            f"{council_adjust['councilOnOrderQty']} with kernelPhysicalQty unchanged; {traded} still has no "
            "balance row at all",
        )

        # --- IDEM-01: the same key replays the answer, it does not write again -----
        #
        # The replay answers the *first* call's payload while the persisted row is exactly where the
        # first call left it.  Both halves matter: an answer that re-ran the write would double the
        # shelf, and a row that moved would mean the write ran again and only its response was
        # rebuilt.  The keys are derived from ``DATA_ID``, so a pinned re-run of this lane replays
        # every write below and changes nothing on the stack — which is why a run meant as fresh
        # evidence takes a fresh ``DATA_ID``.
        receipt = _write(
            admin_token,
            "recordInventoryReceipt",
            {
                "input": stage2.receipt_input(
                    campaign_id, product_id, RECEIVED_QTY, idempotency_key=f"{lane['data_id']}-receipt"
                )
            },
        )
        receipt_replay = _write(
            admin_token,
            "recordInventoryReceipt",
            {
                "input": stage2.receipt_input(
                    campaign_id, product_id, RECEIVED_QTY, idempotency_key=f"{lane['data_id']}-receipt"
                )
            },
        )
        assert receipt_replay == receipt, f"the replay answered something other than the first call: {receipt_replay!r}"
        after_replay = _positions(admin_token, campaign_id)[product_id]
        assert after_replay["kernelPhysicalQty"] == RECEIVED_QTY, (
            f"the replayed receipt key wrote stock again: {after_replay}"
        )
        assert after_replay["version"] == receipt["version"], (
            f"the replayed receipt key rewrote the balance row: {after_replay!r} != {receipt!r}"
        )
        record(
            "IDEM-01",
            f"replayed receipt key answers the original v{receipt['version']} payload (kernel "
            f"{receipt['kernelPhysicalQty']}) and the row is still v{after_replay['version']} kernel "
            f"{after_replay['kernelPhysicalQty']}, not {RECEIVED_QTY * 2}",
        )

        # --- SS-SM-04 step 1 / INV-M-04-01: issue 4, and a second custody balance --
        first_issue = _write(
            admin_token,
            "issueStockToScout",
            {
                "input": stage2.issue_input(
                    campaign_id,
                    scout_campaign_id,
                    scout_profile_id,
                    product_id,
                    FIRST_ISSUE_QTY,
                    idempotency_key=f"{lane['data_id']}-issue-1",
                )
            },
        )
        assert first_issue["inventoryPosition"]["kernelPhysicalQty"] == RECEIVED_QTY - FIRST_ISSUE_QTY, first_issue
        assert first_issue["custodyBalance"]["withScoutQty"] == FIRST_ISSUE_QTY, first_issue
        side_issue = _write(
            admin_token,
            "issueStockToScout",
            {
                "input": stage2.issue_input(
                    campaign_id,
                    scout_campaign_id,
                    scout_profile_id,
                    side_product_id,
                    SIDE_ISSUE_QTY,
                    idempotency_key=f"{lane['data_id']}-issue-side",
                )
            },
        )
        assert side_issue["custodyBalance"]["productId"] == side_product_id, side_issue
        after_issues = _positions(admin_token, campaign_id)
        assert after_issues[product_id]["withScoutQty"] == FIRST_ISSUE_QTY, after_issues[product_id]
        assert after_issues[side_product_id]["withScoutQty"] == SIDE_ISSUE_QTY, after_issues[side_product_id]
        assert stage2.custody_by_product(_custody(admin_token, campaign_id)) == {
            product_id: FIRST_ISSUE_QTY,
            side_product_id: SIDE_ISSUE_QTY,
        }, "scoutCustodyBalances does not answer one row per product for this Scout"
        record(
            "SS-SM-04 step 1 / INV-M-04-01",
            f"issued {FIRST_ISSUE_QTY} of {traded} (kernel {RECEIVED_QTY}→{first_issue['inventoryPosition']['kernelPhysicalQty']}) "
            f"and {SIDE_ISSUE_QTY} of {side_name} as a second custody balance: the two balances answer "
            f"{FIRST_ISSUE_QTY} and {SIDE_ISSUE_QTY} separately",
        )

        # --- ORD-API-02-03: a READ-only account cannot spend custody ---------------
        #
        # The identity the leaf names, built the way the product builds it: the Scout shares the
        # profile with the other fixture admin at READ and nothing else.  READ is "view the profile
        # and its campaigns, orders, and generated reports"; placing an order needs WRITE or a Unit
        # Admin of the originating Unit (``PermissionType``, ``createOrder``).  The refusal has to
        # leave nothing behind — no Order, no custody movement — and the caller who *is* entitled
        # then retries the same idempotency key, so the leg also proves the refused attempt wrote no
        # marker that would make the retry answer a refusal.
        other_admin_email = identities["admin2"]["email"]
        other_admin_token = _token_for(identities["admin2"])
        share = api.gql(
            scout_token,
            stage2.STAGE_TWO_SUPPORT_DOCUMENTS["shareRead"],
            {"input": stage2.share_read_input(scout_profile_id, other_admin_email)},
        )
        share_row = share.get("shareProfileDirect") or {}
        share_account_id = str(share_row.get("targetAccountId") or "")
        assert list(share_row.get("permissions") or []) == ["READ"], share_row
        assert share_account_id, f"the share answered no account id: {share_row!r}"
        built["shareAccountId"] = share_account_id
        sale_input = stage2.custody_sale_input(
            scout_profile_id,
            scout_campaign_id,
            product_id,
            FIRST_SALE_QTY,
            SALE_CUSTOMER,
            idempotency_key=f"{lane['data_id']}-sale-1",
        )
        denial_codes = [item["code"] for item in _refused(other_admin_token, "createOrder", {"input": sale_input})]
        assert denial_codes, f"a READ-only account placed an Order on {scout_profile_id}"
        assert stage2.custody_by_product(_custody(admin_token, campaign_id)).get(product_id) == FIRST_ISSUE_QTY, (
            "the refused sale consumed Scout custody"
        )
        assert _scout_orders(admin_token, campaign_id, scout_campaign_id) == [], "the refused sale wrote an Order"
        record(
            "ORD-API-02-03-01",
            f"READ-only {other_admin_email} refused {denial_codes} on createOrder: custody still "
            f"{FIRST_ISSUE_QTY}, no Order in unitScoutCampaignOrders",
        )

        # --- SS-SM-04 step 2: sale 3, on the same key the denial just spent --------
        first_sale = _write(admin_token, "createOrder", {"input": sale_input})
        first_order_id, first_line_id = _sale_line(first_sale, product_id, FIRST_SALE_QTY)
        assert str(first_sale["unitCampaignId"]) == campaign_id, first_sale
        assert int(first_sale["lineItems"][0]["fulfilledQuantity"] or 0) == FIRST_SALE_QTY, first_sale
        after_first_sale = _positions(admin_token, campaign_id)[product_id]
        assert after_first_sale["withScoutQty"] == FIRST_ISSUE_QTY - FIRST_SALE_QTY, after_first_sale
        assert after_first_sale["kernelPhysicalQty"] == RECEIVED_QTY - FIRST_ISSUE_QTY, (
            f"a custody sale changed Kernel stock: {after_first_sale}"
        )
        record(
            "ORD-API-02-01/03-02",
            f"the entitled retry on key {lane['data_id']}-sale-1 wrote one Order {first_order_id} in "
            f"unitCampaignId={first_sale['unitCampaignId']}: ordered {FIRST_SALE_QTY}, fulfilled "
            f"{FIRST_SALE_QTY} from custody on line {first_line_id} (the write minted that id, §5.19), "
            f"custody {FIRST_ISSUE_QTY}→{after_first_sale['withScoutQty']}, Kernel untouched",
        )

        # --- SS-SM-04 step 2: sale 2 against the one unit the Scout still carries --
        second_sale = _write(
            admin_token,
            "createOrder",
            {
                "input": stage2.custody_sale_input(
                    scout_profile_id,
                    scout_campaign_id,
                    product_id,
                    SECOND_SALE_QTY,
                    "Rowan Door",
                    idempotency_key=f"{lane['data_id']}-sale-2",
                )
            },
        )
        second_order_id, second_line_id = _sale_line(second_sale, product_id, SECOND_SALE_QTY)
        second_line = second_sale["lineItems"][0]
        assert int(second_line["fulfilledQuantity"] or 0) == FIRST_ISSUE_QTY - FIRST_SALE_QTY, (
            f"the partial sale consumed {second_line['fulfilledQuantity']} of the "
            f"{FIRST_ISSUE_QTY - FIRST_SALE_QTY} the Scout carried: {second_line}"
        )
        after_second_sale = _positions(admin_token, campaign_id)[product_id]
        assert after_second_sale["withScoutQty"] == 0, f"custody survived the sale that emptied it: {after_second_sale}"
        assert after_second_sale["kernelPhysicalQty"] == RECEIVED_QTY - FIRST_ISSUE_QTY, after_second_sale
        record(
            "ORD-API-02-02 partial",
            f"sale {second_order_id} ordered {SECOND_SALE_QTY} against "
            f"{FIRST_ISSUE_QTY - FIRST_SALE_QTY} of custody: fulfilled {second_line['fulfilledQuantity']}, "
            f"still owing {SECOND_SALE_QTY - int(second_line['fulfilledQuantity'] or 0)}, Kernel untouched",
        )

        # --- SS-SM-04 steps 2b-3: issue 2, return 1, and the leaf's end state ------
        second_issue = _write(
            admin_token,
            "issueStockToScout",
            {
                "input": stage2.issue_input(
                    campaign_id,
                    scout_campaign_id,
                    scout_profile_id,
                    product_id,
                    SECOND_ISSUE_QTY,
                    idempotency_key=f"{lane['data_id']}-issue-2",
                )
            },
        )
        assert (
            second_issue["inventoryPosition"]["kernelPhysicalQty"] == RECEIVED_QTY - FIRST_ISSUE_QTY - SECOND_ISSUE_QTY
        ), second_issue
        returned = _write(
            admin_token,
            "returnStockFromScout",
            {
                "input": stage2.return_input(
                    campaign_id,
                    scout_campaign_id,
                    scout_profile_id,
                    [{"productId": product_id, "quantity": RETURN_QTY}],
                    idempotency_key=f"{lane['data_id']}-return",
                )
            },
        )
        assert len(returned["custodyBalances"]) == 1 and len(returned["inventoryPositions"]) == 1, returned
        sequence_position = _positions(admin_token, campaign_id)[product_id]
        assert sequence_position["kernelPhysicalQty"] == EXPECTED_FINAL_KERNEL, sequence_position
        assert sequence_position["withScoutQty"] == EXPECTED_FINAL_WITH_SCOUT, sequence_position
        assert sequence_position["totalUnitOwnedUndeliveredQty"] == EXPECTED_FINAL_OWNED, sequence_position
        sequence_trail = _trail(admin_token, campaign_id)
        kernel_sum = sum(
            int(row["kernelPhysicalDelta"] or 0) for row in sequence_trail if str(row.get("productId")) == product_id
        )
        assert kernel_sum == RECEIVED_QTY - FIRST_ISSUE_QTY - SECOND_ISSUE_QTY + RETURN_QTY, (
            f"the {traded} trail sums to a Kernel movement of {kernel_sum}, so a step counted twice: "
            f"expected {RECEIVED_QTY - FIRST_ISSUE_QTY - SECOND_ISSUE_QTY + RETURN_QTY}"
        )
        record(
            "SS-SM-04 steps 2b-3 / §2.8.3",
            f"issue {SECOND_ISSUE_QTY} then return {RETURN_QTY} ends the named sequence at Kernel "
            f"{sequence_position['kernelPhysicalQty']}, With Scout {sequence_position['withScoutQty']}, total "
            f"owned {sequence_position['totalUnitOwnedUndeliveredQty']}; the product's trail sums to "
            f"{kernel_sum:+d} Kernel, so no step decremented stock twice",
        )

        # --- INV-Q-01: the balances, and the formulas they have to satisfy --------
        positions = _positions(admin_token, campaign_id)
        traded_position = positions[product_id]
        side_position = positions[side_product_id]
        violations = stage2.position_arithmetic_violations([traded_position, side_position])
        assert violations == [], f"a derived balance disagrees with its formula: {violations}"
        built["tradedPosition"] = traded_position

        # --- The three §2.6 screens, read by the browser that renders them -------
        with _persona_session(browser, "04-admin-screens", identities["admin"], evidence_dir) as (admin_page, _):
            admin = ShowSellPage(admin_page)
            admin.goto_unit_campaign(unit_id, campaign_id)
            admin.open_stage_two_tab(ID_TAB_INVENTORY)
            screen = admin.wait_for_inventory_position(product_id)
            shot = _screenshot(admin_page, "01-stock-screen", evidence_dir, masks=admin.code_mask_locators())
            for quantity in ("kernelPhysicalQty", "sellableKernelQty", "withScoutQty", "councilOnOrderQty"):
                assert screen.get(quantity) == int(traded_position[quantity]), (
                    f"the Stock tab shows {quantity}={screen.get(quantity)} where the server answers "
                    f"{traded_position[quantity]}"
                )
            side_screen = admin.wait_for_inventory_position(side_product_id)
            assert side_screen.get("councilOnOrderQty") == int(side_position["councilOnOrderQty"]), (
                f"the Stock tab shows the Council-on-order balance on the wrong product: {side_screen}"
            )
            record(
                "INV-Q-01 / §2.6.1",
                f"screen and server agree on {sorted(screen)} for {traded}, and the on-order balance "
                f"{side_screen.get('councilOnOrderQty')} sits on {side_name}, not on {traded}; {shot}",
            )

            admin.open_stage_two_tab(ID_TAB_CUSTODY)
            held = admin.wait_for_custody_held(scout_profile_id)
            shot = _screenshot(admin_page, "02-custody-screen", evidence_dir, masks=admin.code_mask_locators())
            lines = {
                name: admin.custody_line_qty(scout_profile_id, ids)
                for name, ids in ((traded, product_id), (side_name, side_product_id))
            }
            expected_held = int(traded_position["withScoutQty"]) + int(side_position["withScoutQty"])
            assert held == expected_held, f"the custody tab shows {held} held, the balances answer {expected_held}"
            assert lines == {
                traded: int(traded_position["withScoutQty"]),
                side_name: int(side_position["withScoutQty"]),
            }, f"the custody tab's per-product lines read {lines}, the balances answer them differently"
            record("INV-Q-04 / §2.6.2", f"Scout holds {held} across {sorted(lines)}; {shot}")

            admin.open_stage_two_tab(ID_TAB_ORDERS)
            shot = _screenshot(admin_page, "03-orders-screen", evidence_dir, masks=admin.code_mask_locators())
            record("§2.6.3", f"fulfillment tab open, notes={admin.stage_two_notes()}; {shot}")

        # --- INV-Q-05: the Scout's own custody read, and nothing else -------------
        scout_custody = _my_custody(scout_token, campaign_id, scout_profile_id)
        assert stage2.custody_by_product(scout_custody) == {
            product_id: int(traded_position["withScoutQty"]),
            side_product_id: int(side_position["withScoutQty"]),
        }, scout_custody
        record(
            "INV-Q-05-01",
            f"myScoutCustody answers {len(scout_custody)} line(s) for the Scout's own profile and no other's",
        )

        # --- ORD-API-02-02 zero-custody, and SS-SM-10's two Council Needs ---------
        #
        # A sale against a Scout carrying one unit is the same path again: consume
        # ``min(ordered, availableWithScoutQty)``, stay owing the rest.  It also creates the demand
        # that makes the two Council Needs numbers mean something: with 8 units owed and 5 sellable
        # Kernels, both read 3 instead of the two zeroes any arithmetic would produce.
        demand_sale = _write(
            admin_token,
            "createOrder",
            {
                "input": stage2.custody_sale_input(
                    scout_profile_id,
                    scout_campaign_id,
                    product_id,
                    DEMAND_SALE_QTY,
                    "Sasha Door",
                    idempotency_key=f"{lane['data_id']}-sale-3",
                )
            },
        )
        demand_order_id, demand_line_id = _sale_line(demand_sale, product_id, DEMAND_SALE_QTY)
        after_demand_sale = _positions(admin_token, campaign_id)[product_id]
        assert after_demand_sale["withScoutQty"] == 0, (
            f"the sale took custody the Scout was not holding: {after_demand_sale}"
        )
        assert after_demand_sale["kernelPhysicalQty"] == EXPECTED_FINAL_KERNEL, (
            f"a custody sale changed Kernel stock: {after_demand_sale}"
        )
        orders = _scout_orders(admin_token, campaign_id, scout_campaign_id)
        demand = _demand(orders, product_id)
        assert demand["orderedQty"] == FIRST_SALE_QTY + SECOND_SALE_QTY + DEMAND_SALE_QTY, orders
        needs = stage2.council_need_positions(
            demand=demand["unfulfilledQty"],
            sellable=int(after_demand_sale["sellableKernelQty"]),
            unassigned=int(after_demand_sale["unassignedKernelQty"]),
        )
        assert after_demand_sale["assignedOpenQty"] == 0, (
            f"Stage 2 has no Show & Sell event to assign stock, so assignedOpenQty must read 0: {after_demand_sale}"
        )
        assert needs["physicalStockNeed"] > 0 and needs["afterAssignmentsNeed"] > 0, (
            f"the lane arranged demand of {demand['unfulfilledQty']} against a shelf of "
            f"{after_demand_sale['sellableKernelQty']}, so both Needs numbers should be non-zero: {needs}"
        )
        assert needs["physicalStockNeed"] == needs["afterAssignmentsNeed"], (
            f"nothing is assigned to an event in Stage 2, so both Council Needs numbers must agree: {needs}"
        )
        built.update({"needs": needs, "demand": demand, "orderIds": [first_order_id, second_order_id, demand_order_id]})
        record(
            "SS-SM-10 steps 2, 5-6 / ORD-API-02-02 zero-custody",
            f"sale {demand_order_id} ordered {DEMAND_SALE_QTY} against 1 of custody and stayed owing the "
            f"rest; unfulfilled demand {demand['unfulfilledQty']} against sellable "
            f"{after_demand_sale['sellableKernelQty']} and assigned {after_demand_sale['assignedOpenQty']}: "
            f"physical-stock need {needs['physicalStockNeed']}, after-assignments need "
            f"{needs['afterAssignmentsNeed']}, one read",
        )

        # --- INV-M-06-02: the owed line, filled from the Council ------------------
        #
        # ``fulfillmentVersion`` starts at 0 on a door-to-door Order even though the sale itself
        # writes the custody fulfillment(s): the data model creates the Order with version 0 and
        # consumes custody in the same operation (SHOW_AND_SELL_DATA_MODEL.md §806), so the version
        # the first fulfillment conditions on is the one the sale answered.
        version = int(second_sale["fulfillmentVersion"] or 0)
        council_fill = _write(
            admin_token,
            "fulfillIndividualOrderLine",
            {
                "input": stage2.fulfill_input(
                    second_order_id,
                    second_line_id,
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
        assert after_council_fill["councilOnOrderQty"] == 0, (
            f"an external-Council fulfillment consumed the Council-on-order balance: {after_council_fill}. "
            "councilOnOrderQty is expected Council supply, is never subtracted automatically, and this "
            "product never had one (SHOW_AND_SELL_DATA_MODEL.md, the balance table)"
        )
        assert after_council_fill["kernelPhysicalQty"] == EXPECTED_FINAL_KERNEL, (
            f"an external-Council fulfillment moved Kernel stock: {after_council_fill}"
        )
        assert after_council_fill["version"] == after_demand_sale["version"], (
            f"an external-Council fulfillment wrote the balance row anyway: {after_council_fill}"
        )
        council_version = int(council_fill["order"]["fulfillmentVersion"] or version + 1)
        assert council_version > version, f"the fulfillment did not advance the Order version: {council_fill['order']}"
        record(
            "INV-M-06-02",
            f"EXTERNAL_COUNCIL fulfillment {council_record['fulfillmentId']} names no movement and writes no "
            f"inventory row at all: kernelPhysicalQty {after_council_fill['kernelPhysicalQty']} and the balance "
            f"row still at v{after_council_fill['version']}, while the Order's version moved to {council_version}",
        )

        # --- INV-M-07-01: the reversal puts the demand back and only that source ---
        reversal = _write(
            admin_token,
            "reverseIndividualOrderFulfillment",
            {
                "input": stage2.reverse_input(
                    second_order_id,
                    str(council_record["fulfillmentId"]),
                    council_version,
                    idempotency_key=f"{lane['data_id']}-reverse",
                )
            },
        )
        reversal_record = reversal["reversal"]
        assert str(reversal_record["reversalOfFulfillmentId"]) == str(council_record["fulfillmentId"]), reversal_record
        after_reversal = _positions(admin_token, campaign_id)[product_id]
        assert after_reversal["version"] == after_council_fill["version"], (
            f"reversing a Council fulfillment wrote the balance row: {after_reversal}"
        )
        assert after_reversal["kernelPhysicalQty"] == EXPECTED_FINAL_KERNEL, (
            f"a reversal of a Council fulfillment touched Kernel stock: {after_reversal}"
        )
        reversed_line = next(
            item for item in reversal["order"]["lineItems"] if str(item.get("lineItemId")) == second_line_id
        )
        assert int(reversed_line["fulfilledQuantity"] or 0) == FIRST_ISSUE_QTY - FIRST_SALE_QTY, reversed_line
        version = int(reversal["order"]["fulfillmentVersion"] or council_version + 1)
        record(
            "INV-M-07-01",
            f"reversal {reversal_record['fulfillmentId']} names {council_record['fulfillmentId']}, restores the "
            f"line to {reversed_line['fulfilledQuantity']}/{SECOND_SALE_QTY} fulfilled, and leaves the balance "
            f"row exactly where it was (kernel {after_reversal['kernelPhysicalQty']}, v{after_reversal['version']})",
        )

        # --- VER-01: the version the reversal already spent is now stale ----------
        stale = api.gql_raw(
            admin_token,
            stage2.STAGE_TWO_DOCUMENTS["fulfillIndividualOrderLine"],
            {
                "input": stage2.fulfill_input(
                    second_order_id,
                    second_line_id,
                    COUNCIL_FILL,
                    council_version,
                    idempotency_key=f"{lane['data_id']}-stale",
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
        record(
            "VER-01",
            f"fulfillment pinned to the spent v{council_version} refused with {stale_codes}: position still "
            f"v{after_stale['version']} with {after_stale['unassignedKernelQty']} unassigned and the line "
            f"still {reversed_line['fulfilledQuantity']}/{SECOND_SALE_QTY}",
        )

        # --- INV-M-06-01: the third line, filled from unassigned Kernel stock -----
        stock_fill = _write(
            admin_token,
            "fulfillIndividualOrderLine",
            {
                "input": stage2.fulfill_input(
                    demand_order_id,
                    demand_line_id,
                    STOCK_FILL,
                    int(demand_sale["fulfillmentVersion"] or 0),
                    idempotency_key=f"{lane['data_id']}-stock-fill",
                )
            },
        )
        stock_record = stock_fill["fulfillment"]
        assert stock_record["inventoryMovementId"], f"a KERNEL_STOCK fulfillment names no movement: {stock_record}"
        filled_line = next(
            item for item in stock_fill["order"]["lineItems"] if str(item.get("lineItemId")) == demand_line_id
        )
        assert int(filled_line["fulfilledQuantity"] or 0) == 1 + STOCK_FILL, filled_line
        after_stock_fill = _positions(admin_token, campaign_id)[product_id]
        assert after_stock_fill["kernelPhysicalQty"] == EXPECTED_FINAL_KERNEL - STOCK_FILL, (
            f"a Kernel-stock fulfillment did not take the stock it handed over: {after_stock_fill}"
        )
        assert after_stock_fill["unassignedKernelQty"] == after_reversal["unassignedKernelQty"] - STOCK_FILL, (
            f"the fulfillment did not consume unassigned stock: {after_stock_fill}"
        )
        assert after_stock_fill["totalUnitOwnedUndeliveredQty"] == (
            after_reversal["totalUnitOwnedUndeliveredQty"] - STOCK_FILL
        ), f"the Unit's owned-and-undelivered total did not follow the sale: {after_stock_fill}"
        record(
            "INV-M-06-01",
            f"KERNEL_STOCK fulfillment {stock_record['fulfillmentId']} names movement "
            f"{stock_record['inventoryMovementId']}; line {demand_line_id} now "
            f"{filled_line['fulfilledQuantity']}/{DEMAND_SALE_QTY}, kernelPhysicalQty "
            f"{EXPECTED_FINAL_KERNEL}→{after_stock_fill['kernelPhysicalQty']}",
        )

        # --- The fulfillment tab shows the line the server just wrote ------------
        with _persona_session(browser, "05-admin-orders", identities["admin"], evidence_dir) as (admin_page, _):
            admin = ShowSellPage(admin_page)
            admin.goto_unit_campaign(unit_id, campaign_id)
            admin.open_stage_two_tab(ID_TAB_ORDERS)
            admin.select_fulfillment_campaign(lane["campaign_name"])
            screen_orders = admin.order_block_ids()
            shot = _screenshot(
                admin_page, "04-orders-after-fulfillment", evidence_dir, masks=admin.code_mask_locators()
            )
            assert demand_order_id in screen_orders, (
                f"the fulfillment tab lists orders {screen_orders} for {lane['campaign_name']!r}, not "
                f"{demand_order_id}; the tab says {admin.fulfillment_notes() or 'nothing about being empty'}"
            )
            fulfilled, owed = admin.wait_for_order_line(demand_line_id, campaign_name=lane["campaign_name"])
            assert (fulfilled, owed) == (1 + STOCK_FILL, DEMAND_SALE_QTY - 1 - STOCK_FILL), (
                f"the tab shows line {demand_line_id} as {fulfilled} fulfilled / {owed} owed, the server "
                f"says {1 + STOCK_FILL}/{DEMAND_SALE_QTY}"
            )
            record(
                "INV-Q-03 / §2.6.3",
                f"the fulfillment tab shows line {demand_line_id} at {fulfilled} fulfilled and {owed} owed; {shot}",
            )

        # --- INV-Q-02: the audit trail every one of those writes owes -------------
        trail = _trail(admin_token, campaign_id)
        expected_trail = [
            {"movementType": "RECEIPT", "productId": side_product_id, "kernelPhysicalDelta": SIDE_RECEIVED_QTY},
            {"movementType": "STOCK_ADJUSTMENT", "productId": side_product_id, "kernelPhysicalDelta": SIDE_ADJUST_UP},
            {"movementType": "STOCK_ADJUSTMENT", "productId": side_product_id, "kernelPhysicalDelta": SIDE_ADJUST_DOWN},
            {
                "movementType": "COUNCIL_ON_ORDER_ADJUST",
                "productId": side_product_id,
                "councilOnOrderDelta": ON_ORDER_QTY,
            },
            {
                "movementType": "SCOUT_ISSUE",
                "productId": side_product_id,
                "kernelPhysicalDelta": -SIDE_ISSUE_QTY,
                "withScoutDelta": SIDE_ISSUE_QTY,
            },
            {"movementType": "RECEIPT", "productId": product_id, "kernelPhysicalDelta": RECEIVED_QTY},
            {
                "movementType": "SCOUT_ISSUE",
                "productId": product_id,
                "kernelPhysicalDelta": -FIRST_ISSUE_QTY,
                "withScoutDelta": FIRST_ISSUE_QTY,
            },
            # Each sale's custody consumption is recorded as the fulfillment it wrote, not as a
            # ``SCOUT_SALE_CONSUME`` row: that type exists for a Show & Sell event sale and its
            # required source link is the event's ``saleId`` (``src/utils/inventory_models.py``,
            # ``MOVEMENT_REQUIRED_SOURCE_LINKS``), which a door-to-door sale does not have.  Measured
            # on dev on 2026-11-18, the custody a door-to-door sale consumed is traced by an
            # ``INDIVIDUAL_FULFILL`` row naming the Order and the ``SCOUT_CUSTODY`` fulfillment.
            {
                "movementType": "INDIVIDUAL_FULFILL",
                "productId": product_id,
                "withScoutDelta": -FIRST_SALE_QTY,
                "kernelPhysicalDelta": 0,
                "profileId": scout_profile_id,
                "orderId": first_order_id,
            },
            {
                "movementType": "INDIVIDUAL_FULFILL",
                "productId": product_id,
                "withScoutDelta": -(FIRST_ISSUE_QTY - FIRST_SALE_QTY),
                "kernelPhysicalDelta": 0,
                "profileId": scout_profile_id,
                "orderId": second_order_id,
            },
            {
                "movementType": "SCOUT_ISSUE",
                "productId": product_id,
                "kernelPhysicalDelta": -SECOND_ISSUE_QTY,
                "withScoutDelta": SECOND_ISSUE_QTY,
            },
            {
                "movementType": "SCOUT_RETURN",
                "productId": product_id,
                "kernelPhysicalDelta": RETURN_QTY,
                "withScoutDelta": -RETURN_QTY,
            },
            {
                "movementType": "INDIVIDUAL_FULFILL",
                "productId": product_id,
                "withScoutDelta": -1,
                "kernelPhysicalDelta": 0,
                "profileId": scout_profile_id,
                "orderId": demand_order_id,
            },
            {"movementType": "INDIVIDUAL_FULFILL", "productId": product_id, "kernelPhysicalDelta": -STOCK_FILL},
        ]
        violations = stage2.movement_trail_violations(trail, expected_trail)
        assert violations == [], f"the trail does not hold the lane's writes: {violations}\n{trail}"
        assert len(trail) == len(expected_trail), (
            f"the Unit Campaign's trail answers {len(trail)} rows, the lane wrote {len(expected_trail)}: "
            f"something is in the audit that no step of this lane owns"
        )
        council_rows = [
            row for row in trail if str(row.get("fulfillmentId") or "") == str(council_record["fulfillmentId"])
        ]
        assert not council_rows, f"an EXTERNAL_COUNCIL fulfillment wrote inventory history: {council_rows}"
        linked = [
            row
            for row in trail
            if str(row.get("orderId") or "") == demand_order_id
            and str(row.get("fulfillmentId") or "") == str(stock_record["fulfillmentId"])
        ]
        assert linked, f"no movement names the fulfillment that filled the line: {demand_order_id}"
        built["movementCount"] = len(trail)
        record(
            "INV-Q-02 / AC-03",
            f"the trail answers exactly the {len(trail)} rows this lane wrote: both receipts, the adjustment pair, "
            f"the on-order adjustment, all three issues, the return, the custody each sale consumed and the Kernel "
            f"the fulfillment handed over; {len(linked)} names fulfillment {stock_record['fulfillmentId']}, none "
            f"names the Council fulfillment {council_record['fulfillmentId']}, and every stock adjustment carries "
            "its reason",
        )

        # --- ORD-API-02-04 / API-FIX-05: the Campaign joins ANOTHER Unit Campaign --
        #
        # The acceptance line is "after the Campaign joins another Unit Campaign, the old Order,
        # fulfillment, and Council demand retain the original scope", so the live leg moves the Scout
        # Campaign to a second Unit Campaign on the same Unit rather than rejoining the one it left —
        # a rejoin of the same campaign would pass even if scope followed the membership.  The
        # destination carries a receipt of its own before the move, so the leg can show the move put
        # no demand, no custody and no history into it.  It is a campaign of this lane, not a canary:
        # the independent canary lane is the one built at the top of the run.
        moved_name = f"{CAMPAIGN_TEMPLATE.format(data_id=lane['data_id'])} B"
        with _persona_session(browser, "06-admin-second-campaign", identities["admin"], evidence_dir) as (
            admin_page,
            _,
        ):
            admin = ShowSellPage(admin_page)
            # ``goto_unit`` rather than a click on the Unit list: that list is a paged ``myUnits``
            # read, and by this point in the lane's own life the account holds every Unit earlier
            # runs left behind.  The workspace route is the direct, page-independent way in.
            admin.goto_unit(unit_id)
            admin.open_tab("tab-campaigns")
            moved_id, moved_join_code = admin.create_campaign(
                name=moved_name, year=CAMPAIGN_YEAR, catalog_name=catalog_name
            )
            codes.append(moved_join_code)
            built["movedCampaignId"] = moved_id
            built["extraCampaignIds"] = [moved_id]
            built["extraJoinCodes"] = [moved_join_code]
        moved_receipt = _write(
            admin_token,
            "recordInventoryReceipt",
            {
                "input": stage2.receipt_input(
                    moved_id,
                    product_id,
                    SECOND_CAMPAIGN_QTY,
                    idempotency_key=f"{lane['data_id']}-second-campaign-receipt",
                )
            },
        )
        assert moved_receipt["kernelPhysicalQty"] == SECOND_CAMPAIGN_QTY, moved_receipt

        # What the Scout is holding at the moment of the move is not a guess: the side product was
        # issued SIDE_ISSUE_QTY and never sold or returned, and every unit of the traded product's
        # custody went to the sales above — ``planLineConsumption`` in
        # ``tofu/application/appsync/js-resolvers/lib/custody_sale.js`` consumes a line only against
        # that line's own product, so those sales cannot have touched the side product.
        expected_custody_at_move = {side_product_id: SIDE_ISSUE_QTY}
        custody_before_move = _campaign_custody(admin_token, campaign_id)
        custody_read_before = stage2.custody_by_product(_custody(admin_token, campaign_id))
        assert custody_before_move == expected_custody_at_move, (
            f"the lane reached its move holding {custody_before_move} instead of {expected_custody_at_move}"
        )
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
        with _persona_session(browser, "07-scout-moves", identities["scout"], evidence_dir) as (scout_page, _):
            scout = ShowSellPage(scout_page)
            scout.goto_join()
            scout.join_unit_campaign(moved_join_code, scout_profile_id)

        still_there = _scout_orders(admin_token, campaign_id, scout_campaign_id)
        assert sorted(str(row["orderId"]) for row in still_there) == sorted(
            [first_order_id, second_order_id, demand_order_id]
        ), f"the sales did not stay with the Unit Campaign they were sold in: {still_there}"
        assert _demand(still_there, product_id)["orderedQty"] == (FIRST_SALE_QTY + SECOND_SALE_QTY + DEMAND_SALE_QTY), (
            still_there
        )
        history = []
        for order_id in (first_order_id, second_order_id, demand_order_id):
            records = _fulfillments(admin_token, order_id)
            assert records, f"Order {order_id}'s fulfillment records vanished"
            assert {str(row["unitCampaignId"]) for row in records} == {campaign_id}, records
            assert {str(row["campaignId"]) for row in records} == {scout_campaign_id}, records
            history.extend(records)
        still_linked = _trail(admin_token, campaign_id)
        assert [row for row in still_linked if str(row.get("orderId") or "") == first_order_id], (
            "the sale's movements stopped answering the Unit Campaign they were written under"
        )
        moved_orders = _scout_orders(admin_token, moved_id, scout_campaign_id)
        assert not moved_orders, f"the sales moved with the membership into {moved_id}: {moved_orders}"
        assert not _custody(admin_token, moved_id), f"custody moved into {moved_id}"
        moved_positions = _positions(admin_token, moved_id)
        assert int(moved_positions[product_id]["kernelPhysicalQty"]) == SECOND_CAMPAIGN_QTY, moved_positions[product_id]
        assert int(moved_positions[product_id]["withScoutQty"]) == 0, moved_positions[product_id]
        custody_after_move = _campaign_custody(admin_token, campaign_id)
        custody_read_after = stage2.custody_by_product(_custody(admin_token, campaign_id))
        assert custody_after_move == expected_custody_at_move, (
            f"the removal took the custody with it: {custody_after_move} against {expected_custody_at_move}"
        )
        assert custody_after_move == custody_before_move, (
            "the custody balances followed the membership into the new Unit Campaign instead of "
            "staying on the one that issued them"
        )
        assert all(int(row["withScoutQty"] or 0) == 0 for row in moved_positions.values()), (
            f"the move put custody on the destination campaign: {moved_positions}"
        )
        record(
            "ORD-API-02-04 / API-FIX-05",
            f"removed from {campaign_id} and joined {moved_id}: the three Orders, their {len(history)} "
            f"fulfillment record(s) and {FIRST_SALE_QTY + SECOND_SALE_QTY + DEMAND_SALE_QTY} of demand still "
            f"answer {campaign_id}, its trail still names the sale and its custody balances "
            f"{custody_before_move} are untouched, while the new campaign answers 0 Orders, no custody and "
            f"only its own {SECOND_CAMPAIGN_QTY} Kernels; ``scoutCustodyBalances`` answered {custody_read_before} "
            "before the removal and "
            f"{custody_read_after} after it",
        )

        # --- AUTH-U: the right arguments from the wrong account answer nothing ---
        outside_token = _token_for(identities["outside"])
        other_admin_token = _token_for(identities["admin2"])
        for label, token in (("outside", outside_token), ("admin with no grant on this Unit", other_admin_token)):
            codes_answered = [
                item["code"] for item in _refused(token, "inventoryPositions", {"unitCampaignId": campaign_id})
            ]
            assert codes_answered, f"{label} read {campaign_id}'s balances"
            codes_moved = [
                item["code"] for item in _refused(token, "scoutCustodyBalances", {"unitCampaignId": campaign_id})
            ]
            assert codes_moved, f"{label} read {campaign_id}'s custody balances"
        after_refusals = _positions(admin_token, campaign_id)[product_id]
        assert after_refusals["kernelPhysicalQty"] == after_stock_fill["kernelPhysicalQty"], (
            "a refused read changed a balance"
        )
        record(
            "AUTH-U-03/05", "outside and an admin with no grant here were refused on both reads, with no balance change"
        )

        built["finished"] = True
    finally:
        # Cleanup runs whether the journey finished or not, and it is a gate rather than a log:
        # every step reports a verdict, the evidence is written first so a failed teardown still
        # leaves a record, and only then does a failed step turn the run red.  Before this shape, a
        # refused ``deleteOrder`` or a disturbed canary was recorded as an observation and pytest
        # exited 0 — which is exactly how a cleanup gate stops meaning anything.
        # Amendment B's residue census comes first, and before the teardown: the sweep below deletes the
        # Unit and Unit Campaign rows every Stage 2 read is keyed on, so a count of what this lane leaves in
        # the three tables no QA identity can Scan can only be taken while those reads still answer.
        residue: dict[str, str] = {}
        if built.get("unitCampaignId"):
            residue = _residue_census(identities, built)
            cleanup.append(_residue_row(str(lane["data_id"]), residue))
        try:
            cleanup.extend(_teardown_lane(lane["data_id"], built, identities))
        except Exception as exc:  # noqa: BLE001 - a teardown that dies mid-step must still cost the run nothing but its verdict
            cleanup.append(
                stage2.cleanup_row(
                    "§2.8.7 teardown", f"stopped: {type(exc).__name__}: {exc}", result=stage2.CLEANUP_FAILED
                )
            )
        if built.get("unitCampaignId"):
            cleanup.extend(
                _lane_table_sweep(
                    lane["data_id"],
                    _lane_sweep_tokens(str(lane["data_id"]), built),
                    residue,
                )
            )
        if canary_before and canary.get("unitCampaignId"):
            try:
                cleanup.append(_canary_survived(canary_before, _lane_snapshot(canary, identities), canary, identities))
            except Exception as exc:  # noqa: BLE001 - an unreadable canary is a failed canary
                cleanup.append(
                    stage2.cleanup_row(
                        "§2.8.7 independent lane survived", f"{type(exc).__name__}: {exc}", result=stage2.CLEANUP_FAILED
                    )
                )
        sweep_ids = [item.strip() for item in os.environ.get("SS_SWEEP_PRIOR", "").split(",") if item.strip()]
        if sweep_ids:
            cleanup.extend(_sweep_prior_lanes(identities, sweep_ids, lane["data_id"]))
        if canary.get("unitCampaignId"):
            # The canary's own turn: the same teardown, pointed at the canary's ids, proves the sweep
            # removes a whole lane's rows when it is told to — and leaves no fixture behind.  Its census is
            # taken here, after the acceptance lane's teardown, so the counts also show that the lane's
            # teardown left the canary's residue standing.
            canary_residue = _residue_census(identities, canary)
            cleanup.append(_residue_row(f"canary lane {canary['data_id']}", canary_residue))
            cleanup.extend(_teardown_lane(str(canary["data_id"]), canary, identities))
            cleanup.extend(
                _lane_table_sweep(
                    f"canary lane {canary['data_id']}",
                    _lane_sweep_tokens(str(canary["data_id"]), canary),
                    canary_residue,
                )
            )
        for row in cleanup:
            record(row["acceptance"], row["summary"], result=row["result"])
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
                "teardown": "always",
                "cleanupRows": len(cleanup),
                "cleanupNotMet": stage2.cleanup_problems(cleanup),
                "cleanupBlocked": stage2.cleanup_blocked(cleanup),
                **{key: value for key, value in built.items() if key not in ("finished", "steps")},
            },
            steps,
            passwords,
            codes,
        )
        # Written first, then judged: the record of a failed cleanup is what a reviewer reads, and
        # the run still has to fail.
        stage2.assert_cleanup_clean(cleanup)
