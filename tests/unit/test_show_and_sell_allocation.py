"""Wave 4.2 — event stock assignment and the raw allocation read (§3.2.3, §3.2.4).

Resolver-level cases for `EVT-M-04`, `SS-API-01`, `DATA-Q-03`, `AUTH-U`, `PAGE-01`,
`VER-01` and `IDEM`. Everything runs through ``handle_unit_operation`` against moto, so
what is proved is the transaction, not the plan: the allocation row, its movement, the
balance version, the event's cumulative ``productIds`` and the idempotency marker either
commit together or not at all, and the denial the browser sees is the one the resolver
actually raised. The pure half — the planner's arithmetic and the interval rule — is
``tests/unit/test_show_and_sell_allocation_planner.py``.

The scenario fixtures are ALLOC-04's own: four boxes of caramel, two events that overlap,
and a morning/afternoon pair that does not. Event instants are measured from the real
clock, because the resolvers derive ``SCHEDULED``/``ACTIVE``/``ENDED`` from
``utc_now_iso()`` and a literal "future" goes stale the day the calendar crosses it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

import pytest

from src.handlers.unit_operations import (
    ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD,
    EVENT_INVENTORY_ALLOCATIONS_FIELD,
    INVENTORY_POSITIONS_FIELD,
    handle_unit_operation,
)
from src.utils import allocation_models as am
from src.utils import inventory_models as inv
from src.utils import show_and_sell_models as ssm
from src.utils.mutations import MAX_TRANSACTION_ACTIONS
from tests.unit.show_sell_fixtures import (
    CREW_529_SPRING,
    PACK_3149,
    PACK_3149_FALL,
    assert_is_error,
    catalog_item,
    seed_show_sell_fixtures,
    unit_operation_event,
)

CAMPAIGN = PACK_3149_FALL
OTHER_UNIT_CAMPAIGN = CREW_529_SPRING
CATALOG_ID = "CATALOG#fixture-default"
PRODUCT = f"{CATALOG_ID}#prod-1"
OTHER_PRODUCT = f"{CATALOG_ID}#prod-2"
#: A second product whose id continues this one. Product ids carry ``#`` inside them
#: (§6.3), so ``PRODUCT#<extra>`` sits INSIDE the ``PRODUCT#`` sort-key range that a
#: per-product read asks for, and only the row's own ``productId`` attribute tells the two
#: products apart.
NESTED_PRODUCT = f"{PRODUCT}#nested"
MORNING = "SSE#morning"
AFTERNOON = "SSE#afternoon"
LOCATION = "Aurora armory lot"


def _shift(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


#: Both events are still ahead of the clock, so §3.5 allows an assignment, and they
#: overlap by two hours — the four-box case (ALLOC-04).
MORNING_START, MORNING_END = _shift(72), _shift(76)
OVERLAP_START, OVERLAP_END = _shift(74), _shift(78)
#: Adjacent, never overlapping: the end instant is the other's start (§5.11 half-open).
ADJACENT_START, ADJACENT_END = MORNING_END, _shift(80)


def _product(index: int) -> str:
    return f"{CATALOG_ID}#prod-{index}"


# --- Handler turns ---------------------------------------------------------------


def _call(
    field: str,
    caller: Optional[str],
    *,
    mutation: Optional[Dict[str, Any]] = None,
    arguments: Optional[Dict[str, Any]] = None,
) -> Any:
    return handle_unit_operation(unit_operation_event(field, caller, input=mutation, arguments=arguments), None)


def _ok(payload: Any) -> Dict[str, Any]:
    failed = isinstance(payload, dict) and payload.get("__isError")
    assert not failed, f"expected a success payload, got {payload!r}"
    return payload


def _idem(key: Optional[str]) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": key}}


def _version(expected: int) -> Dict[str, Any]:
    return {"version": {"expectedVersion": expected}}


def _target(quantity: int, product_id: str = PRODUCT) -> Dict[str, Any]:
    return {"productId": product_id, "quantity": quantity}


def _assign(
    caller: Optional[str] = "Avery",
    *,
    event_id: str = MORNING,
    items: Sequence[Dict[str, Any]],
    version: int = 1,
    key: str = "assign-1",
    **input_extras: Any,
) -> Any:
    payload: Dict[str, Any] = {
        "showAndSellId": event_id,
        "items": list(items),
        **_version(version),
        **_idem(key),
    }
    payload.update(input_extras)
    return _call(ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD, caller, mutation=payload)


def _read_allocations(
    caller: Optional[str] = "Avery",
    *,
    campaign: str = CAMPAIGN,
    page: Optional[Dict[str, Any]] = None,
    **filters: Any,
) -> Any:
    arguments: Dict[str, Any] = {"unitCampaignId": campaign}
    arguments.update({name: value for name, value in filters.items() if value is not None})
    if page is not None:
        arguments["page"] = page
    return _call(EVENT_INVENTORY_ALLOCATIONS_FIELD, caller, arguments=arguments)


# --- Seeded rows -----------------------------------------------------------------


def _offer_products(catalogs_table: Any, count: int) -> List[str]:
    """Give the campaign's catalog ``count`` products, replacing the seeded one."""
    product_ids = [_product(index) for index in range(1, count + 1)]
    catalogs_table.put_item(
        Item=catalog_item(
            CATALOG_ID,
            "Pack 3149 catalog",
            products=[
                {
                    "productId": product_id,
                    "productName": f"Caramel {index}",
                    "price": Decimal("5.00"),
                    "sortOrder": index,
                }
                for index, product_id in enumerate(product_ids, start=1)
            ],
        )
    )
    return product_ids


