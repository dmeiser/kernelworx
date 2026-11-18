"""Leaf 2.7.2 — the Stage 2 stock fixtures themselves, and the lane they belong to.

These are the tests the checklist asks for alongside the fixtures: the reusable
``SS-SM-03``/``SS-SM-04``/``SS-SM-10`` setups have to produce the smoke plan's numbers and
nothing else, the movement trail has to reconcile to the balances it produced, the last-unit
races have to be reproducible rather than flaky, and one lane's Stage 2 records have to come
out without taking another lane's with them. A fixture that cannot be shown to do those
things is a fixture every later scenario inherits an unproven assumption from.

Every stock operation runs through ``handle_unit_operation`` against moto, so a balance in
these tests is a balance the deployed resolver wrote, and the fixture's own table read is a
second view that has to agree with the resolver's payload.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

import pytest

from src.utils import inventory_models as inv
from src.utils import order_fulfillment_models as ful
from tests.unit.show_sell_fixtures import (
    PROFILES,
    account_id,
    assert_is_error,
    seed_show_sell_fixtures,
)
from tests.unit.show_sell_stock_fixtures import (
    ADMIN,
    BUTTER,
    BUTTER_START_QTY,
    CANARY_CAMPAIGN,
    CARAMEL,
    CARAMEL_FOUR_BOX_QTY,
    CHOCOLATE,
    COUNCIL_BOOTH,
    COUNCIL_LINE_ID,
    COUNCIL_PLANNING,
    DATA_ID,
    DEFAULT_LANE,
    DOOR_TO_DOOR,
    FOUR_BOX,
    SECOND_ADMIN,
    SMOKE_CATALOG_ID,
    SMOKE_PACK,
    SMOKE_PRODUCTS,
    SMOKE_UNIT_CAMPAIGNS,
    STOCK_ADMIN,
    SmokeLane,
    arrange_custody_sale,
    arrange_event_assignment,
    clean_stage2_lane,
    council_needs,
    custody_balances,
    demand_counts,
    fulfill_line,
    issue_to_scout,
    lane_inventory_rows,
    lane_orders,
    moment,
    movement_history,
    movement_trail_violations,
    order_rows,
    positions,
    product_rows,
    race_issue_last_kernel,
    race_return_last_kernel,
    record_receipt,
    return_from_scout,
    reverse_fulfillment,
    sale_totals,
    seed_smoke_lane,
    setup_ss_sm_03,
    setup_ss_sm_04,
    setup_ss_sm_10,
    smoke_join_codes,
    smoke_line,
    smoke_order,
    stock_picture,
)

#: The §7 derived quantities, spelled once so the resolver payload and the stored rows are
#: compared on the same names rather than on whatever each side happened to include.
DERIVED_KEYS = (
    "sellableKernelQty",
    "assignedOpenQty",
    "unassignedKernelQty",
    "assignmentOverageQty",
    "withScoutQty",
    "totalUnitOwnedUndeliveredQty",
)

LANE_CAMPAIGNS = (FOUR_BOX, STOCK_ADMIN, DOOR_TO_DOOR, COUNCIL_PLANNING)


@pytest.fixture
def lane(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    inventory_table: Any,
) -> Dict[str, Any]:
    """The Stage 1 personas, plus this lane's Unit, Unit Campaigns, rosters and catalog.

    The personas come first because the lane's rows name their account, profile and
    campaign ids: an issue that lands on a Scout the rest of the suite does not know would
    be a scenario nothing else can follow. ``inventory_table`` is requested so the table
    exists for the handlers, which resolve it from the environment rather than from here.
    """
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    return seed_smoke_lane(units_table, unit_campaigns_table, catalogs_table)


def _position(campaign: str, product_id: str) -> Dict[str, Any]:
    """One product's position as the resolver answers it."""
    page = positions(campaign, [product_id])
    assert len(page["items"]) == 1, f"one product in, one position out: {page!r}"
    return page["items"][0]


def _derived(payload: Dict[str, Any]) -> Dict[str, int]:
    return {key: int(payload[key]) for key in DERIVED_KEYS}


def _movement_rows(inventory_table: Any, campaign: str, product_id: str = BUTTER) -> List[Dict[str, Any]]:
    return [
        row
        for row in product_rows(inventory_table, campaign, product_id)
        if row.get(inv.ENTITY_TYPE_ATTRIBUTE) == inv.MOVEMENT_ENTITY_TYPE
    ]


def _arrange_canary(inventory_table: Any, orders_table: Any, fulfillments_table: Any) -> Dict[str, str]:
    """Stock, one Order and one real fulfillment in the campaign this lane never cleans.

    The canary is deliberately Devon's again — the same Scout Campaign the Council Order
    sold through — so the sweep is proven to select by originating scope and not by the
    campaign id an Order happens to be keyed by.
    """
    record_receipt(CANARY_CAMPAIGN, BUTTER, 2, key="canary-receipt", occurred_at=moment(60))
    order = smoke_order(
        SECOND_ADMIN,
        "canary-1",
        [smoke_line(BUTTER, 2, "line-canary-1")],
        unit_campaign_id=CANARY_CAMPAIGN,
        customer_name=f"Canary Customer {DATA_ID}",
        order_date=moment(61),
    )
    orders_table.put_item(Item=order)
    fulfill_line(str(order["orderId"]), "line-canary-1", 1, "KERNEL_STOCK", version=0, key="canary-fulfill")
    return {"orderId": str(order["orderId"]), "campaignId": str(order["campaignId"])}


# --- the lane itself ---------------------------------------------------------------


