"""Wave 5.2 (§4.2.1, §4.2.3, §4.3.3) — the pooled-sale model, planner, and shared sale-entry rules.

The pure half of the Wave 5.2 surface. The resolver-level half — the transactions a
``createShowAndSellSale``/``correctShowAndSellSale``/``voidShowAndSellSale`` request
commits — is ``tests/unit/test_show_and_sell_sales.py``; what is proved here is the
arithmetic and the refusal rules on their own:

- §4.2.1's row builders: line arithmetic (subtotal is derived, never supplied), the
  buyer-name rule, the completeness of an archived prior revision, and the snapshot
  staying put when the catalog renames the product afterwards (PAY-06);
- §4.2.3's per-product stock planner: immediate-only and mixed lines, the last unit,
  positive and negative deltas, the unaffected line spending nothing, and the
  over-correction rollback;
- §4.3.3's shared entry rules: the state matrix, the sale-instant boundaries, the
  event's We Owe setting, and the payment rules a sale, a correction and a void all
  answer through ``sale_payment_decision``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional

import pytest

from src.utils import inventory_models as inv
from src.utils import sale_payment_models as spm
from src.utils import show_and_sell_models as ssm
from src.utils import show_and_sell_sale_models as sm
from src.utils import unit_payment_models as upm
from src.utils.errors import AppError, ErrorCode

EVENT = "SSE#model"
EVENT2 = "SSE#model-two"
CAMPAIGN = "uc-model"
UNIT = "unit-model"
PRODUCT = "CATALOG#model#prod-1"
OTHER_PRODUCT = "CATALOG#model#prod-2"
AVERY = "ACCOUNT#avery-fixture"
NOW = "2026-11-21T18:00:00+00:00"

PRICES = {
    PRODUCT: {
        sm.PRODUCT_NAME_SNAPSHOT_ATTRIBUTE: "Caramel Cremes",
        sm.UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE: 500,
    },
    OTHER_PRODUCT: {
        sm.PRODUCT_NAME_SNAPSHOT_ATTRIBUTE: "Triple Mints",
        sm.UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE: 650,
    },
}


def _event_row(
    *,
    status: str = ssm.STATUS_ACTIVE,
    start_at: str = "2026-11-21T17:00:00+00:00",
    end_at: str = "2026-11-21T21:00:00+00:00",
    we_owe_enabled: bool = True,
) -> Dict[str, Any]:
    return {
        ssm.SHOW_AND_SELL_ID_ATTRIBUTE: EVENT,
        ssm.STATUS_ATTRIBUTE: status,
        ssm.START_AT_ATTRIBUTE: start_at,
        ssm.END_AT_ATTRIBUTE: end_at,
        ssm.WE_OWE_ENABLED_ATTRIBUTE: we_owe_enabled,
        ssm.UNIT_ID_ATTRIBUTE: UNIT,
        ssm.UNIT_CAMPAIGN_ID_ATTRIBUTE: CAMPAIGN,
        ssm.VERSION_ATTRIBUTE: 1,
    }


def _line(
    *,
    product_id: str = PRODUCT,
    immediate: int = 2,
    we_owe: int = 0,
) -> Dict[str, Any]:
    return sm.snapshot_line_items([{"productId": product_id, "immediateQty": immediate, "weOweQty": we_owe}], PRICES)[0]


def _lines(*specs: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sm.snapshot_line_items(
        [
            {"productId": spec["product_id"], "immediateQty": spec["immediate"], "weOweQty": spec["we_owe"]}
            for spec in specs
        ],
        PRICES,
    )


def _snapshot(method_code: str = "CASH", display_name: str = "Cash") -> Dict[str, Any]:
    return {"methodCode": method_code, "displayName": display_name}


def _sale_item(
    line_items: List[Dict[str, Any]],
    *,
    sale_id: str = "sale-model-1",
    buyer_name: Optional[str] = "Buyer Bee",
    sale_at: str = "2026-11-21T18:30:00+00:00",
) -> Dict[str, Any]:
    return sm.build_show_and_sell_sale_item(
        show_and_sell_id=EVENT,
        unit_id=UNIT,
        unit_campaign_id=CAMPAIGN,
        sale_at=sale_at,
        entered_by_account_id=AVERY,
        line_items=line_items,
        payment_method_snapshot=_snapshot(),
        idempotency_key="key-model-1",
        now_iso=NOW,
        sale_id=sale_id,
        buyer_name=buyer_name,
    )


def _balance(*, physical: int = 10, sold_in_possession: int = 0, version: int = 1) -> Dict[str, Any]:
    return inv.build_inventory_balance_item(
        unit_campaign_id=CAMPAIGN,
        product_id=PRODUCT,
        kernel_physical_qty=physical,
        sold_in_possession_qty=sold_in_possession,
        council_on_order_qty=0,
        now_iso=NOW,
        version=version,
    )


def _allocation(
    *,
    allocated: int = 10,
    sold: int = 0,
    released: int = 0,
    version: int = 1,
    status: str = inv.ALLOCATION_OPEN,
) -> Dict[str, Any]:
    return inv.build_event_inventory_allocation_item(
        unit_campaign_id=CAMPAIGN,
        product_id=PRODUCT,
        show_and_sell_id=EVENT,
        start_at="2026-11-21T17:00:00+00:00",
        end_at="2026-11-21T21:00:00+00:00",
        allocated_qty=allocated,
        sold_qty=sold,
        released_qty=released,
        status=status,
        now_iso=NOW,
        version=version,
    )


def _decimalize(value: Any) -> Any:
    """A row as DynamoDB hands it back, with every number a ``Decimal``.

    The payload builders turn those into ``int`` because the SDL answers ``Int!`` and a
    ``Decimal`` cannot be stored in the idempotency marker a retry replays, so the
    conversion is worth testing against the shape a read really returns.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, Mapping):
        return {key: _decimalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decimalize(item) for item in value]
    return value


