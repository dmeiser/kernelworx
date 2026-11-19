"""Wave 4.3 — the slot board: ``upsertShowAndSellSlot`` and ``deleteShowAndSellSlot`` (§3.3.2, §3.3.3).

Resolver-level cases for ``SLOT-M-01`` and ``SLOT-M-02``, with ``AUTH-U``, ``VER-01`` and
``IDEM`` from the API contract. Everything runs through ``handle_unit_operation`` against
moto, so what is proved is the committed transaction rather than the plan: the slot row,
the commitment projections a time move carries with it, the affected Scouts' guards, the
event version and the idempotency marker either all land or none of them do, and the
denial the browser sees is the one the resolver actually raised. The pure half — the
interval rule, the 90/120/180-minute shapes, the overlap and counter arithmetic — is
``tests/unit/test_show_and_sell_slot_model.py``.

Event and slot instants are measured from the real clock, because the resolver derives
``SCHEDULED``/``ACTIVE``/``ENDED`` from ``utc_now_iso()`` and a literal "future" goes stale
the day the calendar crosses it. The event window is twelve hours wide so a 180-minute
slot, an adjacency, and a 20-slot board all fit inside it without arithmetic in the test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

import pytest

from src.handlers.unit_operations import (
    DELETE_SLOT_FIELD,
    SHOW_AND_SELL_FIELD,
    UPSERT_SLOT_FIELD,
    handle_unit_operation,
)
from src.utils import show_and_sell_models as ssm
from src.utils.mutations import MAX_TRANSACTION_ACTIONS
from tests.unit.show_sell_fixtures import (
    PACK_3149,
    PACK_3149_FALL,
    PROFILES,
    assert_is_error,
    seed_show_sell_fixtures,
    unit_operation_event,
)

CAMPAIGN = PACK_3149_FALL
OTHER_UNIT = "unit-crew-529-denver"
OTHER_CAMPAIGN = "uc-crew-529-spring-2027"
EVENT = "SSE#slot-board"
OTHER_EVENT = "SSE#other-board"
LOCATION = "Aurora armory lot"
SLOT_FIELDS = {
    "showAndSellId",
    "slotId",
    "label",
    "startAt",
    "endAt",
    "capacity",
    "activeSignupCount",
    "version",
    "createdAt",
    "updatedAt",
}


def _shift(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


#: The board's event: three days ahead of the clock, so still ``SCHEDULED``, and twelve
#: hours wide — enough for a 180-minute slot, an adjacent one, and twenty of either.
EVENT_START, EVENT_END = _shift(72), _shift(84)


def _at(offset: float) -> str:
    """An instant inside the board's event window, measured from its own start."""
    return (datetime.fromisoformat(EVENT_START) + timedelta(hours=offset)).isoformat()


#: The slot every test starts with: one hour into a twelve-hour event, two hours wide, so
#: a 180-minute slot, an adjacent one and a full board all still fit beside it.
FIRST_START, FIRST_END = _at(1), _at(3)

#: The two instants just outside the event, used by the bounds refusal.
OUTSIDE_BEFORE, OUTSIDE_AFTER = _at(-2), _at(14)


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
    failed = isinstance(payload, dict) and payload.get("__isError")
    assert not failed, f"expected a success payload, got {payload!r}"
    return payload


def _idem(key: Optional[str]) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": key}}


def _version(expected: int) -> Dict[str, Any]:
    return {"version": {"expectedVersion": expected}}


def _refusal(payload: Any, code: str) -> str:
    """The sentence one refusal answered, so a test can name the guard it proved.

    ``AppError.details`` does not survive the resolver boundary — a decorated-Lambda
    payload carries ``errorCode`` and ``message`` only — and every guard in these two
    mutations answers ``CONFLICT``, so the sentence is the only thing that says which one
    fired. Each refusal's wording is therefore part of the contract these tests pin.
    """
    return str(assert_is_error(payload, code).get("message") or "")


def _upsert(
    caller: Optional[str] = "Avery",
    *,
    event_id: str = EVENT,
    slot_id: Optional[str] = None,
    slot_version: Optional[Any] = None,
    start_at: Any = FIRST_START,
    end_at: Any = FIRST_END,
    capacity: Any = 4,
    label: Optional[str] = "Morning door",
    version: int = 1,
    key: Optional[str] = "slot-1",
    **extras: Any,
) -> Any:
    """One ``upsertShowAndSellSlot`` turn, with ``slotId``/``slotVersion`` only when named."""
    payload: Dict[str, Any] = {
        "showAndSellId": event_id,
        "startAt": start_at,
        "endAt": end_at,
        "capacity": capacity,
        **_version(version),
        **_idem(key),
    }
    if slot_id is not None:
        payload["slotId"] = slot_id
    if slot_version is not None:
        payload["slotVersion"] = {"expectedVersion": slot_version}
    if label is not None:
        payload["label"] = label
    payload.update(extras)
    return _call(UPSERT_SLOT_FIELD, caller, mutation=payload)


def _delete(
    caller: Optional[str] = "Avery",
    *,
    event_id: str = EVENT,
    slot_id: Any = "slot-1",
    version: int = 1,
    key: Optional[str] = "delete-1",
) -> Any:
    payload: Dict[str, Any] = {
        "showAndSellId": event_id,
        "slotId": slot_id,
        **_version(version),
        **_idem(key),
    }
    return _call(DELETE_SLOT_FIELD, caller, mutation=payload)


def _admin_answer(event_id: str = EVENT) -> Dict[str, Any]:
    """The administrative event read, so a slot write is checked against what a screen sees."""
    return _ok(_call(SHOW_AND_SELL_FIELD, "Avery", arguments={"showAndSellId": event_id}))


# --- Seeded rows -----------------------------------------------------------------


def _event_item(
    event_id: str = EVENT,
    *,
    unit_id: str = PACK_3149,
    unit_campaign_id: str = CAMPAIGN,
    start_at: str = EVENT_START,
    end_at: str = EVENT_END,
    status: str = ssm.STATUS_SCHEDULED,
    version: int = 1,
) -> Dict[str, Any]:
    fields: Dict[str, Any] = {
        "show_and_sell_id": event_id,
        "unit_id": unit_id,
        "unit_campaign_id": unit_campaign_id,
        "location_name": LOCATION,
        "start_at": start_at,
        "end_at": end_at,
        "created_by_account_id": "ACCOUNT#avery-fixture",
        "now_iso": start_at,
        "version": version,
    }
    item = ssm.build_show_and_sell_item(**fields)
    item[ssm.STATUS_ATTRIBUTE] = status
    if status == ssm.STATUS_FINALIZED:
        item[ssm.APPROVED_FINALIZATION_ID_ATTRIBUTE] = f"FIN#{event_id}"
    return item


