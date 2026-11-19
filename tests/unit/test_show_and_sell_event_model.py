"""Leaf 3.1.1 — the ``ShowAndSell`` event model (data model §5.10, §6.4, §9.1).

Model-layer tests for the row §3.1 writes: ``SHOW_AND_SELL#<id> / METADATA`` with
Unit/Campaign scope, required location, optional address, immutable UTC start/end,
state, split override, We Owe default-off, cumulative ``productIds``, finalization
pointers, version, and cancellation audit. The §3.1.1 work order names the four
families this file is organized around — overlap, empty-product, immutable-time and
state-invariant — and each is asserted against the model rather than through a
resolver, because every later stage (§3.2 allocation, §3.3 slots, §3.4 signup, §3.6
finalization) re-reads this row and must inherit these rules rather than re-state
them.

The reads and conditional actions are exercised against moto so the key shapes are
the ones DynamoDB actually holds, and the projections are asserted by key SET rather
than by spot-checking fields: SEC-04 is a claim about what a participant surface may
never contain, and a claim about absence is only provable against a complete set.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List

import pytest

from src.utils import inventory_models as inv
from src.utils import show_and_sell_models as ssm
from src.utils.errors import AppError

EVENT_ID = "SSE#model-event"
OTHER_EVENT_ID = "SSE#model-other"
UNIT = "unit-pack-3149-aurora"
CAMPAIGN = "uc-pack-3149-fall-2026"
PROFILE = "PROFILE#prof-devon-fixture"
CAMPAIGN_SCOUT = "CAMPAIGN#camp-devon-fixture"
PRODUCT = "CATALOG#fixture-default#prod-1"
OTHER_PRODUCT = "CATALOG#fixture-default#prod-2"
ACTOR = "ACCOUNT#admin-fixture"

START = "2026-11-07T08:00:00+00:00"
END = "2026-11-07T13:00:00+00:00"
BEFORE = "2026-11-07T07:00:00+00:00"
DURING = "2026-11-07T10:00:00+00:00"
AFTER = "2026-11-07T14:00:00+00:00"


def _event_row(event_id: str = EVENT_ID, **overrides: Any) -> Dict[str, Any]:
    """A complete, legal METADATA row, with per-test overrides."""
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


def _stored_row(status: str, **overrides: Any) -> Dict[str, Any]:
    """A row whose stored state is set after the build.

    :func:`src.utils.show_and_sell_models.build_show_and_sell_item` refuses a state
    whose audit is missing, so a test that wants to assert the refusal has to build
    the broken row by hand — that is the point of the assertion.
    """
    row = dict(_event_row())
    row[ssm.STATUS_ATTRIBUTE] = status
    row.update(overrides)
    return row


def _slot_row(
    slot_id: str = "slot-1",
    *,
    event_id: str = EVENT_ID,
    status: str = ssm.SIGNUP_ACTIVE,
    active: int = 1,
    capacity: int = 4,
    version: int = 1,
) -> Dict[str, Any]:
    """A slot projection (§5.12) in the shape §3.3 will write it.

    §3.3 owns the authoritative builder; the event leaf only ever READS these rows,
    so the test builds the minimum the reads and projections consume.
    """
    return {
        "pk": ssm.show_and_sell_pk(event_id),
        "sk": ssm.slot_sk(slot_id),
        "entityType": ssm.ENTITY_TYPE_SLOT,
        ssm.SHOW_AND_SELL_ID_ATTRIBUTE: event_id,
        ssm.UNIT_CAMPAIGN_ID_ATTRIBUTE: CAMPAIGN,
        ssm.SLOT_ID_ATTRIBUTE: slot_id,
        ssm.LABEL_ATTRIBUTE: f"Slot {slot_id}",
        ssm.START_AT_ATTRIBUTE: START,
        ssm.END_AT_ATTRIBUTE: END,
        ssm.STATUS_ATTRIBUTE: status,
        ssm.CAPACITY_ATTRIBUTE: capacity,
        ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE: active,
        ssm.VERSION_ATTRIBUTE: version,
        ssm.CREATED_AT_ATTRIBUTE: BEFORE,
        ssm.UPDATED_AT_ATTRIBUTE: BEFORE,
    }


def _signup_row(
    slot_id: str = "slot-1",
    *,
    profile_id: str = PROFILE,
    event_id: str = EVENT_ID,
    status: str = ssm.SIGNUP_ACTIVE,
    actual_minutes: int = 0,
    version: int = 1,
) -> Dict[str, Any]:
    """A signup projection (§5.13) in the shape §3.4 will write it."""
    return {
        "pk": ssm.show_and_sell_pk(event_id),
        "sk": ssm.signup_sk(slot_id, profile_id),
        "entityType": ssm.ENTITY_TYPE_SIGNUP,
        ssm.SHOW_AND_SELL_ID_ATTRIBUTE: event_id,
        ssm.UNIT_CAMPAIGN_ID_ATTRIBUTE: CAMPAIGN,
        ssm.CAMPAIGN_ID_ATTRIBUTE: CAMPAIGN_SCOUT,
        ssm.PROFILE_ID_ATTRIBUTE: profile_id,
        ssm.SLOT_ID_ATTRIBUTE: slot_id,
        ssm.STATUS_ATTRIBUTE: status,
        ssm.START_AT_ATTRIBUTE: START,
        ssm.END_AT_ATTRIBUTE: END,
        ssm.ACTUAL_MINUTES_ATTRIBUTE: actual_minutes,
        ssm.SIGNED_UP_BY_ATTRIBUTE: ACTOR,
        ssm.CONFIRMED_BY_ATTRIBUTE: None,
        ssm.CONFIRMED_AT_ATTRIBUTE: None,
        ssm.VERSION_ATTRIBUTE: version,
        ssm.CREATED_AT_ATTRIBUTE: BEFORE,
        ssm.UPDATED_AT_ATTRIBUTE: BEFORE,
    }


def _commitment_row(
    slot_id: str = "slot-1",
    *,
    profile_id: str = PROFILE,
    event_id: str = EVENT_ID,
    status: str = ssm.SIGNUP_ACTIVE,
    version: int = 1,
) -> Dict[str, Any]:
    """The Scout-side commitment projection (§5.13) on ``unit_campaigns``."""
    return {
        "pk": ssm.commitment_pk(profile_id),
        "sk": ssm.commitment_sk(START, CAMPAIGN, slot_id),
        "entityType": "ShowAndSellCommitment",
        ssm.SHOW_AND_SELL_ID_ATTRIBUTE: event_id,
        ssm.UNIT_CAMPAIGN_ID_ATTRIBUTE: CAMPAIGN,
        ssm.SLOT_ID_ATTRIBUTE: slot_id,
        ssm.STATUS_ATTRIBUTE: status,
        ssm.START_AT_ATTRIBUTE: START,
        ssm.END_AT_ATTRIBUTE: END,
        ssm.VERSION_ATTRIBUTE: version,
        ssm.UPDATED_AT_ATTRIBUTE: BEFORE,
    }


def _allocation_row(
    product_id: str = PRODUCT,
    *,
    event_id: str = EVENT_ID,
    status: str = inv.ALLOCATION_OPEN,
    allocated: int = 10,
    sold: int = 0,
    released: int = 0,
    remaining: int = 10,
    version: int = 1,
) -> Dict[str, Any]:
    """An event allocation (§5.11) on the inventory table."""
    return {
        **ssm.event_allocation_key(CAMPAIGN, product_id, event_id),
        "entityType": inv.ALLOCATION_ENTITY_TYPE,
        ssm.UNIT_CAMPAIGN_ID_ATTRIBUTE: CAMPAIGN,
        inv.PRODUCT_ID_ATTRIBUTE: product_id,
        ssm.SHOW_AND_SELL_ID_ATTRIBUTE: event_id,
        ssm.START_AT_ATTRIBUTE: START,
        ssm.END_AT_ATTRIBUTE: END,
        ssm.STATUS_ATTRIBUTE: status,
        inv.ALLOCATED_QTY: allocated,
        inv.SOLD_QTY: sold,
        inv.RELEASED_QTY: released,
        inv.REMAINING_QTY: remaining,
        ssm.VERSION_ATTRIBUTE: version,
        ssm.CREATED_AT_ATTRIBUTE: BEFORE,
        ssm.UPDATED_AT_ATTRIBUTE: BEFORE,
    }


def _iso(days: float) -> str:
    """An instant a fixed number of days from the real clock.

    The resolvers derive state from ``utc_now_iso()``, so a fixture whose
    "future" is a literal date goes stale the day the calendar crosses it. These
    instants are relative to the run, which is what keeps ``SCHEDULED`` meaning
    scheduled on every date the suite runs on.
    """
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


# --- Key layout (§6.4) -----------------------------------------------------------


def test_event_keys_are_the_documented_partition_and_sort_key() -> None:
    assert ssm.show_and_sell_pk(EVENT_ID) == f"SHOW_AND_SELL#{EVENT_ID}"
    assert ssm.event_metadata_key(EVENT_ID) == {"pk": f"SHOW_AND_SELL#{EVENT_ID}", "sk": "METADATA"}
    assert ssm.slot_sk("slot-1") == "SLOT#slot-1"
    assert ssm.slot_key(EVENT_ID, "slot-1") == {
        "pk": f"SHOW_AND_SELL#{EVENT_ID}",
        "sk": "SLOT#slot-1",
    }
    assert ssm.signup_sk("slot-1", PROFILE) == f"SIGNUP#slot-1#{PROFILE}"
    assert ssm.commitment_sk(START, CAMPAIGN, "slot-1").startswith("COMMITMENT#")
    assert ssm.commitment_key(PROFILE, START, CAMPAIGN, "slot-1") == {
        "pk": ssm.commitment_pk(PROFILE),
        "sk": ssm.commitment_sk(START, CAMPAIGN, "slot-1"),
    }
    assert ssm.commitment_guard_key(PROFILE)["sk"] == ssm.COMMITMENT_GUARD_SK


def test_allocation_key_sits_in_the_same_partition_as_the_balance_it_competes_with() -> None:
    key = ssm.event_allocation_key(CAMPAIGN, PRODUCT, EVENT_ID)
    assert key["pk"] == inv.inventory_pk(CAMPAIGN)
    assert key["sk"] == inv.allocation_sk(PRODUCT, EVENT_ID)


# --- Normalization and validation (§3.4) ----------------------------------------


def test_new_ids_are_unique_and_uuid_shaped() -> None:
    first, second = ssm.new_show_and_sell_id(), ssm.new_show_and_sell_id()
    assert first != second
    assert len(first.split("-")) == 5


@pytest.mark.parametrize("value", ["SSE#fixture-morning", "plain-id", "a#b##c".replace("##", "#-")])
def test_event_ids_are_accepted_in_the_shapes_this_application_spells_them(value: str) -> None:
    assert ssm.normalize_event_id(value) == value


@pytest.mark.parametrize("value", ["", "   ", None, 7])
def test_an_empty_event_id_is_refused(value: Any) -> None:
    with pytest.raises(AppError) as raised:
        ssm.normalize_event_id(value)
    assert raised.value.error_code is ssm.ErrorCode.INVALID_INPUT


@pytest.mark.parametrize("value", ["#lead", "trail#", "a##b"])
def test_an_empty_key_segment_is_refused_because_two_rows_would_share_one_key(value: str) -> None:
    with pytest.raises(AppError):
        ssm.normalize_event_id(value)


def test_location_and_address_carry_the_api_contract_limits() -> None:
    assert ssm.normalize_location_name("  Aurora lot  ") == "Aurora lot"
    assert ssm.normalize_address(None) is None
    assert ssm.normalize_address("12 Main St") == "12 Main St"
    with pytest.raises(AppError):
        ssm.normalize_location_name("   ")
    with pytest.raises(AppError):
        ssm.normalize_location_name("x" * (ssm.MAX_LOCATION_NAME_LENGTH + 1))
    with pytest.raises(AppError):
        ssm.normalize_address("x" * (ssm.MAX_ADDRESS_LENGTH + 1))


def test_cancellation_reason_is_required_and_capped_like_every_other_reason() -> None:
    assert ssm.normalize_cancellation_reason("  storm warning  ") == "storm warning"
    assert len(ssm.normalize_cancellation_reason("x" * ssm.MAX_REASON_LENGTH)) == ssm.MAX_REASON_LENGTH
    for rejected in (None, "", "   ", 5, "x" * (ssm.MAX_REASON_LENGTH + 1)):
        with pytest.raises(AppError):
            ssm.normalize_cancellation_reason(rejected)


def test_moments_are_canonicalized_to_one_utc_spelling_so_sort_keys_compare_as_instants() -> None:
    assert ssm.normalize_moment("2026-11-07T01:00:00Z", "startAt") == "2026-11-07T01:00:00+00:00"
    assert ssm.normalize_moment("2026-11-07T01:00:00-07:00", "startAt") == "2026-11-07T08:00:00+00:00"
    for rejected in (None, "", "  ", "2026-11-07T08:00:00", "yesterday", 1_700_000_000):
        with pytest.raises(AppError):
            ssm.normalize_moment(rejected, "startAt")


def test_the_interval_is_validated_once_and_only_order_is_enforced() -> None:
    assert ssm.normalize_interval(START, END) == (START, END)
    # SSE-03: no assumed hour or half-hour, so a 41-minute event is legal.
    assert ssm.normalize_interval(START, "2026-11-07T08:41:00+00:00") == (START, "2026-11-07T08:41:00+00:00")
    for start_at, end_at in ((START, START), (END, START), (None, END), (START, None)):
        with pytest.raises(AppError):
            ssm.normalize_interval(start_at, end_at)


def test_split_and_we_owe_defaults_are_the_product_defaults() -> None:
    assert ssm.normalize_split_method(None) == ssm.DEFAULT_SPLIT_METHOD
    assert ssm.normalize_split_method("TIME_WORKED") == "TIME_WORKED"
    assert ssm.normalize_we_owe_enabled(None) is False
    assert ssm.normalize_we_owe_enabled(True) is True
    with pytest.raises(AppError):
        ssm.normalize_split_method("SPLIT_BY_ALLOCATION")
    with pytest.raises(AppError):
        ssm.normalize_we_owe_enabled("yes")


def test_status_names_are_the_six_states_of_section_9_1_and_nothing_else() -> None:
    assert ssm.normalize_event_status("cancelled") == "CANCELLED"
    assert ssm.EVENT_STATUSES == {
        "SCHEDULED",
        "ACTIVE",
        "ENDED",
        "REOPENED",
        "FINALIZED",
        "CANCELLED",
    }
    assert ssm.DERIVED_STATUSES == {"SCHEDULED", "ACTIVE", "ENDED"}
    with pytest.raises(AppError):
        ssm.normalize_event_status("ABANDONED")


def test_product_ids_are_cumulative_and_never_capped_but_never_repeated() -> None:
    many = [f"CATALOG#c#prod-{index}" for index in range(500)]
    assert len(ssm.normalize_product_ids(many)) == 500
    assert ssm.normalize_product_ids(None) == []
    assert ssm.normalize_product_ids([PRODUCT, PRODUCT, OTHER_PRODUCT]) == [PRODUCT, OTHER_PRODUCT]
    with pytest.raises(AppError):
        ssm.normalize_product_ids(PRODUCT)
    with pytest.raises(AppError):
        ssm.normalize_product_ids([PRODUCT, ""])


def test_merging_products_keeps_older_entries_first_and_never_drops_one() -> None:
    merged = ssm.merge_product_ids([PRODUCT], [OTHER_PRODUCT, PRODUCT])
    assert merged == [PRODUCT, OTHER_PRODUCT]
    assert ssm.merge_product_ids(None, [PRODUCT]) == [PRODUCT]
    assert ssm.merge_product_ids([PRODUCT], []) == [PRODUCT]


def test_versions_are_positive_integers_and_a_bool_is_never_a_version() -> None:
    assert ssm.normalize_required_version(3) == 3
    assert ssm.normalize_required_version(Decimal("4")) == 4
    # A decimal string is the resolver's to coerce, not the model's: by the time a
    # version reaches here it is a number, so a string here is a caller bug.
    for rejected in (None, 0, -1, True, "3", Decimal("0")):
        with pytest.raises(AppError):
            ssm.normalize_required_version(rejected)


# --- Row shape and invariants (§5.10) -------------------------------------------


def test_the_created_row_carries_every_section_5_10_field_and_nothing_else() -> None:
    item = _event_row(address="12 Main St")
    assert item["pk"] == f"SHOW_AND_SELL#{EVENT_ID}"
    assert item["sk"] == "METADATA"
    assert item["entityType"] == ssm.ENTITY_TYPE_EVENT
    assert item[ssm.UNIT_ID_ATTRIBUTE] == UNIT
    assert item[ssm.UNIT_CAMPAIGN_ID_ATTRIBUTE] == CAMPAIGN
    assert item[ssm.STATUS_ATTRIBUTE] == "SCHEDULED"
    assert item[ssm.SPLIT_METHOD_ATTRIBUTE] == ssm.DEFAULT_SPLIT_METHOD
    assert item[ssm.WE_OWE_ENABLED_ATTRIBUTE] is False
    assert item[ssm.PRODUCT_IDS_ATTRIBUTE] == []
    assert item[ssm.APPROVED_FINALIZATION_ID_ATTRIBUTE] is None
    assert item[ssm.LATEST_FINALIZATION_ID_ATTRIBUTE] is None
    assert item[ssm.VERSION_ATTRIBUTE] == 1
    assert item[ssm.CREATED_AT_ATTRIBUTE] == item[ssm.UPDATED_AT_ATTRIBUTE] == BEFORE
    assert item[ssm.CREATED_BY_ATTRIBUTE] == ACTOR
    assert item[ssm.CANCELLED_BY_ATTRIBUTE] is None
    assert item[ssm.CANCELLED_AT_ATTRIBUTE] is None
    assert item[ssm.CANCELLATION_REASON_ATTRIBUTE] is None
    assert set(item) <= set(ssm.EVENT_ROW_ATTRIBUTES)
    assert set(ssm.EVENT_ROW_ATTRIBUTES) - set(item) == {ssm.ROUNDING_DRAFT_ATTRIBUTE}, (
        "the cents-rounding draft is Wave 5's to write; every other §5.10 field lands at create"
    )


def test_an_omitted_address_stays_off_the_row_rather_than_becoming_an_empty_one() -> None:
    assert ssm.ADDRESS_ATTRIBUTE not in _event_row()
    assert _event_row(address="12 Main St")[ssm.ADDRESS_ATTRIBUTE] == "12 Main St"


def test_overlap_is_never_a_reason_to_refuse_an_event_interval() -> None:
    # SSE-02: two events may run at the same time; the refusal lives in §3.2's
    # concurrent-stock rule, so the model states the interval fact only. Two events
    # on identical times both build, because nothing here may reject the second.
    first = _event_row()
    second = _event_row(OTHER_EVENT_ID)
    assert first[ssm.START_AT_ATTRIBUTE] == second[ssm.START_AT_ATTRIBUTE]
    assert ssm.intervals_overlap(first[ssm.START_AT_ATTRIBUTE], first[ssm.END_AT_ATTRIBUTE], START, END) is True
    assert ssm.intervals_overlap(START, END, END, "2026-11-07T15:00:00+00:00") is False
    assert ssm.intervals_overlap(START, END, "2026-11-07T07:00:00+00:00", START) is False
    assert ssm.intervals_overlap(START, END, "2026-11-07T09:00:00+00:00", "2026-11-07T09:30:00+00:00") is True


def test_an_empty_product_list_is_a_legal_event_not_a_placeholder() -> None:
    item = _event_row()
    assert item[ssm.PRODUCT_IDS_ATTRIBUTE] == []
    assert ssm.event_invariant_violations(item) == []


def test_the_interval_and_state_and_shape_invariants_are_each_named() -> None:
    broken = dict(_event_row())
    broken[ssm.END_AT_ATTRIBUTE] = START
    assert "endAt must be after startAt" in ssm._interval_violations(broken)
    missing = dict(_event_row())
    missing.pop(ssm.START_AT_ATTRIBUTE)
    assert "both startAt and endAt are required" in ssm._interval_violations(missing)

    assert "a FINALIZED event requires approvedFinalizationId" in ssm._state_violations(
        _stored_row(ssm.STATUS_FINALIZED)
    )
    reopened = _stored_row(ssm.STATUS_REOPENED, **{ssm.APPROVED_FINALIZATION_ID_ATTRIBUTE: "FIN#1"})
    assert "a REOPENED event must have approvedFinalizationId cleared" in ssm._state_violations(reopened)
    assert "a CANCELLED event requires cancellationReason and its audit" in ssm._state_violations(
        _stored_row(ssm.STATUS_CANCELLED)
    )
    unknown = dict(_event_row())
    unknown[ssm.STATUS_ATTRIBUTE] = "ABANDONED"
    assert ssm._state_violations(unknown) != []

    repeated = dict(_event_row())
    repeated[ssm.PRODUCT_IDS_ATTRIBUTE] = [PRODUCT, PRODUCT]
    assert "productIds must not repeat a product" in ssm._row_shape_violations(repeated)
    not_a_list = dict(_event_row())
    not_a_list[ssm.PRODUCT_IDS_ATTRIBUTE] = PRODUCT
    assert "productIds must be a list" in ssm._row_shape_violations(not_a_list)
    extra = dict(_event_row())
    extra["surprise"] = "not in the model"
    assert "attributes the model leaves out: surprise" in ssm._row_shape_violations(extra)


def test_the_state_invariants_are_enforced_where_the_row_is_built() -> None:
    for status in (ssm.STATUS_FINALIZED, ssm.STATUS_CANCELLED):
        with pytest.raises(AppError):
            _event_row(status=status)
    finalized = _stored_row(ssm.STATUS_FINALIZED)
    assert ssm.event_invariant_violations(finalized) == [
        "a FINALIZED event requires approvedFinalizationId"
    ]
    finalized[ssm.APPROVED_FINALIZATION_ID_ATTRIBUTE] = "FIN#1"
    assert ssm.event_invariant_violations(finalized) == []
    assert ssm.event_invariant_violations(_stored_row(ssm.STATUS_REOPENED)) == []


def test_only_the_four_settings_are_writable_and_a_smuggled_time_is_refused() -> None:
    changes = ssm.writable_changes({"locationName": "New lot", "address": None})
    assert changes == {"locationName": "New lot", "address": None}
    assert ssm.WRITABLE_FIELDS == {"locationName", "address", "splitMethod", "weOweEnabled"}
    for smuggled in ("startAt", "endAt", "status", "version", "productIds", "unitId"):
        with pytest.raises(AppError) as raised:
            ssm.writable_changes({smuggled: "x"})
        assert smuggled in str(raised.value)


# --- State derivation (§9.1) ----------------------------------------------------


def test_the_clock_states_are_derived_from_the_immutable_interval() -> None:
    row = _event_row()
    assert ssm.derive_event_status(row, BEFORE) == "SCHEDULED"
    assert ssm.derive_event_status(row, DURING) == "ACTIVE"
    assert ssm.derive_event_status(row, AFTER) == "ENDED"
    # The boundary belongs to the later state: the event is running AT startAt and
    # ended AT endAt, which is what makes "cancellable only before startAt" decidable.
    assert ssm.derive_event_status(row, START) == "ACTIVE"
    assert ssm.derive_event_status(row, END) == "ENDED"
    assert ssm.derive_event_status(row) in ssm.DERIVED_STATUSES


def test_a_workflow_state_is_reported_as_written_and_never_derived_away() -> None:
    for stored in (ssm.STATUS_CANCELLED, ssm.STATUS_FINALIZED, ssm.STATUS_REOPENED):
        assert ssm.derive_event_status(_stored_row(stored), AFTER) == stored


def test_the_editable_matrix_matches_api_contract_section_3_5() -> None:
    assert ssm.EDITABLE_STATUSES == {"SCHEDULED", "ACTIVE", "ENDED", "REOPENED"}
    assert ssm.event_is_editable(_event_row(), BEFORE) is True
    assert ssm.require_editable(_event_row(), DURING) == "ACTIVE"
    assert ssm.require_editable(_event_row(), AFTER) == "ENDED"
    assert ssm.require_editable(_stored_row(ssm.STATUS_REOPENED), AFTER) == "REOPENED"
    for stored in (ssm.STATUS_FINALIZED, ssm.STATUS_CANCELLED):
        row = _stored_row(stored)
        with pytest.raises(AppError) as raised:
            ssm.require_editable(row, AFTER)
        assert raised.value.error_code is ssm.ErrorCode.CONFLICT
        assert raised.value.details["status"] == stored


def test_cancellation_needs_both_the_scheduled_state_and_the_clock_before_start() -> None:
    assert ssm.require_cancellable(_event_row(), BEFORE) == "SCHEDULED"
    at_start = dict(_event_row())
    at_start[ssm.STATUS_ATTRIBUTE] = "SCHEDULED"
    for moment, expected in ((START, "ACTIVE"), (DURING, "ACTIVE"), (AFTER, "ENDED")):
        with pytest.raises(AppError) as raised:
            ssm.require_cancellable(at_start, moment)
        assert raised.value.error_code is ssm.ErrorCode.CONFLICT
        assert raised.value.details["status"] == expected
    for stored in (ssm.STATUS_CANCELLED, ssm.STATUS_FINALIZED, ssm.STATUS_REOPENED):
        with pytest.raises(AppError):
            ssm.require_cancellable(_stored_row(stored), BEFORE)
    # A stored SCHEDULED whose interval has already passed is not cancellable: the
    # second guard catches the state the clock moved past.
    with pytest.raises(AppError):
        ssm.require_cancellable(_event_row(), AFTER)


def test_an_open_we_owe_obligation_blocks_turning_we_owe_off_and_a_closed_one_does_not() -> None:
    assert ssm.we_owe_disable_blocked([]) is False
    assert ssm.we_owe_disable_blocked([{"status": ssm.WE_OWE_STATUS_CLOSED}]) is False
    assert ssm.we_owe_disable_blocked([{"status": ssm.WE_OWE_STATUS_CLOSED}, {"status": ssm.WE_OWE_STATUS_OPEN}]) is True


# --- Reads (§6.3, §6.4, SEC-06) -------------------------------------------------


@pytest.fixture
def tables_are_ready(show_and_sells_table: Any, inventory_table: Any, unit_campaigns_table: Any) -> Dict[str, Any]:
    """The three tables an event aggregate's reads reach, with nothing in them yet."""
    return {"show_and_sells": show_and_sells_table, "inventory": inventory_table, "unit_campaigns": unit_campaigns_table}


