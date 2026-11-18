"""Wave 3.3 building blocks — the `OrderFulfillment` row and its line arithmetic.

Persistence-level tests for data model §5.19 and §6.5: the one-partition-per-Order key
grammar, the append-only row builder with its cross-field rules, the admin and
participant projections, the per-line fulfillment arithmetic an Order row must pass,
and the `fulfillmentVersion` condition that serializes fulfill, reverse, and edit on
one Order. Every case is a branch the 100% coverage gate will hold this file to.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

import pytest

from src.utils import order_fulfillment_models as ofm
from src.utils.errors import AppError, ErrorCode

# The order id this application actually spells: the `orders` table is keyed
# {campaignId, orderId} and the id embeds the campaign's bare id.
CAMPAIGN = "CAMPAIGN#devon-fall-2026"
ORDER = "ORDER#devon-fall-2026#ord-42"
BARE_ORDER = "devon-fall-2026#ord-42"
PROFILE = "PROFILE#devon-uuid"
UNIT = "unit-fixture"
UNIT_CAMPAIGN = "uc-pack-fall-2026"
LINE_FIRST = "line-1"
LINE_SECOND = "line-2"
LINE_MISSING = "line-9"
PRODUCT = "CATALOG#fixture-default#prod-1"
FULFILLMENT = "ful-1"
ORIGINAL = "ful-0"
MOVEMENT = "mov-1"
NOW = "2026-11-01T00:00:00+00:00"
NOW_Z = "2026-11-01T00:00:00Z"
LATER = "2026-11-01T12:00:00+00:00"

#: An Order row as this application reads it: a pre-Wave-3 line carries no
#: `fulfilledQuantity`, and a later line does.
ORDER_ROW: Dict[str, Any] = {
    "lineItems": [
        {"lineItemId": LINE_FIRST, "quantity": 5, "fulfilledQuantity": 3},
        {"lineItemId": LINE_SECOND, "quantity": 2},
    ]
}


def _fulfillment(**overrides: Any) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "fulfillment_id": FULFILLMENT,
        "order_id": ORDER,
        "campaign_id": CAMPAIGN,
        "profile_id": PROFILE,
        "unit_id": UNIT,
        "unit_campaign_id": UNIT_CAMPAIGN,
        "line_item_id": LINE_FIRST,
        "product_id": PRODUCT,
        "record_type": ofm.RECORD_TYPE_FULFILL,
        "quantity": 2,
        "source": ofm.SOURCE_KERNEL_STOCK,
        "actor_account_id": "acct-avery",
        "created_at": NOW,
        "inventory_movement_id": MOVEMENT,
    }
    arguments.update(overrides)
    return ofm.build_fulfillment_item(**arguments)


# --- constants: one spelling, one list ---------------------------------------------


def test_the_closed_sets_fix_every_spelling_a_handler_might_invent() -> None:
    """The key prefixes, the record/source enums, and the audit-field list are the contract.

    `SOURCE_MOVES_STOCK` is what separates a fulfillment that moves a Kernel balance
    (and so must name its movement) from one that does not; `ADMIN_ONLY_FULFILLMENT_FIELDS`
    is what separates the admin type from the participant one, by subtraction rather
    than by an allow-list that a future audit field could slip past.
    """
    assert ofm.FULFILLMENT_ENTITY_TYPE == "OrderFulfillment"
    assert ofm.PK_PREFIX == "ORDER"
    assert ofm.FULFILLMENT_SK_PREFIX == "FULFILLMENT"
    assert ofm.REVERSAL_SK_PREFIX == "REVERSAL"
    assert ofm.FULFILLMENT_RECORD_TYPES == frozenset({ofm.RECORD_TYPE_FULFILL, ofm.RECORD_TYPE_REVERSAL})
    assert ofm.FULFILLMENT_SOURCES == frozenset(
        {ofm.SOURCE_KERNEL_STOCK, ofm.SOURCE_SCOUT_CUSTODY, ofm.SOURCE_EXTERNAL_COUNCIL}
    )
    assert ofm.SOURCE_MOVES_STOCK == frozenset({ofm.SOURCE_KERNEL_STOCK, ofm.SOURCE_SCOUT_CUSTODY})
    assert ofm.ADMIN_ONLY_FULFILLMENT_FIELDS == frozenset({"actorAccountId", "inventoryMovementId"})


# --- key builders (§6.5) -----------------------------------------------------------


def test_partition_key_is_idempotent_because_order_ids_already_carry_the_prefix() -> None:
    """Blindly prefixing an order id would mint a partition nothing ever writes.

    The `orders` table is keyed {campaignId, orderId} with the id spelled
    `ORDER#<campaign>#<suffix>`, so a fulfillment partition for that id is the id
    itself; a bare id still gets the prefix so both spellings land on one partition.
    """
    assert ofm.fulfillment_partition_key(ORDER) == ORDER
    assert ofm.fulfillment_partition_key(BARE_ORDER) == ORDER
    assert not ofm.fulfillment_partition_key(ORDER).startswith("ORDER#ORDER#")
    for hostile in ("#lead", "trail#", "mid##dle", "", "   "):
        with pytest.raises(AppError) as caught:
            ofm.fulfillment_partition_key(hostile)
        assert caught.value.error_code is ErrorCode.INVALID_INPUT


def test_fulfillment_sort_key_orders_by_instant_then_identity_with_one_fixed_spelling() -> None:
    """Business time is the sort dimension; `Z` and `+00:00` must not sort apart."""
    assert ofm.fulfillment_sort_key(NOW, FULFILLMENT) == f"FULFILLMENT#{NOW}#{FULFILLMENT}"
    assert ofm.fulfillment_sort_key(NOW_Z, FULFILLMENT) == ofm.fulfillment_sort_key(NOW, FULFILLMENT)
    same_instant_b = ofm.fulfillment_sort_key(NOW, "ful-2")
    later = ofm.fulfillment_sort_key(LATER, FULFILLMENT)
    assert ofm.fulfillment_sort_key(NOW, FULFILLMENT) < same_instant_b < later


def test_the_reversal_key_is_deterministic_so_a_second_reversal_collides_on_it() -> None:
    """Two readers that both answer "not yet reversed" must still not both write.

    The key is derived from the reversed id, never from a freshly minted one, so a
    second reversal of the same fulfillment collides on its key and fails its
    conditional write instead of racing a read (§5.19).
    """
    key = ofm.reversal_sort_key(ORIGINAL)
    assert key == f"REVERSAL#{ORIGINAL}"
    assert ofm.reversal_sort_key(ORIGINAL) == key
    assert ofm.reversal_sort_key(FULFILLMENT) != key


# --- builder and cross-field rules (§5.19) -----------------------------------------


def test_the_builder_refuses_bad_quantities_record_types_and_sources() -> None:
    """Quantity is a positive integer on BOTH record kinds; the enums are closed."""
    for quantity in (0, -1, "2", None, True, 1.5):
        with pytest.raises(AppError) as caught:
            _fulfillment(quantity=quantity)
        assert caught.value.error_code is ErrorCode.INVALID_INPUT
        assert "quantity" in str(caught.value.message)
    with pytest.raises(AppError) as caught:
        _fulfillment(record_type="DONATION")
    assert "recordType" in str(caught.value.message)
    with pytest.raises(AppError) as caught:
        _fulfillment(source="COURIER")
    assert "source" in str(caught.value.message)


def test_a_reversal_needs_the_link_and_a_fulfill_must_not_carry_one() -> None:
    """The link names what is reversed, and it also decides the row's sort key.

    A REVERSAL without it cannot restore "the original demand and only the original
    stock source"; a FULFILL with it would disagree with its own recordType about
    which key it was written under.
    """
    with pytest.raises(AppError) as caught:
        _fulfillment(
            record_type=ofm.RECORD_TYPE_REVERSAL, source=ofm.SOURCE_EXTERNAL_COUNCIL, inventory_movement_id=None
        )
    assert caught.value.error_code is ErrorCode.INVALID_INPUT
    assert "reversalOfFulfillmentId" in str(caught.value.message)
    with pytest.raises(AppError) as caught:
        _fulfillment(reversal_of_fulfillment_id=ORIGINAL)
    assert caught.value.error_code is ErrorCode.INVALID_INPUT
    assert "reversalOfFulfillmentId" in str(caught.value.message)
    reversal = _fulfillment(
        record_type=ofm.RECORD_TYPE_REVERSAL,
        source=ofm.SOURCE_KERNEL_STOCK,
        quantity=2,
        inventory_movement_id=MOVEMENT,
        reversal_of_fulfillment_id=ORIGINAL,
    )
    assert reversal["reversalOfFulfillmentId"] == ORIGINAL
    assert reversal["sk"] == f"REVERSAL#{ORIGINAL}"


def test_stock_sources_need_the_movement_and_external_council_must_not_carry_one() -> None:
    """An untraceable stock change, or a Council change with a stock effect, both lie.

    `KERNEL_STOCK` and `SCOUT_CUSTODY` move a Kernel balance, so each must name the
    movement that did; `EXTERNAL_COUNCIL` changes fulfillment and demand and no Kernel
    balance, so carrying a movement id would claim a stock move the data model says
    never happened.
    """
    for source in (ofm.SOURCE_KERNEL_STOCK, ofm.SOURCE_SCOUT_CUSTODY):
        with pytest.raises(AppError) as caught:
            _fulfillment(source=source, inventory_movement_id=None)
        assert caught.value.error_code is ErrorCode.INVALID_INPUT
        assert "inventoryMovementId" in str(caught.value.message)
    with pytest.raises(AppError) as caught:
        _fulfillment(source=ofm.SOURCE_EXTERNAL_COUNCIL, inventory_movement_id=MOVEMENT)
    assert "inventoryMovementId" in str(caught.value.message)
    council = _fulfillment(
        source=ofm.SOURCE_EXTERNAL_COUNCIL, inventory_movement_id=None, unit_id=None, unit_campaign_id=None
    )
    assert "inventoryMovementId" not in council
    custody = _fulfillment(source=ofm.SOURCE_SCOUT_CUSTODY)
    assert custody["inventoryMovementId"] == MOVEMENT


def test_a_full_fulfillment_row_round_trips_through_the_admin_projection() -> None:
    """The stored row is the only shape; the payload is the only admin view of it."""
    item = _fulfillment(quantity=Decimal("3"))
    assert item["pk"] == ORDER
    assert item["sk"] == f"FULFILLMENT#{NOW}#{FULFILLMENT}"
    assert item["entityType"] == "OrderFulfillment"
    payload = ofm.fulfillment_payload(item)
    assert payload["quantity"] == 3
    assert isinstance(payload["quantity"], int)
    assert payload["orderId"] == ORDER and payload["source"] == ofm.SOURCE_KERNEL_STOCK
    assert payload["recordType"] == ofm.RECORD_TYPE_FULFILL and payload["createdAt"] == NOW
    expected_fields = {
        "fulfillmentId",
        "orderId",
        "campaignId",
        "profileId",
        "unitId",
        "unitCampaignId",
        "lineItemId",
        "productId",
        "recordType",
        "quantity",
        "source",
        "inventoryMovementId",
        "reversalOfFulfillmentId",
        "actorAccountId",
        "createdAt",
    }
    assert set(payload) == expected_fields
    for storage in ("pk", "sk", "entityType"):
        assert storage not in payload


def test_absent_optional_scopes_are_null_not_defaulted() -> None:
    """An independent sale has no originating Unit; empty strings would read as scopes."""
    council = _fulfillment(
        source=ofm.SOURCE_EXTERNAL_COUNCIL,
        inventory_movement_id=None,
        unit_id=None,
        unit_campaign_id=None,
    )
    assert "unitId" not in council and "unitCampaignId" not in council
    payload = ofm.fulfillment_payload(council)
    assert payload["unitId"] is None and payload["unitCampaignId"] is None
    assert payload["inventoryMovementId"] is None
    # A count that is not a count reads as 0, never as an error.
    junk = ofm.fulfillment_payload(dict(council, quantity=True))
    assert junk["quantity"] == 0


def test_the_participant_projection_carries_neither_audit_field_and_the_admin_carries_both() -> None:
    """§10.2: the Scout view is the admin view minus who acted and what moved.

    Derived by subtraction, so an audit field added to the stored row later cannot
    reach a participant projection by someone forgetting an allow-list entry.
    """
    item = _fulfillment()
    admin = ofm.fulfillment_payload(item)
    participant = ofm.participant_fulfillment_payload(item)
    assert admin["actorAccountId"] == "acct-avery"
    assert admin["inventoryMovementId"] == MOVEMENT
    assert "actorAccountId" not in participant and "inventoryMovementId" not in participant
    assert participant == {
        name: value for name, value in admin.items() if name not in ofm.ADMIN_ONLY_FULFILLMENT_FIELDS
    }
    # Reversal history stays visible to the participant: what was reversed and how much.
    reversal = _fulfillment(
        record_type=ofm.RECORD_TYPE_REVERSAL,
        source=ofm.SOURCE_KERNEL_STOCK,
        reversal_of_fulfillment_id=ORIGINAL,
    )
    admin_reversal = ofm.fulfillment_payload(reversal)
    participant_reversal = ofm.participant_fulfillment_payload(reversal)
    assert participant_reversal["reversalOfFulfillmentId"] == ORIGINAL
    assert admin_reversal["reversalOfFulfillmentId"] == ORIGINAL


# --- Order line arithmetic (§5.19) -------------------------------------------------


def test_line_quantity_violations_explains_instead_of_raising() -> None:
    """The caller has to answer INVALID_INPUT with the reason, and has staged nothing yet.

    The reason names which line to shorten; raising here would bury it. A pre-Wave-3
    line with no `fulfilledQuantity` reads as 0 fulfilled and is therefore admissible
    without any backfill.
    """
    assert ofm.line_quantity_violations(ORDER_ROW, LINE_MISSING, 1) == f"this order has no line item {LINE_MISSING}"
    assert (
        ofm.line_quantity_violations({"noLineItems": True}, LINE_FIRST, 1)
        == f"this order has no line item {LINE_FIRST}"
    )
    for requested in (0, -1):
        reason = ofm.line_quantity_violations(ORDER_ROW, LINE_FIRST, requested)
        assert reason is not None and "must be at least 1" in reason
    # 5 ordered, 3 fulfilled: a request of 3 overruns, a request of 2 does not.
    over = ofm.line_quantity_violations(ORDER_ROW, LINE_FIRST, 3)
    assert over is not None and "left unfulfilled" in over
    assert ofm.line_quantity_violations(ORDER_ROW, LINE_FIRST, 2) is None
    # The pre-Wave-3 line: no fulfilledQuantity, so the whole ordered quantity is open.
    assert ofm.line_quantity_violations(ORDER_ROW, LINE_SECOND, 2) is None
    assert ofm.line_quantity_violations(ORDER_ROW, LINE_SECOND, 3) is not None
    # A stored count that is not a count reads as 0, so the junk line is fully open.
    junk_line = {"lineItemId": LINE_FIRST, "quantity": 4, "fulfilledQuantity": "junk"}
    assert ofm.line_quantity_violations({"lineItems": [junk_line]}, LINE_FIRST, 4) is None


def test_apply_line_fulfillment_increments_and_keeps_both_bounds() -> None:
    """Fulfilling is a count move inside [0, ordered]; both ends are CONFLICT territory.

    The bounds are enforced against the arithmetic this request computed, and the
    input row must survive byte-for-byte: the mutation re-checks the snapshot's
    version after building, and an in-place edit of that snapshot stales its own
    condition.
    """
    original_lines = [dict(line) for line in ORDER_ROW["lineItems"]]
    moved = ofm.apply_line_fulfillment(ORDER_ROW, LINE_FIRST, 2)
    assert moved == [
        {"lineItemId": LINE_FIRST, "quantity": 5, "fulfilledQuantity": 5},
        {"lineItemId": LINE_SECOND, "quantity": 2},
    ]
    # The caller's row is untouched.
    assert ORDER_ROW["lineItems"] == original_lines
    # A reversal of the same line walks back inside the bounds.
    reversed_back = ofm.apply_line_fulfillment(ORDER_ROW, LINE_FIRST, -3)
    assert reversed_back[0]["fulfilledQuantity"] == 0
    for delta in (-4, 3):  # 3 - 4 < 0; 3 + 3 > 5
        with pytest.raises(AppError) as caught:
            ofm.apply_line_fulfillment(ORDER_ROW, LINE_FIRST, delta)
        assert caught.value.error_code is ErrorCode.CONFLICT
        assert "line item" in str(caught.value.message)
    with pytest.raises(AppError) as caught:
        ofm.apply_line_fulfillment(ORDER_ROW, LINE_MISSING, 1)
    assert caught.value.error_code is ErrorCode.CONFLICT
    for delta in (0, "two", 1.5):
        with pytest.raises(AppError) as caught:
            ofm.apply_line_fulfillment(ORDER_ROW, LINE_FIRST, delta)
        assert caught.value.error_code is ErrorCode.INVALID_INPUT


def test_apply_line_fulfillment_copies_lines_so_nothing_shared_is_writable() -> None:
    """A junk entry in the stored list is dropped, and every survivor is a fresh copy.

    The returned list shares no reference with the read: editing an entry of it must
    not reach the caller's row.
    """
    row: Dict[str, Any] = {"lineItems": ["junk", dict(ORDER_ROW["lineItems"][1])]}
    moved: List[Dict[str, Any]] = ofm.apply_line_fulfillment(row, LINE_SECOND, 1)
    assert moved == [{"lineItemId": LINE_SECOND, "quantity": 2, "fulfilledQuantity": 1}]
    moved[0]["fulfilledQuantity"] = 99
    assert row["lineItems"][1] == {"lineItemId": LINE_SECOND, "quantity": 2}


# --- the fulfillmentVersion condition (§5.19) --------------------------------------


def test_the_version_condition_carries_the_pre_wave_3_disjunction_and_the_order_key() -> None:
    """Two absences have to be told apart, and the expression is the only place that can.

    A pre-Wave-3 row has no ``fulfillmentVersion`` attribute at all, and equality against
    absence fails, so version 0 must match "attribute_not_exists OR attribute = 0" — both
    spellings of "nobody has fulfilled this yet" — or an unfulfilled legacy Order is
    unfulfillable without a backfill.

    But ``attribute_not_exists`` is equally satisfied by an item that is not there at all,
    and a condition against a missing item SUCCEEDS. Delete the Order between the caller's
    read and this transaction and a version-0 guard alone would let ``UpdateItem`` write a
    partial Order back. So every spelling of the guard also requires the Order's own key
    attribute, and the disjunction is parenthesized because DynamoDB documents no precedence
    for mixing AND with OR.
    """
    zero = ofm.fulfillment_version_condition(0)
    assert zero == {
        "ConditionExpression": (
            "(attribute_not_exists(#fulfillmentVersion) OR #fulfillmentVersion = :expectedFulfillmentVersion)"
            " AND attribute_exists(#orderId)"
        ),
        "ExpressionAttributeNames": {"#fulfillmentVersion": "fulfillmentVersion", "#orderId": "orderId"},
        "ExpressionAttributeValues": {":expectedFulfillmentVersion": {"N": "0"}},
    }
    seventh = ofm.fulfillment_version_condition(7)
    assert seventh == {
        "ConditionExpression": "#fulfillmentVersion = :expectedFulfillmentVersion AND attribute_exists(#orderId)",
        "ExpressionAttributeNames": {"#fulfillmentVersion": "fulfillmentVersion", "#orderId": "orderId"},
        "ExpressionAttributeValues": {":expectedFulfillmentVersion": {"N": "7"}},
    }


def test_the_line_wire_encoder_keeps_every_type_the_js_write_path_stored() -> None:
    """A re-stored line keeps its attribute types, or the Order row's prices change type.

    ``lineItems`` is written by the ``createOrder``/``updateOrder`` JS pipeline through
    ``util.dynamodb.toDynamoDB``, and a fulfillment re-writes the whole list.
    ``mutations.wire_value`` is scalar-only and would turn a price into a ``STRING``, so
    this encoder is total over every JSON type that path can store: number as ``N`` (a
    float keeps its exact decimal rather than a scientific one), boolean as ``BOOL``,
    absent as ``NULL``, text as ``S``.
    """
    assert ofm.wire_line_item_value(Decimal("3.50")) == {"N": "3.50"}
    assert ofm.wire_line_item_value(4) == {"N": "4"}
    assert ofm.wire_line_item_value(19.99) == {"N": "19.99"}
    assert ofm.wire_line_item_value(0.0001) == {"N": "0.0001"}
    assert ofm.wire_line_item_value(True) == {"BOOL": True}
    assert ofm.wire_line_item_value(None) == {"NULL": True}
    assert ofm.wire_line_item_value(LINE_FIRST) == {"S": LINE_FIRST}


def test_the_line_list_is_a_list_of_maps_under_one_attribute() -> None:
    """``L`` of ``M``, not a stringified blob: a nested map has to stay a map."""
    encoded = ofm.wire_line_items(
        [{"lineItemId": LINE_FIRST, "quantity": 5, "pricePerUnit": Decimal("3.50"), "fulfilledQuantity": 1}]
    )
    assert list(encoded) == ["L"]
    (only,) = encoded["L"]
    attributes = only["M"]
    assert attributes["lineItemId"] == {"S": LINE_FIRST}
    assert attributes["pricePerUnit"] == {"N": "3.50"}
    assert attributes["quantity"] == {"N": "5"}
    assert attributes["fulfilledQuantity"] == {"N": "1"}
