"""Wave 5.3 — We Owe reservation, fulfillment and the two obligation reads (§4.4.2-§4.4.4).

Resolver-level cases for ``OWE-M-01``, ``OWE-M-02`` and ``OWE-Q-01``, plus the ``AUTH-U``,
``PAGE-01``, ``VER-01`` and ``IDEM`` halves of each. Everything runs through
``handle_unit_operation`` against moto, so what is proved is the transaction: the
obligation row, its append-only fulfillment record, the balance write, the movement, and
the idempotency marker either commit together or not at all — and that a reservation moves
sold-in-possession while leaving the shelf alone (OWE-04), while a Kernel fulfillment moves
both together and a Council fulfillment moves neither (OWE-07). The pure half — the record
shape, the source/movement pairing, and the target arithmetic — is
``tests/unit/test_show_and_sell_we_owe_model.py``.

The scenario is one table at one event: four boxes of caramel assigned to it, priced at five
dollars, and a buyer who takes one Kernel now and is owed three, so the campaign's unassigned
stock is two and the OWE-04 reservation bound has something to bite on. The seeding helpers
are the Wave 5.2 sale lane's, because an obligation only exists as the child of a real sale:
seeding one directly would test this lane against a row the product cannot write.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

import pytest

from src.handlers.unit_operations import (
    CREATE_SALE_FIELD,
    FULFILL_WE_OWE_FIELD,
    RECORD_RECEIPT_FIELD,
    SET_WE_OWE_RESERVATION_FIELD,
    WE_OWE_OBLIGATION_FIELD,
    WE_OWE_OBLIGATIONS_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from src.utils import show_and_sell_models as ssm
from src.utils import show_and_sell_sale_models as sm
from tests.unit.show_sell_fixtures import account_id, assert_is_error, seed_show_sell_fixtures, unit_operation_event
from tests.unit.test_show_and_sell_sales import (  # the Wave 5.2 scenario: one table, one catalog
    ACTIVE_EVENT,
    CAMPAIGN,
    OTHER_PRODUCT,
    PRICE_CENTS,
    PRODUCT,
    SALE_AT,
    _line,
    _marker_rows,
    _movements,
    _obligation_rows,
    _offer_products,
    _sale_rows,
    _seed_allocation,
    _seed_balance,
    _seed_event,
    _seed_stock,
    _stored,
    _stored_allocation,
    _stored_balance,
    _stored_event,
    _stored_sale,
)

AVERY = account_id("Avery")
CREW_529_CAMPAIGN = "uc-crew-529-spring-2027"
BUYER = "Buyer Bee"
#: A second table in the same campaign, used only where a read filters by event.
RIVAL_ID = "SSE#rival-table"

#: The obligation's SDL fields, as the read answers them. ``check_show_and_sell_schema.test.ts``
#: pins the same list against the SDL, so a payload field that appears here and not there fails.
OBLIGATION_FIELDS = [
    "weOweId",
    "unitCampaignId",
    "showAndSellId",
    "saleId",
    "lineItemId",
    "buyerName",
    "productId",
    "productNameSnapshot",
    "originalQty",
    "fulfilledQty",
    "cancelledQty",
    "reservedQty",
    "remainingQty",
    "uncoveredQty",
    "valueCentsSnapshot",
    "status",
    "closeReason",
    "version",
    "createdAt",
    "closedAt",
]

FULFILLMENT_FIELDS = [
    "fulfillmentId",
    "weOweId",
    "quantity",
    "source",
    "inventoryMovementId",
    "actorAccountId",
    "createdAt",
]


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


def _owe_version(we_owe_id: str) -> int:
    """The obligation's current version, as a screen that just read it would hold it.

    Every accepted write moves it, so the tests that are not about a stale version read it
    back instead of tracking it by hand — and a version they track by hand is one they can
    get wrong without meaning to.
    """
    return int(sm.load_we_owe_by_id_or_not_found(we_owe_id)[sm.VERSION_ATTRIBUTE])


def _reserve(
    we_owe_id: str,
    target: Any,
    caller: Optional[str] = "Avery",
    *,
    version: Optional[int] = None,
    key: Optional[str] = None,
) -> Any:
    return _call(
        SET_WE_OWE_RESERVATION_FIELD,
        caller,
        mutation={
            "weOweId": we_owe_id,
            "targetReservedQty": target,
            **_version(_owe_version(we_owe_id) if version is None else version),
            **_idem(f"reserve-{uuid4()}" if key is None else key),
        },
    )


def _fulfill(
    we_owe_id: str,
    quantity: Any,
    source: Any,
    caller: Optional[str] = "Avery",
    *,
    version: Optional[int] = None,
    key: Optional[str] = None,
) -> Any:
    return _call(
        FULFILL_WE_OWE_FIELD,
        caller,
        mutation={
            "weOweId": we_owe_id,
            "quantity": quantity,
            "source": source,
            **_version(_owe_version(we_owe_id) if version is None else version),
            **_idem(f"fulfill-{uuid4()}" if key is None else key),
        },
    )


def _obligation(we_owe_id: Any, caller: Optional[str] = "Avery") -> Any:
    return _call(WE_OWE_OBLIGATION_FIELD, caller, arguments={"weOweId": we_owe_id})


def _obligations(caller: Optional[str] = "Avery", *, campaign: str = CAMPAIGN, **filters: Any) -> Any:
    arguments: Dict[str, Any] = {"unitCampaignId": campaign}
    arguments.update({name: value for name, value in filters.items() if value is not None})
    return _call(WE_OWE_OBLIGATIONS_FIELD, caller, arguments=arguments)


def _receipt(quantity: int = 4, caller: str = "Avery", *, key: str = "receipt-1") -> Any:
    return _call(
        RECORD_RECEIPT_FIELD,
        caller,
        mutation={"unitCampaignId": CAMPAIGN, "productId": PRODUCT, "quantity": quantity, **_idem(key)},
    )


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
    """The Stage 1 persona world plus the two tables the We Owe writes touch."""
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


def _seed_table(world: Dict[str, Any], *, physical: int = 6, rival: bool = False) -> None:
    """The running event with stock assigned to it, and a second event when a test wants one."""
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    if rival:
        _seed_event(world["show_and_sells"], RIVAL_ID)
    _seed_stock(world, physical=physical)


def _offer_second_product(world: Dict[str, Any], *event_ids: str, allocated: int = 4) -> None:
    """Give the campaign four boxes of the second product and assign them to these events."""
    _seed_balance(world["inventory"], OTHER_PRODUCT, physical=allocated)
    for event_id in event_ids:
        _seed_allocation(world["inventory"], event_id, OTHER_PRODUCT, allocated=allocated)


def _event_version(world: Dict[str, Any], event_id: str) -> int:
    """The event's current version, as a screen that just opened it would hold it.

    Each accepted sale moves the event row, so a test that sells twice at one table has to
    read the version back — the same optimistic-lock rule a stale write is there to enforce.
    """
    return int(_stored_event(world["show_and_sells"], event_id)[sm.VERSION_ATTRIBUTE])


def _sale(
    world: Dict[str, Any],
    *,
    event_id: str = ACTIVE_EVENT,
    product_id: str = PRODUCT,
    immediate: int = 1,
    we_owe: int = 3,
    buyer_name: str = BUYER,
    event_version: Optional[int] = None,
    key: str = "sale-1",
    caller: Optional[str] = "Avery",
    **extras: Any,
) -> Any:
    """Sell at this table through Wave 5.2's own entry, so the obligation is a real child row."""
    payload: Dict[str, Any] = {
        "showAndSellId": event_id,
        "saleAt": SALE_AT,
        "lineItems": [_line(product_id, immediate=immediate, we_owe=we_owe)],
        "paymentMethodCode": "CASH",
        "buyerName": buyer_name,
        **_version(_event_version(world, event_id) if event_version is None else event_version),
        **_idem(key),
    }
    payload.update(extras)
    return _call(CREATE_SALE_FIELD, caller, mutation=payload)