def _we_owe_item(*, quantity: int = 2, fulfilled: int = 0, reserved: int = 0, cancelled: int = 0) -> Dict[str, Any]:
    """One obligation, then moved to a mid-life state.

    A sale only ever creates an OPEN obligation with nothing fulfilled or reserved; the
    mid-life shapes are what Wave 4.4's reservation and fulfillment writes will produce,
    so a test seeds the row the way the read would find it rather than pretending a sale
    can start that way.
    """
    line = _line(immediate=0, we_owe=quantity)
    item = sm.build_we_owe_item(
        show_and_sell_id=EVENT,
        unit_campaign_id=CAMPAIGN,
        sale_id="sale-model-1",
        line_item=line,
        buyer_name="Buyer Bee",
        now_iso=NOW,
    )
    remaining = quantity - fulfilled - cancelled
    item[sm.FULFILLED_QTY_ATTRIBUTE] = fulfilled
    item[sm.CANCELLED_QTY_ATTRIBUTE] = cancelled
    item[sm.RESERVED_QTY_ATTRIBUTE] = reserved
    item[sm.REMAINING_QTY_ATTRIBUTE] = remaining
    item[sm.UNCOVERED_QTY_ATTRIBUTE] = remaining - reserved
    return item


# --- Line arithmetic and snapshots (§4.2.1) --------------------------------------


def test_line_subtotal_and_total_are_derived_from_price_and_quantity() -> None:
    """``subtotalCents`` is computed, and the total is the sum of the subtotals."""
    line = _line(immediate=2, we_owe=1)
    assert line[sm.SUBTOTAL_CENTS_ATTRIBUTE] == 1500
    line2 = _line(product_id=OTHER_PRODUCT, immediate=1, we_owe=0)
    assert line2[sm.SUBTOTAL_CENTS_ATTRIBUTE] == 650
    assert sm.sale_total_cents([line, line2]) == 2150
    assert sm.line_subtotal_cents(line) == 1500


def test_unit_price_cents_rounds_half_up_through_decimal_str() -> None:
    """Prices are decimal dollars; cents come out exact-cent, HALF_UP (§5.14)."""
    assert sm.unit_price_cents(Decimal("5.00")) == 500
    assert sm.unit_price_cents(5.005) == 501
    assert sm.unit_price_cents(Decimal("0.1")) == 10


def test_sale_line_input_rejects_zero_total_and_non_object_lines() -> None:
    with pytest.raises(AppError) as raised:
        sm.normalize_sale_lines([{"productId": PRODUCT, "immediateQty": 0, "weOweQty": 0}])
    assert raised.value.error_code == ErrorCode.INVALID_INPUT
    assert "greater than zero" in raised.value.message
    with pytest.raises(AppError) as raised:
        sm.normalize_sale_lines(["not-an-object"])
    assert raised.value.error_code == ErrorCode.INVALID_INPUT
    with pytest.raises(AppError):
        sm.normalize_sale_lines(None)
    with pytest.raises(AppError):
        sm.normalize_sale_lines([])


def test_correction_lines_address_one_line_once_and_may_name_a_new_line() -> None:
    lines = sm.normalize_correction_lines(
        [
            {"lineItemId": "LINE#1", "productId": PRODUCT, "immediateQty": 1, "weOweQty": 0},
            {"productId": OTHER_PRODUCT, "immediateQty": 0, "weOweQty": 2},
        ]
    )
    assert lines[0][sm.LINE_ITEM_ID_ATTRIBUTE] == "LINE#1"
    assert sm.LINE_ITEM_ID_ATTRIBUTE not in lines[1]
    with pytest.raises(AppError) as raised:
        sm.normalize_correction_lines(
            [
                {"lineItemId": "LINE#1", "productId": PRODUCT, "immediateQty": 1, "weOweQty": 0},
                {"lineItemId": "LINE#1", "productId": PRODUCT, "immediateQty": 2, "weOweQty": 0},
            ]
        )
    assert raised.value.details["subcode"] == sm.DUPLICATE_LINE_ITEM


def test_snapshot_line_items_refuses_a_product_the_catalog_does_not_offer() -> None:
    with pytest.raises(AppError) as raised:
        sm.snapshot_line_items([{"productId": "CATALOG#other#prod-9", "immediateQty": 1, "weOweQty": 0}], PRICES)
    assert "not a product of this campaign's catalog" in raised.value.message


def test_buyer_name_is_required_exactly_when_a_line_creates_we_owe() -> None:
    immediate_only = _lines({"product_id": PRODUCT, "immediate": 1, "we_owe": 0})
    mixed = _lines({"product_id": PRODUCT, "immediate": 1, "we_owe": 1})
    assert sm.buyer_name_required(immediate_only) is False
    assert sm.buyer_name_required(mixed) is True
    with pytest.raises(AppError) as raised:
        _sale_item(mixed, buyer_name=None)
    assert "buyerName" in raised.value.message
    # The correction path opts out of the requirement, because the row may already carry
    # the name this builder call is not being asked to supply.
    corrected = sm.build_show_and_sell_sale_item(
        show_and_sell_id=EVENT,
        unit_id=UNIT,
        unit_campaign_id=CAMPAIGN,
        sale_at="2026-11-21T18:30:00+00:00",
        entered_by_account_id=AVERY,
        line_items=mixed,
        payment_method_snapshot=_snapshot(),
        idempotency_key="key-model-3",
        now_iso=NOW,
        buyer_name=None,
        require_buyer_name=False,
    )
    assert sm.BUYER_NAME_ATTRIBUTE not in corrected


def test_the_buyer_name_takes_the_whole_200_character_limit() -> None:
    """API contract §3.4: "1-200 trimmed characters", so 200 is a name and 201 is not."""
    longest = "B" * sm.MAX_BUYER_NAME_LENGTH
    assert sm.MAX_BUYER_NAME_LENGTH == 200
    assert sm.normalize_buyer_name(f"  {longest}  ") == longest
    with pytest.raises(AppError) as raised:
        sm.normalize_buyer_name(longest + "y")
    assert "buyerName" in raised.value.message


def test_sale_builder_keeps_buyer_fields_absent_when_not_supplied() -> None:
    line_items = _lines({"product_id": PRODUCT, "immediate": 1, "we_owe": 0})
    item = sm.build_show_and_sell_sale_item(
        show_and_sell_id=EVENT,
        unit_id=UNIT,
        unit_campaign_id=CAMPAIGN,
        sale_at="2026-11-21T18:30:00+00:00",
        entered_by_account_id=AVERY,
        line_items=line_items,
        payment_method_snapshot=_snapshot(),
        idempotency_key="key-model-4",
        now_iso=NOW,
        buyer_name=None,
    )
    assert sm.BUYER_NAME_ATTRIBUTE not in item
    assert sm.BUYER_PHONE_ATTRIBUTE not in item
    assert sm.BUYER_EMAIL_ATTRIBUTE not in item
    assert sm.VOIDED_BY_ATTRIBUTE not in item
    assert sm.VOIDED_AT_ATTRIBUTE not in item
    assert sm.CREATED_AT_ATTRIBUTE in item, "a first revision carries its entry instant"
    assert sm.sale_invariant_violations(item) == []


