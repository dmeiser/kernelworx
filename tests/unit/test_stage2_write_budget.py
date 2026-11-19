"""Leaf 2.8.7 (90/91) — the transaction budget, measured on actions Stage 2 really stages.

§2.8.7 asks for the 90/91-action test. The number is a product contract: DynamoDB caps a
``TransactWriteItems`` at 100 items, ``MAX_TRANSACTION_ACTIONS`` holds the fleet at 90, and the spec's
capacity arithmetic (about 29 products for an immediate sale) is derived from that. Counting is of
**real planned actions**, not of input list lengths, so the test has to be built out of the same
action builders the resolvers stage — a balance ``Update``, a custody ``Update``, an appended
movement, the Order ``Update``, the appended fulfillment, and the marker ``Put`` that has to lead the
plan.

Two facts fall out of measuring it rather than asserting a round number, and both are recorded here
so the next reader does not go looking for a batch that lands exactly on 90:

* The only Stage 2 surface that grows is ``returnStockFromScout``, and one item costs exactly three
  actions (balance, custody, movement) plus the one marker. So its batches are ``3n + 1``: 29 items
  commit at 88 actions, 30 are refused at 91. No batch of that shape can ever plan exactly 90, and
  the budget refuses the first plan that **crosses** it.
* The ceiling itself therefore has to be tested at the plan level, and it is: ninety staged actions
  commit as one 90-item transaction, and the ninety-first is refused with ``OPERATION_TOO_LARGE``
  before a single DynamoDB call — no marker, no balance, no movement, nothing.
"""

from __future__ import annotations

from typing import Any, Dict, List

import botocore.client
import pytest

from src.handlers.unit_operations import RETURN_STOCK_FIELD, handle_unit_operation
from src.utils import inventory_models as inv
from src.utils import order_fulfillment_models as ful
from src.utils.dynamodb import tables
from src.utils.errors import AppError
from src.utils.mutations import (
    MARKER_STATUS_COMPLETED,
    MAX_TRANSACTION_ACTIONS,
    IdempotentMutationRunner,
    WritePlan,
    marker_keys,
    normalized_fingerprint,
)
from tests.unit.show_sell_fixtures import (
    PACK_3149,
    PACK_3149_FALL,
    PROFILES,
    account_id,
    assert_is_error,
    order_line_item,
    seed_show_sell_fixtures,
    sold_order_item,
    unit_operation_event,
)

CAMPAIGN = PACK_3149_FALL
CATALOG_ID = "CATALOG#fixture-default"
PRODUCT = f"{CATALOG_ID}#prod-1"
SCOUT = "Devon"
SCOUT_PROFILE = str(PROFILES[SCOUT]["profileId"])
SCOUT_CAMPAIGN = str(PROFILES[SCOUT]["campaignId"])
ACTOR = "Avery"
MORNING = "2026-11-07T08:00:00+00:00"

#: One return item's cost in planned actions, asserted rather than assumed below.
RETURN_ITEM_ACTIONS = 3


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
    """The Stage 1 personas and the two Stage 2 tables the plan writes through."""
    return seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )


class TransactionCalls:
    """The ``TransactWriteItems`` calls a run actually made, with how many actions each carried."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.transacts: List[int] = []
        self.writes: List[str] = []
        self._monkeypatch = monkeypatch

    def attach(self) -> None:
        original = getattr(botocore.client.BaseClient, "_make_api_call")
        calls = self

        def recording_call(self: Any, operation_name: str, params: Any) -> Any:
            if self.meta.service_model.service_name == "dynamodb":
                calls.writes.append(operation_name)
                if operation_name == "TransactWriteItems":
                    calls.transacts.append(len(params.get("TransactItems", [])))
            return original(self, operation_name, params)

        self._monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", recording_call)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> TransactionCalls:
    recorder = TransactionCalls(monkeypatch)
    recorder.attach()
    return recorder


# ---------------------------------------------------------------------------
# Staging real Stage 2 actions into one plan.
# ---------------------------------------------------------------------------


def _products(count: int) -> List[str]:
    return [f"{CATALOG_ID}#budget-{index:02d}" for index in range(count)]


def _seed_products(inventory_table: Any, product_ids: List[str]) -> None:
    """A shelf and a custody for each product, both at version 1, so the plan's pins hold."""
    for product_id in product_ids:
        inventory_table.put_item(
            Item=inv.build_inventory_balance_item(
                unit_campaign_id=CAMPAIGN,
                product_id=product_id,
                kernel_physical_qty=10,
                sold_in_possession_qty=0,
                council_on_order_qty=0,
                now_iso=MORNING,
            )
        )
        inventory_table.put_item(
            Item=inv.build_scout_custody_balance_item(
                unit_campaign_id=CAMPAIGN,
                product_id=product_id,
                profile_id=SCOUT_PROFILE,
                campaign_id=SCOUT_CAMPAIGN,
                with_scout_qty=4,
                now_iso=MORNING,
            )
        )


