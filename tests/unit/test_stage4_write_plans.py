"""Leaf 4.6.7 — the write plans Stage 4 issues, measured at the wire.

§4.2.2 and §8.10 describe a sale's plan; this file measures it. Every case records the
DynamoDB calls the deployed resolver makes, with ``TransactWriteItems`` unpacked into the
actions it really is, and asserts the shape of the transaction rather than a payload count:

- a 1-, 2-, 5- and 15-line sale each stages exactly one transaction, and its action count
  is exactly the measured skeleton plus the measured per-product and per-obligation terms;
- the largest sale the campaign's finalization budget allows commits, and one product more
  is refused with the budget arithmetic in the message and **zero** recorded DynamoDB
  writes — the plan is rejected while it is being computed, before any write is staged;
- a refused oversized attempt leaves no idempotency marker, so an identical retry gets the
  same verdict from the same arithmetic instead of replaying something that never happened;
- an order larger than one request splits into two sales that are each atomic on their own:
  the second one's failure leaves the first exactly as it committed;
- no sale's plan reaches another sale's rows, and no plan reaches a table Stage 4 does not
  own (accounts, profiles, shares, campaigns, orders, preferences).

Measured at this head, for a sale of ``P`` products that write stock and ``W`` obligations:
one marker Put, one sale Put, one aggregate update, three actions per sold product (balance
update, allocation update, movement Put) and one Put per We Owe obligation — so
``3 + 3P + W`` actions in one transaction, and one further write after it commits: the
marker's completion update. Those numbers are the constants below, and each case re-measures
them rather than assuming them.

The scenario is the four-box table from the Wave 5.2 sale tests — one campaign, one running
event, stock assigned to that event — widened to as many catalog products as a case needs.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, List, Sequence, Tuple

import pytest

from src.utils import allocation_models as am
from src.utils import inventory_models as inv
from src.utils import mutations
from src.utils import show_and_sell_models as ssm
from src.utils import show_and_sell_sale_models as sm
from src.utils.mutations import MAX_TRANSACTION_ACTIONS
from tests.unit.show_sell_fixtures import (
    PACK_3149,
    account_id,
    assert_is_error,
    grant_item,
    seed_show_sell_fixtures,
)
from tests.unit.test_show_and_sell_sales import (
    ACTIVE_EVENT,
    PRICE_CENTS,
    _create,
    _offer_products,
    _ok,
    _seed_event,
    _seed_stock,
)
from tests.unit.test_stage2_stock_only_writes import WRITE_ACTIONS

#: What one product a sale actually moves adds to its transaction: the balance update, the
#: allocation update, and the SALE movement that documents both.
ACTIONS_PER_SOLD_PRODUCT = 3

#: What one We Owe line adds: its obligation row. An obligation moves no stock when the sale
#: is entered, so it has no balance, allocation or movement action.
ACTIONS_PER_OBLIGATION = 1

#: The actions every sale stages regardless of its lines: the idempotency marker Put, the
#: sale row Put, and the event aggregate's guarded update.
SALE_PLAN_BASE = 3

#: The one write a committed sale makes outside its transaction: completing its marker.
#: Everything else happening outside a transaction would be the partial-effect class.
MARKER_COMPLETION_WRITES = 1


class PlanRecorder:
    """Every Stage 4 write the resolver issues, split into transactions and solo writes.

    Hooked at the botocore layer, so a write hiding inside ``TransactWriteItems`` is
    recorded as the actions it is, and a plan rejected while it is computed records nothing
    at all — which is the half of §8.10 this leaf asks for.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._transactions: List[List[Tuple[str, str, str, str]]] = []
        self._solo: List[Tuple[str, str, str, str]] = []
        self._monkeypatch = monkeypatch

    def attach(self) -> None:
        client_module = importlib.import_module("botocore.client")
        original = client_module.BaseClient._make_api_call
        recorder = self

        def recording_call(self: Any, operation_name: str, params: Any) -> Any:
            if self.meta.service_model.service_name == "dynamodb" and operation_name in WRITE_ACTIONS:
                if operation_name == "TransactWriteItems":
                    staged: List[Tuple[str, str, str, str]] = []
                    for action in params.get("TransactItems", []):
                        for kind in ("Put", "Update", "Delete", "ConditionCheck"):
                            body = action.get(kind)
                            if isinstance(body, dict):
                                staged.append((kind, str(body.get("TableName")), *_row_address(body)))
                    recorder._transactions.append(staged)
                else:
                    recorder._solo.append((operation_name, str(params.get("TableName")), *_row_address(params)))
            return original(self, operation_name, params)

        self._monkeypatch.setattr(client_module.BaseClient, "_make_api_call", recording_call)

    def reset(self) -> None:
        self._transactions.clear()
        self._solo.clear()

    @property
    def transactions(self) -> List[List[Tuple[str, str, str, str]]]:
        return self._transactions

    @property
    def solo(self) -> List[Tuple[str, str, str, str]]:
        """Writes issued outside any transaction, in the order they were issued."""
        return self._solo

    def actions(self, index: int = -1) -> List[Tuple[str, str, str, str]]:
        return self._transactions[index]

    def action_count(self, index: int = -1) -> int:
        return len(self._transactions[index])

    def rows(self, index: int = -1) -> List[Tuple[str, str]]:
        """The (partition, sort) addresses one transaction writes or guards."""
        return [(action[2], action[3]) for action in self.actions(index)]

    def tables(self) -> List[str]:
        """Every table any recorded write touched, transactions and solo writes together."""
        return sorted({action[1] for tx in self._transactions for action in tx} | {action[1] for action in self._solo})

    def kinds(self, index: int = -1) -> List[str]:
        return [action[0] for action in self.actions(index)]

    def only_marker_completion(self) -> None:
        """Assert the solo writes are exactly the committed sale's marker completion."""
        assert len(self._solo) == MARKER_COMPLETION_WRITES, self._solo
        for operation, table, partition, sort in self._solo:
            assert operation == "UpdateItem", self._solo
            assert partition.startswith(_prefix(mutations.MARKER_PK_PREFIX)), self._solo
            assert table and sort.startswith(_prefix(mutations.MARKER_SK_PREFIX)), self._solo


