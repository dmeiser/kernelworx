"""Wave 5.2 — pooled sale entry, correction and voiding (§4.2.2, §4.3.1, §4.3.2).

Resolver-level cases for ``SALE-M-01``, ``SALE-M-02`` and ``SALE-M-03``, plus the ``AUTH-U``,
``VER-01`` and ``IDEM`` halves of each. Everything runs through ``handle_unit_operation``
against moto, so what is proved is the transaction: the sale row, its obligation rows, the
allocation and balance writes, the audit movements, the event's cumulative ``productIds``
and the idempotency marker either commit together or not at all — and a correction's
archived revision is a real immutable child row, not a promise in a docstring. The pure
half — the line arithmetic, the per-product stock planner and the §8.6.1 obligation
equations — is ``tests/unit/test_show_and_sell_sale_model.py``.

The scenario is one table at one event: four boxes of caramel assigned to it, priced at
five dollars. Event instants are measured from the real clock, because the state matrix
and ``saleAt`` are both read against ``utc_now_iso()`` and a literal "recent past" goes
stale the day the calendar crosses it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

import pytest

from src.handlers.unit_operations import (
    CONFIRM_WORK_FIELD,
    CORRECT_SALE_FIELD,
    CREATE_SALE_FIELD,
    VOID_SALE_FIELD,
    handle_unit_operation,
)
from src.utils import allocation_models as am
from src.utils import inventory_models as inv
from src.utils import show_and_sell_models as ssm
from src.utils import show_and_sell_sale_models as sm
from src.utils import unit_payment_models as upm
from tests.unit.show_sell_fixtures import (
    PACK_3149,
    PACK_3149_FALL,
    account_id,
    assert_is_error,
    catalog_item,
    seed_show_sell_fixtures,
    unit_operation_event,
)

UNIT = PACK_3149
CAMPAIGN = PACK_3149_FALL
CATALOG_ID = "CATALOG#fixture-default"
PRODUCT = f"{CATALOG_ID}#prod-1"
OTHER_PRODUCT = f"{CATALOG_ID}#prod-2"
ACTIVE_EVENT = "SSE#table"
#: A second event overlapping the first, used only to make the campaign's open
#: allocations exceed its stock so the sale answer has to say so (ALLOC-03, AC-10).
RIVAL_EVENT = "SSE#rival"
LOCATION = "Aurora armory lot"
PRICE_CENTS = 500
WISE_METHOD_ID = "pm-wise-sale"
#: The handler stores actor ids the way the identity claim spells them: the bare sub.
AVERY = account_id("Avery")
#: The finalization estimate's terms (§8.10, §9): three baseline writes plus four per
#: allocated product plus one per active sale. The two budgets the sale writes are
#: measured against these numbers.
OVERHEAD = am.FINALIZATION_OVERHEAD_ACTIONS
PER_PRODUCT = am.FINALIZATION_ACTIONS_PER_ALLOCATED_PRODUCT


def _shift(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


#: The event is running: its interval brackets the clock, so a sale entered now is inside it.
ACTIVE_START, ACTIVE_END = _shift(-3), _shift(3)
SALE_AT = _shift(-1)
#: The ended event's interval is wholly behind the clock, which is still a live state (§4.2.2).
ENDED_START, ENDED_END = _shift(-48), _shift(-44)
ENDED_SALE_AT = _shift(-45)
#: The future event is still SCHEDULED — the one state that refuses a sale (§4.2.2's matrix).
FUTURE_START, FUTURE_END = _shift(24), _shift(28)


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


def _sale_version(expected: int) -> Dict[str, Any]:
    return {"saleVersion": {"expectedVersion": expected}}


def _line(product_id: str = PRODUCT, immediate: int = 1, we_owe: int = 0) -> Dict[str, Any]:
    return {"productId": product_id, "immediateQty": immediate, "weOweQty": we_owe}


def _create(
    caller: Optional[str] = "Avery",
    *,
    event_id: str = ACTIVE_EVENT,
    lines: Optional[Sequence[Dict[str, Any]]] = None,
    version: int = 1,
    key: str = "sale-1",
    sale_at: str = SALE_AT,
    **input_extras: Any,
) -> Any:
    payload: Dict[str, Any] = {
        "showAndSellId": event_id,
        "saleAt": sale_at,
        "lineItems": list(lines) if lines is not None else [_line()],
        "paymentMethodCode": "CASH",
        **_version(version),
        **_idem(key),
    }
    payload.update(input_extras)
    return _call(CREATE_SALE_FIELD, caller, mutation=payload)


def _correct(
    caller: Optional[str] = "Avery",
    *,
    event_id: str = ACTIVE_EVENT,
    sale_id: str,
    lines: Sequence[Dict[str, Any]],
    revision: int = 1,
    version: int = 2,
    key: str = "correct-1",
    reason: str = "two boxes came back",
    **input_extras: Any,
) -> Any:
    payload: Dict[str, Any] = {
        "showAndSellId": event_id,
        "saleId": sale_id,
        "reason": reason,
        "lineItems": list(lines),
        **_sale_version(revision),
        **_version(version),
        **_idem(key),
    }
    payload.update(input_extras)
    return _call(CORRECT_SALE_FIELD, caller, mutation=payload)


def _void(
    caller: Optional[str] = "Avery",
    *,
    event_id: str = ACTIVE_EVENT,
    sale_id: str,
    revision: int = 1,
    version: int = 2,
    key: str = "void-1",
    reason: str = "the buyer changed their mind",
    **input_extras: Any,
) -> Any:
    payload: Dict[str, Any] = {
        "showAndSellId": event_id,
        "saleId": sale_id,
        "reason": reason,
        **_sale_version(revision),
        **_version(version),
        **_idem(key),
    }
    payload.update(input_extras)
    return _call(VOID_SALE_FIELD, caller, mutation=payload)


# --- Seeded rows -----------------------------------------------------------------


def _offer_products(catalogs_table: Any, count: int) -> List[str]:
    """Give the campaign's catalog ``count`` products at five dollars, replacing the seeded one."""
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
    # A live event stores SCHEDULED: ACTIVE and ENDED are derived from the interval
    # (SSE-04) and a row storing either one is rejected by the event invariant. The
    # interval below brackets "now", so the seeded event reads ACTIVE — the row the
    # deployed product actually creates, which is what makes these tests exercise the
    # same decision path QA probes on dev.kernelworx.app.
    status: str = ssm.STATUS_SCHEDULED,
    start_at: str = ACTIVE_START,
    end_at: str = ACTIVE_END,
    version: int = 1,
    product_ids: Optional[List[str]] = None,
    we_owe_enabled: bool = True,
    **overrides: Any,
) -> str:
    item = ssm.build_show_and_sell_item(
        show_and_sell_id=event_id,
        unit_id=UNIT,
        unit_campaign_id=CAMPAIGN,
        location_name=LOCATION,
        start_at=start_at,
        end_at=end_at,
        created_by_account_id=AVERY,
        now_iso=start_at,
        product_ids=product_ids or [],
        we_owe_enabled=we_owe_enabled,
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
        now_iso=ACTIVE_START,
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
    start_at: str = ACTIVE_START,
    end_at: str = ACTIVE_END,
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
        now_iso=ACTIVE_START,
        version=version,
    )
    inventory_table.put_item(Item=item)
    return item


def _seed_stock(
    world: Dict[str, Any],
    *,
    event_id: str = ACTIVE_EVENT,
    product_id: str = PRODUCT,
    physical: int = 4,
    allocated: int = 4,
) -> None:
    """The four-box table: the campaign holds four and this event is assigned four."""
    _seed_balance(world["inventory"], product_id, physical=physical)
    _seed_allocation(world["inventory"], event_id, product_id, allocated=allocated)


def _seed_we_owe_state(
    show_and_sells_table: Any,
    inventory_table: Any,
    event_id: str,
    sale_id: str,
    *,
    fulfilled: int = 0,
    reserved: int = 0,
    line_index: int = 0,
) -> Dict[str, Any]:
    """Move one obligation into a mid-life state Wave 4.4's writes will produce.

    A sale only ever creates an OPEN obligation with nothing fulfilled or reserved, so the
    fulfilled and reserved shapes the correction and void rules are written against — the
    quantity the buyer already holds, the units a Scout is carrying — have to be seeded.
    The arithmetic of both rows is kept true on the way in: a reservation Wave 4.4 would
    have written moves the same number of units into ``soldInPossessionQty``, so the seed
    adds them there too, and a test that seeded a broken pair would be refusing a broken
    pair, not enforcing a rule.
    """
    row = dict(sm.sale_obligations(event_id, sale_id)[line_index])
    product_id = str(row[inv.PRODUCT_ID_ATTRIBUTE])
    remaining = int(row[sm.ORIGINAL_QTY_ATTRIBUTE]) - fulfilled - int(row[sm.CANCELLED_QTY_ATTRIBUTE])
    row[sm.FULFILLED_QTY_ATTRIBUTE] = fulfilled
    row[sm.RESERVED_QTY_ATTRIBUTE] = reserved
    row[sm.REMAINING_QTY_ATTRIBUTE] = remaining
    row[sm.UNCOVERED_QTY_ATTRIBUTE] = remaining - reserved
    show_and_sells_table.put_item(Item=row)
    if reserved:
        balance = _stored_balance(inventory_table, product_id)
        assert balance is not None
        inventory_table.update_item(
            Key=inv.balance_key(CAMPAIGN, product_id),
            UpdateExpression="SET #possession = :possession, #version = :version, #updatedAt = :updatedAt",
            ExpressionAttributeNames={
                "#possession": inv.SOLD_IN_POSSESSION_QTY,
                "#version": inv.VERSION_ATTRIBUTE,
                "#updatedAt": inv.UPDATED_AT_ATTRIBUTE,
            },
            ExpressionAttributeValues={
                ":possession": int(balance[inv.SOLD_IN_POSSESSION_QTY]) + reserved,
                ":version": int(balance[inv.VERSION_ATTRIBUTE]) + 1,
                ":updatedAt": row.get(sm.UPDATED_AT_ATTRIBUTE) or row[sm.CREATED_AT_ATTRIBUTE],
            },
        )
    return row