def _owed(world: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """One sale that owes three, with its answer asserted."""
    answer = _ok(_sale(world, **kwargs))
    assert len(answer["obligations"]) == 1
    return answer


def _owe_id(world: Dict[str, Any], **kwargs: Any) -> str:
    return str(_owed(world, **kwargs)["obligations"][0]["weOweId"])


# --- Storage reads ---------------------------------------------------------------


def _fulfillment_rows(show_and_sells_table: Any) -> List[Dict[str, Any]]:
    return [
        row for row in show_and_sells_table.scan()["Items"] if row.get("entityType") == sm.WE_OWE_FULFILLMENT_ENTITY_TYPE
    ]


def _movement_of(inventory_table: Any, kind: str) -> List[Dict[str, Any]]:
    return [row for row in _movements(inventory_table) if row[inv.MOVEMENT_TYPE_ATTRIBUTE] == kind]


def _movement_by_id(inventory_table: Any, movement_id: str) -> Optional[Dict[str, Any]]:
    rows = [row for row in _movements(inventory_table) if row.get(inv.MOVEMENT_ID_ATTRIBUTE) == movement_id]
    return dict(rows[0]) if len(rows) == 1 else None


def _markers_for(show_and_sells_table: Any, operation: str) -> List[Dict[str, Any]]:
    """One operation's idempotency markers.

    The sale that created the obligation writes its own marker in the same table, so counting
    every marker would charge this lane's write for a row another resolver committed.
    """
    return [row for row in _marker_rows(show_and_sells_table) if f"#{operation}#" in str(row.get("pk", ""))]


def _stored_owe(world: Dict[str, Any], we_owe_id: str) -> Dict[str, Any]:
    row = _stored(world["show_and_sells"], sm.we_owe_key(ACTIVE_EVENT, we_owe_id))
    assert row is not None, "the obligation row this test is about is gone"
    return row


# --- OWE-M-01-01, OWE-M-01-02: setWeOweReservation --------------------------------


def test_owe_m_01_01_a_partial_reservation_moves_possession_and_leaves_the_shelf_alone(
    world: Dict[str, Any],
) -> None:
    """OWE-M-01-01, OWE-04: reserved stock leaves sellable stock, never the Kernel's shelf."""
    _seed_table(world)
    we_owe_id = _owe_id(world)
    before = _stored_balance(world["inventory"], PRODUCT)
    assert (before[inv.KERNEL_PHYSICAL_QTY], before[inv.SOLD_IN_POSSESSION_QTY]) == (5, 0)

    answer = _ok(_reserve(we_owe_id, 2))

    obligation = answer["obligation"]
    assert (obligation["reservedQty"], obligation["remainingQty"], obligation["uncoveredQty"]) == (2, 3, 1)
    assert (obligation["version"], obligation["status"]) == (2, sm.WE_OWE_STATUS_OPEN)
    assert obligation["closeReason"] is None and obligation["closedAt"] is None

    balance = _stored_balance(world["inventory"], PRODUCT)
    assert (balance[inv.KERNEL_PHYSICAL_QTY], balance[inv.SOLD_IN_POSSESSION_QTY]) == (5, 2), "physical unchanged"
    assert balance[inv.VERSION_ATTRIBUTE] == 3
    position = answer["inventoryPosition"]
    assert (position["kernelPhysicalQty"], position["soldInPossessionQty"]) == (5, 2)
    assert position["sellableKernelQty"] == 3, "five on the shelf, two held for this buyer"

    reserves = _movement_of(world["inventory"], inv.WE_OWE_RESERVE)
    assert len(reserves) == 1
    movement = reserves[0]
    assert (movement[inv.SOLD_POSSESSION_DELTA], movement[inv.KERNEL_PHYSICAL_DELTA]) == (2, 0)
    assert movement[inv.WE_OWE_ID_ATTRIBUTE] == we_owe_id
    assert movement[inv.INVENTORY_VERSION_ATTRIBUTE] == 3, "the movement names the version this write produced"
    assert _movement_of(world["inventory"], inv.WE_OWE_RELEASE) == []
    assert len(_movements(world["inventory"])) == 2, "the sale's own movement plus this one, and no third"

    assert _stored_owe(world, we_owe_id)[sm.RESERVED_QTY_ATTRIBUTE] == 2
    allocation = _stored_allocation(world["inventory"], ACTIVE_EVENT)
    assert (allocation[inv.ALLOCATED_QTY], allocation[inv.SOLD_QTY], allocation[inv.REMAINING_QTY]) == (4, 1, 3)
    assert len(_markers_for(world["show_and_sells"], SET_WE_OWE_RESERVATION_FIELD)) == 1


def test_owe_m_01_02_targets_above_remaining_or_unassigned_are_refused_and_write_nothing(
    world: Dict[str, Any],
) -> None:
    """OWE-M-01-02: a reservation cannot promise more than is owed, nor stock someone else holds."""
    _seed_table(world)
    we_owe_id = _owe_id(world)

    above_remaining = assert_is_error(_reserve(we_owe_id, 4, key="reserve-over-remaining"), "CONFLICT")
    assert "still owed" in above_remaining["message"], above_remaining["message"]

    _ok(_reserve(we_owe_id, 2))
    above_unassigned = assert_is_error(_reserve(we_owe_id, 3, version=2, key="reserve-over-unassigned"), "CONFLICT")
    assert "unassigned" in above_unassigned["message"], above_unassigned["message"]

    for target in (-1, "two", None):
        assert_is_error(_reserve(we_owe_id, target, version=2, key=f"reserve-{target}"), "INVALID_INPUT")

    stored = _stored_owe(world, we_owe_id)
    assert (stored[sm.RESERVED_QTY_ATTRIBUTE], stored[sm.VERSION_ATTRIBUTE]) == (2, 2), "only the accepted write moved it"
    balance = _stored_balance(world["inventory"], PRODUCT)
    assert (balance[inv.SOLD_IN_POSSESSION_QTY], balance[inv.VERSION_ATTRIBUTE]) == (2, 3)
    assert len(_movement_of(world["inventory"], inv.WE_OWE_RESERVE)) == 1


def test_owe_m_01_02_target_zero_releases_the_reservation_without_reassigning_it(
    world: Dict[str, Any],
) -> None:
    """OWE-M-01-02: zero is a complete release, and released stock goes back to the pool, not to a buyer."""
    _seed_table(world)
    we_owe_id = _owe_id(world)
    _ok(_reserve(we_owe_id, 2))

    answer = _ok(_reserve(we_owe_id, 0, version=2))

    obligation = answer["obligation"]
    assert (obligation["reservedQty"], obligation["uncoveredQty"], obligation["version"]) == (0, 3, 3)
    assert obligation["status"] == sm.WE_OWE_STATUS_OPEN, "the obligation still owes three"
    balance = _stored_balance(world["inventory"], PRODUCT)
    assert (balance[inv.KERNEL_PHYSICAL_QTY], balance[inv.SOLD_IN_POSSESSION_QTY]) == (5, 0)

    releases = _movement_of(world["inventory"], inv.WE_OWE_RELEASE)
    assert len(releases) == 1
    assert releases[0][inv.SOLD_POSSESSION_DELTA] == -2
    assert releases[0][inv.WE_OWE_ID_ATTRIBUTE] == we_owe_id
    assert len(_movement_of(world["inventory"], inv.WE_OWE_RESERVE)) == 1, "the reserve and the release are two rows"
    allocation = _stored_allocation(world["inventory"], ACTIVE_EVENT)
    assert (allocation[inv.ALLOCATED_QTY], allocation[inv.SOLD_QTY], allocation[inv.RELEASED_QTY]) == (4, 1, 0)


def test_a_reservation_retry_whose_obligation_is_gone_answers_not_found(world: Dict[str, Any]) -> None:
    """A retry of a committed write whose obligation row is gone is answered by the tenant gate.

    The marker and the obligation commit together, so a missing obligation is out-of-band
    corruption rather than a caller's error — but the row genuinely does not exist, so the
    read that gates every We Owe write answers ``NOT_FOUND`` for it, and the retry writes
    nothing. The narrow loader path behind it raises an internal fault when it is consulted
    (see ``tests/unit/test_show_and_sell_we_owe_model.py``).
    """
    _seed_table(world)
    we_owe_id = _owe_id(world)
    _ok(_reserve(we_owe_id, 1, version=1, key="reserve-1"))

    markers = [
        row
        for row in _markers_for(world["show_and_sells"], SET_WE_OWE_RESERVATION_FIELD)
        if row["sk"] == "IDEM#reserve-1"
    ]
    assert len(markers) == 1
    world["show_and_sells"].update_item(
        Key={"pk": markers[0]["pk"], "sk": markers[0]["sk"]},
        UpdateExpression="REMOVE resultPayload",
    )
    world["show_and_sells"].delete_item(Key=sm.we_owe_key(ACTIVE_EVENT, we_owe_id))

    error = assert_is_error(_reserve(we_owe_id, 1, version=1, key="reserve-1"), "NOT_FOUND")
    assert "obligation not found" in error["message"]
    assert len(_movement_of(world["inventory"], inv.WE_OWE_RESERVE)) == 1, "the retry does not write a second movement"


def test_an_equal_reservation_target_writes_no_movement_and_moves_no_stock(world: Dict[str, Any]) -> None:
    """§4.4.2: a target is a statement about the whole reservation, so repeating it moves nothing."""
    _seed_table(world)
    we_owe_id = _owe_id(world)
    first = _ok(_reserve(we_owe_id, 2))

    again = _ok(_reserve(we_owe_id, 2, version=2, key="reserve-2"))

    assert again["obligation"]["reservedQty"] == 2
    assert first["obligation"]["version"] == 2
    assert len(_movement_of(world["inventory"], inv.WE_OWE_RESERVE)) == 1, "no second movement for one reservation"
    assert _movement_of(world["inventory"], inv.WE_OWE_RELEASE) == []
    assert _stored_balance(world["inventory"], PRODUCT)[inv.SOLD_IN_POSSESSION_QTY] == 2


def test_owe_m_01_03_reservation_is_guarded_by_tenancy_a_stale_version_and_replay(
    world: Dict[str, Any],
) -> None:
    """OWE-M-01-03, AUTH-U, VER-01, IDEM: one obligation, one writer at a time, one answer per key."""
    _seed_table(world)
    we_owe_id = _owe_id(world)

    for persona in ("Blake", "Taylor", "Devon", "Riley", "Emery"):
        assert_is_error(_reserve(we_owe_id, 1, persona, key=f"reserve-{persona}"), "NOT_FOUND")
    assert_is_error(_reserve(we_owe_id, 1, None, key="reserve-anon"), "UNAUTHORIZED")

    race = assert_is_error(_reserve(we_owe_id, 1, version=9, key="reserve-stale"), "CONFLICT")
    assert "changed since you read it" in race["message"], race["message"]
    assert _stored_owe(world, we_owe_id)[sm.VERSION_ATTRIBUTE] == 1

    first = _ok(_reserve(we_owe_id, 2, version=1, key="reserve-1"))
    replay = _ok(_reserve(we_owe_id, 2, version=1, key="reserve-1"))
    assert replay == first, "a retry answers the write that committed, with no second effect"
    assert len(_markers_for(world["show_and_sells"], SET_WE_OWE_RESERVATION_FIELD)) == 1, (
        "one reservation, one marker, one movement"
    )
    assert len(_movement_of(world["inventory"], inv.WE_OWE_RESERVE)) == 1
    assert _stored_balance(world["inventory"], PRODUCT)[inv.SOLD_IN_POSSESSION_QTY] == 2
    assert _stored_owe(world, we_owe_id)[sm.VERSION_ATTRIBUTE] == 2

    assert_is_error(_reserve(we_owe_id, 1, key="reserve-1"), "INVALID_INPUT")
    assert _stored_owe(world, we_owe_id)[sm.RESERVED_QTY_ATTRIBUTE] == 2, "the refused retry changed nothing"


def test_owe_05_a_new_receipt_never_reserves_stock_for_an_older_obligation(world: Dict[str, Any]) -> None:
    """OWE-05: receipts raise the shelf; only an admin's reservation write moves an obligation's holding."""
    _seed_table(world)
    we_owe_id = _owe_id(world)
    _ok(_reserve(we_owe_id, 2))

    _ok(_receipt(4))

    stored = _stored_owe(world, we_owe_id)
    assert (stored[sm.RESERVED_QTY_ATTRIBUTE], stored[sm.UNCOVERED_QTY_ATTRIBUTE]) == (2, 1), (
        "four more boxes arrived and nothing was claimed for this buyer"
    )
    assert len(_movement_of(world["inventory"], inv.WE_OWE_RESERVE)) == 1

    answer = _ok(_reserve(we_owe_id, 3, version=2, key="reserve-2"))
    assert (answer["obligation"]["reservedQty"], answer["obligation"]["uncoveredQty"]) == (3, 0), (
        "the bound reads live stock, so the new receipt is what made a third unit reservable"
    )


# --- OWE-M-02-01, OWE-M-02-02: fulfillWeOwe --------------------------------------


def test_owe_m_02_01_a_partial_kernel_fulfillment_moves_both_stock_terms_and_leaves_the_sale_alone(
    world: Dict[str, Any],
) -> None:
    """OWE-M-02-01, OWE-07, OWE-03: the shelf and the sold-in-our-possession count leave together."""
    _seed_table(world)
    created = _owed(world)
    we_owe_id = created["obligations"][0]["weOweId"]
    sale_id = created["sale"]["saleId"]
    _ok(_reserve(we_owe_id, 2))

    answer = _ok(_fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_KERNEL, version=2))

    obligation = answer["obligation"]
    assert (
        obligation["originalQty"],
        obligation["fulfilledQty"],
        obligation["reservedQty"],
        obligation["remainingQty"],
        obligation["uncoveredQty"],
    ) == (3, 1, 1, 2, 1)
    assert (obligation["status"], obligation["closeReason"], obligation["version"]) == (
        sm.WE_OWE_STATUS_OPEN,
        None,
        3,
    )

    balance = _stored_balance(world["inventory"], PRODUCT)
    assert (balance[inv.KERNEL_PHYSICAL_QTY], balance[inv.SOLD_IN_POSSESSION_QTY]) == (4, 1)
    assert (balance[inv.VERSION_ATTRIBUTE], balance[inv.KERNEL_PHYSICAL_QTY]) == (4, 4)
    position = answer["inventoryPosition"]
    assert (position["kernelPhysicalQty"], position["soldInPossessionQty"]) == (4, 1)

    record = answer["fulfillment"]
    assert (record["quantity"], record["source"]) == (1, sm.WE_OWE_SOURCE_KERNEL)
    assert record["weOweId"] == we_owe_id and record["actorAccountId"] == AVERY
    assert record["inventoryMovementId"]

    fulfills = _movement_of(world["inventory"], inv.WE_OWE_FULFILL)
    assert len(fulfills) == 1
    movement = fulfills[0]
    assert (movement[inv.KERNEL_PHYSICAL_DELTA], movement[inv.SOLD_POSSESSION_DELTA]) == (-1, -1)
    assert movement[inv.WE_OWE_ID_ATTRIBUTE] == we_owe_id
    assert movement[inv.FULFILLMENT_ID_ATTRIBUTE] == record["fulfillmentId"], (
        "the fulfillment record and the movement name each other"
    )
    assert _movement_of(world["inventory"], inv.WE_OWE_RELEASE) == [], "no second movement for the same units"

    rows = _fulfillment_rows(world["show_and_sells"])
    assert len(rows) == 1
    assert rows[0]["sk"] == f"WE_OWE#{we_owe_id}#FULFILLMENT#{record['fulfillmentId']}"
    assert sm.VERSION_ATTRIBUTE not in rows[0], "history is append-only"
    assert sm.UNIT_CAMPAIGN_ID_ATTRIBUTE not in rows[0] and sm.STATUS_ATTRIBUTE not in rows[0], (
        "a history row in unitCampaignId-status-index would answer a We Owe list with rows that owe nothing"
    )

    sale = _stored_sale(world["show_and_sells"], ACTIVE_EVENT, sale_id)
    assert sale is not None and (sale[sm.REVISION_ATTRIBUTE], sale[sm.STATUS_ATTRIBUTE]) == (1, sm.SALE_STATUS_ACTIVE)
    assert len(_sale_rows(world["show_and_sells"])) == 1, "a fulfillment creates no second sale (OWE-03)"