def _balance(product_id: str) -> Dict[str, Any]:
    """This campaign's balance row for one product, asserted present.

    The plan's version pins read it, so an absent row is a fixture bug and not a case.
    """
    row = inv.read_inventory_balance(unit_campaign_id=CAMPAIGN, product_id=product_id)
    assert row is not None, f"no balance row for {product_id}"
    return row


def _custody(product_id: str) -> Dict[str, Any]:
    """This Scout's custody row for one product, asserted present."""
    row = inv.read_scout_custody(unit_campaign_id=CAMPAIGN, product_id=product_id, profile_id=SCOUT_PROFILE)
    assert row is not None, f"no custody row for {product_id}"
    return row


def _return_actions(product_id: str, movement_index: int) -> List[Any]:
    """The three actions one returned product costs, from the builders the resolver uses."""
    balance = _balance(product_id)
    custody = _custody(product_id)
    movement = inv.build_inventory_movement_item(
        movement_id=f"mov-budget-{movement_index:02d}",
        unit_campaign_id=CAMPAIGN,
        product_id=product_id,
        movement_type=inv.SCOUT_RETURN,
        actor_account_id=account_id(ACTOR),
        occurred_at=MORNING,
        idempotency_key=f"budget-movement-{movement_index:02d}",
        kernel_physical_delta=1,
        with_scout_delta=-1,
        profile_id=SCOUT_PROFILE,
    )
    return [
        inv.inventory_balance_delta_action(
            unit_campaign_id=CAMPAIGN,
            product_id=product_id,
            existing=balance,
            expected_version=int(balance[inv.VERSION_ATTRIBUTE]),
            kernel_physical_delta=1,
            now_iso=MORNING,
        ),
        inv.scout_custody_delta_action(
            unit_campaign_id=CAMPAIGN,
            product_id=product_id,
            profile_id=SCOUT_PROFILE,
            existing=custody,
            expected_version=int(custody[inv.VERSION_ATTRIBUTE]),
            with_scout_delta=-1,
            now_iso=MORNING,
        ),
        inv.put_inventory_movement_action(movement),
    ]


def _fulfillment_actions(orders_table: Any) -> List[Any]:
    """The two actions one individual fulfillment costs: the Order update and the appended row.

    The source is ``EXTERNAL_COUNCIL`` on purpose: it is the one fulfillment that draws no Unit
    stock, so the two actions here really are the whole write set, and the plan stays self-consistent
    with no balance row behind it.
    """
    order = sold_order_item(
        SCOUT,
        suffix="budget-1",
        unit_id=PACK_3149,
        unit_campaign_id=CAMPAIGN,
        lines=[order_line_item(product_id=PRODUCT, quantity=4, line_item_id="line-budget-1")],
    )
    orders_table.put_item(Item=order)
    line = dict(order["lineItems"][0])
    line["fulfilledQuantity"] = 1
    fulfillment = ful.build_fulfillment_item(
        fulfillment_id="33333333-3333-4333-8333-333333333333",
        order_id=order["orderId"],
        campaign_id=SCOUT_CAMPAIGN,
        profile_id=SCOUT_PROFILE,
        unit_id=PACK_3149,
        unit_campaign_id=CAMPAIGN,
        line_item_id="line-budget-1",
        product_id=PRODUCT,
        record_type=ful.RECORD_TYPE_FULFILL,
        quantity=1,
        source=ful.SOURCE_EXTERNAL_COUNCIL,
        actor_account_id=account_id(ACTOR),
        created_at=MORNING,
    )
    return [
        ful.order_fulfillment_update_action(
            order=order,
            line_items=[line],
            expected_version=int(order["fulfillmentVersion"]),
            occurred_at=MORNING,
        ),
        ful.put_fulfillment_action(fulfillment),
    ]