def test_sale_invariants_enumerate_every_broken_term_at_once() -> None:
    item = _sale_item([_line(immediate=2, we_owe=1)])
    broken = dict(item)
    broken.pop(sm.TOTAL_CENTS_ATTRIBUTE)
    broken[sm.LINE_ITEMS_ATTRIBUTE] = [
        {
            sm.LINE_ITEM_ID_ATTRIBUTE: "L",
            sm.PRODUCT_ID_ATTRIBUTE: PRODUCT,
            sm.PRODUCT_NAME_SNAPSHOT_ATTRIBUTE: "Caramel Cremes",
            sm.UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE: 500,
            sm.IMMEDIATE_QTY_ATTRIBUTE: 0,
            sm.WE_OWE_QTY_ATTRIBUTE: 0,
            sm.SUBTOTAL_CENTS_ATTRIBUTE: 0,
        },
    ]
    violations = sm.sale_invariant_violations(broken)
    assert violations == ["totalCents is required"], "a missing term is answered before the arithmetic"

    line_broken = dict(item)
    line_broken[sm.LINE_ITEMS_ATTRIBUTE] = [
        {
            sm.LINE_ITEM_ID_ATTRIBUTE: "L",
            sm.PRODUCT_ID_ATTRIBUTE: PRODUCT,
            sm.PRODUCT_NAME_SNAPSHOT_ATTRIBUTE: "Caramel Cremes",
            sm.UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE: 500,
            sm.IMMEDIATE_QTY_ATTRIBUTE: 0,
            sm.WE_OWE_QTY_ATTRIBUTE: 0,
            sm.SUBTOTAL_CENTS_ATTRIBUTE: 0,
        },
    ]
    violations = sm.sale_invariant_violations(line_broken)
    assert any("immediateQty + weOweQty must be greater than zero" in v for v in violations)
    assert any("totalCents must equal the sum of the line subtotals" in v for v in violations)

    corrupt_total = dict(item)
    corrupt_total[sm.TOTAL_CENTS_ATTRIBUTE] = 1
    violations = sm.sale_invariant_violations(corrupt_total)
    assert violations == ["totalCents must equal the sum of the line subtotals"]

    no_created = dict(item)
    no_created[sm.REVISION_ATTRIBUTE] = 2
    no_created.pop(sm.CREATED_AT_ATTRIBUTE, None)
    assert "createdAt must be stored so a prior revision can be read as history" in sm.sale_invariant_violations(
        no_created
    )


def test_prior_revision_is_complete_and_immutable_shape() -> None:
    """§4.2.1: the archived revision carries everything the live row did, plus the why."""
    item = _sale_item([_line(immediate=2, we_owe=1)], sale_id="sale-model-2")
    revision = sm.build_sale_revision_item(item, corrected_by_account_id=AVERY, reason="wrong line", corrected_at=NOW)
    for attribute in (
        sm.LINE_ITEMS_ATTRIBUTE,
        sm.TOTAL_CENTS_ATTRIBUTE,
        sm.PAYMENT_SNAPSHOT_ATTRIBUTE,
        sm.BUYER_NAME_ATTRIBUTE,
        sm.SALE_AT_ATTRIBUTE,
        sm.STATUS_ATTRIBUTE,
        sm.REVISION_ATTRIBUTE,
    ):
        assert revision[attribute] == item[attribute], f"revision must carry {attribute} verbatim"
    assert revision["sk"] == sm.sale_revision_sk("sale-model-2", 1), "the child names its parent sale in its key"
    assert revision["correctedByAccountId"] == AVERY
    assert revision["correctedAt"] == NOW
    assert revision["reason"] == "wrong line"
    assert revision["entityType"] == sm.SALE_REVISION_ENTITY_TYPE
    assert sm.sale_invariant_violations(revision) == []


def test_snapshot_survives_a_later_catalog_rename_and_price_change() -> None:
    """PAY-06: the snapshot rides the sale; the catalog moving changes nothing on it."""
    line = _line(immediate=2)
    reordered = sm.catalog_price_table(
        [{"productId": PRODUCT, "productName": "Renamed Crunch", "price": Decimal("9.99")}]
    )
    assert reordered[PRODUCT][sm.PRODUCT_NAME_SNAPSHOT_ATTRIBUTE] == "Renamed Crunch"
    corrected = sm.reprice_line_item(line, 1, 1)
    assert corrected[sm.PRODUCT_NAME_SNAPSHOT_ATTRIBUTE] == "Caramel Cremes"
    assert corrected[sm.UNIT_PRICE_CENTS_SNAPSHOT_ATTRIBUTE] == 500
    assert corrected[sm.SUBTOTAL_CENTS_ATTRIBUTE] == 1000


def test_line_quantities_aggregate_per_product_across_lines() -> None:
    totals = sm.sale_line_quantities(
        [
            _line(product_id=PRODUCT, immediate=1, we_owe=0),
            _line(product_id=PRODUCT, immediate=2, we_owe=0),
            _line(product_id=OTHER_PRODUCT, immediate=0, we_owe=3),
        ]
    )
    assert totals == {PRODUCT: 3, OTHER_PRODUCT: 0}


# --- We Owe row invariants and correction targets (§4.2.1, §8.6.1) ----------------


def test_we_owe_row_carries_the_obligation_math() -> None:
    item = _we_owe_item(quantity=2)
    assert item[sm.ORIGINAL_QTY_ATTRIBUTE] == 2
    assert item[sm.FULFILLED_QTY_ATTRIBUTE] == 0
    assert item[sm.CANCELLED_QTY_ATTRIBUTE] == 0
    assert item[sm.RESERVED_QTY_ATTRIBUTE] == 0
    assert item[sm.REMAINING_QTY_ATTRIBUTE] == 2
    assert item[sm.UNCOVERED_QTY_ATTRIBUTE] == 2
    assert item[sm.STATUS_ATTRIBUTE] == sm.WE_OWE_STATUS_OPEN
    assert item[sm.VALUE_CENTS_SNAPSHOT_ATTRIBUTE] == 1000
    assert sm.we_owe_invariant_violations(item) == []


