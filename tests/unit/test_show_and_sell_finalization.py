"""Wave 6.2 — first finalization, automatic reductions and cash/return reconciliation (§5.2).

Resolver-level cases for ``finalizeShowAndSell``. Everything runs through
``handle_unit_operation`` against moto: the cohort of rows that must commit together
(finalization, snapshots, credit, scoped totals, allocation releases, return and
automatic-reduction movements, later-event versions, the approved pointer) is asserted
by reading the tables back, and every refusal is followed by a read that proves nothing
was written. The four-box Morning/Afternoon oracle is driven through the real sale
mutation, so the physical stock the reduction reads is the stock the sale moved.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pytest

from src.handlers import unit_operations as uo
from src.handlers.unit_operations import FINALIZE_SHOW_AND_SELL_FIELD, handle_unit_operation
from src.utils import inventory_models as inv
from src.utils import show_and_sell_finalization_models as fm
from src.utils import show_and_sell_models as ssm
from src.utils import show_and_sell_sale_models as sm
from tests.unit.show_sell_fixtures import (
    assert_is_error,
    seed_show_sell_fixtures,
    unit_operation_event,
)
from tests.unit.test_show_and_sell_finalization_preview import (
    A_SCOUT,
    B_SCOUT,
    ENDED_EVENT,
    _sell,
)
from tests.unit.test_show_and_sell_sales import (
    CAMPAIGN,
    ENDED_END,
    ENDED_SALE_AT,
    ENDED_START,
    OTHER_PRODUCT,
    PRODUCT,
    _create,
    _line,
    _offer_products,
    _seed_allocation,
    _seed_balance,
    _seed_event,
    _seed_signup,
    _stored_event,
)

LATER_EVENT = "SSE#later"
LAST_EVENT = "SSE#last"


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
        "unit_campaigns": unit_campaigns_table,
    }


def _ended(
    world: Dict[str, Any],
    *,
    boxes: int,
    event_id: str = ENDED_EVENT,
    product: str = PRODUCT,
    split: str = "EQUAL",
    version: int = 1,
    start_at: str = ENDED_START,
    end_at: str = ENDED_END,
    allocation: bool = True,
    allocated: Optional[int] = None,
) -> None:
    _seed_event(
        world["show_and_sells"],
        event_id,
        start_at=start_at,
        end_at=end_at,
        product_ids=[product] if allocation else [],
        splitMethod=split,
        version=version,
    )
    _seed_balance(world["inventory"], product, physical=boxes)
    if allocation:
        _seed_allocation(
            world["inventory"],
            event_id,
            product,
            allocated=boxes if allocated is None else allocated,
            start_at=start_at,
            end_at=end_at,
        )


def _return(product: str = PRODUCT, actual: int = 0, reason: Optional[str] = None) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"productId": product, "actualQty": actual}
    if reason is not None:
        entry["reason"] = reason
    return entry


def _cash(actual: int = 0, **extra: Any) -> Dict[str, Any]:
    return {"actualCashCents": actual, **extra}


def _assign(profile: str, cents: int) -> Dict[str, Any]:
    return {"profileId": profile, "cents": cents}


def _finalize(
    world: Dict[str, Any],
    *,
    returns: Optional[Sequence[Dict[str, Any]]] = None,
    cash: Optional[Dict[str, Any]] = None,
    rounding: Optional[Sequence[Dict[str, Any]]] = None,
    version: Optional[int] = None,
    caller: Any = "Avery",
    key: str = "approve-1",
    event_id: str = ENDED_EVENT,
    **extra: Any,
) -> Any:
    if version is None:
        version = int(_stored_event(world["show_and_sells"], event_id)[ssm.VERSION_ATTRIBUTE])
    payload: Dict[str, Any] = {
        "showAndSellId": event_id,
        "returns": list(returns) if returns is not None else [_return()],
        "cash": cash if cash is not None else _cash(),
        "roundingAssignments": list(rounding) if rounding is not None else [],
        "version": {"expectedVersion": version},
        "idempotency": {"idempotencyKey": key},
        **extra,
    }
    return handle_unit_operation(
        unit_operation_event(FINALIZE_SHOW_AND_SELL_FIELD, caller, input=payload), None
    )


def _ok(payload: Any) -> Dict[str, Any]:
    failed = isinstance(payload, dict) and payload.get("__isError")
    assert not failed, f"expected success, got {payload!r}"
    return payload


def _rows(table: Any, entity_type: str) -> List[Dict[str, Any]]:
    return [row for row in table.scan()["Items"] if row.get("entityType") == entity_type]


def _movements(world: Dict[str, Any], kind: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = _rows(world["inventory"], inv.MOVEMENT_ENTITY_TYPE)
    return [row for row in rows if kind is None or row.get("movementType") == kind]


def _allocation(world: Dict[str, Any], event_id: str, product: str = PRODUCT) -> Dict[str, Any]:
    key = inv.allocation_key(CAMPAIGN, product, event_id) if hasattr(inv, "allocation_key") else None
    for row in _rows(world["inventory"], inv.ALLOCATION_ENTITY_TYPE):
        if row.get("showAndSellId") == event_id and row.get("productId") == product:
            assert key is None or key == {"pk": row["pk"], "sk": row["sk"]}
            return dict(row)
    raise AssertionError(f"no allocation row for {event_id}/{product}")


def _balance(world: Dict[str, Any], product: str = PRODUCT) -> Dict[str, Any]:
    for row in _rows(world["inventory"], inv.BALANCE_ENTITY_TYPE):
        if row.get("productId") == product:
            return dict(row)
    raise AssertionError(f"no balance for {product}")


def _two_shares(world: Dict[str, Any]) -> None:
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=240, profile_id=A_SCOUT)
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=120, profile_id=B_SCOUT)


# --- 5.2.1: the first approval --------------------------------------------------


def test_a_no_sale_event_publishes_an_empty_credit_set_and_a_finalized_event(world: Dict[str, Any]) -> None:
    """No sales, no allocations: the empty version still moves the event atomically."""
    _ended(world, boxes=0, allocation=False)
    answer = _ok(_finalize(world, returns=[], cash=_cash()))
    finalization = answer["finalization"]
    assert finalization["wholePoolCents"] == 0
    assert finalization["status"] == fm.FINALIZATION_STATUS_APPROVED
    assert answer["scoutAllocations"] == []
    assert answer["warnings"] == []
    event = _stored_event(world["show_and_sells"], ENDED_EVENT)
    assert event[ssm.STATUS_ATTRIBUTE] == ssm.STATUS_FINALIZED
    assert event[ssm.APPROVED_FINALIZATION_ID_ATTRIBUTE] == finalization["finalizationId"]
    assert event[ssm.LATEST_FINALIZATION_ID_ATTRIBUTE] == finalization["finalizationId"]
    assert int(event[ssm.VERSION_ATTRIBUTE]) == 2


def test_a_sixty_dollar_time_worked_pool_approves_exact_credit_once(world: Dict[str, Any]) -> None:
    """$60 with 240/120 confirmed minutes: $40/$20, no cent left, no second credit."""
    _ended(world, boxes=12, split="TIME_WORKED")
    _two_shares(world)
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=0, profile_id="PROFILE#no-work")
    _sell(world, boxes=12, key="sixty")
    version = int(_stored_event(world["show_and_sells"], ENDED_EVENT)[ssm.VERSION_ATTRIBUTE])
    answer = _ok(_finalize(world, cash=_cash(6000), version=version))
    assert answer["finalization"]["wholePoolCents"] == 6000
    credits = {row["profileId"]: row for row in answer["scoutAllocations"]}
    assert set(credits) == {A_SCOUT, B_SCOUT}
    assert credits[A_SCOUT]["amountCents"] == 4000
    assert credits[B_SCOUT]["amountCents"] == 2000
    assert [row["status"] for row in credits.values()] == [fm.ALLOCATION_STATUS_APPROVED] * 2
    assert sum(int(row["approvedAmountCents"]) for row in world["unit_campaigns"].scan()["Items"] if row.get("entityType") == fm.TOTAL_ENTITY_TYPE) == 6000
    assert _finalize(world, cash=_cash(6000), version=version, key="approve-1") == answer  # idem: one version
    assert len(_rows(world["show_and_sells"], fm.FINALIZATION_ENTITY_TYPE)) == 1
    assert len(_rows(world["show_and_sells"], fm.CREDIT_ENTITY_TYPE)) == 2


def test_open_we_owe_counts_once_and_its_obligation_stays_open(world: Dict[str, Any]) -> None:
    """An open We Owe line enters the pool through its sale and never becomes a second credit."""
    _ended(world, boxes=3)
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=60, profile_id=A_SCOUT)
    sale = _ok(_sell(world, boxes=1, we_owe=2, key="owe-open", buyerName="Sam Buyer"))
    total = int(sale["sale"]["totalCents"])
    answer = _ok(_finalize(world, returns=[_return(actual=2)], cash=_cash(total)))
    assert answer["finalization"]["wholePoolCents"] == total
    assert sum(row["amountCents"] for row in answer["scoutAllocations"]) == 1500
    obligations = [row for row in world["show_and_sells"].scan()["Items"] if row.get("entityType") == sm.WE_OWE_ENTITY_TYPE]
    assert len(obligations) == 1
    assert obligations[0]["status"] == sm.WE_OWE_STATUS_OPEN


def test_missing_inputs_and_stale_versions_write_nothing(world: Dict[str, Any]) -> None:
    """5.2.1's denial cases: a refused approval leaves no finalization, credit or movement."""
    _ended(world, boxes=2)
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=60, profile_id=A_SCOUT)
    assert_is_error(_finalize(world, returns=[], cash=_cash()), "INVALID_INPUT")  # missing return
    assert_is_error(_finalize(world, returns=[_return(actual=5)], cash=_cash()), "INVALID_INPUT")  # unexplained variance
    assert_is_error(_finalize(world, rounding=[_assign(A_SCOUT, 1)]), "CONFLICT")  # an unassigned cent
    assert_is_error(_finalize(world, version=99), "CONFLICT")  # stale event version
    assert_is_error(_finalize(world, caller="Taylor"), "NOT_FOUND")  # AUTH-U
    assert _rows(world["show_and_sells"], fm.FINALIZATION_ENTITY_TYPE) == []
    assert _rows(world["show_and_sells"], fm.CREDIT_ENTITY_TYPE) == []