def _seed_event(show_and_sells_table: Any, event_id: str = EVENT, **overrides: Any) -> str:
    show_and_sells_table.put_item(Item=_event_item(event_id, **overrides))
    return event_id


def _seed_slot(
    show_and_sells_table: Any,
    event_id: str = EVENT,
    slot_id: str = "slot-1",
    *,
    start_at: str = FIRST_START,
    end_at: str = FIRST_END,
    capacity: int = 4,
    active: int = 0,
    version: int = 1,
    label: Optional[str] = "Morning door",
    **stored_overrides: Any,
) -> Dict[str, Any]:
    """One slot row, built by §3.3.1's own builder so the board holds real rows.

    ``stored_overrides`` are the only way to get a row the builder would refuse — a
    counter that disagrees with its signup rows, say — and the tests that use them are
    testing exactly that: the guard that has to hold when the aggregate is already wrong.
    """
    item = ssm.build_show_and_sell_slot_item(
        event=_event_item(event_id),
        slot_id=slot_id,
        start_at=start_at,
        end_at=end_at,
        capacity=capacity,
        active_signup_count=active,
        version=version,
        label=label,
        now_iso=EVENT_START,
    )
    item.update(stored_overrides)
    show_and_sells_table.put_item(Item=item)
    return item


def _seed_signup(
    show_and_sells_table: Any,
    event_id: str = EVENT,
    slot_id: str = "slot-1",
    *,
    persona: str = "Devon",
    profile_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    status: str = ssm.SIGNUP_ACTIVE,
    version: int = 1,
) -> Dict[str, Any]:
    item = ssm.build_show_and_sell_signup_item(
        event=_event_item(event_id),
        slot_id=slot_id,
        profile_id=profile_id or _profile(persona),
        campaign_id=campaign_id or _scout_campaign(persona),
        signed_up_by_account_id=f"ACCOUNT#{persona.lower()}-fixture",
        now_iso=EVENT_START,
        status=status,
        version=version,
    )
    show_and_sells_table.put_item(Item=item)
    return item


def _seed_commitment(
    unit_campaigns_table: Any,
    event_id: str = EVENT,
    slot_id: str = "slot-1",
    *,
    persona: str = "Devon",
    profile_id: Optional[str] = None,
    start_at: str = FIRST_START,
    end_at: str = FIRST_END,
    unit_campaign_id: str = CAMPAIGN,
    status: str = ssm.SIGNUP_ACTIVE,
    version: int = 1,
) -> Dict[str, Any]:
    item = ssm.build_scout_commitment_item(
        profile_id=profile_id or _profile(persona),
        unit_campaign_id=unit_campaign_id,
        show_and_sell_id=event_id,
        slot_id=slot_id,
        start_at=start_at,
        end_at=end_at,
        now_iso=EVENT_START,
        version=version,
        status=status,
    )
    unit_campaigns_table.put_item(Item=item)
    return item


def _seed_guard(
    unit_campaigns_table: Any,
    *,
    persona: str = "Devon",
    profile_id: Optional[str] = None,
    version: int = 3,
) -> Dict[str, Any]:
    item = ssm.build_commitment_guard_item(
        profile_id=profile_id or _profile(persona), commitment_version=version, now_iso=EVENT_START
    )
    unit_campaigns_table.put_item(Item=item)
    return item


def _signed_up_board(
    world: Dict[str, Any],
    *slots: tuple[str, str, str],
    personas: Sequence[str] = ("Devon",),
    commitments: bool = True,
) -> None:
    """Slots, one ACTIVE signup and projection per named Scout in each, and the guards.

    The projection is seeded alongside the signup because §3.4 writes the pair in one
    transaction, and it is the row the overlap rule and a slot move are decided against.
    """
    unit_campaigns = world["unit_campaigns"]
    for slot_id, start_at, end_at in slots:
        _seed_slot(world["show_and_sells"], slot_id=slot_id, start_at=start_at, end_at=end_at, active=len(personas))
        for persona in personas:
            _seed_signup(world["show_and_sells"], slot_id=slot_id, persona=persona)
            if commitments:
                _seed_commitment(unit_campaigns, slot_id=slot_id, persona=persona, start_at=start_at, end_at=end_at)
                _seed_guard(unit_campaigns, persona=persona)


# --- Storage reads ---------------------------------------------------------------


def _partition(show_and_sells_table: Any, event_id: str) -> List[Dict[str, Any]]:
    return list(
        show_and_sells_table.query(
            KeyConditionExpression="#pk = :pk",
            ExpressionAttributeNames={"#pk": "pk"},
            ExpressionAttributeValues={":pk": ssm.show_and_sell_pk(event_id)},
        )["Items"]
    )


def _slot_rows(show_and_sells_table: Any, event_id: str = EVENT) -> List[Dict[str, Any]]:
    return [row for row in _partition(show_and_sells_table, event_id) if row.get("entityType") == ssm.ENTITY_TYPE_SLOT]


def _stored_slot(show_and_sells_table: Any, event_id: str = EVENT, slot_id: str = "slot-1") -> Optional[Dict[str, Any]]:
    found = show_and_sells_table.get_item(Key=ssm.slot_key(event_id, slot_id))
    item = found.get("Item")
    return dict(item) if item else None


def _stored(show_and_sells_table: Any, event_id: str = EVENT) -> Dict[str, Any]:
    return dict(show_and_sells_table.get_item(Key=ssm.event_metadata_key(event_id))["Item"])


def _marker_rows(show_and_sells_table: Any) -> List[Dict[str, Any]]:
    """Every idempotency marker on the event table (§8.9): a refused write leaves none.

    A marker rides the table the mutation writes, so a slot marker is a row on
    ``show_and_sells`` with the ``IDEM#`` sort-key prefix — and it lives in the caller's
    own idempotency partition, not the event's, so the read has to be a table scan.
    """
    return [row for row in show_and_sells_table.scan()["Items"] if str(row.get("sk", "")).startswith("IDEM#")]


def _commitment_rows(unit_campaigns_table: Any, *, persona: str = "Devon") -> List[Dict[str, Any]]:
    return [
        dict(row)
        for row in unit_campaigns_table.query(
            KeyConditionExpression="#pk = :pk AND begins_with(#sk, :prefix)",
            ExpressionAttributeNames={"#pk": "pk", "#sk": "sk"},
            ExpressionAttributeValues={":pk": ssm.commitment_pk(_profile(persona)), ":prefix": "COMMITMENT#"},
        )["Items"]
        if str(row.get("sk", "")) != ssm.COMMITMENT_GUARD_SK
    ]


