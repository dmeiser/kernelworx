"""Leaf 3.3.1 — the slot, signup, commitment and guard model (data model §5.12–§5.13, §6.2, §6.4).

Model-layer tests for the rows §3.3 adds: ``SLOT#<slotId>`` with an arbitrary
event-bounded interval, an optional label, capacity 1–100, a transactional
``activeSignupCount``, and a version — plus the ``SIGNUP#`` row, the cross-campaign
``COMMITMENT#`` projection, and the one-row-per-Scout ``COMMITMENT_GUARD`` those slot
writes reason about. The §3.3.1 work order names the four families this file is
organized around — 90/120/180-minute durations, adjacency, cross-campaign overlap,
and counter reconciliation — and each is asserted against the model rather than
through a resolver, because §3.4's signup and §3.7's validation re-read these rules
and must inherit them rather than restate them.

Like the event model leaf, the conditional actions are asserted on the payload they
produce (a transaction the resolver never got to commit proves nothing about the
condition it carried), and the pure revalidation is decided on seeded rows rather
than imagined numbers, so the sentences it returns name the real signup, slot, and
Scout the refusal is about.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.utils import show_and_sell_models as ssm
from src.utils.errors import AppError

EVENT_ID = "SSE#slot-model-event"
OTHER_EVENT_ID = "SSE#slot-model-other"
UNIT = "unit-pack-3149-aurora"
CAMPAIGN = "uc-pack-3149-fall-2026"
OTHER_CAMPAIGN = "uc-crew-529-spring-2026"
PROFILE = "PROFILE#prof-devon-fixture"
OTHER_PROFILE = "PROFILE#prof-emery-fixture"
SCOUT_CAMPAIGN = "CAMPAIGN#camp-devon-fixture"
ACTOR = "ACCOUNT#admin-fixture"

START = "2026-11-07T08:00:00+00:00"
END = "2026-11-07T13:00:00+00:00"
BEFORE = "2026-11-07T07:00:00+00:00"
AFTER = "2026-11-07T14:00:00+00:00"


def _event_row(event_id: str = EVENT_ID, **overrides: Any) -> Dict[str, Any]:
    """A complete, legal event row: the interval the slot bounds are decided against."""
    fields: Dict[str, Any] = {
        "show_and_sell_id": event_id,
        "unit_id": UNIT,
        "unit_campaign_id": CAMPAIGN,
        "location_name": "Aurora fire station lot",
        "start_at": START,
        "end_at": END,
        "created_by_account_id": ACTOR,
        "now_iso": BEFORE,
    }
    fields.update(overrides)
    return ssm.build_show_and_sell_item(**fields)


def _slot_row(event_id: str = EVENT_ID, slot_id: str = "slot-1", **overrides: Any) -> Dict[str, Any]:
    """A complete, legal slot row, with per-test overrides."""
    fields: Dict[str, Any] = {
        "event": _event_row(event_id),
        "slot_id": slot_id,
        "start_at": "2026-11-07T09:00:00+00:00",
        "end_at": "2026-11-07T10:30:00+00:00",
        "capacity": 4,
        "now_iso": BEFORE,
    }
    fields.update(overrides)
    return ssm.build_show_and_sell_slot_item(**fields)


def _stored_slot_row(event_id: str = EVENT_ID, slot_id: str = "slot-1", **overrides: Any) -> Dict[str, Any]:
    """A slot row altered after the build, for the invariants only a broken row shows.

    The builder refuses every illegal value on the way in, so a test that wants to
    prove the invariant checker catches one — from a row an older writer stored, say
    — has to build the broken row by hand. That is the point of the assertion.
    """
    row = dict(_slot_row(event_id, slot_id))
    row.update(overrides)
    return row


def _signup_row(
    event_id: str = EVENT_ID,
    slot_id: str = "slot-1",
    profile: str = PROFILE,
    **overrides: Any,
) -> Dict[str, Any]:
    fields: Dict[str, Any] = {
        "event": _event_row(event_id),
        "slot_id": slot_id,
        "profile_id": profile,
        "campaign_id": SCOUT_CAMPAIGN,
        "signed_up_by_account_id": ACTOR,
        "now_iso": BEFORE,
    }
    fields.update(overrides)
    return ssm.build_show_and_sell_signup_item(**fields)


def _commitment_row(
    slot_id: str = "slot-1",
    *,
    event_id: str = EVENT_ID,
    unit_campaign_id: str = CAMPAIGN,
    profile: str = PROFILE,
    start_at: str = "2026-11-07T09:00:00+00:00",
    end_at: str = "2026-11-07T10:30:00+00:00",
    **overrides: Any,
) -> Dict[str, Any]:
    fields: Dict[str, Any] = {
        "profile_id": profile,
        "unit_campaign_id": unit_campaign_id,
        "show_and_sell_id": event_id,
        "slot_id": slot_id,
        "start_at": start_at,
        "end_at": end_at,
        "now_iso": BEFORE,
        "version": 1,
    }
    fields.update(overrides)
    return ssm.build_scout_commitment_item(**fields)


# --- Slot rows: arbitrary durations inside the event (SLOT-01, AC-13) -----------


@pytest.mark.parametrize(
    ("start_at", "end_at", "minutes"),
    [
        ("2026-11-07T08:00:00+00:00", "2026-11-07T09:30:00+00:00", 90),
        ("2026-11-07T08:00:00+00:00", "2026-11-07T10:00:00+00:00", 120),
        ("2026-11-07T08:00:00+00:00", "2026-11-07T11:00:00+00:00", 180),
    ],
)
def test_a_slot_may_last_ninety_one_hundred_twenty_or_one_hundred_eighty_minutes(
    start_at: str, end_at: str, minutes: int
) -> None:
    """SLOT-01 / SSE-03 / AC-13: no assumed hour, half-hour, or quarter-hour."""
    slot = _slot_row(start_at=start_at, end_at=end_at)
    assert slot[ssm.START_AT_ATTRIBUTE] == start_at
    assert slot[ssm.END_AT_ATTRIBUTE] == end_at
    assert slot["entityType"] == ssm.ENTITY_TYPE_SLOT


def test_a_slot_may_touch_both_ends_of_the_event_interval() -> None:
    """§5.12's bound is inclusive at both ends: ``event.startAt <= slot.startAt`` and
    ``slot.endAt <= event.endAt``, so the first minute and the last minute of an event
    can each open a booth."""
    slot = _slot_row(start_at=START, end_at=END)
    assert slot[ssm.START_AT_ATTRIBUTE] == START
    assert slot[ssm.END_AT_ATTRIBUTE] == END


def test_a_slot_outside_the_event_interval_is_refused() -> None:
    """A booth before the event opens or after it closes is nobody's to staff."""
    for start_at, end_at, phrase in [
        ("2026-11-07T07:30:00+00:00", "2026-11-07T09:00:00+00:00", "before the event starts"),
        ("2026-11-07T12:00:00+00:00", "2026-11-07T13:30:00+00:00", "after the event ends"),
    ]:
        with pytest.raises(AppError) as raised:
            _slot_row(start_at=start_at, end_at=end_at)
        assert raised.value.error_code is ssm.ErrorCode.INVALID_INPUT
        assert phrase in str(raised.value)