def test_a_missing_event_reads_as_none_and_as_not_found(tables_are_ready: Dict[str, Any]) -> None:
    assert ssm.read_show_and_sell(EVENT_ID) is None
    with pytest.raises(AppError) as raised:
        ssm.load_show_and_sell_or_not_found(EVENT_ID)
    assert raised.value.error_code is ssm.ErrorCode.NOT_FOUND


def test_an_event_written_by_the_model_reads_back_consistently(tables_are_ready: Dict[str, Any]) -> None:
    tables_are_ready["show_and_sells"].put_item(Item=_event_row())
    assert ssm.load_show_and_sell_or_not_found(EVENT_ID)[ssm.LOCATION_NAME_ATTRIBUTE] == "Aurora fire station lot"


def test_the_campaign_read_finds_events_through_the_index_and_ignores_other_row_kinds(
    tables_are_ready: Dict[str, Any],
) -> None:
    tables_are_ready["show_and_sells"].put_item(Item=_event_row(OTHER_EVENT_ID, start_at=END, end_at="2026-11-08T20:00:00+00:00"))
    tables_are_ready["show_and_sells"].put_item(Item=_event_row())
    tables_are_ready["show_and_sells"].put_item(Item=_slot_row())
    tables_are_ready["show_and_sells"].put_item(
        Item={"pk": "GARBAGE#orphan", "sk": "METADATA", "unitCampaignId": CAMPAIGN, "startAt": START}
    )
    events = ssm.list_campaign_events(CAMPAIGN)
    assert len(events) == 2, "the slot row and the key-only row are not events"
    starts = [str(row[ssm.START_AT_ATTRIBUTE]) for row in events]
    assert starts == sorted(starts), "a schedule is answered soonest first"
    assert ssm.list_campaign_events("uc-none") == []


