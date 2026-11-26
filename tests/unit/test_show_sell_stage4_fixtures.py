"""The Stage 4 sales fixtures themselves, and the lane they belong to.

Leaf 4.5.3. These are the tests the checklist asks for alongside the fixtures: the
SS-SM-07 setup has to produce the smoke plan's numbers and nothing else, the two blocked
steps have to leave no partial effects, the movement trail has to reconcile to the balances
it produced including ``assignedDelta``, and one lane's Stage 4 records have to come out
without taking another lane's with them — including a second attempt of the same scenario.

Every stock, event, sale and We Owe write runs through ``handle_unit_operation`` against
moto, so a number in these tests is a number the deployed resolver wrote, and the fixture's
own table read is a second view that has to agree with it.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import pytest

from src.handlers.unit_operations import (
    CREATE_SHOW_AND_SELL_FIELD,
    handle_unit_operation,
)
from src.utils import show_and_sell_models as ssm
from src.utils import unit_payment_models as upm
from src.utils.mutations import marker_keys
from tests.unit.show_sell_fixtures import account_id, unit_operation_event
from tests.unit.show_sell_stage4_fixtures import (
    ADMIN,
    BUTTER,
    CANARY_CAMPAIGN,
    CHOCOLATE,
    DATA_ID,
    DEFAULT_LANE,
    SALE_LINE_WE_OWE_TEST_ID,
    SALES_CAMPAIGN,
    SALES_PACK,
    SalesLane,
    clean_sales_lane,
    discover_event_ids,
    product_rows,
    sales_evidence,
    setup_ss_sm_07,
)


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
    s3_bucket: Any,
) -> Dict[str, Any]:
    """The seeded tables plus the bucket the QR lifecycle writes into."""
    return {
        "units": units_table,
        "unit_campaigns": unit_campaigns_table,
        "catalogs": catalogs_table,
        "inventory": inventory_table,
        "show_and_sells": show_and_sells_table,
        "s3": s3_bucket,
    }


def _setup(world: Dict[str, Any], lane: SalesLane = DEFAULT_LANE) -> Dict[str, Any]:
    return setup_ss_sm_07(
        world["units"],
        world["unit_campaigns"],
        world["catalogs"],
        world["inventory"],
        world["show_and_sells"],
        lane=lane,
        s3_client=world["s3"],
    )


def _marker_row(pk: str) -> Dict[str, Any]:
    """A marker-shaped row for the canary: it exists only to be survived."""
    return {
        "pk": pk,
        "sk": "IDEM#canary",
        "fingerprint": "canary",
        "status": "COMPLETED",
        "operation": "canary",
        "resultId": CANARY_CAMPAIGN,
    }


def _seed_canary_marker(show_and_sells_table: Any) -> str:
    """An ``IDEM#`` marker scoped to the canary campaign, in the escaped key shape."""
    keys = marker_keys(
        table_key=CANARY_CAMPAIGN,
        table_name=show_and_sells_table.table_name,
        actor_id=account_id(ADMIN),
        operation="createShowAndSell",
        scope=CANARY_CAMPAIGN,
        idempotency_key=f"{DATA_ID}-canary-marker",
    )
    row = _marker_row(keys.pk)
    show_and_sells_table.put_item(Item=row)
    return keys.pk


def _lane_markers(table: Any, needle: str) -> List[str]:
    """Every ``IDEM#`` marker partition naming one lane scope, escaped as the writer does."""
    rows = table.scan(
        FilterExpression="begins_with(pk, :prefix) AND contains(pk, :needle)",
        ExpressionAttributeValues={":prefix": "IDEM#", ":needle": needle.replace("#", "%23")},
    )["Items"]
    return sorted(str(row["pk"]) for row in rows)