def test_a_slot_interval_that_does_not_run_forward_is_refused() -> None:
    with pytest.raises(AppError) as raised:
        _slot_row(start_at="2026-11-07T10:00:00+00:00", end_at="2026-11-07T10:00:00+00:00")
    assert raised.value.error_code is ssm.ErrorCode.INVALID_INPUT


def test_the_slot_key_shape_is_the_aggregate_the_read_queries() -> None:
    """§6.4: the slot lives in the event's partition under ``SLOT#<slotId>``."""
    slot = _slot_row()
    assert slot["pk"] == ssm.show_and_sell_pk(EVENT_ID)
    assert slot["sk"] == "SLOT#slot-1"
    assert ssm.slot_key(EVENT_ID, "slot-1") == {"pk": slot["pk"], "sk": slot["sk"]}


def test_the_optional_label_is_trimmed_text_and_a_long_one_is_refused() -> None:
    assert _slot_row(label="  Morning booth  ")[ssm.LABEL_ATTRIBUTE] == "Morning booth"
    assert _slot_row(label=None)[ssm.LABEL_ATTRIBUTE] is None
    with pytest.raises(AppError):
        _slot_row(label="x" * (ssm.MAX_SLOT_LABEL_LENGTH + 1))


@pytest.mark.parametrize("capacity", [0, -1, 101, True, "4"])
def test_capacity_must_be_an_integer_between_one_and_one_hundred(capacity: Any) -> None:
    for legal in (1, ssm.MAX_SLOT_CAPACITY):
        assert _slot_row(capacity=legal)[ssm.CAPACITY_ATTRIBUTE] == legal
    with pytest.raises(AppError) as raised:
        _slot_row(capacity=capacity)
    assert raised.value.error_code is ssm.ErrorCode.INVALID_INPUT