def _wire(value: str) -> str:
    """How one key value of a recorded action reads: the DynamoDB wire form, as text."""
    return str({"S": value})


def _prefix(value: str) -> str:
    """The start of that same wire form, for matching a key prefix rather than a whole key."""
    return "{'S': '" + value


def _row_address(body: Dict[str, Any]) -> Tuple[str, str]:
    """The (partition, sort) address of a transaction action's target row, in wire form."""
    key = body.get("Key")
    if not isinstance(key, dict):
        key = body.get("Item")
    if isinstance(key, dict):
        return (str(key.get("pk", "")), str(key.get("sk", key.get("saleId", ""))))
    return ("", "")


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
    """The Stage 1 persona world plus the tables Stage 4 sales write."""
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    return {
        "units": units_table,
        "unit_campaigns": unit_campaigns_table,
        "catalogs": catalogs_table,
        "inventory": inventory_table,
        "show_and_sells": show_and_sells_table,
    }


@pytest.fixture
def plan(monkeypatch: pytest.MonkeyPatch) -> PlanRecorder:
    """The recorder, attached before the mutation under measurement."""
    recorder = PlanRecorder(monkeypatch)
    recorder.attach()
    return recorder


def _shelf(world: Dict[str, Any], products: Sequence[str]) -> None:
    """Stock and event assignment for every product a case is about to sell."""
    for product_id in products:
        _seed_stock(world, product_id=product_id)


def _lines(products: Sequence[str], *, immediate: int = 1, we_owe: int = 0) -> List[Dict[str, Any]]:
    return [{"productId": product_id, "immediateQty": immediate, "weOweQty": we_owe} for product_id in products]


def _sale_rows(show_and_sells_table: Any) -> List[Dict[str, Any]]:
    return [row for row in show_and_sells_table.scan()["Items"] if row.get("entityType") == sm.SALE_ENTITY_TYPE]


