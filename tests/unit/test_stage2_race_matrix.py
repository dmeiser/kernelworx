"""Leaf 2.8.4 — the Stage 2 race matrix: every race, and zero partial effects on every failure.

§2.8.4 asks for the concurrency cases across the whole Stage 2 surface — issue, receipt,
adjustment, fulfillment, custody return, duplicate reversal and idempotent retry — "and assert
zero partial effects on every failure". The per-leaf suites (§2.2, §2.3, §2.4) proved each
mutation's own happy path and its own guard; this is the card that proves the guards hold
together, and that a failure writes nothing at all.

"Nothing partial" is asserted as a row-level fact, not as a count on one table. Every Stage 2
write reaches exactly three tables — ``inventory`` (balance, custody, allocation, movement, and
the idempotency marker, which rides inside the same transaction), ``orders``, and
``order_fulfillments`` — so each case fingerprints all three before and after. A cancelled
transaction therefore has to leave all three byte-identical: no movement without a balance, no
balance without a movement, no marker for a request that never committed, and no Order row
touched by a stock write. The two races a deployment can genuinely interleave (the last Kernel,
the last custody unit) are additionally run as two real ``TransactWriteItems`` staged from one
read, so the verdict is DynamoDB's rather than the test's.

How a race is forced: the handler re-reads before it stages, so a stale read is injected by
patching the read the handler itself calls — the technique §2.2 and §2.3 already use — and the
version pin or the ``attribute_not_exists`` guard inside the transaction decides the rest. No
case here fabricates a ``TransactionCanceledException``: moto evaluates the real condition.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

from src.handlers.unit_operations import (
    ADJUST_COUNCIL_FIELD,
    ADJUST_INVENTORY_FIELD,
    FULFILL_LINE_FIELD,
    ISSUE_STOCK_FIELD,
    RECORD_RECEIPT_FIELD,
    RETURN_STOCK_FIELD,
    REVERSE_FULFILLMENT_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from tests.unit.show_sell_fixtures import (
    PACK_3149,
    PACK_3149_FALL,
    PROFILES,
    assert_is_error,
    order_line_item,
    seed_show_sell_fixtures,
    sold_order_item,
    unit_operation_event,
)
from tests.unit.show_sell_stock_fixtures import race_issue_last_kernel, race_return_last_kernel

CAMPAIGN = PACK_3149_FALL
CATALOG_ID = "CATALOG#fixture-default"
PRODUCT = f"{CATALOG_ID}#prod-1"
MISSING_PRODUCT = f"{CATALOG_ID}#prod-404"
SCOUT = "Devon"
SCOUT_CAMPAIGN = str(PROFILES[SCOUT]["campaignId"])
SCOUT_PROFILE = str(PROFILES[SCOUT]["profileId"])
LINE = "line-race-1"
NO_ORDER = "ORDER#camp-devon-fixture#missing"
NO_FULFILLMENT = "ff000000-0000-4000-8000-000000000000"
MORNING = "2026-11-07T08:00:00+00:00"


# ---------------------------------------------------------------------------
# Driving the resolvers, and fingerprinting what they wrote.
# ---------------------------------------------------------------------------


def _call(
    field: str,
    caller: Optional[str],
    *,
    mutation: Optional[Dict[str, Any]] = None,
    arguments: Optional[Dict[str, Any]] = None,
) -> Any:
    """One resolver turn through the deployed entry point."""
    return handle_unit_operation(unit_operation_event(field, caller, input=mutation, arguments=arguments), None)


def _idem(key: str) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": key}}


def _ok(payload: Any) -> Dict[str, Any]:
    assert not (isinstance(payload, dict) and payload.get("__isError")), f"expected success, got {payload!r}"
    return payload


def _receipt(
    *,
    quantity: Any = 4,
    key: str = "receipt-1",
    product_id: str = PRODUCT,
    campaign: str = CAMPAIGN,
    caller: str = "Avery",
) -> Any:
    return _call(
        RECORD_RECEIPT_FIELD,
        caller,
        mutation={"unitCampaignId": campaign, "productId": product_id, "quantity": quantity, **_idem(key)},
    )


def _adjust(*, delta: Any = -2, reason: Optional[str] = "miscount", key: str = "adjust-1") -> Any:
    mutation: Dict[str, Any] = {"unitCampaignId": CAMPAIGN, "productId": PRODUCT, "quantityDelta": delta, **_idem(key)}
    if reason is not None:
        mutation["reason"] = reason
    return _call(ADJUST_INVENTORY_FIELD, "Avery", mutation=mutation)


def _council(*, delta: Any = 3, key: str = "council-1", reason: Optional[str] = "council promised a case") -> Any:
    mutation: Dict[str, Any] = {"unitCampaignId": CAMPAIGN, "productId": PRODUCT, "quantityDelta": delta, **_idem(key)}
    if reason is not None:
        mutation["reason"] = reason
    return _call(ADJUST_COUNCIL_FIELD, "Avery", mutation=mutation)


def _issue(*, quantity: Any = 2, key: str = "issue-1", product_id: str = PRODUCT, scout: str = SCOUT) -> Any:
    return _call(
        ISSUE_STOCK_FIELD,
        "Avery",
        mutation={
            "unitCampaignId": CAMPAIGN,
            "campaignId": str(PROFILES[scout]["campaignId"]),
            "profileId": str(PROFILES[scout]["profileId"]),
            "productId": product_id,
            "quantity": quantity,
            **_idem(key),
        },
    )


def _return(*, key: str = "return-1", quantity: Any = 2, product_id: str = PRODUCT, scout: str = SCOUT) -> Any:
    return _call(
        RETURN_STOCK_FIELD,
        "Avery",
        mutation={
            "unitCampaignId": CAMPAIGN,
            "campaignId": str(PROFILES[scout]["campaignId"]),
            "profileId": str(PROFILES[scout]["profileId"]),
            "items": [{"productId": product_id, "quantity": quantity}],
            **_idem(key),
        },
    )


def _fulfill(
    order_id: str,
    *,
    quantity: Any = 2,
    source: str = "KERNEL_STOCK",
    version: int,
    key: str = "fulfill-1",
    line: str = LINE,
) -> Any:
    return _call(
        FULFILL_LINE_FIELD,
        "Avery",
        mutation={
            "orderId": order_id,
            "lineItemId": line,
            "quantity": quantity,
            "source": source,
            "expectedFulfillmentVersion": version,
            **_idem(key),
        },
    )


def _reverse(order_id: str, fulfillment_id: str, *, version: int, key: str = "reverse-1") -> Any:
    return _call(
        REVERSE_FULFILLMENT_FIELD,
        "Avery",
        mutation={
            "orderId": order_id,
            "fulfillmentId": fulfillment_id,
            "expectedFulfillmentVersion": version,
            **_idem(key),
        },
    )


def _rows(table: Any) -> List[Dict[str, Any]]:
    """Every row of one table, following ``LastEvaluatedKey`` to the end."""
    items: List[Dict[str, Any]] = []
    token: Optional[Dict[str, Any]] = None
    while True:
        kwargs: Dict[str, Any] = {}
        if token is not None:
            kwargs["ExclusiveStartKey"] = token
        page = table.scan(**kwargs)
        items.extend(page.get("Items", []))
        token = page.get("LastEvaluatedKey")
        if not token:
            return items


def _state(tables: Dict[str, Any]) -> List[str]:
    """Every row of every Stage 2 table, as stable sorted text.

    Two runs of this agree exactly when no Stage 2 row was created, changed or deleted —
    including the idempotency markers, which sit on the same tables and are the rows most often
    left behind by a write that failed after staging.
    """
    rows: List[str] = []
    for table in tables.values():
        for row in _rows(table):
            rows.append(json.dumps(row, sort_keys=True, default=str))
    return sorted(rows)


def _typed(inventory_table: Any, entity_type: str) -> List[Dict[str, Any]]:
    return [row for row in _rows(inventory_table) if row.get(inv.ENTITY_TYPE_ATTRIBUTE) == entity_type]


def _fulfillment_rows(order_fulfillments_table: Any, record_type: str) -> List[Dict[str, Any]]:
    return [row for row in _rows(order_fulfillments_table) if row.get("recordType") == record_type]


def _seed_balance(
    inventory_table: Any,
    *,
    physical: int,
    reserved: int = 0,
    on_order: int = 0,
    product_id: str = PRODUCT,
    version: int = 1,
) -> Dict[str, Any]:
    item = inv.build_inventory_balance_item(
        unit_campaign_id=CAMPAIGN,
        product_id=product_id,
        kernel_physical_qty=physical,
        sold_in_possession_qty=reserved,
        council_on_order_qty=on_order,
        now_iso=MORNING,
        version=version,
    )
    inventory_table.put_item(Item=item)
    return item


def _stale_copy(row: Dict[str, Any], **changes: Any) -> Dict[str, Any]:
    """The row this request read, as it looked one version before the writer overtook it."""
    return dict(row, **changes)


@pytest.fixture
def world(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    inventory_table: Any,
    orders_table: Any,
    order_fulfillments_table: Any,
) -> Dict[str, Any]:
    """The Stage 1 personas plus every table a Stage 2 write can reach."""
    return seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )


@pytest.fixture
def stage(inventory_table: Any, orders_table: Any, order_fulfillments_table: Any) -> Dict[str, Any]:
    """The three Stage 2 tables as one bundle, so no case forgets to fingerprint one."""
    return {"inventory": inventory_table, "orders": orders_table, "fulfillments": order_fulfillments_table}


def _seed_order(orders_table: Any, *, quantity: int = 4, suffix: str = "race-1") -> Dict[str, Any]:
    """An individual Order originated by this Unit's campaign, unfulfilled."""
    order = sold_order_item(
        SCOUT,
        suffix=suffix,
        unit_id=PACK_3149,
        unit_campaign_id=CAMPAIGN,
        lines=[order_line_item(product_id=PRODUCT, quantity=quantity, line_item_id=LINE)],
    )
    orders_table.put_item(Item=order)
    return order