@pytest.mark.parametrize("count", [-1, True, "1"])
def test_the_active_signup_counter_starts_non_negative(count: Any) -> None:
    with pytest.raises(AppError) as raised:
        _slot_row(active_signup_count=count)
    assert raised.value.error_code is ssm.ErrorCode.INVALID_INPUT


def test_a_counter_above_capacity_cannot_be_written() -> None:
    with pytest.raises(AppError) as raised:
        _slot_row(capacity=2, active_signup_count=3)
    assert "exceeds capacity" in str(raised.value)


@pytest.mark.parametrize(
    ("overrides", "phrase"),
    [
        ({"entityType": "SomethingElse"}, "entityType"),
        ({"bogusField": 1}, "attributes the model leaves out"),
        ({"capacity": "4"}, "capacity must be an integer"),
        ({"capacity": 0}, "capacity must be between 1 and 100"),
        ({"capacity": 101}, "capacity must be between 1 and 100"),
        ({"activeSignupCount": "1"}, "activeSignupCount must be an integer"),
        ({"activeSignupCount": -1}, "must not be negative"),
        ({"activeSignupCount": 5, "capacity": 4}, "exceeds capacity"),
    ],
)
def test_a_hand_stored_slot_row_is_measured_against_every_invariant(overrides: Dict[str, Any], phrase: str) -> None:
    """The checker stands for rows the builder never produced — an older writer, or a
    reader deciding whether an aggregate is intact."""
    violations = ssm.slot_invariant_violations(_stored_slot_row(**overrides))
    assert any(phrase in problem for problem in violations), violations


def test_a_slot_row_missing_an_attribute_is_reported_missing() -> None:
    row = dict(_slot_row())
    del row[ssm.CAPACITY_ATTRIBUTE]
    del row[ssm.START_AT_ATTRIBUTE]
    violations = ssm.slot_invariant_violations(row)
    assert any("missing attributes" in problem for problem in violations)
    assert any("startAt and endAt are required" in problem for problem in violations)


def test_slot_bounds_are_decided_against_the_interval_not_the_clock() -> None:
    """``slot_bounds_violations`` answers only the two outer bounds; a slot that runs
    forward is already settled, and an event row missing an end cannot be a bound."""
    event = _event_row()
    assert ssm.slot_bounds_violations(event, START, END) == []
    broken_event = {"startAt": "", "endAt": ""}
    assert ssm.slot_bounds_violations(broken_event, "2026-11-07T06:00:00+00:00", AFTER) == []


def test_an_event_bound_is_not_measured_against_a_slot_that_carries_no_interval() -> None:
    """A row with no instants of its own has nothing to bound.

    The bound check would answer "ends after the event ends" about a row whose real defect
    is that ``endAt`` is missing, and §3.7's validator reports one defect once: the interval
    checker already named the missing pair, so the bound check stands down rather than
    inventing a comparison against an absent value.
    """
    row = dict(_slot_row())
    del row[ssm.START_AT_ATTRIBUTE]
    del row[ssm.END_AT_ATTRIBUTE]
    violations = ssm.slot_invariant_violations(row, event=_event_row())
    assert any("startAt and endAt are required" in problem for problem in violations), violations
    assert not any("event starts" in problem or "event ends" in problem for problem in violations), violations


# --- Slot writes: the conditions the transaction carries -------------------------


def test_a_slot_insert_is_its_own_duplicate_guard() -> None:
    kind, payload = ssm.put_slot_action(_slot_row())
    assert kind == "Put"
    assert payload["ConditionExpression"] == "attribute_not_exists(#pk) AND attribute_not_exists(#sk)"
    assert payload["TableName"] == ssm.tables.show_and_sells.table_name


def test_a_slot_update_conditions_on_version_and_keeps_room_for_every_signup() -> None:
    """The capacity floor rides the write: the resolver refuses a shrink it read,
    and the condition catches the signup that moved the counter after that read."""
    kind, payload = ssm.update_slot_action(
        show_and_sell_id=EVENT_ID,
        slot_id="slot-1",
        expected_version=3,
        label="Afternoon booth",
        start_at="2026-11-07T09:00:00+00:00",
        end_at="2026-11-07T12:00:00+00:00",
        capacity=2,
        updated_at=AFTER,
    )
    assert kind == "Update"
    assert "#version = :expectedVersion" in payload["ConditionExpression"]
    assert "#activeSignupCount <= :roomCondition" in payload["ConditionExpression"]
    assert payload["ExpressionAttributeValues"][":roomCondition"] == {"N": "2"}
    assert payload["ExpressionAttributeValues"][":version"] == {"N": "4"}