def test_owe_m_02_02_an_external_fulfillment_closes_the_uncovered_part_and_moves_no_stock(
    world: Dict[str, Any],
) -> None:
    """OWE-M-02-02: a Council supplies what no Kernel is promised to, and no Unit quantity changes."""
    _seed_table(world)
    we_owe_id = _owe_id(world)
    balance_before = dict(_stored_balance(world["inventory"], PRODUCT))

    answer = _ok(_fulfill(we_owe_id, 2, sm.WE_OWE_SOURCE_EXTERNAL))

    obligation = answer["obligation"]
    assert (obligation["fulfilledQty"], obligation["remainingQty"], obligation["uncoveredQty"]) == (2, 1, 1)
    assert obligation["reservedQty"] == 0
    assert "inventoryPosition" not in answer, "a position would report a stock effect that did not happen"

    record = answer["fulfillment"]
    assert record["source"] == sm.WE_OWE_SOURCE_EXTERNAL and record["inventoryMovementId"] is None
    assert _stored_balance(world["inventory"], PRODUCT) == balance_before, "the balance did not move at all"
    assert len(_movements(world["inventory"])) == 1, "only the sale's own movement"
    assert _movement_of(world["inventory"], inv.WE_OWE_FULFILL) == []


def test_owe_m_02_02_a_covered_quantity_must_be_released_before_a_council_may_supply_it(
    world: Dict[str, Any],
) -> None:
    """OWE-M-02-02, OWE-07: the Council cannot deliver a unit the Kernel has already set aside."""
    _seed_table(world)
    we_owe_id = _owe_id(world)
    _ok(_reserve(we_owe_id, 2))

    covered = assert_is_error(_fulfill(we_owe_id, 2, sm.WE_OWE_SOURCE_EXTERNAL, version=2, key="fulfill-1"), "CONFLICT")
    assert "release the reservation" in covered["message"], covered["message"]
    assert _fulfillment_rows(world["show_and_sells"]) == []

    uncovered_only = _ok(_fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_EXTERNAL, version=2, key="fulfill-2"))
    assert (uncovered_only["obligation"]["remainingQty"], uncovered_only["obligation"]["reservedQty"]) == (2, 2)
    assert (uncovered_only["obligation"]["status"], uncovered_only["obligation"]["remainingQty"]) == (
        sm.WE_OWE_STATUS_OPEN,
        2,
    )

    still_covered = assert_is_error(_fulfill(we_owe_id, 2, sm.WE_OWE_SOURCE_EXTERNAL, version=3, key="fulfill-3"), "CONFLICT")
    assert "uncovered" in still_covered["message"], still_covered["message"]

    _ok(_reserve(we_owe_id, 0, version=3, key="reserve-release"))
    settled = _ok(_fulfill(we_owe_id, 2, sm.WE_OWE_SOURCE_EXTERNAL, version=4, key="fulfill-4"))

    obligation = settled["obligation"]
    assert (obligation["fulfilledQty"], obligation["remainingQty"], obligation["reservedQty"]) == (3, 0, 0)
    assert (obligation["status"], obligation["closeReason"]) == (sm.WE_OWE_STATUS_CLOSED, sm.WE_OWE_CLOSE_FULFILLED)
    assert obligation["closedAt"]
    assert len(_fulfillment_rows(world["show_and_sells"])) == 2
    assert _stored_balance(world["inventory"], PRODUCT)[inv.SOLD_IN_POSSESSION_QTY] == 0