def test_a_scheduled_event_cannot_take_its_first_finalization(world: Dict[str, Any]) -> None:
    from tests.unit.test_show_and_sell_sales import FUTURE_END, FUTURE_START

    _ended(world, boxes=1, event_id=ENDED_EVENT, start_at=FUTURE_START, end_at=FUTURE_END)
    assert_is_error(_finalize(world), "CONFLICT")
    assert _rows(world["show_and_sells"], fm.FINALIZATION_ENTITY_TYPE) == []


def test_an_oversized_plan_is_refused_before_any_write(world: Dict[str, Any], monkeypatch: Any) -> None:
    """The 90-action ceiling is a pre-write refusal, not a partially committed plan."""
    _ended(world, boxes=2)
    monkeypatch.setattr(uo, "MAX_TRANSACTION_ACTIONS", 2)
    error = assert_is_error(_finalize(world, returns=[_return(actual=1, reason="one box damaged")]), "CONFLICT")
    assert "too large" in error["message"]
    assert _rows(world["show_and_sells"], fm.FINALIZATION_ENTITY_TYPE) == []


# --- 5.2.2: earlier-event priority ----------------------------------------------


def _four_boxes_with_two_later_events(world: Dict[str, Any]) -> None:
    """Morning holds three of four and sells two; two later events each ask for three."""
    from tests.unit.test_show_and_sell_sales import FUTURE_END, FUTURE_START

    _ended(world, boxes=4, allocated=3)
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=60, profile_id=A_SCOUT)
    _sell(world, boxes=2, key="morning-sale")
    for event_id, start, end in (
        (LATER_EVENT, FUTURE_START, FUTURE_END),
        (LAST_EVENT, FUTURE_END, "2027-01-01T00:00:00+00:00"),
    ):
        _seed_event(
            world["show_and_sells"],
            event_id,
            start_at=start,
            end_at=end,
            product_ids=[PRODUCT],
            version=1,
        )
        _seed_allocation(
            world["inventory"],
            event_id,
            PRODUCT,
            allocated=3,
            start_at=start,
            end_at=end,
        )