def _obligation_rows(show_and_sells_table: Any) -> List[Dict[str, Any]]:
    return [row for row in show_and_sells_table.scan()["Items"] if row.get("entityType") == sm.WE_OWE_ENTITY_TYPE]


def _marker_rows(show_and_sells_table: Any) -> List[Dict[str, Any]]:
    return [row for row in show_and_sells_table.scan()["Items"] if str(row.get("pk", "")).startswith("IDEM#")]


def _movement_rows(inventory_table: Any) -> List[Dict[str, Any]]:
    return [row for row in inventory_table.scan()["Items"] if row.get("entityType") == inv.MOVEMENT_ENTITY_TYPE]


# --- The plan, measured ----------------------------------------------------------


@pytest.mark.parametrize("line_count", [1, 2, 5, 15])
def test_a_sale_of_every_named_size_stages_one_transaction(
    world: Dict[str, Any], plan: PlanRecorder, line_count: int
) -> None:
    """4.6.7: 1-, 2-, 5- and 15-line sales, each in exactly one transaction."""
    products = _offer_products(world["catalogs"], line_count)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _shelf(world, products)

    plan.reset()
    answer = _ok(_create(lines=_lines(products), key=f"sale-{line_count}"))
    expected = SALE_PLAN_BASE + line_count * ACTIONS_PER_SOLD_PRODUCT

    assert len(plan.transactions) == 1, f"a {line_count}-line sale must commit in one transaction"
    assert plan.action_count() == expected, f"a {line_count}-line sale staged {plan.action_count()} actions"
    assert plan.action_count() <= MAX_TRANSACTION_ACTIONS
    assert plan.kinds().count("Put") == 2 + line_count
    assert plan.kinds().count("Update") == 1 + 2 * line_count
    assert len(_movement_rows(world["inventory"])) == line_count
    assert len(_sale_rows(world["show_and_sells"])) == 1
    assert len(_marker_rows(world["show_and_sells"])) == 1
    assert answer["sale"]["totalCents"] == line_count * PRICE_CENTS
    plan.only_marker_completion()


@pytest.mark.parametrize("owed_count", [1, 3, 15])
def test_each_obligation_adds_exactly_one_action_and_no_stock_action(
    world: Dict[str, Any], plan: PlanRecorder, owed_count: int
) -> None:
    """4.6.7: an owed line costs its obligation row and no stock action at all."""
    products = _offer_products(world["catalogs"], owed_count)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _shelf(world, products)

    plan.reset()
    answer = _ok(
        _create(lines=_lines(products, immediate=0, we_owe=1), buyerName="Buyer Bee", key=f"owed-{owed_count}")
    )
    expected = SALE_PLAN_BASE + owed_count * ACTIONS_PER_OBLIGATION

    assert len(plan.transactions) == 1
    assert plan.action_count() == expected, f"{owed_count} obligations staged {plan.action_count()} actions"
    assert plan.kinds().count("Put") == 2 + owed_count
    assert plan.kinds().count("Update") == 1
    assert len(_obligation_rows(world["show_and_sells"])) == owed_count
    assert len(answer["obligations"]) == owed_count
    assert _movement_rows(world["inventory"]) == [], "an obligation wrote no stock movement"
    plan.only_marker_completion()


def test_a_mixed_sale_stages_stock_actions_once_per_sold_product_and_one_obligation_each(
    world: Dict[str, Any], plan: PlanRecorder
) -> None:
    """4.6.7: one line with both halves writes one movement, not two, plus one obligation."""
    products = _offer_products(world["catalogs"], 2)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _shelf(world, products)

    plan.reset()
    answer = _ok(
        _create(
            lines=[
                {"productId": products[0], "immediateQty": 0, "weOweQty": 2},
                {"productId": products[1], "immediateQty": 2, "weOweQty": 1},
            ],
            buyerName="Buyer Bee",
            key="sale-mixed",
        )
    )

    assert len(plan.transactions) == 1
    assert plan.action_count() == SALE_PLAN_BASE + ACTIONS_PER_SOLD_PRODUCT + 2 * ACTIONS_PER_OBLIGATION
    assert len(_movement_rows(world["inventory"])) == 1, "only the product handed over moved stock"
    assert len(_obligation_rows(world["show_and_sells"])) == 2
    assert len(answer["obligations"]) == 2
    plan.only_marker_completion()