def test_owe_m_02_03_an_obligation_closes_only_at_zero_remaining_and_zero_reserved(
    world: Dict[str, Any],
) -> None:
    """OWE-M-02-03, OWE-09: partial fulfillment is the normal case; closure needs both numbers at zero."""
    _seed_table(world)
    we_owe_id = _owe_id(world, we_owe=2)
    _ok(_reserve(we_owe_id, 2))

    half = _ok(_fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_KERNEL, version=2))
    assert (half["obligation"]["remainingQty"], half["obligation"]["reservedQty"]) == (1, 1)
    assert (half["obligation"]["status"], half["obligation"]["closeReason"], half["obligation"]["closedAt"]) == (
        sm.WE_OWE_STATUS_OPEN,
        None,
        None,
    )

    settled = _ok(_fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_KERNEL, version=3, key="fulfill-2"))
    obligation = settled["obligation"]
    assert (obligation["fulfilledQty"], obligation["remainingQty"], obligation["reservedQty"]) == (2, 0, 0)
    assert (obligation["status"], obligation["closeReason"]) == (sm.WE_OWE_STATUS_CLOSED, sm.WE_OWE_CLOSE_FULFILLED)
    assert obligation["closedAt"]

    balance = _stored_balance(world["inventory"], PRODUCT)
    assert (balance[inv.KERNEL_PHYSICAL_QTY], balance[inv.SOLD_IN_POSSESSION_QTY]) == (3, 0)
    assert len(_movement_of(world["inventory"], inv.WE_OWE_FULFILL)) == 2
    assert len(_fulfillment_rows(world["show_and_sells"])) == 2

    assert_is_error(_reserve(we_owe_id, 1, version=4, key="reserve-closed"), "CONFLICT")
    refused = assert_is_error(
        _fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_KERNEL, version=4, key="fulfill-closed"), "CONFLICT"
    )
    assert "closed" in refused["message"], refused["message"]
    assert len(_fulfillment_rows(world["show_and_sells"])) == 2, "a closed obligation takes no further write"