def test_allocations_are_found_through_product_ids_not_through_an_index(tables_are_ready: Dict[str, Any]) -> None:
    tables_are_ready["inventory"].put_item(Item=_allocation_row())
    tables_are_ready["inventory"].put_item(Item=_allocation_row(product_id=OTHER_PRODUCT))
    assert ssm.event_allocations(_event_row()) == []
    with_products = _event_row(product_ids=[PRODUCT, OTHER_PRODUCT, "CATALOG#fixture-default#prod-404"])
    found = ssm.event_allocations(with_products)
    assert len(found) == 2, "a product with no allocation row simply contributes nothing"
    assert all(row["entityType"] == inv.ALLOCATION_ENTITY_TYPE for row in found)
    assert len(ssm.open_allocations(with_products)) == 2


def test_closed_allocations_are_not_released_twice(tables_are_ready: Dict[str, Any]) -> None:
    tables_are_ready["inventory"].put_item(Item=_allocation_row(status=inv.ALLOCATION_CANCELLED))
    with_products = _event_row(product_ids=[PRODUCT])
    assert len(ssm.event_allocations(with_products)) == 1
    assert ssm.open_allocations(with_products) == []


def test_slot_and_signup_and_we_owe_rows_come_from_the_event_partition(tables_are_ready: Dict[str, Any]) -> None:
    tables_are_ready["show_and_sells"].put_item(Item=_slot_row())
    tables_are_ready["show_and_sells"].put_item(Item=_slot_row("slot-2", active=0))
    tables_are_ready["show_and_sells"].put_item(Item=_signup_row())
    tables_are_ready["show_and_sells"].put_item(Item=_signup_row("slot-2", status=ssm.SIGNUP_CANCELLED))
    tables_are_ready["show_and_sells"].put_item(
        Item={"pk": ssm.show_and_sell_pk(EVENT_ID), "sk": "WE_OWE#we-1", ssm.STATUS_ATTRIBUTE: ssm.WE_OWE_STATUS_OPEN}
    )
    assert len(ssm.event_slot_rows(EVENT_ID)) == 2
    assert len(ssm.event_signup_rows(EVENT_ID)) == 2
    assert len(ssm.event_we_owe_rows(EVENT_ID)) == 1
    assert [str(row[ssm.SLOT_ID_ATTRIBUTE]) for row in ssm.active_signups(EVENT_ID)] == ["slot-1"]
    assert [str(row[ssm.SLOT_ID_ATTRIBUTE]) for row in ssm.slots_holding_signups(EVENT_ID)] == ["slot-1"]