def test_a_slot_delete_requires_the_row_the_zero_counter_and_the_version_read() -> None:
    kind, payload = ssm.delete_slot_action(show_and_sell_id=EVENT_ID, slot_id="slot-1", expected_version=2)
    assert kind == "Delete"
    assert "attribute_exists(#pk)" in payload["ConditionExpression"]
    assert "#version = :expectedVersion" in payload["ConditionExpression"]
    assert "#activeSignupCount = :zeroCondition" in payload["ConditionExpression"]
    assert payload["ExpressionAttributeValues"][":zeroCondition"] == {"N": "0"}


def test_the_event_version_bump_carries_the_scheduled_state_guard() -> None:
    """§3.3 writes slots only on a SCHEDULED event, and the state this request checked
    is re-checked at commit — the same rule §3.1.4's cancellation carries."""
    kind, payload = ssm.bump_event_version_action(
        show_and_sell_id=EVENT_ID,
        expected_version=5,
        updated_by_account_id=ACTOR,
        updated_at=AFTER,
    )
    assert kind == "Update"
    assert "#status = :stateCondition" in payload["ConditionExpression"]
    assert payload["ExpressionAttributeValues"][":stateCondition"] == {"S": ssm.STATUS_SCHEDULED}
    assert payload["ExpressionAttributeValues"][":version"] == {"N": "6"}


# --- Slots only move while the event is scheduled --------------------------------


def test_require_slots_writable_refuses_every_state_but_scheduled() -> None:
    base = dict(_event_row())
    now = "2026-11-07T07:00:00+00:00"
    assert ssm.require_slots_writable(base, now) == ssm.STATUS_SCHEDULED
    started = dict(base, **{ssm.START_AT_ATTRIBUTE: BEFORE, ssm.END_AT_ATTRIBUTE: AFTER})
    ended = dict(base, **{ssm.START_AT_ATTRIBUTE: BEFORE, ssm.END_AT_ATTRIBUTE: BEFORE})
    for state, row in [
        (ssm.STATUS_ACTIVE, started),
        (ssm.STATUS_ENDED, ended),
        (ssm.STATUS_REOPENED, dict(base, **{ssm.STATUS_ATTRIBUTE: ssm.STATUS_REOPENED})),
        (
            ssm.STATUS_FINALIZED,
            dict(base, **{ssm.STATUS_ATTRIBUTE: ssm.STATUS_FINALIZED, ssm.APPROVED_FINALIZATION_ID_ATTRIBUTE: "fin-1"}),
        ),
        (
            ssm.STATUS_CANCELLED,
            dict(
                base,
                **{
                    ssm.STATUS_ATTRIBUTE: ssm.STATUS_CANCELLED,
                    ssm.CANCELLATION_REASON_ATTRIBUTE: "storm",
                    ssm.CANCELLED_BY_ATTRIBUTE: ACTOR,
                    ssm.CANCELLED_AT_ATTRIBUTE: BEFORE,
                },
            ),
        ),
    ]:
        with pytest.raises(AppError) as raised:
            ssm.require_slots_writable(row, now)
        assert raised.value.error_code is ssm.ErrorCode.CONFLICT
        assert raised.value.details["subcode"] == "EVENT_STATE"
        assert raised.value.details["status"] == state


# --- Signups: one place per Scout per slot (SLOT-02) ------------------------------


def test_a_signup_is_unique_per_scout_and_slot_by_its_key() -> None:
    """§5.13's "at most one active signup per (slotId, profileId)" is a key fact: the
    signup's sort key IS that pair, so the duplicate signup is the same row."""
    first = _signup_row()
    second = _signup_row()
    assert first["sk"] == ssm.signup_sk("slot-1", PROFILE)
    assert first["sk"] == second["sk"]
    assert first["pk"] == ssm.show_and_sell_pk(EVENT_ID)


def test_a_signup_starts_unconfirmed_and_minutes_never_go_negative() -> None:
    signup = _signup_row()
    assert signup[ssm.ACTUAL_MINUTES_ATTRIBUTE] == 0
    assert signup[ssm.CONFIRMED_BY_ATTRIBUTE] is None
    assert signup[ssm.STATUS_ATTRIBUTE] == ssm.SIGNUP_ACTIVE
    with pytest.raises(AppError):
        _signup_row(actual_minutes=-1)
    with pytest.raises(AppError):
        _signup_row(status="DECLINED")


