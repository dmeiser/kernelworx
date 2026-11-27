"""Wave 6.1 — finalization discovery, detail, and the frozen child rows (§5.1.4).

Resolver-level cases for the six finalization reads: ``showAndSellFinalizations``
listing APPROVED/SUSPENDED/SUPERSEDED versions in chain order with their
``previousFinalizationId`` links, ``showAndSellFinalization`` returning the full
record or ``null`` for an absent id, and the four paginated child reads over the
rows one version froze — sale snapshots, work snapshots, return lines, credits.

Per Amendment A every finalization row here is written through the model layer —
``build_finalization_row`` and the suspend/supersede transforms put straight on the
table — because no approve/reopen writer ships on this card (those are §5.2/§5.3,
WORK-175/WORK-176); the live-``dev`` leg of this work order is the empty history,
the null detail, and ``AUTH-U``. The one live half these tests do drive through
product mutations is the immutability claim itself: a sale is created through
``createShowAndSellSale``, frozen through the model snapshot, then VOIDED through
``voidShowAndSellSale`` — and the version's snapshot answer does not move.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from src.handlers.unit_operations import (
    FINALIZATION_CREDITS_FIELD,
    FINALIZATION_RETURN_LINES_FIELD,
    FINALIZATION_SALE_SNAPSHOTS_FIELD,
    FINALIZATION_WORK_SNAPSHOTS_FIELD,
    SHOW_AND_SELL_FINALIZATION_FIELD,
    SHOW_AND_SELL_FINALIZATIONS_FIELD,
)
from src.utils import show_and_sell_finalization_models as fm
from src.utils import show_and_sell_models as ssm
from tests.unit.show_sell_fixtures import (
    assert_is_error,
    seed_show_sell_fixtures,
)
from tests.unit.test_show_and_sell_finalization_preview import (  # the §5.1.2 world: ended table, sales via the product
    A_SCOUT,
    B_SCOUT,
    ENDED_EVENT,
    _call,
    _ended_event,
    _ok,
    _sell,
)
from tests.unit.test_show_and_sell_sales import (
    AVERY,
    CAMPAIGN,
    PRODUCT,
    _stored_sale,
    _void,
)

FIN_ONE = "fin-alpha"
FIN_TWO = "fin-beta"
FIN_THREE = "fin-gamma"


def _query(field: str, caller: Any = "Avery", **arguments: Any) -> Any:
    return _call(field, caller, arguments=arguments)


def _history(caller: Any = "Avery", *, event_id: str = ENDED_EVENT, page: Optional[Dict[str, Any]] = None) -> Any:
    arguments: Dict[str, Any] = {"showAndSellId": event_id}
    if page is not None:
        arguments["page"] = page
    return _query(SHOW_AND_SELL_FINALIZATIONS_FIELD, caller, **arguments)


def _detail(finalization_id: str, caller: Any = "Avery", *, event_id: str = ENDED_EVENT) -> Any:
    return _query(SHOW_AND_SELL_FINALIZATION_FIELD, caller, showAndSellId=event_id, finalizationId=finalization_id)


def _children(
    field: str,
    finalization_id: str,
    *,
    event_id: str = ENDED_EVENT,
    page: Optional[Dict[str, Any]] = None,
) -> Any:
    arguments: Dict[str, Any] = {"showAndSellId": event_id, "finalizationId": finalization_id}
    if page is not None:
        arguments["page"] = page
    return _query(field, "Avery", **arguments)


def _cash(pool: int, *, actual: Optional[int] = None) -> Dict[str, Any]:
    return fm.cash_reconciliation(
        calculated_expected_cents=pool,
        actual_cash_cents=pool if actual is None else actual,
        discrepancy_explanation=None if actual in (None, pool) else "one five-dollar bill went missing",
    )


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
    """The Stage 1 persona world plus the tables finalization history lives on."""
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    from tests.unit.test_show_and_sell_sales import _offer_products

    _offer_products(catalogs_table, 4)
    return {
        "show_and_sells": show_and_sells_table,
        "inventory": inventory_table,
        "catalogs": catalogs_table,
        "units": units_table,
    }


def _seed_finalization(
    world: Dict[str, Any],
    finalization_id: str,
    *,
    version_number: int,
    pool: int = 1500,
    previous: Optional[str] = None,
    status: str = fm.FINALIZATION_STATUS_APPROVED,
    split: str = "EQUAL",
) -> Dict[str, Any]:
    """Write one version through the model layer — the §5.1.4 test fixture, per Amendment A.

    The row is born APPROVED from ``build_finalization_row`` and moved by the same
    transforms §5.2/§5.3 will run when they ship; nothing here goes through a
    resolver this card does not ship.
    """
    row = fm.build_finalization_row(
        show_and_sell_id=ENDED_EVENT,
        unit_campaign_id=CAMPAIGN,
        finalization_id=finalization_id,
        version_number=version_number,
        whole_pool_cents=pool,
        split_method=split,
        cash=_cash(pool),
        previous_finalization_id=previous,
        approved_by_account_id=AVERY,
        approved_at=f"2026-11-0{version_number}T12:00:00+00:00",
        source_event_version=version_number + 2,
    )
    if status == fm.FINALIZATION_STATUS_SUSPENDED:
        row = fm.mark_finalization_suspended(
            row,
            suspended_by_account_id=AVERY,
            suspended_at=f"2026-11-0{version_number}T13:00:00+00:00",
            suspension_reason="a box came back after the approval",
        )
    elif status == fm.FINALIZATION_STATUS_SUPERSEDED:
        row = fm.mark_finalization_superseded(row)
    world["show_and_sells"].put_item(Item=row)
    return row


def _seed_child_rows(world: Dict[str, Any], finalization: Dict[str, Any]) -> List[str]:
    """Freeze one sale (created by the real mutation), one work row, one return line, one credit."""
    fid = str(finalization[fm.FINALIZATION_ID_ATTRIBUTE])
    sale_id = _ok(_sell(world, boxes=3, key="finalized-sale"))["sale"]["saleId"]
    sale_row = _stored_sale(world["show_and_sells"], ENDED_EVENT, sale_id)
    assert sale_row is not None
    world["show_and_sells"].put_item(
        Item=fm.build_sale_snapshot_row(finalization_id=fid, sale=sale_row, show_and_sell_id=ENDED_EVENT)
    )
    world["show_and_sells"].put_item(
        Item=fm.build_work_snapshot_row(
            finalization_id=fid,
            show_and_sell_id=ENDED_EVENT,
            slot_id="slot-budget",
            profile_id=A_SCOUT,
            campaign_id="SC#sale-budget",
            actual_minutes=240,
            source_signup_version=2,
        )
    )
    world["show_and_sells"].put_item(
        Item=fm.build_return_line_row(
            show_and_sell_id=ENDED_EVENT,
            finalization_id=fid,
            product_id=PRODUCT,
            allocated_qty=4,
            expected_qty=3,
            actual_qty=2,
            reconciliation_movement_id="mov-fin-1",
            reason="one box was damaged at the table",
        )
    )
    world["show_and_sells"].put_item(
        Item=fm.build_credit_row(
            finalization=finalization,
            campaign_id="SC#sale-budget",
            profile_id=A_SCOUT,
            actual_minutes=240,
            base_amount_cents=1500,
            rounding_credit_cents=0,
            created_at="2026-11-01T12:00:00+00:00",
            updated_at="2026-11-01T12:00:00+00:00",
        )
    )
    return [sale_id]


# --- Discovery and chains (§5.1.4) -------------------------------------------------


def test_history_lists_every_version_in_chain_order_with_its_predecessor(world: Dict[str, Any]) -> None:
    """First approval, then a re-finalization: both versions stand, chained, with their own statuses."""
    _ended_event(world, boxes=4)
    # The same key, rewritten by the supersede transform: re-finalization retires the
    # prior version's row in place (§5.16) while appending the new version's.
    _seed_finalization(world, FIN_ONE, version_number=1, status=fm.FINALIZATION_STATUS_SUPERSEDED)
    _seed_finalization(world, FIN_TWO, version_number=2, previous=FIN_ONE)

    answer = _ok(_history())
    assert [item["versionNumber"] for item in answer["items"]] == [1, 2]
    one, two = answer["items"]
    assert one["finalizationId"] == FIN_ONE
    assert one["status"] == fm.FINALIZATION_STATUS_SUPERSEDED
    assert one["previousFinalizationId"] is None
    assert two["finalizationId"] == FIN_TWO
    assert two["status"] == fm.FINALIZATION_STATUS_APPROVED
    assert two["previousFinalizationId"] == FIN_ONE


def test_detail_answers_the_whole_record_and_history_stays_readable_after_a_newer_version(
    world: Dict[str, Any],
) -> None:
    """Current-versus-history: the retired version's detail still reads, exactly as it stands."""
    _ended_event(world, boxes=4)
    _seed_finalization(world, FIN_ONE, version_number=1, pool=1500)
    _seed_finalization(world, FIN_ONE, version_number=1, pool=1500, status=fm.FINALIZATION_STATUS_SUPERSEDED)
    _seed_finalization(world, FIN_TWO, version_number=2, pool=2000, previous=FIN_ONE, split="TIME_WORKED")

    current = _ok(_detail(FIN_TWO))
    assert current["status"] == fm.FINALIZATION_STATUS_APPROVED
    assert current["wholePoolCents"] == 2000
    assert current["splitMethod"] == "TIME_WORKED"
    assert current["cash"]["calculatedExpectedCents"] == 2000
    assert current["cash"]["discrepancyCents"] == 0
    assert current["previousFinalizationId"] == FIN_ONE
    assert current["sourceEventVersion"] == 4
    assert current["approvedByAccountId"] == AVERY
    assert current["suspendedByAccountId"] is None

    retired = _ok(_detail(FIN_ONE))
    assert retired["status"] == fm.FINALIZATION_STATUS_SUPERSEDED
    assert retired["wholePoolCents"] == 1500  # the old pool is not restated at the new one