def test_commitments_are_read_from_the_scout_partition_and_filterable_by_event(
    tables_are_ready: Dict[str, Any],
) -> None:
    tables_are_ready["unit_campaigns"].put_item(Item=_commitment_row())
    tables_are_ready["unit_campaigns"].put_item(Item=_commitment_row("slot-2", event_id=OTHER_EVENT_ID))
    assert len(ssm.commitment_rows(PROFILE)) == 2
    assert [str(row[ssm.SLOT_ID_ATTRIBUTE]) for row in ssm.commitment_rows(PROFILE, EVENT_ID)] == ["slot-1"]
    assert ssm.commitment_rows("PROFILE#prof-none") == []


def test_a_scout_without_a_guard_has_none_and_a_scout_with_one_has_it(tables_are_ready: Dict[str, Any]) -> None:
    assert ssm.read_commitment_guard(PROFILE) is None
    tables_are_ready["unit_campaigns"].put_item(
        Item={"pk": ssm.commitment_pk(PROFILE), "sk": ssm.COMMITMENT_GUARD_SK, "commitmentVersion": 3}
    )
    assert ssm.read_commitment_guard(PROFILE)["commitmentVersion"] == 3


# --- Conditional actions (§8.8, §8.10) ------------------------------------------


def test_create_is_a_conditional_insert_so_two_creates_of_one_id_cannot_both_land() -> None:
    kind, payload = ssm.put_show_and_sell_action(_event_row())
    assert kind == "Put"
    assert payload["ConditionExpression"] == "attribute_not_exists(#pk) AND attribute_not_exists(#sk)"
    assert payload["Item"]["pk"] == {"S": f"SHOW_AND_SELL#{EVENT_ID}"}
    assert payload["Item"][ssm.WE_OWE_ENABLED_ATTRIBUTE] == {"BOOL": False}
    assert payload["Item"][ssm.PRODUCT_IDS_ATTRIBUTE] == {"L": []}, (
        "a list attribute must stay a list: the shared scalar encoder would store the text '[]'"
    )