def test_a_confirmation_without_a_confirmer_is_a_broken_audit_trail() -> None:
    row = dict(_signup_row())
    row[ssm.CONFIRMED_AT_ATTRIBUTE] = AFTER
    assert any("confirmedByAccountId" in problem for problem in ssm.signup_invariant_violations(row))
    row[ssm.CONFIRMED_BY_ATTRIBUTE] = ACTOR
    assert ssm.signup_invariant_violations(row) == []


def test_a_confirmed_signup_is_re_emitted_with_both_halves_of_its_audit() -> None:
    """§3.4.3 replays a confirmed signup, so the builder has to produce a confirmed row.

    The confirmation is a build argument rather than a patch, which is what lets a
    replay rewrite the whole row at once; the audit pair lands together or the builder
    refuses, because a row saying work was confirmed with no name next to it is the
    trail §3.4.3 exists to prevent.
    """
    confirmed = _signup_row(confirmed_by_account_id=ACTOR, confirmed_at=AFTER, actual_minutes=90, version=2)
    assert confirmed[ssm.CONFIRMED_BY_ATTRIBUTE] == ACTOR
    assert confirmed[ssm.CONFIRMED_AT_ATTRIBUTE] == AFTER
    assert confirmed[ssm.ACTUAL_MINUTES_ATTRIBUTE] == 90
    assert confirmed[ssm.VERSION_ATTRIBUTE] == 2
    with pytest.raises(AppError) as raised:
        _signup_row(confirmed_at=AFTER)
    assert "confirmedByAccountId" in str(raised.value)


@pytest.mark.parametrize(
    ("overrides", "phrase"),
    [
        ({"entityType": "SomethingElse"}, "entityType"),
        ({"bogusField": 1}, "attributes the model leaves out"),
        ({"status": "DECLINED"}, "status is not one of"),
        ({"actualMinutes": "30"}, "actualMinutes must be an integer"),
        ({"actualMinutes": -1}, "actualMinutes must not be negative"),
    ],
)
def test_a_hand_stored_signup_row_is_measured_against_every_invariant(overrides: Dict[str, Any], phrase: str) -> None:
    row = dict(_signup_row())
    row.update(overrides)
    assert any(phrase in problem for problem in ssm.signup_invariant_violations(row))


def test_a_signup_row_missing_an_attribute_is_reported_missing() -> None:
    row = dict(_signup_row())
    del row[ssm.PROFILE_ID_ATTRIBUTE]
    assert any("missing attributes" in problem for problem in ssm.signup_invariant_violations(row))


# --- Commitments: the cross-campaign blocker (SLOT-03, SLOT-04) -------------------


def test_the_commitment_is_partitioned_by_scout_and_sorted_by_start() -> None:
    """§6.2: ``PROFILE#<profileId> / COMMITMENT#<startAt>#<unitCampaignId>#<slotId>`` —
    the Scout's partition, sorted by start, is what makes the overlap question one
    consistent query rather than a scan of every campaign the Scout joined."""
    commitment = _commitment_row()
    assert commitment["pk"] == "PROFILE#prof-devon-fixture"
    assert commitment["sk"].startswith(f"COMMITMENT#{commitment[ssm.START_AT_ATTRIBUTE]}#{CAMPAIGN}#")
    assert commitment["sk"] == ssm.commitment_sk(commitment[ssm.START_AT_ATTRIBUTE], CAMPAIGN, "slot-1")
    assert commitment[ssm.COMMITMENT_ID_ATTRIBUTE] == ssm.signup_sk("slot-1", PROFILE)


def test_commitments_at_different_campaigns_share_one_scout_partition() -> None:
    """SLOT-04 lives in the row layout: two Unit Campaigns, one Scout, one partition —
    the layout is why §3.4's conflict check is not per-campaign."""
    here = _commitment_row()
    elsewhere = _commitment_row("slot-9", event_id=OTHER_EVENT_ID, unit_campaign_id=OTHER_CAMPAIGN)
    assert here["pk"] == elsewhere["pk"]
    assert here["sk"] != elsewhere["sk"]


def test_adjacent_commitments_never_overlap_and_touching_ends_stay_legal() -> None:
    assert (
        ssm.intervals_overlap(
            "2026-11-07T08:00:00+00:00",
            "2026-11-07T09:00:00+00:00",
            "2026-11-07T09:00:00+00:00",
            "2026-11-07T10:00:00+00:00",
        )
        is False
    )
    assert (
        ssm.intervals_overlap(
            "2026-11-07T08:00:00+00:00",
            "2026-11-07T09:30:00+00:00",
            "2026-11-07T09:00:00+00:00",
            "2026-11-07T10:00:00+00:00",
        )
        is True
    )