def test_a_suspended_version_carries_its_reopen_audit_forever(world: Dict[str, Any]) -> None:
    """§5.16 reason-history: who, when, and why a version stopped standing — on the version."""
    _ended_event(world, boxes=4)
    _seed_finalization(world, FIN_ONE, version_number=1, status=fm.FINALIZATION_STATUS_SUSPENDED)

    detail = _ok(_detail(FIN_ONE))
    assert detail["status"] == fm.FINALIZATION_STATUS_SUSPENDED
    assert detail["suspendedByAccountId"] == AVERY
    assert detail["suspendedAt"] == "2026-11-01T13:00:00+00:00"
    assert detail["suspensionReason"] == "a box came back after the approval"
    assert _ok(_history())["items"][0]["status"] == fm.FINALIZATION_STATUS_SUSPENDED


def test_an_unfinalized_event_answers_an_empty_history_and_a_null_detail(world: Dict[str, Any]) -> None:
    """Amendment A's live leg: empty page and null, never an error, for the never-finalized event."""
    _ended_event(world, boxes=4)

    page = _ok(_history())
    assert page["items"] == []
    assert page["pageInfo"]["hasNextPage"] is False
    assert page["pageInfo"]["endCursor"] is None
    assert _detail(FIN_ONE) is None


def test_history_pages_walk_a_cursor_and_a_cursor_cannot_cross_events(world: Dict[str, Any]) -> None:
    """PAGE-01 on the chain: three versions page two-and-one, and the token belongs to this event."""
    _ended_event(world, boxes=4)
    _seed_finalization(world, FIN_ONE, version_number=1)
    _seed_finalization(world, FIN_ONE, version_number=1, status=fm.FINALIZATION_STATUS_SUPERSEDED)
    _seed_finalization(world, FIN_TWO, version_number=2, previous=FIN_ONE)
    _seed_finalization(world, FIN_TWO, version_number=2, previous=FIN_ONE, status=fm.FINALIZATION_STATUS_SUPERSEDED)
    _seed_finalization(world, FIN_THREE, version_number=3, previous=FIN_TWO)
    _seed_event_other(world)
    first = _ok(_history(page={"limit": 2}))
    assert [item["versionNumber"] for item in first["items"]] == [1, 2]
    assert first["pageInfo"]["hasNextPage"] is True
    second = _ok(_history(page={"limit": 2, "cursor": first["pageInfo"]["endCursor"]}))
    assert [item["versionNumber"] for item in second["items"]] == [3]
    assert second["pageInfo"]["hasNextPage"] is False

    # The event-two list is empty, and the event-one token is refused there — a cursor
    # is a positional claim inside one specific result set (PAGE-01).
    assert _ok(_history(event_id=OTHER_EVENT))["items"] == []
    error = assert_is_error(
        _history(event_id=OTHER_EVENT, page={"limit": 2, "cursor": first["pageInfo"]["endCursor"]}), "INVALID_INPUT"
    )
    assert "different request" in error["message"]