def _seed_event(
    show_and_sells_table: Any,
    event_id: str,
    *,
    start_at: str = MORNING_START,
    end_at: str = MORNING_END,
    status: str = ssm.STATUS_SCHEDULED,
    version: int = 1,
    product_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> str:
    item = ssm.build_show_and_sell_item(
        show_and_sell_id=event_id,
        unit_id=PACK_3149,
        unit_campaign_id=CAMPAIGN,
        location_name=LOCATION,
        start_at=start_at,
        end_at=end_at,
        created_by_account_id="ACCOUNT#avery-fixture",
        now_iso=start_at,
        product_ids=product_ids or [],
        version=version,
    )
    item[ssm.STATUS_ATTRIBUTE] = status
    if status == ssm.STATUS_FINALIZED:
        item[ssm.APPROVED_FINALIZATION_ID_ATTRIBUTE] = f"FIN#{event_id}"
    item.update(overrides)
    show_and_sells_table.put_item(Item=item)
    return event_id


def _seed_balance(
    inventory_table: Any,
    product_id: str = PRODUCT,
    *,
    physical: int = 4,
    sold: int = 0,
    council: int = 0,
    version: int = 1,
) -> Dict[str, Any]:
    item = inv.build_inventory_balance_item(
        unit_campaign_id=CAMPAIGN,
        product_id=product_id,
        kernel_physical_qty=physical,
        sold_in_possession_qty=sold,
        council_on_order_qty=council,
        now_iso=MORNING_START,
        version=version,
    )
    inventory_table.put_item(Item=item)
    return item


def _seed_allocation(
    inventory_table: Any,
    event_id: str,
    product_id: str = PRODUCT,
    *,
    allocated: int,
    sold: int = 0,
    released: int = 0,
    status: str = inv.ALLOCATION_OPEN,
    version: int = 1,
    start_at: str = MORNING_START,
    end_at: str = MORNING_END,
) -> Dict[str, Any]:
    item = inv.build_event_inventory_allocation_item(
        unit_campaign_id=CAMPAIGN,
        product_id=product_id,
        show_and_sell_id=event_id,
        start_at=start_at,
        end_at=end_at,
        allocated_qty=allocated,
        sold_qty=sold,
        released_qty=released,
        status=status,
        now_iso=MORNING_START,
        version=version,
    )
    inventory_table.put_item(Item=item)
    return item


# --- Storage reads ---------------------------------------------------------------


def _inventory_rows(inventory_table: Any) -> List[Dict[str, Any]]:
    return list(inventory_table.scan()["Items"])


def _movements(inventory_table: Any) -> List[Dict[str, Any]]:
    return [row for row in _inventory_rows(inventory_table) if row.get("entityType") == inv.MOVEMENT_ENTITY_TYPE]


def _allocations(inventory_table: Any) -> List[Dict[str, Any]]:
    return [row for row in _inventory_rows(inventory_table) if row.get("entityType") == inv.ALLOCATION_ENTITY_TYPE]


def _stored_allocation(inventory_table: Any, event_id: str, product_id: str = PRODUCT) -> Optional[Dict[str, Any]]:
    response = inventory_table.get_item(Key=ssm.event_allocation_key(CAMPAIGN, product_id, event_id))
    item = response.get("Item")
    return dict(item) if isinstance(item, dict) else None


def _stored_balance(inventory_table: Any, product_id: str = PRODUCT) -> Dict[str, Any]:
    return dict(inventory_table.get_item(Key=inv.balance_key(CAMPAIGN, product_id))["Item"])


def _stored_event(show_and_sells_table: Any, event_id: str = MORNING) -> Dict[str, Any]:
    return dict(show_and_sells_table.get_item(Key=ssm.event_metadata_key(event_id))["Item"])


def _marker_rows(show_and_sells_table: Any) -> List[Dict[str, Any]]:
    return [row for row in show_and_sells_table.scan()["Items"] if str(row.get("sk", "")).startswith("IDEM#")]


def _two_events(world: Dict[str, Any], *, second_start: str = OVERLAP_START, second_end: str = OVERLAP_END) -> None:
    """The four-box fixture: two events, four boxes of caramel, nothing assigned yet."""
    _seed_event(world["show_and_sells"], MORNING)
    _seed_event(world["show_and_sells"], AFTERNOON, start_at=second_start, end_at=second_end)
    _seed_balance(world["inventory"], PRODUCT, physical=4)


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
    """The Stage 1 persona world plus the two tables this mutation writes."""
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    return {
        "show_and_sells": show_and_sells_table,
        "inventory": inventory_table,
        "catalogs": catalogs_table,
    }


# --- EVT-M-04-01: sequential warnings and concurrent refusal ---------------------


def test_evt_m_04_01_assigning_to_a_first_event_writes_the_allocation_and_its_trail(
    world: Dict[str, Any],
) -> None:
    """The happy path is still the audit path: one row, one movement, one version each."""
    _two_events(world)

    answer = _ok(_assign(items=[_target(3)]))

    assert answer["warnings"] == [], "3 of 4 sellable is inside the stock"
    stored = _stored_allocation(world["inventory"], MORNING)
    assert stored is not None
    assert (stored[inv.ALLOCATED_QTY], stored[inv.REMAINING_QTY], stored[inv.SOLD_QTY]) == (3, 3, 0)
    assert stored[ssm.STATUS_ATTRIBUTE] == inv.ALLOCATION_OPEN
    assert stored[ssm.START_AT_ATTRIBUTE] == ssm.normalize_moment(MORNING_START, "startAt")

    balance = _stored_balance(world["inventory"])
    assert balance[inv.KERNEL_PHYSICAL_QTY] == 4, "ALLOC-01: an assignment never touches physical stock"
    assert balance[inv.VERSION_ATTRIBUTE] == 2, "the position's version moved, because assignedOpenQty did"

    movements = _movements(world["inventory"])
    assert len(movements) == 1
    assert movements[0][inv.MOVEMENT_TYPE_ATTRIBUTE] == inv.EVENT_ASSIGN
    assert movements[0][inv.ASSIGNED_DELTA] == 3
    assert movements[0][inv.SHOW_AND_SELL_ID_ATTRIBUTE] == MORNING
    assert movements[0][inv.INVENTORY_VERSION_ATTRIBUTE] == 2

    assert answer["allocations"] == [ssm.allocation_payload(stored)]
    position = answer["inventoryPositions"][0]
    assert (position["assignedOpenQty"], position["sellableKernelQty"], position["unassignedKernelQty"]) == (3, 4, 1)
    assert _stored_event(world["show_and_sells"])[ssm.PRODUCT_IDS_ATTRIBUTE] == [PRODUCT]
    assert len(_marker_rows(world["show_and_sells"])) == 1


def test_evt_m_04_01_a_non_overlapping_second_event_saves_with_the_overage_warning(
    world: Dict[str, Any],
) -> None:
    """ALLOC-03, ALLOC-04, AC-10: three in the morning and three in the afternoon is allowed, and said."""
    _seed_event(world["show_and_sells"], MORNING)
    _seed_event(world["show_and_sells"], AFTERNOON, start_at=ADJACENT_START, end_at=ADJACENT_END)
    _seed_balance(world["inventory"], PRODUCT, physical=4)
    _ok(_assign(event_id=MORNING, items=[_target(3)], key="assign-morning"))

    answer = _ok(_assign(event_id=AFTERNOON, items=[_target(3)], version=1, key="assign-afternoon"))

    assert len(answer["warnings"]) == 1
    warning = answer["warnings"][0]
    assert warning["code"] == am.SEQUENTIAL_OVER_ASSIGNMENT
    assert warning["productId"] == PRODUCT
    assert (warning["currentStockQty"], warning["assignedQty"], warning["overageQty"]) == (4, 6, 2)
    for fact in (PRODUCT, "4", "6", "2"):
        assert fact in warning["message"], "the tooltip states the numbers, not only a sentence"

    assert _stored_balance(world["inventory"])[inv.KERNEL_PHYSICAL_QTY] == 4
    assert sum(row[inv.REMAINING_QTY] for row in _allocations(world["inventory"])) == 6


def test_evt_m_04_01_two_overlapping_events_cannot_each_hold_three_of_four_boxes(
    world: Dict[str, Any],
) -> None:
    """ALLOC-02, ALLOC-04, AC-09: the four-box block, and the block writes nothing at all."""
    _two_events(world)
    _ok(_assign(event_id=MORNING, items=[_target(3)], key="assign-morning"))

    refused = _assign(event_id=AFTERNOON, items=[_target(3)], key="assign-afternoon")

    error = assert_is_error(refused, "CONFLICT")
    for fact in (PRODUCT, "4", "6", "2"):
        assert fact in error["message"], f"the refusal states the numbers: {error['message']}"
    assert _stored_allocation(world["inventory"], AFTERNOON) is None
    assert len(_allocations(world["inventory"])) == 1
    assert len(_movements(world["inventory"])) == 1, "no audit row for a request that was refused"
    refused_markers = [row for row in _marker_rows(world["show_and_sells"]) if "afternoon" in str(row["pk"])]
    assert refused_markers == [], "the marker rides the transaction, so the refusal leaves none"
    assert _stored_event(world["show_and_sells"], AFTERNOON)[ssm.VERSION_ATTRIBUTE] == 1
    balance = _stored_balance(world["inventory"])
    assert (balance[inv.KERNEL_PHYSICAL_QTY], balance[inv.VERSION_ATTRIBUTE]) == (4, 2)


def test_evt_m_04_01_the_refusal_grows_when_the_stock_is_smaller_than_the_first_assignment(
    world: Dict[str, Any],
) -> None:
    """A campaign holding less than one event already promised cannot be promised more."""
    _two_events(world)
    inventory_table = world["inventory"]
    inventory_table.delete_item(Key=inv.balance_key(CAMPAIGN, PRODUCT))
    _seed_balance(inventory_table, PRODUCT, physical=2)

    _ok(_assign(event_id=MORNING, items=[_target(2)], key="assign-morning"))
    refused = _assign(event_id=AFTERNOON, items=[_target(1)], key="assign-afternoon")

    assert_is_error(refused, "CONFLICT")
    assert _stored_allocation(inventory_table, AFTERNOON) is None


def test_evt_m_04_01_an_over_assigned_instant_does_not_license_one_at_another(
    world: Dict[str, Any],
) -> None:
    """ALLOC-02 is an every-instant rule, so a fresh violation is refused where it lands.

    The morning is committed to one Kernel of a product the campaign does not hold — a
    state the Kernel has to be able to correct, and the campaign's worst instant. The
    afternoon instant this request opens carries nothing today, so the campaign's peak does
    not move at all and a campaign-wide ceiling would let the write land. It is refused at
    the afternoon instant, and reducing the morning stays possible afterwards.
    """
    inventory_table = world["inventory"]
    _seed_event(world["show_and_sells"], MORNING)
    _seed_event(world["show_and_sells"], AFTERNOON, start_at=ADJACENT_START, end_at=ADJACENT_END)
    _seed_allocation(inventory_table, MORNING, PRODUCT, allocated=1)

    refused = _assign(event_id=AFTERNOON, items=[_target(1)], key="assign-afternoon")

    error = assert_is_error(refused, "CONFLICT")
    for fact in (PRODUCT, "0", "1"):
        assert fact in error["message"], f"the refusal states the numbers: {error['message']}"
    assert _stored_allocation(inventory_table, AFTERNOON) is None
    assert _movements(inventory_table) == []

    _ok(_assign(event_id=MORNING, items=[_target(0)], key="release-morning"))
    morning = _stored_allocation(inventory_table, MORNING)
    assert morning is not None and morning[inv.REMAINING_QTY] == 0, "the remedy was never blocked"


def test_evt_m_04_01_a_released_allocation_frees_the_instant_for_another_event(
    world: Dict[str, Any],
) -> None:
    """Reducing the morning to nothing makes the afternoon's three legal again (§3.2.3 remedy)."""
    _two_events(world)
    _ok(_assign(event_id=MORNING, items=[_target(3)], key="assign-morning"))
    assert_is_error(_assign(event_id=AFTERNOON, items=[_target(3)], key="no"), "CONFLICT")

    _ok(_assign(event_id=MORNING, items=[_target(0)], version=2, key="release-morning"))
    answer = _ok(_assign(event_id=AFTERNOON, items=[_target(3)], key="assign-afternoon"))

    assert answer["warnings"] == []
    morning = _stored_allocation(world["inventory"], MORNING)
    assert morning is not None and morning[inv.REMAINING_QTY] == 0
    assert morning[ssm.STATUS_ATTRIBUTE] == inv.ALLOCATION_OPEN, "a manual reduce is not a §9.2 RELEASED row"


# --- EVT-M-04-02: target zero, omitted products, manual adjustment ----------------


def test_evt_m_04_02_a_target_of_zero_releases_only_that_product_s_remainder(
    world: Dict[str, Any],
) -> None:
    _seed_event(world["show_and_sells"], MORNING, product_ids=[PRODUCT, OTHER_PRODUCT])
    _seed_balance(world["inventory"], PRODUCT, physical=4)
    _seed_balance(world["inventory"], OTHER_PRODUCT, physical=4)
    _seed_allocation(world["inventory"], MORNING, PRODUCT, allocated=4)
    _seed_allocation(world["inventory"], MORNING, OTHER_PRODUCT, allocated=3)

    answer = _ok(_assign(items=[_target(0)], version=1))

    released = _stored_allocation(world["inventory"], MORNING, PRODUCT)
    assert released is not None
    assert (released[inv.ALLOCATED_QTY], released[inv.REMAINING_QTY], released[inv.RELEASED_QTY]) == (0, 0, 0)
    untouched = _stored_allocation(world["inventory"], MORNING, OTHER_PRODUCT)
    assert untouched is not None and untouched[inv.ALLOCATED_QTY] == 3
    assert untouched[ssm.VERSION_ATTRIBUTE] == 1, "the other product's row is not even rewritten"
    assert _stored_balance(world["inventory"], OTHER_PRODUCT)[inv.VERSION_ATTRIBUTE] == 1

    movement = _movements(world["inventory"])[0]
    assert movement[inv.MOVEMENT_TYPE_ATTRIBUTE] == inv.EVENT_MANUAL_REDUCE
    assert movement[inv.ASSIGNED_DELTA] == -4
    assert _stored_event(world["show_and_sells"])[ssm.PRODUCT_IDS_ATTRIBUTE] == [PRODUCT, OTHER_PRODUCT], (
        "§6.3: a released product stays listed, or finalization loses the row"
    )
    assert answer["allocations"][0]["remainingQty"] == 0
    assert answer["warnings"] == []


def test_evt_m_04_02_an_omitted_product_keeps_its_allocation_and_its_version(
    world: Dict[str, Any],
) -> None:
    """§3.2.1: the batch is a set of targets, and a product outside it is not a zero."""
    _seed_event(world["show_and_sells"], MORNING, product_ids=[PRODUCT, OTHER_PRODUCT])
    _seed_balance(world["inventory"], PRODUCT, physical=6)
    _seed_balance(world["inventory"], OTHER_PRODUCT, physical=6)
    _seed_allocation(world["inventory"], MORNING, OTHER_PRODUCT, allocated=5)

    _ok(_assign(items=[_target(2)]))

    kept = _stored_allocation(world["inventory"], MORNING, OTHER_PRODUCT)
    assert kept is not None and (kept[inv.ALLOCATED_QTY], kept[ssm.VERSION_ATTRIBUTE]) == (5, 1)
    assert _stored_balance(world["inventory"], OTHER_PRODUCT)[inv.VERSION_ATTRIBUTE] == 1


def test_evt_m_04_02_a_reduced_allocation_can_be_assigned_again(world: Dict[str, Any]) -> None:
    """ALLOC-05/06's "a Kernel may manually adjust the results" needs the row to stay open."""
    _two_events(world)

    _ok(_assign(items=[_target(4)], key="one"))
    _ok(_assign(items=[_target(0)], version=2, key="two"))
    _ok(_assign(items=[_target(2)], version=3, key="three"))

    stored = _stored_allocation(world["inventory"], MORNING)
    assert stored is not None
    assert (stored[inv.ALLOCATED_QTY], stored[inv.REMAINING_QTY], stored[ssm.VERSION_ATTRIBUTE]) == (2, 2, 3)
    assert [row[inv.MOVEMENT_TYPE_ATTRIBUTE] for row in _movements(world["inventory"])] == [
        inv.EVENT_ASSIGN,
        inv.EVENT_MANUAL_REDUCE,
        inv.EVENT_ASSIGN,
    ]


def test_restating_a_target_saves_without_another_allocation_write_or_movement(world: Dict[str, Any]) -> None:
    """§3.2.1: a target the row already carries is not a change, so it writes no row fact.

    The save still commits — its marker is what makes the retry safe, and the event version
    is that save's receipt — but the allocation row keeps its quantity, its version, and its
    single movement pair. Otherwise every re-opened editor session that pressed Save twice
    would leave an audit trail of movements that moved nothing.
    """
    _two_events(world)
    _ok(_assign(items=[_target(3)], key="one"))

    answer = _ok(_assign(items=[_target(3)], version=2, key="two"))

    stored = _stored_allocation(world["inventory"], MORNING)
    assert stored is not None
    assert (stored[inv.ALLOCATED_QTY], stored[inv.REMAINING_QTY]) == (3, 3)
    assert stored[ssm.VERSION_ATTRIBUTE] == 1, "the row was not written, so its version did not move"
    assert len(_movements(world["inventory"])) == 1, "no movement for a target that moved nothing"
    assert _stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 3, "both saves are receipts"
    assert answer["allocations"][0]["version"] == 1


def test_a_target_below_what_the_event_sold_is_refused_without_touching_the_row(
    world: Dict[str, Any],
) -> None:
    """§3.2.1 sold-stock protection: a sale at the event is history the target cannot undo.

    A non-zero target below ``soldQty + releasedQty`` is refused outright. Zero is the one
    target that is allowed past that floor, because it is not a quantity under the history
    but the command that releases the remainder — see the zero cases below.
    """
    _seed_event(world["show_and_sells"], MORNING, product_ids=[PRODUCT])
    _seed_balance(world["inventory"], PRODUCT, physical=6, sold=4)
    _seed_allocation(world["inventory"], MORNING, PRODUCT, allocated=6, sold=4)

    refused = _assign(items=[_target(3)])

    error = assert_is_error(refused, "INVALID_INPUT")
    assert "sold" in error["message"]
    stored = _stored_allocation(world["inventory"], MORNING)
    assert stored is not None and stored[inv.ALLOCATED_QTY] == 6
    assert _stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 1


def test_a_target_of_zero_after_a_sale_releases_the_remainder_and_keeps_the_sale(
    world: Dict[str, Any],
) -> None:
    """§3.1, §6.2: zero removes the remaining allocation, and a sale is not in the way.

    6 allocated, 4 sold at the event: the 4 sold are history the target cannot undo, and
    the 2 still assigned are exactly what a zero releases. The row keeps its sold quantity
    and lands on the floor with nothing remaining, so the sale, the position and the audit
    trail go on agreeing about the same two Kernels.
    """
    _seed_event(world["show_and_sells"], MORNING, product_ids=[PRODUCT])
    _seed_balance(world["inventory"], PRODUCT, physical=6, sold=4)
    _seed_allocation(world["inventory"], MORNING, PRODUCT, allocated=6, sold=4)

    answer = _ok(_assign(items=[_target(0)]))

    stored = _stored_allocation(world["inventory"], MORNING)
    assert stored is not None
    assert (stored[inv.ALLOCATED_QTY], stored[inv.SOLD_QTY], stored[inv.RELEASED_QTY]) == (4, 4, 0)
    assert stored[inv.REMAINING_QTY] == 0
    assert stored[ssm.STATUS_ATTRIBUTE] == inv.ALLOCATION_OPEN, "zero is a reduction, not the §9.2 RELEASED state"
    movement = _movements(world["inventory"])[0]
    assert movement[inv.MOVEMENT_TYPE_ATTRIBUTE] == inv.EVENT_MANUAL_REDUCE
    assert movement[inv.ASSIGNED_DELTA] == -2, "only the remainder moved"
    position = answer["inventoryPositions"][0]
    assert (position["assignedOpenQty"], position["sellableKernelQty"], position["unassignedKernelQty"]) == (0, 2, 2)
    assert answer["warnings"] == []


def test_a_target_of_zero_after_a_release_releases_only_what_is_still_assigned(
    world: Dict[str, Any],
) -> None:
    """A row that already put part of its remainder back is still zero-able, once."""
    _seed_event(world["show_and_sells"], MORNING, product_ids=[PRODUCT])
    _seed_balance(world["inventory"], PRODUCT, physical=6)
    _seed_allocation(world["inventory"], MORNING, PRODUCT, allocated=6, sold=2, released=3)

    _ok(_assign(items=[_target(0)]))

    stored = _stored_allocation(world["inventory"], MORNING)
    assert stored is not None
    assert (stored[inv.ALLOCATED_QTY], stored[inv.SOLD_QTY], stored[inv.RELEASED_QTY]) == (5, 2, 3)
    assert stored[inv.REMAINING_QTY] == 0
    assert [am.assigned_delta_of(row) for row in _movements(world["inventory"])] == [-1]


def test_assigning_a_product_never_touches_the_product_whose_id_shares_its_key_range(
    world: Dict[str, Any],
) -> None:
    """§6.3: a product id contains ``#``, so a per-product key range is two products wide.

    ``PRODUCT#nested`` lives inside the ``PRODUCT#`` range this mutation reads before it
    plans a write, and only the rows' own ``productId`` attribute separates the two
    products. Read as if the range were an identity, the neighbour's allocation for the
    same event is planned as though it were the requested product's: the write moves the
    neighbour's row while bumping the requested product's balance and auditing the
    requested product, and the allocation, the position and the audit trail then disagree
    about which product ever changed.
    """
    inventory_table = world["inventory"]
    _seed_event(world["show_and_sells"], MORNING, product_ids=[NESTED_PRODUCT])
    _seed_balance(inventory_table, PRODUCT, physical=6)
    _seed_balance(inventory_table, NESTED_PRODUCT, physical=6)
    _seed_allocation(inventory_table, MORNING, NESTED_PRODUCT, allocated=5)

    answer = _ok(_assign(items=[_target(2)]))

    mine = _stored_allocation(inventory_table, MORNING, PRODUCT)
    assert mine is not None, "the product that was asked for gets its own allocation row"
    assert (mine[inv.PRODUCT_ID_ATTRIBUTE], mine[inv.ALLOCATED_QTY], mine[inv.REMAINING_QTY]) == (PRODUCT, 2, 2)
    neighbour = _stored_allocation(inventory_table, MORNING, NESTED_PRODUCT)
    assert neighbour is not None
    assert (neighbour[inv.ALLOCATED_QTY], neighbour[ssm.VERSION_ATTRIBUTE]) == (5, 1), "the neighbour is not rewritten"
    assert _stored_balance(inventory_table, NESTED_PRODUCT)[inv.VERSION_ATTRIBUTE] == 1
    assert _stored_balance(inventory_table, PRODUCT)[inv.VERSION_ATTRIBUTE] == 2
    assert [row[inv.PRODUCT_ID_ATTRIBUTE] for row in _movements(inventory_table)] == [PRODUCT]
    assert sorted((row["productId"], row["allocatedQty"]) for row in answer["allocations"]) == [
        (PRODUCT, 2),
        (NESTED_PRODUCT, 5),
    ]
    positions = {row["productId"]: row for row in answer["inventoryPositions"]}
    assert positions[PRODUCT]["assignedOpenQty"] == 2, "a position counts its own product's allocations only"
    assert positions[NESTED_PRODUCT]["assignedOpenQty"] == 5


def test_a_released_allocation_is_not_re_opened_by_an_assignment(world: Dict[str, Any]) -> None:
    """§9.2: only a cancellation or a finalization closes a row, and a closed row is not re-used."""
    _seed_event(world["show_and_sells"], MORNING, product_ids=[PRODUCT])
    _seed_balance(world["inventory"], PRODUCT, physical=6)
    _seed_allocation(world["inventory"], MORNING, PRODUCT, allocated=6, released=6, status=inv.ALLOCATION_RELEASED)

    assert_is_error(_assign(items=[_target(2)]), "CONFLICT")
    assert _stored_allocation(world["inventory"], MORNING) is not None


# --- EVT-M-04-03: the computed write plan and the 16th product -------------------


def test_evt_m_04_03_a_sixteenth_product_is_allowed_and_the_plan_fits_the_budget(
    world: Dict[str, Any],
) -> None:
    """§5.10 no event-wide cap; §8.10 the cap is the computed action count."""
    products = _offer_products(world["catalogs"], 16)
    _seed_event(world["show_and_sells"], MORNING)
    for product_id in products:
        _seed_balance(world["inventory"], product_id, physical=2)

    answer = _ok(_assign(items=[_target(1, product_id) for product_id in products]))

    assert len(answer["allocations"]) == 16
    assert len(_allocations(world["inventory"])) == 16
    assert len(_movements(world["inventory"])) == 16
    stored = _stored_event(world["show_and_sells"])
    assert len(stored[ssm.PRODUCT_IDS_ATTRIBUTE]) == 16
    assert stored[ssm.VERSION_ATTRIBUTE] == 2

    # The complete plan this commit ran: marker + event row + (allocation, movement,
    # balance version) per product, well inside the 90-action budget.
    assert 2 + 3 * 16 <= MAX_TRANSACTION_ACTIONS
    # And the finalization this assignment makes possible still fits its own budget:
    # 3 baseline writes + 4 per touched product = 67 (§9).
    assert 3 + 4 * 16 == 67 <= MAX_TRANSACTION_ACTIONS


def test_21_allocated_products_are_the_most_the_event_can_still_finalize(world: Dict[str, Any]) -> None:
    """§8.10, §9: the floor reaches 87 writes at 21 products, which is still inside 90.

    The arithmetic is the documented estimate written out rather than a computation on the
    implementation's constants, so a changed constant moves a failing line instead of
    quietly moving the boundary a Kernel can put their event on.
    """
    products = _offer_products(world["catalogs"], 21)
    _seed_event(world["show_and_sells"], MORNING)
    for product_id in products:
        _seed_balance(world["inventory"], product_id, physical=2)

    answer = _ok(_assign(items=[_target(1, product_id) for product_id in products]))

    assert 3 + 4 * 21 == 87 <= MAX_TRANSACTION_ACTIONS
    assert len(answer["allocations"]) == 21
    assert len(_allocations(world["inventory"])) == 21
    assert len(_movements(world["inventory"])) == 21


def test_evt_m_04_03_a_batch_the_event_could_no_longer_finalize_is_refused_first(
    world: Dict[str, Any],
) -> None:
    """§8.10: 22 products would need 3 + 4*22 = 91 writes to finalize, one over the budget.

    The preflight runs before a single action is staged, so the refusal leaves no
    allocation, no movement, no marker and no moved version, and names what to reduce. The
    assignment's own plan is only 68 actions here: what the event can still finalize is the
    binding limit, not the size of this request.
    """
    products = _offer_products(world["catalogs"], 22)
    _seed_event(world["show_and_sells"], MORNING)
    for product_id in products:
        _seed_balance(world["inventory"], product_id, physical=2)

    refused = _assign(items=[_target(1, product_id) for product_id in products])

    assert 3 + 4 * 22 == 91 > MAX_TRANSACTION_ACTIONS
    error = assert_is_error(refused, "CONFLICT")
    assert "finalize" in error["message"]
    assert "91" in error["message"], "the refusal states the write count the event can no longer reach"
    assert _allocations(world["inventory"]) == []
    assert _movements(world["inventory"]) == []
    assert _marker_rows(world["show_and_sells"]) == []
    assert _stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 1
    for product_id in products:
        assert _stored_balance(world["inventory"], product_id)[inv.VERSION_ATTRIBUTE] == 1


def test_an_assignment_refuses_a_product_the_campaign_does_not_sell(world: Dict[str, Any]) -> None:
    """§2.2.1's catalog allowlist applies to an assignment as it does to a receipt."""
    _two_events(world)

    refused = _assign(items=[_target(1, f"{CATALOG_ID}#prod-40")])

    error = assert_is_error(refused, "INVALID_INPUT")
    assert "catalog" in error["message"]
    assert _allocations(world["inventory"]) == []


def test_a_product_the_campaign_has_never_received_still_follows_the_stock_rule(
    world: Dict[str, Any],
) -> None:
    """No balance row means nothing is sellable, so an assignment there is still ALLOC-02's question."""
    _seed_event(world["show_and_sells"], MORNING)

    assert_is_error(_assign(items=[_target(1)]), "CONFLICT")
    assert _allocations(world["inventory"]) == []
    assert _stored_balance_or_none(world["inventory"]) is None, "an assignment never materialises a balance row"


def test_a_reduction_for_a_product_with_no_balance_row_writes_no_balance_and_names_no_version(
    world: Dict[str, Any],
) -> None:
    """An allocation is a fact of its own: correcting one does not require a balance row.

    A campaign can hold an assignment for a product whose balance row is gone — a teardown
    that swept the receipt, a product the catalog dropped — and the assignment is still the
    thing the Kernel has to fix. The write then carries no balance update, and its movement
    names no ``inventoryVersion``, because no ``InventoryPosition`` moved.
    """
    _seed_event(world["show_and_sells"], MORNING, product_ids=[PRODUCT])
    _seed_balance(world["inventory"], PRODUCT, physical=6)
    _ok(_assign(items=[_target(6)], key="six"))

    world["inventory"].delete_item(Key=inv.balance_key(CAMPAIGN, PRODUCT))
    answer = _ok(_assign(items=[_target(2)], version=2, key="two"))

    stored = _stored_allocation(world["inventory"], MORNING)
    assert stored is not None
    assert (stored[inv.ALLOCATED_QTY], stored[inv.REMAINING_QTY]) == (2, 2)
    assert _stored_balance_or_none(world["inventory"]) is None, "the write never materialises a balance row"
    movements = _movements(world["inventory"])
    assert [row[inv.MOVEMENT_TYPE_ATTRIBUTE] for row in movements] == [inv.EVENT_ASSIGN, inv.EVENT_MANUAL_REDUCE]
    assert [inv.INVENTORY_VERSION_ATTRIBUTE in row for row in movements] == [True, False]
    assert [am.assigned_delta_of(row) for row in movements] == [6, -4]
    assert sum(am.assigned_delta_of(row) for row in movements) == 2 == stored[inv.REMAINING_QTY]
    assert answer["allocations"][0]["remainingQty"] == 2


def _stored_balance_or_none(inventory_table: Any, product_id: str = PRODUCT) -> Optional[Dict[str, Any]]:
    item = inventory_table.get_item(Key=inv.balance_key(CAMPAIGN, product_id)).get("Item")
    return dict(item) if isinstance(item, dict) else None


def _put_allocation_for(event_id: str) -> Any:
    """One allocation row as a conditional Put, for the race fixture."""
    start_at, end_at = (MORNING_START, MORNING_END) if event_id == MORNING else (OVERLAP_START, OVERLAP_END)
    return ssm.put_allocation_action(
        inv.build_event_inventory_allocation_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            show_and_sell_id=event_id,
            start_at=start_at,
            end_at=end_at,
            allocated_qty=3,
            now_iso=MORNING_START,
        )
    )


