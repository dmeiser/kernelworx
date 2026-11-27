"""Wave 6.1 — the finalization preview the Admin approves or amends (§5.1.2).

Resolver-level cases for ``showAndSellFinalizationPreview``: the three checklist pools
(sixty dollars split ``TIME_WORKED`` forty/twenty, four hundred dollars as one whole-event
``EQUAL`` pool, one hundred twenty dollars counted with open We Owe exactly once), the
empty-pool answer, and the load-bearing no-side-effect rule — repeated previews create no
finalization, allocation, credit, or inventory record and do not move the event version
(EVT-Q-06-02, SPLIT-06). Everything runs through ``handle_unit_operation`` against moto,
and the sales being computed over are written by ``createShowAndSellSale`` rather than
seeded: the payment snapshot ``expectedCashCents`` reads by code, the obligation an open
We Owe leaves behind, and the ``soldQty`` an allocation carries are all things the write
puts there.

``AUTH-U`` is asserted here and in ``test_unit_tenant_wiring``; the stale-rounding-draft
issues and the FINALIZED/CANCELLED refusals ride the same surface because a preview that
silently trimmed a broken draft would promise an approval §5.2 then refuses. The live-``dev``
companion of this file's ENDED-event scenarios is runnable against the deployed app; the
states only §5.2/§5.3 write (a populated APPROVED/SUSPENDED/SUPERSEDED discovery, §5.1.4)
are proven at the model and resolver layer here and pick up live evidence when those
writers ship.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.handlers.unit_operations import (
    SHOW_AND_SELL_FINALIZATION_PREVIEW_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from src.utils import show_and_sell_finalization_models as fm
from src.utils import show_and_sell_models as ssm
from src.utils import show_and_sell_sale_models as sm
from tests.unit.show_sell_fixtures import (
    assert_is_error,
    seed_show_sell_fixtures,
    unit_operation_event,
)
from tests.unit.test_show_and_sell_sales import (  # the Wave 5.2 scenario: one table, one catalog
    CAMPAIGN,
    ENDED_END,
    ENDED_SALE_AT,
    ENDED_START,
    OTHER_PRODUCT,
    PRODUCT,
    SALE_AT,
    WISE_METHOD_ID,
    _create,
    _line,
    _method,
    _offer_products,
    _seed_allocation,
    _seed_balance,
    _seed_event,
    _seed_signup,
    _stored_event,
)

# --- The scenario: events at the states finalization work runs against -----------

ENDED_EVENT = "SSE#finalizing"
ACTIVE_LIVE_EVENT = "SSE#still-running"
A_SCOUT = "PROFILE#work6-scout-a"
B_SCOUT = "PROFILE#work6-scout-b"
C_SCOUT = "PROFILE#work6-scout-c"
SCOUT_CAMPAIGN = "SC#sale-budget"


def _call(
    field: str,
    caller: Any,
    *,
    arguments: Any = None,
    mutation: Any = None,
) -> Any:
    event = unit_operation_event(field, caller, arguments=arguments)
    if mutation is not None:
        event["arguments"] = {"input": mutation}
    return handle_unit_operation(event, None)


def _ok(payload: Any) -> Dict[str, Any]:
    failed = isinstance(payload, dict) and payload.get("__isError")
    assert not failed, f"expected a success payload, got {payload!r}"
    return payload


def _preview(caller: Any = "Avery", *, event_id: str = ENDED_EVENT) -> Any:
    return _call(SHOW_AND_SELL_FINALIZATION_PREVIEW_FIELD, caller, arguments={"showAndSellId": event_id})


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
    """The Stage 1 persona world plus the tables finalization touches."""
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
        "unit_campaigns": unit_campaigns_table,
    }


def _ended_event(world: Dict[str, Any], *, split: str = "EQUAL", boxes: int = 40) -> None:
    """An event wholly behind the clock with stock assigned — the state preview starts from."""
    _seed_event(
        world["show_and_sells"],
        ENDED_EVENT,
        start_at=ENDED_START,
        end_at=ENDED_END,
        product_ids=[PRODUCT],
        splitMethod=split,
    )
    _seed_balance(world["inventory"], PRODUCT, physical=boxes)
    _seed_allocation(world["inventory"], ENDED_EVENT, PRODUCT, allocated=boxes)


def _sell(world: Dict[str, Any], *, boxes: int = 1, we_owe: int = 0, key: str, **extras: Any) -> Dict[str, Any]:
    version = int(_stored_event(world["show_and_sells"], ENDED_EVENT)[ssm.VERSION_ATTRIBUTE])
    return _ok(
        _create(
            event_id=ENDED_EVENT,
            version=version,
            sale_at=ENDED_SALE_AT,
            lines=[_line(PRODUCT, immediate=boxes, we_owe=we_owe)],
            key=key,
            **extras,
        )
    )


def _confirm(world: Dict[str, Any], profile: str, minutes: int) -> None:
    _seed_signup(
        world["show_and_sells"],
        ENDED_EVENT,
        minutes=minutes,
        profile_id=profile,
    )


def _put_draft(world: Dict[str, Any], draft: Dict[str, int]) -> None:
    """Seed a rounding draft the way §5.1.3's mutation writes it onto the event row."""
    world["show_and_sells"].update_item(
        Key=ssm.event_metadata_key(ENDED_EVENT),
        UpdateExpression="SET #draft = :draft",
        ExpressionAttributeNames={"#draft": ssm.ROUNDING_DRAFT_ATTRIBUTE},
        ExpressionAttributeValues={":draft": draft},
    )


