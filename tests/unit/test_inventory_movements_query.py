"""The §2.2.4 audit read has to answer on the deployed DynamoDB, not only on moto.

WORK-158 shipped ``inventoryMovements`` discriminating movement rows out of the
campaign partition with ``contains(#sk, '#MOVEMENT#')`` — a filter over the table's
sort key. The service refuses that call outright, so the deployed field answered
``INTERNAL_ERROR`` for every campaign, including an empty one, while ``INV-Q-02``
and ``PAGE-01`` stayed green because moto accepts the request. The guard installed
by the ``inventory_table`` fixture (``tests/unit/dynamodb_query_guard.py``) makes
this module's reads speak the service's rules, which is what turns the fix into a
pin: the first test below is the failing call, kept on purpose.

What the read must still do is asserted as well, because the defect hid the rest of
the contract: the audit trail excludes the balance, allocation and custody rows that
share its partition, and a product filter selects one product and no other — even
when a second product's id is spelled with the first product's id and the movement
marker in it, which is the case a key prefix cannot separate.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from botocore.exceptions import ClientError

from src.utils import inventory_models as inv
from src.utils.dynamodb import tables
from tests.unit.dynamodb_query_guard import key_attributes_by_index, violating_key_attribute
from tests.unit.table_schemas import create_inventory_table_schema

CAMPAIGN = "uc-pack-3149-fall-2026"
OTHER_CAMPAIGN = "uc-crew-529-denver"
# Product ids are spelled with the catalog id inside them, so a ``#`` sits in the
# middle of every one (§6.3).
PRODUCT = "CATALOG#fixture-default#prod-1"
SIBLING = "CATALOG#fixture-default#prod-10"
# One product id whose leading segments are another product id plus the movement
# marker: opening prod-1's history range also opens this product's.
NESTED = "CATALOG#fixture-default#prod-1#MOVEMENT"
SCOUT = "PROFILE#devon-uuid"
EVENT = "SSE#morning"
NOW = "2026-11-07T08:00:00+00:00"
LATER = "2026-11-07T09:00:00+00:00"

_SCOPES = key_attributes_by_index(create_inventory_table_schema())


def _movement(product_id: str, movement_id: str, occurred_at: str, **overrides: Any) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "movement_id": movement_id,
        "unit_campaign_id": CAMPAIGN,
        "product_id": product_id,
        "movement_type": inv.RECEIPT,
        "actor_account_id": "acct-avery",
        "occurred_at": occurred_at,
        "idempotency_key": f"idem-{movement_id}",
        "kernel_physical_delta": 1,
        "inventory_version": 1,
    }
    arguments.update(overrides)
    return inv.build_inventory_movement_item(**arguments)


def _seed(inventory_table: Any) -> None:
    """One campaign partition holding every row kind, and a second campaign to keep out."""
    for item in (
        inv.build_inventory_balance_item(
            unit_campaign_id=CAMPAIGN, product_id=PRODUCT, kernel_physical_qty=3, now_iso=NOW
        ),
        inv.build_event_inventory_allocation_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            show_and_sell_id=EVENT,
            start_at=NOW,
            end_at=LATER,
            allocated_qty=2,
            now_iso=NOW,
        ),
        inv.build_scout_custody_balance_item(
            unit_campaign_id=CAMPAIGN,
            product_id=PRODUCT,
            profile_id=SCOUT,
            campaign_id="CAMPAIGN#devon-fixture",
            with_scout_qty=1,
            now_iso=NOW,
        ),
        _movement(PRODUCT, "mov-1", NOW),
        _movement(PRODUCT, "mov-2", LATER, movement_type=inv.STOCK_ADJUSTMENT, reason="miscount"),
        _movement(SIBLING, "mov-3", LATER),
        _movement(NESTED, "mov-4", LATER),
        _movement(PRODUCT, "mov-other", LATER, unit_campaign_id=OTHER_CAMPAIGN),
    ):
        inventory_table.put_item(Item=item)


# --- the guard itself: it must bite on the real defect and only on that class -----


def test_the_sort_key_filter_this_read_used_to_carry_is_the_call_the_service_refuses(
    inventory_table: Any,
) -> None:
    """The exact request WORK-158 deployed fails here, with the service's own words."""
    with pytest.raises(ClientError) as raised:
        tables.inventory.query(
            KeyConditionExpression="#pk = :pk",
            ExpressionAttributeNames={"#sk": "sk"},
            ExpressionAttributeValues={":pk": inv.inventory_pk(CAMPAIGN), ":marker": f"#{inv.MOVEMENT_SK_MARKER}#"},
            FilterExpression="contains(#sk, :marker)",
        )
    error = raised.value.response["Error"]
    assert error["Code"] == "ValidationException"
    assert error["Message"] == (
        "Filter Expression can only contain non-primary key attributes: Primary key attribute: sk"
    )