def test_the_four_box_morning_afternoon_oracle_reduces_three_to_two(world: Dict[str, Any]) -> None:
    """AC-11: 4 physical, morning sells 2 of 3, afternoon's open 3 becomes 2."""
    _four_boxes_with_two_later_events(world)
    answer = _ok(_finalize(world, returns=[_return(actual=1)], cash=_cash(1000)))
    assert _allocation(world, ENDED_EVENT)["status"] == inv.ALLOCATION_RELEASED
    assert int(_allocation(world, LATER_EVENT)["allocatedQty"]) == 2
    assert int(_allocation(world, LATER_EVENT)["remainingQty"]) == 2
    reductions = {str(row["showAndSellId"]): int(row[inv.ASSIGNED_DELTA]) for row in _movements(world, inv.EVENT_AUTO_REDUCE)}
    assert reductions == {LATER_EVENT: -1, LAST_EVENT: -3}
    warnings = [row for row in answer["warnings"] if row["code"] == "AUTOMATIC_ALLOCATION_REDUCTION"]
    assert [(row["productId"], row["assignedQty"], row["overageQty"]) for row in warnings] == [
        (PRODUCT, 2, 1),
        (PRODUCT, 0, 3),
    ]
    # The later events are guarded by a version condition, not rewritten by another
    # resolver's pointer: only their allocations and the audit movements change.
    assert int(_stored_event(world["show_and_sells"], LATER_EVENT)[ssm.VERSION_ATTRIBUTE]) == 1
    assert int(_stored_event(world["show_and_sells"], LAST_EVENT)[ssm.VERSION_ATTRIBUTE]) == 1