# --- SS-API-01: two assignments of one product, planned from one read ------------


def test_ss_api_01_two_assignments_planned_from_one_read_commit_one_at_a_time(
    world: Dict[str, Any],
) -> None:
    """ALLOC-08: two Kernels that both read the same snapshot cannot both over-assign.

    Both callers send the version they read before either wrote, which is what a real
    concurrent save looks like. The application-level overlap check cannot see across the
    two requests, so the pinned row version decides: exactly one allocation, one movement,
    and one version bump for the whole race.
    """
    _two_events(world)

    first = _ok(_assign(items=[_target(3)], version=1, key="morning-save"))
    second = _assign(items=[_target(4)], version=1, key="afternoon-save")

    assert first["warnings"] == []
    error = assert_is_error(second, "CONFLICT")
    assert "changed since you read it" in error["message"]

    rows = _allocations(world["inventory"])
    assert [(r[inv.SHOW_AND_SELL_ID_ATTRIBUTE], r[inv.ALLOCATED_QTY]) for r in rows] == [(MORNING, 3)]
    assert len(_movements(world["inventory"])) == 1
    assert _stored_balance(world["inventory"])[inv.VERSION_ATTRIBUTE] == 2
    assert _stored_balance(world["inventory"])[inv.KERNEL_PHYSICAL_QTY] == 4, "physical stock never moves"


