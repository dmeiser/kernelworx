"""Wave 4.4 — signups, confirmed work, and the reads over them (§3.4.1-§3.4.5).

Resolver-level cases for ``SIGN-M-01``, ``SIGN-M-02`` and ``SIGN-M-03``, with ``EVT-Q-05``,
``INV-Q-06``, ``AUTH-U``, ``AUTH-P``, ``PAGE-01``, ``DATA-Q-05`` and ``AUTH-P-02/05`` from the
API contract. Everything runs through ``handle_unit_operation`` against moto, so what is
proved is the committed aggregate rather than the plan: the signup row, its cross-campaign
commitment projection, the Scout's commitment guard, the slot counter, the roster row's
condition and the event version either all land or none of them do — and the denial the
browser sees is the one the resolver actually raised. A refusal is asserted on its sentence
as well as its code, because every guard here answers ``CONFLICT`` and ``AppError.details``
does not survive the resolver boundary.

Event, slot and commitment instants are measured from the real clock, because the resolver
derives ``SCHEDULED``/``ACTIVE``/``ENDED`` from ``utc_now_iso()``. The event window is twelve
hours wide so a 180-minute slot, an adjacent one, and an overlapping one all fit inside it
without arithmetic in the test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional

import pytest

from src.handlers.unit_operations import (
    CANCEL_SIGNUP_FIELD,
    CONFIRM_WORK_FIELD,
    MY_COMMITMENTS_FIELD,
    SHOW_AND_SELL_SIGNUPS_FIELD,
    SIGNUP_CALENDAR_FIELD,
    SIGNUP_SCOUT_FIELD,
    handle_unit_operation,
)
from src.utils import show_and_sell_models as ssm
from src.utils import unit_campaign_models as ucm
from tests.unit.show_sell_fixtures import (
    PACK_3149,
    PACK_3149_FALL,
    PROFILES,
    account_id,
    assert_is_error,
    generated_display_name,
    seed_show_sell_fixtures,
    unit_campaign_membership_item,
    unit_operation_event,
)

CAMPAIGN = PACK_3149_FALL
OTHER_UNIT = "unit-crew-529-denver"
OTHER_CAMPAIGN = "uc-crew-529-spring-2027"
EVENT = "SSE#signup-board"
OTHER_EVENT = "SSE#other-signup-board"
LOCATION = "Aurora armory lot"
ADDRESS = "4410 E 30th Ave, Aurora, CO"

SIGNUP_FIELDS = {
    "showAndSellId",
    "slotId",
    "startAt",
    "endAt",
    "status",
    "actualMinutes",
    "signupVersion",
}


def _shift(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


#: The board's event: three days ahead of the clock, so still ``SCHEDULED``, and twelve
#: hours wide — enough for a 180-minute slot, an adjacent one, and an overlapping one.
EVENT_START, EVENT_END = _shift(72), _shift(84)


def _at(offset: float) -> str:
    """An instant inside the board's event window, measured from its own start."""
    return (datetime.fromisoformat(EVENT_START) + timedelta(hours=offset)).isoformat()


#: The slot every test starts with: one hour into a twelve-hour event, two hours wide, so
#: a 180-minute slot, an adjacent one and an overlapping one all still fit beside it.
FIRST_START, FIRST_END = _at(1), _at(3)

#: Adjacent to the first slot (sharing an endpoint, never an instant), and overlapping it.
ADJACENT_START, ADJACENT_END = FIRST_END, _at(4)
OVERLAP_START, OVERLAP_END = _at(2), _at(4)


def _inside(start: str, end: str, lead: int = 15, trail: int = 15) -> tuple[str, str]:
    """One interval set comfortably inside an event's own window.

    §5.12 refuses a slot that starts before its event starts or ends after it ends, so a test
    that wants an event that has already run places its slots inside that window rather than
    pretending the bound does not hold.
    """
    first = (datetime.fromisoformat(start) + timedelta(minutes=lead)).isoformat()
    last = (datetime.fromisoformat(end) - timedelta(minutes=trail)).isoformat()
    return first, last


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


def _refusal(payload: Any, code: str) -> str:
    """The sentence one refusal answered, so a test can name the guard it proved."""
    return str(assert_is_error(payload, code).get("message") or "")


def _idem(key: Optional[str]) -> Dict[str, Any]:
    return {"idempotency": {"idempotencyKey": key}}


def _version(expected: int) -> Dict[str, Any]:
    return {"version": {"expectedVersion": expected}}


def _signup(
    caller: Optional[str] = "Avery",
    *,
    event_id: str = EVENT,
    slot_id: Any = "slot-1",
    persona: str = "Devon",
    profile_id: Optional[str] = None,
    campaign_id: Any = ...,
    key: Optional[str] = "signup-1",
    **extras: Any,
) -> Any:
    payload: Dict[str, Any] = {
        "showAndSellId": event_id,
        "slotId": slot_id,
        "profileId": profile_id if profile_id is not None else _profile(persona),
        "idempotency": {"idempotencyKey": key},
    }
    if campaign_id is not ...:
        payload["campaignId"] = campaign_id
    else:
        payload["campaignId"] = _scout_campaign(persona)
    payload.update(extras)
    return _call(SIGNUP_SCOUT_FIELD, caller, mutation=payload)


def _cancel(
    caller: Optional[str] = "Avery",
    *,
    event_id: str = EVENT,
    slot_id: Any = "slot-1",
    persona: str = "Devon",
    profile_id: Optional[str] = None,
    version: int = 1,
    key: Optional[str] = "cancel-1",
) -> Any:
    payload: Dict[str, Any] = {
        "showAndSellId": event_id,
        "slotId": slot_id,
        "profileId": profile_id if profile_id is not None else _profile(persona),
        **_version(version),
        **_idem(key),
    }
    return _call(CANCEL_SIGNUP_FIELD, caller, mutation=payload)


def _confirm(
    caller: Optional[str] = "Avery",
    *,
    event_id: str = EVENT,
    work: Any = None,
    version: int = 1,
    key: Optional[str] = "work-1",
) -> Any:
    payload: Dict[str, Any] = {
        "showAndSellId": event_id,
        "work": work
        if work is not None
        else [{"slotId": "slot-1", "profileId": _profile("Devon"), "actualMinutes": 75}],
        **_version(version),
        **_idem(key),
    }
    return _call(CONFIRM_WORK_FIELD, caller, mutation=payload)


def _signup_rows(caller: Optional[str] = "Avery", *, event_id: str = EVENT, **arguments: Any) -> Any:
    return _call(SHOW_AND_SELL_SIGNUPS_FIELD, caller, arguments={"showAndSellId": event_id, **arguments})


def _commitments(caller: Optional[str] = "Devon", **arguments: Any) -> Any:
    return _call(
        MY_COMMITMENTS_FIELD, caller, arguments={"profileId": _profile(arguments.pop("persona", "Devon")), **arguments}
    )