# ---------------------------------------------------------------------------
# Every refusal leaves nothing behind, in any Stage 2 table.
# ---------------------------------------------------------------------------


def _mutation_input(key: str, **fields: Any) -> Dict[str, Any]:
    """One mutation argument block with this case's own idempotency key."""
    return {"input": {"unitCampaignId": CAMPAIGN, **fields, **_idem(key)}}


@pytest.mark.parametrize(
    "field,caller,arguments,code",
    [
        (
            RECORD_RECEIPT_FIELD,
            None,
            _mutation_input("no-session", productId=PRODUCT, quantity=4),
            "UNAUTHORIZED",
        ),
        (
            ADJUST_INVENTORY_FIELD,
            "Blake",
            _mutation_input("revoked", productId=PRODUCT, quantityDelta=-1, reason="a removed admin"),
            "NOT_FOUND",
        ),
        (
            ADJUST_INVENTORY_FIELD,
            "Riley",
            _mutation_input("foreign", productId=PRODUCT, quantityDelta=-1, reason="another Unit's campaign"),
            "NOT_FOUND",
        ),
        (
            RECORD_RECEIPT_FIELD,
            "Avery",
            _mutation_input("no-catalog", productId=MISSING_PRODUCT, quantity=4),
            "INVALID_INPUT",
        ),
        (RECORD_RECEIPT_FIELD, "Avery", _mutation_input("zero", productId=PRODUCT, quantity=0), "INVALID_INPUT"),
        (
            ADJUST_INVENTORY_FIELD,
            "Avery",
            _mutation_input("no-reason", productId=PRODUCT, quantityDelta=-1),
            "INVALID_INPUT",
        ),
        (
            ADJUST_INVENTORY_FIELD,
            "Avery",
            _mutation_input("below-sold", productId=PRODUCT, quantityDelta=-9, reason="counted out"),
            "INVALID_INPUT",
        ),
        (
            ADJUST_COUNCIL_FIELD,
            "Avery",
            _mutation_input("on-order-negative", productId=PRODUCT, quantityDelta=-4, reason="nothing promised"),
            "INVALID_INPUT",
        ),
        (
            ISSUE_STOCK_FIELD,
            "Avery",
            _mutation_input(
                "over-issue", campaignId=SCOUT_CAMPAIGN, profileId=SCOUT_PROFILE, productId=PRODUCT, quantity=9
            ),
            "INVALID_INPUT",
        ),
        (
            RETURN_STOCK_FIELD,
            "Avery",
            _mutation_input(
                "over-return",
                campaignId=SCOUT_CAMPAIGN,
                profileId=SCOUT_PROFILE,
                items=[{"productId": PRODUCT, "quantity": 1}],
            ),
            "INVALID_INPUT",
        ),
        (
            FULFILL_LINE_FIELD,
            "Avery",
            {
                "input": {
                    "orderId": NO_ORDER,
                    "lineItemId": LINE,
                    "quantity": 1,
                    "source": "KERNEL_STOCK",
                    "expectedFulfillmentVersion": 0,
                    **_idem("no-order"),
                }
            },
            "NOT_FOUND",
        ),
        (
            REVERSE_FULFILLMENT_FIELD,
            "Avery",
            {
                "input": {
                    "orderId": NO_ORDER,
                    "fulfillmentId": NO_FULFILLMENT,
                    "expectedFulfillmentVersion": 0,
                    **_idem("no-fulfillment"),
                }
            },
            "NOT_FOUND",
        ),
    ],
    ids=[
        "no-session",
        "revoked-admin",
        "foreign-unit-admin",
        "catalog-product-missing",
        "quantity-zero",
        "adjustment-no-reason",
        "adjustment-below-reservation",
        "on-order-below-zero",
        "issue-beyond-unassigned",
        "return-beyond-custody",
        "fulfill-unknown-order",
        "reverse-unknown-fulfillment",
    ],
)
def test_every_stage_two_refusal_writes_nothing_anywhere(
    world: Dict[str, Any],
    inventory_table: Any,
    stage: Dict[str, Any],
    field: str,
    caller: Optional[str],
    arguments: Dict[str, Any],
    code: str,
) -> None:
    """§2.8.4: a refusal is a refusal — no marker, no movement, no balance, no Order write."""
    _seed_balance(inventory_table, physical=10, reserved=2, on_order=1)
    before = _state(stage)

    assert_is_error(_call(field, caller, arguments=arguments), code)

    assert _state(stage) == before