def test_the_lane_is_the_smoke_plan_s_unit_campaigns_and_three_product_catalog(
    lane: Dict[str, Any], units_table: Any, unit_campaigns_table: Any, catalogs_table: Any
) -> None:
    """The names and prices §3.3 states, because a scenario's dollars are only as good as them."""
    catalog = catalogs_table.get_item(Key={"catalogId": SMOKE_CATALOG_ID})["Item"]
    prices = {str(product["productId"]): Decimal(str(product["price"])) for product in catalog["products"]}
    assert prices == {product_id: price for product_id, (_name, price) in SMOKE_PRODUCTS.items()}
    assert set(prices) == {CARAMEL, BUTTER, CHOCOLATE}

    codes = smoke_join_codes()
    for campaign_id, campaign_name in SMOKE_UNIT_CAMPAIGNS.items():
        metadata = unit_campaigns_table.get_item(Key={"pk": f"UNIT_CAMPAIGN#{campaign_id}", "sk": "METADATA"})
        assert metadata["Item"]["campaignName"] == campaign_name
        assert metadata["Item"]["unitId"] == SMOKE_PACK
        assert metadata["Item"]["catalogId"] == SMOKE_CATALOG_ID
        assert len(codes[campaign_id]) == 16
        pointer = unit_campaigns_table.get_item(Key={"pk": f"JOIN_CODE#{codes[campaign_id]}", "sk": "POINTER"})
        assert pointer["Item"]["unitCampaignId"] == campaign_id
        roster = unit_campaigns_table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": f"UNIT_CAMPAIGN#{campaign_id}", ":prefix": "MEMBERSHIP#"},
        )
        assert len(roster["Items"]) == 2, "Alex and Casey are both on every smoke roster"

    grants = units_table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": f"UNIT#{SMOKE_PACK}", ":prefix": "GRANT#"},
    )["Items"]
    assert {str(row["accountId"]) for row in grants} == {account_id(ADMIN), account_id(SECOND_ADMIN)}


def test_the_four_box_and_door_to_door_counts_are_the_plan_s_exactly_four_and_ten(
    lane: Dict[str, Any], inventory_table: Any
) -> None:
    """Exactly 4 Caramel and 10 Butter, and the catalog product with nothing received is a zero."""
    record_receipt(FOUR_BOX, CARAMEL, CARAMEL_FOUR_BOX_QTY, key="four-box", occurred_at=moment(1))
    record_receipt(DOOR_TO_DOOR, BUTTER, BUTTER_START_QTY, key="door-stock", occurred_at=moment(2))

    caramel = _position(FOUR_BOX, CARAMEL)
    assert caramel["kernelPhysicalQty"] == 4
    assert caramel["sellableKernelQty"] == 4
    butter = _position(DOOR_TO_DOOR, BUTTER)
    assert butter["kernelPhysicalQty"] == 10
    assert butter["withScoutQty"] == 0

    chocolate = _position(FOUR_BOX, CHOCOLATE)
    assert chocolate["kernelPhysicalQty"] == 0, "the screen still has to show the product nothing arrived for"
    assert _derived(chocolate) == {key: 0 for key in DERIVED_KEYS}


# --- SS-SM-03: stock-only adjustments (steps 4-8) ---------------------------------


def test_ss_sm_03_the_trail_is_two_then_four_then_three_stock(lane: Dict[str, Any], inventory_table: Any) -> None:
    """Receipt 2, ``+2`` with a trade reason, ``-1`` gift: the plan's three balances."""
    trail = setup_ss_sm_03(inventory_table)

    assert [step["after"]["kernelPhysicalQty"] for step in trail] == [2, 4, 3, 4]
    assert trail[0]["after"]["sellableKernelQty"] == 2
    assert trail[1]["after"]["unassignedKernelQty"] == 4
    assert trail[2]["after"]["kernelPhysicalQty"] == 3
    assert trail[2]["after"]["balanceVersion"] == 3, "three writes, one balance, three versions"


def test_ss_sm_03_a_stock_only_adjustment_creates_no_sale_payment_or_fulfillment(
    lane: Dict[str, Any],
    inventory_table: Any,
    orders_table: Any,
    order_fulfillments_table: Any,
    campaigns_table: Any,
) -> None:
    """The separation the stock count is reconciled against: stock moved, money did not."""
    before = sorted(str(item["campaignId"]) for item in campaigns_table.scan()["Items"])
    setup_ss_sm_03(inventory_table)

    assert orders_table.scan()["Items"] == [], "an adjustment that opened an Order is a sale nobody sold"
    assert order_fulfillments_table.scan()["Items"] == []
    assert sorted(str(item["campaignId"]) for item in campaigns_table.scan()["Items"]) == before
    assert {row[inv.MOVEMENT_TYPE_ATTRIBUTE] for row in _movement_rows(inventory_table, STOCK_ADMIN)} == {
        inv.RECEIPT,
        inv.STOCK_ADJUSTMENT,
    }


def test_ss_sm_03_the_history_names_product_quantity_actor_reason_and_timestamp(
    lane: Dict[str, Any], inventory_table: Any
) -> None:
    """Steps 7 and 8: the trail is readable, and the second admin is named as herself."""
    setup_ss_sm_03(inventory_table)
    newest_first = movement_history(STOCK_ADMIN)["items"]

    assert [row["movementType"] for row in newest_first] == [
        inv.RECEIPT,
        inv.STOCK_ADJUSTMENT,
        inv.STOCK_ADJUSTMENT,
        inv.RECEIPT,
    ]
    assert [row["occurredAt"] for row in newest_first] == [moment(4), moment(3), moment(2), moment(1)]
    assert newest_first[0]["actorAccountId"] == account_id(SECOND_ADMIN)
    assert newest_first[0]["kernelPhysicalDelta"] == 1
    assert newest_first[1]["reason"] == "Gift to outgoing volunteer"
    assert newest_first[1]["actorAccountId"] == account_id(ADMIN)
    assert newest_first[2]["reason"] == "Trade with Troop 7150; money settled outside app"
    assert all(row["productId"] == BUTTER for row in newest_first)