# --- VER-01, IDEM, AUTH-U for the mutation --------------------------------------


def test_ver_01_a_stale_event_version_is_refused_rather_than_applied(world: Dict[str, Any]) -> None:
    """§3.5: the version the caller read is the version the write conditions on."""
    _two_events(world)

    _ok(_assign(items=[_target(2)], key="first"))
    refused = _assign(items=[_target(3)], version=1, key="second")

    error = assert_is_error(refused, "CONFLICT")
    assert "changed since you read it" in error["message"]
    assert _stored_allocation(world["inventory"], MORNING) is not None
    assert _stored_allocation(world["inventory"], MORNING)[inv.ALLOCATED_QTY] == 2
    assert len(_movements(world["inventory"])) == 1


def test_idem_a_retry_replays_the_original_answer_and_writes_nothing_more(world: Dict[str, Any]) -> None:
    """§3.1 idempotency: the same key and fingerprint answer the original result, exactly once."""
    _two_events(world)

    first = _ok(_assign(items=[_target(3)], key="assign-1"))
    again = _ok(_assign(items=[_target(3)], key="assign-1"))

    assert again == first
    assert len(_allocations(world["inventory"])) == 1
    assert len(_movements(world["inventory"])) == 1
    assert _stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 2
    assert len(_marker_rows(world["show_and_sells"])) == 1