def _guard_version(unit_campaigns_table: Any, *, persona: str = "Devon") -> Optional[int]:
    found = unit_campaigns_table.get_item(Key=ssm.commitment_guard_key(_profile(persona)))
    item = found.get("Item")
    return None if not item else int(item[ssm.COMMITMENT_VERSION_ATTRIBUTE])


@pytest.fixture
def world(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    show_and_sells_table: Any,
) -> Dict[str, Any]:
    """The Stage 1 persona world plus the two tables a slot write touches."""
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    _seed_event(show_and_sells_table)
    _seed_event(show_and_sells_table, OTHER_EVENT, unit_id=OTHER_UNIT, unit_campaign_id=OTHER_CAMPAIGN)
    return {
        "show_and_sells": show_and_sells_table,
        "unit_campaigns": unit_campaigns_table,
    }


# --- SLOT-M-01-01: 90/120/180-minute slots, and the SCHEDULED-state edit ----------


@pytest.mark.parametrize(
    ("minutes", "capacity"),
    [(90, 1), (120, 7), (180, 100)],
)
def test_slot_m_01_01_a_90_120_or_180_minute_slot_is_created_with_the_capacity_offered(
    world: Dict[str, Any], minutes: int, capacity: int
) -> None:
    """SLOT-M-01-01: arbitrary durations and capacities, one conditional write plan.

    No hour or half-hour is assumed (§5.12, SSE-03): the only interval rule is that the
    slot runs forward inside the event. The answer is the SDL's own ``ShowAndSellSlot``
    shape, the counter starts at zero because nobody has signed up yet, and the event
    version moves because its slot board did (§8.3).
    """
    start = _at(1)
    end = (datetime.fromisoformat(start) + timedelta(minutes=minutes)).isoformat()

    answer = _ok(_upsert(start_at=start, end_at=end, capacity=capacity, key=f"slot-{minutes}"))
    assert set(answer) == SLOT_FIELDS, f"the answer is the SDL ``ShowAndSellSlot``: {sorted(answer)}"
    assert answer["startAt"] == start and answer["endAt"] == end
    assert answer["capacity"] == capacity
    assert answer[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE] == 0, "a created slot counts nobody yet"
    assert answer["version"] == 1

    stored = _stored_slot(world["show_and_sells"], slot_id=answer["slotId"])
    assert stored is not None
    assert (
        datetime.fromisoformat(stored[ssm.END_AT_ATTRIBUTE]) - datetime.fromisoformat(stored[ssm.START_AT_ATTRIBUTE])
    ).seconds == minutes * 60
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 2
    assert len(_marker_rows(world["show_and_sells"])) == 1, "the marker rides the same transaction"


def test_slot_m_01_01_a_slot_may_take_the_whole_event_or_touch_either_end(world: Dict[str, Any]) -> None:
    """§5.12's bound is inclusive at both ends: ``event.startAt <= slot.startAt`` and
    ``slot.endAt <= event.endAt``, so a slot that spans the event exactly is legal."""
    whole = _ok(_upsert(start_at=EVENT_START, end_at=EVENT_END, capacity=1, key="whole"))
    assert whole["startAt"] == EVENT_START and whole["endAt"] == EVENT_END

    edge = _ok(_upsert(start_at=_at(11.5), end_at=EVENT_END, key="edge", version=2))
    assert edge["endAt"] == EVENT_END


def test_the_server_mints_the_slot_id_and_two_creates_are_two_slots(world: Dict[str, Any]) -> None:
    """A create names no slot: the id is the server's, and two creates cannot collide.

    The id is the suffix of the slot row's sort key inside the event's partition, so an
    id the browser guessed could land on a slot the event already has and read back as a
    duplicate rather than as the new slot that was asked for.
    """
    first = _ok(_upsert(key="create-a"))
    second = _ok(_upsert(start_at=_at(2), end_at=_at(4), key="create-b", version=2))
    assert first["slotId"] != second["slotId"]
    assert len({first["slotId"], second["slotId"]}) == 2
    assert [row["slotId"] for row in _slot_rows(world["show_and_sells"])] == sorted([first["slotId"], second["slotId"]])
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 3


def test_a_label_is_written_as_offered_and_an_omitted_label_stores_none(world: Dict[str, Any]) -> None:
    """§5.12's label is optional, and an upsert writes the whole slot as offered."""
    answer = _ok(_upsert(label="Ring 3 drive", key="labelled"))
    assert answer["label"] == "Ring 3 drive"

    unlabelled = _ok(_upsert(slot_id=answer["slotId"], slot_version=1, label=None, version=2, key="unlabelled"))
    assert unlabelled["label"] is None
    assert (
        ssm.LABEL_ATTRIBUTE not in _stored_slot(world["show_and_sells"], slot_id=answer["slotId"])
        or _stored_slot(world["show_and_sells"], slot_id=answer["slotId"])[ssm.LABEL_ATTRIBUTE] is None
    )


def test_slot_m_01_01_an_edit_moves_the_interval_capacity_and_label_and_both_versions(
    world: Dict[str, Any],
) -> None:
    """SLOT-M-01-01: an edit in SCHEDULED state moves the slot row and the event version."""
    created = _ok(_upsert(key="create-1"))
    slot_id = created["slotId"]

    edited = _ok(
        _upsert(
            slot_id=slot_id,
            slot_version=1,
            start_at=_at(4),
            end_at=_at(6),
            capacity=6,
            label="Afternoon door",
            version=2,
            key="edit-1",
        )
    )
    assert edited["version"] == 2
    assert edited["capacity"] == 6
    assert edited["label"] == "Afternoon door"
    assert edited["startAt"] == _at(4)
    assert edited["createdAt"] == created["createdAt"], "an edit re-dates nothing but ``updatedAt``"

    stored = _stored_slot(world["show_and_sells"], slot_id=slot_id)
    assert stored is not None
    assert stored[ssm.VERSION_ATTRIBUTE] == 2
    assert stored[ssm.CREATED_AT_ATTRIBUTE] == created["createdAt"]
    assert len(_slot_rows(world["show_and_sells"])) == 1, "an edit writes the one row it addressed"
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 3


# --- SLOT-M-01-02: the refusals that must leave the board and its signups alone ---


@pytest.mark.parametrize(
    ("start_at", "end_at", "phrase"),
    [
        (OUTSIDE_BEFORE, _at(2), "starts before the event starts"),
        (_at(2), OUTSIDE_AFTER, "ends after the event ends"),
    ],
)
def test_slot_m_01_02_a_slot_outside_the_event_interval_is_refused_and_writes_nothing(
    world: Dict[str, Any], start_at: str, end_at: str, phrase: str
) -> None:
    """SLOT-M-01-02: ``event.startAt <= slot.startAt < slot.endAt <= event.endAt``."""
    refused = assert_is_error(_upsert(start_at=start_at, end_at=end_at), "INVALID_INPUT")
    assert phrase in str(refused.get("message") or ""), refused

    assert _slot_rows(world["show_and_sells"]) == [], "a refused slot write writes no row"
    assert _marker_rows(world["show_and_sells"]) == [], "and leaves no marker behind"
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 1


