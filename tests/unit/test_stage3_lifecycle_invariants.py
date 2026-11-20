"""Leaf 3.7.4 — the Stage 3 lifecycle invariants a re-created event must not break.

§3.7.4 asks for facts proved over the whole event surface, not inside one mutation:
cancellation is possible only before the start; no update reschedules; a re-created event
carries NOTHING over from the cancelled one; and the cancellation reason and audit stay on
the cancelled row where a later read can still find them. The §3.1 leaf tests proved each
guard where its own mutation lives — EVT-M-02-01 refused a smuggled time, EVT-M-03-02
refused at/after-start cancellation, EVT-M-03-04 froze the audit against a second cancel.
What no leaf proved is the sequence a Kernel actually walks after a cancellation: cancel →
create the replacement → read the replacement. That hand-off is proven here at the resolver,
because the frontend recreate flow only proves the FORM carries nothing over — the server
could still have copied stock or signups underneath it and the screens would never show it.

The walk therefore builds a real event through the real mutations — create, assign, slot,
signup — cancels it while the clock is still before its start, and creates the replacement
through ``createShowAndSell``. Then it reads the replacement through the same reads an admin
screen uses, and the answer is an empty event: no allocations, no slots, no signups, no
cumulative ``productIds``. The cancelled event's rows stay exactly where the cancellation
left them — allocations ``CANCELLED``, signup ``CANCELLED`` — and none of them was copied,
re-opened, or re-pointed at the replacement's id.

Immutability of the cancelled history is asserted row-for-row, not by counting: every row
present when the cancellation committed is still present, byte-identical, after the
replacement write. A copy-over that re-opened a cancelled allocation or re-pointed a
commitment would change a row's bytes without changing any count, and a multiset comparison
sees exactly that.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pytest

from src.handlers.unit_operations import (
    ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD,
    CANCEL_SHOW_AND_SELL_FIELD,
    CREATE_SHOW_AND_SELL_FIELD,
    EVENT_INVENTORY_ALLOCATIONS_FIELD,
    SHOW_AND_SELL_FIELD,
    SHOW_AND_SELL_SIGNUPS_FIELD,
    SIGNUP_SCOUT_FIELD,
    UPDATE_SHOW_AND_SELL_FIELD,
    UPSERT_SLOT_FIELD,
    handle_unit_operation,
)
from src.utils import inventory_models as inv
from src.utils import show_and_sell_models as ssm
from tests.unit.show_sell_fixtures import (
    PACK_3149,
    PACK_3149_FALL,
    PROFILES,
    account_id,
    assert_is_error,
    seed_show_sell_fixtures,
    unit_operation_event,
)

CAMPAIGN = PACK_3149_FALL
CATALOG_ID = "CATALOG#fixture-default"
PRODUCT = f"{CATALOG_ID}#prod-1"
CANCELLED_EVENT = "SSE#cancelled-board"
LOCATION = "Library on Main"
REASON = "Road closure at the venue"


def _shift(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


#: Comfortably ahead of the clock, so the event is SCHEDULED and the cancellation window
#: (EVT-M-03-02 refuses at or after ``startAt``) is open for the whole walk.
CANCEL_START, CANCEL_END = _shift(2), _shift(6)


def _at(start: str, hours: float) -> str:
    return (datetime.fromisoformat(start) + timedelta(hours=hours)).isoformat()


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
    assert not (isinstance(payload, dict) and payload.get("__isError")), f"expected success, got {payload!r}"
    return payload


def _idem(key: str) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": key}}


def _version(expected: int) -> Dict[str, Any]:
    return {"version": {"expectedVersion": expected}}


# --- Seeded rows and table observation -------------------------------------------


def _seed_event(
    show_and_sells_table: Any,
    event_id: str,
    *,
    start_at: str = CANCEL_START,
    end_at: str = CANCEL_END,
    version: int = 1,
) -> str:
    item = ssm.build_show_and_sell_item(
        show_and_sell_id=event_id,
        unit_id=PACK_3149,
        unit_campaign_id=CAMPAIGN,
        location_name=LOCATION,
        start_at=start_at,
        end_at=end_at,
        created_by_account_id="ACCOUNT#avery-fixture",
        now_iso=start_at,
        version=version,
    )
    show_and_sells_table.put_item(Item=item)
    return event_id


def _seed_balance(inventory_table: Any, product_id: str = PRODUCT, *, physical: int = 4) -> None:
    inventory_table.put_item(
        Item=inv.build_inventory_balance_item(
            unit_campaign_id=CAMPAIGN,
            product_id=product_id,
            kernel_physical_qty=physical,
            sold_in_possession_qty=0,
            council_on_order_qty=0,
            now_iso=CANCEL_START,
        )
    )


def _event_version(world: Dict[str, Any], event_id: str) -> int:
    item = world["show_and_sells"].get_item(Key=ssm.event_metadata_key(event_id)).get("Item")
    assert item is not None, f"event {event_id} is missing"
    return int(item[ssm.VERSION_ATTRIBUTE])


def _row_multiset(world: Dict[str, Any]) -> Counter:
    """Every row of both Stage 3 tables as one multiset of serialized rows."""
    rows: Counter = Counter()
    for table in (world["show_and_sells"], world["inventory"]):
        rows.update(
            json.dumps(item, sort_keys=True, default=str) for item in table.scan()["Items"]
        )
    return rows


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
    """The Stage 1 persona world plus the two tables this walk mutates."""
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    _seed_balance(inventory_table)
    return {
        "show_and_sells": show_and_sells_table,
        "inventory": inventory_table,
        "unit_campaigns": unit_campaigns_table,
    }


# --- §3.7.4: cancel → recreate transfers nothing ---------------------------------


def test_recreating_a_cancelled_event_creates_an_empty_event_and_moves_nothing_with_it(
    world: Dict[str, Any],
) -> None:
    """SS-SM-11 / §3.7.4: the replacement is a new event with nothing carried over.

    Every step is a real handler call so the cancelled event holds committed aggregate
    rows — an allocation with its movement, a slot, a signup with its commitment — and
    "transfers nothing" is asserted against those rows, not against fixtures.
    """
    created = _ok(
        _call(
            CREATE_SHOW_AND_SELL_FIELD,
            "Avery",
            mutation={
                "unitCampaignId": CAMPAIGN,
                "locationName": LOCATION,
                "startAt": CANCEL_START,
                "endAt": CANCEL_END,
                **_idem("create-original"),
            },
        )
    )
    event_id = created["showAndSellId"]

    _ok(
        _call(
            ASSIGN_SHOW_AND_SELL_INVENTORY_FIELD,
            "Avery",
            mutation={
                "showAndSellId": event_id,
                "items": [{"productId": PRODUCT, "quantity": 3}],
                **_version(_event_version(world, event_id)),
                **_idem("assign-original"),
            },
        )
    )
    slot = _ok(
        _call(
            UPSERT_SLOT_FIELD,
            "Avery",
            mutation={
                "showAndSellId": event_id,
                "label": "Doors",
                "startAt": _at(CANCEL_START, 0.5),
                "endAt": _at(CANCEL_START, 2),
                "capacity": 1,
                **_version(_event_version(world, event_id)),
                **_idem("slot-original"),
            },
        )
    )
    _ok(
        _call(
            SIGNUP_SCOUT_FIELD,
            "Avery",
            mutation={
                "showAndSellId": event_id,
                "slotId": slot["slotId"],
                "campaignId": str(PROFILES["Devon"]["campaignId"]),
                "profileId": str(PROFILES["Devon"]["profileId"]),
                **_idem("signup-original"),
            },
        )
    )

    _ok(
        _call(
            CANCEL_SHOW_AND_SELL_FIELD,
            "Avery",
            mutation={
                "showAndSellId": event_id,
                **_version(_event_version(world, event_id)),
                "reason": REASON,
                **_idem("cancel-original"),
            },
        )
    )
    cancelled_rows = _row_multiset(world)

    replacement = _ok(
        _call(
            CREATE_SHOW_AND_SELL_FIELD,
            "Avery",
            mutation={
                "unitCampaignId": CAMPAIGN,
                "locationName": LOCATION,
                "startAt": _shift(24),
                "endAt": _shift(28),
                **_idem("create-replacement"),
            },
        )
    )
    new_id = replacement["showAndSellId"]
    assert new_id != event_id, "the replacement mints a new id; the cancelled row is never re-opened"

    # The replacement reads EMPTY through the reads an admin screen uses.
    allocations = _ok(
        _call(
            EVENT_INVENTORY_ALLOCATIONS_FIELD,
            "Avery",
            arguments={"unitCampaignId": CAMPAIGN, "showAndSellId": new_id},
        )
    )
    assert allocations["items"] == [], "no allocation followed the event"
    signups = _ok(_call(SHOW_AND_SELL_SIGNUPS_FIELD, "Avery", arguments={"showAndSellId": new_id}))
    assert signups["items"] == [], "no signup followed the event"
    detail = _ok(_call(SHOW_AND_SELL_FIELD, "Avery", arguments={"showAndSellId": new_id}))
    assert detail["slots"] == [], "no slot followed the event"

    # The cancelled event's aggregate rows are exactly as the cancellation left them.
    stored_old = world["show_and_sells"].get_item(Key=ssm.event_metadata_key(event_id)).get("Item")
    assert stored_old is not None and stored_old[ssm.STATUS_ATTRIBUTE] == ssm.STATUS_CANCELLED
    allocations_old = _ok(
        _call(
            EVENT_INVENTORY_ALLOCATIONS_FIELD,
            "Avery",
            arguments={"unitCampaignId": CAMPAIGN, "showAndSellId": event_id},
        )
    )
    assert [row["status"] for row in allocations_old["items"]] == ["CANCELLED"], (
        "the released allocation is history the replacement does not re-open"
    )
    signups_old = _ok(_call(SHOW_AND_SELL_SIGNUPS_FIELD, "Avery", arguments={"showAndSellId": event_id}))
    assert [row["status"] for row in signups_old["items"]] == ["CANCELLED"]

    # Every row that existed when the cancellation committed is still present, unchanged:
    # the replacement write added its own rows and touched none of the old event's.
    after = _row_multiset(world)
    for row, count in cancelled_rows.items():
        assert after[row] >= count, f"the replacement write rewrote a cancelled event's row: {row}"


def test_cancellation_audit_survives_a_later_cancel_attempt_and_reports_why(
    world: Dict[str, Any],
) -> None:
    """§3.7.4: reason, actor, and instant stay on the cancelled row for a later admin read."""
    _seed_event(world["show_and_sells"], CANCELLED_EVENT)
    _ok(
        _call(
            CANCEL_SHOW_AND_SELL_FIELD,
            "Avery",
            mutation={
                "showAndSellId": CANCELLED_EVENT,
                **_version(1),
                "reason": REASON,
                **_idem("cancel-audit"),
            },
        )
    )

    detail = _ok(_call(SHOW_AND_SELL_FIELD, "Avery", arguments={"showAndSellId": CANCELLED_EVENT}))
    assert detail["status"] == ssm.STATUS_CANCELLED
    assert detail["cancellationReason"] == REASON
    assert detail["cancelledByAccountId"] == account_id("Avery")
    assert detail["cancelledAt"], "the audit instant is persisted, not derived at read time"

    # A later cancel attempt cannot rewrite the audit (EVT-M-03-04 holds at this head too).
    _call(
        CANCEL_SHOW_AND_SELL_FIELD,
        "Avery",
        mutation={
            "showAndSellId": CANCELLED_EVENT,
            **_version(_event_version(world, CANCELLED_EVENT)),
            "reason": "a second reason must never land",
            **_idem("cancel-again"),
        },
    )
    again = _ok(_call(SHOW_AND_SELL_FIELD, "Avery", arguments={"showAndSellId": CANCELLED_EVENT}))
    assert again["cancellationReason"] == REASON


def test_no_update_can_move_the_event_clock(world: Dict[str, Any]) -> None:
    """§3.7.4 "no reschedule": settings change, the stored interval does not.

    A plain settings edit succeeds; the same call smuggling ``startAt``/``endAt`` is refused
    outright, and the stored instants are unchanged after both — the immutable-time rule
    proven against a board that has already accepted one legal update, not only a fresh row.
    """
    _seed_event(world["show_and_sells"], CANCELLED_EVENT, start_at=CANCEL_START, end_at=CANCEL_END)

    moved = _ok(
        _call(
            UPDATE_SHOW_AND_SELL_FIELD,
            "Avery",
            mutation={
                "showAndSellId": CANCELLED_EVENT,
                "locationName": "Second street armory",
                **_version(1),
                **_idem("update-settings"),
            },
        )
    )
    assert moved["locationName"] == "Second street armory"
    assert moved["startAt"] == ssm.normalize_moment(CANCEL_START, "startAt")

    refused = _call(
        UPDATE_SHOW_AND_SELL_FIELD,
        "Avery",
        mutation={
            "showAndSellId": CANCELLED_EVENT,
            "startAt": _shift(100),
            "endAt": _shift(104),
            **_version(_event_version(world, CANCELLED_EVENT)),
            **_idem("update-smuggled"),
        },
    )
    assert_is_error(refused, "INVALID_INPUT")

    stored = world["show_and_sells"].get_item(Key=ssm.event_metadata_key(CANCELLED_EVENT)).get("Item")
    assert stored is not None
    assert stored[ssm.START_AT_ATTRIBUTE] == ssm.normalize_moment(CANCEL_START, "startAt")
    assert stored[ssm.END_AT_ATTRIBUTE] == ssm.normalize_moment(CANCEL_END, "endAt")