OTHER_EVENT = "SSE#no-finalizations"


def _seed_event_other(world: Dict[str, Any]) -> None:
    from tests.unit.test_show_and_sell_sales import _seed_event

    _seed_event(world["show_and_sells"], OTHER_EVENT)


# --- The frozen child collections ---------------------------------------------------


def test_child_pages_answer_the_frozen_rows_and_refuse_an_absent_version(world: Dict[str, Any]) -> None:
    """One version's four collections, shaped, scoped, and refused whole for an id that names nothing."""
    _ended_event(world, boxes=4)
    finalization = _seed_finalization(world, FIN_ONE, version_number=1)
    _seed_child_rows(world, finalization)

    snapshots = _ok(_children(FINALIZATION_SALE_SNAPSHOTS_FIELD, FIN_ONE))
    assert len(snapshots["items"]) == 1
    sale = snapshots["items"][0]
    assert sale["finalizationId"] == FIN_ONE
    assert sale["totalCents"] == 1500
    assert sale["paymentMethodSnapshot"]["methodCode"] == "CASH"
    assert sale["lineItems"][0]["productNameSnapshot"] == "Caramel 1"

    work = _ok(_children(FINALIZATION_WORK_SNAPSHOTS_FIELD, FIN_ONE))
    assert work["items"] == [
        {
            "finalizationId": FIN_ONE,
            "slotId": "slot-budget",
            "profileId": A_SCOUT,
            "campaignId": "SC#sale-budget",
            "actualMinutes": 240,
            "sourceSignupVersion": 2,
        }
    ]

    lines = _ok(_children(FINALIZATION_RETURN_LINES_FIELD, FIN_ONE))
    line = lines["items"][0]
    assert line["productId"] == PRODUCT
    assert (line["allocatedQty"], line["expectedQty"], line["actualQty"]) == (4, 3, 2)
    assert (line["varianceQty"], line["netStockEffectQty"]) == (-1, -2)
    assert line["reconciliationMovementId"] == "mov-fin-1"

    credits = _ok(_children(FINALIZATION_CREDITS_FIELD, FIN_ONE))
    credit = credits["items"][0]
    assert credit["profileId"] == A_SCOUT
    assert credit["baseAmountCents"] + credit["roundingCreditCents"] == credit["amountCents"]
    assert credit["status"] == fm.ALLOCATION_STATUS_APPROVED

    missing = assert_is_error(_children(FINALIZATION_CREDITS_FIELD, FIN_THREE), "NOT_FOUND")
    assert "not found" in missing["message"]
    assert_is_error(_children(FINALIZATION_CREDITS_FIELD, "bad#id"), "INVALID_INPUT")