def test_a_slot_interval_that_does_not_run_forward_is_refused(world: Dict[str, Any]) -> None:
    """``endAt > startAt`` is checked before the bound, so an inverted slot never reads as "outside"."""
    assert_is_error(_upsert(start_at=_at(5), end_at=_at(5)), "INVALID_INPUT")
    assert_is_error(_upsert(start_at=_at(6), end_at=_at(4)), "INVALID_INPUT")
    assert _slot_rows(world["show_and_sells"]) == []


@pytest.mark.parametrize("capacity", [0, 101, "4"])
def test_capacity_outside_one_to_one_hundred_is_refused(world: Dict[str, Any], capacity: Any) -> None:
    """§3.3.2: capacity 1-100 is validation, not a tunable (0 fills nothing, four digits is a slip)."""
    assert_is_error(_upsert(capacity=capacity), "INVALID_INPUT")
    assert _slot_rows(world["show_and_sells"]) == []


def test_slot_m_01_02_the_twentieth_slot_is_written_and_the_twenty_first_is_not(
    world: Dict[str, Any],
) -> None:
    """SLOT-M-01-02 / 20-21: the cap is enforced before the write, and the board stays whole.

    The count cannot be a DynamoDB condition, so the race closes on the event version:
    both writers read the same 20 slots, and only the one holding the current event
    version commits.
    """
    for index in range(ssm.MAX_SLOTS_PER_EVENT):
        offset = 0.5 + index * 0.25
        _ok(_upsert(start_at=_at(offset), end_at=_at(offset + 0.25), key=f"fill-{index}", version=index + 1))
    assert len(_slot_rows(world["show_and_sells"])) == ssm.MAX_SLOTS_PER_EVENT

    message = _refusal(
        _upsert(start_at=_at(11), end_at=EVENT_END, key="one-too-many", version=ssm.MAX_SLOTS_PER_EVENT + 1),
        "CONFLICT",
    )
    assert "already has 20 slots" in message and "at most 20" in message, message
    assert len(_slot_rows(world["show_and_sells"])) == ssm.MAX_SLOTS_PER_EVENT