def test_ss_sm_07_setup_reproduces_the_plan_numbers(world: Dict[str, Any]) -> None:
    """The whole scenario's arithmetic, read back from the rows the resolvers wrote."""
    result = _setup(world)
    evidence = sales_evidence(world["inventory"], world["show_and_sells"], result["eventId"], lane=DEFAULT_LANE)

    event = evidence["event"]
    assert event["status"] == "ENDED"
    assert event["locationName"] == "Church on Elm sales3149"
    assert event["splitMethod"] == "EQUAL"
    assert event["weOweEnabled"] is True

    assert len(evidence["sales"]) == 3
    totals = sorted(int(sale["totalCents"]) for sale in evidence["sales"])
    assert totals == [2000, 2500, 7500]
    assert evidence["poolCents"] == 12000

    buyers = {sale.get("buyerName") for sale in evidence["sales"]}
    assert buyers == {"Nora Cash", "Quinn WeOwe", "Sam Split"}
    nora = next(sale for sale in evidence["sales"] if sale.get("buyerName") == "Nora Cash")
    assert nora["paymentMethodSnapshot"]["methodCode"] == "CASH"
    assert nora["expectedCashCents"] == 2500
    quinn = next(sale for sale in evidence["sales"] if sale.get("buyerName") == "Quinn WeOwe")
    assert quinn["paymentMethodSnapshot"]["methodCode"] == "OTHER"
    assert quinn["paymentMethodSnapshot"]["otherDetails"] == "Apple Pay; Kernel reimbursed unit by Venmo"
    assert quinn.get("buyerPhone") is None and quinn.get("buyerEmail") is None
    sam = next(sale for sale in evidence["sales"] if sale.get("buyerName") == "Sam Split")
    assert sam["paymentMethodSnapshot"]["methodCode"] == "OTHER"
    assert sam["paymentMethodSnapshot"]["otherDetails"] == "$10 cash + $10 Venmo"
    assert "tenders" not in sam["paymentMethodSnapshot"]

    assert evidence["expectedCashCents"] == 2500
    assert evidence["cashAdjustmentCents"] == 1000
    assert evidence["cashAdjustmentReason"] == "Cash portion of Sam Split Other payment"
    assert evidence["adjustedExpectedCashCents"] == 3500
    assert evidence["actualCashCents"] == 3400
    assert evidence["discrepancyCents"] == -100
    assert evidence["cashExplanation"] == "$1 short at closeout"
    assert evidence["perScoutPendingCents"] == 6000

    chocolate = evidence["stock"]["chocolate"]
    assert chocolate["kernelPhysicalQty"] == 0
    assert chocolate["soldInPossessionQty"] == 0
    assert chocolate["assignedOpenQty"] == 0
    assert chocolate["unassignedKernelQty"] == 0
    butter = evidence["stock"]["butter"]
    assert butter["kernelPhysicalQty"] == 0
    assert butter["assignedOpenQty"] == 0
    assert evidence["allocationRemainingQty"] == 0

    assert len(evidence["obligations"]) == 1
    obligation = evidence["obligations"][0]
    assert obligation["buyerName"] == "Quinn WeOwe"
    assert obligation["originalQty"] == 2
    assert obligation["fulfilledQty"] == 2
    assert obligation["remainingQty"] == 0
    assert obligation["reservedQty"] == 0
    assert obligation["status"] == "CLOSED"

    fulfillments = evidence["fulfillments"]
    assert [row["source"] for row in fulfillments] == ["KERNEL_STOCK", "EXTERNAL_COUNCIL"]
    assert all(row["quantity"] == 1 for row in fulfillments)

    work = evidence["work"]
    assert len(work) == 2
    assert sorted(row["actualMinutes"] for row in work) == [60, 60]
    assert all(row["confirmedByAccountId"] == account_id(ADMIN) for row in work)
    assert evidence["movementViolations"] == []
    assert evidence["saleLineWeOweTestId"] == SALE_LINE_WE_OWE_TEST_ID == "sale-line-weowe-0"


def test_blocked_steps_leave_no_partial_effects(world: Dict[str, Any]) -> None:
    """The denied sale and the off-We Owe short sale write no sale, obligation or stock."""
    result = _setup(world)
    event_id = str(result["eventId"])
    evidence = sales_evidence(world["inventory"], world["show_and_sells"], event_id, lane=DEFAULT_LANE)
    assert result["blocked"]["morganDenied"]["errorCode"] == "NOT_FOUND"
    assert result["blocked"]["stockRefused"]["errorCode"] == "CONFLICT"
    assert "3 asked for, but this event holds 2 to sell" in result["blocked"]["stockRefused"]["message"]
    assert len(evidence["sales"]) == 3
    assert len(evidence["obligations"]) == 1
    assert evidence["poolCents"] == 12000