def _calendar(
    caller: Optional[str] = "Avery",
    *,
    event_id: str = EVENT,
    slot_id: Any = "slot-1",
    persona: str = "Devon",
    profile_id: Optional[str] = None,
) -> Any:
    return _call(
        SIGNUP_CALENDAR_FIELD,
        caller,
        arguments={
            "showAndSellId": event_id,
            "slotId": slot_id,
            "profileId": profile_id if profile_id is not None else _profile(persona),
        },
    )


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
    item = ssm.build_show_and_sell_item(
        show_and_sell_id=event_id,
        unit_id=unit_id,
        unit_campaign_id=unit_campaign_id,
        location_name=LOCATION,
        address=ADDRESS,
        start_at=start_at,
        end_at=end_at,
        created_by_account_id="ACCOUNT#avery-fixture",
        now_iso=start_at,
        version=version,
    )
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

    The bound is checked against the event row that is actually stored, which is what §5.12's
    invariant means: a slot outside its own event's window is refused here rather than seeded,
    so a test cannot prove anything about a board that could not exist.
    """
    stored = show_and_sells_table.get_item(Key=ssm.event_metadata_key(event_id)).get("Item")
    item = ssm.build_show_and_sell_slot_item(
        event=dict(stored) if stored else _event_item(event_id),
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
    minutes: int = 0,
    signed_up_by: Optional[str] = None,
    confirmed_by: Optional[str] = None,
    bump_slot: bool = True,
    **stored_overrides: Any,
) -> Dict[str, Any]:
    """One signup row, plus the slot counter that a held place is supposed to move.

    ``bump_slot`` keeps the fixture honest by default: §5.12's ``activeSignupCount`` is the
    projection capacity and the cancellation arithmetic are decided against, so an ACTIVE row
    that is not counted is a drifted board. A test that wants the drift asks for it.
    """
    profile = profile_id or _profile(persona)
    stored_event = show_and_sells_table.get_item(Key=ssm.event_metadata_key(event_id)).get("Item")
    item = ssm.build_show_and_sell_signup_item(
        event=dict(stored_event) if stored_event else _event_item(event_id),
        slot_id=slot_id,
        profile_id=profile,
        campaign_id=campaign_id or _scout_campaign(persona),
        signed_up_by_account_id=signed_up_by or f"ACCOUNT#{str(profile).lower()}",
        now_iso=EVENT_START,
        status=status,
        version=version,
        actual_minutes=minutes,
        confirmed_by_account_id=confirmed_by,
        confirmed_at=EVENT_START if confirmed_by else None,
    )
    item.update(stored_overrides)
    show_and_sells_table.put_item(Item=item)
    if bump_slot and status == ssm.SIGNUP_ACTIVE:
        slot = show_and_sells_table.get_item(Key=ssm.slot_key(event_id, slot_id)).get("Item")
        if slot is not None:
            show_and_sells_table.update_item(
                Key=ssm.slot_key(event_id, slot_id),
                UpdateExpression="SET #count = #count + :one",
                ExpressionAttributeNames={"#count": ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE},
                ExpressionAttributeValues={":one": 1},
            )
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


def _seed_membership(
    unit_campaigns_table: Any,
    *,
    persona: str = "Emery",
    unit_campaign_id: str = CAMPAIGN,
    status: str = "REMOVED",
    version: int = 2,
) -> Dict[str, Any]:
    item = unit_campaign_membership_item(
        unit_campaign_id,
        PACK_3149,
        _scout_campaign(persona),
        _profile(persona),
        status=status,
        joined_by=persona,
        version=version,
    )
    unit_campaigns_table.put_item(Item=item)
    return item


def _board(world: Dict[str, Any], *slots: tuple[str, str, str], capacity: int = 4) -> None:
    """Extra slots on the board's event, by id and interval."""
    for slot_id, start_at, end_at in slots:
        _seed_slot(world["show_and_sells"], slot_id=slot_id, start_at=start_at, end_at=end_at, capacity=capacity)


def _crowd(world: Dict[str, Any], count: int, *, minutes: int = 10, slot_id: str = "slot-9") -> List[str]:
    """``count`` ACTIVE signups for synthetic Scouts, each carrying confirmed work.

    The §8.10 preflight counts participants, not identities, and a real roster of forty
    Scouts is the same forty rows to the estimate — so the budget tests seed the rows the
    arithmetic reads rather than forty persona fixtures.
    """
    _seed_slot(world["show_and_sells"], slot_id=slot_id, start_at=_at(4), end_at=_at(6), capacity=100)
    profiles = []
    for index in range(count):
        profile = f"PROFILE#prof-crowd-{index:03d}"
        _seed_signup(
            world["show_and_sells"],
            slot_id=slot_id,
            profile_id=profile,
            campaign_id=f"CAMPAIGN#camp-crowd-{index:03d}",
            minutes=minutes,
        )
        profiles.append(profile)
    return profiles


# --- Storage reads ---------------------------------------------------------------


def _stored_event(show_and_sells_table: Any, event_id: str = EVENT) -> Dict[str, Any]:
    return dict(show_and_sells_table.get_item(Key=ssm.event_metadata_key(event_id))["Item"])


def _stored_slot(show_and_sells_table: Any, event_id: str = EVENT, slot_id: str = "slot-1") -> Optional[Dict[str, Any]]:
    found = show_and_sells_table.get_item(Key=ssm.slot_key(event_id, slot_id))
    item = found.get("Item")
    return dict(item) if item else None


