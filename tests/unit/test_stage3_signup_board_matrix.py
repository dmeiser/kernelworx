"""Leaf 3.7.2 / 3.7.6 — the SS-SM-06 board walked end-to-end through the resolvers.

§3.7.2 asks for arbitrary slot durations, capacity, duplicate signup, adjacent slots,
cross-Unit-Campaign conflicts, and work unconfirmation tested together, and §3.7.6 asks for
``SS-SM-06`` to be RUN, not re-asserted one guard at a time. The §3.3/§3.4 leaf suites proved
each rule in isolation (SLOT-M-01/02, SIGN-M-01/02/03); this is the scenario runner: the
smoke plan's own board — a 3.5-hour event with First Sales (90 min, capacity 1), Midday
(120 min, adjacent), and Full Booth (180 min, overlapping both) — walked in the plan's step
order through ``handle_unit_operation``, with the storage read back after every step.

Two things the leaf tests could not see are visible here:

* the cross-Unit-Campaign half of the conflict rule — the scout's other commitment lives in
  ANOTHER Unit Campaign in another Unit, and the overlap guard must refuse on it while the
  refusal names neither the other campaign nor the other event (the privacy rule of
  INV-Q-06-03, asserted here at scenario scale); and
* ``NOTIFY-01`` (SS-SM-06 step 10): a signup generates no automatic notification anywhere.
  That is proven as a closed write-set: the signup commit adds exactly the signup row and
  its idempotency marker to ``show_and_sells`` and the commitment projection and guard to
  ``unit_campaigns``, moves exactly the slot counter and the event version, and leaves every
  other table byte-identical. No notification row, mail record, or inbox entry is reachable,
  because nothing else changed at all.

The work-unconfirmation half rides a second, already-ended board, because confirmations are
legal only on ACTIVE/ENDED/REOPENED events: 75 minutes confirmed, then 0 un-confirms the row
and clears its audit, exactly as the plan's step 9 arithmetic (75 + 115 ≠ slot durations)
demands.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pytest

from src.handlers.unit_operations import (
    CANCEL_SIGNUP_FIELD,
    CONFIRM_WORK_FIELD,
    SIGNUP_SCOUT_FIELD,
    UPSERT_SLOT_FIELD,
    handle_unit_operation,
)
from src.utils import show_and_sell_models as ssm
from tests.unit.show_sell_fixtures import (
    CREW_529_SPRING,
    PACK_3149,
    PACK_3149_FALL,
    PROFILES,
    assert_is_error,
    seed_show_sell_fixtures,
    unit_campaign_membership_item,
    unit_operation_event,
)

CAMPAIGN = PACK_3149_FALL
OTHER_CAMPAIGN = CREW_529_SPRING
BOARD = "SSE#board-06"
PAST_BOARD = "SSE#board-06-past"
LOCATION = "Library on Main"
CONFLICT_EVENT = "SSE#other-campaign-board"


def _shift(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _at(start: str, hours: float) -> str:
    return (datetime.fromisoformat(start) + timedelta(hours=hours)).isoformat()


#: The plan's board, seven days out.
E_START, E_END = _shift(24 * 7), _shift(24 * 7 + 3.5)

#: First Sales 90' at capacity 1; Midday 120' adjacent to it; Full Booth 180' overlapping both.
FIRST_START, FIRST_END = E_START, _at(E_START, 1.5)
MIDDAY_START, MIDDAY_END = FIRST_END, _at(E_START, 3.5)
FULL_START, FULL_END = E_START, _at(E_START, 3)

#: The past board ran and ended: start 24 h ago, end one hour ago. Slot "p-1" is 90' inside it.
PAST_START, PAST_END = _shift(-24), _shift(-1)
P_SLOT_START, P_SLOT_END = _at(PAST_START, 0.5), _at(PAST_START, 2)


def _profile(persona: str) -> str:
    return str(PROFILES[persona]["profileId"])


def _scout_campaign(persona: str) -> str:
    return str(PROFILES[persona]["campaignId"])


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


def _refusal(payload: Any, code: str) -> str:
    return str(assert_is_error(payload, code).get("message") or "")


def _idem(key: str) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": key}}


def _version(expected: int) -> Dict[str, Any]:
    return {"version": {"expectedVersion": expected}}


def _signup(
    caller: Optional[str],
    persona: str,
    slot_id: str,
    key: str,
    *,
    event_id: str = BOARD,
) -> Any:
    return _call(
        SIGNUP_SCOUT_FIELD,
        caller,
        mutation={
            "showAndSellId": event_id,
            "slotId": slot_id,
            "campaignId": _scout_campaign(persona),
            "profileId": _profile(persona),
            **_idem(key),
        },
    )


# --- Seeded rows -----------------------------------------------------------------


def _seed_event(
    show_and_sells_table: Any,
    event_id: str,
    *,
    start_at: str = E_START,
    end_at: str = E_END,
    status: Optional[str] = None,
) -> None:
    item = ssm.build_show_and_sell_item(
        show_and_sell_id=event_id,
        unit_id=PACK_3149,
        unit_campaign_id=CAMPAIGN,
        location_name=LOCATION,
        start_at=start_at,
        end_at=end_at,
        created_by_account_id="ACCOUNT#avery-fixture",
        now_iso=start_at,
    )
    if status is not None:
        item[ssm.STATUS_ATTRIBUTE] = status
    show_and_sells_table.put_item(Item=item)


def _seed_slot(
    show_and_sells_table: Any,
    event_id: str,
    slot_id: str,
    start_at: str,
    end_at: str,
    *,
    capacity: int,
) -> None:
    stored = show_and_sells_table.get_item(Key=ssm.event_metadata_key(event_id)).get("Item")
    show_and_sells_table.put_item(
        Item=ssm.build_show_and_sell_slot_item(
            event=dict(stored) if stored else {},
            slot_id=slot_id,
            start_at=start_at,
            end_at=end_at,
            capacity=capacity,
            active_signup_count=0,
            version=1,
            label=slot_id,
            now_iso=E_START,
        )
    )


def _stored_slot_count(world: Dict[str, Any], slot_id: str, event_id: str = BOARD) -> int:
    item = world["show_and_sells"].get_item(Key=ssm.slot_key(event_id, slot_id)).get("Item")
    return int(item[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE]) if item else -1


def _stored_signup(
    world: Dict[str, Any], persona: str, slot_id: str, event_id: str = BOARD
) -> Optional[Dict[str, Any]]:
    for row in world["show_and_sells"].scan()["Items"]:
        if (
            row.get(ssm.SHOW_AND_SELL_ID_ATTRIBUTE) == event_id
            and row.get("slotId") == slot_id
            and row.get(ssm.PROFILE_ID_ATTRIBUTE) == _profile(persona)
            and row.get("entityType") == "ShowAndSellSignup"
        ):
            return dict(row)
    return None


def _event_version(world: Dict[str, Any], event_id: str = BOARD) -> int:
    item = world["show_and_sells"].get_item(Key=ssm.event_metadata_key(event_id)).get("Item")
    assert item is not None
    return int(item[ssm.VERSION_ATTRIBUTE])


def _table_map(table: Any) -> Dict[tuple, str]:
    """Every row of a table keyed by its key attributes, serialized for comparison."""
    names = [key["AttributeName"] for key in table.key_schema]
    rows = {}
    for item in table.scan()["Items"]:
        rows[tuple(str(item.get(name, "")) for name in names)] = json.dumps(item, sort_keys=True, default=str)
    return rows


ALL_TABLES = ("show_and_sells", "unit_campaigns", "inventory", "profiles", "campaigns", "shares", "units", "catalogs")


def _census(world: Dict[str, Any]) -> Dict[str, Dict[tuple, str]]:
    return {name: _table_map(world[name]) for name in ALL_TABLES}


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
    """The SS-SM-06 board plus the roster facts the scenario names.

    Taylor is joined to this Unit Campaign (the second Scout the capacity step needs);
    Emery stays un-joined here (their membership fixture is REMOVED in another campaign),
    and Taylor carries an ACTIVE commitment in ANOTHER Unit Campaign — the cross-campaign
    conflict the step 5 walk reaches for.
    """
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    unit_campaigns_table.put_item(
        Item=unit_campaign_membership_item(
            CAMPAIGN, PACK_3149, _scout_campaign("Taylor"), _profile("Taylor"), status="ACTIVE", joined_by="Taylor"
        )
    )
    _seed_event(show_and_sells_table, BOARD)
    _seed_event(show_and_sells_table, PAST_BOARD, start_at=PAST_START, end_at=PAST_END, status=ssm.STATUS_ENDED)
    _seed_slot(show_and_sells_table, PAST_BOARD, "p-1", P_SLOT_START, P_SLOT_END, capacity=2)
    show_and_sells_table.put_item(
        Item=ssm.build_show_and_sell_signup_item(
            event=show_and_sells_table.get_item(Key=ssm.event_metadata_key(PAST_BOARD))["Item"],
            slot_id="p-1",
            profile_id=_profile("Devon"),
            campaign_id=_scout_campaign("Devon"),
            signed_up_by_account_id="ACCOUNT#avery-fixture",
            now_iso=PAST_START,
        )
    )
    world_map = {
        "show_and_sells": show_and_sells_table,
        "unit_campaigns": unit_campaigns_table,
        "inventory": inventory_table,
        "profiles": profiles_table,
        "campaigns": campaigns_table,
        "shares": shares_table,
        "units": units_table,
        "catalogs": catalogs_table,
    }
    show_and_sells_table.update_item(
        Key=ssm.slot_key(PAST_BOARD, "p-1"),
        UpdateExpression="SET #count = #count + :one",
        ExpressionAttributeNames={"#count": ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE},
        ExpressionAttributeValues={":one": 1},
    )
    return world_map


# --- The scenario walk -----------------------------------------------------------


def test_the_ss_sm_06_board_walks_capacity_duplicates_adjacency_and_conflicts(
    world: Dict[str, Any],
) -> None:
    """SS-SM-06 steps 1-5 and 7 through the resolvers, with storage read back each step."""
    # Steps 1/4 of §3.3's shape: the three arbitrary durations, inside the event, capacity 1.
    first = _ok(_call(UPSERT_SLOT_FIELD, "Avery", mutation={
        "showAndSellId": BOARD, "label": "First Sales", "startAt": FIRST_START, "endAt": FIRST_END,
        "capacity": 1, **_version(_event_version(world)), **_idem("slot-first")}))
    midday = _ok(_call(UPSERT_SLOT_FIELD, "Avery", mutation={
        "showAndSellId": BOARD, "label": "Midday", "startAt": MIDDAY_START, "endAt": MIDDAY_END,
        "capacity": 1, **_version(_event_version(world)), **_idem("slot-midday")}))
    full = _ok(_call(UPSERT_SLOT_FIELD, "Avery", mutation={
        "showAndSellId": BOARD, "label": "Full Booth", "startAt": FULL_START, "endAt": FULL_END,
        "capacity": 1, **_version(_event_version(world)), **_idem("slot-full")}))
    assert (first["slotId"], midday["slotId"], full["slotId"]) != ("", "", "")
    assert first["capacity"] == midday["capacity"] == full["capacity"] == 1

    # Step 1: Avery(Devon) into First Sales.
    _ok(_signup("Avery", "Devon", first["slotId"], "sign-devon-first"))
    assert _stored_slot_count(world, first["slotId"]) == 1

    # Duplicate: the same Scout, the same slot, a fresh idempotency key.
    _refusal(_signup("Avery", "Devon", first["slotId"], "sign-devon-again"), "CONFLICT")
    assert _stored_slot_count(world, first["slotId"]) == 1

    # Step 3: capacity 1 is enforced against a different Scout, and nothing waits.
    _refusal(_signup("Avery", "Taylor", first["slotId"], "sign-taylor-first"), "CONFLICT")
    assert _stored_slot_count(world, first["slotId"]) == 1
    assert _stored_signup(world, "Taylor", first["slotId"]) is None

    # Step 4: the adjacent Midday slot succeeds — an endpoint it only touches is not shared.
    _ok(_signup("Avery", "Devon", midday["slotId"], "sign-devon-midday"))
    assert _stored_slot_count(world, midday["slotId"]) == 1

    # Step 5: Full Booth overlaps BOTH of Devon's commitments and is refused; nothing partial.
    message = _refusal(_signup("Avery", "Devon", full["slotId"], "sign-devon-full"), "CONFLICT")
    assert "another Show & Sell at these hours" in message
    assert _stored_signup(world, "Devon", full["slotId"]) is None
    assert _stored_slot_count(world, full["slotId"]) == 0

    # Step 7: an un-joined Scout is absent, not forbidden.
    _refusal(_signup("Avery", "Emery", midday["slotId"], "sign-emery"), "NOT_FOUND")
    assert _stored_signup(world, "Emery", midday["slotId"]) is None

    # A cancellation frees the place again (the plan's release rule), and the counter moves.
    _ok(_call(CANCEL_SIGNUP_FIELD, "Avery", mutation={
        "showAndSellId": BOARD, "slotId": midday["slotId"], "profileId": _profile("Devon"),
        **_version(1), **_idem("cancel-devon-midday")}))
    assert _stored_slot_count(world, midday["slotId"]) == 0


def test_a_commitment_in_another_unit_campaign_blocks_the_signup_and_stays_unnamed(
    world: Dict[str, Any],
) -> None:
    """§3.7.2 cross-Unit-Campaign: the guard spans campaigns, the refusal names no tenant.

    Taylor holds an ACTIVE commitment in another Unit Campaign of another Unit, overlapping
    the Midday hours. The signup for Taylor into Midday is refused, and the sentence does not
    disclose the other campaign or event (INV-Q-06-03).
    """
    midday_slot = _ok(_call(UPSERT_SLOT_FIELD, "Avery", mutation={
        "showAndSellId": BOARD, "label": "Midday", "startAt": MIDDAY_START, "endAt": MIDDAY_END,
        "capacity": 4, **_version(_event_version(world)), **_idem("slot-midday")}))
    world["unit_campaigns"].put_item(
        Item=ssm.build_scout_commitment_item(
            profile_id=_profile("Taylor"),
            unit_campaign_id=OTHER_CAMPAIGN,
            show_and_sell_id=CONFLICT_EVENT,
            slot_id="slot-there",
            start_at=MIDDAY_START,
            end_at=_at(MIDDAY_START, 1),
            now_iso=E_START,
            version=1,
        )
    )
    message = _refusal(_signup("Avery", "Taylor", midday_slot["slotId"], "sign-taylor-midday"), "CONFLICT")
    assert OTHER_CAMPAIGN not in message and CONFLICT_EVENT not in message, "the refusal names no other tenant"
    assert _stored_slot_count(world, midday_slot["slotId"]) == 0


def test_work_is_confirmed_per_slot_and_zero_unconfirms_with_its_audit(world: Dict[str, Any]) -> None:
    """SS-SM-06 step 9 + §3.7.2 unconfirmation: 75' then 0' clears the row, keeps the place.

    Minutes need not equal the slot duration (75 in a 90-minute slot), the audit names the
    confirming Kernel, and a later 0 un-confirms: the minutes drop, the work audit clears,
    and the Scout's place itself survives.
    """
    confirmed = _ok(_call(CONFIRM_WORK_FIELD, "Avery", mutation={
        "showAndSellId": PAST_BOARD,
        "work": [{"slotId": "p-1", "profileId": _profile("Devon"), "actualMinutes": 75}],
        **_version(_event_version(world, PAST_BOARD)), **_idem("confirm-75")}))
    assert confirmed["work"][0]["actualMinutes"] == 75
    row = _stored_signup(world, "Devon", "p-1", PAST_BOARD)
    assert row is not None and row.get("confirmedByAccountId")

    _ok(_call(CONFIRM_WORK_FIELD, "Avery", mutation={
        "showAndSellId": PAST_BOARD,
        "work": [{"slotId": "p-1", "profileId": _profile("Devon"), "actualMinutes": 0}],
        **_version(_event_version(world, PAST_BOARD)), **_idem("confirm-zero")}))
    cleared = _stored_signup(world, "Devon", "p-1", PAST_BOARD)
    assert cleared is not None
    assert int(cleared[ssm.ACTUAL_MINUTES_ATTRIBUTE]) == 0
    assert not cleared.get("confirmedByAccountId"), "zero clears the work audit with it"
    assert cleared[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_ACTIVE, "un-confirming is not cancelling the place"
    assert _stored_slot_count(world, "p-1", PAST_BOARD) == 1


def test_a_signup_writes_only_its_documented_rows_and_generates_no_notification(
    world: Dict[str, Any],
) -> None:
    """NOTIFY-01 / SS-SM-06 step 10: no automatic mail, inbox row, or side effect anywhere.

    The oracle is the closed write-set: taking a place adds exactly the signup row and its
    idempotency marker to ``show_and_sells``, and exactly the commitment projection and
    Scout guard to ``unit_campaigns``; it moves exactly the slot counter and the event
    version. Every other table is byte-identical, so no notification artifact exists to
    find — the absence is proved by closure, not by keyword luck.
    """
    first = _ok(_call(UPSERT_SLOT_FIELD, "Avery", mutation={
        "showAndSellId": BOARD, "label": "First Sales", "startAt": FIRST_START, "endAt": FIRST_END,
        "capacity": 2, **_version(_event_version(world)), **_idem("slot-first")}))

    before = _census(world)
    _ok(_signup("Avery", "Devon", first["slotId"], "sign-devon-first"))
    after = _census(world)

    added = {
        name: set(after[name]) - set(before[name])
        for name in ALL_TABLES
    }
    changed = {
        name: {key for key in set(before[name]) & set(after[name]) if before[name][key] != after[name][key]}
        for name in ALL_TABLES
    }
    assert added["show_and_sells"] and len(added["show_and_sells"]) == 2, (
        "exactly the signup row and its marker are added"
    )
    assert added["unit_campaigns"] and len(added["unit_campaigns"]) == 2, (
        "exactly the commitment projection and the Scout's guard are added"
    )
    assert changed["show_and_sells"] and len(changed["show_and_sells"]) == 2, (
        "exactly the slot counter and the event version move"
    )
    for name in ("inventory", "profiles", "campaigns", "shares", "units", "catalogs"):
        assert not added[name] and not changed[name], f"the signup write reached the {name} table"

    words = ("notification", "notify", "email", "inbox", "message", "sms")
    touched = [
        after[name][key]
        for name in ALL_TABLES
        for key in added[name] | changed[name]
    ]
    for row in touched:
        lowered = row.lower()
        assert not any(word in lowered for word in words), f"a touched row carries notification vocabulary: {row[:120]}"