def test_owe_m_02_03_excess_quantity_a_bad_source_and_a_stale_version_write_nothing(
    world: Dict[str, Any],
) -> None:
    """OWE-M-02-03: every refusal lands before a write, and the trail is what it was before the call."""
    _seed_table(world)
    we_owe_id = _owe_id(world)

    above_remaining = assert_is_error(_fulfill(we_owe_id, 4, sm.WE_OWE_SOURCE_KERNEL), "CONFLICT")
    assert "owes 3 more" in above_remaining["message"], above_remaining["message"]

    assert_is_error(_fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_KERNEL, key="fulfill-no-reserve"), "CONFLICT")
    assert_is_error(_fulfill(we_owe_id, 1, "SCOUT_CUSTODY", key="fulfill-source"), "INVALID_INPUT")
    assert_is_error(_fulfill(we_owe_id, 0, sm.WE_OWE_SOURCE_EXTERNAL, key="fulfill-zero"), "INVALID_INPUT")
    assert_is_error(
        _fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_EXTERNAL, version="x", key="fulfill-junk-version"), "INVALID_INPUT"
    )
    stale = assert_is_error(
        _fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_EXTERNAL, version=9, key="fulfill-stale"), "CONFLICT"
    )
    assert "changed since you read it" in stale["message"], stale["message"]

    stored = _stored_owe(world, we_owe_id)
    assert (stored[sm.FULFILLED_QTY_ATTRIBUTE], stored[sm.VERSION_ATTRIBUTE]) == (0, 1)
    assert _fulfillment_rows(world["show_and_sells"]) == []
    assert _movement_of(world["inventory"], inv.WE_OWE_FULFILL) == []
    assert _stored_balance(world["inventory"], PRODUCT)[inv.VERSION_ATTRIBUTE] == 2

    _ok(_reserve(we_owe_id, 1, key="reserve-2"))
    kernel_above = assert_is_error(
        _fulfill(we_owe_id, 2, sm.WE_OWE_SOURCE_KERNEL, version=2, key="fulfill-over"), "CONFLICT"
    )
    assert "reserved for this obligation" in kernel_above["message"], kernel_above["message"]
    assert _fulfillment_rows(world["show_and_sells"]) == []