def test_no_sale_plan_reaches_a_table_stage_four_does_not_own(world: Dict[str, Any], plan: PlanRecorder) -> None:
    """4.6.7: the write set is the event and inventory tables, and nothing else."""
    products = _offer_products(world["catalogs"], 3)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _shelf(world, products)

    plan.reset()
    _ok(_create(lines=_lines(products, we_owe=1), buyerName="Buyer Bee", key="sale-scope"))

    assert plan.tables() == sorted([world["show_and_sells"].table_name, world["inventory"].table_name]), plan.tables()
    plan.only_marker_completion()


def test_two_sales_do_not_share_a_row_except_the_aggregate_they_both_guard(
    world: Dict[str, Any], plan: PlanRecorder
) -> None:
    """4.6.7: the second sale's plan never reaches the first sale's rows — no coordinator."""
    products = _offer_products(world["catalogs"], 4)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _shelf(world, products)

    first = _ok(_create(lines=_lines(products[:2]), key="sale-a"))
    plan.reset()
    second = _ok(_create(lines=_lines(products[2:]), version=2, key="sale-b"))

    assert len(plan.transactions) == 1, "one sale, one transaction — no plan spans two sales"
    event_pk = _wire(ssm.show_and_sell_pk(ACTIVE_EVENT))
    first_sale_row = (event_pk, _wire(sm.sale_sk(str(first["sale"]["saleId"]))))
    second_rows = set(plan.rows())
    assert first_sale_row not in second_rows, "the second sale wrote inside the first sale's row"
    assert (event_pk, _wire(ssm.METADATA_SK)) in second_rows, "the aggregate guard is the shared row"
    assert len(_sale_rows(world["show_and_sells"])) == 2
    assert second["sale"]["saleId"] != first["sale"]["saleId"]


# --- The ceiling, and failing before any write -----------------------------------


def test_the_largest_sale_the_budget_allows_lands_and_one_product_more_writes_nothing(
    world: Dict[str, Any], plan: PlanRecorder
) -> None:
    """4.6.7: the largest transaction-safe sale commits; the next product stages nothing."""
    products = _offer_products(world["catalogs"], 22)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _shelf(world, products)

    plan.reset()
    largest = _ok(_create(lines=_lines(products[:21]), key="sale-largest"))

    assert len(plan.transactions) == 1
    assert plan.action_count() == SALE_PLAN_BASE + 21 * ACTIONS_PER_SOLD_PRODUCT
    assert plan.action_count() <= MAX_TRANSACTION_ACTIONS
    assert len(largest["inventoryPositions"]) == 21
    assert len(_sale_rows(world["show_and_sells"])) == 1
    assert len(_movement_rows(world["inventory"])) == 21

    plan.reset()
    refused = assert_is_error(_create(lines=_lines(products), version=2, key="sale-too-big"), "CONFLICT")
    assert plan.transactions == [], f"an over-budget request staged {plan.transactions}"
    assert plan.solo == []
    expected_actions = (
        am.FINALIZATION_OVERHEAD_ACTIONS
        + 22 * am.FINALIZATION_ACTIONS_PER_ALLOCATED_PRODUCT
        + 2 * am.FINALIZATION_ACTIONS_PER_SALE
    )
    assert f"{expected_actions} actions" in refused["message"], refused["message"]
    assert expected_actions > MAX_TRANSACTION_ACTIONS
    assert len(_sale_rows(world["show_and_sells"])) == 1
    assert len(_movement_rows(world["inventory"])) == 21