def test_we_owe_invariants_catch_broken_arithmetic_and_bad_states() -> None:
    item = _we_owe_item(quantity=2)
    bad_remaining = dict(item)
    bad_remaining[sm.REMAINING_QTY_ATTRIBUTE] = 1
    assert any("remainingQty must equal" in v for v in sm.we_owe_invariant_violations(bad_remaining))

    over_reserved = dict(item)
    over_reserved[sm.RESERVED_QTY_ATTRIBUTE] = 3
    assert any("reservedQty must stay between" in v for v in sm.we_owe_invariant_violations(over_reserved))

    closed_open = dict(item)
    closed_open[sm.STATUS_ATTRIBUTE] = sm.WE_OWE_STATUS_CLOSED
    assert any(
        "CLOSED requires remainingQty and reservedQty to be zero" in v
        for v in sm.we_owe_invariant_violations(closed_open)
    )

    missing = dict(item)
    missing.pop(sm.BUYER_NAME_ATTRIBUTE)
    assert any("buyerName is required" in v for v in sm.we_owe_invariant_violations(missing))


def test_correction_targets_take_back_only_the_unfulfilled_and_release_the_reservation() -> None:
    row = _we_owe_item(quantity=3, reserved=2)
    target = sm.we_owe_correction_targets(row, 1)
    assert target.cancelled_qty == 2
    assert target.remaining_qty == 1
    assert target.reserved_qty == 1
    assert target.uncovered_qty == 0
    assert target.release_qty == 1
    assert target.status == sm.WE_OWE_STATUS_OPEN
    assert target.close_reason is None
    assert target.changed is True

    closed = sm.we_owe_correction_targets(row, 0)
    assert closed.status == sm.WE_OWE_STATUS_CLOSED
    assert closed.close_reason == sm.WE_OWE_CLOSE_CANCELLED
    assert closed.release_qty == 2
    assert closed.remaining_qty == 0

    fulfilled_close = sm.we_owe_correction_targets(_we_owe_item(quantity=3, fulfilled=3), 3)
    assert fulfilled_close.status == sm.WE_OWE_STATUS_CLOSED
    assert fulfilled_close.close_reason == sm.WE_OWE_CLOSE_FULFILLED


def test_correction_targets_refuse_fulfilled_reductions_and_upward_rewrites() -> None:
    row = _we_owe_item(quantity=2, fulfilled=1, reserved=1)
    with pytest.raises(AppError) as raised:
        sm.we_owe_correction_targets(row, 0)
    assert raised.value.details["subcode"] == sm.FULFILLED_WE_OWE_PROTECTED
    with pytest.raises(AppError) as raised:
        sm.we_owe_correction_targets(row, 3)
    assert raised.value.error_code == ErrorCode.INVALID_INPUT


def test_unchanged_targets_write_nothing() -> None:
    row = _we_owe_item(quantity=2, reserved=1)
    target = sm.we_owe_correction_targets(row, 2)
    assert target.changed is False


# --- The shared per-product sale stock planner (§4.2.3) ----------------------------


def test_planner_sells_the_last_unit_and_moves_every_number() -> None:
    """Immediate-only: soldQty rises, remainingQty falls, physical falls, one movement each."""
    allocation = _allocation(allocated=10, sold=9)
    balance = _balance(physical=9)
    change = sm.plan_sale_stock(
        show_and_sell_id=EVENT,
        product_id=PRODUCT,
        immediate_qty=1,
        allocation=allocation,
        balance=balance,
    )
    assert change is not None
    assert change.new_sold_qty == 10
    assert change.new_remaining_qty == 0
    assert change.physical_delta == -1
    assert change.movement_type == inv.EVENT_IMMEDIATE_SALE
    assert change.immediate_delta == 1


def test_planner_mixed_line_consumes_only_the_immediate_quantity() -> None:
    """We Owe consumes no allocation: the owed quantity spends nothing at entry."""
    change = sm.plan_sale_stock(
        show_and_sell_id=EVENT,
        product_id=PRODUCT,
        immediate_qty=2,
        allocation=_allocation(allocated=10, sold=1),
        balance=_balance(physical=10),
    )
    assert change is not None and change.new_sold_qty == 3
    assert change.new_remaining_qty == 7


def test_planner_refuses_more_than_the_event_holds_and_a_missing_allocation() -> None:
    with pytest.raises(AppError) as raised:
        sm.plan_sale_stock(
            show_and_sell_id=EVENT,
            product_id=PRODUCT,
            immediate_qty=5,
            allocation=_allocation(allocated=4),
            balance=_balance(physical=10),
        )
    assert raised.value.details["subcode"] == sm.INSUFFICIENT_EVENT_STOCK
    with pytest.raises(AppError) as raised:
        sm.plan_sale_stock(
            show_and_sell_id=EVENT,
            product_id=PRODUCT,
            immediate_qty=1,
            allocation=None,
            balance=_balance(physical=10),
        )
    assert raised.value.details["subcode"] == sm.NO_EVENT_ALLOCATION


def test_planner_refuses_stock_the_shelf_cannot_cover_and_a_zero_answers_nothing() -> None:
    with pytest.raises(AppError) as raised:
        sm.plan_sale_stock(
            show_and_sell_id=EVENT,
            product_id=PRODUCT,
            immediate_qty=8,
            allocation=_allocation(allocated=10),
            balance=_balance(physical=5),
        )
    assert raised.value.details["subcode"] == sm.INSUFFICIENT_EVENT_STOCK
    # Units promised to reservations are not sellable at the table (§7).
    with pytest.raises(AppError):
        sm.plan_sale_stock(
            show_and_sell_id=EVENT,
            product_id=PRODUCT,
            immediate_qty=6,
            allocation=_allocation(allocated=10),
            balance=_balance(physical=10, sold_in_possession=5),
        )
    assert (
        sm.plan_sale_stock(
            show_and_sell_id=EVENT,
            product_id=PRODUCT,
            immediate_qty=0,
            allocation=_allocation(allocated=10),
            balance=_balance(physical=10),
        )
        is None
    )