def test_a_later_events_version_cancels_the_whole_reduction(world: Dict[str, Any], monkeypatch: Any) -> None:
    """A competing writer to a later event loses the finalization whole, with no partial rows."""
    _four_boxes_with_two_later_events(world)
    load = ssm.load_show_and_sell_or_not_found

    def stale(event_id: str) -> Dict[str, Any]:
        row = dict(load(event_id))
        if event_id == LATER_EVENT:
            row[ssm.VERSION_ATTRIBUTE] = 9  # the caller read version 1
        return row

    monkeypatch.setattr(ssm, "load_show_and_sell_or_not_found", stale)
    assert_is_error(_finalize(world, returns=[_return(actual=1)], cash=_cash(1000)), "CONFLICT")
    assert _rows(world["show_and_sells"], fm.FINALIZATION_ENTITY_TYPE) == []
    assert _movements(world, inv.EVENT_AUTO_REDUCE) == []
    assert int(_allocation(world, LATER_EVENT)["allocatedQty"]) == 3


# --- 5.2.3: returns and cash ----------------------------------------------------


def test_a_return_variance_is_a_reasoned_stock_only_adjustment(world: Dict[str, Any]) -> None:
    """FIN-04: ten assigned, six sold, four expected, three returned: one stock move only."""
    _ended(world, boxes=10)
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=60, profile_id=A_SCOUT)
    _sell(world, boxes=6, key="six-sold")
    answer = _ok(_finalize(world, returns=[_return(actual=3, reason="one box was damaged")], cash=_cash(3000)))
    assert int(_balance(world)["kernelPhysicalQty"]) == 3  # 10 - 6 sold - 1 missing
    lines = _rows(world["show_and_sells"], fm.RETURN_LINE_ENTITY_TYPE)
    assert len(lines) == 1
    assert (int(lines[0]["expectedQty"]), int(lines[0]["actualQty"]), int(lines[0]["varianceQty"])) == (4, 3, -1)
    assert int(lines[0]["netStockEffectQty"]) == -7
    reconcile = _movements(world, inv.EVENT_RETURN_RECONCILE)
    assert len(reconcile) == 1
    assert int(reconcile[0]["kernelPhysicalDelta"]) == -1
    assert reconcile[0]["reason"] == "one box was damaged"
    assert answer["finalization"]["wholePoolCents"] == 3000
    assert sum(row["amountCents"] for row in answer["scoutAllocations"]) == 3000
    assert _movements(world, inv.EVENT_IMMEDIATE_SALE)[0]["saleId"]


def test_an_actual_above_expected_return_raises_stock_without_touching_credit(world: Dict[str, Any]) -> None:
    """An overage raises physical stock by the variance and still freezes the old pool."""
    _ended(world, boxes=4)
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=60, profile_id=A_SCOUT)
    _sell(world, boxes=1, key="one-sold")
    _ok(_finalize(world, returns=[_return(actual=4, reason="found a box in the car")], cash=_cash(500)))
    assert int(_balance(world)["kernelPhysicalQty"]) == 4  # 3 after the sale, +1 overage
    assert int(_movements(world, inv.EVENT_RETURN_RECONCILE)[0]["kernelPhysicalDelta"]) == 1
    assert sum(int(row["approvedAmountCents"]) for row in world["unit_campaigns"].scan()["Items"] if row.get("entityType") == fm.TOTAL_ENTITY_TYPE) == 500