def _issue_codes(payload: Dict[str, Any]) -> List[str]:
    return [str(issue["code"]) for issue in payload["issues"]]


# --- The checklist pools (§5.1.2) ------------------------------------------------


def test_a_sixty_dollar_event_previews_time_worked_shares_of_forty_and_twenty(world: Dict[str, Any]) -> None:
    """§5.1.2: a $60 ``TIME_WORKED`` pool previews $40/$20 for 240 and 120 confirmed minutes."""
    _ended_event(world, split="TIME_WORKED", boxes=20)
    _sell(world, boxes=12, key="pool-60")
    _confirm(world, A_SCOUT, 240)
    _confirm(world, B_SCOUT, 120)

    answer = _ok(_preview())
    assert answer["wholePoolCents"] == 6000
    by_profile = {row["profileId"]: row for row in answer["baseAllocations"]}
    assert sorted(by_profile) == sorted([A_SCOUT, B_SCOUT])
    assert by_profile[A_SCOUT]["baseAmountCents"] == 4000
    assert by_profile[B_SCOUT]["baseAmountCents"] == 2000
    assert answer["unassignedCents"] == 0
    assert by_profile[A_SCOUT]["amountCents"] == 4000
    assert by_profile[A_SCOUT]["campaignId"] == SCOUT_CAMPAIGN
    assert answer["cashPreview"]["calculatedExpectedCents"] == 6000
    assert _issue_codes(answer) == []
    assert answer["eventVersion"] == int(_stored_event(world["show_and_sells"], ENDED_EVENT)[ssm.VERSION_ATTRIBUTE])


def test_a_four_hundred_dollar_event_previews_one_whole_event_equal_pool(world: Dict[str, Any]) -> None:
    """§5.1.2 / SPLIT-02: a $300 and a $100 sale preview one $400 pool, not two per-slot pools."""
    _ended_event(world, boxes=80)
    _sell(world, boxes=60, key="morning")
    _sell(world, boxes=20, key="afternoon")
    _confirm(world, A_SCOUT, 30)
    _confirm(world, B_SCOUT, 999)

    answer = _ok(_preview())
    assert answer["wholePoolCents"] == 40000
    by_profile = {row["profileId"]: row for row in answer["baseAllocations"]}
    assert by_profile[A_SCOUT]["baseAmountCents"] == 20000
    assert by_profile[B_SCOUT]["baseAmountCents"] == 20000
    assert answer["unassignedCents"] == 0