def test_idem_a_fulfillment_retry_answers_the_record_that_committed(world: Dict[str, Any]) -> None:
    """IDEM: the retry's answer is the same record, so one delivery is never counted twice."""
    _seed_table(world)
    we_owe_id = _owe_id(world)
    _ok(_reserve(we_owe_id, 2))

    first = _ok(_fulfill(we_owe_id, 2, sm.WE_OWE_SOURCE_KERNEL, version=2, key="fulfill-1"))
    replay = _ok(_fulfill(we_owe_id, 2, sm.WE_OWE_SOURCE_KERNEL, version=2, key="fulfill-1"))

    assert replay == first
    assert first["fulfillment"]["fulfillmentId"] == replay["fulfillment"]["fulfillmentId"]
    assert len(_fulfillment_rows(world["show_and_sells"])) == 1
    assert len(_movement_of(world["inventory"], inv.WE_OWE_FULFILL)) == 1
    balance = _stored_balance(world["inventory"], PRODUCT)
    assert (balance[inv.KERNEL_PHYSICAL_QTY], balance[inv.SOLD_IN_POSSESSION_QTY]) == (3, 0)
    assert _stored_owe(world, we_owe_id)[sm.VERSION_ATTRIBUTE] == 3

    assert_is_error(_fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_KERNEL, version=3, key="fulfill-1"), "INVALID_INPUT")
    assert len(_fulfillment_rows(world["show_and_sells"])) == 1


def test_a_fulfillment_retry_whose_record_is_gone_is_an_internal_fault(world: Dict[str, Any]) -> None:
    """A completed marker replays its stored answer; a back-fill that died has to load the record.

    The record and the obligation commit together, so a missing record on that narrow path is
    an internal fault, not a caller's error — and the retry must not write a second record.
    """
    _seed_table(world)
    we_owe_id = _owe_id(world)
    _ok(_reserve(we_owe_id, 1))
    first = _ok(_fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_KERNEL, version=2, key="fulfill-1"))

    markers = [
        row
        for row in _markers_for(world["show_and_sells"], FULFILL_WE_OWE_FIELD)
        if row["sk"] == "IDEM#fulfill-1"
    ]
    assert len(markers) == 1, "the write's marker is in the same table as the obligation"
    world["show_and_sells"].update_item(
        Key={"pk": markers[0]["pk"], "sk": markers[0]["sk"]},
        UpdateExpression="REMOVE resultPayload",
    )
    world["show_and_sells"].delete_item(
        Key=sm.we_owe_fulfillment_key(ACTIVE_EVENT, we_owe_id, first["fulfillment"]["fulfillmentId"])
    )

    error = assert_is_error(_fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_KERNEL, version=2, key="fulfill-1"), "INTERNAL_ERROR")
    assert "could not be loaded" in error["message"]
    assert _fulfillment_rows(world["show_and_sells"]) == [], "the retry does not write a second record"
    assert len(_movement_of(world["inventory"], inv.WE_OWE_FULFILL)) == 1


# --- OWE-Q-01: the two reads -----------------------------------------------------


def test_owe_q_01_01_the_direct_read_answers_the_obligation_and_its_history_oldest_first(
    world: Dict[str, Any],
) -> None:
    """OWE-Q-01: origin links, versions, covered/uncovered, and the fulfillment trail behind them."""
    _seed_table(world)
    created = _owed(world, buyerPhone="303-555-0100", buyerEmail="bee@example.test")
    we_owe_id = created["obligations"][0]["weOweId"]
    sale_id = created["sale"]["saleId"]
    line_id = created["sale"]["lineItems"][0]["lineItemId"]

    _ok(_reserve(we_owe_id, 2))
    kernel = _ok(_fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_KERNEL, version=2))["fulfillment"]
    _ok(_reserve(we_owe_id, 0, version=3, key="reserve-2"))
    external = _ok(_fulfill(we_owe_id, 2, sm.WE_OWE_SOURCE_EXTERNAL, version=4, key="fulfill-2"))["fulfillment"]

    answer = _ok(_obligation(we_owe_id))

    obligation = answer["obligation"]
    assert (obligation["weOweId"], obligation["saleId"], obligation["lineItemId"]) == (we_owe_id, sale_id, line_id)
    assert obligation["showAndSellId"] == ACTIVE_EVENT and obligation["unitCampaignId"] == CAMPAIGN
    assert obligation["buyerName"] == BUYER and obligation["productNameSnapshot"] == "Caramel 1"
    assert obligation["productId"] == PRODUCT
    assert obligation["valueCentsSnapshot"] == 3 * PRICE_CENTS, "the owed quantity at the sale's snapshot price"
    assert (
        obligation["originalQty"],
        obligation["fulfilledQty"],
        obligation["cancelledQty"],
        obligation["reservedQty"],
        obligation["remainingQty"],
        obligation["uncoveredQty"],
    ) == (3, 3, 0, 0, 0, 0)
    assert (obligation["status"], obligation["closeReason"], obligation["version"]) == (
        sm.WE_OWE_STATUS_CLOSED,
        sm.WE_OWE_CLOSE_FULFILLED,
        5,
    )
    assert set(obligation) == set(OBLIGATION_FIELDS), "no due date, no aging, no assignee (OWE-10)"

    history = answer["fulfillments"]
    assert [item["source"] for item in history] == [sm.WE_OWE_SOURCE_KERNEL, sm.WE_OWE_SOURCE_EXTERNAL]
    assert [item["createdAt"] for item in history] == sorted(item["createdAt"] for item in history)
    assert [item["fulfillmentId"] for item in history] == [kernel["fulfillmentId"], external["fulfillmentId"]]
    assert history[0]["quantity"] == 1 and history[1]["quantity"] == 2

    stored_movement = _movement_by_id(world["inventory"], kernel["inventoryMovementId"])
    assert stored_movement is not None, "the Kernel fulfillment names the movement that moved the stock"
    assert stored_movement[inv.MOVEMENT_TYPE_ATTRIBUTE] == inv.WE_OWE_FULFILL
    assert history[1]["inventoryMovementId"] is None, "the Council moved nothing, so it names nothing"

    for item in history:
        assert set(item) == set(FULFILLMENT_FIELDS)
        assert "buyerName" not in item and "dueDate" not in item and "assigneeId" not in item