def test_a_scan_may_still_filter_the_sort_key_because_a_scan_has_no_key_condition(
    inventory_table: Any,
) -> None:
    """Guarding Scan too would invent a rule the service does not have."""
    _seed(inventory_table)
    response = tables.inventory.scan(
        ExpressionAttributeNames={"#sk": "sk"},
        ExpressionAttributeValues={":prefix": inv.product_scope_prefix(PRODUCT)},
        FilterExpression="begins_with(#sk, :prefix)",
    )
    assert response["Items"]


def test_an_index_query_may_filter_a_base_table_key_attribute_that_the_index_does_not_key(
    inventory_table: Any,
) -> None:
    """The schema that counts is the queried index's, not the table's.

    The Stage 1 reads that list a Unit's campaigns and invites query an index and
    filter the base table's ``pk``/``sk``, and the service answers them; a guard
    that read the base schema would condemn working code.
    """
    _seed(inventory_table)
    inventory_table.put_item(
        Item=_movement(
            PRODUCT,
            "mov-issue",
            LATER,
            movement_type=inv.SCOUT_ISSUE,
            profile_id=SCOUT,
            show_and_sell_id=EVENT,
            with_scout_delta=1,
            kernel_physical_delta=0,
        )
    )
    response = tables.inventory.query(
        IndexName="showAndSellId-index",
        KeyConditionExpression="showAndSellId = :event",
        ExpressionAttributeNames={"#sk": "sk"},
        ExpressionAttributeValues={
            ":event": EVENT,
            ":prefix": inv.product_movement_prefix(PRODUCT),
        },
        FilterExpression="begins_with(#sk, :prefix)",
    )
    assert [row["movementId"] for row in response["Items"]] == ["mov-issue"]


def test_a_value_placeholder_named_like_a_key_is_not_an_attribute_reference(inventory_table: Any) -> None:
    """``:sk`` is a value; reading it as an attribute would reject legal queries."""
    _seed(inventory_table)
    response = tables.inventory.query(
        KeyConditionExpression="#pk = :pk",
        ExpressionAttributeNames={"#pk": "pk", "#entityType": inv.ENTITY_TYPE_ATTRIBUTE},
        ExpressionAttributeValues={":pk": inv.inventory_pk(CAMPAIGN), ":sk": inv.MOVEMENT_ENTITY_TYPE},
        FilterExpression="#entityType = :sk",
    )
    assert len(response["Items"]) == 4


@pytest.mark.parametrize(
    ("filter_expression", "names", "expected"),
    [
        ("contains(#sk, :marker)", {"#sk": "sk"}, "sk"),
        ("#sk = :metadata", {"#sk": "sk"}, "sk"),
        ("begins_with(pk, :prefix)", {}, "pk"),
        ("#pk = :pk and begins_with(#sk, :prefix)", {"#pk": "pk", "#sk": "sk"}, "pk"),
        ("sk.nested = :value", {}, "sk"),
        ("#entityType = :movementEntityType", {"#entityType": inv.ENTITY_TYPE_ATTRIBUTE}, None),
        ("#entityType = :movementEntityType and #productId = :movementProductId", {}, None),
        ("#movementType = :movementType and #occurredAt >= :startAt", {}, None),
        ("#entityType = :sk", {}, None),
        ("attribute_not_exists(version)", {}, None),
        ("size(#entityType) > :length", {"#entityType": inv.ENTITY_TYPE_ATTRIBUTE}, None),
    ],
)
def test_the_guard_names_the_key_attribute_a_filter_over_reaches_and_nothing_else(
    filter_expression: str, names: Dict[str, str], expected: str | None
) -> None:
    """Table-driven so a token cannot be mistaken for another: values, paths, functions."""
    params = {"TableName": "kernelworx-inventory-ue1-dev", "FilterExpression": filter_expression}
    if names:
        params["ExpressionAttributeNames"] = names
    assert violating_key_attribute(params, _SCOPES) == expected


def test_an_index_scope_joins_the_rejection_for_its_own_keys() -> None:
    """The same rule, judged against the index: its partition key is a key attribute."""
    params = {
        "TableName": "kernelworx-inventory-ue1-dev",
        "IndexName": "showAndSellId-index",
        "FilterExpression": "#event = :event",
        "ExpressionAttributeNames": {"#event": "showAndSellId"},
    }
    assert violating_key_attribute(params, _SCOPES) == "showAndSellId"
    # and the base table's sort key is fair game inside that index read
    params["FilterExpression"] = "#sk = :metadata"
    params["ExpressionAttributeNames"] = {"#sk": "sk"}
    assert violating_key_attribute(params, _SCOPES) is None