def test_correction_applies_only_the_immediate_delta_either_direction() -> None:
    """§8.6.1 step 2: a negative delta hands units back; the unaffected line is None."""
    negative = sm.corrected_sale_stock_change(
        show_and_sell_id=EVENT,
        product_id=PRODUCT,
        immediate_delta=-2,
        allocation=_allocation(allocated=10, sold=4),
        balance=_balance(physical=6, version=3),
    )
    assert negative is not None
    assert negative.immediate_delta == -2
    assert negative.new_sold_qty == 2
    assert negative.new_remaining_qty == 8
    assert negative.physical_delta == 2
    assert negative.balance_version == 3

    positive = sm.corrected_sale_stock_change(
        show_and_sell_id=EVENT,
        product_id=PRODUCT,
        immediate_delta=3,
        allocation=_allocation(allocated=10, sold=1),
        balance=_balance(physical=10),
    )
    assert positive is not None and positive.new_sold_qty == 4

    assert (
        sm.corrected_sale_stock_change(
            show_and_sell_id=EVENT,
            product_id=PRODUCT,
            immediate_delta=0,
            allocation=_allocation(allocated=10, sold=1),
            balance=_balance(physical=10),
        )
        is None
    )


def test_correction_rolls_back_when_the_handback_exceeds_what_was_sold() -> None:
    """Forced rollback: refusing the over-correction is what keeps the row arithmetic true."""
    with pytest.raises(AppError) as raised:
        sm.corrected_sale_stock_change(
            show_and_sell_id=EVENT,
            product_id=PRODUCT,
            immediate_delta=-5,
            allocation=_allocation(allocated=10, sold=2),
            balance=_balance(physical=10),
        )
    assert raised.value.details["subcode"] == sm.INSUFFICIENT_EVENT_STOCK

    with pytest.raises(AppError) as raised:
        sm.corrected_sale_stock_change(
            show_and_sell_id=EVENT,
            product_id=PRODUCT,
            immediate_delta=-1,
            allocation=None,
            balance=_balance(physical=10),
        )
    assert raised.value.details["subcode"] == sm.INSUFFICIENT_EVENT_STOCK
    assert "holds 0 to sell" in raised.value.message


def test_write_actions_pin_every_version_and_refuse_to_overwrite() -> None:
    """The sale write shapes: every action conditions on the version this request read."""
    item = _sale_item([_line(immediate=1)])
    kind, put = sm.put_sale_action(item)
    assert kind == "Put"
    assert put["ConditionExpression"] == "attribute_not_exists(#pk) AND attribute_not_exists(#sk)"

    revision = sm.build_sale_revision_item(item, corrected_by_account_id=AVERY, reason="r", corrected_at=NOW)
    _, revision_put = sm.put_sale_revision_action(revision)
    assert revision_put["ConditionExpression"] == "attribute_not_exists(#pk) AND attribute_not_exists(#sk)"

    _, we_owe_put = sm.put_we_owe_action(_we_owe_item(quantity=1))
    assert we_owe_put["ConditionExpression"] == "attribute_not_exists(#pk) AND attribute_not_exists(#sk)"

    _, update = sm.sale_revision_update_action(
        show_and_sell_id=EVENT,
        sale_id="sale-model-1",
        expected_revision=1,
        sets={sm.STATUS_ATTRIBUTE: sm.SALE_STATUS_VOIDED, sm.BUYER_EMAIL_ATTRIBUTE: None},
        updated_at=NOW,
    )
    assert "#version = :expectedVersion" in update["ConditionExpression"]
    assert "REMOVE #buyerEmail" in update["UpdateExpression"]
    assert "SET #status" in update["UpdateExpression"]

    change = sm.SaleStockChange(
        product_id=PRODUCT,
        immediate_delta=2,
        new_sold_qty=2,
        new_remaining_qty=3,
        allocation_version=4,
        balance_version=5,
        physical_delta=-2,
        movement_type=inv.EVENT_IMMEDIATE_SALE,
    )
    _, allocation_update = sm.sale_allocation_action(change, _allocation(allocated=5), NOW)
    assert "#allocatedQty >= :guardSold" in allocation_update["ConditionExpression"]
    assert allocation_update["ExpressionAttributeValues"][":guardSold"] == {"N": "2"}

    _, event_update = sm.sale_event_action(
        show_and_sell_id=EVENT,
        expected_version=7,
        product_ids=[PRODUCT],
        updated_by_account_id=AVERY,
        updated_at=NOW,
    )
    assert "#status IN (:saleStateActive, :saleStateEnded)" in event_update["ConditionExpression"]

    _, movement = sm.sale_immediate_movement_action(
        event_row=_event_row(),
        sale_id="sale-model-1",
        change=change,
        actor_account_id=AVERY,
        occurred_at=NOW,
        idempotency_key="key-model-5",
        inventory_version=6,
    )
    assert movement["Item"]["movementType"] == {"S": inv.EVENT_IMMEDIATE_SALE}
    assert movement["Item"]["saleId"] == {"S": "sale-model-1"}
    assert movement["Item"]["inventoryVersion"] == {"N": "6"}

    _, release = sm.we_owe_release_movement_action(
        unit_campaign_id=CAMPAIGN,
        product_id=PRODUCT,
        we_owe_id="we-owe-model-1",
        release_qty=2,
        inventory_version=6,
        actor_account_id=AVERY,
        occurred_at=NOW,
        idempotency_key="key-model-6",
    )
    assert release["Item"]["movementType"] == {"S": inv.WE_OWE_RELEASE}


# --- Shared entry rules (§4.3.3) ----------------------------------------------------


def test_sale_entry_state_matrix() -> None:
    """ACTIVE and ENDED write now, REOPENED writes only the draft, everything else refuses."""
    assert sm.require_sale_state(_event_row(status=ssm.STATUS_ACTIVE)) == sm.SALE_STATE_LIVE
    assert sm.require_sale_state(_event_row(status=ssm.STATUS_ENDED)) == sm.SALE_STATE_LIVE
    assert sm.require_sale_state(_event_row(status=ssm.STATUS_REOPENED)) == sm.SALE_STATE_DRAFT
    for refused in (ssm.STATUS_SCHEDULED, ssm.STATUS_FINALIZED, ssm.STATUS_CANCELLED):
        with pytest.raises(AppError) as raised:
            sm.require_sale_state(_event_row(status=refused))
        assert raised.value.details["subcode"] == "EVENT_STATE_REFUSES_SALE"


