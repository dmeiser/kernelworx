"""The Stage 3 deployed-stack support module (§3.6.2).

Nothing here talks to AWS.  What it does prove is the part of §3.6.2 that can be proven
offline: that the Stage 3 suite sends documents and payloads the shipped SDL actually
accepts (``API-FIX-01``), that its fixtures reproduce themselves and plan an event in
every derived state (``EVT-M-01/02/03``), that every conflict pair earns a refusal the
table records with its exact code and sentence (``SS-SM-05/06/11``), that the idempotency
inputs and replay/fingerprint answers are pinned (``API-FIX-03``), that the ICS validator
only ever accepts what the browser's own emitter produces (CAL-01/CAL-02), and that the
cleanup plan speaks the Stage 2 vocabulary with the TTL gate closed.

The live suite itself is the Stage 3 smoke spec; it is marked ``slow`` and no CI path
runs it, so these are the only executable checks its contract gets short of a deployed
run.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from src.utils import mutations, show_and_sell_models
from src.utils.errors import AppError
from tests.e2e.utils import show_sell_graphql
from tests.e2e.utils import show_sell_stage2_support as stage2
from tests.e2e.utils import show_sell_stage3_support as stage3

REPO_ROOT = Path(__file__).resolve().parents[2]
SDL_PATH = REPO_ROOT / "tofu" / "application" / "schema" / "schema.graphql"


def _sdl() -> str:
    """The SDL this repository ships, which is what the deployed build's API is built from."""
    return SDL_PATH.read_text(encoding="utf-8")