def test_a_commitment_projection_is_measured_against_its_invariants() -> None:
    broken = dict(_commitment_row())
    broken["entityType"] = "ShowAndSellCommitment"
    assert any("entityType" in problem for problem in ssm.commitment_invariant_violations(broken))
    inverted = dict(_commitment_row())
    inverted[ssm.END_AT_ATTRIBUTE] = "2026-11-06T01:00:00+00:00"
    assert any("endAt must be after startAt" in problem for problem in ssm.commitment_invariant_violations(inverted))
    wrong_status = dict(_commitment_row())
    wrong_status[ssm.STATUS_ATTRIBUTE] = "DECLINED"
    assert any("status is not one of" in problem for problem in ssm.commitment_invariant_violations(wrong_status))
    missing = dict(_commitment_row())
    del missing[ssm.SLOT_ID_ATTRIBUTE]
    assert any("missing attributes" in problem for problem in ssm.commitment_invariant_violations(missing))
    smuggled = dict(_commitment_row())
    smuggled["buyerName"] = "someone"
    assert any(
        "attributes the model leaves out" in problem for problem in ssm.commitment_invariant_violations(smuggled)
    )


def test_the_guard_is_the_one_small_version_row_per_scout() -> None:
    guard = ssm.build_commitment_guard_item(profile_id=PROFILE, commitment_version=3, now_iso=BEFORE)
    assert guard["pk"] == ssm.commitment_pk(PROFILE)
    assert guard["sk"] == ssm.COMMITMENT_GUARD_SK
    assert guard[ssm.COMMITMENT_VERSION_ATTRIBUTE] == 3
    with pytest.raises(AppError):
        ssm.build_commitment_guard_item(profile_id=PROFILE, commitment_version=None, now_iso=BEFORE)


def test_the_guard_bump_pins_the_version_the_plan_validated_against() -> None:
    """The bump is a compare-and-set, not just an increment.

    An increment that only requires the guard to EXIST serializes nothing: two slot moves, one
    at each of one Scout's two Show & Sells, each revalidate the Scout's board against the
    other's old interval, both bumps succeed, and the Scout ends up with two commitments at the
    same hour — the AC-14 breach, with no event-version condition anywhere to catch it. Pinning
    the version the plan read makes the second writer's whole plan roll back, while the value
    stays DynamoDB's own increment so no writer ever writes a number it invented.
    """
    kind, payload = ssm.bump_commitment_guard_action(
        profile_id=PROFILE, updated_at=AFTER, expected_commitment_version=3
    )
    assert kind == "Update"
    assert "#commitmentVersion = :expectedCommitmentVersion" in payload["ConditionExpression"]
    assert payload["ExpressionAttributeValues"][":expectedCommitmentVersion"] == {"N": "3"}
    assert payload["UpdateExpression"] == "SET #commitmentVersion = #commitmentVersion + :one, #updatedAt = :updatedAt"

    unpinned = ssm.bump_commitment_guard_action(profile_id=PROFILE, updated_at=AFTER)[1]
    assert unpinned["ConditionExpression"] == "attribute_exists(#pk) AND attribute_exists(#commitmentVersion)"
    assert ":expectedCommitmentVersion" not in unpinned["ExpressionAttributeValues"]


# --- The revalidation a slot edit must pass (§3.3.2) ------------------------------


def _revalidate(
    *,
    slot_id: str = "slot-1",
    start_at: str = "2026-11-07T09:00:00+00:00",
    end_at: str = "2026-11-07T10:30:00+00:00",
    capacity: int = 4,
    slots: List[Dict[str, Any]] | None = None,
    signups: List[Dict[str, Any]] | None = None,
    commitments_by_profile: Dict[str, List[Dict[str, Any]]] | None = None,
) -> List[str]:
    return ssm.slot_revalidation_violations(
        show_and_sell_id=EVENT_ID,
        slot_id=slot_id,
        start_at=start_at,
        end_at=end_at,
        capacity=capacity,
        slots=slots or [],
        signups=signups or [],
        commitments_by_profile=commitments_by_profile or {},
    )