def _method(
    units_table: Any,
    *,
    payment_method_id: str = WISE_METHOD_ID,
    display_name: str = "Wise Transfer",
    is_active: bool = True,
) -> Dict[str, Any]:
    """One custom payment method row, written the way ``createUnitPaymentMethod`` writes it."""
    item = upm.build_payment_item(
        payment_method_id=payment_method_id,
        unit_id=UNIT,
        display_name=display_name,
        created_by_account_id=AVERY,
        now_iso=ACTIVE_START,
        is_active=is_active,
    )
    units_table.put_item(Item=item)
    return item


def _rename_method(units_table: Any, *, display_name: str = "Wise Business", is_active: bool = False) -> Dict[str, Any]:
    """Rename and retire the seeded method the way ``updateUnitPaymentMethod`` does.

    The method's sort key is its normalized name, so a rename is a new key with the same
    ``paymentMethodId`` and the old key gone — which is exactly the drift a sale's payment
    snapshot exists to survive (PAY-06).
    """
    for row in list(units_table.scan()["Items"]):
        if str(row.get("paymentMethodId", "")) == WISE_METHOD_ID:
            units_table.delete_item(Key={"pk": str(row["pk"]), "sk": str(row["sk"])})
    return _method(units_table, display_name=display_name, is_active=is_active)


def _seed_signup(
    show_and_sells_table: Any,
    event_id: str,
    *,
    minutes: int = 0,
    profile_id: str = "PROFILE#sale-budget-scout",
) -> Dict[str, Any]:
    """One ACTIVE signup row; minutes > 0 reads as confirmed work by §8.10's budget."""
    event = show_and_sells_table.get_item(Key=ssm.event_metadata_key(event_id)).get("Item")
    item = ssm.build_show_and_sell_signup_item(
        event=dict(event),
        slot_id="slot-budget",
        profile_id=profile_id,
        campaign_id="SC#sale-budget",
        signed_up_by_account_id=AVERY,
        now_iso=ACTIVE_START,
        status=ssm.SIGNUP_ACTIVE,
        actual_minutes=minutes,
        confirmed_by_account_id=AVERY if minutes else None,
        confirmed_at=ACTIVE_START if minutes else None,
    )
    show_and_sells_table.put_item(Item=item)
    return item


# --- Storage reads ---------------------------------------------------------------


def _rows(table: Any) -> List[Dict[str, Any]]:
    return list(table.scan()["Items"])


def _stored(table: Any, key: Dict[str, str]) -> Optional[Dict[str, Any]]:
    item = table.get_item(Key=key).get("Item")
    return dict(item) if isinstance(item, dict) else None


def _stored_sale(show_and_sells_table: Any, event_id: str, sale_id: str) -> Optional[Dict[str, Any]]:
    return _stored(show_and_sells_table, sm.sale_key(event_id, sale_id))


def _stored_revision(show_and_sells_table: Any, event_id: str, sale_id: str, revision: int) -> Optional[Dict[str, Any]]:
    return _stored(show_and_sells_table, sm.sale_revision_key(event_id, sale_id, revision))


def _sale_rows(show_and_sells_table: Any) -> List[Dict[str, Any]]:
    return [row for row in _rows(show_and_sells_table) if row.get("entityType") == sm.SALE_ENTITY_TYPE]


def _revision_rows(show_and_sells_table: Any) -> List[Dict[str, Any]]:
    return [row for row in _rows(show_and_sells_table) if row.get("entityType") == sm.SALE_REVISION_ENTITY_TYPE]


def _obligation_rows(show_and_sells_table: Any) -> List[Dict[str, Any]]:
    return [row for row in _rows(show_and_sells_table) if row.get("entityType") == sm.WE_OWE_ENTITY_TYPE]


def _marker_rows(show_and_sells_table: Any) -> List[Dict[str, Any]]:
    return [row for row in _rows(show_and_sells_table) if str(row.get("sk", "")).startswith("IDEM#")]


def _stored_event(show_and_sells_table: Any, event_id: str = ACTIVE_EVENT) -> Dict[str, Any]:
    return dict(show_and_sells_table.get_item(Key=ssm.event_metadata_key(event_id))["Item"])


def _inventory_rows(inventory_table: Any) -> List[Dict[str, Any]]:
    return list(inventory_table.scan()["Items"])


def _movements(inventory_table: Any) -> List[Dict[str, Any]]:
    return [row for row in _inventory_rows(inventory_table) if row.get("entityType") == inv.MOVEMENT_ENTITY_TYPE]


def _stored_allocation(inventory_table: Any, event_id: str, product_id: str = PRODUCT) -> Optional[Dict[str, Any]]:
    return _stored(inventory_table, ssm.event_allocation_key(CAMPAIGN, product_id, event_id))


def _stored_balance(inventory_table: Any, product_id: str = PRODUCT) -> Optional[Dict[str, Any]]:
    return _stored(inventory_table, inv.balance_key(CAMPAIGN, product_id))


def _sold_inventory(inventory_table: Any, product_id: str = PRODUCT) -> Dict[str, Any]:
    """One product's (physical, version, allocation sold, allocation remaining) after a write."""
    balance = _stored_balance(inventory_table, product_id)
    assert balance is not None
    return {
        "physical": balance[inv.KERNEL_PHYSICAL_QTY],
        "version": balance[inv.VERSION_ATTRIBUTE],
        "sold": balance[inv.SOLD_IN_POSSESSION_QTY],
    }


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
    """The Stage 1 persona world plus the two tables these three mutations write."""
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    # The seeded catalog offers one product of its own, at its own price; every scenario
    # here sells two products at five dollars, so the campaign's catalog has to be rewritten.
    _offer_products(catalogs_table, 4)
    return {
        "show_and_sells": show_and_sells_table,
        "inventory": inventory_table,
        "catalogs": catalogs_table,
        "units": units_table,
    }