# --- the read itself -------------------------------------------------------------


def test_the_history_read_names_no_key_attribute_in_its_filter(inventory_table: Any, monkeypatch: Any) -> None:
    """Both shapes of the read, inspected as the DynamoDB call they actually send."""
    captured: List[Dict[str, Any]] = []
    real_query_all_items = inv.query_all_items

    def _capture(table: Any, query_kwargs: Dict[str, Any], max_items: Any = None) -> List[Dict[str, Any]]:
        captured.append(dict(query_kwargs))
        return real_query_all_items(table, query_kwargs, max_items=max_items)

    monkeypatch.setattr(inv, "query_all_items", _capture)
    _seed(inventory_table)
    inv.list_inventory_movements(CAMPAIGN)
    inv.list_inventory_movements(CAMPAIGN, product_id=PRODUCT, movement_type=inv.RECEIPT)

    assert len(captured) == 2
    for query in captured:
        assert violating_key_attribute(query, _SCOPES) is None
        assert query["KeyConditionExpression"].startswith("#pk = :pk")
    campaign_wide, product_scoped = captured
    assert campaign_wide["KeyConditionExpression"] == "#pk = :pk"
    assert campaign_wide["FilterExpression"] == "#entityType = :movementEntityType"
    assert product_scoped["KeyConditionExpression"] == "#pk = :pk and begins_with(#sk, :prefix)"
    assert product_scoped["ExpressionAttributeValues"][":prefix"] == inv.product_movement_prefix(PRODUCT)
    assert product_scoped["FilterExpression"] == (
        "#entityType = :movementEntityType and #productId = :movementProductId and #movementType = :movementType"
    )


def test_a_history_read_answers_only_movement_rows_of_one_campaign(inventory_table: Any) -> None:
    """Balance, allocation and custody rows share the partition and never belong here."""
    _seed(inventory_table)
    rows = inv.list_inventory_movements(CAMPAIGN)
    assert [row["movementId"] for row in rows] == ["mov-1", "mov-2", "mov-3", "mov-4"]
    assert all(row[inv.ENTITY_TYPE_ATTRIBUTE] == inv.MOVEMENT_ENTITY_TYPE for row in rows)


def test_a_product_filter_selects_one_product_even_when_another_id_contains_it(inventory_table: Any) -> None:
    """A key prefix cannot tell ``prod-1`` from ``prod-1#MOVEMENT``; the attribute can.

    The marker range for one product is also the whole range of a product whose id
    continues it, so an audit screen filtered to one product would otherwise show
    another product's stock changes and its deltas would not sum to this position.
    """
    _seed(inventory_table)
    rows = inv.list_inventory_movements(CAMPAIGN, product_id=PRODUCT)
    assert [row["movementId"] for row in rows] == ["mov-1", "mov-2"]
    assert all(row[inv.PRODUCT_ID_ATTRIBUTE] == PRODUCT for row in rows)
    assert [row["movementId"] for row in inv.list_inventory_movements(CAMPAIGN, product_id=NESTED)] == ["mov-4"]


def test_every_other_filter_still_selects_its_own_slice(inventory_table: Any) -> None:
    """Type, event, Scout, and the two ends of the window, applied by the read."""
    _seed(inventory_table)
    tables.inventory.put_item(
        Item=_movement(
            PRODUCT,
            "mov-issue",
            LATER,
            movement_type=inv.SCOUT_ISSUE,
            profile_id=SCOUT,
            show_and_sell_id=EVENT,
            with_scout_delta=1,
            kernel_physical_delta=0,
        )
    )
    assert [row["movementId"] for row in inv.list_inventory_movements(CAMPAIGN, movement_type=inv.SCOUT_ISSUE)] == [
        "mov-issue"
    ]
    assert [row["movementId"] for row in inv.list_inventory_movements(CAMPAIGN, show_and_sell_id=EVENT)] == [
        "mov-issue"
    ]
    assert [row["movementId"] for row in inv.list_inventory_movements(CAMPAIGN, profile_id=SCOUT)] == ["mov-issue"]
    assert [row["movementId"] for row in inv.list_inventory_movements(CAMPAIGN, start_at=LATER)] == [
        "mov-2",
        "mov-3",
        "mov-4",
        "mov-issue",
    ]
    assert [row["movementId"] for row in inv.list_inventory_movements(CAMPAIGN, end_at=NOW)] == ["mov-1"]
    combined = inv.list_inventory_movements(CAMPAIGN, product_id=PRODUCT, movement_type=inv.STOCK_ADJUSTMENT)
    assert [(row["movementId"], row[inv.REASON_ATTRIBUTE]) for row in combined] == [("mov-2", "miscount")]