def _stored_signup(
    show_and_sells_table: Any,
    event_id: str = EVENT,
    slot_id: str = "slot-1",
    *,
    persona: str = "Devon",
    profile_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    profile = profile_id or _profile(persona)
    found = show_and_sells_table.get_item(
        Key={"pk": ssm.show_and_sell_pk(event_id), "sk": ssm.signup_sk(slot_id, profile)}
    )
    item = found.get("Item")
    return dict(item) if item else None


def _signup_rows_stored(show_and_sells_table: Any, event_id: str = EVENT) -> List[Dict[str, Any]]:
    return [
        row for row in _partition(show_and_sells_table, event_id) if row.get("entityType") == ssm.ENTITY_TYPE_SIGNUP
    ]


def _partition(show_and_sells_table: Any, event_id: str) -> List[Dict[str, Any]]:
    return list(
        show_and_sells_table.query(
            KeyConditionExpression="#pk = :pk",
            ExpressionAttributeNames={"#pk": "pk"},
            ExpressionAttributeValues={":pk": ssm.show_and_sell_pk(event_id)},
        )["Items"]
    )


def _commitment_rows(
    unit_campaigns_table: Any, *, persona: str = "Devon", profile_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    profile = profile_id or _profile(persona)
    return [
        dict(row)
        for row in unit_campaigns_table.query(
            KeyConditionExpression="#pk = :pk AND begins_with(#sk, :prefix)",
            ExpressionAttributeNames={"#pk": "pk", "#sk": "sk"},
            ExpressionAttributeValues={":pk": ssm.commitment_pk(profile), ":prefix": "COMMITMENT#"},
        )["Items"]
        if str(row.get("sk", "")) != ssm.COMMITMENT_GUARD_SK
    ]


def _guard_version(
    unit_campaigns_table: Any, *, persona: str = "Devon", profile_id: Optional[str] = None
) -> Optional[int]:
    profile = profile_id or _profile(persona)
    found = unit_campaigns_table.get_item(Key=ssm.commitment_guard_key(profile))
    item = found.get("Item")
    return None if not item else int(item[ssm.COMMITMENT_VERSION_ATTRIBUTE])


def _marker_rows(show_and_sells_table: Any) -> List[Dict[str, Any]]:
    return [row for row in show_and_sells_table.scan()["Items"] if str(row.get("sk", "")).startswith("IDEM#")]


def _stranded_marker(show_and_sells_table: Any) -> None:
    """Leave one committed marker as a crashed attempt leaves it: in flight, no stored answer.

    ``execute`` flips the marker to COMPLETED with the answer after the transaction lands, and a
    process that dies in that gap leaves a marker that can only be answered from the row its
    ``resultId`` names. That is the one state the resolver's loader is for, so the tests exercise
    it by hand rather than pretending it cannot happen.
    """
    marker = dict(_marker_rows(show_and_sells_table)[0])
    show_and_sells_table.put_item(
        Item={key: value for key, value in marker.items() if key != "resultPayload"} | {"status": "IN_FLIGHT"}
    )


def _nothing_written(
    world: Dict[str, Any], *, persona: str = "Devon", slot_id: str = "slot-1", event_id: str = EVENT
) -> None:
    """A refusal wrote no signup, no projection for this event, no guard, and no marker (§8.9).

    The projection filter is the event, not the Scout: a test may legitimately seed a
    commitment the Scout holds in another Unit Campaign — that is the row the overlap guard is
    refusing on — and the point is that this refused write added nothing to it.
    """
    assert _stored_signup(world["show_and_sells"], event_id, slot_id, persona=persona) is None
    projections = [
        row
        for row in _commitment_rows(world["unit_campaigns"], persona=persona)
        if row.get(ssm.SHOW_AND_SELL_ID_ATTRIBUTE) == event_id
    ]
    assert projections == []
    assert _guard_version(world["unit_campaigns"], persona=persona) is None
    assert _marker_rows(world["show_and_sells"]) == []


# --- Frozen boards: one read while storage moves on (the race half) ---------------


def _frozen_slot(monkeypatch: pytest.MonkeyPatch, world: Dict[str, Any], *, slot_id: str = "slot-1") -> None:
    """Hand the resolver the slot row it read before a competing signup committed.

    Moto cannot interleave two transactions, so the race is proved the way §8.3 says it is
    settled: the loser's plan carries the numbers it read, and DynamoDB refuses them. The
    read is frozen and storage is moved by hand, which is exactly the state the loser's
    condition sees.
    """
    stale = dict(ssm.load_slot_or_not_found(EVENT, slot_id))

    def fake(show_and_sell_id: str, wanted: str) -> Optional[Dict[str, Any]]:
        if wanted == slot_id:
            return dict(stale)
        return None

    monkeypatch.setattr(ssm, "read_slot", fake)


def _frozen_membership(monkeypatch: pytest.MonkeyPatch, membership: Mapping) -> None:
    """Hand the resolver the ACTIVE roster row it read before §1.4.3's removal committed."""
    real = ucm.read_membership

    def fake(unit_campaign_id: str, profile_id: str) -> Optional[Dict[str, Any]]:
        if profile_id == membership["profileId"]:
            return dict(membership)
        return real(unit_campaign_id, profile_id)

    monkeypatch.setattr(ucm, "read_membership", fake)


# --- Fixture --------------------------------------------------------------------


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
    """The Stage 1 persona world plus the two tables a signup write touches."""
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
    _seed_slot(show_and_sells_table)
    return {"show_and_sells": show_and_sells_table, "unit_campaigns": unit_campaigns_table}


# --- SIGN-M-01-01: the aggregate commit -----------------------------------------


def test_signup_writes_the_whole_aggregate_and_answers_the_participant_shape(world: Dict[str, Any]) -> None:
    """SIGN-M-01-01, AUTH-U-01: a Kernel signs a roster Scout into a slot of a scheduled event."""
    answer = _ok(_signup("Avery"))
    assert set(answer) == SIGNUP_FIELDS, "the participant answer is the whole allowlist (SEC-04)"
    assert answer == {
        "showAndSellId": EVENT,
        "slotId": "slot-1",
        "startAt": FIRST_START,
        "endAt": FIRST_END,
        "status": ssm.SIGNUP_ACTIVE,
        "actualMinutes": 0,
        "signupVersion": 1,
    }

    signup = _stored_signup(world["show_and_sells"])
    assert signup is not None and signup[ssm.CAMPAIGN_ID_ATTRIBUTE] == _scout_campaign("Devon")
    assert signup[ssm.SIGNED_UP_BY_ATTRIBUTE] == account_id("Avery"), "the audit names who placed the place"

    projections = _commitment_rows(world["unit_campaigns"])
    assert len(projections) == 1 and projections[0][ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_ACTIVE
    assert projections[0][ssm.START_AT_ATTRIBUTE] == FIRST_START and projections[0][ssm.END_AT_ATTRIBUTE] == FIRST_END
    assert projections[0][ssm.VERSION_ATTRIBUTE] == signup[ssm.VERSION_ATTRIBUTE], (
        "§5.13: the projection's version matches its source signup's"
    )

    slot = _stored_slot(world["show_and_sells"])
    assert slot is not None and int(slot[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE]) == 1
    assert int(slot[ssm.VERSION_ATTRIBUTE]) == 2, "the slot row moved with its counter"
    assert _guard_version(world["unit_campaigns"]) == 1, "the first place a Scout holds writes the guard"
    assert int(_stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE]) == 2, (
        "§8.3: the event version moves with its participant set"
    )
    assert len(_marker_rows(world["show_and_sells"])) == 1


def test_a_write_share_on_the_scout_profile_may_sign_the_scout_up(world: Dict[str, Any]) -> None:
    """AUTH-P-05: Owner/WRITE for the Scout is enough — no Unit grant needed."""
    answer = _ok(_signup("Taylor", key="signup-write"))
    assert answer["status"] == ssm.SIGNUP_ACTIVE
    assert _stored_signup(world["show_and_sells"]) is not None


def test_the_first_signup_ever_creates_the_guard_and_a_later_one_bumps_it(world: Dict[str, Any]) -> None:
    """SIGN-M-01-02: the guard is written once and pinned thereafter (§5.13)."""
    _ok(_signup("Avery", key="signup-first"))
    _seed_slot(world["show_and_sells"], slot_id="slot-2", start_at=ADJACENT_START, end_at=ADJACENT_END)
    _ok(_signup("Avery", slot_id="slot-2", key="signup-second"))
    assert _guard_version(world["unit_campaigns"]) == 2
    assert len(_commitment_rows(world["unit_campaigns"])) == 2, "adjacent slots are not an overlap (SLOT-03)"


def test_a_signup_replays_once_and_the_retry_answers_the_first_commit(world: Dict[str, Any]) -> None:
    """IDEM: the completed attempt moved the counter, the version and the guard."""
    first = _ok(_signup("Avery"))
    again = _ok(_signup("Avery"))
    assert again == first, "a replay answers the original row, not a second CONFLICT"
    assert int(_stored_slot(world["show_and_sells"])[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE]) == 1
    assert _guard_version(world["unit_campaigns"]) == 1
    assert len(_commitment_rows(world["unit_campaigns"])) == 1


def test_a_replay_answers_the_stored_commit_after_the_row_moves_on(world: Dict[str, Any]) -> None:
    """IDEM: a completed marker replays its own answer, it does not re-read (§8.9).

    The retry of a committed request is not re-decided against state that has moved since —
    which is why the first attempt's answer rides on the marker. Deleting the row afterwards
    is the strongest form of that rule: even a signup that is no longer there answers the place
    it did grant, and the retry invents no write to explain itself.
    """
    first = _ok(_signup("Avery"))
    world["show_and_sells"].delete_item(
        Key={"pk": ssm.show_and_sell_pk(EVENT), "sk": ssm.signup_sk("slot-1", _profile("Devon"))}
    )
    assert _ok(_signup("Avery")) == first
    assert _stored_signup(world["show_and_sells"]) is None, "the replay wrote nothing back"
    assert len(_marker_rows(world["show_and_sells"])) == 1


def test_a_stranded_marker_is_answered_from_the_row_it_named(world: Dict[str, Any]) -> None:
    """The loader is the narrow fallback for a commit whose marker flip never happened (§8.9)."""
    first = _ok(_signup("Avery"))
    _stranded_marker(world["show_and_sells"])
    assert _ok(_signup("Avery")) == first, "the fallback reads the committed row, it does not re-run the write"
    assert int(_stored_slot(world["show_and_sells"])[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE]) == 1


def test_a_stranded_marker_for_a_row_that_is_gone_answers_not_found(world: Dict[str, Any]) -> None:
    """And when the row it pointed at is gone too, the honest answer is NOT_FOUND, not a fresh place."""
    _ok(_signup("Avery"))
    _stranded_marker(world["show_and_sells"])
    world["show_and_sells"].delete_item(
        Key={"pk": ssm.show_and_sell_pk(EVENT), "sk": ssm.signup_sk("slot-1", _profile("Devon"))}
    )
    _refusal(_signup("Avery"), "NOT_FOUND")
    assert _stored_signup(world["show_and_sells"]) is None, "the retry invented no place"


# --- SIGN-M-01-02/03: duplicate, capacity, overlap, membership, budget -----------


def test_a_duplicate_signup_is_refused_and_writes_nothing(world: Dict[str, Any]) -> None:
    """SIGN-M-01-02, SLOT-02: one ACTIVE place per Scout per slot."""
    _ok(_signup("Avery"))
    message = _refusal(_signup("Avery", key="signup-again"), "CONFLICT")
    assert "already holds a place" in message
    assert int(_stored_slot(world["show_and_sells"])[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE]) == 1
    assert len(_commitment_rows(world["unit_campaigns"])) == 1


def test_a_cancelled_place_is_history_and_cannot_be_taken_again(world: Dict[str, Any]) -> None:
    """§9.3: cancellation is terminal, so re-taking the slot is refused, not rewritten."""
    _ok(_signup("Avery"))
    _ok(_cancel("Avery", version=1))
    message = _refusal(_signup("Avery", key="signup-again"), "CONFLICT")
    assert "cancelled signup stays history" in message
    rows = _signup_rows_stored(world["show_and_sells"])
    assert len(rows) == 1 and rows[0][ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_CANCELLED, (
        "the cancelled row is kept as history (§5.13)"
    )
    assert int(_stored_slot(world["show_and_sells"])[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE]) == 0


def test_a_full_slot_is_refused_and_writes_nothing(world: Dict[str, Any]) -> None:
    """SIGN-M-01-02 capacity (AC-13): the last place is the last place."""
    _seed_slot(world["show_and_sells"], capacity=1, active=1)
    _seed_signup(
        world["show_and_sells"],
        profile_id="PROFILE#prof-holder-0001",
        campaign_id="CAMPAIGN#camp-holder-0001",
        bump_slot=False,
    )
    message = _refusal(_signup("Avery"), "CONFLICT")
    assert "is full" in message
    _nothing_written(world)


def test_a_racing_signup_loses_its_whole_plan_on_the_pinned_counter(
    world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-13: pinning the counter, not only the slot version, is what keeps a slot honest."""
    _seed_slot(world["show_and_sells"], capacity=1, active=0)
    _frozen_slot(monkeypatch, world)
    # The winner moved the counter and left the version where the loser read it: the
    # version condition alone would let the loser commit and take a second last place.
    world["show_and_sells"].update_item(
        Key=ssm.slot_key(EVENT, "slot-1"),
        UpdateExpression="SET #count = :one",
        ExpressionAttributeNames={"#count": ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE},
        ExpressionAttributeValues={":one": 1},
    )
    _refusal(_signup("Avery"), "CONFLICT")
    _nothing_written(world)
    slot = _stored_slot(world["show_and_sells"])
    assert slot is not None and int(slot[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE]) == 1, "the winner's count stands"


def test_an_overlapping_commitment_anywhere_refuses_the_signup(world: Dict[str, Any]) -> None:
    """SIGN-M-01-01 (AC-14, INV-Q-06-03): the other Show & Sell is not named to the caller."""
    _seed_slot(world["show_and_sells"], slot_id="slot-2", start_at=OVERLAP_START, end_at=OVERLAP_END)
    _seed_commitment(
        world["unit_campaigns"],
        OTHER_EVENT,
        "slot-x",
        start_at=_at(1.5),
        end_at=_at(2.5),
        unit_campaign_id=OTHER_CAMPAIGN,
    )
    message = _refusal(_signup("Avery", slot_id="slot-2"), "CONFLICT")
    assert "another Show & Sell at these hours" in message
    assert OTHER_EVENT not in message and OTHER_CAMPAIGN not in message, "the refusal names no other tenant"
    _nothing_written(world, slot_id="slot-2")


def test_a_removed_roster_entry_cannot_take_a_new_place(world: Dict[str, Any]) -> None:
    """SIGN-M-01-03: §5.6's removal keeps existing signups and blocks new ones."""
    _seed_membership(world["unit_campaigns"], persona="Emery")
    message = _refusal(_signup("Avery", persona="Emery"), "CONFLICT")
    assert "roster entry is REMOVED" in message
    _nothing_written(world, persona="Emery")


def test_a_membership_race_fails_the_plan_on_the_roster_condition(
    world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.3: the signup conditions on the roster row's version and ACTIVE status."""
    row = _seed_membership(world["unit_campaigns"], persona="Emery", status="ACTIVE", version=1)
    _frozen_membership(monkeypatch, {**row, "status": "ACTIVE", "version": 1})
    world["unit_campaigns"].update_item(
        Key=ucm.membership_key(CAMPAIGN, _profile("Emery")),
        UpdateExpression="SET #status = :gone, #version = :two",
        ExpressionAttributeNames={"#status": "status", "#version": "version"},
        ExpressionAttributeValues={":gone": "REMOVED", ":two": 2},
    )
    _refusal(_signup("Avery", persona="Emery"), "CONFLICT")
    _nothing_written(world, persona="Emery")


def test_a_scout_on_another_unit_campaign_is_not_on_this_roster(world: Dict[str, Any]) -> None:
    """AUTH-U: a Scout of another Unit Campaign is absent here, not forbidden."""
    _refusal(_signup("Avery", persona="Riley"), "NOT_FOUND")


def test_a_roster_row_from_another_scout_campaign_is_refused(world: Dict[str, Any]) -> None:
    """§2.3.1's identity rule on the signup write: the Campaign must be the roster's own."""
    message = _refusal(_signup("Avery", campaign_id="CAMPAIGN#camp-someone-else"), "CONFLICT")
    assert "different Scout Campaign" in message
    _nothing_written(world)


def test_a_signup_the_finalization_budget_can_still_carry_is_allowed(world: Dict[str, Any]) -> None:
    """The §8.10 preflight runs, and the answer is still yes: 28 rows, 29 Scouts, 89 actions."""
    _crowd(world, 28)
    _ok(_signup("Avery", slot_id="slot-9", key="signup-fits"))
    assert _stored_signup(world["show_and_sells"], slot_id="slot-9") is not None


def test_the_finalization_budget_gets_its_preflight_before_anything_is_staged(world: Dict[str, Any]) -> None:
    """SIGN-M-01 budget (§8.10): an event that can no longer finalize in one transaction refuses."""
    _crowd(world, 29)
    message = _refusal(_signup("Avery", slot_id="slot-9", key="signup-over"), "CONFLICT")
    assert "actions to finalize" in message
    assert _stored_signup(world["show_and_sells"], slot_id="slot-9") is None
    assert _marker_rows(world["show_and_sells"]) == []


def test_a_window_that_is_not_scheduled_takes_no_signups(world: Dict[str, Any]) -> None:
    """SIGN-M-01: only a ``SCHEDULED`` event grants places (ACTIVE/ENDED are taken or released)."""
    _seed_event(world["show_and_sells"], "SSE#running", start_at=_shift(-2), end_at=_shift(2))
    _seed_slot(world["show_and_sells"], "SSE#running", slot_id="slot-1", start_at=_shift(-1), end_at=_shift(1))
    message = _refusal(_signup("Avery", event_id="SSE#running"), "CONFLICT")
    assert "signup" in message.lower() or "window" in message.lower()
    assert _stored_signup(world["show_and_sells"], "SSE#running") is None


def test_a_missing_event_or_slot_is_not_found(world: Dict[str, Any]) -> None:
    """NOT_FOUND for the row that is not there, before any state rule is decided."""
    _refusal(_signup("Avery", event_id="SSE#never-seeded"), "NOT_FOUND")
    _refusal(_signup("Avery", slot_id="slot-404"), "NOT_FOUND")


def test_a_caller_with_no_standing_here_is_forbidden(world: Dict[str, Any]) -> None:
    """AUTH-U / AUTH-P: no grant on the Unit and no share on the profile is FORBIDDEN."""
    _refusal(_signup("Emery"), "FORBIDDEN")
    _refusal(_signup("Blake"), "FORBIDDEN")


def test_a_read_only_share_cannot_sign_the_profile_up(world: Dict[str, Any]) -> None:
    """AUTH-P-02: Riley holds READ on Avery's profile, and a place is a write."""
    _refusal(_signup("Riley", persona="Avery", slot_id="slot-1"), "FORBIDDEN")
    _nothing_written(world, persona="Avery")


# --- SIGN-M-02: cancellation -----------------------------------------------------


def test_a_scout_gives_the_place_back_and_everything_moves_with_it(world: Dict[str, Any]) -> None:
    """SIGN-M-02-01: signup, projection, counter, guard and event version in one plan."""
    _ok(_signup("Avery"))
    answer = _ok(_cancel("Taylor", version=1, key="cancel-1"))
    assert answer["status"] == ssm.SIGNUP_CANCELLED and answer["signupVersion"] == 2

    signup = _stored_signup(world["show_and_sells"])
    assert signup is not None and signup[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_CANCELLED
    projections = _commitment_rows(world["unit_campaigns"])
    assert len(projections) == 1 and projections[0][ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_CANCELLED, (
        "the projection is released too, so the Scout is free at those hours again"
    )
    assert projections[0][ssm.VERSION_ATTRIBUTE] == 2
    assert int(_stored_slot(world["show_and_sells"])[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE]) == 0
    assert _guard_version(world["unit_campaigns"]) == 2
    assert int(_stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE]) == 3


def test_cancelling_releases_the_scout_for_another_slot(world: Dict[str, Any]) -> None:
    """The released projection is what lets the same hours be taken again elsewhere."""
    _ok(_signup("Avery"))
    _ok(_cancel("Avery", version=1))
    _seed_slot(world["show_and_sells"], slot_id="slot-2", start_at=OVERLAP_START, end_at=OVERLAP_END)
    _ok(_signup("Avery", slot_id="slot-2", key="signup-second"))


def test_a_kernel_corrects_a_record_after_the_event_started(world: Dict[str, Any]) -> None:
    """SIGN-M-02: ACTIVE, ENDED and REOPENED are Kernel corrections, not Scout releases."""
    for index, (status, start, end) in enumerate(
        (
            ("SCHEDULED", _shift(-2), _shift(2)),
            ("SCHEDULED", _shift(-4), _shift(-2)),
            (ssm.STATUS_REOPENED, _shift(-4), _shift(-2)),
        )
    ):
        # Short ids, not the window: the idempotency marker's scope is an AWS-safe key fragment,
        # and an ISO instant carries characters that are not — which is why §3.3.1's own ids are
        # short too.
        event_id = f"SSE#late-{index}-{status}"
        _seed_event(world["show_and_sells"], event_id, start_at=start, end_at=end, status=status)
        slot_start, slot_end = _inside(start, end)
        _seed_slot(world["show_and_sells"], event_id, slot_id="slot-1", start_at=slot_start, end_at=slot_end)
        _seed_signup(world["show_and_sells"], event_id)
        _seed_commitment(world["unit_campaigns"], event_id, start_at=slot_start, end_at=slot_end)
        _seed_guard(world["unit_campaigns"])
        answer = _ok(_cancel("Avery", event_id=event_id, key=f"cancel-{event_id}"))
        assert answer["status"] == ssm.SIGNUP_CANCELLED, status


def test_a_scout_cannot_release_a_place_after_the_event_started(world: Dict[str, Any]) -> None:
    """SIGN-M-02 role/state matrix: past the start the row is evidence, not a place to give."""
    _seed_event(world["show_and_sells"], "SSE#running", start_at=_shift(-2), end_at=_shift(2))
    _seed_slot(world["show_and_sells"], "SSE#running", slot_id="slot-1", start_at=_shift(-1), end_at=_shift(1))
    _seed_signup(world["show_and_sells"], "SSE#running")
    _seed_commitment(world["unit_campaigns"], "SSE#running")
    _seed_guard(world["unit_campaigns"])
    message = _refusal(_cancel("Taylor", event_id="SSE#running"), "CONFLICT")
    assert "only its Kernel" in message
    assert _stored_signup(world["show_and_sells"], "SSE#running")[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_ACTIVE
    assert _guard_version(world["unit_campaigns"]) == 3, "a refusal moved nothing"


def test_a_cancellation_racing_a_signup_loses_on_the_pinned_counter(
    world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The counter is pinned on the way down too: a place taken after this read fails the plan.

    A decrement computed from a stale read would erase the competing signup's place, and the slot
    would then believe it holds one Scout fewer than it does — the same capacity hole the create
    guard closes, from the other side.
    """
    _ok(_signup("Avery"))
    _frozen_slot(monkeypatch, world)
    world["show_and_sells"].update_item(
        Key=ssm.slot_key(EVENT, "slot-1"),
        UpdateExpression="SET #count = :two, #version = :three",
        ExpressionAttributeNames={"#count": ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE, "#version": "version"},
        ExpressionAttributeValues={":two": 2, ":three": 3},
    )
    _refusal(_cancel("Avery", version=1), "CONFLICT")
    assert _stored_signup(world["show_and_sells"])[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_ACTIVE
    slot = _stored_slot(world["show_and_sells"])
    assert slot is not None and int(slot[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE]) == 2, "the winner's count stands"
    assert _guard_version(world["unit_campaigns"]) == 1, "a refusal moved no guard"


def test_a_finalized_or_cancelled_event_is_closed_over_its_signups(world: Dict[str, Any]) -> None:
    """SIGN-M-02: finalized credit needs §5's reopen; a cancellation already released."""
    _seed_event(world["show_and_sells"], "SSE#final", status=ssm.STATUS_FINALIZED)
    _seed_signup(world["show_and_sells"], "SSE#final")
    message = _refusal(_cancel("Avery", event_id="SSE#final"), "CONFLICT")
    assert "Reopen it" in message

    _seed_event(world["show_and_sells"], "SSE#gone", status=ssm.STATUS_CANCELLED)
    _seed_signup(world["show_and_sells"], "SSE#gone")
    assert "already released its signups" in _refusal(_cancel("Avery", event_id="SSE#gone"), "CONFLICT")


def test_historical_cleanup_does_not_need_an_active_roster_row(world: Dict[str, Any]) -> None:
    """SIGN-M-03 / EVT-M-04: a removed Scout still has a place to give back."""
    _seed_signup(world["show_and_sells"], persona="Emery")
    _seed_commitment(world["unit_campaigns"], persona="Emery")
    _seed_guard(world["unit_campaigns"], persona="Emery")
    _seed_membership(world["unit_campaigns"], persona="Emery")
    answer = _ok(_cancel("Avery", persona="Emery", key="cancel-removed"))
    assert answer["status"] == ssm.SIGNUP_CANCELLED
    assert _commitment_rows(world["unit_campaigns"], persona="Emery")[0][ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_CANCELLED


def test_a_stale_version_or_a_second_cancellation_is_refused(world: Dict[str, Any]) -> None:
    """VER-01 on the signup's own version, and §9.3's terminal state."""
    _ok(_signup("Avery"))
    _refusal(_cancel("Avery", version=2, key="cancel-stale"), "CONFLICT")
    _ok(_cancel("Avery", version=1, key="cancel-once"))
    assert "already cancelled" in _refusal(_cancel("Avery", version=2, key="cancel-twice"), "CONFLICT")


def test_cancelling_a_scout_with_no_projection_still_releases_the_place(world: Dict[str, Any]) -> None:
    """The aggregate is already wrong; refusing would strand a Scout giving a place back."""
    _seed_signup(world["show_and_sells"])
    answer = _ok(_cancel("Avery"))
    assert answer["status"] == ssm.SIGNUP_CANCELLED
    assert _commitment_rows(world["unit_campaigns"]) == []
    assert _guard_version(world["unit_campaigns"]) is None, "no guard to bump, and none is invented"
    assert int(_stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE]) == 2


def test_cancelling_beside_a_drifted_counter_refuses_rather_than_goes_negative(world: Dict[str, Any]) -> None:
    """A counter below zero is an aggregate this write did not create (§3.7 owns the repair)."""
    _seed_signup(world["show_and_sells"])
    _seed_slot(world["show_and_sells"], active=0)
    _refusal(_cancel("Avery"), "INVALID_INPUT")
    assert _stored_signup(world["show_and_sells"])[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_ACTIVE


def test_a_cancellation_of_a_signup_that_is_not_there_is_not_found(world: Dict[str, Any]) -> None:
    """NOT_FOUND, and a caller with no standing is refused before the row is read."""
    _refusal(_cancel("Avery"), "NOT_FOUND")
    _seed_signup(world["show_and_sells"])
    _refusal(_cancel("Emery"), "FORBIDDEN")
    assert _stored_signup(world["show_and_sells"])[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_ACTIVE


def test_a_cancellation_replays_once(world: Dict[str, Any]) -> None:
    _ok(_signup("Avery"))
    first = _ok(_cancel("Avery", version=1))
    again = _ok(_cancel("Avery", version=1))
    assert again == first
    assert int(_stored_slot(world["show_and_sells"])[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE]) == 0
    assert _guard_version(world["unit_campaigns"]) == 2


# --- SIGN-M-03: confirmed work ---------------------------------------------------


def _two_scouts(world: Dict[str, Any]) -> None:
    """Two Scouts holding two slots, so one batch spans two signups (75 and 115).

    The board's event is reopened first: work is what a Kernel watched happen, so §3.4.3's
    window only opens once the event has started, and REOPENED is the stored state that says so
    without waiting on the clock.
    """
    _seed_event(world["show_and_sells"], status=ssm.STATUS_REOPENED)
    _seed_slot(world["show_and_sells"], slot_id="slot-2", start_at=_at(4), end_at=_at(6))
    _seed_signup(world["show_and_sells"])
    _seed_signup(world["show_and_sells"], slot_id="slot-2", persona="Emery")


def test_a_batch_confirms_two_signups_and_totals_the_event(world: Dict[str, Any]) -> None:
    """SIGN-M-03 75/115 totaling 190, with the pending preview recomputed (§3.4.3)."""
    _two_scouts(world)
    answer = _ok(
        _confirm(
            "Avery",
            work=[
                {"slotId": "slot-1", "profileId": _profile("Devon"), "actualMinutes": 75},
                {"slotId": "slot-2", "profileId": _profile("Emery"), "actualMinutes": 115},
            ],
            version=1,
        )
    )
    assert set(answer) == {"work", "preview"}
    assert len(answer["work"]) == 2 and answer["work"][0]["actualMinutes"] == 75
    assert answer["work"][0]["signedUpByAccountId"] and answer["work"][0]["confirmedByAccountId"], (
        "the admin shape keeps the audit"
    )
    assert answer["preview"] == {
        "eventVersion": 2,
        "totalConfirmedMinutes": 190,
        "confirmedWorkRows": 2,
        "confirmedParticipants": 2,
        "minimumFinalizationActions": 3 + 2 + 4,
    }
    assert _stored_signup(world["show_and_sells"])["actualMinutes"] == 75
    assert _stored_signup(world["show_and_sells"], slot_id="slot-2", persona="Emery")[
        "confirmedByAccountId"
    ] == account_id("Avery")
    assert int(_stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE]) == 2


def test_zero_minutes_unconfirms_and_clears_the_audit_with_it(world: Dict[str, Any]) -> None:
    """§5.13: a row that says work was confirmed must name who confirmed it."""
    _seed_event(world["show_and_sells"], status=ssm.STATUS_REOPENED)
    _seed_signup(world["show_and_sells"], minutes=90, confirmed_by="ACCOUNT#avery-fixture")
    answer = _ok(_confirm("Avery", work=[{"slotId": "slot-1", "profileId": _profile("Devon"), "actualMinutes": 0}]))
    assert answer["preview"]["totalConfirmedMinutes"] == 0 and answer["preview"]["confirmedWorkRows"] == 0
    stored = _stored_signup(world["show_and_sells"])
    assert stored["actualMinutes"] == 0
    assert ssm.CONFIRMED_BY_ATTRIBUTE not in stored and ssm.CONFIRMED_AT_ATTRIBUTE not in stored, (
        "the audit is removed, not nulled"
    )


def test_work_is_confirmed_while_active_ended_or_reopened(world: Dict[str, Any]) -> None:
    """SIGN-M-03 REOPENED: the correction is what reopening is for."""
    for index, (status, start, end) in enumerate(
        (
            ("SCHEDULED", _shift(-2), _shift(2)),
            ("SCHEDULED", _shift(-4), _shift(-2)),
            (ssm.STATUS_REOPENED, _shift(-4), _shift(-2)),
        )
    ):
        # ACTIVE, ENDED and REOPENED, in that order: the first two come from the clock over a
        # stored SCHEDULED, the third is what §3.6's reopen writes.
        event_id = f"SSE#work-{index}-{status}"
        _seed_event(world["show_and_sells"], event_id, start_at=start, end_at=end, status=status)
        slot_start, slot_end = _inside(start, end)
        _seed_slot(world["show_and_sells"], event_id, slot_id="slot-1", start_at=slot_start, end_at=slot_end)
        _seed_signup(world["show_and_sells"], event_id)
        answer = _ok(_confirm("Avery", event_id=event_id, version=1, key=f"work-{event_id}"))
        assert answer["work"][0]["actualMinutes"] == 75, status


def test_a_scheduled_event_has_no_work_to_confirm(world: Dict[str, Any]) -> None:
    """SIGN-M-03: the window opens at the start."""
    _seed_signup(world["show_and_sells"])
    assert "no shift here" in _refusal(_confirm("Avery"), "CONFLICT")
    assert _stored_signup(world["show_and_sells"])[ssm.ACTUAL_MINUTES_ATTRIBUTE] == 0


def test_a_scout_cannot_confirm_their_own_work(world: Dict[str, Any]) -> None:
    """AUTH-U: the minutes are what the Kernel watched, and the audit names them."""
    _seed_signup(world["show_and_sells"])
    _refusal(_confirm("Taylor"), "NOT_FOUND")
    _refusal(_confirm("Devon"), "NOT_FOUND")


def test_minutes_longer_than_the_slot_are_refused(world: Dict[str, Any]) -> None:
    """SIGN-M-03 over-duration: the ceiling is the slot's own stored duration (SSE-03)."""
    _seed_signup(world["show_and_sells"])
    _seed_event(world["show_and_sells"], status=ssm.STATUS_REOPENED)
    message = _refusal(
        _confirm("Avery", work=[{"slotId": "slot-1", "profileId": _profile("Devon"), "actualMinutes": 121}]),
        "INVALID_INPUT",
    )
    assert "longer than this slot runs" in message


def test_a_batch_that_names_one_row_twice_is_refused(world: Dict[str, Any]) -> None:
    """SIGN-M-03 duplicate-row: two answers about one row's minutes is a request bug."""
    _seed_signup(world["show_and_sells"])
    _seed_event(world["show_and_sells"], status=ssm.STATUS_REOPENED)
    row = {"slotId": "slot-1", "profileId": _profile("Devon"), "actualMinutes": 60}
    message = _refusal(_confirm("Avery", work=[row, dict(row)]), "INVALID_INPUT")
    assert "one Scout twice" in message


def test_a_batch_shape_that_cannot_be_resolved_is_refused(world: Dict[str, Any]) -> None:
    """The input half of the same rule: 1-100 rows, each naming a row that exists."""
    _seed_event(world["show_and_sells"], status=ssm.STATUS_REOPENED)
    _refusal(_confirm("Avery", work=[]), "INVALID_INPUT")
    _refusal(_confirm("Avery", work="not-a-list"), "INVALID_INPUT")
    _refusal(_confirm("Avery", work=["slot-1"]), "INVALID_INPUT")
    _refusal(
        _confirm("Avery", work=[{"slotId": "slot-1", "profileId": _profile("Devon"), "actualMinutes": 30}]), "NOT_FOUND"
    )
    _seed_signup(world["show_and_sells"])
    _refusal(
        _confirm("Avery", work=[{"slotId": "slot-404", "profileId": _profile("Devon"), "actualMinutes": 30}]),
        "NOT_FOUND",
    )
    _refusal(
        _confirm(
            "Avery",
            work=[{"slotId": f"s{index}", "profileId": _profile("Devon"), "actualMinutes": 1} for index in range(101)],
        ),
        "INVALID_INPUT",
    )


def test_the_work_batch_is_bounded_by_the_finalization_budget_it_frees(
    world: Dict[str, Any],
) -> None:
    """SIGN-M-03 zero-frees-budget: clearing a row takes a work snapshot out of the plan."""
    _crowd(world, 30)
    _seed_event(world["show_and_sells"], status=ssm.STATUS_REOPENED)
    crowd = [row for row in _signup_rows_stored(world["show_and_sells"]) if str(row[ssm.SLOT_ID_ATTRIBUTE]) == "slot-9"]
    row = crowd[0]
    keep = [{"slotId": row[ssm.SLOT_ID_ATTRIBUTE], "profileId": row[ssm.PROFILE_ID_ATTRIBUTE], "actualMinutes": 10}]
    assert "actions to finalize" in _refusal(_confirm("Avery", work=keep), "CONFLICT")
    two = [
        {"slotId": item[ssm.SLOT_ID_ATTRIBUTE], "profileId": item[ssm.PROFILE_ID_ATTRIBUTE], "actualMinutes": 0}
        for item in crowd[:2]
    ]
    answer = _ok(_confirm("Avery", work=two, key="work-freed"))
    assert answer["preview"]["confirmedWorkRows"] == 28
    assert answer["preview"]["minimumFinalizationActions"] == 3 + 28 + 2 * 28 <= 90


def test_a_confirmation_racing_a_cancellation_loses_on_the_row_itself(world: Dict[str, Any]) -> None:
    """The write conditions on the signup's version and its state, not on a stale read."""
    _seed_signup(world["show_and_sells"], status=ssm.SIGNUP_CANCELLED, version=2)
    _seed_event(world["show_and_sells"], status=ssm.STATUS_REOPENED)
    _refusal(
        _confirm("Avery", work=[{"slotId": "slot-1", "profileId": _profile("Devon"), "actualMinutes": 75}]), "CONFLICT"
    )
    assert _stored_signup(world["show_and_sells"])[ssm.ACTUAL_MINUTES_ATTRIBUTE] == 0


def test_a_confirmation_replays_once(world: Dict[str, Any]) -> None:
    _seed_signup(world["show_and_sells"])
    _seed_event(world["show_and_sells"], status=ssm.STATUS_REOPENED)
    first = _ok(_confirm("Avery"))
    again = _ok(_confirm("Avery"))
    assert again == first
    assert int(_stored_event(world["show_and_sells"])[ssm.VERSION_ATTRIBUTE]) == 2


def test_a_stale_event_version_or_a_missing_event_is_refused(world: Dict[str, Any]) -> None:
    _seed_event(world["show_and_sells"], status=ssm.STATUS_REOPENED)
    _seed_signup(world["show_and_sells"])
    _refusal(_confirm("Avery", version=7), "CONFLICT")
    _refusal(_confirm("Avery", event_id="SSE#never-seeded", key="work-2"), "NOT_FOUND")


# --- EVT-Q-05: the admin signup board -------------------------------------------


def test_the_admin_board_carries_the_audit_and_the_cancelled_history(world: Dict[str, Any]) -> None:
    """EVT-Q-05: cancelled rows stay, because they are the history §5.13 keeps."""
    _seed_signup(world["show_and_sells"])
    _seed_signup(world["show_and_sells"], persona="Emery", status=ssm.SIGNUP_CANCELLED, version=2)
    answer = _ok(_signup_rows("Avery"))
    assert set(answer) == {"items", "pageInfo"}
    assert len(answer["items"]) == 2
    first = answer["items"][0]
    assert {"signedUpByAccountId", "confirmedByAccountId", "confirmedAt", "version"} <= set(first)
    assert first["profileId"] == _profile("Devon")

    active = _ok(_signup_rows("Avery", status="ACTIVE"))
    assert [row["profileId"] for row in active["items"]] == [_profile("Devon")]
    cancelled = _ok(_signup_rows("Avery", status="CANCELLED"))
    assert [row["profileId"] for row in cancelled["items"]] == [_profile("Emery")]


def test_the_board_paginates_and_pins_its_cursor_to_the_filter(world: Dict[str, Any]) -> None:
    """PAGE-01: a page token belongs to the filter set it was minted for."""
    _seed_signup(world["show_and_sells"])
    _seed_signup(world["show_and_sells"], persona="Emery", status=ssm.SIGNUP_CANCELLED, version=2)
    page = _ok(_signup_rows("Avery", page={"limit": 1}))
    assert len(page["items"]) == 1
    token = page["pageInfo"]["endCursor"]
    assert token, "a page with more rows carries a cursor"
    second = _ok(_signup_rows("Avery", page={"limit": 1, "cursor": token}))
    assert [row["profileId"] for row in second["items"]] == [_profile("Emery")]
    message = _refusal(_signup_rows("Avery", status="ACTIVE", page={"limit": 1, "cursor": token}), "INVALID_INPUT")
    assert "different request" in message, "the ACTIVE board cannot be paged with a full-history cursor"


def test_the_board_refuses_an_unknown_state_and_a_caller_outside_the_unit(world: Dict[str, Any]) -> None:
    _seed_signup(world["show_and_sells"])
    _refusal(_signup_rows("Avery", status="PENDING"), "INVALID_INPUT")
    _refusal(_signup_rows("Emery"), "NOT_FOUND")
    _refusal(_signup_rows("Avery", showAndSellId="SSE#never-seeded"), "NOT_FOUND")


# --- INV-Q-06: the Scout's own commitment list -----------------------------------


def test_a_scout_reads_their_own_commitments_across_every_unit_campaign(world: Dict[str, Any]) -> None:
    """INV-Q-06-01: one Scout, two Unit Campaigns, and no actor or Unit bookkeeping."""
    _seed_commitment(world["unit_campaigns"])
    _seed_commitment(
        world["unit_campaigns"],
        OTHER_EVENT,
        "slot-x",
        start_at=_at(30),
        end_at=_at(32),
        unit_campaign_id=OTHER_CAMPAIGN,
    )
    answer = _ok(_commitments(persona="Devon"))
    assert set(answer) == {"items", "pageInfo"}
    assert [row["startAt"] for row in answer["items"]] == [FIRST_START, _at(30)]
    for row in answer["items"]:
        assert set(row) == {"showAndSellId", "slotId", "startAt", "endAt", "status", "signupVersion"}
        assert row["signupVersion"] == 1, "the Scout holds the number their cancellation names"


def test_cancelled_commitments_are_history_the_caller_asks_for(world: Dict[str, Any]) -> None:
    """Only an ACTIVE commitment blocks a signup, so the default list is the blocker list."""
    _seed_commitment(world["unit_campaigns"])
    _seed_commitment(
        world["unit_campaigns"],
        "SSE#released-place",
        "slot-2",
        start_at=_at(4),
        end_at=_at(6),
        status=ssm.SIGNUP_CANCELLED,
    )
    answer = _ok(_commitments(persona="Devon"))
    assert len(answer["items"]) == 1
    everything = _ok(_commitments(persona="Devon", includeCancelled=True))
    assert len(everything["items"]) == 2


def test_a_unit_admin_sees_only_the_unit_they_name(world: Dict[str, Any]) -> None:
    """INV-Q-06-02 / AUTH-U: the admin path is a narrowing filter, never a wider window."""
    _seed_commitment(world["unit_campaigns"])
    _seed_commitment(
        world["unit_campaigns"],
        OTHER_EVENT,
        "slot-x",
        start_at=_at(30),
        end_at=_at(32),
        unit_campaign_id=OTHER_CAMPAIGN,
    )
    answer = _ok(_commitments("Avery", persona="Devon", unitId=PACK_3149))
    assert [row["showAndSellId"] for row in answer["items"]] == [EVENT]
    own = _ok(_commitments("Devon", persona="Devon", unitId=PACK_3149))
    assert [row["showAndSellId"] for row in own["items"]] == [EVENT], (
        "the Scout who holds the profile may name a Unit to narrow their own read — no second "
        "authorization is asked for, and none is skipped"
    )
    _refusal(_commitments("Emery", persona="Devon", unitId=PACK_3149), "NOT_FOUND")
    _refusal(_commitments("Emery", persona="Devon"), "FORBIDDEN")


def test_a_read_only_share_may_see_the_profile_it_holds(world: Dict[str, Any]) -> None:
    """AUTH-P: READ is enough to look, and never enough to hold a place."""
    _seed_commitment(world["unit_campaigns"], OTHER_EVENT, "slot-x", persona="Avery", unit_campaign_id=OTHER_CAMPAIGN)
    answer = _ok(_commitments("Riley", persona="Avery"))
    assert len(answer["items"]) == 1 and answer["items"][0]["showAndSellId"] == OTHER_EVENT


def test_a_scout_sees_nothing_about_a_scout_they_are_not(world: Dict[str, Any]) -> None:
    """INV-Q-06-03 / AUTH-P: the answer is the caller's own schedule, and an empty one is fine."""
    _seed_commitment(world["unit_campaigns"], persona="Emery")
    answer = _ok(_commitments("Devon"))
    assert answer["items"] == []


# --- DATA-Q-05 / CAL-01: the calendar data a browser builds an invite from --------


def test_the_calendar_data_is_the_stable_identity_and_the_utc_interval(world: Dict[str, Any]) -> None:
    """DATA-Q-05, CAL-01: identity, location, IANA timezone and UTC times — and nothing else."""
    _ok(_signup("Avery"))
    answer = _ok(_calendar("Avery"))
    assert answer == {
        "unitId": PACK_3149,
        "unitDisplayName": generated_display_name("Pack", 3149, "Aurora", "CO"),
        "unitCampaignId": CAMPAIGN,
        "unitCampaignName": "Pack 3149 Fall Show & Sell",
        "showAndSellId": EVENT,
        "slotId": "slot-1",
        "profileId": _profile("Devon"),
        "slotLabel": "Morning door",
        "locationName": LOCATION,
        "address": ADDRESS,
        "timezone": "America/Denver",
        "slotStartAt": FIRST_START,
        "slotEndAt": FIRST_END,
    }


def test_an_arbitrary_slot_duration_passes_through_unchanged(world: Dict[str, Any]) -> None:
    """SSE-03/CAL-01: a 137-minute slot is not rounded to a grid on its way out."""
    _seed_slot(world["show_and_sells"], slot_id="slot-odd", start_at=_at(5), end_at=_at(5 + 137 / 60), label=None)
    _seed_signup(world["show_and_sells"], slot_id="slot-odd")
    answer = _ok(_calendar("Avery", slot_id="slot-odd"))
    assert answer["slotLabel"] is None
    assert (
        int(
            (
                datetime.fromisoformat(answer["slotEndAt"]) - datetime.fromisoformat(answer["slotStartAt"])
            ).total_seconds()
        )
        == 137 * 60
    )


def test_a_scout_builds_their_own_invite(world: Dict[str, Any]) -> None:
    """AUTH-P-05: Owner/WRITE for the exact Scout is enough."""
    _seed_signup(world["show_and_sells"])
    answer = _ok(_calendar("Taylor"))
    assert answer["profileId"] == _profile("Devon")


def test_a_read_only_share_or_a_foreign_kernel_is_refused(world: Dict[str, Any]) -> None:
    """AUTH-P-02: READ on the profile and admin of another Unit are both outside this read."""
    _seed_signup(world["show_and_sells"], persona="Avery")
    _refusal(_calendar("Riley", persona="Avery"), "FORBIDDEN")
    _seed_signup(world["show_and_sells"], OTHER_EVENT, persona="Devon")
    _seed_slot(world["show_and_sells"], OTHER_EVENT, slot_id="slot-1")
    # Riley administers a different Unit, and that grant buys nothing here (AUTH-P-02).
    _refusal(_calendar("Riley", event_id=OTHER_EVENT, persona="Devon"), "FORBIDDEN")
    assert _stored_signup(world["show_and_sells"], OTHER_EVENT) is not None


def test_calendar_data_for_a_signup_that_never_happened_is_not_found(world: Dict[str, Any]) -> None:
    """There is no empty-but-successful answer here to confuse with one (PAGE-01)."""
    _refusal(_calendar("Avery"), "NOT_FOUND")
    _seed_signup(world["show_and_sells"], status=ssm.SIGNUP_CANCELLED, version=2)
    answer = _ok(_calendar("Avery"))
    assert answer["showAndSellId"] == EVENT, "a released place still describes the hours it held"