def test_cash_adjustment_and_discrepancy_are_explained_exactly(world: Dict[str, Any]) -> None:
    """CASH-03: 6000 calculated, +1000 manual, 6800 counted, -200 explained."""
    _ended(world, boxes=12)
    _two_shares(world)
    _sell(world, boxes=12, key="cash-sale")
    answer = _ok(
        _finalize(
            world,
            cash=_cash(
                6800,
                manualAdjustmentCents=1000,
                manualAdjustmentReason="split payment included cash",
                discrepancyExplanation="two dollars left in the change tin",
            ),
        )
    )
    cash = answer["finalization"]["cash"]
    assert (cash["calculatedExpectedCents"], cash["manualAdjustmentCents"]) == (6000, 1000)
    assert (cash["adjustedExpectedCents"], cash["actualCashCents"], cash["discrepancyCents"]) == (7000, 6800, -200)
    assert cash["discrepancyExplanation"] == "two dollars left in the change tin"


def test_cash_reasons_are_required_exactly_when_their_amounts_are_nonzero(world: Dict[str, Any]) -> None:
    """CASH-02/04: an unexplained adjustment or a negative discrepancy refuses the whole plan."""
    _ended(world, boxes=4)
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=60, profile_id=A_SCOUT)
    _sell(world, boxes=1, key="cash-reasons")
    assert_is_error(
        _finalize(world, cash=_cash(500, manualAdjustmentCents=100)),
        "CONFLICT",
    )
    assert_is_error(_finalize(world, cash=_cash(400)), "CONFLICT")
    assert _rows(world["show_and_sells"], fm.FINALIZATION_ENTITY_TYPE) == []


def test_a_cash_only_call_writes_no_sale_or_credit_side_effect(world: Dict[str, Any]) -> None:
    """A manual cash reconciliation changes the cash record and nothing else."""
    _ended(world, boxes=1)
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=60, profile_id=A_SCOUT)
    _sell(world, boxes=1, key="cash-only")
    before = len(_rows(world["show_and_sells"], sm.SALE_ENTITY_TYPE))
    answer = _ok(
        _finalize(
            world,
            cash=_cash(600, manualAdjustmentCents=100, manualAdjustmentReason="cash in the split"),
        )
    )
    assert answer["finalization"]["cash"]["adjustedExpectedCents"] == 600
    assert len(_rows(world["show_and_sells"], sm.SALE_ENTITY_TYPE)) == before
    assert [row["movementType"] for row in _movements(world)] == [inv.EVENT_IMMEDIATE_SALE]




# --- 5.2 guard rails not exercised by the happy paths above ----------------------


def test_malformed_answer_shapes_are_refused_before_any_read(world: Dict[str, Any]) -> None:
    """The three answer fields have one dialect; malformed values never reach a write."""
    _ended(world, boxes=1)
    assert_is_error(_finalize(world, returns="not-a-list"), "INVALID_INPUT")  # type: ignore[arg-type]
    assert_is_error(
        _finalize(world, returns=[_return(), _return()]), "INVALID_INPUT"
    )  # the same product twice
    assert_is_error(_finalize(world, cash={}), "INVALID_INPUT")
    assert_is_error(_finalize(world, rounding="not-a-list"), "INVALID_INPUT")  # type: ignore[arg-type]
    assert _rows(world["show_and_sells"], fm.FINALIZATION_ENTITY_TYPE) == []


def test_a_pool_without_confirmed_work_is_refused(world: Dict[str, Any]) -> None:
    """SPLIT-03: a $5 sale with no signed-up minutes has nobody to credit."""
    _ended(world, boxes=1)
    _sell(world, boxes=1, key="no-work")
    assert_is_error(_finalize(world, returns=[_return()], cash=_cash(500)), "INVALID_INPUT")
    assert _rows(world["show_and_sells"], fm.FINALIZATION_ENTITY_TYPE) == []