def test_ss_sm_03_a_movement_filter_returns_what_it_names(lane: Dict[str, Any], inventory_table: Any) -> None:
    """The history screen's filters, because an audit list that ignores one is a wrong list."""
    setup_ss_sm_03(inventory_table)

    adjustments = movement_history(STOCK_ADMIN, movementType=inv.STOCK_ADJUSTMENT)["items"]
    assert len(adjustments) == 2
    assert {row["movementType"] for row in adjustments} == {inv.STOCK_ADJUSTMENT}
    assert len(movement_history(STOCK_ADMIN, productId=BUTTER)["items"]) == 4
    assert movement_history(STOCK_ADMIN, productId=CARAMEL)["items"] == []
    assert movement_history(STOCK_ADMIN, profileId=str(PROFILES[ADMIN]["profileId"]))["items"] == []
    window = movement_history(STOCK_ADMIN, dateRange={"startAt": moment(1), "endAt": moment(3)})["items"]
    assert [row["occurredAt"] for row in window] == [moment(3), moment(2), moment(1)]


def test_the_movement_trail_reconciles_to_the_balances_it_explains(lane: Dict[str, Any], inventory_table: Any) -> None:
    """The reconciliation leaf 2.8.7 runs: summed deltas equal the stored quantities."""
    setup_ss_sm_03(inventory_table)

    assert movement_trail_violations(inventory_table, STOCK_ADMIN, BUTTER) == []
    balances = [
        row
        for row in product_rows(inventory_table, STOCK_ADMIN, BUTTER)
        if row.get(inv.ENTITY_TYPE_ATTRIBUTE) == inv.BALANCE_ENTITY_TYPE
    ]
    assert len(balances) == 1, "four writes, one balance"
    assert inv.balance_invariant_violations(balances[0]) == []


def test_the_reconciler_notices_a_trail_that_stops_explaining_the_balance(
    lane: Dict[str, Any], inventory_table: Any
) -> None:
    """A checker that cannot fail is not a checker: one stray row has to be caught."""
    setup_ss_sm_03(inventory_table)
    inventory_table.put_item(
        Item=inv.build_inventory_movement_item(
            movement_id="MOVEMENT#phantom-receipt",
            unit_campaign_id=STOCK_ADMIN,
            product_id=BUTTER,
            movement_type=inv.RECEIPT,
            actor_account_id=account_id(ADMIN),
            occurred_at=moment(50),
            idempotency_key="phantom",
            kernel_physical_delta=5,
        )
    )

    violations = movement_trail_violations(inventory_table, STOCK_ADMIN, BUTTER)
    assert violations == [
        "sum(kernelPhysicalDelta) = 9 but the balance carries kernelPhysicalQty = 4",
    ]


# --- SS-SM-04: custody, sales and the return (steps 1-7) -------------------------