def _sold_sale(world: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Sell at this event and return the answer, asserting it landed."""
    return _ok(_create(**kwargs))


# --- SALE-M-01-01: entering a sale, and who may enter one ------------------------


def test_sale_m_01_01_one_sale_answers_sale_allocation_obligation_position_and_warning(
    world: Dict[str, Any],
) -> None:
    """SALE-M-01-01, AC-19, AC-21, AC-10: the whole answer, and the whole trail behind it."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_event(world["show_and_sells"], RIVAL_EVENT)
    _seed_stock(world)
    _seed_allocation(world["inventory"], RIVAL_EVENT, PRODUCT, allocated=2)

    answer = _sold_sale(
        world,
        lines=[_line(PRODUCT, immediate=1, we_owe=1)],
        buyerName="Buyer Bee",
        buyerPhone=" 303-555-0100 ",
    )

    sale = answer["sale"]
    stored = _stored_sale(world["show_and_sells"], ACTIVE_EVENT, sale["saleId"])
    assert stored is not None
    assert (sale["revision"], sale["status"]) == (1, sm.SALE_STATUS_ACTIVE)
    assert sale["unitId"] == UNIT and sale["unitCampaignId"] == CAMPAIGN
    assert sale["saleAt"] == SALE_AT
    assert sale["enteredByAccountId"] == AVERY
    assert sale["buyerName"] == "Buyer Bee"
    assert sale["buyerPhone"] == "303-555-0100", "contact detail is stored trimmed"
    assert sm.BUYER_EMAIL_ATTRIBUTE not in stored, "an omitted contact field is absent, not empty"
    assert sale["paymentMethodSnapshot"] == {"methodCode": "CASH", "displayName": "Cash", "otherDetails": None}
    assert sale["expectedCashCents"] == 1000, "two Kernels at five dollars, all of it cash"

    line = sale["lineItems"][0]
    assert line[sm.PRODUCT_NAME_SNAPSHOT_ATTRIBUTE] == "Caramel 1"
    assert line[sm.UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE] == PRICE_CENTS
    assert line[sm.SUBTOTAL_CENTS_ATTRIBUTE] == 1000
    assert sale["totalCents"] == 1000

    stored_allocation = _stored_allocation(world["inventory"], ACTIVE_EVENT)
    assert stored_allocation is not None
    assert (stored_allocation[inv.SOLD_QTY], stored_allocation[inv.REMAINING_QTY]) == (1, 3)
    assert answer["allocations"] == [ssm.allocation_payload(stored_allocation)]

    balance = _sold_inventory(world["inventory"])
    assert (balance["physical"], balance["version"]) == (3, 2), "one Kernel off the shelf, one version"
    position = answer["inventoryPositions"][0]
    assert (position["kernelPhysicalQty"], position["sellableKernelQty"]) == (3, 3)

    assert len(answer["warnings"]) == 1
    warning = answer["warnings"][0]
    assert warning["code"] == am.SEQUENTIAL_OVER_ASSIGNMENT
    assert (warning["currentStockQty"], warning["assignedQty"], warning["overageQty"]) == (3, 5, 2)

    assert len(answer["obligations"]) == 1
    obligation = answer["obligations"][0]
    assert obligation["lineItemId"] == line[sm.LINE_ITEM_ID_ATTRIBUTE]
    assert obligation["buyerName"] == "Buyer Bee"
    assert (obligation["originalQty"], obligation["remainingQty"], obligation["uncoveredQty"]) == (1, 1, 1)
    assert obligation["valueCentsSnapshot"] == PRICE_CENTS
    assert obligation["status"] == sm.WE_OWE_STATUS_OPEN

    assert len(_movements(world["inventory"])) == 1
    movement = _movements(world["inventory"])[0]
    assert movement[inv.MOVEMENT_TYPE_ATTRIBUTE] == inv.EVENT_IMMEDIATE_SALE
    assert movement[inv.KERNEL_PHYSICAL_DELTA] == -1
    assert movement[inv.ASSIGNED_DELTA] == -1
    assert movement[inv.SALE_ID_ATTRIBUTE] == sale["saleId"]
    assert movement[inv.SHOW_AND_SELL_ID_ATTRIBUTE] == ACTIVE_EVENT
    assert movement[inv.INVENTORY_VERSION_ATTRIBUTE] == 2, "the movement names the version this write produced"

    event = _stored_event(world["show_and_sells"])
    assert (event[ssm.VERSION_ATTRIBUTE], event[ssm.PRODUCT_IDS_ATTRIBUTE]) == (2, [PRODUCT])
    assert answer["eventVersion"] == 2 and answer["draftOnly"] is False
    assert len(_marker_rows(world["show_and_sells"])) == 1


def test_sale_m_01_01_an_ended_event_still_takes_sales(world: Dict[str, Any]) -> None:
    """§4.2.2: ENDED is a live state — finalization has not decided what sold yet.

    The stored row still says SCHEDULED (an ENDED row is a state the event model derives
    and refuses to store); the interval is what makes it ended. This is the exact shape
    QA's reproduction hits on the deployed product.
    """
    _seed_event(world["show_and_sells"], ACTIVE_EVENT, start_at=ENDED_START, end_at=ENDED_END)
    _seed_stock(world)

    answer = _sold_sale(world, event_id=ACTIVE_EVENT, sale_at=ENDED_SALE_AT)

    assert answer["draftOnly"] is False
    assert _stored_allocation(world["inventory"], ACTIVE_EVENT)[inv.SOLD_QTY] == 1


def test_sale_m_01_01_only_this_units_admins_enter_sales(world: Dict[str, Any]) -> None:
    """AUTH-U: tenancy comes from the event row, so another Unit's Admin is told not-found."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)

    for persona in ("Blake", "Devon", "Taylor", "Riley", "Emery"):
        assert_is_error(_create(caller=persona, key=f"sale-{persona}"), "NOT_FOUND")
    assert_is_error(_create(caller=None), "UNAUTHORIZED")
    assert_is_error(_create(event_id="SSE#never-created"), "NOT_FOUND")

    assert _sale_rows(world["show_and_sells"]) == []
    assert _obligation_rows(world["show_and_sells"]) == []
    assert _movements(world["inventory"]) == []
    assert _marker_rows(world["show_and_sells"]) == []
    assert _stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 1


# --- SALE-M-01-02: state, interval, version and the write budget ------------------


def test_every_event_this_file_seeds_is_a_row_the_deployed_product_writes(world: Dict[str, Any]) -> None:
    """The suite is evidence only if it seeds rows the product can actually create.

    QA's reproduction failed on the deployed build because every live event there stores
    ``SCHEDULED`` while this file used to store ``ACTIVE`` — a clock state the event model
    derives and whose invariant rejects a row that carries one — so a gate that read the
    stored field looked right against a row the deployed product never writes. This pins
    the three shapes the sale tests use to the model's own checks: no invariant violation,
    and the state the read path reports is the one each test believes it is exercising.
    """
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_event(world["show_and_sells"], "SSE#guarded-ended", start_at=ENDED_START, end_at=ENDED_END)
    _seed_event(world["show_and_sells"], "SSE#guarded-reopened", status=ssm.STATUS_REOPENED)

    for event_id, stored, derived in (
        (ACTIVE_EVENT, ssm.STATUS_SCHEDULED, ssm.STATUS_ACTIVE),
        ("SSE#guarded-ended", ssm.STATUS_SCHEDULED, ssm.STATUS_ENDED),
        ("SSE#guarded-reopened", ssm.STATUS_REOPENED, ssm.STATUS_REOPENED),
    ):
        row = _stored_event(world["show_and_sells"], event_id)
        assert ssm.event_invariant_violations(row) == [], f"{event_id} seeds a row the model rejects"
        assert row[ssm.STATUS_ATTRIBUTE] == stored, f"{event_id} stores the placeholder, not the answer"
        assert ssm.derive_event_status(row) == derived, f"{event_id} is not the state the tests assume"


def test_sale_m_01_02_scheduled_finalized_and_cancelled_events_refuse_sales(world: Dict[str, Any]) -> None:
    """§4.2.2's matrix, and the refusal names the state so the admin knows the remedy.

    ``SCHEDULED`` is refused by its interval, not by its stored field — a stored
    ``SCHEDULED`` whose interval has begun reads ``ACTIVE`` and takes sales, which is the
    state every other test in this file seeds. ``FINALIZED`` and ``CANCELLED`` are stored
    workflow states and refuse whatever the clock says.
    """
    cases = (
        (ssm.STATUS_SCHEDULED, FUTURE_START, FUTURE_END),
        (ssm.STATUS_FINALIZED, ACTIVE_START, ACTIVE_END),
        (ssm.STATUS_CANCELLED, ACTIVE_START, ACTIVE_END),
    )
    for status, start_at, end_at in cases:
        event_id = f"SSE#{status.lower()}"
        _seed_event(world["show_and_sells"], event_id, status=status, start_at=start_at, end_at=end_at)
        _seed_stock(world, event_id=event_id)

        refused = _create(event_id=event_id, key=f"sale-{status}")

        error = assert_is_error(refused, "CONFLICT")
        assert status in error["message"], f"the refusal says which state it refused: {error['message']}"
        assert _sale_rows(world["show_and_sells"]) == []
        assert _stored_allocation(world["inventory"], event_id)[inv.SOLD_QTY] == 0
        assert _stored_balance(world["inventory"])[inv.VERSION_ATTRIBUTE] == 1
        assert _stored_event(world["show_and_sells"], event_id)[ssm.VERSION_ATTRIBUTE] == 1


def test_sale_m_01_02_a_sale_outside_the_event_and_a_stale_event_version_write_nothing(
    world: Dict[str, Any],
) -> None:
    """SALE-M-01-02, VER-01: the interval is the event's, and the version is the row's."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)

    assert_is_error(_create(sale_at=_shift(-4), key="sale-early"), "INVALID_INPUT")
    assert_is_error(_create(sale_at=_shift(4), key="sale-late"), "INVALID_INPUT")
    assert_is_error(_create(sale_at="not-a-moment", key="sale-junk"), "INVALID_INPUT")
    assert_is_error(_create(version=7, key="sale-stale"), "CONFLICT")
    assert_is_error(_create(key=None), "INVALID_INPUT")
    assert_is_error(_create(lines=[], key="sale-empty"), "INVALID_INPUT")

    error = assert_is_error(_create(version=7, key="sale-stale-again"), "CONFLICT")
    assert "changed since you read it" in error["message"]
    assert _sale_rows(world["show_and_sells"]) == []
    assert _movements(world["inventory"]) == []
    assert _stored_balance(world["inventory"])[inv.VERSION_ATTRIBUTE] == 1
    assert _stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 1


def test_sale_m_01_02_the_largest_transaction_safe_batch_lands_and_a_bigger_one_is_refused(
    world: Dict[str, Any],
) -> None:
    """AC-42's ceiling: 21 products finalize in 89 actions; a 22nd asks 95 of the second sale."""
    products = _offer_products(world["catalogs"], 22)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    for product_id in products:
        _seed_stock(world, product_id=product_id)

    largest = _ok(_create(lines=[_line(product_id) for product_id in products[:21]], key="sale-21"))

    assert len(largest["inventoryPositions"]) == 21
    assert largest["sale"]["totalCents"] == 21 * PRICE_CENTS
    assert len(_movements(world["inventory"])) == 21
    assert sorted(_stored_event(world["show_and_sells"])[ssm.PRODUCT_IDS_ATTRIBUTE]) == sorted(products[:21])

    refused = _create(lines=[_line(product_id) for product_id in products], version=2, key="sale-22")

    error = assert_is_error(refused, "CONFLICT")
    assert "finalize" in error["message"], error["message"]
    assert f"{22 * PER_PRODUCT + OVERHEAD + 2 * am.FINALIZATION_ACTIONS_PER_SALE} actions" in error["message"], error[
        "message"
    ]
    assert len(_sale_rows(world["show_and_sells"])) == 1, "the refusal adds no second sale"
    assert sorted(_stored_event(world["show_and_sells"])[ssm.PRODUCT_IDS_ATTRIBUTE]) == sorted(products[:21])


def test_sale_m_01_02_confirmed_work_shrinks_the_finalization_budget_a_sale_may_use(
    world: Dict[str, Any],
) -> None:
    """§8.10: the preflight counts the event, not just this sale — confirmed work and the
    Scouts who earned it are writes finalization has to make too."""
    products = _offer_products(world["catalogs"], 21)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    for product_id in products:
        _seed_stock(world, product_id=product_id)
    _seed_signup(world["show_and_sells"], ACTIVE_EVENT, minutes=0)

    largest = _ok(_create(lines=[_line(product_id) for product_id in products], key="sale-21"))
    assert len(largest["inventoryPositions"]) == 21, (
        f"an unconfirmed signup costs the budget nothing: {OVERHEAD} + 21×{PER_PRODUCT} + 1 sale fits"
    )

    _seed_signup(world["show_and_sells"], ACTIVE_EVENT, minutes=30)

    refused = _create(lines=[_line(product_id) for product_id in products], version=2, key="sale-21-again")

    error = assert_is_error(refused, "CONFLICT")
    assert "finalize" in error["message"], error["message"]
    assert (
        f"{OVERHEAD + 21 * PER_PRODUCT + am.FINALIZATION_ACTIONS_PER_CONFIRMED_SIGNUP + am.FINALIZATION_ACTIONS_PER_PARTICIPATING_SCOUT + 2 * am.FINALIZATION_ACTIONS_PER_SALE} actions"
        in error["message"]
    ), error["message"]
    assert len(_sale_rows(world["show_and_sells"])) == 1, "the refusal adds no second sale"
    assert _stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 2, "the refusal wrote nothing"


def test_work_confirmation_after_sales_is_budget_checked(world: Dict[str, Any]) -> None:
    """§8.10: sales recorded first cannot let a later work confirmation strand the event."""
    from tests.unit.test_show_and_sell_signups import _seed_slot

    _offer_products(world["catalogs"], 1)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world, physical=40, allocated=40)
    _seed_slot(
        world["show_and_sells"],
        event_id=ACTIVE_EVENT,
        slot_id="slot-budget",
        start_at=ACTIVE_START,
        end_at=ACTIVE_END,
        capacity=8,
        active=1,
    )
    signup = _seed_signup(world["show_and_sells"], ACTIVE_EVENT, minutes=0)
    profile_id = str(signup[ssm.PROFILE_ID_ATTRIBUTE])

    # Forty sales of one product fit the sale preflight at 87 actions. Confirming the
    # signed-up Scout afterwards must see those sales, not just the product count.
    for index in range(40):
        _ok(_create(lines=[_line(PRODUCT)], version=index + 1, key=f"sale-before-work-{index}"))
    stored_event = _stored_event(world["show_and_sells"])
    event_version = int(stored_event[ssm.VERSION_ATTRIBUTE])

    refused = _call(
        CONFIRM_WORK_FIELD,
        "Avery",
        mutation={
            "showAndSellId": ACTIVE_EVENT,
            "work": [{"slotId": "slot-budget", "profileId": profile_id, "actualMinutes": 75}],
            **_version(event_version),
            **_idem("work-after-sales"),
        },
    )
    error = assert_is_error(refused, "CONFLICT")
    assert "91 actions" in error["message"], error["message"]
    assert ssm.read_signup(ACTIVE_EVENT, "slot-budget", profile_id) == signup, "the signup was untouched"
    assert _stored_event(world["show_and_sells"]) == stored_event, "the event version was untouched"
    assert len(_sale_rows(world["show_and_sells"])) == 40, "the refusal added no work write"