def test_idem_the_same_key_with_different_targets_is_refused(world: Dict[str, Any]) -> None:
    """§3.1: one key means one request. A different body under it is refused, never replayed."""
    _two_events(world)
    _ok(_assign(items=[_target(3)], key="assign-1"))

    error = assert_is_error(_assign(items=[_target(2)], key="assign-1"), "INVALID_INPUT")
    assert "different request content" in error["message"]
    assert _stored_allocation(world["inventory"], MORNING)[inv.ALLOCATED_QTY] == 3
    assert len(_movements(world["inventory"])) == 1


def test_auth_u_only_an_admin_of_the_event_s_own_unit_may_assign_it(world: Dict[str, Any]) -> None:
    """AUTH-U: tenancy comes from the event row, so another Unit's Admin is told not-found."""
    _two_events(world)

    for persona in ("Blake", "Devon", "Taylor", "Riley", "Emery"):
        assert_is_error(_assign(caller=persona, items=[_target(1)], key=f"assign-{persona}"), "NOT_FOUND")
    assert_is_error(_assign(caller=None, items=[_target(1)]), "UNAUTHORIZED")
    assert_is_error(_assign(event_id="SSE#never-created", items=[_target(1)]), "NOT_FOUND")
    assert _allocations(world["inventory"]) == []
    assert _marker_rows(world["show_and_sells"]) == []