def test_ss_sm_04_the_sequence_ends_kernel_five_with_scout_one_and_six_owned(
    lane: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """Issue 4 → sale 3 → sale 2 → issue 2 → return 1, in the plan's balances at every step."""
    steps = setup_ss_sm_04(inventory_table, orders_table, order_fulfillments_table)

    def at(step: int, key: str) -> Any:
        return steps[step - 1][key]

    assert at(1, "after")["kernelPhysicalQty"] == 10
    assert at(2, "after")["kernelPhysicalQty"] == 6
    assert at(2, "after")["withScoutQty"] == 4
    assert at(2, "after")["totalUnitOwnedUndeliveredQty"] == 10, "issuing moves stock, it does not create it"
    assert at(3, "after")["withScoutQty"] == 1
    assert at(3, "after")["kernelPhysicalQty"] == 6, "a sale out of custody never touches Kernel physical"
    assert at(4, "after")["withScoutQty"] == 0, "With Scout stops at zero rather than going negative"
    assert at(4, "after")["totalUnitOwnedUndeliveredQty"] == 6
    assert at(5, "after")["kernelPhysicalQty"] == 4
    assert at(6, "after")["kernelPhysicalQty"] == 5
    assert at(6, "after")["withScoutQty"] == 1
    assert at(6, "after")["totalUnitOwnedUndeliveredQty"] == 6
    assert at(6, "after")["unassignedKernelQty"] == 5, "the Scout's unit is not available event stock"


def test_ss_sm_04_the_two_sales_leave_one_unit_still_owed(
    lane: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """Steps 2-4: three fulfilled, then one fulfilled and one unfulfilled, ``$100`` and five units."""
    steps = setup_ss_sm_04(inventory_table, orders_table, order_fulfillments_table)

    assert steps[2]["demand"] == {"orderedQty": 3, "fulfilledQty": 3, "unfulfilledQty": 0}
    assert steps[3]["demand"] == {"orderedQty": 5, "fulfilledQty": 4, "unfulfilledQty": 1}
    assert steps[5]["demand"] == {"orderedQty": 5, "fulfilledQty": 4, "unfulfilledQty": 1}
    assert steps[5]["sales"] == {
        "orderCount": 2,
        "money": Decimal("100"),
        "units": 5,
        "fulfilledQty": 4,
    }
    assert demand_counts(orders_table, [DOOR_TO_DOOR], BUTTER)["unfulfilledQty"] == 1
    assert sale_totals(orders_table, [DOOR_TO_DOOR])["money"] == Decimal("100")


def test_ss_sm_04_a_sale_consuming_no_custody_writes_no_stock_history(
    lane: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """The line that finds an empty trunk still sells, and owes Council demand instead.

    SS-SM-04 step 3 is the partial case; this is the case one step past it, where With
    Scout is already zero. Refusing the sale would lose the customer's order, and writing a
    fulfillment for stock nobody consumed would break the audit trail's arithmetic.
    """
    record_receipt(DOOR_TO_DOOR, BUTTER, 1, key="empty-trunk-receipt", occurred_at=moment(20))
    issue_to_scout(DOOR_TO_DOOR, ADMIN, BUTTER, 1, key="empty-trunk-issue", occurred_at=moment(21))
    first = arrange_custody_sale(
        orders_table,
        inventory_table,
        order_fulfillments_table,
        scout=ADMIN,
        unit_campaign_id=DOOR_TO_DOOR,
        suffix="empty-trunk-1",
        product_id=BUTTER,
        quantity=1,
        line_item_id="line-empty-1",
        occurred_at=moment(22),
        idempotency_key="empty-trunk-sale-1",
    )
    second = arrange_custody_sale(
        orders_table,
        inventory_table,
        order_fulfillments_table,
        scout=ADMIN,
        unit_campaign_id=DOOR_TO_DOOR,
        suffix="empty-trunk-2",
        product_id=BUTTER,
        quantity=2,
        line_item_id="line-empty-2",
        occurred_at=moment(23),
        idempotency_key="empty-trunk-sale-2",
    )

    assert (first["consumedQty"], first["unfulfilledQty"]) == (1, 0)
    assert (second["consumedQty"], second["unfulfilledQty"]) == (0, 2)
    picture = stock_picture(inventory_table, DOOR_TO_DOOR, BUTTER)
    assert (picture["kernelPhysicalQty"], picture["withScoutQty"]) == (0, 0)
    assert len(ful.fulfillment_rows(str(second["order"]["orderId"]))) == 0
    fills = [
        row
        for row in _movement_rows(inventory_table, DOOR_TO_DOOR)
        if row[inv.MOVEMENT_TYPE_ATTRIBUTE] == inv.INDIVIDUAL_FULFILL
    ]
    assert [(int(row[inv.KERNEL_PHYSICAL_DELTA]), int(row[inv.WITH_SCOUT_DELTA])) for row in fills] == [(0, -1)]
    assert movement_trail_violations(inventory_table, DOOR_TO_DOOR, BUTTER) == []


def test_ss_sm_04_returning_more_than_the_scout_holds_moves_nothing(
    lane: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """The over-return the one-click screen has to refuse before it writes (§2.6.2)."""
    setup_ss_sm_04(inventory_table, orders_table, order_fulfillments_table)
    before = stock_picture(inventory_table, DOOR_TO_DOOR, BUTTER)
    trail_before = len(_movement_rows(inventory_table, DOOR_TO_DOOR))

    refused = assert_is_error(
        return_from_scout(DOOR_TO_DOOR, ADMIN, [(BUTTER, 4)], key="sm04-over-return"), "INVALID_INPUT"
    )
    assert "1 Kernels" in refused["message"]

    assert stock_picture(inventory_table, DOOR_TO_DOOR, BUTTER) == before
    assert len(_movement_rows(inventory_table, DOOR_TO_DOOR)) == trail_before, "a refused return leaves no audit row"
    returned = [
        row
        for row in _movement_rows(inventory_table, DOOR_TO_DOOR)
        if row[inv.MOVEMENT_TYPE_ATTRIBUTE] == inv.SCOUT_RETURN
    ]
    assert len(returned) == 1, "only the plan's step-6 return is on the trail"


def test_ss_sm_04_the_per_scout_view_and_the_position_agree(
    lane: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """Step 7: Avery's one remaining unit is visible, and it is not counted as available stock."""
    setup_ss_sm_04(inventory_table, orders_table, order_fulfillments_table)
    page = custody_balances(DOOR_TO_DOOR)

    assert page["totalWithScoutQty"] == 1
    assert [(row["profileId"], row["withScoutQty"]) for row in page["items"]] == [
        (str(PROFILES[ADMIN]["profileId"]), 1)
    ]
    assert page["items"][0]["campaignId"] == str(PROFILES[ADMIN]["campaignId"])
    position = _position(DOOR_TO_DOOR, BUTTER)
    assert position["withScoutQty"] == 1
    assert position["unassignedKernelQty"] == 5
    assert position["totalUnitOwnedUndeliveredQty"] == 6


# --- SS-SM-10: Council demand and both fulfillment sources -----------------------


def test_ss_sm_10_the_starting_balances_are_the_plan_s_six_two_four_two_and_three(
    lane: Dict[str, Any], inventory_table: Any, orders_table: Any
) -> None:
    """Demand 10, With Scout 2, Kernel 6, assigned 4, unassigned 2, on order 3, owned 8."""
    setup_ss_sm_10(inventory_table, orders_table)
    picture = stock_picture(inventory_table, COUNCIL_PLANNING, BUTTER)

    assert picture["kernelPhysicalQty"] == 6
    assert picture["sellableKernelQty"] == 6
    assert picture["assignedOpenQty"] == 4
    assert picture["unassignedKernelQty"] == 2
    assert picture["assignmentOverageQty"] == 0
    assert picture["withScoutQty"] == 2
    assert picture["totalUnitOwnedUndeliveredQty"] == 8
    assert picture["councilOnOrderQty"] == 3
    assert picture["allocations"] == [{"showAndSellId": COUNCIL_BOOTH, "remainingQty": 4}]
    assert demand_counts(orders_table, [COUNCIL_PLANNING], BUTTER) == {
        "orderedQty": 10,
        "fulfilledQty": 0,
        "unfulfilledQty": 10,
    }
    assert council_needs(10, picture) == {"PHYSICAL_STOCK": 4, "AFTER_ASSIGNMENTS": 8}


def test_the_position_payload_and_the_stored_rows_answer_with_the_same_numbers(
    lane: Dict[str, Any], inventory_table: Any, orders_table: Any
) -> None:
    """The resolver and the fixture read the same history, so a scenario can trust either."""
    setup_ss_sm_10(inventory_table, orders_table)
    picture = stock_picture(inventory_table, COUNCIL_PLANNING, BUTTER)

    assert _derived(_position(COUNCIL_PLANNING, BUTTER)) == _derived(picture)


def test_ss_sm_10_both_needs_survive_a_kernel_fulfillment_and_move_on_an_external_one(
    lane: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """Steps 5 and 6: Kernel stock answers demand on both sides, Council supply answers only demand."""
    council = setup_ss_sm_10(inventory_table, orders_table)
    order_id = council["orderId"]
    demand = 10

    refused_source = fulfill_line(order_id, COUNCIL_LINE_ID, 1, "SCOUT_CUSTODY", version=0, key="sm10-custody")
    assert_is_error(refused_source, "INVALID_INPUT")

    kernel = _ok(fulfill_line(order_id, COUNCIL_LINE_ID, 1, "KERNEL_STOCK", version=0, key="sm10-kernel"))
    assert kernel["inventoryPosition"]["unassignedKernelQty"] == 1
    demand = demand_counts(orders_table, [COUNCIL_PLANNING], BUTTER)["unfulfilledQty"]
    picture = stock_picture(inventory_table, COUNCIL_PLANNING, BUTTER)
    assert demand == 9
    assert (picture["kernelPhysicalQty"], picture["sellableKernelQty"], picture["unassignedKernelQty"]) == (5, 5, 1)
    assert council_needs(demand, picture) == {"PHYSICAL_STOCK": 4, "AFTER_ASSIGNMENTS": 8}, "both sides fell by one"

    external = _ok(fulfill_line(order_id, COUNCIL_LINE_ID, 1, "EXTERNAL_COUNCIL", version=1, key="sm10-external"))
    assert "inventoryPosition" not in external, "no Kernel moved, so no position may be reported"
    demand = demand_counts(orders_table, [COUNCIL_PLANNING], BUTTER)["unfulfilledQty"]
    picture = stock_picture(inventory_table, COUNCIL_PLANNING, BUTTER)
    assert demand == 8
    assert (picture["kernelPhysicalQty"], picture["councilOnOrderQty"]) == (5, 3), "on order moves only when named"
    assert council_needs(demand, picture) == {"PHYSICAL_STOCK": 3, "AFTER_ASSIGNMENTS": 7}
    assert movement_trail_violations(inventory_table, COUNCIL_PLANNING, BUTTER) == []
    fills = [
        row
        for row in _movement_rows(inventory_table, COUNCIL_PLANNING)
        if row[inv.MOVEMENT_TYPE_ATTRIBUTE] == inv.INDIVIDUAL_FULFILL
    ]
    assert len(fills) == 1, "the external fill writes no movement of its own"
    assert len(_movement_rows(inventory_table, COUNCIL_PLANNING)) == 4, "receipt, issue, on order, one Kernel fill"


def test_ss_sm_10_fulfillment_versions_move_for_both_sources(
    lane: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """A stale version is refused, and a refused fulfillment leaves no partial effect."""
    council = setup_ss_sm_10(inventory_table, orders_table)
    order_id = council["orderId"]
    scout_campaign = str(PROFILES[SECOND_ADMIN]["campaignId"])

    _ok(fulfill_line(order_id, COUNCIL_LINE_ID, 1, "KERNEL_STOCK", version=0, key="v-kernel"))
    _ok(fulfill_line(order_id, COUNCIL_LINE_ID, 1, "EXTERNAL_COUNCIL", version=1, key="v-external"))
    order = orders_table.get_item(Key={"campaignId": scout_campaign, "orderId": order_id})["Item"]
    assert order["fulfillmentVersion"] == 2
    assert [line["fulfilledQuantity"] for line in order["lineItems"]] == [2]

    before = (
        stock_picture(inventory_table, COUNCIL_PLANNING, BUTTER),
        len(_movement_rows(inventory_table, COUNCIL_PLANNING)),
    )
    assert_is_error(fulfill_line(order_id, COUNCIL_LINE_ID, 1, "KERNEL_STOCK", version=1, key="v-stale"), "CONFLICT")
    assert stock_picture(inventory_table, COUNCIL_PLANNING, BUTTER) == before[0]
    assert len(_movement_rows(inventory_table, COUNCIL_PLANNING)) == before[1]
    assert len(ful.fulfillment_rows(order_id)) == 2


def test_ss_sm_10_a_reversal_restores_the_source_it_came_from_once(
    lane: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """Kernel stock comes back, demand is owed again, and the same fulfillment cannot reverse twice."""
    council = setup_ss_sm_10(inventory_table, orders_table)
    order_id = council["orderId"]

    kernel = _ok(fulfill_line(order_id, COUNCIL_LINE_ID, 1, "KERNEL_STOCK", version=0, key="rev-kernel"))
    fulfillment_id = str(kernel["fulfillment"]["fulfillmentId"])
    reversal = _ok(reverse_fulfillment(order_id, fulfillment_id, version=1, key="rev-once"))
    assert reversal["reversal"]["reversalOfFulfillmentId"] == fulfillment_id
    assert reversal["inventoryPosition"]["kernelPhysicalQty"] == 6

    picture = stock_picture(inventory_table, COUNCIL_PLANNING, BUTTER)
    assert (picture["kernelPhysicalQty"], picture["unassignedKernelQty"]) == (6, 2)
    assert demand_counts(orders_table, [COUNCIL_PLANNING], BUTTER)["unfulfilledQty"] == 10
    assert movement_trail_violations(inventory_table, COUNCIL_PLANNING, BUTTER) == []

    assert_is_error(reverse_fulfillment(order_id, fulfillment_id, version=2, key="rev-twice"), "CONFLICT")
    assert len(ful.fulfillment_rows(order_id)) == 2, "one fulfillment, one reversal, no more"


# --- last-unit races --------------------------------------------------------------


def test_the_race_for_the_last_kernel_moves_the_unit_exactly_once(
    lane: Dict[str, Any], inventory_table: Any
) -> None:
    """Two issues of one Kernel, both planned from one read: one commits, and the loser writes nothing."""
    record_receipt(DOOR_TO_DOOR, BUTTER, 1, key="race-receipt", occurred_at=moment(30))

    result = race_issue_last_kernel(inventory_table, quantity=1, occurred_at=moment(31))

    assert [verdict["committed"] for verdict in result["verdicts"]] == [True, False]
    assert result["committed"] == 1
    assert result["verdicts"][1]["code"] == "TransactionCanceledException"
    picture = stock_picture(inventory_table, DOOR_TO_DOOR, BUTTER)
    assert (picture["kernelPhysicalQty"], picture["withScoutQty"]) == (0, 1)
    assert [row[inv.MOVEMENT_TYPE_ATTRIBUTE] for row in _movement_rows(inventory_table, DOOR_TO_DOOR)] == [
        inv.RECEIPT,
        inv.SCOUT_ISSUE,
    ]
    assert movement_trail_violations(inventory_table, DOOR_TO_DOOR, BUTTER) == []


def test_the_race_for_the_last_custody_unit_returns_it_exactly_once(
    lane: Dict[str, Any], inventory_table: Any
) -> None:
    """With Scout cannot go negative and a Unit cannot be handed the same Kernel twice."""
    record_receipt(DOOR_TO_DOOR, BUTTER, 1, key="return-race-receipt", occurred_at=moment(32))
    issue_to_scout(DOOR_TO_DOOR, ADMIN, BUTTER, 1, key="return-race-issue", occurred_at=moment(33))

    result = race_return_last_kernel(inventory_table, quantity=1, occurred_at=moment(34))

    assert result["committed"] == 1
    assert result["verdicts"][1]["code"] == "TransactionCanceledException"
    picture = stock_picture(inventory_table, DOOR_TO_DOOR, BUTTER)
    assert (picture["kernelPhysicalQty"], picture["withScoutQty"]) == (1, 0)
    assert [row[inv.MOVEMENT_TYPE_ATTRIBUTE] for row in _movement_rows(inventory_table, DOOR_TO_DOOR)] == [
        inv.RECEIPT,
        inv.SCOUT_ISSUE,
        inv.SCOUT_RETURN,
    ]
    assert movement_trail_violations(inventory_table, DOOR_TO_DOOR, BUTTER) == []


# --- lane cleanup (leaf 2.8.7) ---------------------------------------------------


def test_cleaning_one_lane_leaves_the_canary_lane_and_the_personas_alone(
    lane: Dict[str, Any],
    inventory_table: Any,
    orders_table: Any,
    order_fulfillments_table: Any,
    units_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
) -> None:
    """Every Stage 2 record this lane wrote is removable, and one campaign's is not."""
    people = {
        name: sorted(str(item) for item in table.scan()["Items"])
        for name, table in (("units", units_table), ("profiles", profiles_table), ("campaigns", campaigns_table))
    }
    setup_ss_sm_04(inventory_table, orders_table, order_fulfillments_table)
    council = setup_ss_sm_10(inventory_table, orders_table)
    _ok(fulfill_line(council["orderId"], COUNCIL_LINE_ID, 1, "KERNEL_STOCK", version=0, key="clean-fulfill"))
    canary = _arrange_canary(inventory_table, orders_table, order_fulfillments_table)
    devon_campaign = str(PROFILES[SECOND_ADMIN]["campaignId"])
    assert len(order_rows(orders_table, devon_campaign)) == 2, "Council and canary sales share one Scout Campaign"
    expected_inventory = sum(len(lane_inventory_rows(inventory_table, campaign_id)) for campaign_id in LANE_CAMPAIGNS)
    assert expected_inventory > 0

    removed = clean_stage2_lane(inventory_table, orders_table, order_fulfillments_table, DEFAULT_LANE)

    assert removed["orders"] == 3, "two door-to-door sales and the Council Order"
    assert removed["fulfillments"] == 3, "two custody fills and one Kernel fill, the canary's aside"
    assert removed["inventory"] == expected_inventory
    assert removed["markers"] > 0
    for campaign_id in LANE_CAMPAIGNS:
        assert lane_inventory_rows(inventory_table, campaign_id) == []
    assert lane_orders(orders_table, LANE_CAMPAIGNS) == []
    assert [str(row["orderId"]) for row in order_rows(orders_table, devon_campaign)] == [canary["orderId"]]

    assert len(ful.fulfillment_rows(canary["orderId"])) == 1, "the canary's fulfillment history survives"
    assert lane_orders(orders_table, [CANARY_CAMPAIGN])[0]["orderId"] == canary["orderId"]
    canary_markers = [
        str(row["pk"]) for row in inventory_table.scan()["Items"] if str(row["pk"]).startswith("IDEM#")
    ]
    assert canary_markers and all(CANARY_CAMPAIGN in pk for pk in canary_markers)
    canary_stock = stock_picture(inventory_table, CANARY_CAMPAIGN, BUTTER)
    assert canary_stock["kernelPhysicalQty"] == 1
    assert len(_movement_rows(inventory_table, CANARY_CAMPAIGN)) == 2
    for name, table in (("units", units_table), ("profiles", profiles_table), ("campaigns", campaigns_table)):
        assert sorted(str(item) for item in table.scan()["Items"]) == people[name]


def test_cleanup_takes_the_idempotency_markers_a_lane_s_writes_left_behind(
    lane: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """Markers live under their own ``IDEM#`` partition, so a partition sweep alone misses them."""
    setup_ss_sm_03(inventory_table)
    council = setup_ss_sm_10(inventory_table, orders_table)
    _ok(fulfill_line(council["orderId"], COUNCIL_LINE_ID, 1, "KERNEL_STOCK", version=0, key="marker-fulfill"))

    def markers(table: Any) -> List[str]:
        return [str(row["pk"]) for row in table.scan()["Items"] if str(row["pk"]).startswith("IDEM#")]

    inventory_markers = markers(inventory_table)
    fulfillment_markers = markers(order_fulfillments_table)
    assert any(STOCK_ADMIN in pk for pk in inventory_markers), "a receipt leaves its marker on the inventory table"
    assert any(COUNCIL_PLANNING in pk for pk in inventory_markers)
    assert fulfillment_markers != [], "the fulfillment's marker sits on the fulfillments table, not the Order"

    removed = clean_stage2_lane(inventory_table, orders_table, order_fulfillments_table, DEFAULT_LANE)

    assert removed["markers"] == len(inventory_markers) + len(fulfillment_markers)
    assert markers(inventory_table) == []
    assert markers(order_fulfillments_table) == []
    again = clean_stage2_lane(inventory_table, orders_table, order_fulfillments_table, DEFAULT_LANE)
    assert again == {"inventory": 0, "markers": 0, "orders": 0, "fulfillments": 0}, "cleanup is idempotent"


# --- lane identity: one scenario, two attempts (leaf 2.7.2, smoke plan §3.1) ------


def test_a_second_attempt_runs_the_same_scenario_beside_the_first_and_is_cleaned_alone(
    lane: Dict[str, Any],
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    inventory_table: Any,
    orders_table: Any,
    order_fulfillments_table: Any,
) -> None:
    """FIX-AC-03: a retry does not inherit, replay, or delete the attempt it is retrying.

    The smoke plan makes the lane's identity ``<RUN_ID>-<SCENARIO_ID>-<LANE_ID>-<ATTEMPT_ID>``
    and its stamps setup-relative for a reason: two attempts of one scenario sit in the same
    Stage 1 personas and the same Scout Campaigns, so the only thing separating their rows,
    idempotency keys and markers is the identity each one derives its ids from. A fixed
    ``DATA_ID`` makes a retried attempt answer the earlier attempt's stored result and makes one
    lane's cleanup able to eat the other's evidence.
    """
    first = DEFAULT_LANE
    second = SmokeLane.new("SS-SM-04", run_id="1763600000-aaaaaa", attempt_id="bbbbbb")
    seed_smoke_lane(units_table, unit_campaigns_table, catalogs_table, lane=second)

    setup_ss_sm_04(inventory_table, orders_table, order_fulfillments_table, lane=first)
    setup_ss_sm_04(inventory_table, orders_table, order_fulfillments_table, lane=second)

    assert second.pack != SMOKE_PACK
    assert second.door_to_door != DOOR_TO_DOOR
    assert second.butter != BUTTER
    assert second.key("receipt") != first.key("receipt"), "one label, two writes, no replayed result"
    assert second.moment(1) != first.moment(1), "stamps are setup-relative, not a calendar date"
    assert smoke_join_codes(second)[second.door_to_door] != smoke_join_codes(first)[first.door_to_door]

    assert lane_inventory_rows(inventory_table, first.door_to_door) != []
    assert lane_inventory_rows(inventory_table, second.door_to_door) != []

    first_markers = [
        str(row["pk"]) for row in order_fulfillments_table.scan()["Items"] if str(row["pk"]).startswith("IDEM#")
    ]
    assert len(first_markers) == 4, "two sale markers per attempt, in two attempts"

    removed = clean_stage2_lane(inventory_table, orders_table, order_fulfillments_table, first)

    assert removed["orders"] == 2, "only the first attempt's two sales"
    for campaign_id in first.stock_campaign_ids:
        assert lane_inventory_rows(inventory_table, campaign_id) == []
    assert lane_orders(orders_table, first.stock_campaign_ids) == []

    assert stock_picture(inventory_table, second.door_to_door, second.butter)["kernelPhysicalQty"] == 5
    assert stock_picture(inventory_table, second.door_to_door, second.butter)["withScoutQty"] == 1
    assert demand_counts(orders_table, [second.door_to_door], second.butter) == {
        "orderedQty": 5,
        "fulfilledQty": 4,
        "unfulfilledQty": 1,
    }
    assert sale_totals(orders_table, [second.door_to_door])["money"] == Decimal("100")
    assert movement_trail_violations(inventory_table, second.door_to_door, second.butter) == []
    assert sale_totals(orders_table, [second.door_to_door])["orderCount"] == 2
    surviving = lane_orders(orders_table, [second.door_to_door])
    assert len(surviving) == 2
    assert all(second.attempt_key in str(row["orderId"]) for row in surviving), "the suffix names its attempt"
    assert all(second.attempt_key in str(line["lineItemId"]) for row in surviving for line in row["lineItems"])
    assert all(str(row["unitId"]) == second.pack for row in surviving), "the sale names this attempt's Unit"
    surviving_ids = {str(row["orderId"]) for row in surviving}
    records = [row for row in order_fulfillments_table.scan()["Items"] if str(row.get("orderId")) in surviving_ids]
    assert records, "the second attempt's sale wrote fulfillment history"
    assert all(str(row["unitId"]) == second.pack for row in records), "so does the history that copies it"
    survivors = [
        str(row["pk"]) for row in order_fulfillments_table.scan()["Items"] if str(row["pk"]).startswith("IDEM#")
    ]
    assert len(survivors) == 2, "the second attempt's replay markers are its own"
    assert catalogs_table.get_item(Key={"catalogId": second.catalog_id}).get("Item") is not None
    assert unit_campaigns_table.get_item(Key={"pk": f"UNIT_CAMPAIGN#{second.door_to_door}", "sk": "METADATA"}).get(
        "Item"
    ) is not None


# --- origin scope: a Scout Campaign is shared, a lane's demand is not -------------


def test_council_demand_and_sale_totals_ignore_another_campaign_s_orders_in_the_same_scout_campaign(
    lane: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """FUNC-6: the plan's ten units are this campaign's ten, with another lane's Order present.

    Orders are keyed by Scout Campaign, and the personas' Scout Campaigns are shared by every
    lane and every campaign in this suite. Counted by that key, Council demand would carry the
    canary's two units too, and the scenario would be asserting a number no campaign owes.
    """
    setup_ss_sm_04(inventory_table, orders_table, order_fulfillments_table)
    council = setup_ss_sm_10(inventory_table, orders_table)
    setup_order_id = council["orderId"]
    canary = _arrange_canary(inventory_table, orders_table, order_fulfillments_table)
    devon_campaign = str(PROFILES[SECOND_ADMIN]["campaignId"])

    assert demand_counts(orders_table, [COUNCIL_PLANNING], BUTTER) == {
        "orderedQty": 10,
        "fulfilledQty": 0,
        "unfulfilledQty": 10,
    }
    assert sale_totals(orders_table, [COUNCIL_PLANNING]) == {
        "orderCount": 1,
        "money": Decimal("200"),
        "units": 10,
        "fulfilledQty": 0,
    }
    assert sale_totals(orders_table, [DOOR_TO_DOOR, COUNCIL_PLANNING])["orderCount"] == 3

    shared = order_rows(orders_table, devon_campaign)
    assert {str(row["orderId"]) for row in shared} == {canary["orderId"], str(setup_order_id)}
    assert len(shared) == 2, "the canary sells through Devon's Scout Campaign too"
    assert sum(len(row["lineItems"]) for row in shared) == 2
    assert demand_counts(orders_table, [CANARY_CAMPAIGN], BUTTER) == {
        "orderedQty": 2,
        "fulfilledQty": 1,
        "unfulfilledQty": 1,
    }, "the canary's demand is the canary's own"


# --- markers: the sweep reaches the one a sale wrote, not only the ones it can grep --


def test_a_custody_sale_s_replay_marker_is_removed_by_the_order_it_answers(
    lane: Dict[str, Any], inventory_table: Any, orders_table: Any, order_fulfillments_table: Any
) -> None:
    """FUNC-7: a ``createOrder`` marker names no campaign and no Order id in its key.

    The arrangement writes the marker at the address the pipeline would use — actor, operation,
    Scout Campaign — so the cleanup is proven against the shape that actually survives a
    partition sweep, rather than against the shape the sweep was already able to find.
    """
    setup_ss_sm_04(inventory_table, orders_table, order_fulfillments_table)
    sold = [str(row["orderId"]) for row in lane_orders(orders_table, [DOOR_TO_DOOR])]
    assert len(sold) == 2

    sale_markers = [
        row
        for row in order_fulfillments_table.scan()["Items"]
        if "#createOrder#" in str(row.get("pk", ""))
    ]
    assert len(sale_markers) == 2, "one marker per arranged sale"
    assert all(mk["resultId"] in sold for mk in sale_markers)
    assert all(mk["status"] == "COMPLETED" for mk in sale_markers)
    for marker in sale_markers:
        assert DOOR_TO_DOOR not in str(marker["pk"]), "the key names the Scout Campaign, not the Unit Campaign"
        assert not any(order_id.replace("#", "%23") in str(marker["pk"]) for order_id in sold), (
            "no search for an Order id reaches this marker"
        )

    def marker_count(table: Any) -> int:
        return len([row for row in table.scan()["Items"] if str(row["pk"]).startswith("IDEM#")])

    inventory_before = marker_count(inventory_table)
    fulfillment_before = marker_count(order_fulfillments_table)
    assert inventory_before == 4, "receipt, two issues and one return leave their markers on the stock table"
    assert fulfillment_before == 2, "each sale leaves one createOrder marker"

    removed = clean_stage2_lane(inventory_table, orders_table, order_fulfillments_table, DEFAULT_LANE)

    assert removed["markers"] == inventory_before + fulfillment_before
    assert [row for row in order_fulfillments_table.scan()["Items"] if str(row["pk"]).startswith("IDEM#")] == []
    assert [row for row in inventory_table.scan()["Items"] if str(row["pk"]).startswith("IDEM#")] == []


def test_the_lane_reads_walk_past_one_dynamodb_page() -> None:
    """One Scout Campaign holds more Orders than one 1 MB page, and the sweep counts them all.

    ``LastEvaluatedKey`` is a cursor, not a footnote: a reader that stops at the first page
    reports a lane's demand as short and its cleanup as complete while rows of both are still
    in the table.
    """
    pages = [
        {"Items": [{"orderId": "ORDER#1", "unitCampaignId": DOOR_TO_DOOR}], "LastEvaluatedKey": {"orderId": "ORDER#1"}},
        {"Items": [{"orderId": "ORDER#2", "unitCampaignId": DOOR_TO_DOOR}]},
    ]
    calls: List[Dict[str, Any]] = []

    class TwoPageScan:
        """A stand-in for the orders table that answers exactly two Scan pages."""

        def scan(self, **kwargs: Any) -> Dict[str, Any]:
            calls.append(kwargs)
            return pages[len(calls) - 1]

    rows = lane_orders(TwoPageScan(), [DOOR_TO_DOOR])

    assert [str(row["orderId"]) for row in rows] == ["ORDER#1", "ORDER#2"]
    assert len(calls) == 2, "the walk stopped at the first page"
    assert calls[1]["ExclusiveStartKey"] == {"orderId": "ORDER#1"}
    assert "ExclusiveStartKey" not in calls[0]


def test_an_assignment_arranged_for_the_scenario_stays_out_of_the_trail_check(
    lane: Dict[str, Any], inventory_table: Any
) -> None:
    """The one column the reconciler does not balance, stated rather than quietly passed.

    §3.2 owns the ``EVENT_ASSIGN`` write and has not landed, so an allocation row has no
    movement behind it in any lane this suite can build. Recording that as an exception is
    the honest version: when §3.2 lands, the lane gains a movement and this test gains its
    reconciliation for free.
    """
    record_receipt(COUNCIL_PLANNING, BUTTER, 8, key="assign-receipt", occurred_at=moment(40))
    arrange_event_assignment(
        inventory_table,
        campaign=COUNCIL_PLANNING,
        product_id=BUTTER,
        quantity=4,
        start_at=moment(41),
        end_at=moment(200),
    )

    picture = stock_picture(inventory_table, COUNCIL_PLANNING, BUTTER)
    assert (picture["assignedOpenQty"], picture["unassignedKernelQty"]) == (4, 4)
    assert movement_trail_violations(inventory_table, COUNCIL_PLANNING, BUTTER) == []
    assert inv.EVENT_ASSIGN not in {row[inv.MOVEMENT_TYPE_ATTRIBUTE] for row in _movement_rows(inventory_table, COUNCIL_PLANNING)}


def _ok(payload: Any) -> Dict[str, Any]:
    """A payload the resolver was allowed to answer with."""
    failed = isinstance(payload, dict) and payload.get("__isError")
    assert not failed, f"expected a success payload, got {payload!r}"
    return payload