def test_an_update_carries_the_read_version_and_the_cleared_address_is_removed_not_emptied() -> None:
    kind, payload = ssm.update_event_settings_action(
        show_and_sell_id=EVENT_ID,
        expected_version=4,
        changes={ssm.ADDRESS_ATTRIBUTE: None, ssm.LOCATION_NAME_ATTRIBUTE: "New lot"},
        updated_by_account_id=ACTOR,
        updated_at=AFTER,
    )
    assert kind == "Update"
    assert "#version = :expectedVersion" in payload["ConditionExpression"]
    assert "#address = :address" in payload["UpdateExpression"]
    assert "#locationName = :locationName" in payload["UpdateExpression"]
    assert payload["ExpressionAttributeValues"][":address"] == {"NULL": True}
    assert payload["ExpressionAttributeValues"][":version"] == {"N": "5"}


def test_cancellation_conditions_on_version_and_on_the_event_not_already_being_finalized() -> None:
    kind, payload = ssm.cancel_event_action(
        show_and_sell_id=EVENT_ID,
        expected_version=2,
        cancelled_by_account_id=ACTOR,
        cancelled_at=AFTER,
        reason="storm warning",
    )
    assert kind == "Update"
    assert "#version = :expectedVersion" in payload["ConditionExpression"]
    assert "#status <> :finalizedCondition" in payload["ConditionExpression"]
    assert payload["ExpressionAttributeValues"][f":{ssm.CANCELLATION_REASON_ATTRIBUTE}"] == {"S": "storm warning"}