def test_an_unassigned_cent_must_be_routed_before_approval(world: Dict[str, Any]) -> None:
    """SPLIT-10: $5.01 split equally leaves one cent that must be assigned explicitly."""
    from decimal import Decimal

    from tests.unit.show_sell_fixtures import catalog_item
    from tests.unit.test_show_and_sell_sales import CATALOG_ID

    odd_product = f"{CATALOG_ID}#prod-odd"
    world["catalogs"].put_item(
        Item=catalog_item(
            CATALOG_ID,
            "Odd cent catalog",
            products=[
                {
                    "productId": odd_product,
                    "productName": "Odd cent box",
                    "price": Decimal("5.01"),
                    "sortOrder": 1,
                }
            ],
        )
    )
    _ended(world, boxes=1, product=odd_product)
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=60, profile_id=A_SCOUT)
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=60, profile_id=B_SCOUT)
    odd_version = int(_stored_event(world["show_and_sells"], ENDED_EVENT)[ssm.VERSION_ATTRIBUTE])
    _ok(
        _create(
            event_id=ENDED_EVENT,
            version=odd_version,
            sale_at=ENDED_SALE_AT,
            lines=[_line(odd_product, immediate=1)],
            key="odd-cent",
        )
    )
    error = assert_is_error(
        _finalize(world, returns=[_return(odd_product)], cash=_cash(501)), "INVALID_INPUT"
    )
    assert error["message"].startswith("every unassigned cent")
    assert _rows(world["show_and_sells"], fm.FINALIZATION_ENTITY_TYPE) == []


def test_products_without_an_open_allocation_need_no_return_answer(world: Dict[str, Any]) -> None:
    """A listed product that was never assigned is skipped by the return reconciliation."""
    from tests.unit.test_show_and_sell_sales import _seed_event as seed_event

    seed_event(
        world["show_and_sells"],
        ENDED_EVENT,
        start_at=ENDED_START,
        end_at=ENDED_END,
        product_ids=[PRODUCT, OTHER_PRODUCT],
        version=1,
    )
    _seed_balance(world["inventory"], PRODUCT, physical=2)
    _seed_allocation(world["inventory"], ENDED_EVENT, PRODUCT, allocated=2)
    answer = _ok(_finalize(world, returns=[_return(actual=2)], cash=_cash()))
    assert [line["productId"] for line in _rows(world["show_and_sells"], fm.RETURN_LINE_ENTITY_TYPE)] == [PRODUCT]
    assert len(answer["inventoryPositions"]) == 2


def test_earlier_overlap_reserves_stock_and_leaves_a_later_allocation_untouched(world: Dict[str, Any]) -> None:
    """An earlier overlapping event's open remainder is removed before later events are served."""
    from datetime import datetime, timedelta

    from tests.unit.test_show_and_sell_sales import FUTURE_END, FUTURE_START

    current_start = (datetime.fromisoformat(ENDED_START) + timedelta(hours=1)).isoformat()
    _ended(world, boxes=5, allocated=2, start_at=current_start)
    _seed_event(
        world["show_and_sells"],
        "SSE#overlap",
        start_at=ENDED_START,
        end_at=current_start,
        product_ids=[PRODUCT],
        version=1,
    )
    _seed_allocation(
        world["inventory"], "SSE#overlap", PRODUCT, allocated=2, start_at=ENDED_START, end_at=current_start
    )
    _seed_event(
        world["show_and_sells"],
        LATER_EVENT,
        start_at=FUTURE_START,
        end_at=FUTURE_END,
        product_ids=[PRODUCT],
        version=1,
    )
    _seed_allocation(world["inventory"], LATER_EVENT, PRODUCT, allocated=3, start_at=FUTURE_START, end_at=FUTURE_END)
    answer = _ok(_finalize(world, returns=[_return(actual=2)], cash=_cash()))
    assert int(_allocation(world, LATER_EVENT)["allocatedQty"]) == 3
    assert _movements(world, inv.EVENT_AUTO_REDUCE) == []
    assert answer["warnings"] == []