def test_an_oversized_request_fails_before_the_marker_so_its_retry_is_not_a_replay(
    world: Dict[str, Any], plan: PlanRecorder
) -> None:
    """4.6.7: an over-budget sale writes nothing, marker included, so a retry re-decides."""
    products = _offer_products(world["catalogs"], 22)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _shelf(world, products)
    oversized = _lines(products)

    plan.reset()
    first = assert_is_error(_create(lines=oversized, buyerName="Buyer Bee", key="sale-oversized"), "CONFLICT")
    assert plan.transactions == []
    assert plan.solo == []
    assert _marker_rows(world["show_and_sells"]) == [], "a rejected request left a replay marker"
    assert _sale_rows(world["show_and_sells"]) == []
    assert _movement_rows(world["inventory"]) == []

    plan.reset()
    again = assert_is_error(_create(lines=oversized, buyerName="Buyer Bee", key="sale-oversized"), "CONFLICT")
    assert again["message"] == first["message"], "the same request gets the same verdict, not a replay"
    assert plan.transactions == []

    plan.reset()
    _ok(_create(lines=_lines(products[:21]), buyerName="Buyer Bee", key="sale-fits"))
    assert len(plan.transactions) == 1, "the next request that fits is a real write"
    assert len(_sale_rows(world["show_and_sells"])) == 1


def test_the_ceiling_that_binds_is_the_finalization_budget_not_the_transaction_cap(
    world: Dict[str, Any], plan: PlanRecorder
) -> None:
    """4.6.7: the largest sale is 21 products because of §8.10's estimate, not the 90-action cap."""
    products = _offer_products(world["catalogs"], 21)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _shelf(world, products)

    plan.reset()
    _ok(_create(lines=_lines(products), key="sale-budget-largest"))

    staged = plan.action_count()
    assert staged == SALE_PLAN_BASE + 21 * ACTIONS_PER_SOLD_PRODUCT
    assert staged < MAX_TRANSACTION_ACTIONS, "the sale's own plan is not what runs out of room"

    overhead = am.FINALIZATION_OVERHEAD_ACTIONS
    per_product = am.FINALIZATION_ACTIONS_PER_ALLOCATED_PRODUCT
    assert overhead + 21 * per_product + am.FINALIZATION_ACTIONS_PER_SALE <= MAX_TRANSACTION_ACTIONS
    assert overhead + 22 * per_product + am.FINALIZATION_ACTIONS_PER_SALE > MAX_TRANSACTION_ACTIONS


def test_a_sale_whose_new_we_owe_rows_cross_the_budget_is_refused_before_any_write(
    world: Dict[str, Any], plan: PlanRecorder
) -> None:
    """§8.10: the pending write's obligations are part of the estimate it must fit."""
    products = _offer_products(world["catalogs"], 19)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT, product_ids=products)
    _shelf(world, products)

    for index in range(3):
        plan.reset()
        _ok(
            _create(
                lines=_lines(products[:1], immediate=0, we_owe=1),
                buyerName="Buyer Bee",
                version=index + 1,
                key=f"owe-fitting-{index}",
            )
        )

    # 19 products + 3 sales + 3 obligations = 88; the fourth sale adds one of
    # each, taking the same estimate to 91. The filter is the obligation term.
    plan.reset()
    refused = assert_is_error(
        _create(
            lines=_lines(products[:1], immediate=0, we_owe=1),
            buyerName="Buyer Bee",
            version=4,
            key="owe-over-budget",
        ),
        "CONFLICT",
    )
    assert "91 actions" in refused["message"], refused["message"]
    assert plan.transactions == []
    assert plan.solo == []
    assert len(_sale_rows(world["show_and_sells"])) == 3
    assert len(_obligation_rows(world["show_and_sells"])) == 3


# --- Splitting an order that is too large for one request ------------------------