def test_sale_m_01_02_a_line_batch_over_the_action_budget_is_refused_and_splits_into_two_sales(
    world: Dict[str, Any],
) -> None:
    """§8.10: an oversized line batch fails before one write, and two smaller sales fit."""
    products = _offer_products(world["catalogs"], 20)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    for product_id in products:
        _seed_stock(world, product_id=product_id)
    oversized = [_line(product_id) for product_id in products] + [
        _line(products[index % len(products)], immediate=0, we_owe=1) for index in range(40)
    ]

    refused = _create(lines=oversized, buyerName="Buyer Bee", key="sale-big")

    assert_is_error(refused, "CONFLICT")
    assert _sale_rows(world["show_and_sells"]) == []
    assert _obligation_rows(world["show_and_sells"]) == []
    assert _movements(world["inventory"]) == []
    assert _marker_rows(world["show_and_sells"]) == []

    immediate_sale = _ok(_create(lines=[_line(product_id) for product_id in products], key="sale-part-1"))
    owed_sale = _ok(
        _create(
            lines=[_line(products[index % len(products)], immediate=0, we_owe=1) for index in range(3)],
            buyerName="Buyer Bee",
            version=2,
            key="sale-part-2",
        )
    )

    assert len(immediate_sale["obligations"]) == 0
    assert len(owed_sale["obligations"]) == 3
    assert len(_sale_rows(world["show_and_sells"])) == 2
    assert len(_movements(world["inventory"])) == 20, "the owed-only sale consumed no stock"


# --- SALE-M-01-03: the event's We Owe setting and mixed lines --------------------


def test_sale_m_01_03_an_event_that_did_not_enable_we_owe_refuses_an_owed_quantity(
    world: Dict[str, Any],
) -> None:
    """SALE-M-01-03: We Owe is the event's choice, and a sale does not make it again."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT, we_owe_enabled=False)
    _seed_stock(world)

    refused = _create(lines=[_line(PRODUCT, immediate=1, we_owe=2), _line(OTHER_PRODUCT, immediate=0, we_owe=1)])

    error = assert_is_error(refused, "CONFLICT")
    assert PRODUCT in error["message"] and OTHER_PRODUCT in error["message"]
    assert _obligation_rows(world["show_and_sells"]) == []
    assert _sale_rows(world["show_and_sells"]) == []

    answer = _ok(_create(lines=[_line(PRODUCT, immediate=1, we_owe=0)], key="sale-2"))
    assert answer["obligations"] == []


def test_sale_m_01_03_mixed_lines_need_only_a_buyer_name_and_link_one_obligation_each(
    world: Dict[str, Any],
) -> None:
    """SALE-M-01-03: an obligation has no Account, so a name is enough — and is required."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world, physical=6)
    _seed_allocation(world["inventory"], ACTIVE_EVENT, OTHER_PRODUCT, allocated=4)
    _seed_balance(world["inventory"], OTHER_PRODUCT, physical=6)

    assert_is_error(_create(lines=[_line(PRODUCT, immediate=0, we_owe=2)]), "INVALID_INPUT")

    answer = _ok(
        _create(
            lines=[
                _line(PRODUCT, immediate=2, we_owe=1),
                _line(PRODUCT, immediate=1, we_owe=2),
                _line(OTHER_PRODUCT, immediate=0, we_owe=3),
            ],
            buyerName="  Buyer Bee  ",
        )
    )

    assert answer["sale"]["buyerName"] == "Buyer Bee"
    assert len(answer["obligations"]) == 3
    by_line = {obligation["lineItemId"]: obligation for obligation in answer["obligations"]}
    for line in answer["sale"]["lineItems"]:
        assert line[sm.LINE_ITEM_ID_ATTRIBUTE] in by_line
    assert [by_line[line[sm.LINE_ITEM_ID_ATTRIBUTE]]["originalQty"] for line in answer["sale"]["lineItems"]] == [
        1,
        2,
        3,
    ]
    assert all(o["buyerName"] == "Buyer Bee" for o in answer["obligations"])

    sold = _stored_allocation(world["inventory"], ACTIVE_EVENT, PRODUCT)
    assert sold is not None and sold[inv.SOLD_QTY] == 3, "one allocation serves several lines of one product"
    assert _stored_allocation(world["inventory"], ACTIVE_EVENT, OTHER_PRODUCT)[inv.SOLD_QTY] == 0
    assert _stored_balance(world["inventory"], OTHER_PRODUCT)[inv.KERNEL_PHYSICAL_QTY] == 6


# --- SALE-M-01-04: payment methods and server-derived snapshots ------------------


def test_sale_m_01_04_other_needs_its_details_and_only_active_methods_of_this_unit_are_sold(
    world: Dict[str, Any],
) -> None:
    """AC-20, AC-22, AUTH-U-05: the method vocabulary is the Unit's and Other explains itself."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)
    _method(world["units"])

    no_details = assert_is_error(_create(paymentMethodCode="OTHER"), "INVALID_INPUT")
    assert "paymentMethod.otherDetails is required" in no_details["message"]
    assert_is_error(_create(paymentMethodCode="CASH", otherDetails="paid at the door"), "INVALID_INPUT")
    assert_is_error(_create(paymentMethodCode="CASH_LIKE"), "INVALID_INPUT")
    assert_is_error(_create(paymentMethodCode="CUSTOM:pm-nope"), "NOT_FOUND")
    assert_is_error(_create(paymentMethodCode="OTHER", otherDetails="x" * 251), "INVALID_INPUT")

    other = _ok(_create(paymentMethodCode="OTHER", otherDetails="paid half at the door", key="sale-other"))
    assert other["sale"]["paymentMethodSnapshot"]["otherDetails"] == "paid half at the door"
    assert other["sale"]["expectedCashCents"] == 0

    custom = _ok(_create(paymentMethodCode=f"CUSTOM:{WISE_METHOD_ID}", version=2, key="sale-wise"))
    assert custom["sale"]["paymentMethodSnapshot"] == {
        "methodCode": f"CUSTOM:{WISE_METHOD_ID}",
        "displayName": "Wise Transfer",
        "otherDetails": None,
    }
    assert custom["sale"]["expectedCashCents"] == 0

    _method(world["units"], is_active=False)
    retired = _create(paymentMethodCode=f"CUSTOM:{WISE_METHOD_ID}", version=3, key="sale-retired-again")
    error = assert_is_error(retired, "CONFLICT")
    assert "no longer available" in error["message"]
    assert len(_sale_rows(world["show_and_sells"])) == 2


def test_sale_m_01_04_name_price_subtotal_and_total_come_from_the_catalog(world: Dict[str, Any]) -> None:
    """SALE-M-01-04, AC-19: a caller that sends its own numbers is not trusted by the handler."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)

    answer = _ok(
        _create(
            lines=[
                {
                    "productId": PRODUCT,
                    "immediateQty": 2,
                    "weOweQty": 0,
                    "unitPriceCentsSnapshot": 1,
                    "productNameSnapshot": "Free Kernels",
                    "subtotalCents": 2,
                    "totalCents": 2,
                }
            ]
        )
    )

    line = answer["sale"]["lineItems"][0]
    assert line[sm.UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE] == PRICE_CENTS
    assert line[sm.PRODUCT_NAME_SNAPSHOT_ATTRIBUTE] == "Caramel 1"
    assert line[sm.SUBTOTAL_CENTS_ATTRIBUTE] == 1000
    assert answer["sale"]["totalCents"] == 1000
    stripped = sm.normalize_sale_lines(
        [{"productId": PRODUCT, "immediateQty": 1, "weOweQty": 0, "unitPriceCentsSnapshot": 1}]
    )[0]
    assert sm.UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE not in stripped, "the accepted input never carries a price at all"

    outside = assert_is_error(_create(lines=[_line("CATALOG#other#prod-9")], key="sale-2", version=2), "INVALID_INPUT")
    assert "catalog" in outside["message"]
    assert len(_sale_rows(world["show_and_sells"])) == 1


# --- SALE-M-01-05: a reopened event records a draft, and retries do not double ----