def test_canary_survives_and_second_pass_is_idempotent(world: Dict[str, Any]) -> None:
    """Cleanup removes one lane and nothing else; a second pass finds nothing to remove."""
    result = _setup(world)
    event_id = str(result["eventId"])

    canary_event = _ok_event(CANARY_CAMPAIGN)
    canary_marker_pk = _seed_canary_marker(world["show_and_sells"])
    canary_keys = {
        "event": (world["show_and_sells"], {"pk": ssm.show_and_sell_pk(canary_event), "sk": "METADATA"}),
        "campaign": (
            world["unit_campaigns"],
            {"pk": f"UNIT_CAMPAIGN#{CANARY_CAMPAIGN}", "sk": "METADATA"},
        ),
    }

    first = clean_sales_lane(
        world["inventory"], world["show_and_sells"], world["units"], DEFAULT_LANE, s3_client=world["s3"]
    )
    assert first["events"] == 1
    assert first["eventRows"] > 0
    assert first["markers"] > 0
    assert first["paymentMethods"] >= 2  # the named row plus its capacity counter
    assert first["qrObjects"] == 1  # confirm publishes the attachment and retires the upload
    assert first["inventory"] > 0

    second = clean_sales_lane(
        world["inventory"], world["show_and_sells"], world["units"], DEFAULT_LANE, s3_client=world["s3"]
    )
    assert second == {"events": 0, "eventRows": 0, "markers": 0, "paymentMethods": 0, "qrObjects": 0, "inventory": 0}

    for name, (table, key) in canary_keys.items():
        assert table.get_item(Key=key).get("Item") is not None, f"{name} did not survive the sweep"
    marker = world["show_and_sells"].get_item(
        Key={"pk": canary_marker_pk, "sk": "IDEM#canary"}
    ).get("Item")
    assert marker is not None, "the canary's idempotency marker did not survive the sweep"

    # The sweep took every marker this lane's writes left in all three tables:
    # the event- and campaign-scoped ones on the event table, the receipt and
    # assignment ones on the inventory table, and the payment/QR ones on the
    # units table, which are scoped to the unitId itself.
    assert _lane_markers(world["show_and_sells"], SALES_CAMPAIGN) == []
    assert _lane_markers(world["show_and_sells"], event_id) == []
    assert _lane_markers(world["inventory"], SALES_CAMPAIGN) == []
    assert _lane_markers(world["units"], SALES_PACK) == []
    assert canary_marker_pk in _lane_markers(world["show_and_sells"], CANARY_CAMPAIGN)

    remaining = world["show_and_sells"].scan(
        FilterExpression="pk = :pk",
        ExpressionAttributeValues={":pk": ssm.show_and_sell_pk(event_id)},
    )["Items"]
    assert remaining == []
    assert product_rows(world["inventory"], SALES_CAMPAIGN, CHOCOLATE) == []
    assert product_rows(world["inventory"], SALES_CAMPAIGN, BUTTER) == []
    leftovers = [
        row
        for row in world["s3"].list_objects_v2(
            Bucket=os.environ["EXPORTS_BUCKET"], Prefix="payment-qr-codes/units/"
        ).get("Contents", [])
        if SALES_PACK in row["Key"]
    ]
    assert leftovers == []