def test_the_direct_read_addresses_the_obligation_and_not_its_history_by_id(
    world: Dict[str, Any],
) -> None:
    """§6.4: ``weOweId-index`` holds the obligation and its records, so the marker picks the aggregate."""
    _seed_table(world)
    we_owe_id = _owe_id(world)
    _ok(_reserve(we_owe_id, 1))
    _ok(_fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_KERNEL, version=2))

    index_rows = [row for row in world["show_and_sells"].scan()["Items"] if row.get(sm.WE_OWE_ID_ATTRIBUTE) == we_owe_id]
    assert len(index_rows) == 2, "the obligation and its one fulfillment share the weOweId index key"

    answer = _ok(_obligation(we_owe_id))
    assert answer["obligation"]["weOweId"] == we_owe_id
    assert answer["obligation"]["status"] == sm.WE_OWE_STATUS_OPEN, "two of the three are still owed"
    assert len(answer["fulfillments"]) == 1, "the record sharing the index key is the history, not the aggregate"

    obligations = ssm.event_we_owe_rows(ACTIVE_EVENT)
    assert len(obligations) == 1 and obligations[0][sm.WE_OWE_ID_ATTRIBUTE] == we_owe_id, (
        "the event's obligation read answers obligations, never audit history"
    )


def test_owe_q_01_01_the_list_reports_every_number_a_report_adds_up_and_no_history(
    world: Dict[str, Any],
) -> None:
    """OWE-Q-01: the rows are the report — covered is ``reservedQty``, uncovered is on the row."""
    _seed_table(world, rival=True)
    _offer_second_product(world, ACTIVE_EVENT, RIVAL_ID, allocated=4)

    one = _owed(world)
    we_owe_one = one["obligations"][0]["weOweId"]
    two = _owed(world, product_id=OTHER_PRODUCT, buyer_name="Buttercup", key="sale-2")
    we_owe_two = two["obligations"][0]["weOweId"]
    three = _owed(world, event_id=RIVAL_ID, product_id=OTHER_PRODUCT, buyer_name="Carol Chen", key="sale-3")
    we_owe_three = three["obligations"][0]["weOweId"]

    _ok(_reserve(we_owe_one, 2))
    _ok(_fulfill(we_owe_one, 1, sm.WE_OWE_SOURCE_KERNEL, version=2))
    _ok(_fulfill(we_owe_three, 3, sm.WE_OWE_SOURCE_EXTERNAL, key="fulfill-3"))

    page = _ok(_obligations())

    assert [item["weOweId"] for item in page["items"]] == [we_owe_two, we_owe_one, we_owe_three], (
        "open obligations first, newest first inside each state, then the closed one"
    )
    partial = page["items"][1]
    assert (partial["reservedQty"], partial["remainingQty"], partial["uncoveredQty"]) == (1, 2, 1)
    assert partial["status"] == sm.WE_OWE_STATUS_OPEN
    closed = page["items"][2]
    assert (closed["status"], closed["closeReason"], closed["remainingQty"]) == (
        sm.WE_OWE_STATUS_CLOSED,
        sm.WE_OWE_CLOSE_FULFILLED,
        0,
    )

    for item in page["items"]:
        assert set(item) == set(OBLIGATION_FIELDS), "a list row carries no fulfillment history and no totals"
    assert set(page) == {"items", "pageInfo"}, "no server-side totals for the browser to disagree with"


def test_owe_q_01_01_filters_select_by_state_event_product_and_buyer(world: Dict[str, Any]) -> None:
    """OWE-Q-01: partial fulfillment keeps an obligation in the OPEN list, with its quantities."""
    _seed_table(world, rival=True)
    _offer_second_product(world, ACTIVE_EVENT, RIVAL_ID, allocated=4)

    one = _owed(world)
    we_owe_one = one["obligations"][0]["weOweId"]
    two = _owed(world, product_id=OTHER_PRODUCT, buyer_name="Buttercup", key="sale-2")
    we_owe_two = two["obligations"][0]["weOweId"]
    three = _owed(world, event_id=RIVAL_ID, product_id=OTHER_PRODUCT, buyer_name="Carol Chen", key="sale-3")
    we_owe_three = three["obligations"][0]["weOweId"]

    _ok(_fulfill(we_owe_two, 1, sm.WE_OWE_SOURCE_EXTERNAL))
    _ok(_fulfill(we_owe_three, 3, sm.WE_OWE_SOURCE_EXTERNAL, key="fulfill-3"))

    assert [i["weOweId"] for i in _ok(_obligations(status="OPEN"))["items"]] == [we_owe_two, we_owe_one]
    assert [i["weOweId"] for i in _ok(_obligations(status="CLOSED"))["items"]] == [we_owe_three]
    assert_is_error(_obligations(status="PARTIALLY_FULFILLED"), "INVALID_INPUT")

    assert [i["weOweId"] for i in _ok(_obligations(showAndSellId=RIVAL_ID))["items"]] == [we_owe_three]
    assert [i["weOweId"] for i in _ok(_obligations(productId=OTHER_PRODUCT))["items"]] == [we_owe_two, we_owe_three], (
        "the product filter keeps the state-first order: the open obligation before the settled one"
    )
    assert [i["weOweId"] for i in _ok(_obligations(productId=OTHER_PRODUCT, status="OPEN"))["items"]] == [we_owe_two]

    assert [i["weOweId"] for i in _ok(_obligations(buyerName=BUYER))["items"]] == [we_owe_one]
    assert [i["weOweId"] for i in _ok(_obligations(buyerName=BUYER.lower()))["items"]] == [], "an exact match is exact"
    assert [i["weOweId"] for i in _ok(_obligations(buyerNamePrefix="but"))["items"]] == [we_owe_two]
    assert [i["weOweId"] for i in _ok(_obligations(buyerNamePrefix="CAROL"))["items"]] == [we_owe_three]
    assert [i["weOweId"] for i in _ok(_obligations(buyerName="Nobody"))["items"]] == []

    partial = [item for item in _ok(_obligations(buyerName="Buttercup"))["items"] if item["weOweId"] == we_owe_two][0]
    assert (partial["fulfilledQty"], partial["remainingQty"], partial["uncoveredQty"]) == (1, 2, 2), (
        "the Council delivered one without a reservation, so both remaining units are uncovered"
    )

    assert_is_error(_obligations(buyerName=""), "INVALID_INPUT"), "an empty filter is a refusal, not every row"
    assert_is_error(_obligations(productId=""), "INVALID_INPUT")
    assert _ok(_obligations(showAndSellId="SSE#never-created"))["items"] == [], (
        "a filter on an event this campaign never held selects nothing; it is not an error and not every row"
    )