def test_releasing_an_allocation_moves_its_whole_remainder_and_refuses_a_terminal_state() -> None:
    kind, payload = ssm.cancel_allocation_action(
        allocation=_allocation_row(released=2, remaining=8), released_qty=10, updated_at=AFTER
    )
    assert kind == "Update"
    values = payload["ExpressionAttributeValues"]
    assert values[f":{inv.RELEASED_QTY}"] == {"N": "10"}
    assert values[f":{inv.REMAINING_QTY}"] == {"N": "0"}
    assert "#status <> :closedCondition" in payload["ConditionExpression"]
    with pytest.raises(AppError):
        ssm.cancel_allocation_action(
            allocation=_allocation_row(status=inv.ALLOCATION_CANCELLED), released_qty=1, updated_at=AFTER
        )


def test_the_release_movement_is_the_only_delta_a_cancellation_moves() -> None:
    kind, payload = ssm.event_release_movement_action(
        event=_event_row(),
        allocation=_allocation_row(),
        released_qty=7,
        actor_account_id=ACTOR,
        occurred_at=AFTER,
        idempotency_key="cancel-1",
        allocation_version=2,
    )
    assert kind == "Put"
    item = payload["Item"]
    assert item["movementType"] == {"S": inv.EVENT_RELEASE}
    assert item["assignedDelta"] == {"N": "-7"}
    for unchanged in (
        inv.KERNEL_PHYSICAL_DELTA,
        inv.WITH_SCOUT_DELTA,
        inv.SOLD_POSSESSION_DELTA,
        inv.COUNCIL_ON_ORDER_DELTA,
    ):
        assert item[unchanged] == {"N": "0"}, f"a cancellation must not move {unchanged}"