def _minutes(start_at: str, end_at: str) -> int:
    start = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
    return int((end - start).total_seconds() // 60)


def _ics(uid: str) -> str:
    body = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "PRODID:-//KernelWorx//Show And Sell//EN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        "DTSTART;TZID=America/Denver:20260309T090000",
        "DTEND;TZID=America/Denver:20260309T103000",
        "SUMMARY:Show & Sell - Riverside Grange",
        "LOCATION:Riverside Grange",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "".join(f"{line}\r\n" for line in body)


# ---------------------------------------------------------------------------
# The documents and payloads match the shipped SDL (API-FIX-01)
# ---------------------------------------------------------------------------


def test_every_stage_three_endpoint_has_a_document_and_a_builder() -> None:
    """No Stage 3 acceptance id is exercised with an ad-hoc query string."""
    assert set(stage3.STAGE_THREE_DOCUMENTS) == set(stage3.STAGE_THREE_WRITES) | set(stage3.STAGE_THREE_READS)
    assert set(stage3._BUILDERS) == set(stage3.STAGE_THREE_WRITES)
    for field, document in stage3.STAGE_THREE_DOCUMENTS.items():
        assert field in document, f"{field}'s document never names the field it sends"


def test_the_stage_three_documents_match_the_shipped_sdl() -> None:
    """Every Stage 3 argument name the suite sends, and every input key it builds, is declared."""
    assert stage3.stage_three_contract_violations(_sdl()) == []


def test_the_stage_three_selections_match_the_shipped_sdl() -> None:
    """Every field the Stage 3 documents select is declared by the type that answers it."""
    assert stage3.stage_three_selection_violations(_sdl()) == []


def test_a_renamed_argument_is_named_rather_than_mis_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    """The check is not vacuous: an argument the SDL does not declare stops the lane by name."""
    documents = dict(stage3.STAGE_THREE_DOCUMENTS)
    documents["showAndSells"] = documents["showAndSells"].replace(
        "showAndSells(unitCampaignId: $unitCampaignId", "showAndSells(campaignId: $unitCampaignId"
    )
    monkeypatch.setattr(stage3, "STAGE_THREE_DOCUMENTS", documents)
    violations = stage3.stage_three_contract_violations(_sdl())
    assert any("showAndSells" in line and "campaignId" in line for line in violations)


def test_a_renamed_field_is_named_with_its_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """A selection the answer does not carry fails the contract before AppSync parse does."""
    documents = dict(stage3.STAGE_THREE_DOCUMENTS)
    documents["showAndSell"] = documents["showAndSell"].replace("productIds", "products")
    monkeypatch.setattr(stage3, "STAGE_THREE_DOCUMENTS", documents)
    violations = stage3.stage_three_selection_violations(_sdl())
    assert any("products" in line and "ShowAndSellAdmin" in line for line in violations)


def test_a_payload_key_the_sdl_never_declared_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """An input builder that drifts from the SDL names the key and the input type."""
    samples = dict(stage3._SAMPLES)
    samples["CreateShowAndSellInput"] = {**samples["CreateShowAndSellInput"], "eventName": "Hall Sale"}
    monkeypatch.setattr(stage3, "_SAMPLES", samples)
    violations = stage3.stage_three_contract_violations(_sdl())
    assert any("createShowAndSell" in line and "eventName" in line for line in violations)


def test_the_support_documents_are_the_stage_two_documents_verbatim() -> None:
    """The Stage 3 lane's non-Stage-3 calls are imported, not copied — one owner, no drift."""
    assert stage3.STAGE_THREE_SUPPORT_DOCUMENTS == stage2.STAGE_TWO_SUPPORT_DOCUMENTS
    assert "listScoutCampaignJoins" not in stage3.STAGE_THREE_SUPPORT_DOCUMENTS
    assert not stage2._field_exists(_sdl(), "Query", "listScoutCampaignJoins")


def test_the_shipped_sdl_carries_every_stage_three_endpoint() -> None:
    assert stage3.missing_stage_three_endpoints(_sdl()) == []


def test_an_earlier_build_stops_the_suite_and_names_the_endpoints() -> None:
    """A build predating Stage 3 answers none of these: the lane says *stopped*, not *passed*."""
    sdl = _sdl().replace("signupScoutForShowAndSellSlot(", "signUpScoutForShowAndSellSlot(", 1)
    missing = stage3.missing_stage_three_endpoints(sdl)
    assert missing == ["signupScoutForShowAndSellSlot"]


def test_the_introspection_gate_reports_what_the_deployed_api_answers() -> None:
    """The live gate keeps module order and reports exactly what the API's own schema carries."""
    names = [*stage3.STAGE_THREE_WRITES, *stage3.STAGE_THREE_READS]
    schema = {
        "__schema": {
            "queryType": {"fields": [{"name": n} for n in stage3.STAGE_THREE_READS[:-1]]},
            "mutationType": {"fields": [{"name": n} for n in stage3.STAGE_THREE_WRITES]},
        }
    }
    answered = stage3.stage_three_fields_in_schema(schema)
    assert answered == names[:-1]


# ---------------------------------------------------------------------------
# The two workflow states Stage 3 cannot reach are reported, never faked
# (EVT-M-02/03)
# ---------------------------------------------------------------------------


def test_finalize_and_reopen_are_absent_and_those_states_report_blocked() -> None:
    """§5's mutations are Stage 5's barrier: the lane blocks FINALIZED/REOPENED by name."""
    sdl = _sdl()
    assert not stage2._field_exists(sdl, "Mutation", "finalizeShowAndSell")
    assert not stage2._field_exists(sdl, "Mutation", "reopenShowAndSell")
    assert stage3.STAGE_THREE_BLOCKED_STATE_FIXTURES == ("FINALIZED", "REOPENED")
    for state in stage3.STAGE_THREE_BLOCKED_STATE_FIXTURES:
        assert state in sdl  # the enum carries the state; only the write is missing
        assert state not in json.dumps(stage3.stage_three_fixture(0), default=str)
    assert "never fakes them" in stage3.BLOCKED_STATE_FIXTURE_NOTE


# ---------------------------------------------------------------------------
# The fixture reproduces itself and plans every derived state (EVT-M-01/02/03)
# ---------------------------------------------------------------------------


def test_the_fixture_reproduces_itself_byte_for_byte() -> None:
    """Same seed, same bytes — ids, names, keys and intervals all pinned by the lane token."""
    assert json.dumps(stage3.stage_three_fixture(0), sort_keys=True) == json.dumps(
        stage3.stage_three_fixture(0), sort_keys=True
    )
    assert stage3.lane_token(0) == stage3.lane_token(0)
    assert len(stage3.lane_token(0)) == 12


def test_a_different_seed_moves_the_lane_token_and_therefore_every_key() -> None:
    assert stage3.lane_token(0) != stage3.lane_token(1)
    assert stage3.stage_three_fixture(1)["lane"] != stage3.stage_three_fixture(0)["lane"]


def test_the_fixture_plans_an_event_in_every_derived_state_at_t0() -> None:
    """ENDED, ACTIVE and SCHEDULED-then-CANCELLED all exist in the tree without a time-travel write."""
    fixture = stage3.stage_three_fixture(0)
    t0 = datetime.fromisoformat(stage3.T0_UTC.replace("Z", "+00:00"))

    def window(name: str) -> tuple[datetime, datetime]:
        event = fixture["events"][name]
        start = datetime.fromisoformat(event["startAt"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(event["endAt"].replace("Z", "+00:00"))
        return start, end

    start, end = window("ended")
    assert end < t0
    start, end = window("active")
    assert start < t0 < end
    for name in ("slots", "cancellation", "four-boxes", "big", "confirm"):
        start, end = window(name)
        assert t0 < start
    assert fixture["t0"] == stage3.T0_UTC


def test_the_slots_are_90_120_and_180_minutes_with_capacity_one_and_hundred() -> None:
    """SS-SM-05 walkthrough shape: 90/120/180-minute slots at capacity 1 and at capacity 100."""
    slots = stage3.stage_three_fixture(0)["slots"]
    assert _minutes(slots["first-sales"]["startAt"], slots["first-sales"]["endAt"]) == 90
    assert _minutes(slots["midday"]["startAt"], slots["midday"]["endAt"]) == 120
    assert _minutes(slots["full-booth"]["startAt"], slots["full-booth"]["endAt"]) == 180
    assert slots["first-sales"]["capacity"] == 1 == stage3.MIN_SLOT_CAPACITY
    assert slots["full-booth"]["capacity"] == 100 == stage3.MAX_SLOT_CAPACITY


def test_the_catalog_products_and_allocation_targets_pin_the_ledger() -> None:
    """Three products carry cents prices, and each event's targets are a product/quantity list."""
    fixture = stage3.stage_three_fixture(0)
    assert len(fixture["products"]) == 3
    assert all(p["cents"] > 0 for p in fixture["products"].values())
    refs = {product["ref"] for product in fixture["products"].values()}
    for targets in fixture["allocations"].values():
        for _profile, product, quantity in targets:
            assert product in refs
            assert quantity >= 0


def test_twenty_slots_is_the_boundary_and_the_21st_is_refused() -> None:
    """SS-SM-05: the boundary event holds exactly ``MAX_SLOTS_PER_EVENT`` slots; the 21st earns SLOT_LIMIT."""
    fixture = stage3.stage_three_fixture(0)
    assert len(fixture["bigSlots"]) == stage3.MAX_SLOTS_PER_EVENT == 20
    answer = stage3.stage_three_refusal("slot-limit")
    assert answer["code"] == "CONFLICT"
    assert answer["subcode"] == "SLOT_LIMIT"


def test_capacity_zero_and_101_are_refused_by_the_same_table_row() -> None:
    answer = stage3.stage_three_refusal("capacity-range")
    assert answer["code"] == "INVALID_INPUT"
    assert "must be between" in answer["sentence"]
    assert stage3.MIN_SLOT_CAPACITY == 1
    assert stage3.MAX_SLOT_CAPACITY == 100
    assert stage3.stage_three_refusal("work-over-duration")["subcode"] == "WORK_OVER_DURATION"


def test_the_model_itself_refuses_capacity_zero_and_101() -> None:
    """The refusal the table records is the model's own sentence at the boundary."""
    for bad in (0, 101):
        with pytest.raises(AppError) as excinfo:
            show_and_sell_models.normalize_capacity(bad)
        assert excinfo.value.error_code == "INVALID_INPUT"
        assert f"must be between {stage3.MIN_SLOT_CAPACITY} and {stage3.MAX_SLOT_CAPACITY}" in excinfo.value.message


def test_the_confirm_batch_carries_101_rows_and_the_cap_names_the_refusal() -> None:
    """SS-SM-06: the fixture plans one row past the 100-row cap, and the table answers the refusal."""
    fixture = stage3.stage_three_fixture(0)
    assert fixture["confirmRows"] == stage3.MAX_WORK_LINES + 1 == 101
    answer = stage3.stage_three_refusal("work-batch-cap")
    assert answer["code"] == "INVALID_INPUT"
    assert answer["sentence"] == "may be confirmed at once."


def test_zero_minutes_un_confirms_a_work_row() -> None:
    """``actualMinutes = 0`` is a legal payload — the SDL spells zero the un-confirm."""
    payload = stage3.confirm_work_input(
        "SHOW#x",
        1,
        [("SLOT#x", "PROFILE#x", 0)],
        idempotency_key=stage3.idempotency_key_for("confirmShowAndSellWork", "ab"),
    )
    assert payload["work"][0]["actualMinutes"] == 0
    over = stage3.stage_three_refusal("work-over-duration")
    assert over["subcode"] == "WORK_OVER_DURATION"


def test_the_dst_pair_straddles_the_spring_forward_at_the_same_wall_clock() -> None:
    """SS-SM-11's calendar facts: 09:00 local on both sides of 2026-03-08, UTC offsets that differ."""
    assert stage3.DST_SPRING_FORWARD.month == 3 and stage3.DST_SPRING_FORWARD.day == 8
    saturday = stage3.denver_wall_clock(stage3.DST_SATURDAY_START_UTC)
    monday = stage3.denver_wall_clock(stage3.DST_MONDAY_START_UTC)
    assert saturday.endswith("09:00 MST")
    assert monday.endswith("09:00 MDT")
    fixture = stage3.stage_three_fixture(0)
    event = fixture["events"]["dst"]
    for name in ("dst-saturday", "dst-monday"):
        slot = fixture["slots"][name]
        assert event["startAt"] <= slot["startAt"] and slot["endAt"] <= event["endAt"]


# ---------------------------------------------------------------------------
# Idempotency (API-FIX-01/03)
# ---------------------------------------------------------------------------


def test_builders_put_an_idempotency_input_on_every_write() -> None:
    """Every Stage 3 mutation takes ``IdempotencyInput``; no builder may omit it."""
    for type_name, sample in stage3._SAMPLES.items():
        assert "idempotency" in sample, f"{type_name} carries no idempotency input"
        assert "idempotencyKey" in sample["idempotency"]


def test_idempotency_keys_are_deterministic_unique_and_legal() -> None:
    lane = stage3.lane_token(0)
    keys = [stage3.idempotency_key_for(op, lane) for op in stage3.STAGE_THREE_WRITES]
    assert keys == [stage3.idempotency_key_for(op, lane) for op in stage3.STAGE_THREE_WRITES]
    assert len(set(keys)) == len(keys)
    assert all(1 <= len(key) <= 128 for key in keys)
    assert stage3.idempotency_key_for("createShowAndSell", lane, "retry") == f"{keys[0]}-retry"


def test_the_replay_and_changed_fingerprint_answers_are_recorded() -> None:
    """API-FIX-03: a replay returns the recorded answer; a changed body earns the fingerprint refusal."""
    replay = stage3.stage_three_refusal("idempotency-replayed")
    assert replay["code"] == "REPLAYED"
    assert "IDEM-01" in stage3.STAGE_THREE_REFUSALS["idempotency-replayed"]
    changed = stage3.stage_three_refusal("idempotency-changed")
    assert changed["code"] == "INVALID_INPUT"
    assert changed["subcode"] == "IDEMPOTENCY_FINGERPRINT_MISMATCH"


# ---------------------------------------------------------------------------
# Write shapes the SDL pins
# ---------------------------------------------------------------------------


def test_a_signup_names_the_scout_campaign_and_the_profile_and_no_version() -> None:
    """The signup input carries the roster pair; its version is the aggregate's, not the caller's."""
    payload = stage3.signup_input("SHOW#x", "SLOT#x", "CAMP#x", "PROFILE#x", idempotency_key="k")
    assert {"campaignId": "CAMP#x", "profileId": "PROFILE#x"}.items() <= payload.items()
    assert "version" not in payload


def test_an_upsert_edit_names_the_slot_and_its_version_in_nested_shape() -> None:
    create = stage3.upsert_slot_input("SHOW#x", 1, "A", "B", 2, idempotency_key="k")
    assert "slotId" not in create and "slotVersion" not in create
    edit = stage3.upsert_slot_input("SHOW#x", 1, "A", "B", 2, slot_id="SLOT#x", slot_version=2, idempotency_key="k")
    assert edit["slotVersion"] == {"expectedVersion": 2}


def test_cancel_signup_conditions_on_the_signup_version_not_the_event() -> None:
    payload = stage3.cancel_signup_input("SHOW#x", "SLOT#x", "PROFILE#x", 4, idempotency_key="k")
    assert payload["version"] == {"expectedVersion": 4}
    assert payload["profileId"] == "PROFILE#x"


def test_a_cancel_event_input_names_the_reason_it_must_give() -> None:
    payload = stage3.cancel_event_input("SHOW#x", 1, "Vendor conflict", idempotency_key="k")
    assert payload["reason"] == "Vendor conflict"
    assert payload["version"] == {"expectedVersion": 1}


def test_bind_ids_replaces_placeholders_and_refuses_unbound_ones() -> None:
    bound = stage3.bind_ids({"event": {"ref": "event.slots"}}, {"event.slots": "SHOW#1"})
    assert bound["event"]["ref"] == "SHOW#1"
    with pytest.raises(KeyError, match="event.dst"):
        stage3.bind_ids({"event": {"ref": "event.dst"}}, {"event.slots": "SHOW#1"})


# ---------------------------------------------------------------------------
# The conflict table (SS-SM-05/06/11)
# ---------------------------------------------------------------------------


def test_the_conflict_pairs_name_a_recorded_refusal_each() -> None:
    """Every §3.6.2 collision resolves to the table's code, subcode and acceptance ids."""
    assert stage3.STAGE_THREE_CONFLICT_PAIRS
    for row in stage3.STAGE_THREE_CONFLICT_PAIRS:
        assert row["op"] in stage3.STAGE_THREE_WRITES
        answer = stage3.STAGE_THREE_REFUSAL_ANSWERS[str(row["refusal"])]
        assert row["code"] == answer["code"]
        assert row["subcode"] == answer["subcode"]
        assert stage3.STAGE_THREE_REFUSALS[str(row["refusal"])]
    refusals = {str(row["refusal"]) for row in stage3.STAGE_THREE_CONFLICT_PAIRS}
    for required in ("duplicate-signup", "capacity-full", "cross-campaign-overlap", "concurrent-over-assignment"):
        assert required in refusals
    joined_acceptance = " ".join(str(row["acceptance"]) for row in stage3.STAGE_THREE_CONFLICT_PAIRS)
    for smoke in ("SS-SM-05", "SS-SM-06", "SS-SM-11"):
        assert smoke in joined_acceptance


def test_conflict_row_refuses_an_op_that_is_not_a_stage_three_write() -> None:
    with pytest.raises(KeyError):
        stage3.conflict_row("finalizeShowAndSell", "slot-limit")


def test_the_refusal_sentences_are_the_raising_source_words() -> None:
    """The table quotes the server, not the other way round: every recorded sentence is a
    literal fragment of the source file that raises it."""
    sources: dict[str, str] = {}
    for refusal in stage3.STAGE_THREE_REFUSAL_ANSWERS.values():
        sentence, source = refusal["sentence"], refusal["source"]
        if not sentence:
            continue
        if source not in sources:
            sources[source] = (REPO_ROOT / source).read_text(encoding="utf-8")
        assert sentence in sources[source], f"{sentence!r} is not a fragment of {source}"


def test_a_matching_error_answer_satisfies_a_refusal() -> None:
    """SS-SM-06 step 3: the duplicate answer the lane observed matches the table."""
    observed = [{"code": "CONFLICT", "message": "This Scout already holds a place in this slot."}]
    assert stage3.refusal_violations("duplicate-signup", observed) == []


def test_a_mismatched_error_answer_is_named_against_the_table() -> None:
    observed = [{"code": "NOT_FOUND", "message": "no such slot"}]
    violations = stage3.refusal_violations("capacity-full", observed)
    assert violations and "CONFLICT" in violations[0] and "This slot is full" in violations[0]


def test_the_error_code_is_read_from_all_four_homes() -> None:
    """An APPSYNC_JS resolver answers ``errorType`` with no ``extensions``; the check reads it."""
    payload = {
        "errors": [
            {"message": "This Scout already holds a place in this slot.", "errorType": "CONFLICT"},
            {"message": "unrelated", "extensions": {"code": "INVALID_INPUT"}},
        ]
    }
    summaries = show_sell_graphql.error_summaries(payload)
    assert stage3.refusal_violations("duplicate-signup", summaries) == []
    assert stage3.refusal_violations_from_response("duplicate-signup", payload) == []


# ---------------------------------------------------------------------------
# Calendar data and the browser's ICS (CAL-01/CAL-02)
# ---------------------------------------------------------------------------


def _dto(**overrides: Any) -> dict[str, Any]:
    dto = stage3.calendar_invite_dto(
        unit_id="U#x",
        unit_campaign_id="UC#x",
        unit_campaign_name="Avery",
        show_and_sell_id="S#x",
        slot_id="SL#x",
        profile_id="P#x",
        location_name="Riverside Grange",
        slot_start_at=stage3.DST_MONDAY_START_UTC,
        slot_end_at=stage3.DST_MONDAY_END_UTC,
        slot_label="DST Monday",
    )
    dto.update(overrides)
    return dto


def test_the_calendar_dto_shape_matches_the_sdl_type() -> None:
    members = stage2._type_member_map(_sdl())["CalendarInviteData"]
    for field in stage3.CALENDAR_DTO_FIELDS:
        assert field in members, f"CalendarInviteData declares no {field}"
    assert stage3.calendar_dto_violations(_dto()) == []


def test_a_dto_the_browser_cannot_turn_into_an_invite_is_named() -> None:
    assert any("timezone" in line for line in stage3.calendar_dto_violations(_dto(timezone="Mars/Phobos")))
    assert any("slotStartAt" in line for line in stage3.calendar_dto_violations(_dto(slotStartAt="")))
    assert any(
        "does not run after" in line
        for line in stage3.calendar_dto_violations(_dto(slotEndAt=stage3.DST_MONDAY_START_UTC))
    )


def test_the_invite_uid_is_the_browser_identity_tuple() -> None:
    uid = stage3.calendar_invite_uid("UC#x", "S#x", "SL#x", "P#x")
    assert uid == "kernelworx-show-and-sell-UC#x-S#x-SL#x-P#x@kernelworx.app"
    assert stage3.calendar_invite_uid("UC#x", "S#x", "SL#x", "P#x") == uid  # stable across downloads


def _good_uid() -> str:
    return stage3.calendar_invite_uid("UC#x", "S#x", "SL#x", "P#x")


def test_the_browser_ics_passes_the_validator() -> None:
    """CAL-01: the validator accepts what ``buildInvite`` actually emits — CRLF, TZID, stable UID."""
    assert stage3.validate_ics(_ics(_good_uid()), _good_uid()) == ()


def test_an_ics_without_tzid_is_rejected() -> None:
    """A floating-UTC DTSTART is the failure mode CAL-02 exists to catch."""
    body = _ics(_good_uid()).replace("DTSTART;TZID=America/Denver:20260309T090000", "DTSTART:20260309T150000")
    problems = stage3.validate_ics(body, _good_uid())
    assert any("DTSTART" in line and "TZID" in line for line in problems)


def test_an_overlong_line_is_rejected() -> None:
    """RFC 5545 folding: the browser breaks lines at 73 octets; an unfolded break fails."""
    long_summary = "SUMMARY:" + "x" * (stage3.ICS_MAX_LINE_OCTETS + 1)
    body = _ics(_good_uid()).replace("SUMMARY:Show & Sell - Riverside Grange", long_summary)
    problems = stage3.validate_ics(body, _good_uid())
    assert any("octets" in line for line in problems)


def test_a_uid_that_moves_between_downloads_is_rejected() -> None:
    """CAL-02: the UID is the signup's identity; a second download with another UID is a different file."""
    problems = stage3.validate_ics(_ics(_good_uid()), stage3.calendar_invite_uid("UC#y", "S#x", "SL#x", "P#x"))
    assert any("UID" in line for line in problems)


def test_a_calendar_file_without_the_publish_method_is_rejected() -> None:
    body = _ics(_good_uid()).replace("METHOD:PUBLISH\r\n", "")
    problems = stage3.validate_ics(body, _good_uid())
    assert any("METHOD:PUBLISH" in line for line in problems)


def test_no_server_artifact_is_in_the_checks() -> None:
    """RPT-00: the checks own only what the browser produces; no download URL is a stage 3 concept."""
    assert any("browser" in check for check in stage3.ICS_CHECKS)
    assert any("no server artifact" in check.lower() or "no download URL" in check for check in stage3.ICS_CHECKS)


# ---------------------------------------------------------------------------
# The ledger (EVT-M-04 posture, §7 derived quantities)
# ---------------------------------------------------------------------------


def test_the_ledger_holds_when_sold_credit_and_cash_reconcile() -> None:
    sold = [{"productId": "PROD#x", "units": 3, "cents": 100}]
    credits = [{"profileId": "PROFILE#x", "cents": 100}]
    assert stage3.stage_three_ledger_invariants(sold, credits, 200, 300) == ()


def test_a_ledger_that_breaks_an_invariant_is_named() -> None:
    sold = [{"productId": "PROD#x", "units": 3, "cents": 100}]
    problems = stage3.stage_three_ledger_invariants(sold, [{"profileId": "P#x", "cents": 150}], 100, 300)
    assert any("we-owe mismatch" in p for p in problems)
    problems = stage3.stage_three_ledger_invariants(sold, [], 300, 250)
    assert any("cash mismatch" in p for p in problems)
    problems = stage3.stage_three_ledger_invariants([{"productId": "P", "units": -1, "cents": 100}], [], -100, -100)
    assert any("negative" in p for p in problems)


def test_assigned_by_product_sums_the_allocation_rows() -> None:
    rows = [
        {"productId": "PROD#x", "allocatedQty": 12},
        {"productId": "PROD#x", "allocatedQty": 5},
        {"productId": "PROD#y", "allocatedQty": 1},
    ]
    assert stage3.assigned_by_product(rows) == {"PROD#x": 17, "PROD#y": 1}


def test_the_stock_snapshot_carries_only_the_columns_stage_three_must_not_move() -> None:
    snapshot = stage3.stock_snapshot([{"productId": "PROD#x", "kernelPhysicalQty": 40, "withScoutQty": 6}])
    assert snapshot["PROD#x"] == dict.fromkeys(stage3.STAGE_THREE_STOCK_COLUMNS, 0) | {
        "kernelPhysicalQty": 40,
        "withScoutQty": 6,
    }


# ---------------------------------------------------------------------------
# Cleanup (SS-SM-05/06/11 lane cleanup, TTL-gated)
# ---------------------------------------------------------------------------


def test_the_cleanup_plan_uses_the_stage_two_vocabulary() -> None:
    plan = stage3.stage_three_cleanup_plan("ab12")
    assert plan and all({"acceptance", "summary", "result"} <= set(row) for row in plan)
    assert all(row["result"] == stage2.CLEANUP_OBSERVED for row in plan)
    joined = " ".join(row["summary"] for row in plan)
    assert "idem" in joined and str(stage3.MARKER_TTL_SECONDS // 3600) in joined


def test_a_failed_cleanup_row_raises_the_stage_three_error() -> None:
    rows = [
        stage2.cleanup_row("SS-SM-06", "signup cancelled"),
        stage2.cleanup_row("SS-SM-11", "event left live", stage2.CLEANUP_FAILED),
    ]
    with pytest.raises(stage3.StageThreeCleanupError):
        stage3.assert_stage_three_cleanup_clean(rows, strict=False)
    stage3.assert_stage_three_cleanup_clean(rows[:1], strict=False)


def test_a_lane_business_row_never_rides_the_ttl() -> None:
    """The table's TTL block is for markers only: an expiring signup is a violation, not a plan."""
    problems = stage3.ttl_gate_violations(
        [{"class": "signup", "expiresAtEpoch": 1_700_000_000}, {"class": "marker", "expiresAtEpoch": None}]
    )
    assert len(problems) == 2
    clean = stage3.ttl_gate_violations(
        [{"class": "signup", "expiresAtEpoch": None}, {"class": "marker", "expiresAtEpoch": 1}]
    )
    assert clean == []
    assert "marker" not in stage3.NEVER_EXPIRING_ROW_CLASSES


def test_the_ttl_expectation_is_seven_days_from_minting() -> None:
    """The gate agrees with the writer: same attribute and seven days as ``src/utils/mutations.py``."""
    expectation = stage3.stage_three_ttl_expectation(1_000)
    assert expectation["attribute"] == mutations.MARKER_TTL_ATTRIBUTE == stage3.MARKER_TTL_ATTRIBUTE
    assert expectation["expiresAtEpoch"] == 1_000 + mutations.MARKER_TTL_SECONDS == 1_000 + stage3.MARKER_TTL_SECONDS


def test_sweep_tokens_are_typed_and_add_only_idem() -> None:
    """Stage 3 sweeps with Stage 2's tokens plus ``idem`` — no free text."""
    tokens = stage3.stage_three_sweep_tokens("ab12")
    kinds = [token.split("=", 1)[0] for token in tokens]
    assert kinds == [*stage2.LANE_TOKEN_KINDS, "idem"]
    assert stage3.STAGE_THREE_LANE_TOKEN_KINDS == (*stage2.LANE_TOKEN_KINDS, "idem")
    assert all(token == f"{kind}=ab12" for kind, token in zip(kinds, tokens, strict=True))
