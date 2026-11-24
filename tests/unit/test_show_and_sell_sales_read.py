"""Wave 5.5 — the raw sale read the Unit Admin's sale screens are built on (§4.5.2).

Resolver-level cases for the read behind the screen, with ``PAGE-01``, ``AUTH-U``, ``SEC-04``
and ``VER-01``. Everything runs through ``handle_unit_operation`` against moto, and the sales
being read are written by ``createShowAndSellSale`` rather than seeded: a list test that handed
the resolver a hand-built sale row would prove nothing about the rows the product actually
writes — the payment snapshot, the ``expectedCashCents`` term, the buyer fields an obligation
needs, and the revision a correction conditions on are all things the write puts there, and
the read is only correct if it answers them.

The scenario is the smoke-test table: one running event, four boxes of caramel at five
dollars, and a handful of sales whose ``saleAt`` instants differ so that ordering and cursor
completion are observable rather than assumed. The arithmetic claims these tests make are about
the rows, never about a total the server computed — ``showAndSellSales`` answers no pool, no
Cash expectation and no per-product rollup, because §9 and AC-36 put that addition in the
browser over exactly these rows.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from src.handlers.unit_operations import (
    EVENT_INVENTORY_ALLOCATIONS_FIELD,
    INVENTORY_POSITIONS_FIELD,
    SHOW_AND_SELL_FIELD,
    SHOW_AND_SELL_SALES_FIELD,
    SHOW_AND_SELL_SIGNUPS_FIELD,
    UNIT_PAYMENT_METHODS_FIELD,
    WE_OWE_OBLIGATIONS_FIELD,
    handle_unit_operation,
)
from src.utils import show_and_sell_models as ssm
from src.utils import show_and_sell_sale_models as sm
from tests.unit.show_sell_fixtures import (
    account_id,
    assert_is_error,
    seed_show_sell_fixtures,
    unit_operation_event,
)
from tests.unit.test_show_and_sell_sales import (  # the Wave 5.2 scenario: one table, one catalog
    ACTIVE_EVENT,
    CAMPAIGN,
    PRODUCT,
    RIVAL_EVENT,
    SALE_AT,
    UNIT,
    _correct,
    _create,
    _line,
    _method,
    _offer_products,
    _revision_rows,
    _seed_allocation,
    _seed_event,
    _seed_signup,
    _seed_stock,
    _shift,
    _stored_event,
    _void,
)

AVERY = account_id("Avery")

#: The sale's SDL fields, as the read answers them. ``check_show_and_sell_schema.test.ts``
#: pins the same list against the SDL, so a payload field that appears here and not there fails.
SALE_FIELDS = [
    "saleId",
    "showAndSellId",
    "unitId",
    "unitCampaignId",
    "saleAt",
    "enteredByAccountId",
    "buyerName",
    "buyerPhone",
    "buyerEmail",
    "lineItems",
    "totalCents",
    "paymentMethodSnapshot",
    "revision",
    "status",
    "voidedByAccountId",
    "voidedAt",
    "createdAt",
    "updatedAt",
    "expectedCashCents",
]


# --- Handler turns ---------------------------------------------------------------


def _call(
    field: str,
    caller: Optional[str],
    *,
    arguments: Optional[Dict[str, Any]] = None,
) -> Any:
    return handle_unit_operation(unit_operation_event(field, caller, arguments=arguments), None)


def _ok(payload: Any) -> Dict[str, Any]:
    failed = isinstance(payload, dict) and payload.get("__isError")
    assert not failed, f"expected a success payload, got {payload!r}"
    return payload


def _sales(caller: Optional[str] = "Avery", *, event_id: str = ACTIVE_EVENT, **arguments: Any) -> Any:
    return _call(SHOW_AND_SELL_SALES_FIELD, caller, arguments={"showAndSellId": event_id, **arguments})


def _sale_ids(page: Dict[str, Any]) -> List[str]:
    return [str(item["saleId"]) for item in page["items"]]


# --- Seeded state ----------------------------------------------------------------


@pytest.fixture
def world(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    inventory_table: Any,
    show_and_sells_table: Any,
) -> Dict[str, Any]:
    """The Stage 1 persona world plus the two tables a sale touches."""
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    _offer_products(catalogs_table, 4)
    return {
        "show_and_sells": show_and_sells_table,
        "inventory": inventory_table,
        "catalogs": catalogs_table,
        "units": units_table,
    }


def _seed_table(world: Dict[str, Any], *, rival: bool = False) -> None:
    """The running event with stock assigned to it, and a second event when a test wants one."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    if rival:
        _seed_event(world["show_and_sells"], RIVAL_EVENT)
    _seed_stock(world)