def test_a_finalized_or_cancelled_event_is_not_assigned(world: Dict[str, Any]) -> None:
    """§3.5's matrix: assignment is never allowed on FINALIZED or CANCELLED."""
    _seed_balance(world["inventory"], PRODUCT, physical=4)
    _seed_event(world["show_and_sells"], "SSE#finalized", status=ssm.STATUS_FINALIZED)
    _seed_event(world["show_and_sells"], "SSE#cancelled", status=ssm.STATUS_CANCELLED)

    assert_is_error(_assign(event_id="SSE#finalized", items=[_target(1)]), "CONFLICT")
    assert_is_error(_assign(event_id="SSE#cancelled", items=[_target(1)]), "CONFLICT")
    assert _allocations(world["inventory"]) == []


def test_an_ended_event_is_still_assigned(world: Dict[str, Any]) -> None:
    """§3.5 allows assignment while ENDED: finalization has not decided what sold yet."""
    _seed_balance(world["inventory"], PRODUCT, physical=4)
    _seed_event(world["show_and_sells"], "SSE#ended", start_at=_shift(-48), end_at=_shift(-44))

    _ok(_assign(event_id="SSE#ended", items=[_target(4)]))

    assert _stored_allocation(world["inventory"], "SSE#ended")[inv.ALLOCATED_QTY] == 4