def test_slot_m_01_02_capacity_cannot_drop_below_the_active_signups_a_slot_holds(
    world: Dict[str, Any],
) -> None:
    """SLOT-M-01-02 / capacity-shrink: freeing a Scout is §3.4's cancellation, never a side effect."""
    _signed_up_board(world, ("slot-1", FIRST_START, FIRST_END), personas=("Devon", "Emery"))

    message = _refusal(_upsert(slot_id="slot-1", slot_version=1, capacity=1, version=1), "CONFLICT")
    assert "holds 2 active signup(s)" in message and "capacity cannot drop below" in message, message

    stored = _stored_slot(world["show_and_sells"])
    assert stored is not None
    assert stored[ssm.CAPACITY_ATTRIBUTE] == 4 and stored[ssm.VERSION_ATTRIBUTE] == 1
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 1
    assert _marker_rows(world["show_and_sells"]) == []
    signups = [
        row for row in _partition(world["show_and_sells"], EVENT) if row.get("entityType") == ssm.ENTITY_TYPE_SIGNUP
    ]
    assert len(signups) == 2 and all(row[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_ACTIVE for row in signups)


def test_a_capacity_shrink_that_a_signup_raced_is_refused_by_the_write_condition(
    world: Dict[str, Any],
) -> None:
    """The floor is enforced twice: against this read, and as a condition on the write itself.

    A slot whose stored counter disagrees with its signup rows is a broken aggregate, and
    it is the case the read-side floor cannot see — so ``#activeSignupCount <= :capacity``
    is what refuses it. The transaction is cancelled whole: no slot row, no event version.
    """
    _seed_slot(world["show_and_sells"], capacity=5, active=4)

    refused = assert_is_error(_upsert(slot_id="slot-1", slot_version=1, capacity=3), "CONFLICT")
    assert "changed underneath this request" in str(refused.get("message") or "")

    stored = _stored_slot(world["show_and_sells"])
    assert stored is not None
    assert stored[ssm.CAPACITY_ATTRIBUTE] == 5
    assert stored[ssm.VERSION_ATTRIBUTE] == 1
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 1
    assert _marker_rows(world["show_and_sells"]) == []


def test_slot_m_01_02_a_time_move_onto_a_sibling_slot_of_the_same_scout_is_refused(
    world: Dict[str, Any],
) -> None:
    """SLOT-M-01-02 / newly-conflicting-time: one Scout, two slots, one body.

    The refusal names the slot the Scout already holds, because a Kernel moving a board
    has to know which other slot collided, not just that something did.
    """
    _signed_up_board(
        world,
        ("slot-1", _at(1), _at(3)),
        ("slot-2", _at(5), _at(7)),
    )

    message = _refusal(
        _upsert(slot_id="slot-1", slot_version=1, start_at=_at(5), end_at=_at(7), version=1),
        "CONFLICT",
    )
    assert "overlap slot slot-2" in message, message
    assert _profile("Devon") in message, "the refusal names the Scout who is already there"

    for slot_id in ("slot-1", "slot-2"):
        stored = _stored_slot(world["show_and_sells"], slot_id=slot_id)
        assert stored is not None and stored[ssm.VERSION_ATTRIBUTE] == 1
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 1
    assert len(_commitment_rows(world["unit_campaigns"])) == 2, "the signups keep the interval they were made for"


def test_slot_m_01_02_a_time_move_onto_another_show_and_sell_s_commitment_is_refused(
    world: Dict[str, Any],
) -> None:
    """SLOT-M-01-02 / SLOT-04: the blocker is the Scout's commitment, not this event's signup rows.

    The Scout is signed up for this board at 09:00-11:00 and for another Unit Campaign's
    event at 13:00-15:00. Moving this slot onto the afternoon is refused even though
    nothing in this event collides, because the cross-campaign projection is what §3.4's
    signup will consult and AC-14 says a Scout cannot hold overlapping commitments.
    """
    _seed_slot(world["show_and_sells"], start_at=_at(1), end_at=_at(3))
    _seed_signup(world["show_and_sells"], slot_id="slot-1")
    _seed_commitment(world["unit_campaigns"], slot_id="slot-1", start_at=_at(1), end_at=_at(3))
    _seed_commitment(
        world["unit_campaigns"],
        OTHER_EVENT,
        "slot-elsewhere",
        start_at=_at(5),
        end_at=_at(7),
        unit_campaign_id=OTHER_CAMPAIGN,
    )
    _seed_guard(world["unit_campaigns"])

    refused = assert_is_error(
        _upsert(slot_id="slot-1", slot_version=1, start_at=_at(5), end_at=_at(7), version=1),
        "CONFLICT",
    )
    assert OTHER_EVENT in str(refused.get("message") or ""), refused
    assert len(_commitment_rows(world["unit_campaigns"])) == 2, "the refusal moves no projection"
    assert _guard_version(world["unit_campaigns"]) == 3


def test_a_time_move_next_to_a_sibling_slot_stays_legal(world: Dict[str, Any]) -> None:
    """SLOT-03: touching ends are adjacent, never overlapping, so the move is allowed."""
    _signed_up_board(
        world,
        ("slot-1", _at(1), _at(3)),
        ("slot-2", _at(3), _at(5)),
    )

    answer = _ok(_upsert(slot_id="slot-1", slot_version=1, start_at=_at(5), end_at=_at(7), version=1))
    assert answer["startAt"] == _at(5)

    projections = _commitment_rows(world["unit_campaigns"])
    assert len(projections) == 2, "the sibling's projection is not this slot's to move"
    assert [row[ssm.START_AT_ATTRIBUTE] for row in projections] == [_at(3), _at(5)], "only slot-1's projection moved"
    assert projections[1]["sk"] == ssm.commitment_sk(_at(5), CAMPAIGN, "slot-1")
    assert _guard_version(world["unit_campaigns"]) == 4, "the Scout whose commitment moved has a new guard"


def test_a_move_re_commits_only_this_event_s_projection_and_leaves_the_scout_s_other_one(
    world: Dict[str, Any],
) -> None:
    """A Scout working two Show & Sells holds two projections, and only this event's moves.

    The Scout's whole partition is read — that is what makes the cross-campaign overlap rule
    (SLOT-04) answerable — and the same read has to be filtered here. Another event's
    projection still describes hours that event is still running, so rewriting it would
    re-time an event this request never named, and the Scout's own record of when she works
    would come from whichever board was edited last.
    """
    _seed_slot(world["show_and_sells"], start_at=_at(1), end_at=_at(3))
    _seed_signup(world["show_and_sells"], slot_id="slot-1")
    _seed_commitment(world["unit_campaigns"], slot_id="slot-1", start_at=_at(1), end_at=_at(3))
    _seed_commitment(
        world["unit_campaigns"],
        OTHER_EVENT,
        "slot-elsewhere",
        start_at=_at(-4),
        end_at=_at(-2),
        unit_campaign_id=OTHER_CAMPAIGN,
    )
    _seed_guard(world["unit_campaigns"])

    _ok(_upsert(slot_id="slot-1", slot_version=1, start_at=_at(5), end_at=_at(7)))

    projections = _commitment_rows(world["unit_campaigns"])
    assert len(projections) == 2
    #: The other event's row sorts first, so the read has to look past it to find this slot's.
    assert projections[0]["sk"] == ssm.commitment_sk(_at(-4), OTHER_CAMPAIGN, "slot-elsewhere")
    assert projections[0][ssm.SHOW_AND_SELL_ID_ATTRIBUTE] == OTHER_EVENT
    assert projections[1]["sk"] == ssm.commitment_sk(_at(5), CAMPAIGN, "slot-1"), "this event's projection moved"
    assert _guard_version(world["unit_campaigns"]) == 4


def test_a_moved_slot_carries_its_signups_commitment_to_the_new_interval(
    world: Dict[str, Any],
) -> None:
    """A time change moves the projection with the slot, in the same transaction.

    The projection's key IS its interval (§6.2), so leaving it behind would answer the
    next overlap question about hours nobody works: the following signup would be refused
    for the old hours and admitted beside a Scout now holding the new ones. The version
    rides unchanged — §5.13 keeps it equal to the source signup's — and the Scout's guard
    increments, which is what makes a signup planned against the old guard fail.
    """
    _signed_up_board(world, ("slot-1", _at(1), _at(3)), personas=("Devon", "Emery"))

    _ok(_upsert(slot_id="slot-1", slot_version=1, start_at=_at(5), end_at=_at(7), version=1))

    unit_campaigns = world["unit_campaigns"]
    for persona in ("Devon", "Emery"):
        projections = _commitment_rows(unit_campaigns, persona=persona)
        assert len(projections) == 1, "the old interval is gone, not left beside the new one"
        moved = projections[0]
        assert moved[ssm.START_AT_ATTRIBUTE] == _at(5) and moved[ssm.END_AT_ATTRIBUTE] == _at(7)
        assert moved["sk"] == ssm.commitment_sk(_at(5), CAMPAIGN, "slot-1")
        assert moved[ssm.VERSION_ATTRIBUTE] == 1, (
            "the projection's version is its source signup's, and the signup did not move"
        )
        assert _guard_version(unit_campaigns, persona=persona) == 4, "a moved commitment is a commitment change"
    signup = world["show_and_sells"].get_item(
        Key={"pk": ssm.show_and_sell_pk(EVENT), "sk": ssm.signup_sk("slot-1", _profile("Devon"))}
    )["Item"]
    assert signup[ssm.VERSION_ATTRIBUTE] == 1, "the signup row itself is untouched by its slot moving"


def test_a_slot_edit_that_moves_no_time_writes_no_commitment_and_bumps_no_guard(
    world: Dict[str, Any],
) -> None:
    """A capacity or label edit moves no projection.

    Staging a delete-and-put pair and a guard bump for a row that is not moving spends
    three transaction actions on a row that cannot change, and a guard bump would make an
    unrelated in-flight signup for that Scout fail for no reason.
    """
    _signed_up_board(world, ("slot-1", _at(1), _at(3)))

    _ok(_upsert(slot_id="slot-1", slot_version=1, start_at=_at(1), end_at=_at(3), capacity=9, key="cap-only"))

    projections = _commitment_rows(world["unit_campaigns"])
    assert [row[ssm.START_AT_ATTRIBUTE] for row in projections] == [_at(1)]
    assert projections[0]["sk"] == ssm.commitment_sk(_at(1), CAMPAIGN, "slot-1")
    assert _guard_version(world["unit_campaigns"]) == 3


def test_a_signup_with_no_projection_has_nothing_to_move_and_the_move_still_succeeds(
    world: Dict[str, Any],
) -> None:
    """A signup whose projection is missing is a broken aggregate, not something this write repairs.

    Inventing a commitment row would need a version to condition on, and the projection's
    version is its source signup's — the agreement §3.7's validation exists to check. The
    slot still moves: the board is the admin's, and the disagreement is reported there.
    """
    _signed_up_board(world, ("slot-1", _at(1), _at(3)), commitments=False)

    _ok(_upsert(slot_id="slot-1", slot_version=1, start_at=_at(5), end_at=_at(7), version=1))

    assert _stored_slot(world["show_and_sells"]) is not None
    assert _commitment_rows(world["unit_campaigns"]) == []
    assert _guard_version(world["unit_campaigns"]) is None


def test_a_time_move_with_more_signups_than_one_transaction_can_hold_is_refused_first(
    world: Dict[str, Any],
) -> None:
    """The move is atomic or it does not happen: a slot at its new time beside stale
    commitments is the disagreement AC-14 exists to prevent, so the plan is never split.

    Ninety writes is the plan ceiling, and a re-time spends three per Scout — the
    projection's delete, its put at the new key, and that Scout's guard bump — plus the
    marker, the slot row and the event bump. Thirty Scouts is the first number that does
    not fit, so the board is minted to that size rather than hoping a fixture's roster
    happens to be large enough to reach the ceiling.
    """
    scouts = [f"PROFILE#prof-move-{index:02d}-fixture" for index in range(30)]
    _seed_slot(world["show_and_sells"], capacity=len(scouts), active=len(scouts))
    for scout in scouts:
        _seed_signup(world["show_and_sells"], profile_id=scout)
        _seed_commitment(world["unit_campaigns"], profile_id=scout)
        _seed_guard(world["unit_campaigns"], profile_id=scout)

    message = _refusal(
        _upsert(slot_id="slot-1", slot_version=1, start_at=_at(5), end_at=_at(7), capacity=len(scouts)), "CONFLICT"
    )
    assert f"has {len(scouts)} active signup(s)" in message, message
    assert f"({MAX_TRANSACTION_ACTIONS} writes)" in message, message

    stored = _stored_slot(world["show_and_sells"])
    assert stored is not None and stored[ssm.START_AT_ATTRIBUTE] == FIRST_START
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 1
    assert _marker_rows(world["show_and_sells"]) == []


# --- SLOT-M-01-03: AUTH-U, VER-01 for event and slot, IDEM -----------------------


def test_slot_m_01_03_only_an_admin_of_the_event_s_own_unit_may_write_its_slots(
    world: Dict[str, Any],
) -> None:
    """AUTH-U: a Scout, another Unit's Admin, and an unauthenticated caller are refused.

    The cross-Unit refusal is ``NOT_FOUND``, the same answer as for an event that does not
    exist, so a slot mutation is never a resource-existence oracle across tenants (SEC-03).
    """
    for persona in ("Blake", "Riley", "Devon", "Taylor"):
        assert_is_error(_upsert(caller=persona), "NOT_FOUND")
    assert_is_error(_upsert(caller=None), "UNAUTHORIZED")
    assert_is_error(_delete(caller="Taylor"), "NOT_FOUND")
    assert_is_error(_delete(caller=None), "UNAUTHORIZED")

    assert _slot_rows(world["show_and_sells"]) == []
    assert _marker_rows(world["show_and_sells"]) == []


def test_slot_m_01_03_only_a_slot_of_the_named_event_is_reachable(world: Dict[str, Any]) -> None:
    """The parent id is part of the key, so another event's slot id is simply not here.

    The caller does not choose the Unit or the campaign: tenancy comes from the event row
    the parent id resolves to, and an id from another tenant's event answers ``NOT_FOUND``.
    """
    _seed_slot(world["show_and_sells"], OTHER_EVENT)

    assert_is_error(_upsert(slot_id="slot-1", slot_version=1), "NOT_FOUND")
    assert _stored_slot(world["show_and_sells"], OTHER_EVENT) is not None, "the other event's row is untouched"

    assert_is_error(_delete(slot_id="slot-1"), "NOT_FOUND")
    assert _stored_slot(world["show_and_sells"], OTHER_EVENT) is not None
    assert _admin_answer()["slots"] == [], "this event's board is still empty"


def test_ver_01_a_slot_write_holding_a_stale_event_version_writes_nothing(
    world: Dict[str, Any],
) -> None:
    """VER-01 on the event: the version the caller names must be the version it read."""
    message = _refusal(_upsert(version=2), "CONFLICT")
    assert "event changed since you read it" in message, message
    assert _refusal(_upsert(slot_id="slot-1", slot_version=1), "NOT_FOUND"), (
        "the event's guard is checked before the slot row is read, so a matching event "
        "version and an unknown slot answer the same thing an unknown event does"
    )

    assert _slot_rows(world["show_and_sells"]) == []
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 1


def test_ver_01_a_slot_edit_holding_a_stale_slot_version_writes_nothing(
    world: Dict[str, Any],
) -> None:
    """VER-01 on the slot: ``expectedSlotVersion`` is required on an update and must match."""
    created = _ok(_upsert(key="create-1"))
    slot_id = created["slotId"]

    message = _refusal(_upsert(slot_id=slot_id, slot_version=0, version=2), "CONFLICT")
    assert "slot changed since you read it" in message, message

    stored = _stored_slot(world["show_and_sells"], slot_id=slot_id)
    assert stored is not None and stored[ssm.VERSION_ATTRIBUTE] == 1
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 2, "the create's bump is all the event moved"


def test_two_slot_edits_planned_from_one_read_commit_one_at_a_time(world: Dict[str, Any]) -> None:
    """SS-API-01 for the slot board: both writers read version 1, one of them writes.

    The event version bump rides every slot write, so the slot board has one
    serialization point and two admins cannot each believe they set the board.
    """
    first = _ok(_upsert(key="admin-a"))
    second = assert_is_error(_upsert(slot_id=first["slotId"], slot_version=1, capacity=9, key="admin-b"), "CONFLICT")
    assert "event changed since you read it" in str(second.get("message") or "")

    assert len(_slot_rows(world["show_and_sells"])) == 1
    assert _stored_slot(world["show_and_sells"], slot_id=first["slotId"]) is not None


def test_an_update_must_name_the_slot_version_it_read(world: Dict[str, Any]) -> None:
    """§3.3.2: ``expectedSlotVersion`` is required on an update, and means nothing on a create.

    A ``slotId`` with no version is an edit whose number is being guessed, which is what
    VER-01 refuses; a version with no ``slotId`` is a number for a row the request never
    named.
    """
    _seed_slot(world["show_and_sells"])

    missing = assert_is_error(_upsert(slot_id="slot-1"), "INVALID_INPUT")
    assert "slotVersion" in str(missing.get("message") or "")
    assert_is_error(_upsert(slot_version=1), "INVALID_INPUT")
    assert_is_error(_upsert(slot_version={"expectedVersion": "two"}), "INVALID_INPUT")
    assert _stored_slot(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 1


def test_a_slot_write_requires_its_idempotency_and_version_envelopes(world: Dict[str, Any]) -> None:
    """The mutation contract's own envelopes are required, not inferred."""
    assert_is_error(_upsert(key=None), "INVALID_INPUT")
    payload = {"showAndSellId": EVENT, "startAt": FIRST_START, "endAt": FIRST_END, "capacity": 4, **_idem("k")}
    assert_is_error(_call(UPSERT_SLOT_FIELD, "Avery", mutation=payload), "INVALID_INPUT")
    assert _slot_rows(world["show_and_sells"]) == []


def test_slot_m_01_03_a_retry_replays_the_slot_and_writes_nothing_more(world: Dict[str, Any]) -> None:
    """IDEM: the same key and content returns the first answer, with no second row."""
    first = _ok(_upsert(key="create-1"))
    again = _ok(_upsert(key="create-1"))
    assert again == first, "a replay answers the original slot, not a fresh read of a moved board"

    assert len(_slot_rows(world["show_and_sells"])) == 1
    assert len(_marker_rows(world["show_and_sells"])) == 1, "the retry wrote no second marker"
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 2

    mismatch = assert_is_error(_upsert(key="create-1", capacity=9), "INVALID_INPUT")
    assert "idempotencyKey" in str(mismatch.get("message") or "")
    assert len(_slot_rows(world["show_and_sells"])) == 1


def test_a_retry_of_an_edited_slot_replays_the_edited_row(world: Dict[str, Any]) -> None:
    """The replay reads the stored row, so the retried edit answers capacity 6, not capacity 4."""
    created = _ok(_upsert(key="create-1"))
    edited = _ok(_upsert(slot_id=created["slotId"], slot_version=1, capacity=6, version=2, key="edit-1"))
    again = _ok(_upsert(slot_id=created["slotId"], slot_version=1, capacity=6, version=2, key="edit-1"))
    assert again == edited
    assert again["capacity"] == 6
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 3


def test_slots_stop_being_writable_when_the_event_stops_being_scheduled(world: Dict[str, Any]) -> None:
    """§3.3 allows slot writes in SCHEDULED only — stricter than §3.5's editable matrix.

    Once the event has started its slots are facts the Scouts already worked against, and a
    reopened event's edits are finalization drafts, not the shift board. Every other state
    is refused, on create and on delete alike, and the state guard rides the write too, so
    a cancellation between this read and this commit cancels the plan.
    """
    _seed_slot(world["show_and_sells"])

    _ok(_upsert(slot_id="slot-1", slot_version=1, capacity=9, key="scheduled"))

    for state in (ssm.STATUS_CANCELLED, ssm.STATUS_FINALIZED, ssm.STATUS_REOPENED):
        event_id = _seed_event(world["show_and_sells"], event_id=f"SSE#{state.lower()}", status=state)
        message = _refusal(_upsert(event_id=event_id, key=f"state-{state}"), "CONFLICT")
        assert "only be changed while the event is scheduled" in message, message
        assert _slot_rows(world["show_and_sells"], event_id) == [], f"a {state} event gains no slot"

    started = _seed_event(world["show_and_sells"], event_id="SSE#running", start_at=_shift(-2), end_at=_shift(2))
    assert _refusal(_upsert(event_id=started, key="state-running"), "CONFLICT"), (
        "ACTIVE is a clock state, not a stored one"
    )
    ended = _seed_event(world["show_and_sells"], event_id="SSE#over", start_at=_shift(-4), end_at=_shift(-1))
    assert_is_error(_delete(event_id=ended, key="state-over-delete"), "CONFLICT")

    assert len(_slot_rows(world["show_and_sells"])) == 1, "the board on the SCHEDULED event is the only one written"


# --- SLOT-M-02-01: deleting an unused slot by parent and id -----------------------


def test_slot_m_02_01_an_admin_deletes_an_unused_slot_by_parent_and_id(world: Dict[str, Any]) -> None:
    """SLOT-M-02-01: one atomic write — the row gone, the event version bumped, marker included."""
    created = _ok(_upsert(key="create-1"))
    slot_id = created["slotId"]

    assert _delete(slot_id=slot_id, version=2) is True

    assert _stored_slot(world["show_and_sells"], slot_id=slot_id) is None
    assert _slot_rows(world["show_and_sells"]) == []
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 3, "the board's version moved with the delete"
    assert len(_marker_rows(world["show_and_sells"])) == 2, "each mutation carries its own marker"
    assert _admin_answer()["slots"] == [], "the administrative read answers the board that exists"


def test_a_deleted_slot_frees_a_place_on_a_full_board(world: Dict[str, Any]) -> None:
    """The 20-slot cap counts rows that exist, so a deletion makes room for the next create."""
    for index in range(ssm.MAX_SLOTS_PER_EVENT):
        offset = 0.5 + index * 0.25
        answer = _ok(_upsert(start_at=_at(offset), end_at=_at(offset + 0.25), key=f"fill-{index}", version=index + 1))
        if index == 0:
            spare = answer["slotId"]
    assert len(_slot_rows(world["show_and_sells"])) == ssm.MAX_SLOTS_PER_EVENT

    _delete(slot_id=spare, version=ssm.MAX_SLOTS_PER_EVENT + 1)
    assert len(_slot_rows(world["show_and_sells"])) == ssm.MAX_SLOTS_PER_EVENT - 1

    _ok(_upsert(start_at=_at(11.5), end_at=EVENT_END, key="refilled", version=ssm.MAX_SLOTS_PER_EVENT + 2))
    assert len(_slot_rows(world["show_and_sells"])) == ssm.MAX_SLOTS_PER_EVENT


def test_a_delete_needs_no_slot_version_and_moves_no_other_row(world: Dict[str, Any]) -> None:
    """The caller's number is the event's; the slot's own version comes from this read.

    A deletion names the row by its key, so asking for a slot version too would make the
    screen hold two numbers for one save; the row's version still conditions the write,
    taken from the consistent read this request made.
    """
    created = _ok(_upsert(key="create-1"))
    _seed_slot(world["show_and_sells"], slot_id="slot-2", start_at=_at(4), end_at=_at(6), version=4)

    assert _delete(slot_id=created["slotId"], version=2) is True
    kept = _stored_slot(world["show_and_sells"], slot_id="slot-2")
    assert kept is not None and kept[ssm.VERSION_ATTRIBUTE] == 4, "the other slot row is not this delete's to move"
    assert [row[ssm.SLOT_ID_ATTRIBUTE] for row in _slot_rows(world["show_and_sells"])] == ["slot-2"]


# --- SLOT-M-02-02: a held slot is not deleted, and nobody is cancelled -----------


def test_slot_m_02_02_a_slot_holding_an_active_signup_is_not_deleted(world: Dict[str, Any]) -> None:
    """SLOT-M-02-02: a deletion never silently cancels a participant.

    A signup is a Scout's place in a slot, and cancelling it is its own mutation with its
    own audit and its own commitment release (§3.4). The row, the counter, the signup and
    the event version all stay exactly as they were, and no marker is left behind.
    """
    _signed_up_board(world, ("slot-1", _at(1), _at(3)), personas=("Devon", "Emery"))

    message = _refusal(_delete(), "CONFLICT")
    assert "This slot has 2 active signup(s)" in message, message

    stored = _stored_slot(world["show_and_sells"])
    assert stored is not None
    assert stored[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE] == 2 and stored[ssm.VERSION_ATTRIBUTE] == 1
    signups = [
        row for row in _partition(world["show_and_sells"], EVENT) if row.get("entityType") == ssm.ENTITY_TYPE_SIGNUP
    ]
    assert len(signups) == 2 and all(row[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_ACTIVE for row in signups)
    for persona in ("Devon", "Emery"):
        assert len(_commitment_rows(world["unit_campaigns"], persona=persona)) == 1, "nobody's commitment was released"
        assert _guard_version(world["unit_campaigns"], persona=persona) == 3, "and no guard moved"
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 1
    assert _marker_rows(world["show_and_sells"]) == []


def test_a_cancelled_signup_is_history_and_does_not_hold_the_slot(world: Dict[str, Any]) -> None:
    """A CANCELLED signup is a history row (§5.13), not a participant, so the slot is deletable."""
    _seed_slot(world["show_and_sells"], active=0)
    _seed_signup(world["show_and_sells"], status=ssm.SIGNUP_CANCELLED)

    assert _delete() is True
    assert _stored_slot(world["show_and_sells"]) is None
    history = [
        row for row in _partition(world["show_and_sells"], EVENT) if row.get("entityType") == ssm.ENTITY_TYPE_SIGNUP
    ]
    assert len(history) == 1, "the signup history is not this delete's to remove"


def test_the_zero_counter_condition_rides_the_delete_when_the_counter_moved_after_the_read(
    world: Dict[str, Any],
) -> None:
    """``#activeSignupCount = :zero`` is the same promise, enforced on the row at commit.

    The read-side refusal counts the signup rows this request read; the condition counts the
    counter at commit time. A signup that lands in that window has moved both, and the
    condition is the only thing that can see it — so the test writes the state that window
    leaves behind (a counter of one, and no signup row this request read) and proves the
    plan is cancelled whole: the slot row stays, the event version stays, and no marker is
    left behind for a deletion that never happened.
    """
    _seed_slot(world["show_and_sells"], active=1)

    message = _refusal(_delete(), "CONFLICT")
    assert "changed underneath this request" in message, message

    stored = _stored_slot(world["show_and_sells"])
    assert stored is not None and stored[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE] == 1, "the slot was not deleted"
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 1, "and the event version did not move"
    assert _marker_rows(world["show_and_sells"]) == []


def test_ver_01_a_stale_event_version_deletes_nothing(world: Dict[str, Any]) -> None:
    """VER-01: the delete's version must be the event's current one, or nothing moves."""
    created = _ok(_upsert(key="create-1"))

    message = _refusal(_delete(slot_id=created["slotId"], version=1), "CONFLICT")
    assert "event changed since you read it" in message, message

    assert _stored_slot(world["show_and_sells"], slot_id=created["slotId"]) is not None
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 2


def test_idem_a_delete_retry_replays_true_and_deletes_nothing_more(world: Dict[str, Any]) -> None:
    """IDEM: an identical retry of a completed deletion answers ``true`` with no second effect."""
    _ok(_upsert(key="create-1"))
    _seed_slot(world["show_and_sells"], slot_id="slot-2", start_at=_at(4), end_at=_at(6))

    assert _delete(slot_id="slot-2", key="delete-1", version=2) is True
    assert _delete(slot_id="slot-2", key="delete-1", version=2) is True, (
        "the retry replays, it does not re-check the version"
    )

    assert len(_marker_rows(world["show_and_sells"])) == 2, "the retry wrote no second marker"
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 3

    mismatch = assert_is_error(_delete(slot_id="slot-2", key="delete-1", version=9), "INVALID_INPUT")
    assert "idempotencyKey" in str(mismatch.get("message") or "")


def test_a_delete_names_the_parent_the_slot_and_its_envelopes(world: Dict[str, Any]) -> None:
    """§3.3.3: ``showAndSellId + slotId + expectedVersion + idempotencyKey``, each required."""
    created = _ok(_upsert(key="create-1"))

    assert_is_error(_delete(slot_id=None), "INVALID_INPUT")
    assert_is_error(_delete(key=None), "INVALID_INPUT")
    payload = {"showAndSellId": EVENT, "slotId": "slot-1", **_idem("k")}
    assert_is_error(_call(DELETE_SLOT_FIELD, "Avery", mutation=payload), "INVALID_INPUT")

    assert _stored_slot(world["show_and_sells"], slot_id=created["slotId"]) is not None
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 2


def test_a_board_read_after_a_write_answers_the_slots_that_exist(world: Dict[str, Any]) -> None:
    """The administrative event read is the board a Kernel acts on, so it answers these rows.

    ``showAndSell`` carries the slots soonest-first, with the counter and version §3.3
    conditions on, which is what lets the screen send the right ``expectedSlotVersion`` on
    the next edit rather than guessing one.
    """
    morning = _ok(_upsert(start_at=_at(1), end_at=_at(3), key="morning"))
    afternoon = _ok(_upsert(start_at=_at(5), end_at=_at(7), capacity=2, key="afternoon", version=2))

    board = _admin_answer()["slots"]
    assert [row["slotId"] for row in board] == [morning["slotId"], afternoon["slotId"]]
    assert [row["startAt"] for row in board] == [_at(1), _at(5)]
    assert {row["capacity"] for row in board} == {4, 2}
    assert all(row["version"] == 1 and row[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE] == 0 for row in board)

    _delete(slot_id=afternoon["slotId"], version=3)
    assert [row["slotId"] for row in _admin_answer()["slots"]] == [morning["slotId"]]


def test_a_version_number_that_is_not_a_number_is_refused_as_input(world: Dict[str, Any]) -> None:
    """The version envelope is validated before any read: a non-integer never reaches a condition.

    ``Decimal("NaN")`` is the one value that is a number, passes the type check, and has no
    integer form, so the arithmetic refusal is a real path rather than dead code.
    """
    for value in (True, {"x": 1}, [], "two", Decimal("NaN")):
        assert_is_error(_upsert(version=value), "INVALID_INPUT")
    assert _ok(_upsert(version="1", key="numeric-string"))["version"] == 1
    assert _stored(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE] == 2