def test_a_projection_is_found_by_its_event_and_slot_not_by_its_key() -> None:
    """The ``(showAndSellId, slotId)`` pair identifies a projection; its key is only its interval.

    A re-timed slot already lives under a new sort key, so "this slot's commitment" is a row
    filter, not a key lookup — and a same-named slot at a different Show & Sell, or one this
    Scout no longer holds, is not the row the move must carry.
    """
    moved = _commitment_row(slot_id="slot-1", start_at="2026-11-07T11:00:00+00:00", end_at="2026-11-07T12:30:00+00:00")
    elsewhere = _commitment_row(slot_id="slot-1", event_id=OTHER_EVENT_ID, unit_campaign_id=OTHER_CAMPAIGN)

    found = ssm.active_commitment_for([elsewhere, moved], EVENT_ID, "slot-1")
    assert found is not None
    assert found["sk"] == moved["sk"], "the row the interval moved to, not the one left behind"
    assert ssm.active_commitment_for([elsewhere], EVENT_ID, "slot-1") is None
    assert ssm.active_commitment_for([_commitment_row(status=ssm.SIGNUP_CANCELLED)], EVENT_ID, "slot-1") is None


def test_a_signup_and_its_projection_are_reported_as_one_aggregate() -> None:
    """The pair §5.13 writes together is read together, and a half-missing pair is a violation.

    Returning the projection alongside each Scout holding the slot is what lets the resolver
    stage a move without a second read; reporting the Scouts whose projection is absent is what
    stops it staging a move at all. A cancelled projection does not count: it is history for a
    signup that no longer holds the slot, and the signup that is ACTIVE has no row describing
    the hours it is working.
    """
    pairs, violations = ssm.slot_commitment_state(
        show_and_sell_id=EVENT_ID,
        slot_id="slot-1",
        signups=[_signup_row(), _signup_row(profile=OTHER_PROFILE)],
        commitments_by_profile={PROFILE: [_commitment_row()], OTHER_PROFILE: []},
    )
    assert [profile for profile, _ in pairs] == [PROFILE]
    assert pairs[0][1][ssm.START_AT_ATTRIBUTE] == "2026-11-07T09:00:00+00:00"
    assert violations == [f"Scout {OTHER_PROFILE} holds a signup on this slot with no ACTIVE commitment row"]

    cancelled_pairs, cancelled_violations = ssm.slot_commitment_state(
        show_and_sell_id=EVENT_ID,
        slot_id="slot-1",
        signups=[_signup_row()],
        commitments_by_profile={PROFILE: [_commitment_row(status=ssm.SIGNUP_CANCELLED)]},
    )
    assert cancelled_pairs == []
    assert len(cancelled_violations) == 1


def test_capacity_cannot_drop_below_the_active_signups_a_slot_holds() -> None:
    signups = [_signup_row(), _signup_row(profile=OTHER_PROFILE)]
    violations = _revalidate(capacity=1, signups=signups)
    assert any("already holds 2 active signup" in problem for problem in violations)
    assert _revalidate(capacity=2, signups=signups) == []


def test_a_time_move_that_collides_with_a_sibling_signup_in_the_same_event_is_refused() -> None:
    """SLOT-04 inside one event: Devon holds slot-1 and slot-2; moving slot-2 onto
    slot-1's minutes puts Devon in two booths at once."""
    slot1 = _slot_row(slot_id="slot-1", start_at="2026-11-07T09:00:00+00:00", end_at="2026-11-07T10:30:00+00:00")
    slot2 = _slot_row(slot_id="slot-2", start_at="2026-11-07T11:00:00+00:00", end_at="2026-11-07T12:30:00+00:00")
    signups = [_signup_row(slot_id="slot-1"), _signup_row(slot_id="slot-2")]
    violations = _revalidate(
        slot_id="slot-2",
        start_at="2026-11-07T09:30:00+00:00",
        end_at="2026-11-07T11:00:00+00:00",
        slots=[slot1, slot2],
        signups=signups,
    )
    assert any("slot-1" in problem and PROFILE in problem for problem in violations)
    # A second collision for the same Scout does not stack a second sentence.
    slot3 = _slot_row(slot_id="slot-3", start_at="2026-11-07T08:00:00+00:00", end_at="2026-11-07T09:45:00+00:00")
    signups.append(_signup_row(slot_id="slot-3"))
    with_three = _revalidate(
        slot_id="slot-2",
        start_at="2026-11-07T09:30:00+00:00",
        end_at="2026-11-07T11:00:00+00:00",
        slots=[slot1, slot2, slot3],
        signups=signups,
    )
    assert sum(1 for problem in with_three if "already signed up for" in problem) == 1