def _budget_plan(product_count: int, label: str) -> WritePlan:
    """A plan of ``1 + 3*product_count`` real Stage 2 actions, marker staged first."""
    runner = IdempotentMutationRunner()
    keys = marker_keys(
        table_key="inventory",
        table_name=tables.inventory.table_name,
        actor_id=account_id(ACTOR),
        operation="budgetProbe",
        scope=CAMPAIGN,
        idempotency_key=f"budget-{label}",
    )
    plan = WritePlan()
    runner.stage_marker(
        plan, keys, fingerprint=normalized_fingerprint({"probe": product_count, "label": label}), result_id=PRODUCT
    )
    for index, product_id in enumerate(_products(product_count), start=1):
        for action, item in _return_actions(product_id, index):
            plan.add(action, item)
    return plan


def _probe_keys(label: str) -> Any:
    """The marker address :func:`_budget_plan` staged, so the runner can execute that plan."""
    return marker_keys(
        table_key="inventory",
        table_name=tables.inventory.table_name,
        actor_id=account_id(ACTOR),
        operation="budgetProbe",
        scope=CAMPAIGN,
        idempotency_key=f"budget-{label}",
    )


# ---------------------------------------------------------------------------
# The ceiling: ninety actions commit, ninety-one are refused before anything is called.
# ---------------------------------------------------------------------------


def test_ninety_staged_stage_two_actions_commit_as_one_transaction(
    world: Dict[str, Any],
    inventory_table: Any,
    orders_table: Any,
    order_fulfillments_table: Any,
    calls: TransactionCalls,
) -> None:
    """29 returns plus one fulfillment is exactly ninety actions, and they commit together.

    The commit is the half that makes the ceiling mean something: a plan of ninety real actions is
    accepted by the service in one transaction, so 90 is headroom that is genuinely usable rather
    than a number the code merely refuses to exceed. The marker rides inside that same transaction,
    so a caller who retries a write this large is answered from it rather than re-applying it.
    """
    products = _products(29)
    _seed_products(inventory_table, products)
    plan = _budget_plan(29, "commit")
    for action, item in _fulfillment_actions(orders_table):
        plan.add(action, item)
    assert plan.action_count == MAX_TRANSACTION_ACTIONS == 90
    assert plan.tables == {tables.inventory.table_name, tables.orders.table_name, tables.order_fulfillments.table_name}

    result = IdempotentMutationRunner().execute(
        _probe_keys("commit"),
        plan,
        operation="budgetProbe",
        fingerprint=normalized_fingerprint({"probe": 29, "label": "commit"}),
        result_id=PRODUCT,
        result_payload=lambda: {"plannedActions": plan.action_count},
    )

    assert result == PRODUCT
    assert calls.transacts == [90], f"expected one 90-action transaction, got {calls.transacts}"
    assert int(_balance(products[-1])[inv.KERNEL_PHYSICAL_QTY]) == 11
    assert int(_custody(products[-1])[inv.WITH_SCOUT_QTY]) == 3
    marker = IdempotentMutationRunner().load_marker(_probe_keys("commit"))
    assert marker is not None and marker["status"]["S"] == MARKER_STATUS_COMPLETED, marker


def test_the_ninety_first_action_is_refused_before_a_single_call(
    world: Dict[str, Any],
    inventory_table: Any,
    orders_table: Any,
    order_fulfillments_table: Any,
    calls: TransactionCalls,
) -> None:
    """Staging the 91st action raises there and then: no transaction, no marker, no movement.

    This is the "fails before any write" half of §8.10. A budget enforced only by the service would
    leave the caller with a cancelled transaction whose marker may or may not exist; here the plan
    never reaches DynamoDB at all.
    """
    products = _products(30)
    _seed_products(inventory_table, products)
    plan = _budget_plan(29, "oversize")
    for action, item in _fulfillment_actions(orders_table):
        plan.add(action, item)
    assert plan.action_count == MAX_TRANSACTION_ACTIONS

    spare = products[-1]
    assert spare not in _products(29), "the probe row must be outside the staged plan"
    balance = _balance(spare)
    one_too_many = inv.inventory_balance_delta_action(
        unit_campaign_id=CAMPAIGN,
        product_id=spare,
        existing=balance,
        expected_version=int(balance[inv.VERSION_ATTRIBUTE]),
        kernel_physical_delta=1,
        now_iso=MORNING,
    )
    with pytest.raises(Exception) as raised:
        plan.add(*one_too_many)
    error = raised.value
    assert isinstance(error, AppError), error
    assert error.error_code == "CONFLICT", error
    assert error.details.get("subcode") == "OPERATION_TOO_LARGE", error.details
    assert error.details.get("plannedActions") == 91, error.details
    assert plan.action_count == MAX_TRANSACTION_ACTIONS, "the refused action was staged anyway"
    assert "TransactWriteItems" not in calls.writes, f"an oversize plan reached DynamoDB: {calls.writes}"
    assert int(_balance(spare)[inv.KERNEL_PHYSICAL_QTY]) == 10