def test_a_snapshot_survives_the_void_of_the_sale_it_came_from(world: Dict[str, Any]) -> None:
    """§5.17's whole point: void the live sale, and the version's report answer does not move."""
    _ended_event(world, boxes=4)
    finalization = _seed_finalization(world, FIN_ONE, version_number=1)
    sale_id = _seed_child_rows(world, finalization)[0]

    event_version = int(ssm.read_show_and_sell(ENDED_EVENT)[ssm.VERSION_ATTRIBUTE])  # type: ignore[index]
    _ok(_void(sale_id=sale_id, event_id=ENDED_EVENT, revision=1, version=event_version, key="void-after-approval"))

    snapshot = _ok(_children(FINALIZATION_SALE_SNAPSHOTS_FIELD, FIN_ONE))["items"][0]
    assert snapshot["saleId"] == sale_id
    assert snapshot["totalCents"] == 1500  # the frozen answer, not the voided live row
    assert _ok(_detail(FIN_ONE))["wholePoolCents"] == 1500


def test_child_cursors_are_scoped_to_one_version(world: Dict[str, Any]) -> None:
    """A page token from one version's credits cannot be replayed on another version's."""
    _ended_event(world, boxes=4)
    one = _seed_finalization(world, FIN_ONE, version_number=1)
    for scout in (A_SCOUT, B_SCOUT):
        world["show_and_sells"].put_item(
            Item=fm.build_credit_row(
                finalization=one,
                campaign_id="SC#sale-budget",
                profile_id=scout,
                actual_minutes=100,
                base_amount_cents=750,
                rounding_credit_cents=0,
                created_at="2026-11-01T12:00:00+00:00",
                updated_at="2026-11-01T12:00:00+00:00",
            )
        )
    _seed_finalization(world, FIN_TWO, version_number=2, previous=FIN_ONE)

    first = _ok(_children(FINALIZATION_CREDITS_FIELD, FIN_ONE, page={"limit": 1}))
    assert len(first["items"]) == 1
    cursor = first["pageInfo"]["endCursor"]

    crossed = assert_is_error(
        _children(FINALIZATION_CREDITS_FIELD, FIN_TWO, page={"limit": 1, "cursor": cursor}), "INVALID_INPUT"
    )
    assert "different request" in crossed["message"]
    # The same version's second page answers normally.
    second = _ok(_children(FINALIZATION_CREDITS_FIELD, FIN_ONE, page={"limit": 1, "cursor": cursor}))
    assert len(second["items"]) == 1


def test_only_the_events_unit_admin_reads_finalization_history(world: Dict[str, Any]) -> None:
    """AUTH-U across the six reads: no existence to another Unit's admin, a removed admin, or an anonymous caller."""
    _ended_event(world, boxes=4)
    _seed_finalization(world, FIN_ONE, version_number=1)

    for caller in ("Blake", "Riley"):
        for field, arguments in (
            (SHOW_AND_SELL_FINALIZATIONS_FIELD, {"showAndSellId": ENDED_EVENT}),
            (SHOW_AND_SELL_FINALIZATION_FIELD, {"showAndSellId": ENDED_EVENT, "finalizationId": FIN_ONE}),
            (FINALIZATION_CREDITS_FIELD, {"showAndSellId": ENDED_EVENT, "finalizationId": FIN_ONE}),
        ):
            error = assert_is_error(_query(field, caller, **arguments), "NOT_FOUND")
            assert "not found" in error["message"]
    assert_is_error(_query(SHOW_AND_SELL_FINALIZATIONS_FIELD, None, showAndSellId=ENDED_EVENT), "UNAUTHORIZED")