def test_sale_at_bounds_are_inclusive_of_both_event_instants() -> None:
    row = _event_row()
    assert sm.require_sale_at_in_event("2026-11-21T17:00:00+00:00", row) == "2026-11-21T17:00:00+00:00"
    assert sm.require_sale_at_in_event("2026-11-21T21:00:00+00:00", row)
    with pytest.raises(AppError) as raised:
        sm.require_sale_at_in_event("2026-11-21T16:59:59+00:00", row)
    assert raised.value.error_code == ErrorCode.INVALID_INPUT
    with pytest.raises(AppError):
        sm.require_sale_at_in_event("2026-11-21T21:00:01+00:00", row)
    with pytest.raises(AppError):
        sm.normalize_sale_at("not-a-moment")


def test_we_owe_setting_refuses_owed_lines_and_names_the_products() -> None:
    disabled = _event_row(we_owe_enabled=False)
    owed = _lines({"product_id": PRODUCT, "immediate": 0, "we_owe": 1})
    with pytest.raises(AppError) as raised:
        sm.require_we_owe_available(disabled, owed)
    assert raised.value.details["subcode"] == sm.WE_OWE_NOT_ENABLED
    assert raised.value.details["product_ids"] == [PRODUCT]
    # Immediate-only lines on a We Owe-disabled event are fine.
    sm.require_we_owe_available(disabled, _lines({"product_id": PRODUCT, "immediate": 1, "we_owe": 0}))
    sm.require_we_owe_available(_event_row(we_owe_enabled=True), owed)


def test_expected_cash_is_classified_solely_by_method_code() -> None:
    """AC-31: a display name that says Cash is not Cash; only ``methodCode`` decides."""
    cash_row = _sale_item([_line(immediate=2)], sale_id="sale-model-3")
    assert sm.sale_expected_cash_cents(cash_row) == 1000
    cash_named_row = dict(cash_row)
    cash_named_row[sm.PAYMENT_SNAPSHOT_ATTRIBUTE] = {"methodCode": "CUSTOM:x", "displayName": "Cash Only"}
    assert sm.sale_expected_cash_cents(cash_named_row) == 0
    cash_named_row[sm.PAYMENT_SNAPSHOT_ATTRIBUTE] = {"methodCode": "CASH", "displayName": "Venmo"}
    assert sm.sale_expected_cash_cents(cash_named_row) == 1000


def test_corrections_and_voids_share_the_payment_rules(units_table: Any) -> None:
    """§4.3.3: Other needs its explanation everywhere, and a method must be this Unit's."""
    # Built-ins need no stored row.
    decision = spm.sale_payment_decision(unit_id=UNIT, method_code="CHECK")
    assert decision["condition"] is None
    assert decision["snapshot"] == {"methodCode": "CHECK", "displayName": "Check", "otherDetails": None}
    # Other without details is refused; details on anything else are refused.
    with pytest.raises(AppError) as raised:
        spm.sale_payment_decision(unit_id=UNIT, method_code="OTHER")
    assert "paymentMethod.otherDetails is required" in raised.value.message
    with pytest.raises(AppError) as raised:
        spm.sale_payment_decision(unit_id=UNIT, method_code="CASH", other_details="split with a friend")
    assert raised.value.details["subcode"] == "OTHER_DETAILS_NOT_ALLOWED"
    other = spm.sale_payment_decision(unit_id=UNIT, method_code="OTHER", other_details="split with a friend")
    assert other["snapshot"]["otherDetails"] == "split with a friend"
    # The split-payment guidance is what makes Other lawful (AC-20).
    with pytest.raises(AppError) as raised:
        spm.sale_payment_decision(unit_id=UNIT, method_code="OTHER", other_details="x" * 251)
    assert raised.value.error_code == ErrorCode.INVALID_INPUT


def test_custom_methods_must_exist_and_be_active_in_this_unit(units_table: Any) -> None:
    item = upm.build_payment_item(
        payment_method_id="pm-wise",
        unit_id=UNIT,
        display_name="Wise Transfer",
        created_by_account_id=AVERY,
        now_iso=NOW,
        is_active=True,
    )
    units_table.put_item(Item=item)
    decision = spm.sale_payment_decision(unit_id=UNIT, method_code="CUSTOM:pm-wise")
    assert decision["snapshot"]["displayName"] == "Wise Transfer"
    assert decision["condition"]["ConditionExpression"], "the condition pins the row this request read"
    # Another Unit's id is not found here, indistinguishable from a missing row (AUTH-U-05).
    with pytest.raises(AppError) as raised:
        spm.sale_payment_decision(unit_id="unit-other", method_code="CUSTOM:pm-wise")
    assert raised.value.error_code == ErrorCode.NOT_FOUND
    # A retired method refuses new sales but a correction may keep naming it.
    units_table.put_item(Item={**item, "isActive": False})
    with pytest.raises(AppError) as raised:
        spm.sale_payment_decision(unit_id=UNIT, method_code="CUSTOM:pm-wise", require_active=True)
    assert raised.value.details["subcode"] == "PAYMENT_METHOD_NOT_ACTIVE"
    kept = spm.sale_payment_decision(unit_id=UNIT, method_code="CUSTOM:pm-wise", require_active=False)
    assert kept["snapshot"]["displayName"] == "Wise Transfer"
    with pytest.raises(AppError):
        spm.sale_payment_decision(unit_id=UNIT, method_code="CUSTOM:pm-gone")
    with pytest.raises(AppError):
        spm.sale_payment_decision(unit_id=UNIT, method_code="CASH_LIKE")


def test_sale_status_and_revision_guards(show_and_sells_table: Any) -> None:
    active = _sale_item([_line(immediate=1)])
    sm.require_sale_active(active)
    sm.require_sale_revision(active, 1)
    voided = dict(active)
    voided[sm.STATUS_ATTRIBUTE] = sm.SALE_STATUS_VOIDED
    with pytest.raises(AppError) as raised:
        sm.require_sale_active(voided)
    assert raised.value.details["subcode"] == sm.SALE_ALREADY_VOIDED
    with pytest.raises(AppError):
        sm.require_sale_revision(active, 2)
    with pytest.raises(AppError) as raised:
        sm.load_sale_or_not_found(EVENT, "sale-nope")
    assert raised.value.error_code == ErrorCode.NOT_FOUND


# --- Field rules, reads, and the answer shape (§5.14, §5.15, §7.1) -----------------