def test_sale_m_01_05_a_reopened_sale_is_a_draft_that_moves_no_stock(world: Dict[str, Any]) -> None:
    """§8.6, SALE-M-01-05: the entry is recorded, its stock effect belongs to re-finalization."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT, status=ssm.STATUS_REOPENED, product_ids=[OTHER_PRODUCT])
    _seed_stock(world)
    _seed_allocation(world["inventory"], ACTIVE_EVENT, OTHER_PRODUCT, allocated=4)

    answer = _ok(_create(lines=[_line(PRODUCT, immediate=2, we_owe=1)], buyerName="Buyer Bee"))

    assert answer["draftOnly"] is True
    assert answer["allocations"] == [] and answer["inventoryPositions"] == [] and answer["warnings"] == []
    assert answer["obligations"] == [], "only the draft sale is written; its obligations arrive at re-finalization"
    assert _stored_allocation(world["inventory"], ACTIVE_EVENT)[inv.SOLD_QTY] == 0
    assert _stored_balance(world["inventory"])[inv.KERNEL_PHYSICAL_QTY] == 4
    assert _movements(world["inventory"]) == []
    event = _stored_event(world["show_and_sells"])
    assert (event[ssm.VERSION_ATTRIBUTE], sorted(event[ssm.PRODUCT_IDS_ATTRIBUTE])) == (
        2,
        sorted([PRODUCT, OTHER_PRODUCT]),
    )
    assert event[ssm.ALLOCATION_DRAFT_ATTRIBUTE] == {PRODUCT: 0}, (
        "the zero baseline is for the newly referenced product only: a product the event "
        "already held keeps its approved allocation, and stamping 0 would tell "
        "re-finalization the Kernel reduced it"
    )
    assert OTHER_PRODUCT not in event[ssm.ALLOCATION_DRAFT_ATTRIBUTE]


def test_sale_m_01_05_a_retry_cannot_create_two_sale_ids_or_double_the_stock(world: Dict[str, Any]) -> None:
    """IDEM: the same key replays one answer, and a fresh key is a separate sale."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)

    first = _ok(_create(lines=[_line(PRODUCT, immediate=1, we_owe=1)], buyerName="Buyer Bee", key="sale-1"))
    assert first["priorRevision"] is None, "a create had no previous revision to carry"
    replay = _ok(_create(lines=[_line(PRODUCT, immediate=1, we_owe=1)], buyerName="Buyer Bee", key="sale-1"))

    assert replay == first
    assert len(_sale_rows(world["show_and_sells"])) == 1
    assert len(_obligation_rows(world["show_and_sells"])) == 1
    assert len(_movements(world["inventory"])) == 1
    assert _stored_allocation(world["inventory"], ACTIVE_EVENT)[inv.SOLD_QTY] == 1
    assert _stored_balance(world["inventory"])[inv.VERSION_ATTRIBUTE] == 2
    assert _stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 2

    second = _ok(_create(lines=[_line(PRODUCT, immediate=1)], version=2, key="sale-2"))
    assert second["sale"]["saleId"] != first["sale"]["saleId"]
    assert _stored_allocation(world["inventory"], ACTIVE_EVENT)[inv.SOLD_QTY] == 2

    mismatched = _create(lines=[_line(PRODUCT, immediate=3)], key="sale-1")
    assert_is_error(mismatched, "INVALID_INPUT"), "the same key with a different body is refused, not re-run"


# --- SALE-M-02-01: correcting a line by its stable identity ----------------------


def test_sale_m_02_01_a_correction_addresses_a_line_by_its_id_and_archives_the_prior_revision(
    world: Dict[str, Any],
) -> None:
    """SALE-M-02-01, AC-23: the previous revision survives whole, and only deltas move."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world, physical=6)
    created = _ok(
        _create(lines=[_line(PRODUCT, immediate=3, we_owe=1)], buyerName="Buyer Bee", buyerEmail="bee@example.test")
    )
    sale_id = created["sale"]["saleId"]
    line_id = created["sale"]["lineItems"][0][sm.LINE_ITEM_ID_ATTRIBUTE]
    before = dict(_stored_sale(world["show_and_sells"], ACTIVE_EVENT, sale_id) or {})

    answer = _ok(
        _correct(
            sale_id=sale_id, lines=[{"lineItemId": line_id, "productId": PRODUCT, "immediateQty": 1, "weOweQty": 1}]
        )
    )

    assert answer["sale"]["revision"] == 2
    assert answer["sale"]["lineItems"][0][sm.LINE_ITEM_ID_ATTRIBUTE] == line_id
    assert answer["sale"]["lineItems"][0][sm.IMMEDIATE_QTY_ATTRIBUTE] == 1
    assert answer["sale"]["totalCents"] == 1000, "one Kernel immediate, one owed"

    prior = answer["priorRevision"]
    assert prior is not None, "§7.1: the correction's answer includes the prior revision"
    assert prior[sm.REVISION_ATTRIBUTE] == 1
    assert prior[sm.LINE_ITEMS_ATTRIBUTE] == [sm.sale_line_payload(line) for line in before[sm.LINE_ITEMS_ATTRIBUTE]]
    assert prior[sm.TOTAL_CENTS_ATTRIBUTE] == int(before[sm.TOTAL_CENTS_ATTRIBUTE])
    assert prior[sm.PAYMENT_SNAPSHOT_ATTRIBUTE] == before[sm.PAYMENT_SNAPSHOT_ATTRIBUTE]
    assert prior[sm.BUYER_EMAIL_ATTRIBUTE] == "bee@example.test"
    assert prior[sm.SALE_AT_ATTRIBUTE] == before[sm.SALE_AT_ATTRIBUTE]
    assert prior[sm.STATUS_ATTRIBUTE] == sm.SALE_STATUS_ACTIVE
    assert prior["reason"] == "two boxes came back"
    assert prior["correctedByAccountId"] == AVERY

    revision = _stored_revision(world["show_and_sells"], ACTIVE_EVENT, sale_id, 1)
    assert revision is not None
    for attribute in (
        sm.LINE_ITEMS_ATTRIBUTE,
        sm.TOTAL_CENTS_ATTRIBUTE,
        sm.PAYMENT_SNAPSHOT_ATTRIBUTE,
        sm.BUYER_NAME_ATTRIBUTE,
        sm.BUYER_EMAIL_ATTRIBUTE,
        sm.SALE_AT_ATTRIBUTE,
        sm.STATUS_ATTRIBUTE,
        sm.REVISION_ATTRIBUTE,
        sm.CREATED_AT_ATTRIBUTE,
    ):
        assert revision[attribute] == before[attribute], f"the archived revision keeps {attribute} verbatim"
    assert revision["reason"] == "two boxes came back"
    assert revision["correctedByAccountId"] == AVERY
    assert revision[sm.UNIT_ID_ATTRIBUTE] == UNIT
    assert revision["sk"] == sm.sale_revision_sk(sale_id, 1)

    allocation = _stored_allocation(world["inventory"], ACTIVE_EVENT)
    assert allocation is not None and (allocation[inv.SOLD_QTY], allocation[inv.REMAINING_QTY]) == (1, 3)
    assert _stored_balance(world["inventory"])[inv.KERNEL_PHYSICAL_QTY] == 5, "one Kernel back on the shelf"
    movements = _movements(world["inventory"])
    assert len(movements) == 2
    reversal = [row for row in movements if row[inv.KERNEL_PHYSICAL_DELTA] == 2][0]
    assert reversal[inv.MOVEMENT_TYPE_ATTRIBUTE] == inv.EVENT_IMMEDIATE_SALE
    assert reversal[inv.ASSIGNED_DELTA] == 2
    assert reversal[inv.INVENTORY_VERSION_ATTRIBUTE] == _stored_balance(world["inventory"])[inv.VERSION_ATTRIBUTE]

    assert len(answer["obligations"]) == 1
    assert answer["obligations"][0]["version"] == 1, "an unchanged obligation is not rewritten"


def test_sale_m_02_01_an_unaffected_product_writes_no_stock_and_a_misaddressed_line_is_not_found(
    world: Dict[str, Any],
) -> None:
    """§8.6.1 step 2: a line whose immediate quantity did not move spends nothing."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)
    _seed_balance(world["inventory"], OTHER_PRODUCT, physical=4)
    _seed_allocation(world["inventory"], ACTIVE_EVENT, OTHER_PRODUCT, allocated=4)
    created = _ok(_create(lines=[_line(PRODUCT, immediate=1), _line(OTHER_PRODUCT, immediate=2)]))
    sale_id = created["sale"]["saleId"]
    lines = {line[sm.PRODUCT_ID_ATTRIBUTE]: line[sm.LINE_ITEM_ID_ATTRIBUTE] for line in created["sale"]["lineItems"]}

    answer = _ok(
        _correct(
            sale_id=sale_id,
            lines=[
                {"lineItemId": lines[PRODUCT], "productId": PRODUCT, "immediateQty": 1, "weOweQty": 0},
                {"lineItemId": lines[OTHER_PRODUCT], "productId": OTHER_PRODUCT, "immediateQty": 1, "weOweQty": 1},
            ],
            buyerName="Buyer Bee",
        )
    )

    assert (_stored_balance(world["inventory"], OTHER_PRODUCT) or {})[inv.KERNEL_PHYSICAL_QTY] == 3
    assert (_stored_balance(world["inventory"], PRODUCT) or {})[inv.KERNEL_PHYSICAL_QTY] == 3, "untouched"
    assert (_stored_allocation(world["inventory"], ACTIVE_EVENT, PRODUCT) or {})[inv.VERSION_ATTRIBUTE] == 2, (
        "the create left version 2; a correction that did not move the product did not rewrite the row"
    )
    assert len(_movements(world["inventory"])) == 3, "two create movements and one correction reversal"
    assert answer["sale"]["totalCents"] == 1500

    wrong = _correct(
        sale_id=sale_id,
        lines=[{"lineItemId": "LINE#not-mine", "productId": PRODUCT, "immediateQty": 1, "weOweQty": 0}],
        revision=2,
        version=3,
        key="correct-2",
    )
    assert_is_error(wrong, "NOT_FOUND")
    assert answer["sale"]["lineItems"][0][sm.IMMEDIATE_QTY_ATTRIBUTE] == 1