def test_a_cancelled_later_event_does_not_compete_for_stock(world: Dict[str, Any]) -> None:
    """A cancelled later event's open allocation is not reduced by an earlier finalization."""
    from tests.unit.test_show_and_sell_sales import FUTURE_END, FUTURE_START

    _ended(world, boxes=4, allocated=2)
    _seed_event(
        world["show_and_sells"],
        LATER_EVENT,
        start_at=FUTURE_START,
        end_at=FUTURE_END,
        product_ids=[PRODUCT],
        version=1,
    )
    _seed_allocation(world["inventory"], LATER_EVENT, PRODUCT, allocated=3, start_at=FUTURE_START, end_at=FUTURE_END)
    world["show_and_sells"].update_item(
        Key=ssm.event_metadata_key(LATER_EVENT),
        UpdateExpression="SET #status = :status, #reason = :reason",
        ExpressionAttributeNames={"#status": "status", "#reason": "cancellationReason"},
        ExpressionAttributeValues={":status": ssm.STATUS_CANCELLED, ":reason": "rain"},
    )
    _ok(_finalize(world, returns=[_return(actual=2)], cash=_cash()))
    assert int(_allocation(world, LATER_EVENT)["allocatedQty"]) == 3
    assert _movements(world, inv.EVENT_AUTO_REDUCE) == []


def test_an_existing_scoped_total_is_updated_in_the_same_transaction(world: Dict[str, Any]) -> None:
    """The second approval in a Unit Campaign adds to that scope's running total, not a new row."""
    from tests.unit.test_show_and_sell_sales import CAMPAIGN

    _ended(world, boxes=2)
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=60, profile_id=A_SCOUT)
    world["unit_campaigns"].put_item(
        Item=fm.build_total_row(
            campaign_id="SC#sale-budget",
            profile_id=A_SCOUT,
            unit_campaign_id=CAMPAIGN,
            approved_amount_cents=125,
            version=7,
            updated_at="2026-01-01T00:00:00+00:00",
        )
    )
    _sell(world, boxes=2, key="total-sale")
    _ok(_finalize(world, returns=[_return()], cash=_cash(1000)))
    totals = _rows(world["unit_campaigns"], fm.TOTAL_ENTITY_TYPE)
    assert len(totals) == 1
    assert (int(totals[0][fm.APPROVED_AMOUNT_CENTS_ATTRIBUTE]), int(totals[0]["version"])) == (1125, 8)


def test_an_allocation_without_a_balance_row_is_not_invented(world: Dict[str, Any]) -> None:
    """A recorded allocation with no balance row is finalized without fabricating stock."""
    from tests.unit.test_show_and_sell_sales import _seed_event as seed_event

    seed_event(
        world["show_and_sells"],
        ENDED_EVENT,
        start_at=ENDED_START,
        end_at=ENDED_END,
        product_ids=[PRODUCT],
        version=1,
    )
    _seed_allocation(world["inventory"], ENDED_EVENT, PRODUCT, allocated=2)
    _ok(_finalize(world, returns=[_return(actual=2)], cash=_cash()))
    assert _rows(world["inventory"], inv.BALANCE_ENTITY_TYPE) == []
    assert _movements(world) == []


def test_a_prior_events_reduction_movement_is_not_reported_again(world: Dict[str, Any]) -> None:
    """The answer filters movements by finalizationId, not by the whole campaign."""
    from tests.unit.test_show_and_sell_sales import FUTURE_END, FUTURE_START

    _ended(world, boxes=4, allocated=3)
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=60, profile_id=A_SCOUT)
    _sell(world, boxes=2, key="prior-move")
    _seed_event(
        world["show_and_sells"],
        LATER_EVENT,
        start_at=FUTURE_START,
        end_at=FUTURE_END,
        product_ids=[PRODUCT],
        version=1,
    )
    _seed_allocation(world["inventory"], LATER_EVENT, PRODUCT, allocated=3, start_at=FUTURE_START, end_at=FUTURE_END)
    old = inv.build_inventory_movement_item(
        movement_id=inv.new_inventory_movement_id(),
        unit_campaign_id=CAMPAIGN,
        product_id=PRODUCT,
        movement_type=inv.EVENT_AUTO_REDUCE,
        actor_account_id="Avery",
        occurred_at=ENDED_SALE_AT,
        idempotency_key="old-reduction",
        assigned_delta=-1,
        show_and_sell_id=LATER_EVENT,
        finalization_id="old-finalization",
    )
    world["inventory"].put_item(Item=old)
    answer = _ok(_finalize(world, returns=[_return(actual=1)], cash=_cash(1000)))
    assert [row["code"] for row in answer["warnings"]] == ["AUTOMATIC_ALLOCATION_REDUCTION"]
    assert int(_allocation(world, LATER_EVENT)["allocatedQty"]) == 2