def test_a_one_hundred_twenty_dollar_event_counts_an_open_we_owe_once(world: Dict[str, Any]) -> None:
    """§5.1.2 / SPLIT-05: We Owe sales sit inside the pool exactly once; cash stays snapshot-only.

    ``CASH-01`` shows here: the $95 CUSTOM-method sale and the $20 OTHER sale add their totals
    to the pool but nothing to expected cash — only the $25 snapshotted ``CASH`` sale does,
    and no display name or note is parsed for cash content.
    """
    _ended_event(world, boxes=40)
    _method(world["units"])
    _sell(world, boxes=5, key="cash-25")
    _sell(
        world, boxes=9, we_owe=6, key="we-owe-75", paymentMethodCode=f"CUSTOM:{WISE_METHOD_ID}", buyerName="Buyer Bee"
    )
    _sell(world, boxes=4, key="other-20", paymentMethodCode="OTHER", otherDetails="check in the mail")

    answer = _ok(_preview())
    assert answer["wholePoolCents"] == 12000
    assert answer["cashPreview"]["calculatedExpectedCents"] == 2500
    # The obligations exist and are OPEN; they add no cents a second time.
    obligations = [
        obligation
        for sale in sm.event_sale_rows(ENDED_EVENT)
        for obligation in sm.sale_obligations(ENDED_EVENT, str(sale[sm.SALE_ID_ATTRIBUTE]))
    ]
    assert obligations and all(str(row[ssm.STATUS_ATTRIBUTE]) == sm.WE_OWE_STATUS_OPEN for row in obligations)


def test_an_event_with_no_sales_previews_an_empty_pool(world: Dict[str, Any]) -> None:
    """§5.1.2: the empty pool answers zeros and an open question, not an error."""
    _ended_event(world, boxes=4)

    answer = _ok(_preview())
    assert answer["wholePoolCents"] == 0
    assert answer["baseAllocations"] == []
    assert answer["unassignedCents"] == 0
    assert answer["cashPreview"]["calculatedExpectedCents"] == 0
    assert answer["returnLines"] == [{"productId": PRODUCT, "allocatedQty": 4, "soldQty": 0, "expectedQty": 4}]
    assert _issue_codes(answer) == []


def test_repeated_previews_persist_no_finalization_credit_or_movement(world: Dict[str, Any]) -> None:
    """EVT-Q-06-02 / SPLIT-06: two previews, zero rows written, version unmoved, same answer."""
    _ended_event(world, split="TIME_WORKED", boxes=20)
    _sell(world, boxes=12, key="pool-60-again")
    _confirm(world, A_SCOUT, 240)
    _confirm(world, B_SCOUT, 120)
    before = {
        "show_and_sells": len(world["show_and_sells"].scan()["Items"]),
        "inventory": len(world["inventory"].scan()["Items"]),
        "unit_campaigns": len(world["unit_campaigns"].scan()["Items"]),
    }
    version_before = int(_stored_event(world["show_and_sells"], ENDED_EVENT)[ssm.VERSION_ATTRIBUTE])

    first = _ok(_preview())
    second = _ok(_preview())

    assert first == second
    assert {
        "show_and_sells": len(world["show_and_sells"].scan()["Items"]),
        "inventory": len(world["inventory"].scan()["Items"]),
        "unit_campaigns": len(world["unit_campaigns"].scan()["Items"]),
    } == before
    assert int(_stored_event(world["show_and_sells"], ENDED_EVENT)[ssm.VERSION_ATTRIBUTE]) == version_before
    assert not [
        row
        for row in world["unit_campaigns"].scan()["Items"]
        if str(row.get("entityType", "")) == fm.TOTAL_ENTITY_TYPE or str(row.get("sk", "")) == fm.SHOW_AND_SELL_TOTAL_SK
    ]
    assert not [
        row
        for row in world["show_and_sells"].scan()["Items"]
        if str(row.get("entityType", "")) in (fm.CREDIT_ENTITY_TYPE, fm.FINALIZATION_ENTITY_TYPE)
        or str(row.get("sk", "")).startswith(f"{fm.CREDIT_SK_PREFIX}#")
        or str(row.get("sk", "")).startswith("FINALIZATION#")
    ]