def test_a_large_order_splits_into_two_sales_that_are_each_atomic(world: Dict[str, Any], plan: PlanRecorder) -> None:
    """4.6.7: a larger order is two independent sales, each atomic on its own."""
    products = _offer_products(world["catalogs"], 20)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _shelf(world, products)

    first = _ok(_create(lines=_lines(products), key="split-part-1"))
    plan.reset()
    second = _ok(
        _create(
            lines=_lines(products[:3], immediate=0, we_owe=1),
            buyerName="Buyer Bee",
            version=2,
            key="split-part-2",
        )
    )

    assert len(plan.transactions) == 1, "the second sale is its own transaction"
    assert len(second["obligations"]) == 3
    assert len(_obligation_rows(world["show_and_sells"])) == 3
    assert len(_movement_rows(world["inventory"])) == 20, "the obligation sale moved no extra stock"

    # A third attempt that fails on its own terms leaves both committed sales exactly as they are.
    plan.reset()
    assert_is_error(_create(lines=_lines(products[:1]), version=2, key="split-part-3"), "CONFLICT")
    assert plan.transactions == []

    sales = {str(row[sm.SALE_ID_ATTRIBUTE]) for row in _sale_rows(world["show_and_sells"])}
    assert sales == {str(first["sale"]["saleId"]), str(second["sale"]["saleId"])}
    assert sm.sale_obligations(ACTIVE_EVENT, str(second["sale"]["saleId"]))
    assert sm.sale_obligations(ACTIVE_EVENT, str(first["sale"]["saleId"])) == []


def test_a_sale_refused_by_its_version_pin_writes_no_row_anywhere(world: Dict[str, Any], plan: PlanRecorder) -> None:
    """4.6.7: a losing request never stages — the handler re-reads and refuses first."""
    products = _offer_products(world["catalogs"], 5)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _shelf(world, products)

    _ok(_create(lines=_lines(products[:1]), key="sale-first"))
    world["show_and_sells"].update_item(
        Key=ssm.event_metadata_key(ACTIVE_EVENT),
        UpdateExpression="SET #version = :version",
        ExpressionAttributeNames={"#version": ssm.VERSION_ATTRIBUTE},
        ExpressionAttributeValues={":version": 9},
    )

    plan.reset()
    assert_is_error(_create(lines=_lines(products[1:]), version=2, key="sale-raced"), "CONFLICT")
    assert plan.transactions == [], "the stale request staged nothing"
    assert plan.solo == []
    assert len(_sale_rows(world["show_and_sells"])) == 1
    assert len(_movement_rows(world["inventory"])) == 1
    assert len(_marker_rows(world["show_and_sells"])) == 1


def test_a_replayed_sale_writes_nothing_at_all(world: Dict[str, Any], plan: PlanRecorder) -> None:
    """4.6.7: the marker's answer to a replay is the committed sale, with zero writes."""
    products = _offer_products(world["catalogs"], 2)
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _shelf(world, products)

    committed = _ok(_create(lines=_lines(products), key="sale-replay"))
    plan.reset()
    replay = _ok(_create(lines=_lines(products), version=1, key="sale-replay"))

    assert replay["sale"]["saleId"] == committed["sale"]["saleId"]
    assert plan.transactions == [], "an identical retry writes nothing at all"
    assert plan.solo == []
    assert len(_sale_rows(world["show_and_sells"])) == 1
    assert len(_marker_rows(world["show_and_sells"])) == 1
    assert _marker_rows(world["show_and_sells"])[0]["status"] == "COMPLETED"


def test_a_sale_written_by_another_unit_admin_is_the_only_other_row_in_its_partition(
    world: Dict[str, Any], plan: PlanRecorder
) -> None:
    """4.6.7: two writers of one event still write one sale each, never one another's."""
    products = _offer_products(world["catalogs"], 4)
    world["units"].put_item(Item=grant_item(PACK_3149, "Devon", created_by="Avery"))
    _seed_event(world["show_and_sells"], ACTIVE_EVENT)
    _shelf(world, products)

    first = _ok(_create(lines=_lines(products[:2]), key="sale-avery"))
    plan.reset()
    other = _ok(_create(caller="Devon", lines=_lines(products[2:]), version=2, key="sale-devon"))

    assert len(plan.transactions) == 1
    event_pk = _wire(ssm.show_and_sell_pk(ACTIVE_EVENT))
    rows = plan.rows()
    assert (event_pk, _wire(sm.sale_sk(str(other["sale"]["saleId"])))) in rows
    assert (event_pk, _wire(sm.sale_sk(str(first["sale"]["saleId"])))) not in rows
    markers = [row for row in rows if row[1].startswith(_prefix(mutations.MARKER_SK_PREFIX))]
    assert len(markers) == 1, plan.rows()
    assert account_id("Avery") != account_id("Devon")