# ---------------------------------------------------------------------------
# Receipt and on-order: the two balance writes that had no race case of their own.
# ---------------------------------------------------------------------------


def test_two_first_receipts_of_one_product_commit_once(
    world: Dict[str, Any], inventory_table: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two receipts that both read "no balance yet" — the conditional Put decides, and once.

    The product has never been received, so both callers plan a ``Put`` guarded by
    ``attribute_not_exists``. One commits; the loser's whole plan — marker, balance and
    movement — cancels, so the Unit never books one delivery twice and the trail never gains a
    row the balance does not explain.
    """
    monkeypatch.setattr(inv, "read_inventory_balance", lambda *_a, **_k: None)
    first = _ok(_receipt(quantity=4, key="receipt-a"))
    second = _receipt(quantity=6, key="receipt-b")

    assert_is_error(second, "CONFLICT")
    assert first["kernelPhysicalQty"] == 4
    balances = _typed(inventory_table, inv.BALANCE_ENTITY_TYPE)
    assert len(balances) == 1 and balances[0]["kernelPhysicalQty"] == 4 and balances[0]["version"] == 1
    movements = _typed(inventory_table, inv.MOVEMENT_ENTITY_TYPE)
    assert len(movements) == 1 and movements[0]["kernelPhysicalDelta"] == 4


def test_a_receipt_planned_from_a_stale_balance_read_cancels_wholly(
    world: Dict[str, Any], inventory_table: Any, stage: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A receipt staged against a version the row no longer carries writes nothing at all."""
    _seed_balance(inventory_table, physical=10, version=7)
    stale = _stale_copy(_typed(inventory_table, inv.BALANCE_ENTITY_TYPE)[0], version=6, kernelPhysicalQty=9)
    monkeypatch.setattr(inv, "read_inventory_balance", lambda *_a, **_k: stale)
    before = _state(stage)

    assert_is_error(_receipt(quantity=5, key="receipt-1"), "CONFLICT")

    assert _state(stage) == before, "a lost receipt may not leave a movement or a marker behind"


def test_an_on_order_adjustment_planned_from_a_stale_read_cancels_wholly(
    world: Dict[str, Any], inventory_table: Any, stage: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2.2.3's write carries the same version pin as the physical one, and fails the same way."""
    _seed_balance(inventory_table, physical=10, on_order=4, version=3)
    stale = _stale_copy(_typed(inventory_table, inv.BALANCE_ENTITY_TYPE)[0], version=2, councilOnOrderQty=4)
    monkeypatch.setattr(inv, "read_inventory_balance", lambda *_a, **_k: stale)
    before = _state(stage)

    assert_is_error(_council(delta=6, key="council-1"), "CONFLICT")

    assert _state(stage) == before


# ---------------------------------------------------------------------------
# Custody: a return whose read went stale, and the two last-unit races.
# ---------------------------------------------------------------------------


def test_a_return_planned_from_a_stale_custody_read_cancels_wholly(
    world: Dict[str, Any], inventory_table: Any, stage: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2.3.2's return re-reads custody, and a stale read loses the whole batch.

    The over-return guard is a pre-check, so it can pass against a read another writer has
    already overtaken. The version pin on the custody increment is what decides, and the batch
    is one transaction: Kernel stock never rises for a custody row that no longer says what the
    return assumed.
    """
    _seed_balance(inventory_table, physical=4)
    _ok(_issue(quantity=3, key="issue-1"))
    held = _typed(inventory_table, inv.CUSTODY_ENTITY_TYPE)[0]
    stale = _stale_copy(held, version=int(held[inv.VERSION_ATTRIBUTE]) - 1, withScoutQty=3)
    monkeypatch.setattr(inv, "read_scout_custody", lambda *_a, **_k: stale)
    before = _state(stage)

    assert_is_error(_return(quantity=3, key="return-1"), "CONFLICT")

    assert _state(stage) == before


def test_the_race_for_the_last_kernel_moves_stock_custody_and_history_once(
    world: Dict[str, Any], inventory_table: Any
) -> None:
    """Two issues of one Kernel, planned from one read: DynamoDB picks one, and only one.

    Both plans come from the same snapshot, which is how a deployment interleaves them — the
    pre-check passes for both callers against one read. The verdict asserted here is not only
    that one transaction cancelled, but that the Kernel moved once, the custody moved once, and
    exactly one movement row exists.
    """
    _seed_balance(inventory_table, physical=1)
    verdicts = race_issue_last_kernel(inventory_table, campaign=CAMPAIGN, product_id=PRODUCT, scout=SCOUT, quantity=1)

    assert verdicts["committed"] == 1, verdicts["verdicts"]
    loser = next(verdict for verdict in verdicts["verdicts"] if not verdict["committed"])
    assert loser["code"] == "TransactionCanceledException"
    balances = _typed(inventory_table, inv.BALANCE_ENTITY_TYPE)
    assert len(balances) == 1 and balances[0]["kernelPhysicalQty"] == 0 and balances[0]["version"] == 2
    custody = _typed(inventory_table, inv.CUSTODY_ENTITY_TYPE)
    assert len(custody) == 1 and custody[0]["withScoutQty"] == 1 and custody[0]["version"] == 1
    assert len(_typed(inventory_table, inv.MOVEMENT_ENTITY_TYPE)) == 1


def test_the_race_for_the_last_custody_unit_returns_it_once(world: Dict[str, Any], inventory_table: Any) -> None:
    """The other side of the same race: With Scout cannot go negative, Kernel cannot gain twice."""
    _seed_balance(inventory_table, physical=2)
    _ok(_issue(quantity=1, key="issue-1"))
    verdicts = race_return_last_kernel(inventory_table, campaign=CAMPAIGN, product_id=PRODUCT, scout=SCOUT, quantity=1)

    assert verdicts["committed"] == 1, verdicts["verdicts"]
    balances = _typed(inventory_table, inv.BALANCE_ENTITY_TYPE)
    assert balances[0]["kernelPhysicalQty"] == 2 and balances[0]["version"] == 3
    custody = _typed(inventory_table, inv.CUSTODY_ENTITY_TYPE)
    assert len(custody) == 1 and custody[0]["withScoutQty"] == 0
    assert len(_typed(inventory_table, inv.MOVEMENT_ENTITY_TYPE)) == 2


# ---------------------------------------------------------------------------
# Fulfillment and reversal: both §2.4 writers, raced.
# ---------------------------------------------------------------------------


def test_two_fulfillments_that_both_read_an_unfulfilled_line_commit_once(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, stage: Dict[str, Any]
) -> None:
    """Two admins of one Order, both reading ``fulfillmentVersion: 0``: one line, one movement.

    This is the fulfillment race spelled the way the browser does it — each caller sends the
    version it read, so the loser is refused by the Order-row condition rather than by a
    re-read. The stock has to move exactly once: a Kernel spent twice on one line is stock the
    Unit no longer holds reporting as stock it sold.
    """
    _seed_balance(inventory_table, physical=6)
    order = _seed_order(orders_table, quantity=4)
    order_id = str(order["orderId"])

    first = _ok(_fulfill(order_id, quantity=2, version=0, key="fulfill-a"))
    second = _fulfill(order_id, quantity=2, version=0, key="fulfill-b")

    assert_is_error(second, "CONFLICT")
    assert first["order"]["lineItems"][0]["fulfilledQuantity"] == 2
    stored = orders_table.get_item(Key={"campaignId": order["campaignId"], "orderId": order_id})["Item"]
    assert int(stored["fulfillmentVersion"]) == 1
    assert int(stored["lineItems"][0]["fulfilledQuantity"]) == 2
    balance = _typed(inventory_table, inv.BALANCE_ENTITY_TYPE)[0]
    assert balance["kernelPhysicalQty"] == 4 and balance["version"] == 2
    assert len(_typed(inventory_table, inv.MOVEMENT_ENTITY_TYPE)) == 1
    assert len(_fulfillment_rows(stage["fulfillments"], "FULFILL")) == 1


def test_an_external_fulfillment_raced_with_a_kernel_one_moves_stock_once(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, stage: Dict[str, Any]
) -> None:
    """An external-Council fulfillment cannot double-count what a Kernel fulfillment spent.

    Both sources increment the same Order version, so the version guard serializes a Kernel
    fulfillment against an external one, not just like against like.
    """
    _seed_balance(inventory_table, physical=6)
    order = _seed_order(orders_table, quantity=4)
    order_id = str(order["orderId"])

    _ok(_fulfill(order_id, quantity=2, source="EXTERNAL_COUNCIL", version=0, key="fulfill-ext"))
    second = _fulfill(order_id, quantity=2, source="KERNEL_STOCK", version=0, key="fulfill-kernel")

    assert_is_error(second, "CONFLICT")
    balance = _typed(inventory_table, inv.BALANCE_ENTITY_TYPE)[0]
    assert balance["kernelPhysicalQty"] == 6 and balance["version"] == 1
    assert _typed(inventory_table, inv.MOVEMENT_ENTITY_TYPE) == []


def test_two_reversals_of_one_fulfillment_restore_stock_once(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, stage: Dict[str, Any]
) -> None:
    """The duplicate-reversal race: the deterministic key means the second cannot land twice.

    Both callers read the Order at version 1 and both name the same fulfillment, so the loser
    is stopped by the reversal's deterministic sort key as well as by the Order version — the
    row the second attempt would write already exists. Demand and stock are each restored once,
    and the shelf never gains the same Kernel twice.
    """
    _seed_balance(inventory_table, physical=6)
    order = _seed_order(orders_table, quantity=4)
    order_id = str(order["orderId"])
    fulfilled = _ok(_fulfill(order_id, quantity=3, version=0, key="fulfill-1"))
    fulfillment_id = str(fulfilled["fulfillment"]["fulfillmentId"])

    first = _ok(_reverse(order_id, fulfillment_id, version=1, key="reverse-a"))
    second = _reverse(order_id, fulfillment_id, version=1, key="reverse-b")

    assert_is_error(second, "CONFLICT")
    assert first["order"]["lineItems"][0]["fulfilledQuantity"] == 0
    balance = _typed(inventory_table, inv.BALANCE_ENTITY_TYPE)[0]
    assert balance["kernelPhysicalQty"] == 6 and balance["version"] == 3
    movements = _typed(inventory_table, inv.MOVEMENT_ENTITY_TYPE)
    assert [row["movementType"] for row in movements] == ["INDIVIDUAL_FULFILL", "REVERSAL"]
    assert len(_fulfillment_rows(stage["fulfillments"], "REVERSAL")) == 1


def test_a_reversal_record_cannot_win_a_race_against_itself(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, stage: Dict[str, Any]
) -> None:
    """Reversing a reversal is refused, so no pair of corrections can loop stock upward."""
    _seed_balance(inventory_table, physical=6)
    order = _seed_order(orders_table, quantity=4)
    order_id = str(order["orderId"])
    fulfilled = _ok(_fulfill(order_id, quantity=3, version=0, key="fulfill-1"))
    reversal = _ok(_reverse(order_id, str(fulfilled["fulfillment"]["fulfillmentId"]), version=1, key="reverse-1"))
    before = _state(stage)

    assert_is_error(
        _reverse(order_id, str(reversal["reversal"]["fulfillmentId"]), version=2, key="reverse-2"), "INVALID_INPUT"
    )

    assert _state(stage) == before


# ---------------------------------------------------------------------------
# Idempotent retry: a replay is an answer, not a second write.
# ---------------------------------------------------------------------------


#: Each Stage 2 mutation, and the pair of identical calls a double-submit makes.
REPLAYS: Dict[str, Tuple[Callable[[], Any], int]] = {
    "receipt": (lambda: _receipt(quantity=4, key="k-receipt"), 1),
    "adjust": (lambda: _adjust(delta=-2, key="k-adjust"), 1),
    "council": (lambda: _council(delta=3, key="k-council"), 1),
    "issue": (lambda: _issue(quantity=2, key="k-issue"), 1),
    "return": (lambda: _return(quantity=2, key="k-return"), 2),
}


@pytest.mark.parametrize("operation", sorted(REPLAYS))
def test_a_replayed_key_answers_without_writing_again(
    world: Dict[str, Any], inventory_table: Any, stage: Dict[str, Any], operation: str
) -> None:
    """The idempotent-retry race: the second attempt is a read of the first's answer.

    The per-leaf tests compare the returned payload; this compares the tables. A replay has to
    leave the movement trail, the balances and the marker exactly as the first attempt left
    them, because a retry that appends a second movement is an audit trail that no longer
    explains the balance it is supposed to justify.
    """
    call, movements_after = REPLAYS[operation]
    if operation != "receipt":
        _seed_balance(inventory_table, physical=10)
    if operation == "return":
        _ok(_issue(quantity=2, key="k-issue-for-return"))

    first = _ok(call())
    second = _ok(call())
    assert second == first

    after_retry = _state(stage)
    _ok(call())
    assert _state(stage) == after_retry
    assert len(_typed(inventory_table, inv.MOVEMENT_ENTITY_TYPE)) == movements_after


def test_a_replayed_fulfillment_and_reversal_write_no_second_row(
    world: Dict[str, Any], inventory_table: Any, orders_table: Any, stage: Dict[str, Any]
) -> None:
    """The §2.4 pair replays too: one fulfillment row, one reversal, one movement each."""
    _seed_balance(inventory_table, physical=6)
    order = _seed_order(orders_table, quantity=4)
    order_id = str(order["orderId"])
    first = _ok(_fulfill(order_id, quantity=2, version=0, key="k-fulfill"))
    assert _ok(_fulfill(order_id, quantity=2, version=0, key="k-fulfill")) == first

    fulfillment_id = str(first["fulfillment"]["fulfillmentId"])
    reversed_first = _ok(_reverse(order_id, fulfillment_id, version=1, key="k-reverse"))
    assert _ok(_reverse(order_id, fulfillment_id, version=1, key="k-reverse")) == reversed_first

    assert len(_fulfillment_rows(stage["fulfillments"], "FULFILL")) == 1
    assert len(_fulfillment_rows(stage["fulfillments"], "REVERSAL")) == 1
    assert len(_typed(inventory_table, inv.MOVEMENT_ENTITY_TYPE)) == 2
    balance = _typed(inventory_table, inv.BALANCE_ENTITY_TYPE)[0]
    assert balance["kernelPhysicalQty"] == 6 and balance["version"] == 3


def test_a_cancelled_attempt_leaves_no_marker_so_its_retry_is_a_real_write(
    world: Dict[str, Any], inventory_table: Any, stage: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A loser's retry is a fresh request, because nothing of its attempt survived to replay.

    This is the half of the idempotency contract the marker tests leave implicit: a cancelled
    transaction wrote no marker, so the same key retried after the row settled must actually
    perform the write rather than answer a phantom stored result — and it must perform it once,
    with the winner's movement still the only one for that product until it does.
    """
    _seed_balance(inventory_table, physical=10, version=7)
    stale = _stale_copy(_typed(inventory_table, inv.BALANCE_ENTITY_TYPE)[0], version=6, kernelPhysicalQty=9)
    monkeypatch.setattr(inv, "read_inventory_balance", lambda *_a, **_k: stale)
    assert_is_error(_receipt(quantity=5, key="receipt-1"), "CONFLICT")

    assert [row for row in _rows(inventory_table) if str(row.get("pk", "")).startswith("IDEM#")] == []
    assert _typed(inventory_table, inv.MOVEMENT_ENTITY_TYPE) == []
    monkeypatch.undo()

    retry = _ok(_receipt(quantity=5, key="receipt-1"))
    assert retry["kernelPhysicalQty"] == 15
    assert len(_typed(inventory_table, inv.MOVEMENT_ENTITY_TYPE)) == 1
    assert _typed(inventory_table, inv.BALANCE_ENTITY_TYPE)[0]["version"] == 8