def test_sale_m_02_01_a_correction_releases_only_the_reservation_above_the_new_remainder(
    world: Dict[str, Any],
) -> None:
    """§8.6.1 step 4: what no longer has anything owed under it is let go, in the same write."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world, physical=6)
    created = _ok(_create(lines=[_line(PRODUCT, immediate=1, we_owe=3)], buyerName="Buyer Bee"))
    sale_id = created["sale"]["saleId"]
    line_id = created["sale"]["lineItems"][0][sm.LINE_ITEM_ID_ATTRIBUTE]
    _seed_we_owe_state(world["show_and_sells"], world["inventory"], ACTIVE_EVENT, sale_id, reserved=2)

    answer = _ok(
        _correct(
            sale_id=sale_id,
            lines=[{"lineItemId": line_id, "productId": PRODUCT, "immediateQty": 1, "weOweQty": 1}],
        )
    )

    kept = [o for o in answer["obligations"] if o["status"] == sm.WE_OWE_STATUS_OPEN]
    assert len(kept) == 1
    assert (kept[0]["originalQty"], kept[0]["remainingQty"]) == (3, 1)
    assert kept[0]["reservedQty"] == 1, "two were reserved; only the one above the new remainder is released"
    balance = _stored_balance(world["inventory"])
    assert balance[inv.SOLD_IN_POSSESSION_QTY] == 1
    assert balance[inv.KERNEL_PHYSICAL_QTY] == 5, "the immediate quantity did not move, so no stock did"
    releases = [row for row in _movements(world["inventory"]) if row[inv.MOVEMENT_TYPE_ATTRIBUTE] == inv.WE_OWE_RELEASE]
    assert len(releases) == 1
    assert releases[0][inv.SOLD_POSSESSION_DELTA] == -1
    assert releases[0][inv.WE_OWE_ID_ATTRIBUTE] == kept[0]["weOweId"], "the trail names whose reservation it released"


# --- SALE-M-02-02: a reopened correction defers its effects ----------------------


def test_sale_m_02_02_a_reopened_correction_defers_effects_and_adds_zero_baselines(world: Dict[str, Any]) -> None:
    """§8.6, SALE-M-02-02: new products join as zero baselines; the old content is immutable."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT, status=ssm.STATUS_REOPENED, product_ids=[PRODUCT])
    _seed_stock(world)
    _seed_balance(world["inventory"], OTHER_PRODUCT, physical=4)
    created = _ok(_create(lines=[_line(PRODUCT, immediate=2, we_owe=1)], buyerName="Buyer Bee"))
    sale_id = created["sale"]["saleId"]
    line_id = created["sale"]["lineItems"][0][sm.LINE_ITEM_ID_ATTRIBUTE]
    original = dict(_stored_sale(world["show_and_sells"], ACTIVE_EVENT, sale_id) or {})

    answer = _ok(
        _correct(
            sale_id=sale_id,
            lines=[
                {"lineItemId": line_id, "productId": PRODUCT, "immediateQty": 1, "weOweQty": 1},
                _line(OTHER_PRODUCT, immediate=1, we_owe=1),
            ],
        )
    )

    assert answer["draftOnly"] is True
    assert answer["allocations"] == [] and answer["inventoryPositions"] == []
    assert _stored_balance(world["inventory"])[inv.KERNEL_PHYSICAL_QTY] == 4
    assert (_stored_balance(world["inventory"], OTHER_PRODUCT) or {})[inv.KERNEL_PHYSICAL_QTY] == 4
    assert _movements(world["inventory"]) == []
    event = _stored_event(world["show_and_sells"])
    assert (event[ssm.VERSION_ATTRIBUTE], sorted(event[ssm.PRODUCT_IDS_ATTRIBUTE])) == (
        3,
        sorted([PRODUCT, OTHER_PRODUCT]),
    )
    assert event[ssm.ALLOCATION_DRAFT_ATTRIBUTE] == {OTHER_PRODUCT: 0}, (
        "only the product the sale newly references takes a zero baseline; PRODUCT was "
        "already on the event and its approved allocation stands"
    )
    assert answer["obligations"] == [], "a reopened correction writes no obligations; re-finalization replays the lines"
    assert len(_revision_rows(world["show_and_sells"])) == 1
    revision = _stored_revision(world["show_and_sells"], ACTIVE_EVENT, sale_id, 1)
    assert revision is not None
    assert revision[sm.LINE_ITEMS_ATTRIBUTE] == original[sm.LINE_ITEMS_ATTRIBUTE]
    assert revision[sm.TOTAL_CENTS_ATTRIBUTE] == original[sm.TOTAL_CENTS_ATTRIBUTE]


# --- SALE-M-02-03: omitted lines, supplemental lines, and the ceilings -----------


def test_sale_m_02_03_an_omitted_line_is_voided_and_a_new_line_adds_an_obligation(world: Dict[str, Any]) -> None:
    """§8.6.1: an omitted line closes as cancelled; a supplemental line owes its own."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)
    _seed_balance(world["inventory"], OTHER_PRODUCT, physical=4)
    _seed_allocation(world["inventory"], ACTIVE_EVENT, OTHER_PRODUCT, allocated=4)
    created = _ok(
        _create(
            lines=[_line(PRODUCT, immediate=1, we_owe=2), _line(OTHER_PRODUCT, immediate=1, we_owe=1)],
            buyerName="Buyer Bee",
        )
    )
    sale_id = created["sale"]["saleId"]
    kept = created["sale"]["lineItems"][0][sm.LINE_ITEM_ID_ATTRIBUTE]

    answer = _ok(
        _correct(
            sale_id=sale_id,
            lines=[
                {"lineItemId": kept, "productId": PRODUCT, "immediateQty": 1, "weOweQty": 1},
                _line(OTHER_PRODUCT, immediate=0, we_owe=3),
            ],
        )
    )

    closed = [o for o in answer["obligations"] if o["status"] == sm.WE_OWE_STATUS_CLOSED]
    assert len(closed) == 1
    assert closed[0]["lineItemId"] != kept
    assert closed[0]["closeReason"] == sm.WE_OWE_CLOSE_CANCELLED
    assert closed[0]["cancelledQty"] == 1
    assert closed[0]["remainingQty"] == 0
    supplementals = [o for o in answer["obligations"] if o["originalQty"] == 3]
    assert len(supplementals) == 1 and supplementals[0]["status"] == sm.WE_OWE_STATUS_OPEN
    assert len(answer["obligations"]) == 3, "the cancelled original survives; history is not edited away"

    assert (_stored_balance(world["inventory"], OTHER_PRODUCT) or {})[inv.KERNEL_PHYSICAL_QTY] == 4
    assert len(_movements(world["inventory"])) == 3


def test_sale_m_02_03_reducing_below_fulfilled_we_owe_and_a_stale_version_write_nothing(
    world: Dict[str, Any],
) -> None:
    """SALE-M-02-03: what the buyer already holds is not this correction's to take back."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)
    created = _ok(_create(lines=[_line(PRODUCT, immediate=1, we_owe=2)], buyerName="Buyer Bee"))
    sale_id = created["sale"]["saleId"]
    line_id = created["sale"]["lineItems"][0][sm.LINE_ITEM_ID_ATTRIBUTE]
    _seed_we_owe_state(world["show_and_sells"], world["inventory"], ACTIVE_EVENT, sale_id, fulfilled=1, reserved=1)
    before = dict(_stored_sale(world["show_and_sells"], ACTIVE_EVENT, sale_id) or {})

    below = _correct(
        sale_id=sale_id, lines=[{"lineItemId": line_id, "productId": PRODUCT, "immediateQty": 1, "weOweQty": 0}]
    )

    error = assert_is_error(below, "CONFLICT")
    assert "fulfilled" in error["message"]
    assert _revision_rows(world["show_and_sells"]) == []
    assert _obligation_rows(world["show_and_sells"])[0][sm.FULFILLED_QTY_ATTRIBUTE] == 1
    assert dict(_stored_sale(world["show_and_sells"], ACTIVE_EVENT, sale_id) or {}) == before

    upward = _correct(
        sale_id=sale_id,
        lines=[{"lineItemId": line_id, "productId": PRODUCT, "immediateQty": 1, "weOweQty": 5}],
        key="correct-up",
    )
    assert_is_error(upward, "INVALID_INPUT")
    stale_sale = _correct(sale_id=sale_id, lines=[_line(PRODUCT)], revision=9, version=2, key="correct-rev")
    assert_is_error(stale_sale, "CONFLICT")
    stale_event = _correct(sale_id=sale_id, lines=[_line(PRODUCT)], revision=1, version=7, key="correct-event")
    assert_is_error(stale_event, "CONFLICT")
    assert_is_error(_correct(sale_id="sale-nope", lines=[_line(PRODUCT)], key="correct-missing"), "NOT_FOUND")
    assert _revision_rows(world["show_and_sells"]) == []


# --- SALE-M-02-04: an unchanged method may be retired, and the guards apply ------


def test_sale_m_02_04_an_unchanged_correction_may_keep_a_retired_method(world: Dict[str, Any]) -> None:
    """PAY-06, SALE-M-02-04: restating history is not choosing a payment method again.

    The two halves sit one character apart in the input and worlds apart in the rule:
    naming the method the sale already carried is a restatement, so a method the Unit has
    since retired is still allowed, and the name it keeps is the one the sale recorded,
    never the row's current one; naming any other method is a fresh choice, and a retired
    method is not a choice a sale may be re-priced onto.
    """
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)
    _method(world["units"])
    created = _ok(_create(paymentMethodCode=f"CUSTOM:{WISE_METHOD_ID}", lines=[_line(PRODUCT, immediate=2)]))
    sale_id = created["sale"]["saleId"]
    line_id = created["sale"]["lineItems"][0][sm.LINE_ITEM_ID_ATTRIBUTE]
    corrected = [{"lineItemId": line_id, "productId": PRODUCT, "immediateQty": 1, "weOweQty": 0}]

    _rename_method(world["units"])
    kept = _ok(
        _correct(
            sale_id=sale_id,
            lines=corrected,
            paymentMethodCode=f"  custom:{WISE_METHOD_ID} ",
        )
    )
    assert kept["sale"]["paymentMethodSnapshot"] == {
        "methodCode": f"CUSTOM:{WISE_METHOD_ID}",
        "displayName": "Wise Transfer",
        "otherDetails": None,
    }, "the restatement keeps the sale's own snapshot; the renamed row cannot reach it"
    assert kept["sale"]["revision"] == 2

    _method(world["units"], payment_method_id="pm-wise-sale-retired", is_active=False)
    switched = _correct(
        sale_id=sale_id,
        lines=corrected,
        paymentMethodCode="CUSTOM:pm-wise-sale-retired",
        revision=2,
        version=3,
        key="correct-retired",
    )
    error = assert_is_error(switched, "CONFLICT")
    assert "no longer available for new sales" in error["message"], error["message"]
    assert _stored_sale(world["show_and_sells"], ACTIVE_EVENT, sale_id)[sm.REVISION_ATTRIBUTE] == 2