def test_page_01_obligation_pages_are_complete_ordered_and_scoped_to_their_filters(
    world: Dict[str, Any],
) -> None:
    """PAGE-01: a cursor continues one specific result set — the campaign and its filters."""
    _seed_table(world)
    _offer_second_product(world, ACTIVE_EVENT, allocated=6)

    oldest = _owe_id(world)
    middle = _owe_id(world, product_id=OTHER_PRODUCT, buyer_name="Buyer 2", key="sale-2")
    newest = _owe_id(world, product_id=OTHER_PRODUCT, buyer_name="Buyer 3", key="sale-3")

    first = _ok(_obligations(page={"limit": 1}))
    assert [item["weOweId"] for item in first["items"]] == [newest]
    assert first["pageInfo"]["hasNextPage"] is True and first["pageInfo"]["endCursor"]

    second = _ok(_obligations(page={"limit": 1, "cursor": first["pageInfo"]["endCursor"]}))
    assert [item["weOweId"] for item in second["items"]] == [middle]
    tail = _ok(_obligations(page={"limit": 1, "cursor": second["pageInfo"]["endCursor"]}))
    assert [item["weOweId"] for item in tail["items"]] == [oldest]
    assert tail["pageInfo"]["hasNextPage"] is False and tail["pageInfo"]["endCursor"] is None

    filtered = _ok(_obligations(productId=OTHER_PRODUCT, page={"limit": 1}))
    assert [item["weOweId"] for item in filtered["items"]] == [newest]
    assert filtered["pageInfo"]["hasNextPage"] is True
    cursor = filtered["pageInfo"]["endCursor"]
    assert _ok(_obligations(productId=OTHER_PRODUCT, page={"limit": 1, "cursor": cursor}))["items"][0]["weOweId"] == middle

    assert_is_error(_obligations(page={"limit": 1, "cursor": cursor}), "INVALID_INPUT")
    assert_is_error(_obligations(buyerName="Buyer 2", page={"limit": 1, "cursor": cursor}), "INVALID_INPUT")
    assert_is_error(_obligations(productId=PRODUCT, page={"limit": 1, "cursor": cursor}), "INVALID_INPUT")
    assert_is_error(_obligations(page={"limit": 1, "cursor": "bm90LWEtY3Vyc29y"}), "INVALID_INPUT")
    assert_is_error(_obligations(page={"limit": 101}), "INVALID_INPUT")


def test_owe_q_01_02_tenancy_is_the_obligations_row_and_the_buyer_is_only_a_name(
    world: Dict[str, Any],
) -> None:
    """AUTH-U plus the privacy rule: an unknown id and a foreign id give the same answer."""
    _seed_table(world)
    we_owe_id = _owe_id(world, buyerPhone="303-555-0100", buyerEmail="bee@example.test")
    _ok(_reserve(we_owe_id, 1))
    _ok(_fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_KERNEL))

    for persona in ("Blake", "Taylor", "Devon", "Riley", "Emery"):
        assert_is_error(_obligation(we_owe_id, persona), "NOT_FOUND")
        assert_is_error(_obligations(persona), "NOT_FOUND")
        assert_is_error(_reserve(we_owe_id, 1, persona, key=f"reserve-{persona}"), "NOT_FOUND")
        assert_is_error(_fulfill(we_owe_id, 1, sm.WE_OWE_SOURCE_EXTERNAL, persona, key=f"fulfill-{persona}"), "NOT_FOUND")
    assert_is_error(_obligation(we_owe_id, None), "UNAUTHORIZED")
    assert_is_error(_obligations(None), "UNAUTHORIZED")

    assert_is_error(_obligation("00000000-0000-4000-8000-000000000000"), "NOT_FOUND")
    assert_is_error(_obligation("#"), "INVALID_INPUT")

    other_campaign = _ok(_obligations("Avery", campaign=CREW_529_CAMPAIGN))
    assert other_campaign["items"] == [], (
        "Avery administers Crew 529 too, and its obligation list is its own — Pack 3149's never appear there"
    )

    for row in _obligation_rows(world["show_and_sells"]) + _fulfillment_rows(world["show_and_sells"]):
        assert sm.BUYER_PHONE_ATTRIBUTE not in row and sm.BUYER_EMAIL_ATTRIBUTE not in row, (
            "the sale carries contact detail; the obligation a We Owe list shows carries the name"
        )
    answer = _ok(_obligation(we_owe_id))
    assert "buyerPhone" not in answer["obligation"] and "buyerEmail" not in answer["obligation"]
    assert [item["actorAccountId"] for item in answer["fulfillments"]] == [AVERY]


def test_owe_q_01_02_two_products_one_campaign_never_share_a_read(world: Dict[str, Any]) -> None:
    """OWE-Q-01-02: the campaign's obligations are listed by row, not by a second product's rows."""
    _seed_table(world)
    _offer_second_product(world, ACTIVE_EVENT, allocated=4)

    caramel = _owe_id(world)
    other = _owe_id(world, product_id=OTHER_PRODUCT, buyer_name="Buttercup", key="sale-2")

    _ok(_reserve(caramel, 1))
    _ok(_fulfill(other, 2, sm.WE_OWE_SOURCE_EXTERNAL))

    listed = _ok(_obligations())["items"]
    assert [item["weOweId"] for item in listed] == [other, caramel], "both are open, so newest first"
    assert [item["productId"] for item in listed] == [OTHER_PRODUCT, PRODUCT]
    assert [item["productNameSnapshot"] for item in listed] == ["Caramel 2", "Caramel 1"]
    assert _stored_balance(world["inventory"], PRODUCT)[inv.SOLD_IN_POSSESSION_QTY] == 1
    assert _stored_balance(world["inventory"], OTHER_PRODUCT)[inv.SOLD_IN_POSSESSION_QTY] == 0, (
        "the Council supplied the second obligation, so its possession count never moved"
    )

    only_other = _ok(_obligations(productId=OTHER_PRODUCT))["items"]
    assert [item["weOweId"] for item in only_other] == [other]
    assert _ok(_obligation(other))["obligation"]["productId"] == OTHER_PRODUCT
    assert _ok(_obligation(caramel))["obligation"]["productId"] == PRODUCT


def test_an_obligation_is_not_readable_through_another_campaigns_id(world: Dict[str, Any]) -> None:
    """Tenancy is the obligation's own row: a foreign caller cannot reach it by id, or by list."""
    _seed_table(world)
    we_owe_id = _owe_id(world)
    _ok(_reserve(we_owe_id, 1))

    foreign = _obligation_rows(world["show_and_sells"])[0]
    assert foreign[sm.UNIT_CAMPAIGN_ID_ATTRIBUTE] == CAMPAIGN

    assert_is_error(_obligations("Riley", campaign=CREW_529_CAMPAIGN), "NOT_FOUND")
    assert_is_error(_obligation(we_owe_id, "Riley"), "NOT_FOUND")
    assert_is_error(_obligation(we_owe_id, "Devon"), "NOT_FOUND")