def test_zeroing_a_slot_and_cancelling_a_signup_and_a_commitment_all_condition_on_the_read_version(
    tables_are_ready: Dict[str, Any],
) -> None:
    slot = ssm.zero_slot_counter_action(
        show_and_sell_id=EVENT_ID, slot_id="slot-1", expected_version=3, updated_at=AFTER
    )
    signup = ssm.cancel_signup_action(
        show_and_sell_id=EVENT_ID, slot_id="slot-1", profile_id=PROFILE, expected_version=2, updated_at=AFTER
    )
    commitment = ssm.cancel_commitment_action(commitment=_commitment_row(), updated_at=AFTER)
    for kind, payload in (slot, signup, commitment):
        assert kind == "Update"
        assert "#version = :expectedVersion" in payload["ConditionExpression"]
    assert slot[1]["ExpressionAttributeValues"][f":{ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE}"] == {"N": "0"}
    assert signup[1]["ExpressionAttributeValues"][f":{ssm.STATUS_ATTRIBUTE}"] == {"S": ssm.SIGNUP_CANCELLED}
    assert commitment[1]["TableName"] == tables_are_ready["unit_campaigns"].table_name


def test_the_commitment_guard_increments_in_the_write_itself() -> None:
    kind, payload = ssm.bump_commitment_guard_action(profile_id=PROFILE, updated_at=AFTER)
    assert kind == "Update"
    assert "#commitmentVersion = #commitmentVersion + :one" in payload["UpdateExpression"]
    assert "attribute_exists(#commitmentVersion)" in payload["ConditionExpression"]
    assert payload["ExpressionAttributeValues"][":one"] == {"N": "1"}


def test_expression_values_stay_scalar_and_row_values_get_the_total_encoder() -> None:
    encoded = ssm.wire_values({":a": "text", ":b": 3, ":c": True, ":d": None})
    assert encoded == {":a": {"S": "text"}, ":b": {"N": "3"}, ":c": {"BOOL": True}, ":d": {"NULL": True}}
    assert ssm.wire_item_value(Decimal("3.50")) == {"N": "3.50"}
    assert ssm.wire_item_value([PRODUCT, OTHER_PRODUCT]) == {"L": [{"S": PRODUCT}, {"S": OTHER_PRODUCT}]}
    assert ssm.wire_item_value(("a",)) == {"L": [{"S": "a"}]}
    row = ssm.wire_item(_event_row(product_ids=[PRODUCT]))
    assert row[ssm.PRODUCT_IDS_ATTRIBUTE] == {"L": [{"S": PRODUCT}]}
    assert row[ssm.VERSION_ATTRIBUTE] == {"N": "1"}
    assert row[ssm.APPROVED_FINALIZATION_ID_ATTRIBUTE] == {"NULL": True}


# --- Projections (API contract §3.2, SEC-04) ------------------------------------