def test_sale_m_02_04_a_correction_that_changes_the_method_validates_it_as_a_fresh_choice(
    world: Dict[str, Any],
) -> None:
    """A new method is not a restatement: it is a fresh choice, validated as such.

    The restated path keeps the sale's recorded snapshot and carries no method-row
    condition, because nothing about the method changed; a correction that names a
    different method is the opposite case, and it must snapshot the new method's own
    display name and refuse to commit a method the Unit has since retired.
    """
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)
    _method(world["units"])
    _method(world["units"], payment_method_id="pm-wise-payout", display_name="Wise Payout")
    created = _ok(_create(paymentMethodCode=f"CUSTOM:{WISE_METHOD_ID}", lines=[_line(PRODUCT, immediate=2)]))
    sale_id = created["sale"]["saleId"]
    line_id = created["sale"]["lineItems"][0][sm.LINE_ITEM_ID_ATTRIBUTE]
    corrected = [{"lineItemId": line_id, "productId": PRODUCT, "immediateQty": 1, "weOweQty": 0}]

    switched = _ok(
        _correct(
            sale_id=sale_id,
            lines=corrected,
            paymentMethodCode="CUSTOM:pm-wise-payout",
            key="correct-fresh",
        )
    )

    assert switched["sale"]["paymentMethodSnapshot"] == {
        "methodCode": "CUSTOM:pm-wise-payout",
        "displayName": "Wise Payout",
        "otherDetails": None,
    }, "a changed method snapshots its own display name, never the sale's recorded one"
    assert switched["sale"]["revision"] == 2
    assert (
        _stored_sale(world["show_and_sells"], ACTIVE_EVENT, sale_id)[sm.PAYMENT_SNAPSHOT_ATTRIBUTE]["methodCode"]
        == "CUSTOM:pm-wise-payout"
    )


def test_sale_m_02_04_a_correction_may_edit_the_other_note_without_choosing_the_method_again(
    world: Dict[str, Any],
) -> None:
    """§4.3.1: the note rides the method it explains, and an omission keeps what is on file."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)
    created = _ok(
        _create(
            paymentMethodCode="OTHER",
            otherDetails="half cash, half a favor",
            lines=[_line(PRODUCT, immediate=2)],
        )
    )
    sale_id = created["sale"]["saleId"]
    line_id = created["sale"]["lineItems"][0][sm.LINE_ITEM_ID_ATTRIBUTE]
    corrected = [{"lineItemId": line_id, "productId": PRODUCT, "immediateQty": 1, "weOweQty": 0}]

    edited = _ok(_correct(sale_id=sale_id, lines=corrected, otherDetails="cash arrived the next morning"))
    assert edited["sale"]["paymentMethodSnapshot"] == {
        "methodCode": "OTHER",
        "displayName": "Other",
        "otherDetails": "cash arrived the next morning",
    }

    kept = _ok(
        _correct(
            sale_id=sale_id,
            lines=[{"lineItemId": line_id, "productId": PRODUCT, "immediateQty": 1, "weOweQty": 0}],
            revision=2,
            version=3,
            key="correct-note-keep",
        )
    )
    assert kept["sale"]["paymentMethodSnapshot"]["otherDetails"] == "cash arrived the next morning", (
        "an omitted note keeps the one on file, like every other omitted field"
    )


def test_sale_m_02_04_a_note_on_a_sale_that_is_not_other_is_refused_either_way(world: Dict[str, Any]) -> None:
    """§4.3.3: otherDetails exists only for the Other method, said with or without the code."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)
    created = _ok(_create(paymentMethodCode="CASH", lines=[_line(PRODUCT, immediate=2)]))
    sale_id = created["sale"]["saleId"]
    line_id = created["sale"]["lineItems"][0][sm.LINE_ITEM_ID_ATTRIBUTE]
    corrected = [{"lineItemId": line_id, "productId": PRODUCT, "immediateQty": 1, "weOweQty": 0}]

    without_code = _correct(sale_id=sale_id, lines=corrected, otherDetails="card on the side", key="correct-note-1")
    assert_is_error(without_code, "INVALID_INPUT")
    with_code = _correct(
        sale_id=sale_id,
        lines=corrected,
        paymentMethodCode="CASH",
        otherDetails="card on the side",
        key="correct-note-2",
    )
    assert_is_error(with_code, "INVALID_INPUT")
    assert _stored_sale(world["show_and_sells"], ACTIVE_EVENT, sale_id)[sm.REVISION_ATTRIBUTE] == 1


def test_sale_m_02_01_a_correction_cannot_move_a_line_to_another_product(world: Dict[str, Any]) -> None:
    """§8.6.1: a line is its product's new quantity; a product change is an omission plus a supplemental."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)
    _seed_balance(world["inventory"], OTHER_PRODUCT, physical=4)
    _seed_allocation(world["inventory"], ACTIVE_EVENT, OTHER_PRODUCT, allocated=4)
    created = _ok(_create(lines=[_line(PRODUCT, immediate=1)]))
    sale_id = created["sale"]["saleId"]
    line_id = created["sale"]["lineItems"][0][sm.LINE_ITEM_ID_ATTRIBUTE]

    moved = _correct(
        sale_id=sale_id,
        lines=[{"lineItemId": line_id, "productId": OTHER_PRODUCT, "immediateQty": 1, "weOweQty": 0}],
    )

    error = assert_is_error(moved, "INVALID_INPUT")
    assert "keeps the product it sold" in error["message"]
    assert _stored_sale(world["show_and_sells"], ACTIVE_EVENT, sale_id)[sm.REVISION_ATTRIBUTE] == 1
    assert _revision_rows(world["show_and_sells"]) == []
    assert len(_movements(world["inventory"])) == 1, "the refusal wrote nothing"


def test_sale_m_02_04_a_correction_is_guarded_by_tenancy_replay_and_the_buyer_rule(
    world: Dict[str, Any],
) -> None:
    """AUTH-U, IDEM: the same guards as the create, on the sale's own revision."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)
    created = _ok(_create(lines=[_line(PRODUCT, immediate=2)], buyerPhone="303-555-0100"))
    sale_id = created["sale"]["saleId"]
    line_id = created["sale"]["lineItems"][0][sm.LINE_ITEM_ID_ATTRIBUTE]
    corrected = [
        {"lineItemId": line_id, "productId": PRODUCT, "immediateQty": 1, "weOweQty": 0},
        _line(PRODUCT, immediate=0, we_owe=1),
    ]

    for persona in ("Blake", "Devon", "Taylor", "Riley", "Emery"):
        assert_is_error(
            _correct(caller=persona, sale_id=sale_id, lines=corrected, key=f"correct-{persona}"), "NOT_FOUND"
        )
    assert_is_error(_correct(caller=None, sale_id=sale_id, lines=corrected), "UNAUTHORIZED")
    (
        assert_is_error(_correct(sale_id=sale_id, lines=corrected), "INVALID_INPUT"),
        "the new line owes, so a name is required",
    )
    assert_is_error(
        _correct(sale_id=sale_id, lines=corrected, buyerName="Buyer Bee", buyerPhone="x" * 41), "INVALID_INPUT"
    )

    answer = _ok(_correct(sale_id=sale_id, lines=corrected, buyerName="Buyer Bee"))
    assert answer["sale"]["buyerName"] == "Buyer Bee"
    assert answer["sale"]["buyerPhone"] == "303-555-0100", "an omitted contact field keeps the one on file"

    replay = _ok(_correct(sale_id=sale_id, lines=corrected, buyerName="Buyer Bee"))
    assert replay == answer
    assert len(_revision_rows(world["show_and_sells"])) == 1
    assert _stored_sale(world["show_and_sells"], ACTIVE_EVENT, sale_id)[sm.REVISION_ATTRIBUTE] == 2


# --- SALE-M-03-01: voiding a whole sale ----------------------------------------