def test_an_empty_batch_and_a_missing_envelope_are_refused(world: Dict[str, Any]) -> None:
    _two_events(world)

    assert_is_error(_assign(items=[]), "INVALID_INPUT")
    assert_is_error(_assign(items=[_target(1)], key=None), "INVALID_INPUT")
    assert _allocations(world["inventory"]) == []


# --- §3.2.3 REOPENED: draft inputs only -----------------------------------------


def test_a_reopened_event_records_the_targets_as_drafts_and_moves_no_stock(
    world: Dict[str, Any],
) -> None:
    """§3.2.3, §8.6: while REOPENED the save is an input, not a stock effect."""
    _seed_event(
        world["show_and_sells"],
        "SSE#reopened",
        status=ssm.STATUS_REOPENED,
        product_ids=[OTHER_PRODUCT],
        **{ssm.ALLOCATION_DRAFT_ATTRIBUTE: {OTHER_PRODUCT: 5}},
    )
    _seed_balance(world["inventory"], PRODUCT, physical=6)
    _seed_balance(world["inventory"], OTHER_PRODUCT, physical=6)
    _seed_allocation(
        world["inventory"],
        "SSE#reopened",
        OTHER_PRODUCT,
        allocated=6,
        released=6,
        status=inv.ALLOCATION_RELEASED,
    )

    answer = _ok(_assign(event_id="SSE#reopened", items=[_target(4)]))

    assert answer["warnings"] == [], "a draft changes no instant, so nothing over-assigns yet"
    assert [(item["showAndSellId"], item["status"]) for item in answer["allocations"]] == [
        ("SSE#reopened", inv.ALLOCATION_RELEASED)
    ], "the released row is reported, and no new row appears"
    assert answer["inventoryPositions"][0]["assignedOpenQty"] == 0, "a draft assigns nothing today"
    stored = _stored_event(world["show_and_sells"], "SSE#reopened")
    assert stored[ssm.ALLOCATION_DRAFT_ATTRIBUTE] == {OTHER_PRODUCT: 5, PRODUCT: 4}, "merged, not replaced"
    assert stored[ssm.PRODUCT_IDS_ATTRIBUTE] == [OTHER_PRODUCT, PRODUCT]
    assert stored[ssm.VERSION_ATTRIBUTE] == 2
    assert len(_allocations(world["inventory"])) == 1, "the released row is left alone, and no new row is written"
    assert _movements(world["inventory"]) == []
    for product_id in (PRODUCT, OTHER_PRODUCT):
        balance = _stored_balance(world["inventory"], product_id)
        assert (balance[inv.VERSION_ATTRIBUTE], balance[inv.KERNEL_PHYSICAL_QTY]) == (1, 6)
    assert _stored_allocation(world["inventory"], "SSE#reopened", PRODUCT) is None


def test_a_reopened_draft_for_a_product_that_is_not_stocked_stays_off_the_list(
    world: Dict[str, Any],
) -> None:
    """§8.10: finalization requires an allocation for every listed product."""
    _seed_event(world["show_and_sells"], "SSE#reopened", status=ssm.STATUS_REOPENED)

    _ok(_assign(event_id="SSE#reopened", items=[_target(0)]))

    assert _stored_event(world["show_and_sells"], "SSE#reopened")[ssm.PRODUCT_IDS_ATTRIBUTE] == []


# --- §3.2.4 the raw allocation read (DATA-Q-03, PAGE-01, AUTH-U) ----------------