# --- Rounding: residue, draft, and drafts that went stale (§5.1.2, §7.2) ---------


def test_the_round_down_residue_is_reported_and_a_draft_lands_on_its_participant(world: Dict[str, Any]) -> None:
    """SPLIT-10 / §7.2: $100 three ways previews 3×$33.33 and one unassigned cent; the draft names its Scout."""
    _ended_event(world, boxes=20)
    _sell(world, boxes=20, key="pool-100")
    for scout in (A_SCOUT, B_SCOUT, C_SCOUT):
        _confirm(world, scout, 10)

    unassigned = _ok(_preview())
    assert unassigned["wholePoolCents"] == 10000
    assert {row["baseAmountCents"] for row in unassigned["baseAllocations"]} == {3333}
    assert unassigned["unassignedCents"] == 1
    assert _issue_codes(unassigned) == ["ROUNDING_CENTS_UNASSIGNED"]

    _put_draft(world, {A_SCOUT: 1})
    drafted = _ok(_preview())
    by_profile = {row["profileId"]: row for row in drafted["baseAllocations"]}
    assert by_profile[A_SCOUT]["roundingCreditCents"] == 1
    assert by_profile[A_SCOUT]["amountCents"] == 3334
    assert by_profile[B_SCOUT]["amountCents"] == 3333
    assert drafted["unassignedCents"] == 1  # the split's residue, not what is left after the draft
    assert _issue_codes(drafted) == []


def test_a_rounding_draft_that_went_stale_is_reported_rather_than_trimmed(world: Dict[str, Any]) -> None:
    """A stored draft overtaken by the clock: an ineligible name and an over-sum are named, not hidden."""
    _ended_event(world, boxes=20)
    _sell(world, boxes=20, key="pool-100-stale")
    _confirm(world, A_SCOUT, 10)
    _confirm(world, B_SCOUT, 10)
    _put_draft(world, {C_SCOUT: 2, A_SCOUT: 1})

    answer = _ok(_preview())
    assert _issue_codes(answer) == ["ROUNDING_OVERSUM", "ROUNDING_PARTICIPANT_INELIGIBLE"]
    ineligible = next(issue for issue in answer["issues"] if issue["code"] == "ROUNDING_PARTICIPANT_INELIGIBLE")
    assert ineligible["profileId"] == C_SCOUT
    by_profile = {row["profileId"]: row for row in answer["baseAllocations"]}
    assert by_profile[A_SCOUT]["roundingCreditCents"] == 1  # shown as stored; nothing silently trimmed


# --- Eligibility and blockers -----------------------------------------------------


def test_cancelled_and_unconfirmed_signups_are_not_eligible_work(world: Dict[str, Any]) -> None:
    """SPLIT-03: minutes only count when confirmed; a pool with nobody confirmed names the blocker."""
    _ended_event(world, boxes=4)
    _sell(world, boxes=1, key="solo-sale")
    _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=0, profile_id=A_SCOUT)
    cancelled = _seed_signup(world["show_and_sells"], ENDED_EVENT, minutes=120, profile_id=B_SCOUT)
    world["show_and_sells"].update_item(
        Key={"pk": str(cancelled["pk"]), "sk": str(cancelled["sk"])},
        UpdateExpression="SET #status = :status, #minutes = :minutes",
        ExpressionAttributeNames={"#status": ssm.STATUS_ATTRIBUTE, "#minutes": ssm.ACTUAL_MINUTES_ATTRIBUTE},
        ExpressionAttributeValues={":status": ssm.SIGNUP_CANCELLED, ":minutes": 0},
    )

    answer = _ok(_preview())
    assert answer["baseAllocations"] == []
    assert _issue_codes(answer) == ["NO_CONFIRMED_WORK"]