def test_sale_m_03_01_voiding_a_sale_hands_every_unit_back_and_closes_each_obligation(
    world: Dict[str, Any],
) -> None:
    """SALE-M-03-01, AC-24: the stock, the obligations and the sales pool all reverse together."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world, physical=6)
    _seed_balance(world["inventory"], OTHER_PRODUCT, physical=6)
    _seed_allocation(world["inventory"], ACTIVE_EVENT, OTHER_PRODUCT, allocated=4)
    created = _ok(
        _create(
            lines=[_line(PRODUCT, immediate=2, we_owe=2), _line(OTHER_PRODUCT, immediate=1)],
            buyerName="Buyer Bee",
        )
    )
    sale_id = created["sale"]["saleId"]

    answer = _ok(_void(sale_id=sale_id))

    assert answer["sale"]["status"] == sm.SALE_STATUS_VOIDED
    assert answer["sale"]["revision"] == 2
    assert answer["sale"]["voidedByAccountId"] == AVERY
    assert answer["sale"]["voidedAt"]
    assert answer["sale"]["lineItems"] == created["sale"]["lineItems"], "a void never rewrites the lines"
    prior = answer["priorRevision"]
    assert prior is not None, "the void archives the revision it replaced, and the answer carries it"
    assert prior[sm.REVISION_ATTRIBUTE] == 1
    assert prior[sm.STATUS_ATTRIBUTE] == sm.SALE_STATUS_ACTIVE
    assert prior[sm.LINE_ITEMS_ATTRIBUTE] == created["sale"]["lineItems"]
    assert prior["reason"] == "the buyer changed their mind"
    assert all(o["status"] == sm.WE_OWE_STATUS_CLOSED for o in answer["obligations"])
    assert all(o["closeReason"] == sm.WE_OWE_CLOSE_CANCELLED for o in answer["obligations"])

    allocation = _stored_allocation(world["inventory"], ACTIVE_EVENT)
    assert allocation is not None and (allocation[inv.SOLD_QTY], allocation[inv.REMAINING_QTY]) == (0, 4)
    assert _stored_balance(world["inventory"])[inv.KERNEL_PHYSICAL_QTY] == 6
    assert (_stored_balance(world["inventory"], OTHER_PRODUCT) or {})[inv.KERNEL_PHYSICAL_QTY] == 6
    reversals = [row for row in _movements(world["inventory"]) if row[inv.KERNEL_PHYSICAL_DELTA] > 0]
    assert len(reversals) == 2
    assert {row[inv.PRODUCT_ID_ATTRIBUTE] for row in reversals} == {PRODUCT, OTHER_PRODUCT}
    assert len(_revision_rows(world["show_and_sells"])) == 1
    assert sorted(_stored_event(world["show_and_sells"])[ssm.PRODUCT_IDS_ATTRIBUTE]) == sorted([PRODUCT, OTHER_PRODUCT])
    assert _stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 3


def test_sale_m_03_01_line_level_voiding_is_a_correction_that_omits_the_line(world: Dict[str, Any]) -> None:
    """SALE-M-03-01: a whole-sale void is the only void, so one line goes by correction."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)
    _seed_balance(world["inventory"], OTHER_PRODUCT, physical=4)
    _seed_allocation(world["inventory"], ACTIVE_EVENT, OTHER_PRODUCT, allocated=4)
    created = _ok(_create(lines=[_line(PRODUCT, immediate=1), _line(OTHER_PRODUCT, immediate=1)]))
    sale_id = created["sale"]["saleId"]
    kept = created["sale"]["lineItems"][0][sm.LINE_ITEM_ID_ATTRIBUTE]

    answer = _ok(
        _correct(sale_id=sale_id, lines=[{"lineItemId": kept, "productId": PRODUCT, "immediateQty": 1, "weOweQty": 0}])
    )

    assert answer["sale"]["status"] == sm.SALE_STATUS_ACTIVE
    assert len(answer["sale"]["lineItems"]) == 1
    positions = {position["productId"] for position in answer["inventoryPositions"]}
    assert positions == {PRODUCT, OTHER_PRODUCT}, (
        "the omitted line's handback is one of this write's effects, and the answer names it "
        "in the position and allocation it moved"
    )
    allocations = {allocation["productId"] for allocation in answer["allocations"]}
    assert allocations == {PRODUCT, OTHER_PRODUCT}
    assert (_stored_allocation(world["inventory"], ACTIVE_EVENT, OTHER_PRODUCT) or {})[inv.SOLD_QTY] == 0
    assert (_stored_balance(world["inventory"], OTHER_PRODUCT) or {})[inv.KERNEL_PHYSICAL_QTY] == 4


def test_sale_m_03_01_a_void_of_a_draft_sale_marks_the_row_and_defers_the_stock(world: Dict[str, Any]) -> None:
    """§4.3.2 read with §8.6: a REOPENED event may void, and the handback waits for re-finalization."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT, status=ssm.STATUS_REOPENED, product_ids=[PRODUCT])
    _seed_stock(world)
    created = _ok(_create(lines=[_line(PRODUCT, immediate=2, we_owe=1)], buyerName="Buyer Bee"))
    sale_id = created["sale"]["saleId"]

    answer = _ok(_void(sale_id=sale_id, version=2))

    assert answer["draftOnly"] is True
    assert answer["sale"]["status"] == sm.SALE_STATUS_VOIDED
    assert answer["sale"]["revision"] == 2
    assert answer["allocations"] == [] and answer["inventoryPositions"] == []
    assert answer["obligations"] == [], "the draft sale never wrote obligations, so none close"
    stored = _stored_sale(world["show_and_sells"], ACTIVE_EVENT, sale_id) or {}
    assert stored[sm.STATUS_ATTRIBUTE] == sm.SALE_STATUS_VOIDED
    assert stored[sm.VOIDED_BY_ATTRIBUTE] == AVERY
    assert _stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 3
    assert _movements(world["inventory"]) == []
    assert _stored_balance(world["inventory"])[inv.KERNEL_PHYSICAL_QTY] == 4
    revision = _stored_revision(world["show_and_sells"], ACTIVE_EVENT, sale_id, 1)
    assert revision is not None, "the void archives the draft it replaced, as a correction would"


# --- SALE-M-03-02: fulfilled We Owe is protected, and no reservation survives ----


def test_sale_m_03_02_a_fulfilled_obligation_cannot_be_voided_as_unfulfilled(world: Dict[str, Any]) -> None:
    """SALE-M-03-02: stock the Unit no longer has cannot be handed back by rewriting history."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)
    created = _ok(_create(lines=[_line(PRODUCT, immediate=1, we_owe=2)], buyerName="Buyer Bee"))
    sale_id = created["sale"]["saleId"]
    _seed_we_owe_state(world["show_and_sells"], world["inventory"], ACTIVE_EVENT, sale_id, fulfilled=1)

    refused = _void(sale_id=sale_id)

    error = assert_is_error(refused, "CONFLICT")
    assert "fulfilled" in error["message"]
    assert _stored_sale(world["show_and_sells"], ACTIVE_EVENT, sale_id)[sm.STATUS_ATTRIBUTE] == sm.SALE_STATUS_ACTIVE
    assert _revision_rows(world["show_and_sells"]) == []
    assert len(_movements(world["inventory"])) == 1, "the create's own movement; the refusal wrote nothing"
    assert _stored_balance(world["inventory"])[inv.KERNEL_PHYSICAL_QTY] == 3


def test_sale_m_03_02_no_reservation_survives_a_void_that_takes_the_quantity_back(world: Dict[str, Any]) -> None:
    """SALE-M-03-02: a corrected remainder of zero releases every unit a reservation was holding."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world, physical=6)
    created = _ok(_create(lines=[_line(PRODUCT, immediate=1, we_owe=3)], buyerName="Buyer Bee"))
    sale_id = created["sale"]["saleId"]
    _seed_we_owe_state(world["show_and_sells"], world["inventory"], ACTIVE_EVENT, sale_id, reserved=2)

    answer = _ok(_void(sale_id=sale_id))

    obligation = answer["obligations"][0]
    assert (obligation["reservedQty"], obligation["remainingQty"], obligation["uncoveredQty"]) == (0, 0, 0)
    assert obligation["status"] == sm.WE_OWE_STATUS_CLOSED
    assert obligation["closeReason"] == sm.WE_OWE_CLOSE_CANCELLED
    balance = _stored_balance(world["inventory"])
    assert balance is not None
    assert (balance[inv.KERNEL_PHYSICAL_QTY], balance[inv.SOLD_IN_POSSESSION_QTY]) == (6, 0)
    assert balance[inv.VERSION_ATTRIBUTE] == 4, "one void balance write carries both the stock and the reservation"

    release = [row for row in _movements(world["inventory"]) if row[inv.MOVEMENT_TYPE_ATTRIBUTE] == inv.WE_OWE_RELEASE]
    assert len(release) == 1
    assert release[0][inv.SOLD_POSSESSION_DELTA] == -2
    assert release[0][inv.WE_OWE_ID_ATTRIBUTE] == obligation["weOweId"]
    assert release[0][inv.INVENTORY_VERSION_ATTRIBUTE] == 4


# --- SALE-M-03-03: the void's guards -------------------------------------------


def test_sale_m_03_03_a_void_is_guarded_by_tenancy_stale_versions_and_replay(world: Dict[str, Any]) -> None:
    """SALE-M-03-03: AUTH-U, VER-01 and IDEM on the whole-sale void."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _seed_stock(world)
    created = _ok(_create(lines=[_line(PRODUCT, immediate=2)]))
    sale_id = created["sale"]["saleId"]

    for persona in ("Blake", "Devon", "Taylor", "Riley", "Emery"):
        assert_is_error(_void(caller=persona, sale_id=sale_id, key=f"void-{persona}"), "NOT_FOUND")
    assert_is_error(_void(caller=None, sale_id=sale_id), "UNAUTHORIZED")
    # The sale's own revision token is part of the address: with no token there is no
    # revision to compare, so the request is refused rather than guessed at.
    line_id = created["sale"]["lineItems"][0][sm.LINE_ITEM_ID_ATTRIBUTE]
    no_sale_version = _call(
        CORRECT_SALE_FIELD,
        "Avery",
        mutation={
            "showAndSellId": ACTIVE_EVENT,
            "saleId": sale_id,
            "reason": "typo",
            "lineItems": [{"lineItemId": line_id, "productId": PRODUCT, "immediateQty": 2, "weOweQty": 0}],
            **_version(2),
            **_idem("correct-no-sale-version"),
        },
    )
    assert "saleVersion.expectedVersion is required" in assert_is_error(no_sale_version, "INVALID_INPUT")["message"]
    no_version_void = _call(
        VOID_SALE_FIELD,
        "Avery",
        mutation={
            "showAndSellId": ACTIVE_EVENT,
            "saleId": sale_id,
            "reason": "the buyer left",
            **_version(2),
            **_idem("void-no-sale-version"),
        },
    )
    assert "saleVersion.expectedVersion is required" in assert_is_error(no_version_void, "INVALID_INPUT")["message"]
    assert_is_error(_void(sale_id=sale_id, reason="   "), "INVALID_INPUT")
    assert_is_error(_void(sale_id=sale_id, revision=9), "CONFLICT")
    assert_is_error(_void(sale_id=sale_id, version=7, key="void-event"), "CONFLICT")
    assert_is_error(_void(sale_id="sale-nope", key="void-missing"), "NOT_FOUND")

    answer = _ok(_void(sale_id=sale_id))
    replay = _ok(_void(sale_id=sale_id))
    assert replay == answer
    assert len(_sale_rows(world["show_and_sells"])) == 1
    assert len(_revision_rows(world["show_and_sells"])) == 1
    assert len(_movements(world["inventory"])) == 2, "one sale movement and one void reversal"

    again = _void(sale_id=sale_id, key="void-fresh")
    error = assert_is_error(again, "CONFLICT")
    assert "already voided" in error["message"]
    assert _stored_balance(world["inventory"])[inv.KERNEL_PHYSICAL_QTY] == 4