def test_data_q_03_the_read_answers_rows_and_never_an_aggregate(world: Dict[str, Any]) -> None:
    """§9, AC-36: the browser does the arithmetic, so the read carries the fields, not a total."""
    _seed_event(world["show_and_sells"], MORNING)
    _seed_event(world["show_and_sells"], AFTERNOON, start_at=ADJACENT_START, end_at=ADJACENT_END)
    _seed_balance(world["inventory"], PRODUCT, physical=4)
    _seed_allocation(world["inventory"], MORNING, PRODUCT, allocated=3)
    _seed_allocation(world["inventory"], AFTERNOON, PRODUCT, allocated=3, start_at=ADJACENT_START, end_at=ADJACENT_END)

    page = _ok(_read_allocations())

    assert sorted(page.keys()) == ["items", "pageInfo"]
    assert len(page["items"]) == 2
    first = page["items"][0]
    assert sorted(first.keys()) == sorted(
        [
            "unitCampaignId",
            "productId",
            "showAndSellId",
            "startAt",
            "endAt",
            "status",
            "allocatedQty",
            "soldQty",
            "releasedQty",
            "remainingQty",
            "version",
            "createdAt",
            "updatedAt",
        ]
    )
    assert (first["allocatedQty"], first["remainingQty"], first["status"], first["version"]) == (3, 3, "OPEN", 1)
    assert page["pageInfo"]["hasNextPage"] is False

    positions = _ok(
        _call(INVENTORY_POSITIONS_FIELD, "Avery", arguments={"unitCampaignId": CAMPAIGN, "productIds": [PRODUCT]})
    )
    total_assigned = sum(item["remainingQty"] for item in page["items"] if item["status"] == "OPEN")
    assert positions["items"][0]["assignedOpenQty"] == total_assigned, (
        "the read reconciles against the same rows the position derives from"
    )
    assert positions["items"][0]["assignmentOverageQty"] == 2


def test_data_q_03_the_allocations_reconcile_to_the_movement_trail(world: Dict[str, Any]) -> None:
    """§4.3, ALLOC-05/06: every change of assigned quantity is one movement, and the trail sums to the row.

    The browser is allowed to add the page up; that promise is only worth anything if the
    audit rows describe the same history the allocation row reports. Each save is one
    movement carrying exactly the quantity that save moved, in the order the saves ran, and
    the running total lands on the row the read returns.
    """
    _seed_event(world["show_and_sells"], MORNING)
    _seed_balance(world["inventory"], PRODUCT, physical=6)
    _ok(_assign(items=[_target(5)], key="five"))
    _ok(_assign(items=[_target(2)], version=2, key="two"))
    _ok(_assign(items=[_target(0)], version=3, key="zero"))
    _ok(_assign(items=[_target(3)], version=4, key="three"))

    movements = _movements(world["inventory"])
    assert [row[inv.MOVEMENT_TYPE_ATTRIBUTE] for row in movements] == [
        inv.EVENT_ASSIGN,
        inv.EVENT_MANUAL_REDUCE,
        inv.EVENT_MANUAL_REDUCE,
        inv.EVENT_ASSIGN,
    ]
    assert [am.assigned_delta_of(row) for row in movements] == [5, -3, -2, 3]
    assert sum(am.assigned_delta_of(row) for row in movements) == 3

    rows = _ok(_read_allocations())["items"]
    assert [(r["allocatedQty"], r["soldQty"], r["releasedQty"], r["remainingQty"]) for r in rows] == [(3, 0, 0, 3)]
    assert sum(r["remainingQty"] for r in rows if r["status"] == inv.ALLOCATION_OPEN) == sum(
        am.assigned_delta_of(row) for row in movements
    )


def test_the_read_filters_by_product_event_and_status(world: Dict[str, Any]) -> None:
    _seed_event(world["show_and_sells"], MORNING)
    _seed_event(world["show_and_sells"], AFTERNOON)
    _seed_balance(world["inventory"], PRODUCT, physical=10)
    _seed_balance(world["inventory"], OTHER_PRODUCT, physical=10)
    _seed_allocation(world["inventory"], MORNING, PRODUCT, allocated=2)
    _seed_allocation(world["inventory"], AFTERNOON, PRODUCT, allocated=1)
    _seed_allocation(
        world["inventory"], MORNING, OTHER_PRODUCT, allocated=3, released=3, status=inv.ALLOCATION_RELEASED
    )

    assert [row["showAndSellId"] for row in _ok(_read_allocations(productId=PRODUCT))["items"]] == [
        AFTERNOON,
        MORNING,
    ]
    assert [row["productId"] for row in _ok(_read_allocations(showAndSellId=MORNING))["items"]] == [
        PRODUCT,
        OTHER_PRODUCT,
    ]
    assert [row["status"] for row in _ok(_read_allocations(status="RELEASED"))["items"]] == ["RELEASED"]
    assert _ok(_read_allocations(showAndSellId="SSE#nobody"))["items"] == []
    assert_is_error(_read_allocations(status="ARCHIVED"), "INVALID_INPUT")
    assert_is_error(_read_allocations(campaign="uc-none"), "NOT_FOUND")
    for persona in ("Blake", "Devon", "Taylor"):
        assert_is_error(_read_allocations(caller=persona), "NOT_FOUND")


def test_page_01_an_allocation_cursor_belongs_to_one_filtered_page(world: Dict[str, Any]) -> None:
    """PAGE-01: the cursor is a positional claim inside one filtered result set."""
    _seed_event(world["show_and_sells"], MORNING)
    _seed_balance(world["inventory"], PRODUCT, physical=40)
    for index in range(4):
        _seed_allocation(world["inventory"], f"SSE#page-{index}", PRODUCT, allocated=index + 1)

    first = _ok(_read_allocations(page={"limit": 2}))
    assert len(first["items"]) == 2 and first["pageInfo"]["hasNextPage"] is True
    second = _ok(_read_allocations(page={"limit": 2, "cursor": first["pageInfo"]["endCursor"]}))
    assert len(second["items"]) == 2 and second["pageInfo"]["hasNextPage"] is False
    assert {item["showAndSellId"] for item in first["items"]}.isdisjoint(
        {item["showAndSellId"] for item in second["items"]}
    )

    cursor = first["pageInfo"]["endCursor"]
    assert_is_error(_read_allocations(page={"limit": 2, "cursor": cursor}, status="OPEN"), "INVALID_INPUT")
    assert_is_error(_read_allocations(page={"limit": 2, "cursor": cursor}, productId=PRODUCT), "INVALID_INPUT")
    assert_is_error(
        _read_allocations(campaign=OTHER_UNIT_CAMPAIGN, page={"limit": 2, "cursor": cursor}), "INVALID_INPUT"
    )


def test_the_read_sees_the_allocation_a_mutation_just_committed(world: Dict[str, Any]) -> None:
    """DATA-Q-03's reconciliation depends on a consistent read, not an index that lags."""
    _two_events(world)

    _ok(_assign(items=[_target(3)], key="assign-1"))
    page = _ok(_read_allocations())

    assert [(item["showAndSellId"], item["allocatedQty"], item["version"]) for item in page["items"]] == [
        (MORNING, 3, 1)
    ]