def test_a_move_next_to_a_sibling_signup_stays_legal() -> None:
    """SLOT-03: adjacent is adjacent, even after a move. Slot-2 ending when slot-1
    starts is exactly what the rule permits."""
    slot1 = _slot_row(slot_id="slot-1", start_at="2026-11-07T09:00:00+00:00", end_at="2026-11-07T10:30:00+00:00")
    signups = [_signup_row(slot_id="slot-1")]
    assert (
        _revalidate(
            slot_id="slot-2",
            start_at="2026-11-07T10:30:00+00:00",
            end_at="2026-11-07T12:00:00+00:00",
            slots=[slot1],
            signups=signups,
        )
        == []
    )


def test_a_time_move_that_collides_with_another_show_and_sell_is_refused() -> None:
    """SLOT-04 across campaigns: the commitment projection at another Unit Campaign is
    the row §3.4's signup consults, so "legal for this Scout" must mean the same thing
    before and after the move."""
    other = _commitment_row(
        "slot-7",
        event_id=OTHER_EVENT_ID,
        unit_campaign_id=OTHER_CAMPAIGN,
        start_at="2026-11-07T11:00:00+00:00",
        end_at="2026-11-07T12:00:00+00:00",
    )
    signups = [_signup_row()]
    violations = _revalidate(
        start_at="2026-11-07T11:30:00+00:00",
        end_at="2026-11-07T12:30:00+00:00",
        signups=signups,
        commitments_by_profile={PROFILE: [other]},
    )
    assert any(OTHER_EVENT_ID in problem and PROFILE in problem for problem in violations)


def test_a_slot_never_conflicts_with_its_own_commitment_and_cancelled_rows_never_block() -> None:
    own = _commitment_row()
    cancelled_elsewhere = _commitment_row(
        "slot-7",
        event_id=OTHER_EVENT_ID,
        unit_campaign_id=OTHER_CAMPAIGN,
        start_at="2026-11-07T09:00:00+00:00",
        end_at="2026-11-07T10:30:00+00:00",
        status=ssm.SIGNUP_CANCELLED,
    )
    quiet = _commitment_row(
        "slot-8",
        event_id=OTHER_EVENT_ID,
        unit_campaign_id=OTHER_CAMPAIGN,
        start_at="2026-11-07T11:00:00+00:00",
        end_at="2026-11-07T12:00:00+00:00",
    )
    signups = [_signup_row(), _signup_row(profile=OTHER_PROFILE, status=ssm.SIGNUP_CANCELLED)]
    assert (
        _revalidate(
            signups=signups,
            commitments_by_profile={PROFILE: [own, cancelled_elsewhere, quiet]},
        )
        == []
    )


def test_a_signup_holding_a_missing_slot_row_does_not_fabricate_a_conflict() -> None:
    """A broken aggregate — a signup pointing at a slot this event no longer holds —
    is not a Scout double-booking; the commitment read is what guards the interval."""
    signups = [_signup_row(slot_id="slot-1"), _signup_row(slot_id="slot-ghost")]
    violations = _revalidate(
        start_at="2026-11-07T09:00:00+00:00",
        end_at="2026-11-07T10:30:00+00:00",
        slots=[],
        signups=signups,
    )
    assert violations == []


# --- Counter reconciliation (§5.12 transactional counter) --------------------------


@pytest.fixture
def aggregate(show_and_sells_table: Any) -> Any:
    show_and_sells_table.put_item(Item=_event_row())
    return show_and_sells_table


def test_the_counter_reconciliation_agrees_with_the_active_signups_by_default(aggregate: Any) -> None:
    aggregate.put_item(Item=_slot_row(active_signup_count=1))
    aggregate.put_item(Item=_signup_row())
    aggregate.put_item(Item=_signup_row(profile=OTHER_PROFILE, status=ssm.SIGNUP_CANCELLED))
    assert ssm.slot_counter_reconciliation(EVENT_ID) == []


def test_a_counter_that_disagrees_with_its_signup_rows_is_reported(aggregate: Any) -> None:
    aggregate.put_item(Item=_slot_row(slot_id="slot-1", active_signup_count=3))
    aggregate.put_item(Item=_slot_row(slot_id="slot-2", active_signup_count=0))
    aggregate.put_item(Item=_signup_row(slot_id="slot-2"))
    mismatches = ssm.slot_counter_reconciliation(EVENT_ID)
    assert mismatches == [("slot-1", 3, 0), ("slot-2", 0, 1)]