def test_the_admin_projection_reports_the_derived_state_and_the_full_audit() -> None:
    row = dict(_event_row(address="12 Main St"))
    row[ssm.STATUS_ATTRIBUTE] = ssm.STATUS_CANCELLED
    row[ssm.CANCELLED_BY_ATTRIBUTE] = ACTOR
    row[ssm.CANCELLED_AT_ATTRIBUTE] = AFTER
    row[ssm.CANCELLATION_REASON_ATTRIBUTE] = "storm warning"
    payload = ssm.event_admin_payload(row, AFTER)
    assert payload[ssm.STATUS_ATTRIBUTE] == ssm.STATUS_CANCELLED
    assert payload[ssm.CANCELLATION_REASON_ATTRIBUTE] == "storm warning"
    assert payload[ssm.VERSION_ATTRIBUTE] == 1
    assert payload[ssm.UNIT_ID_ATTRIBUTE] == UNIT
    assert payload[ssm.ADDRESS_ATTRIBUTE] == "12 Main St"
    assert set(payload) == set(ssm.EVENT_ROW_ATTRIBUTES) - {"pk", "sk", "entityType", ssm.ROUNDING_DRAFT_ATTRIBUTE}


def test_the_participant_projection_is_the_allowlist_and_carries_no_administrative_field() -> None:
    opportunity = ssm.opportunity_payload(
        _event_row(we_owe_enabled=True),
        timezone_name="America/Denver",
        slots=[_slot_row()],
        signups=[_signup_row()],
        now_iso=BEFORE,
    )
    assert set(opportunity) == {
        ssm.SHOW_AND_SELL_ID_ATTRIBUTE,
        ssm.LOCATION_NAME_ATTRIBUTE,
        ssm.ADDRESS_ATTRIBUTE,
        ssm.START_AT_ATTRIBUTE,
        ssm.END_AT_ATTRIBUTE,
        ssm.STATUS_ATTRIBUTE,
        ssm.SPLIT_METHOD_ATTRIBUTE,
        ssm.WE_OWE_ENABLED_ATTRIBUTE,
        "timezone",
        "eventVersion",
        "slots",
        "mySignups",
    }
    assert opportunity[ssm.STATUS_ATTRIBUTE] == "SCHEDULED"
    assert opportunity["eventVersion"] == 1
    assert opportunity["slots"][0]["openCapacity"] == 3
    assert opportunity["slots"][0]["capacity"] == 4
    assert opportunity["mySignups"][0]["signupVersion"] == 1

    forbidden = {
        ssm.UNIT_ID_ATTRIBUTE,
        ssm.UNIT_CAMPAIGN_ID_ATTRIBUTE,
        ssm.PRODUCT_IDS_ATTRIBUTE,
        ssm.APPROVED_FINALIZATION_ID_ATTRIBUTE,
        ssm.LATEST_FINALIZATION_ID_ATTRIBUTE,
        ssm.VERSION_ATTRIBUTE,
        ssm.CREATED_AT_ATTRIBUTE,
        ssm.UPDATED_AT_ATTRIBUTE,
        ssm.CREATED_BY_ATTRIBUTE,
        ssm.UPDATED_BY_ATTRIBUTE,
        ssm.CANCELLED_BY_ATTRIBUTE,
        ssm.CANCELLED_AT_ATTRIBUTE,
        ssm.CANCELLATION_REASON_ATTRIBUTE,
        "allocations",
        "openCapacity" + "s",
        ssm.SIGNED_UP_BY_ATTRIBUTE,
        ssm.CONFIRMED_BY_ATTRIBUTE,
        ssm.CONFIRMED_AT_ATTRIBUTE,
        inv.ALLOCATED_QTY,
        inv.SOLD_QTY,
        inv.REMAINING_QTY,
        inv.KERNEL_PHYSICAL_QTY,
    }
    surfaces: List[Any] = [opportunity, opportunity["slots"], opportunity["mySignups"]]
    for surface in surfaces:
        for name in forbidden:
            assert name not in surface, f"{name} must never reach a participant surface"


def test_the_admin_side_projections_carry_the_counters_and_audit_a_kernel_needs() -> None:
    allocation = ssm.allocation_payload(_allocation_row(sold=3, released=1, remaining=6))
    assert allocation["allocatedQty"] == 10
    assert allocation["soldQty"] == 3
    assert allocation["releasedQty"] == 1
    assert allocation["remainingQty"] == 6
    assert allocation[ssm.STATUS_ATTRIBUTE] == inv.ALLOCATION_OPEN

    slot = ssm.slot_admin_payload(_slot_row(capacity=5, active=2, version=4))
    assert slot[ssm.CAPACITY_ATTRIBUTE] == 5
    assert slot[ssm.ACTIVE_SIGNUP_COUNT_ATTRIBUTE] == 2
    assert slot[ssm.VERSION_ATTRIBUTE] == 4

    signup = ssm.signup_admin_payload(_signup_row(actual_minutes=45, version=2))
    assert signup["actualMinutes"] == 45
    assert signup[ssm.SIGNED_UP_BY_ATTRIBUTE] == ACTOR
    assert signup[ssm.VERSION_ATTRIBUTE] == 2

    summary = ssm.signup_summary_payload(_signup_row(actual_minutes=45, version=2))
    assert summary["actualMinutes"] == 45
    assert summary["signupVersion"] == 2
    assert ssm.SIGNED_UP_BY_ATTRIBUTE not in summary
    assert ssm.CONFIRMED_BY_ATTRIBUTE not in summary


def test_projections_default_a_missing_counter_to_zero_rather_than_raising() -> None:
    thin = {
        "pk": "x",
        "sk": "y",
        ssm.SHOW_AND_SELL_ID_ATTRIBUTE: EVENT_ID,
        ssm.SLOT_ID_ATTRIBUTE: "slot-9",
        ssm.START_AT_ATTRIBUTE: START,
        ssm.END_AT_ATTRIBUTE: END,
    }
    assert ssm.slot_opportunity_payload(thin)["capacity"] == 0
    assert ssm.slot_opportunity_payload(thin)["openCapacity"] == 0
    assert ssm.signup_summary_payload(thin)["actualMinutes"] == 0
    assert ssm.signup_summary_payload(thin)["signupVersion"] == 1