def test_an_event_still_running_previews_with_a_named_blocker(world: Dict[str, Any]) -> None:
    """FIN-01 across the read surface: an ACTIVE event previews, flagged, and nothing is assumed approved."""
    _seed_event(world["show_and_sells"], ACTIVE_LIVE_EVENT, product_ids=[PRODUCT])
    _seed_balance(world["inventory"], PRODUCT, physical=4)
    _seed_allocation(world["inventory"], ACTIVE_LIVE_EVENT, PRODUCT, allocated=4)
    version = int(_stored_event(world["show_and_sells"], ACTIVE_LIVE_EVENT)[ssm.VERSION_ATTRIBUTE])
    _ok(
        _create(
            event_id=ACTIVE_LIVE_EVENT,
            version=version,
            sale_at=SALE_AT,
            lines=[_line(PRODUCT, immediate=1)],
            key="live-sale",
        )
    )

    answer = _ok(_preview(event_id=ACTIVE_LIVE_EVENT))
    assert answer["wholePoolCents"] == 500
    assert _issue_codes(answer) == ["EVENT_NOT_ENDED", "NO_CONFIRMED_WORK"]


def test_a_finalized_or_cancelled_event_refuses_the_preview(world: Dict[str, Any]) -> None:
    """SPLIT-06: an approved answer is read from the finalization, not recomputed beside it; a cancelled event has no pool."""
    _seed_event(
        world["show_and_sells"],
        "SSE#done",
        start_at=ENDED_START,
        end_at=ENDED_END,
        status=ssm.STATUS_FINALIZED,
    )
    error = assert_is_error(_preview(event_id="SSE#done"), "CONFLICT")
    assert "approved and final" in error["message"]

    _seed_event(
        world["show_and_sells"],
        "SSE#gone",
        start_at=ENDED_START,
        end_at=ENDED_END,
        status=ssm.STATUS_CANCELLED,
    )
    error = assert_is_error(_preview(event_id="SSE#gone"), "CONFLICT")
    assert "cancelled event is never finalized" in error["message"]


def test_only_the_events_unit_admin_previews(world: Dict[str, Any]) -> None:
    """AUTH-U: a removed admin, another Unit's admin, and an unauthenticated caller all get no existence."""
    _ended_event(world, boxes=4)
    for caller in ("Blake", "Riley"):
        error = assert_is_error(_preview(caller), "NOT_FOUND")
        assert "not found" in error["message"]
    assert_is_error(_preview(None), "UNAUTHORIZED")


def test_expected_returns_come_from_the_events_open_allocations(world: Dict[str, Any]) -> None:
    """FIN-02 preview half: allocated four, sold three, one expected back — inventory not touched by the read.

    The RELEASED second allocation is in the event's ``productIds`` but not an OPEN row,
    so it stays out of the expected returns: preview lines mirror the allocations an
    approval would finalize, not the event's whole assignment history.
    """
    _ended_event(world, boxes=4)
    _seed_allocation(
        world["inventory"],
        ENDED_EVENT,
        OTHER_PRODUCT,
        allocated=2,
        sold=0,
        released=2,
        status=inv.ALLOCATION_RELEASED,
    )
    world["show_and_sells"].update_item(
        Key=ssm.event_metadata_key(ENDED_EVENT),
        UpdateExpression="SET #products = :products",
        ExpressionAttributeNames={"#products": ssm.PRODUCT_IDS_ATTRIBUTE},
        ExpressionAttributeValues={":products": [PRODUCT, OTHER_PRODUCT]},
    )
    _sell(world, boxes=3, key="three-sold")

    answer = _ok(_preview())
    assert answer["returnLines"] == [{"productId": PRODUCT, "allocatedQty": 4, "soldQty": 3, "expectedQty": 1}]
    allocation = world["inventory"].get_item(Key=ssm.event_allocation_key(CAMPAIGN, PRODUCT, ENDED_EVENT)).get("Item")
    assert int(allocation[inv.SOLD_QTY]) == 3

    # The preview's numbers are the model's own equations, not a second dialect:
    assert fm.expected_return_qty(4, 3) == 1