def test_key_ids_refuse_an_empty_hash_segment_because_sort_keys_collide() -> None:
    """A sort key is ``#``-delimited, so an empty segment is a second row's address."""
    for bad in ("#lead", "trail#", "mid##seg"):
        with pytest.raises(AppError) as raised:
            sm.normalize_sale_id(bad)
        assert "empty # segment" in raised.value.message
    with pytest.raises(AppError):
        sm.normalize_line_item_id("line#")


def test_status_close_reason_money_and_price_normalizers_refuse_the_wrong_thing() -> None:
    for call in (
        lambda: sm.normalize_sale_status("PENDING"),
        lambda: sm.normalize_sale_status(None),
        lambda: sm.normalize_we_owe_status("FULFILLED"),
        lambda: sm.normalize_we_owe_close_reason("CUSTOMER_CHANGED_MIND"),
        lambda: sm.normalize_money_cents(sm.MAX_MONEY_CENTS + 1, "totalCents"),
        lambda: sm.unit_price_cents(True),
        lambda: sm.unit_price_cents({"amount": 5}),
        lambda: sm.unit_price_cents("five dollars"),
        lambda: sm.unit_price_cents("-1.00"),
    ):
        with pytest.raises(AppError):
            call()
    assert sm.normalize_sale_status(sm.SALE_STATUS_VOIDED) == sm.SALE_STATUS_VOIDED
    assert sm.normalize_we_owe_status(sm.WE_OWE_STATUS_CLOSED) == sm.WE_OWE_STATUS_CLOSED
    assert sm.normalize_we_owe_close_reason(sm.WE_OWE_CLOSE_CANCELLED) == sm.WE_OWE_CLOSE_CANCELLED


def test_sale_line_violations_name_the_missing_term_and_the_subtotal_drift() -> None:
    line = _line(immediate=2, we_owe=1)
    assert sm.sale_line_violations(line) == []
    missing = dict(line)
    missing.pop(sm.SUBTOTAL_CENTS_ATTRIBUTE)
    assert sm.sale_line_violations(missing) == [f"{sm.SUBTOTAL_CENTS_ATTRIBUTE} is required"]
    drifted = dict(line)
    drifted[sm.SUBTOTAL_CENTS_ATTRIBUTE] = int(line[sm.SUBTOTAL_CENTS_ATTRIBUTE]) + 1
    assert sm.sale_line_violations(drifted) == [
        "subtotalCents must equal (immediateQty + weOweQty) * unitPriceCentsSnapshot"
    ]


def test_sale_invariants_cover_empty_lines_revision_and_the_payment_snapshot() -> None:
    item = _sale_item([_line(immediate=1)])

    empty = dict(item)
    empty[sm.LINE_ITEMS_ATTRIBUTE] = []
    violations = sm.sale_invariant_violations(empty)
    assert "lineItems must not be empty" in violations
    assert "totalCents must equal the sum of the line subtotals" in violations

    no_revision = dict(item)
    no_revision[sm.REVISION_ATTRIBUTE] = 0
    assert "revision must be a positive integer" in sm.sale_invariant_violations(no_revision)

    not_a_map = dict(item)
    not_a_map[sm.PAYMENT_SNAPSHOT_ATTRIBUTE] = "CASH"
    assert sm.sale_invariant_violations(not_a_map) == ["paymentMethodSnapshot must carry methodCode and displayName"]

    no_code = dict(item)
    no_code[sm.PAYMENT_SNAPSHOT_ATTRIBUTE] = {"displayName": "Cash"}
    assert sm.sale_invariant_violations(no_code) == ["paymentMethodSnapshot.methodCode is required"]

    no_name = dict(item)
    no_name[sm.PAYMENT_SNAPSHOT_ATTRIBUTE] = {"methodCode": "CASH"}
    assert sm.sale_invariant_violations(no_name) == ["paymentMethodSnapshot.displayName is required"]

    bare_other = dict(item)
    bare_other[sm.PAYMENT_SNAPSHOT_ATTRIBUTE] = {"methodCode": "OTHER", "displayName": "Other"}
    assert sm.sale_invariant_violations(bare_other) == [
        "paymentMethodSnapshot.otherDetails is required for the Other method"
    ]

    stray_details = dict(item)
    stray_details[sm.PAYMENT_SNAPSHOT_ATTRIBUTE] = {
        "methodCode": "CASH",
        "displayName": "Cash",
        "otherDetails": "a cheque, later",
    }
    assert sm.sale_invariant_violations(stray_details) == [
        "paymentMethodSnapshot.otherDetails belongs only to the Other method"
    ]


def test_the_sale_builder_refuses_a_row_its_own_invariants_would_reject() -> None:
    """A snapshot the builder cannot make legal is refused, not stored for a report to trip on."""
    with pytest.raises(AppError) as raised:
        sm.build_show_and_sell_sale_item(
            show_and_sell_id=EVENT,
            unit_id=UNIT,
            unit_campaign_id=CAMPAIGN,
            sale_at="2026-11-21T18:30:00+00:00",
            entered_by_account_id=AVERY,
            line_items=_lines({"product_id": PRODUCT, "immediate": 1, "we_owe": 0}),
            payment_method_snapshot={"methodCode": "OTHER", "displayName": "Other"},
            idempotency_key="key-model-invariants",
            now_iso=NOW,
        )
    assert "would break the sale invariants" in raised.value.message
    assert "otherDetails is required" in raised.value.message


def test_a_revision_is_not_archived_without_a_counter_to_archive_under() -> None:
    item = _sale_item([_line(immediate=1)], sale_id="sale-model-revision-zero")
    item[sm.REVISION_ATTRIBUTE] = 0
    with pytest.raises(AppError) as raised:
        sm.build_sale_revision_item(item, corrected_by_account_id=AVERY, reason="typo", corrected_at=NOW)
    assert raised.value.error_code == ErrorCode.INVALID_INPUT
    assert "positive integer" in raised.value.message


def test_an_obligation_is_not_built_for_a_quantity_nobody_owes() -> None:
    line = _line(immediate=1, we_owe=1)
    with pytest.raises(AppError) as raised:
        sm.build_we_owe_item(
            show_and_sell_id=EVENT,
            unit_campaign_id=CAMPAIGN,
            sale_id="sale-model-1",
            line_item=line,
            buyer_name="Buyer Bee",
            now_iso=NOW,
            quantity=0,
        )
    assert raised.value.error_code == ErrorCode.INVALID_INPUT
    assert "greater than zero" in raised.value.message