def test_second_attempt_coexists_with_the_reference_lane(world: Dict[str, Any]) -> None:
    """A second attempt's ids, keys and rows are disjoint from the reference lane's."""
    _setup(world)
    second = SalesLane.new("SS-SM-07", run_id="1763600000-aaaaaa", attempt_id="bbbbbb")
    assert second.data_id != DATA_ID
    result = _setup(world, second)

    default_events = discover_event_ids(world["show_and_sells"], SALES_CAMPAIGN)
    second_events = discover_event_ids(world["show_and_sells"], second.sales_campaign)
    assert default_events and second_events
    assert not set(default_events) & set(second_events)
    assert result["eventId"] in second_events

    default_evidence = sales_evidence(
        world["inventory"], world["show_and_sells"], default_events[0], lane=DEFAULT_LANE
    )
    second_evidence = sales_evidence(
        world["inventory"], world["show_and_sells"], str(result["eventId"]), lane=second
    )
    for evidence in (default_evidence, second_evidence):
        assert evidence["poolCents"] == 12000
        assert len(evidence["obligations"]) == 1
        assert evidence["movementViolations"] == []

    removed = clean_sales_lane(
        world["inventory"], world["show_and_sells"], world["units"], second, s3_client=world["s3"]
    )
    assert removed["events"] == 1
    assert discover_event_ids(world["show_and_sells"], second.sales_campaign) == []
    assert discover_event_ids(world["show_and_sells"], SALES_CAMPAIGN) == default_events
    # Both lanes' payment markers are scoped to their own unitId, so sweeping the
    # second lane's markers cannot touch the reference lane's replay guards.
    assert _lane_markers(world["units"], second.pack) == []
    assert _lane_markers(world["units"], SALES_PACK)
    survivor = sales_evidence(
        world["inventory"], world["show_and_sells"], default_events[0], lane=DEFAULT_LANE
    )
    assert survivor["poolCents"] == 12000
    assert survivor["obligations"][0]["status"] == "CLOSED"


def test_payment_method_and_qr_are_the_units_own_rows(world: Dict[str, Any]) -> None:
    """``Venmo <DATA_ID>`` is a real named method with the upload and attachment it minted."""
    result = _setup(world)
    payment = result["payment"]
    assert payment["uploadKey"] != payment["attachmentKey"]
    prefix = upm.unit_qr_prefix(SALES_PACK, payment["paymentMethodId"])
    assert payment["uploadKey"].startswith(f"{prefix}/uploads/")
    assert payment["attachmentKey"].startswith(f"{prefix}/attachments/")

    rows = [
        row
        for row in world["units"].query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": f"UNIT#{SALES_PACK}", ":prefix": upm.PAYMENT_SK_PREFIX},
        ).get("Items", [])
    ]
    assert any(row.get("displayName") == f"Venmo {DATA_ID}" for row in rows)
    capacity = world["units"].get_item(Key=upm.payment_capacity_key(SALES_PACK)).get("Item")
    assert capacity is not None and int(capacity["activeCount"]) == 1

    objects = world["s3"].list_objects_v2(Bucket=os.environ["EXPORTS_BUCKET"], Prefix=prefix).get("Contents", [])
    # Confirm publishes the attachment under a new name and retires the upload
    # target, so only the published half survives (§4.1.2).
    assert {row["Key"] for row in objects} == {payment["attachmentKey"]}
    assert payment["uploadKey"] not in {row["Key"] for row in objects}


def test_setup_does_not_finalize_the_event(world: Dict[str, Any]) -> None:
    """The lane stops before finalization: credit is pending, and the pool is read live."""
    result = _setup(world)
    event_id = str(result["eventId"])
    event = ssm.event_admin_payload(ssm.load_show_and_sell_or_not_found(event_id))
    assert event["status"] == "ENDED"
    assert event["latestFinalizationId"] is None


def _ok_event(campaign_id: str) -> str:
    """Create one more event on a campaign, through the resolver, for the canary."""
    payload = {
        "unitCampaignId": campaign_id,
        "locationName": f"Canary Booth {DATA_ID}",
        "startAt": DEFAULT_LANE.moment(-120),
        "endAt": DEFAULT_LANE.moment(120),
        "idempotency": {"idempotencyKey": f"{DATA_ID}-canary-event"},
    }
    answer = handle_unit_operation(unit_operation_event(CREATE_SHOW_AND_SELL_FIELD, ADMIN, input=payload), None)
    assert isinstance(answer, dict) and not answer.get("__isError"), answer
    return str(answer["showAndSellId"])