def _sold(world: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Sell at the running event and return the answer, asserting it landed.

    Every create bumps the event version, so each sale is pinned to the event as the
    read sees it rather than to the create-time default.
    """
    event_id = kwargs.pop("event_id", ACTIVE_EVENT)
    version = kwargs.pop("version", int(_stored_event(world["show_and_sells"], event_id)[ssm.VERSION_ATTRIBUTE]))
    return _ok(_create(event_id=event_id, version=version, **kwargs))


# --- The shape of the answer (§4.5.2) --------------------------------------------


def test_the_sale_page_is_the_administrative_row_with_no_computed_total(world: Dict[str, Any]) -> None:
    """§4.5.2, PAGE-01, AC-19: every field a sale screen shows is on the row; nothing else is."""
    _seed_table(world)
    cash = _sold(world, lines=[_line(PRODUCT, immediate=2)], buyerName="Nora N")
    mixed = _sold(
        world,
        key="sale-2",
        sale_at=_shift(-2),
        lines=[_line(PRODUCT, immediate=1, we_owe=2)],
        buyerName="Quinn Q",
        buyerPhone="303-555-0101",
    )
    voided = _sold(world, key="sale-3", sale_at=_shift(0))
    _ok(
        _void(
            event_id=ACTIVE_EVENT,
            sale_id=voided["sale"]["saleId"],
            version=int(_stored_event(world["show_and_sells"], ACTIVE_EVENT)[ssm.VERSION_ATTRIBUTE]),
            key="void-1",
            reason="the buyer changed their mind",
        )
    )

    page = _ok(_sales())

    assert set(page) == {"items", "pageInfo"}, "no pool, no Cash expectation, no rollup on the connection"
    assert len(page["items"]) == 3
    for item in page["items"]:
        assert set(item) == set(SALE_FIELDS), "the row is the administrative sale, storage keys and all excluded"
        assert item["showAndSellId"] == ACTIVE_EVENT
        assert item["unitId"] == UNIT and item["unitCampaignId"] == CAMPAIGN
        assert item["enteredByAccountId"] == AVERY

    by_id = {item["saleId"]: item for item in page["items"]}
    assert by_id[cash["sale"]["saleId"]]["totalCents"] == 1000
    assert by_id[cash["sale"]["saleId"]]["expectedCashCents"] == 1000, "a Cash sale's total is the drawer's"
    assert by_id[cash["sale"]["saleId"]]["paymentMethodSnapshot"]["methodCode"] == "CASH"
    assert by_id[cash["sale"]["saleId"]]["lineItems"][0]["immediateQty"] == 2
    assert by_id[cash["sale"]["saleId"]]["lineItems"][0]["productNameSnapshot"] == "Caramel 1"

    owed = by_id[mixed["sale"]["saleId"]]
    assert owed["totalCents"] == 1500 and owed["expectedCashCents"] == 1500, (
        "the sale reports its total as expected cash exactly when the method is CASH (AC-31)"
    )
    assert owed["lineItems"][0]["weOweQty"] == 2
    assert (owed["buyerName"], owed["buyerPhone"]) == ("Quinn Q", "303-555-0101"), (
        "the buyer snapshot is on the sale, because an obligation has no Account, only a name"
    )

    gone = by_id[voided["sale"]["saleId"]]
    assert (gone["status"], gone["voidedByAccountId"]) == (sm.SALE_STATUS_VOIDED, AVERY)
    assert gone["voidedAt"], "a voided row says when and by whom, so the history is readable"
    assert by_id[cash["sale"]["saleId"]]["voidedAt"] is None


def test_the_list_shows_one_row_per_sale_at_its_current_revision(world: Dict[str, Any]) -> None:
    """§4.5.2, VER-01: the archived revision child is history the correction returns, not a second row."""
    _seed_table(world)
    answer = _sold(world, lines=[_line(PRODUCT, immediate=2)])
    sale_id = str(answer["sale"]["saleId"])
    line_id = str(answer["sale"]["lineItems"][0]["lineItemId"])
    _ok(
        _correct(
            event_id=ACTIVE_EVENT,
            sale_id=sale_id,
            lines=[{"lineItemId": line_id, "productId": PRODUCT, "immediateQty": 1, "weOweQty": 0}],
            key="correct-1",
        )
    )

    page = _ok(_sales())
    assert _sale_ids(page) == [sale_id], "a corrected sale is still one row in the list"
    assert page["items"][0]["revision"] == 2, "the row the screen re-reads carries the version the next write pins"
    assert len(_revision_rows(world["show_and_sells"])) == 1, (
        "the prior revision is stored, and it is reachable only through the correction that made it"
    )


# --- Filters and cursor scope (PAGE-01) -----------------------------------------


def test_the_status_filter_selects_one_state_and_refuses_any_other_word(world: Dict[str, Any]) -> None:
    """PAGE-01, AC-20: both states by default, one on request, and no third state exists."""
    _seed_table(world)
    kept = _sold(world, key="sale-1")
    gone = _sold(world, key="sale-2", sale_at=_shift(0))
    kept_id, gone_id = str(kept["sale"]["saleId"]), str(gone["sale"]["saleId"])
    _ok(
        _void(
            event_id=ACTIVE_EVENT,
            sale_id=gone_id,
            version=int(_stored_event(world["show_and_sells"], ACTIVE_EVENT)[ssm.VERSION_ATTRIBUTE]),
            key="void-1",
        )
    )

    assert _sale_ids(_ok(_sales())) == [kept_id, gone_id], "omit the filter and the history is the history"
    assert _sale_ids(_ok(_sales(status=sm.SALE_STATUS_ACTIVE))) == [kept_id]
    assert _sale_ids(_ok(_sales(status=sm.SALE_STATUS_VOIDED))) == [gone_id]

    for bad in ("CANCELLED", "PARTIALLY_VOIDED", "active", ""):
        assert_is_error(_sales(status=bad), "INVALID_INPUT"), f"``{bad}`` is not a sale state"


def test_sale_pages_are_complete_ordered_and_scoped_to_the_filter_that_made_them(world: Dict[str, Any]) -> None:
    """PAGE-01: a cursor continues one specific result set — the event and its status filter."""
    _seed_table(world, rival=True)
    oldest = str(_sold(world, key="sale-1", sale_at=_shift(-2))["sale"]["saleId"])
    middle = str(_sold(world, key="sale-2", sale_at=SALE_AT)["sale"]["saleId"])
    newest = str(_sold(world, key="sale-3", sale_at=_shift(0))["sale"]["saleId"])

    first = _ok(_sales(page={"limit": 1}))
    assert _sale_ids(first) == [oldest], "sale time first, so the ledger reads in the order it happened"
    assert first["pageInfo"]["hasNextPage"] is True and first["pageInfo"]["endCursor"]

    second = _ok(_sales(page={"limit": 1, "cursor": first["pageInfo"]["endCursor"]}))
    assert _sale_ids(second) == [middle]
    tail = _ok(_sales(page={"limit": 1, "cursor": second["pageInfo"]["endCursor"]}))
    assert _sale_ids(tail) == [newest]
    assert tail["pageInfo"]["hasNextPage"] is False and tail["pageInfo"]["endCursor"] is None, (
        "the walk ends with an answer, not a cursor that promises more"
    )

    filtered = _ok(_sales(status=sm.SALE_STATUS_ACTIVE, page={"limit": 1}))
    assert _sale_ids(filtered) == [oldest]
    cursor = filtered["pageInfo"]["endCursor"]
    assert _sale_ids(_ok(_sales(status=sm.SALE_STATUS_ACTIVE, page={"limit": 1, "cursor": cursor}))) == [middle]

    assert_is_error(_sales(page={"limit": 1, "cursor": cursor}), "INVALID_INPUT")
    assert_is_error(_sales(status=sm.SALE_STATUS_VOIDED, page={"limit": 1, "cursor": cursor}), "INVALID_INPUT")
    assert_is_error(
        _sales(event_id=RIVAL_EVENT, page={"limit": 1, "cursor": cursor}),
        "INVALID_INPUT",
    )
    assert_is_error(_sales(page={"limit": 1, "cursor": "bm90LWEtY3Vyc29y"}), "INVALID_INPUT")
    assert_is_error(_sales(page={"limit": 101}), "INVALID_INPUT")


def test_an_event_with_no_sales_answers_an_empty_page_rather_than_an_error(world: Dict[str, Any]) -> None:
    """PAGE-01, AC-19: an event that sold nothing is a real answer, not a failure to read."""
    _seed_table(world)

    for arguments in ({}, {"status": sm.SALE_STATUS_ACTIVE}, {"status": sm.SALE_STATUS_VOIDED}):
        page = _ok(_sales(**arguments))
        assert page["items"] == []
        assert page["pageInfo"] == {"endCursor": None, "hasNextPage": False}

    _sold(world, key="sale-1")
    assert_is_error(_sales(event_id="SSE#never-created"), "NOT_FOUND"), (
        "an event that was never created is not an event that sold nothing"
    )


def test_two_events_in_one_campaign_never_share_a_sale_list(world: Dict[str, Any]) -> None:
    """§4.5.2: the read is addressed by event, so an event's list is its own rows only."""
    _seed_table(world, rival=True)
    _seed_allocation(world["inventory"], RIVAL_EVENT, PRODUCT, allocated=4)
    here = str(_sold(world, key="sale-1")["sale"]["saleId"])
    there = str(_sold(world, key="sale-2", event_id=RIVAL_EVENT)["sale"]["saleId"])

    assert _sale_ids(_ok(_sales())) == [here]
    assert _sale_ids(_ok(_sales(event_id=RIVAL_EVENT))) == [there]


# --- Tenancy and privacy (AUTH-U, SEC-04) ---------------------------------------


def test_the_sale_read_is_the_events_own_history_and_no_other_caller_reaches_it(world: Dict[str, Any]) -> None:
    """AUTH-U, SEC-04: an unknown event and a foreign caller give the same answer."""
    _seed_table(world)
    _sold(world, buyerName="Nora N", buyerPhone="303-555-0100", buyerEmail="nora@example.test")

    for persona in ("Blake", "Taylor", "Devon", "Riley", "Emery"):
        assert_is_error(_sales(persona), "NOT_FOUND")
    assert_is_error(_sales(None), "UNAUTHORIZED")
    assert_is_error(_sales("Avery", event_id="SSE#never-created"), "NOT_FOUND")
    assert_is_error(_sales("Avery", event_id="   "), "INVALID_INPUT")

    assert_is_error(_sales("Avery", event_id="uc-crew-529-spring-2027"), "NOT_FOUND"), (
        "a campaign id is not an event id; the event read is refused rather than answered"
    )


def test_the_buyers_contact_detail_travels_on_the_sale_and_nowhere_else(world: Dict[str, Any]) -> None:
    """SEC-04: the sale carries the snapshot; the obligation a We Owe list shows carries the name."""
    _seed_table(world)
    _sold(world, lines=[_line(PRODUCT, immediate=1, we_owe=1)], buyerName="Nora N", buyerPhone="303-555-0100", buyerEmail="nora@example.test")

    listed = _ok(_sales())["items"]
    assert [(item["buyerName"], item["buyerPhone"], item["buyerEmail"]) for item in listed] == [
        ("Nora N", "303-555-0100", "nora@example.test")
    ]

    obligations = _ok(_call(WE_OWE_OBLIGATIONS_FIELD, "Avery", arguments={"unitCampaignId": CAMPAIGN}))["items"]
    assert [item["buyerName"] for item in obligations] == ["Nora N"]
    for item in obligations:
        assert "buyerPhone" not in item and "buyerEmail" not in item


# --- The version tokens the next screen writes against (VER-01) -----------------


def test_every_raw_read_finalization_walks_carries_the_version_its_write_conditions_on(
    world: Dict[str, Any],
) -> None:
    """§4.5.2: sale, event, balance, allocation, obligation and signup versions all survive the read.

    Finalization, the sale screen and the We Owe screen are all optimistic-concurrency
    writers, and each one conditions on a number it read on this same surface. A read that
    dropped a version would leave the screen unable to write at all, and a read that
    invented one would let it pin a number the row never had.
    """
    _seed_table(world)
    _method(world["units"])
    _seed_signup(world["show_and_sells"], ACTIVE_EVENT, minutes=45)
    sale = _sold(world, lines=[_line(PRODUCT, immediate=1, we_owe=1)], buyerName="Nora N")
    obligation_id = str(sale["obligations"][0]["weOweId"])

    sales = _ok(_sales())["items"]
    assert [item["revision"] for item in sales] == [1]

    event = _ok(_call(SHOW_AND_SELL_FIELD, "Avery", arguments={"showAndSellId": ACTIVE_EVENT}))
    assert event["version"] == _stored_event(world["show_and_sells"], ACTIVE_EVENT)[ssm.VERSION_ATTRIBUTE]

    positions = _ok(_call(INVENTORY_POSITIONS_FIELD, "Avery", arguments={"unitCampaignId": CAMPAIGN}))["items"]
    assert [item["version"] for item in positions] == [2], "the campaign balance moved one version with the sale"

    allocations = _ok(
        _call(EVENT_INVENTORY_ALLOCATIONS_FIELD, "Avery", arguments={"unitCampaignId": CAMPAIGN, "showAndSellId": ACTIVE_EVENT})
    )["items"]
    assert [item["version"] for item in allocations] == [2], "the sale moved the allocation's sold quantity and its version"

    obligations = _ok(_call(WE_OWE_OBLIGATIONS_FIELD, "Avery", arguments={"unitCampaignId": CAMPAIGN}))["items"]
    assert [(item["weOweId"], item["version"]) for item in obligations] == [(obligation_id, 1)]

    signups = _ok(_call(SHOW_AND_SELL_SIGNUPS_FIELD, "Avery", arguments={"showAndSellId": ACTIVE_EVENT}))["items"]
    assert [item["version"] for item in signups] == [1], "the seeded confirmed signup carries its own version"

    methods = _ok(_call(UNIT_PAYMENT_METHODS_FIELD, "Avery", arguments={"unitId": UNIT}))
    custom = [item for item in methods if item["paymentMethodId"] == "pm-wise-sale"]
    assert [item["version"] for item in custom] == [1]
    assert [item["version"] for item in methods if item["paymentMethodId"] == "CASH"] == [0], (
        "a built-in method is not mutable, and says so with the version no write can pin"
    )