def test_we_owe_invariants_cover_the_original_floor_status_and_version() -> None:
    owed = _we_owe_item(quantity=2)
    assert sm.we_owe_invariant_violations(owed) == []

    over_fulfilled = dict(owed)
    over_fulfilled[sm.FULFILLED_QTY_ATTRIBUTE] = 3
    assert "originalQty must be at least fulfilledQty + cancelledQty" in sm.we_owe_invariant_violations(over_fulfilled)

    third_status = dict(owed)
    third_status[sm.STATUS_ATTRIBUTE] = "FULFILLED"
    assert "status must be one of OPEN, CLOSED" in sm.we_owe_invariant_violations(third_status)

    no_version = dict(owed)
    no_version[sm.VERSION_ATTRIBUTE] = 0
    assert "version must be a positive integer" in sm.we_owe_invariant_violations(no_version)


def test_reads_find_one_obligation_and_one_sale_revision(show_and_sells_table: Any) -> None:
    """§8.6.1's reads: the obligation by id, and a sale's prior revisions oldest first."""
    owed = _we_owe_item(quantity=3)
    show_and_sells_table.put_item(Item=owed)
    found = sm.read_we_owe(EVENT, str(owed[sm.WE_OWE_ID_ATTRIBUTE]))
    assert found is not None and int(found[sm.ORIGINAL_QTY_ATTRIBUTE]) == 3
    assert sm.read_we_owe(EVENT, "we-owe-never-written") is None

    sale = _sale_item([_line(immediate=1)], sale_id="sale-model-reads")
    revision = sm.build_sale_revision_item(sale, corrected_by_account_id=AVERY, reason="typo", corrected_at=NOW)
    show_and_sells_table.put_item(Item=sale)
    show_and_sells_table.put_item(Item=revision)
    assert [int(r[sm.REVISION_ATTRIBUTE]) for r in sm.sale_revision_rows(EVENT, "sale-model-reads")] == [1]
    assert sm.sale_revision_rows(EVENT, "sale-model-none") == []

    archived = sm.read_sale_revision(EVENT, "sale-model-reads", 1)
    assert archived is not None and str(archived[sm.REASON_ATTRIBUTE]) == "typo"
    assert sm.read_sale_revision(EVENT, "sale-model-reads", 0) is None, (
        "a sale at revision 1 has no previous revision to answer"
    )
    assert sm.read_sale_revision(EVENT, "sale-model-none", 1) is None


def test_the_planner_refuses_a_cancelled_allocation_and_a_product_with_no_shelf() -> None:
    """Two absences that read the same at the table: nothing assigned, and nothing on hand."""
    with pytest.raises(AppError) as raised:
        sm.plan_sale_stock(
            show_and_sell_id=EVENT,
            product_id=PRODUCT,
            immediate_qty=1,
            allocation=_allocation(allocated=4, status=inv.ALLOCATION_CANCELLED),
            balance=_balance(physical=10),
        )
    assert raised.value.details["subcode"] == sm.INSUFFICIENT_EVENT_STOCK
    assert "allocation is CANCELLED" in raised.value.message
    with pytest.raises(AppError) as raised:
        sm.plan_sale_stock(
            show_and_sell_id=EVENT,
            product_id=PRODUCT,
            immediate_qty=1,
            allocation=_allocation(allocated=4),
            balance=None,
        )
    assert raised.value.details["subcode"] == sm.INSUFFICIENT_EVENT_STOCK
    assert "holds 0 to sell" in raised.value.message


def test_a_null_set_becomes_a_remove_because_dynamodb_cannot_bind_a_null() -> None:
    names: Dict[str, str] = {}
    values: Dict[str, Any] = {}
    expression = sm._sets_expression(
        {sm.STATUS_ATTRIBUTE: sm.WE_OWE_STATUS_OPEN, sm.CLOSE_REASON_ATTRIBUTE: None}, [], names, values
    )
    assert expression == f"SET #{sm.STATUS_ATTRIBUTE} = :{sm.STATUS_ATTRIBUTE} REMOVE #{sm.CLOSE_REASON_ATTRIBUTE}"
    assert values[f":{sm.STATUS_ATTRIBUTE}"] == sm.WE_OWE_STATUS_OPEN
    assert f":{sm.CLOSE_REASON_ATTRIBUTE}" not in values
    # An all-clear write is a REMOVE alone: no SET clause is emitted for an empty set map.
    cleared_names: Dict[str, str] = {}
    cleared_values: Dict[str, Any] = {}
    cleared = sm._sets_expression({sm.CLOSE_REASON_ATTRIBUTE: None}, [], cleared_names, cleared_values)
    assert cleared == f"REMOVE #{sm.CLOSE_REASON_ATTRIBUTE}"


def test_payloads_answer_every_stored_number_as_an_int(show_and_sells_table: Any) -> None:
    """A row read back is Decimals; the SDL answers Int, and the marker must be serializable."""
    sale = _sale_item([_line(immediate=1, we_owe=1)], sale_id="sale-model-payload")
    stored_sale = _decimalize(sale)
    payload = sm.sale_payload(stored_sale)
    assert payload[sm.TOTAL_CENTS_ATTRIBUTE] == 1000
    assert all(isinstance(value, int) for value in payload["lineItems"][0].values() if not isinstance(value, str))
    assert isinstance(payload["expectedCashCents"], int)

    revision = sm.build_sale_revision_item(sale, corrected_by_account_id=AVERY, reason="typo", corrected_at=NOW)
    revision_payload = sm.sale_revision_payload(_decimalize(revision))
    assert revision_payload[sm.REVISION_ATTRIBUTE] == 1
    assert isinstance(revision_payload["lineItems"][0][sm.SUBTOTAL_CENTS_ATTRIBUTE], int)

    owed = _we_owe_item(quantity=2, fulfilled=1, reserved=1)
    owed_payload = sm.we_owe_payload(_decimalize(owed))
    assert owed_payload[sm.ORIGINAL_QTY_ATTRIBUTE] == 2
    assert owed_payload[sm.UNCOVERED_QTY_ATTRIBUTE] == 0, "one owed unit, one reserved"

    with pytest.raises(AppError):
        sm.sale_line_payload({**_line(immediate=1), sm.SUBTOTAL_CENTS_ATTRIBUTE: 5.0})