def test_a_return_batch_refuses_at_the_crossing_it_can_actually_make(
    world: Dict[str, Any],
    inventory_table: Any,
    calls: TransactionCalls,
) -> None:
    """The growing Stage 2 surface steps from 88 actions to 91, so 90 is never its plan.

    Twenty-nine items commit, and their transaction carries exactly ``3 * 29 + 1`` actions; thirty
    are refused, and the thirtieth product's rows are untouched. Reading the arithmetic off the
    recorded call is what keeps this test honest if the per-item cost ever changes: the assertion
    that would then fail is the count, not the round number.
    """
    products = _products(30)
    for product_id in products:
        inventory_table.put_item(
            Item=inv.build_inventory_balance_item(
                unit_campaign_id=CAMPAIGN,
                product_id=product_id,
                kernel_physical_qty=6,
                sold_in_possession_qty=0,
                council_on_order_qty=0,
                now_iso=MORNING,
            )
        )
        inventory_table.put_item(
            Item=inv.build_scout_custody_balance_item(
                unit_campaign_id=CAMPAIGN,
                product_id=product_id,
                profile_id=SCOUT_PROFILE,
                campaign_id=SCOUT_CAMPAIGN,
                with_scout_qty=2,
                now_iso=MORNING,
            )
        )

    fits = products[:29]
    committed = _ok(_return(items=[{"productId": product_id, "quantity": 1} for product_id in fits], key="fits"))
    assert len(committed["inventoryPositions"]) == 29
    assert calls.transacts == [1 + RETURN_ITEM_ACTIONS * 29], f"the 29-item batch planned {calls.transacts}"

    calls.transacts.clear()
    refused = assert_is_error(
        _return(items=[{"productId": product_id, "quantity": 1} for product_id in products], key="oversize"),
        "CONFLICT",
    )
    assert "too large" in refused["message"], refused
    assert calls.transacts == [], "the oversize batch reached DynamoDB"

    leftover = _custody(products[-1])
    assert int(leftover[inv.WITH_SCOUT_QTY]) == 2
    assert int(_balance(products[-1])[inv.KERNEL_PHYSICAL_QTY]) == 6


def test_a_return_action_is_three_actions_and_no_more(world: Dict[str, Any], inventory_table: Any) -> None:
    """The cost per item is what the crossing arithmetic says it is.

    A Stage 2 change to any of the three builders — a guard action, a second movement, a linked
    history row — moves the batch limit, and the spec's capacity numbers move with it. This is the
    assertion that notices.
    """
    product_id = f"{CATALOG_ID}#budget-probe"
    _seed_products(inventory_table, [product_id])
    actions = _return_actions(product_id, 1)
    assert len(actions) == RETURN_ITEM_ACTIONS
    assert [action for action, _item in actions] == ["Update", "Update", "Put"]
    assert {item["TableName"] for _action, item in actions} == {tables.inventory.table_name}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _return(items: List[Dict[str, Any]], key: str) -> Any:
    return handle_unit_operation(
        unit_operation_event(
            RETURN_STOCK_FIELD,
            ACTOR,
            input={
                "unitCampaignId": CAMPAIGN,
                "campaignId": SCOUT_CAMPAIGN,
                "profileId": SCOUT_PROFILE,
                "items": items,
                "idempotency": {"idempotencyKey": key},
            },
        ),
        None,
    )


def _ok(payload: Any) -> Dict[str, Any]:
    assert isinstance(payload, dict) and not payload.get("__isError"), f"expected success, got {payload!r}"
    return payload
