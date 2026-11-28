"""The Stage 3 deployed-stack support module (§3.6.2).

Nothing here talks to AWS or to a deployed endpoint.  What this module proves is the part of §3.6.2
that can be proven offline, and it proves it by executing the layer rather than reading strings out of
it: that the Stage 3 suite sends documents and payloads the shipped SDL accepts (``API-FIX-01``); that
every fixture instant is an offset from the ``T0`` setup handed over, in any year, with the DST pair
computed and *checked* against ``zoneinfo`` (FIX-AC-03, SS-SM-11); that the tree carries every state
and boundary §3.6.2 names by name — 16 products, four-box events, 90/120/180-minute slots, 20 slots,
101 work rows, removed members, stale versions, race barriers, and FINALIZED/REOPENED as
builder-produced states (``EVT-M-01/02/03``); that the refusal table quotes the raising source
(``SS-SM-05/06/11``); that the ICS validator accepts the bytes ``buildInvite`` really wrote and
refuses what it did not (CAL-01/CAL-02); and that the cleanup plan names a table and a key per row in
the Stage 2 verdict vocabulary, TTL gate closed.

The half that *performs* the work — the transport-driven conflict lane, the stale-version and
removed-member fixtures, the race barriers, the DynamoDB state-fixture builder, and the
delete-and-read-back teardown — is exercised in ``tests/unit/test_show_sell_stage3_scenario.py``.
Both helper modules live under ``tests/e2e/utils`` rather than in a spec, because importing a Stage 3
spec from the unit suite would fail on its ``slow`` marker under the root pytest configuration.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from src.utils import mutations, show_and_sell_models
from src.utils.errors import AppError
from tests.e2e.utils import show_sell_graphql
from tests.e2e.utils import show_sell_stage2_support as stage2
from tests.e2e.utils import show_sell_stage3_support as stage3

REPO_ROOT = Path(__file__).resolve().parents[2]
SDL_PATH = REPO_ROOT / "tofu" / "application" / "schema" / "schema.graphql"
FIXTURES_DIR = REPO_ROOT / "tests" / "e2e" / "fixtures"

#: The scenario setup time the walkthroughs are written against.
DEFAULT_T0 = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)

#: A ``T0`` five years on, in a year no fixture in this repository was ever written for, used to prove the
#: tree follows the clock rather than a calendar.  It reads the *same Unit wall clock* as
#: :data:`DEFAULT_T0` (07:30 MST, standard time in both Nov and Jan) on purpose: a fixture anchored on a
#: day offset and a wall clock then has to move by exactly the ``T0`` shift, so an exact comparison is the
#: right one and a copied date shows up as a path that did not move.  No assertion below quotes a date
#: from the module under test: they are all about offsets and spreads.
OTHER_YEAR_T0 = datetime(2031, 1, 10, 14, 30, tzinfo=timezone.utc)


def _sdl() -> str:
    """The SDL this repository ships, which is what the deployed build's API is built from."""
    return SDL_PATH.read_text(encoding="utf-8")


def _clock(
    t0: datetime = DEFAULT_T0, *, scenario_id: str = "SS-SM-05", lane_id: str = "L02", attempt_id: str = "a9"
) -> stage3.ScenarioClock:
    """A clock built the way FIX-AC-03 hands one over: ``T0`` plus the four ``DATA_ID`` parts."""
    return stage3.ScenarioClock(
        t0=t0,
        run_id=f"{int(t0.timestamp())}-ff00aa",
        scenario_id=scenario_id,
        lane_id=lane_id,
        attempt_id=attempt_id,
    )


def _fixture(t0: datetime = DEFAULT_T0) -> dict[str, Any]:
    return stage3.stage_three_fixture(_clock(t0))


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _minutes(start_at: str, end_at: str) -> int:
    return int((_instant(end_at) - _instant(start_at)).total_seconds() // 60)


def _ics_instant(iso: str) -> str:
    """The emitter's own ``icsUtc`` rule, so a capture is checkable against the DTO it was built from."""
    date_part, _, rest = iso.partition("T")
    clock, _, _zone = rest.partition("Z")
    return f"{date_part.replace('-', '')}T{clock.split('.')[0].replace(':', '')}Z"


def _fixture_instants(node: Any, path: str = "") -> dict[str, datetime]:
    """Every persisted UTC instant in the tree, keyed by where it was found."""
    found: dict[str, datetime] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            found.update(_fixture_instants(value, f"{path}.{key}"))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            found.update(_fixture_instants(value, f"{path}[{index}]"))
    elif isinstance(node, str) and len(node) == 20 and node.endswith("Z"):
        try:
            found[path] = _instant(node)
        except ValueError:
            pass
    return found


def _capture(name: str) -> str:
    """One captured ``buildInvite`` download, read with universal newlines switched off.

    ``newline=''`` is not decoration: the CRLF pairs are part of what the validator checks, and a
    reader that translates them hands the validator a file nobody downloaded.
    """
    with (FIXTURES_DIR / name).open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _capture_uid() -> str:
    """The UID the capture pair must carry, rebuilt from the documented DTO rather than read out of it."""
    dto = stage3.ICS_CAPTURE_DTO
    return stage3.calendar_invite_uid(
        str(dto["unitCampaignId"]), str(dto["showAndSellId"]), str(dto["slotId"]), str(dto["profileId"])
    )


def _synthetic_uid() -> str:
    """A short identity for the hand-written documents, so their baseline stays inside one line."""
    return stage3.calendar_invite_uid("UC#x", "S#x", "SL#x", "P#x")


def _invite(*, omit: tuple[str, ...] = (), replace: tuple[tuple[str, str], ...] = ()) -> str:
    """A hand-written invite in the shape ``buildInvite`` writes, with named omissions and replacements.

    The baseline is UTC with an explicit ``Z`` and no ``TZID``, because that is the emitter's output.
    Every caller below introduces one break the validator has to name.
    """
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//KernelWorx//Show and Sell//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{_synthetic_uid()}",
        f"DTSTAMP:{_ics_instant(stage3.ICS_CAPTURE_CLOCKS[0])}",
        "DTSTART:20260328T150000Z",
        "DTEND:20260328T163000Z",
        "SUMMARY:Show & Sell: First Sales",
        "LOCATION:Library on Main",
        r"DESCRIPTION:Slot: First Sales\nTimes in America/Denver",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    kept: list[str] = []
    for line in lines:
        if line.split(":", 1)[0] in omit:
            continue
        for needle, value in replace:
            line = line.replace(needle, value)
        kept.append(line)
    return "".join(f"{line}\r\n" for line in kept)


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
# FINALIZED and REOPENED: no mutation in this SDL, so a documented builder (API-FIX-01)
# ---------------------------------------------------------------------------


def test_finalize_is_live_and_reopen_remains_a_builder_fixture() -> None:
    """§5.2 now writes FINALIZED; §5.3 remains unshipped, so REOPENED is still a labelled fixture.

    The two states are both in the fixture set (§3.6.2 and API-FIX-01). The note says out loud
    how they were made, which is what lets a reviewer tell a builder-produced fixture apart
    from a finalization the product actually ran.
    """
    sdl = _sdl()
    assert stage2._field_exists(sdl, "Mutation", "finalizeShowAndSell")
    assert not stage2._field_exists(sdl, "Mutation", "reopenShowAndSell")
    assert stage3.STAGE_THREE_BUILDER_ONLY_STATE_FIXTURES == (
        show_and_sell_models.STATUS_FINALIZED,
        show_and_sell_models.STATUS_REOPENED,
    )
    for state in stage3.STAGE_THREE_BUILDER_ONLY_STATE_FIXTURES:
        assert state in sdl  # the enum carries both states even though one write is still a fixture
    note = stage3.BUILDER_ONLY_STATE_FIXTURE_NOTE
    assert "finalizeShowAndSell" in note and "fixture" in note and "§5" in note


def test_the_tree_holds_an_event_in_each_builder_only_state_and_says_who_wrote_it() -> None:
    """The FINALIZED/REOPENED fixtures are planned writes with a named builder, never a status string."""
    fixture = _fixture()
    for name, state in (
        ("finalized", show_and_sell_models.STATUS_FINALIZED),
        ("reopened", show_and_sell_models.STATUS_REOPENED),
    ):
        event = fixture["events"][name]
        assert event["storedStatus"] == state
        assert event["setup"]["how"] == "fixture-builder"
        assert event["setup"]["blockedWhenDenied"] is True
        assert "builder" in event["setup"]["note"]


# ---------------------------------------------------------------------------
# The clock: every instant is an offset from the scenario's T0 (FIX-AC-03, finding 1)
# ---------------------------------------------------------------------------


def test_two_scenarios_with_different_t0_values_get_the_same_offsets() -> None:
    """Two clocks, two ``T0``s, identical offsets: the tree is relative, not scheduled.

    The comparison is between the two trees, so a literal date anywhere in the builder would move one
    tree and not the other, and this would fail with the offending path named.  The one family that must
    *not* move by the shift is the DST pair, which is anchored on each clock's own spring-forward rather
    than on ``T0`` — and that is proven here, not excused: both pairs still straddle a real boundary, and
    the boundaries are different dates in different years.
    """
    early = _clock(DEFAULT_T0)
    late = _clock(OTHER_YEAR_T0)
    first, second = stage3.stage_three_fixture(early), stage3.stage_three_fixture(late)
    shift = (late.t0 - early.t0).total_seconds()
    first_times, second_times = _fixture_instants(first), _fixture_instants(second)
    assert len(first_times) > 60, f"only {len(first_times)} instants found: the walk stopped seeing the tree"
    assert set(first_times) == set(second_times)
    moved = {path: round((second_times[path] - first_times[path]).total_seconds() - shift, 6) for path in first_times}
    stuck = {path: value for path, value in moved.items() if value != 0.0 and "dst" not in path}
    assert not stuck, f"{len(stuck)} fixture instants did not move with T0: {sorted(stuck)[:5]}"
    dst_only = {path for path in moved if "dst" in path}
    assert dst_only, "the tree carries no DST family, so the exclusion above would hide anything"
    assert all(moved[path] != 0.0 for path in dst_only), (
        "the DST pair moved with T0, so it is no longer anchored on a boundary"
    )
    assert first["dst"]["boundary"] != second["dst"]["boundary"]
    assert stage3.validate_dst_pair(first["dst"]) == () and stage3.validate_dst_pair(second["dst"]) == ()
    assert first["t0"] == early.iso() and second["t0"] == late.iso()
    assert first["t0Epoch"] == int(early.t0.timestamp())


def test_no_date_in_the_tree_is_a_calendar_date_someone_copied() -> None:
    """A scenario set up in 2031 plans a 2031 tree, and nothing in it predates its own ``T0`` by months.

    §3.1 forbids hardcoded calendar dates in automation.  The enforceable form of that rule is to run
    the builder with a ``T0`` no fixture was ever written for and measure the spread of what comes back.
    """
    tree = stage3.stage_three_fixture(_clock(OTHER_YEAR_T0))
    moments = _fixture_instants(tree)
    assert len(moments) > 60
    deltas = sorted((value - OTHER_YEAR_T0).total_seconds() / 86400 for value in moments.values())
    assert -30 <= deltas[0] and deltas[-1] <= 120, f"the spread left -30..120 days: {deltas[:5]} {deltas[-5:]}"
    assert {value.year for value in moments.values()} == {OTHER_YEAR_T0.year}


def test_the_lane_token_and_data_id_carry_every_part_setup_hands_over() -> None:
    """FIX-AC-03's five values are all in the identity: a retry gets a fresh lane, never the old keys."""
    clock = stage3.ScenarioClock(
        t0=DEFAULT_T0,
        run_id="1794753000-a1b2c3",
        scenario_id="SS-SM-06",
        lane_id="L01",
        attempt_id="7d41d8cd",
    )
    assert clock.data_id == "-".join((clock.run_id, clock.scenario_id, clock.lane_id, clock.attempt_id))
    assert len(clock.token) == 12
    same = stage3.ScenarioClock(
        t0=clock.t0,
        run_id=clock.run_id,
        scenario_id=clock.scenario_id,
        lane_id=clock.lane_id,
        attempt_id=clock.attempt_id,
    )
    assert same.token == clock.token
    for field, value in (("run_id", "1794753000-zz9999"), ("attempt_id", "beef0000"), ("lane_id", "L09")):
        changed = stage3.ScenarioClock(
            t0=clock.t0,
            run_id=value if field == "run_id" else clock.run_id,
            scenario_id=clock.scenario_id,
            lane_id=value if field == "lane_id" else clock.lane_id,
            attempt_id=value if field == "attempt_id" else clock.attempt_id,
        )
        assert changed.token != clock.token, f"changing {field} left the lane token where it was"
        first = stage3.stage_three_fixture(clock)
        second = stage3.stage_three_fixture(changed)
        assert second["lane"] != first["lane"], f"changing {field} left every fixture name shared"
        assert second["dataId"] != first["dataId"], f"changing {field} left DATA_ID shared"


def test_from_run_id_takes_t0_from_the_run_identifier_and_a_supplied_t0_wins() -> None:
    """§3.1 spells ``RUN_ID`` as epoch seconds plus a short UUID, so the clock never needs a literal."""
    t0 = datetime(2027, 4, 30, 9, 15, tzinfo=timezone.utc)
    derived = stage3.ScenarioClock.from_run_id(f"{int(t0.timestamp())}-beef", "SS-SM-11", "L03", "a1")
    assert derived.t0 == t0
    explicit = stage3.ScenarioClock.from_run_id(
        f"{int(t0.timestamp())}-beef", "SS-SM-11", "L03", "a1", t0=t0 - timedelta(days=2)
    )
    assert explicit.t0 == t0 - timedelta(days=2)
    with pytest.raises(ValueError, match="epoch seconds"):
        stage3.ScenarioClock.from_run_id("pr-969-beef", "SS-SM-11", "L03", "a1")


def test_a_naive_t0_and_an_unusable_identity_part_are_refused() -> None:
    """A naive ``T0`` is the writer's clock wearing the scenario's clothes."""
    with pytest.raises(ValueError, match="timezone"):
        stage3.ScenarioClock(
            t0=datetime(2026, 11, 15, 14, 30),
            run_id="1794753000-a1b2c3",
            scenario_id="S",
            lane_id="L01",
            attempt_id="a1",
        )
    for field, bad in (("lane_id", ""), ("lane_id", "L 01"), ("attempt_id", "a/1")):
        with pytest.raises(ValueError, match=field.upper()):
            stage3.ScenarioClock(
                t0=DEFAULT_T0,
                run_id="1794753000-a1b2c3",
                scenario_id="S",
                lane_id=bad if field == "lane_id" else "L01",
                attempt_id=bad if field == "attempt_id" else "a1",
            )


def test_the_offsets_are_counted_in_the_units_own_calendar_not_in_utc() -> None:
    """A scenario set up at 04:00 UTC still gets its ``tomorrow 09:00`` on the Unit's tomorrow.

    ``T0`` here is 21:00 on the Unit's own wall clock, so counting a day off the UTC date would put the
    "tomorrow" event a day late — a whole day of drift, only visible in the Unit's zone.
    """
    clock = _clock(datetime(2026, 11, 15, 4, 0, tzinfo=timezone.utc))
    assert clock.t0.date() == date(2026, 11, 15), "the UTC calendar day, which is not the Unit's"
    assert clock.local_date(0) == date(2026, 11, 14), "04:00Z is 21:00 the night before in the Unit zone"
    start, end = clock.unit_window(1, "09:00", "10:00")
    local = _instant(start).astimezone(ZoneInfo(stage3.UNIT_TIMEZONE))
    assert local.strftime("%Y-%m-%d %H:%M") == "2026-11-15 09:00"
    assert _minutes(start, end) == 60
    assert _instant(start) > clock.t0


# ---------------------------------------------------------------------------
# The DST pair is computed, and checked against zoneinfo, for several years (SS-SM-11)
# ---------------------------------------------------------------------------


def _abbrev(day: date) -> str:
    """The Unit-zone abbreviation on that date: MST before a spring-forward, MDT after it."""
    moment = datetime(day.year, day.month, day.day, 9, 0, tzinfo=ZoneInfo(stage3.UNIT_TIMEZONE))
    return moment.strftime("%Z")


def test_the_dst_pair_straddles_a_real_spring_forward_in_every_year_a_scenario_can_run_in() -> None:
    """The boundary moves; the pair has to move with it.

    It is 2026-03-08 in one year, 2027-03-14 in another and 2028-03-12 in a third.  A pair copied from
    one of those calendars straddles nothing in the other two, so the check runs for all three plus a
    year no fixture was written for, and every fact is re-derived from ``zoneinfo`` at call time.
    """
    boundaries = {}
    for year in (2026, 2027, 2028, 2031):
        boundary = stage3.spring_forward_date(year)
        boundaries[year] = boundary
        assert boundary.month == 3 and boundary.weekday() == 6
        clock = _clock(datetime(year, 1, 10, 14, 0, tzinfo=timezone.utc))
        assert clock.spring_forward() == boundary
        pair = clock.dst_pair()
        assert stage3.validate_dst_pair(pair) == (), f"{year}: {stage3.validate_dst_pair(pair)}"
        assert pair["boundary"] == boundary.isoformat()
        assert pair["saturdayDate"] == (boundary - timedelta(days=1)).isoformat()
        assert pair["mondayDate"] == (boundary + timedelta(days=1)).isoformat()
        assert pair["saturdayWallClock"].endswith(f"09:00 {_abbrev(boundary - timedelta(days=1))}")
        assert pair["mondayWallClock"].endswith(f"09:00 {_abbrev(boundary + timedelta(days=1))}")
    assert {boundaries[year].day for year in (2026, 2027, 2028)} == {8, 14, 12}


def test_the_spring_forward_date_is_the_second_sunday_in_march_for_every_year_checked() -> None:
    """Computed, never copied: the same rule is re-derived here straight from the calendar."""
    for year in range(2024, 2041):
        first = date(year, 3, 1)
        second_sunday = first + timedelta(days=(6 - first.weekday()) % 7, weeks=1)
        assert stage3.spring_forward_date(year) == second_sunday, year


def test_a_dst_pair_that_does_not_straddle_anything_is_named() -> None:
    """The check is not vacuous: a pair copied from last year's calendar fails it, by name."""
    clock = _clock(datetime(2027, 1, 10, 14, 0, tzinfo=timezone.utc))
    pair = clock.dst_pair()
    copied = dict(pair, boundary="2026-03-08")
    problems = stage3.validate_dst_pair(copied)
    assert any("is not the day before the boundary" in line for line in problems), problems
    assert any("does not fall between the two instants" in line for line in problems), problems
    third_sunday = dict(pair, boundary=(clock.spring_forward() + timedelta(days=7)).isoformat())
    assert any("second Sunday" in line for line in stage3.validate_dst_pair(third_sunday)), third_sunday
    shifted = dict(
        pair,
        mondayStartAt=(_instant(pair["mondayStartAt"]) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    problems = stage3.validate_dst_pair(shifted)
    assert any("47 hours" in line or "one hour" in line for line in problems), problems
    spelled = dict(pair, mondayStartAt=_instant(pair["mondayStartAt"]))
    assert any("explicit Z" in line for line in stage3.validate_dst_pair(spelled)), spelled
    assert stage3.validate_dst_pair(pair) == (), "the pair nobody changed must pass what the changed one fails"


def test_the_dst_fixture_pair_sits_inside_its_event_and_uses_both_offsets() -> None:
    """The two slots are 09:00 Unit wall clock on the Saturday before and the Monday after the boundary."""
    fixture = _fixture()
    pair = fixture["dst"]
    event = fixture["events"]["dst"]
    assert stage3.validate_dst_pair(pair) == ()
    for name in ("dst-saturday", "dst-monday"):
        slot = fixture["slots"][name]
        assert event["startAt"] <= slot["startAt"] and slot["endAt"] <= event["endAt"]
        assert _minutes(slot["startAt"], slot["endAt"]) == 30
    assert pair["saturdayOffset"] == "-0700" and pair["mondayOffset"] == "-0600"
    assert pair["elapsedHours"] == 47.0


def test_a_wall_clock_inside_the_spring_forward_gap_has_no_answer_and_says_so() -> None:
    """02:30 on the boundary date never happened; a fixture that asks for it must fail, not shift."""
    clock = _clock(OTHER_YEAR_T0)
    day_offset = (clock.spring_forward() - clock.local_date()).days
    with pytest.raises(ValueError, match="does not exist"):
        clock.at_unit_wall_clock(day_offset, "02:30")
    morning = clock.at_unit_wall_clock(day_offset, "09:00")
    assert morning.astimezone(ZoneInfo(stage3.UNIT_TIMEZONE)).strftime("%H:%M %Z") == "09:00 MDT"
    assert morning.strftime("%H:%M") == "15:00", "the answer is persisted in UTC, where 09:00 MDT is 15:00"
    before = clock.at_unit_wall_clock(day_offset - 1, "09:00")
    assert before.astimezone(ZoneInfo(stage3.UNIT_TIMEZONE)).strftime("%H:%M %Z") == "09:00 MST"
    assert (morning - before) == timedelta(hours=23), "the same wall clock, an hour earlier in UTC"


# ---------------------------------------------------------------------------
# The fixture tree carries everything §3.6.2 names (EVT-M-01/02/03)
# ---------------------------------------------------------------------------


def test_the_tree_plans_an_event_in_every_state_3_6_2_names() -> None:
    """past, future, ACTIVE, ENDED, REOPENED, FINALIZED, CANCELLED — and the four-box triple."""
    fixture = _fixture()
    t0 = _instant(fixture["t0"])

    def window(name: str) -> tuple[datetime, datetime]:
        event = fixture["events"][name]
        return _instant(event["startAt"]), _instant(event["endAt"])

    assert window("ended")[1] < t0
    active_start, active_end = window("active")
    assert active_start < t0 < active_end
    for name in ("future", "big", "confirm", "dst"):
        assert t0 < window(name)[0]
    assert fixture["events"]["cancellation"]["storedStatus"] == show_and_sell_models.STATUS_CANCELLED
    statuses = {event["storedStatus"] for event in fixture["events"].values()}
    assert set(stage3.STAGE_THREE_BUILDER_ONLY_STATE_FIXTURES) <= statuses
    assert {"past", "ended", "active", "future", "cancellation", "started", "finalized", "reopened"} <= set(
        fixture["events"]
    )


def test_every_slot_and_event_runs_forward_and_sits_inside_its_own_event() -> None:
    """A zero-length or backwards slot is a fixture the server refuses, so the tree must never write one."""
    fixture = _fixture()
    for name, slot in fixture["slots"].items():
        assert _instant(slot["startAt"]) < _instant(slot["endAt"]), f"{name} does not run forward"
        assert stage3.MIN_SLOT_CAPACITY <= slot["capacity"] <= stage3.MAX_SLOT_CAPACITY, name
        event = fixture["events"][fixture["slotEvents"][name]]
        assert event["startAt"] <= slot["startAt"] and slot["endAt"] <= event["endAt"], name
    for slot in fixture["bigSlots"]:
        assert _instant(slot["startAt"]) < _instant(slot["endAt"])
    for name, event in fixture["events"].items():
        assert _instant(event["startAt"]) < _instant(event["endAt"]), name


def test_the_four_box_triple_is_a_morning_an_afternoon_and_an_overlap() -> None:
    """§3.6.2's four-box fixture, in ALLOC-04's two halves.

    Morning and afternoon do not overlap, so assigning three of four boxes to each is allowed with the
    four-box warning; the third event sits *inside* the morning, so assigning three there is the hard
    block (``CONCURRENT_OVER_ASSIGNMENT``).  A fixture that mixed the two cases would evidence neither.
    """
    fixture = _fixture()
    morning = fixture["events"]["four-box.morning"]
    afternoon = fixture["events"]["four-box.afternoon"]
    overlap = fixture["events"]["four-box.overlap"]
    assert stage3.FOUR_BOX_QUANTITY == 4
    for name in ("four-box.morning", "four-box.afternoon", "four-box.overlap"):
        setup = fixture["events"][name]["setup"]
        assert setup["how"] == "mutation" and setup["op"] == "createShowAndSell", name
    assert _instant(morning["endAt"]) <= _instant(afternoon["startAt"]), "the warning case must not overlap"
    assert _instant(morning["startAt"]) < _instant(overlap["startAt"]), "the block case must be inside the morning"
    assert _instant(overlap["endAt"]) <= _instant(morning["endAt"]), "the block case must be inside the morning"
    names = ("four-box.morning", "four-box.afternoon", "four-box.overlap")
    plans = {name: [quantity for _profile, _product, quantity in fixture["allocations"][name]] for name in names}
    assert all(plan == [stage3.FOUR_BOX_QUANTITY - 1] for plan in plans.values()), plans
    assigned = sum(plan[0] for plan in plans.values())
    assert assigned > stage3.FOUR_BOX_QUANTITY, "the overage is what earns the refusal"
    assert fixture["slots"]["morning"]["capacity"] == fixture["slots"]["afternoon"]["capacity"]


def test_the_catalog_carries_sixteen_products_and_every_target_names_one() -> None:
    """§3.6.2 says 16 products; the ledger checks need prices, not placeholders."""
    fixture = _fixture()
    assert len(fixture["products"]) == stage3.PRODUCT_CATALOG_SIZE == 16
    assert {product["catalogIndex"] for product in fixture["products"].values()} == set(range(1, 17))
    assert all(product["cents"] > 0 for product in fixture["products"].values())
    refs = {product["ref"] for product in fixture["products"].values()}
    for targets in fixture["allocations"].values():
        for _profile, product, quantity in targets:
            assert product in refs
            assert quantity >= 0


def test_the_slots_are_ninety_one_twenty_and_one_hundred_eighty_minutes_at_capacity_one_and_hundred() -> None:
    """SS-SM-05's walkthrough shape, with both capacity bounds carried by real slots.

    ``full-booth`` is the one the Full Booth case fills — capacity 1, so a second SCHEDULED signup earns
    ``SLOT_CAPACITY`` — while ``wide-booth`` carries the other bound, ``MAX_SLOT_CAPACITY``.
    """
    slots = _fixture()["slots"]
    assert _minutes(slots["first-sales"]["startAt"], slots["first-sales"]["endAt"]) == 90
    assert _minutes(slots["midday"]["startAt"], slots["midday"]["endAt"]) == 120
    assert _minutes(slots["full-booth"]["startAt"], slots["full-booth"]["endAt"]) == 180
    assert _minutes(slots["wide-booth"]["startAt"], slots["wide-booth"]["endAt"]) == 180
    assert slots["first-sales"]["capacity"] == 1 == stage3.MIN_SLOT_CAPACITY
    assert slots["full-booth"]["capacity"] == 1, "the Full Booth case has to be a slot that can actually fill"
    assert slots["wide-booth"]["capacity"] == 100 == stage3.MAX_SLOT_CAPACITY


def test_twenty_slots_is_the_boundary_and_the_twenty_first_is_refused() -> None:
    """SS-SM-05: the boundary event holds exactly ``MAX_SLOTS_PER_EVENT`` slots; the 21st earns SLOT_LIMIT."""
    fixture = _fixture()
    assert len(fixture["bigSlots"]) == stage3.MAX_SLOTS_PER_EVENT == 20
    assert all(slot["ref"].startswith("slot.big-") for slot in fixture["bigSlots"])
    events = {fixture["slotEvents"][slot["ref"].removeprefix("slot.")] for slot in fixture["bigSlots"]}
    assert events == {"big"}
    answer = stage3.stage_three_refusal("slot-limit")
    assert answer["code"] == "CONFLICT"
    assert answer["subcode"] == "SLOT_LIMIT"


def test_the_confirm_plan_carries_one_row_past_the_cap_and_the_cap_names_the_refusal() -> None:
    """SS-SM-06: the fixture plans 101 rows so the 101st becomes an executed call, not a description."""
    fixture = _fixture()
    assert fixture["confirmRows"] == stage3.MAX_WORK_LINES + 1 == 101
    answer = stage3.stage_three_refusal("work-batch-cap")
    assert answer["code"] == "INVALID_INPUT"
    assert answer["sentence"] == "may be confirmed at once."


def test_the_tree_plans_removed_members_stale_versions_and_race_barriers_as_steps() -> None:
    """§3.6.2's last three fixtures are step lists the scenario module can execute."""
    fixture = _fixture()
    removed = {row["profile"]: row for row in fixture["removedMembers"]}
    assert set(removed) == {"profile.devon", "profile.emery"}
    devon = removed["profile.devon"]["steps"]
    assert [next(iter(step)) for step in devon] == ["read", "write", "read", "write"]
    assert devon[0]["expect"]["status"] == "ACTIVE" and devon[2]["expect"]["status"] == "REMOVED"
    assert devon[1]["write"] == "removeUnitCampaignMembership"
    assert devon[1]["versionSource"] == "unitCampaignRoster", "the removal must condition on what the read answered"
    assert devon[3]["refusal"] == "removed-member-signup"
    assert removed["profile.emery"]["steps"][0]["expect"] == {"absent": True}
    assert removed["profile.emery"]["steps"][1]["refusal"] == "unjoined-scout-signup"

    for kind, plan in fixture["staleVersions"].items():
        assert plan["read"] and plan["advance"] and plan["submit"], kind
        assert len({plan["read"], plan["advance"], plan["submit"]}) == 3, kind
        assert plan["refusal"] == "stale-event-version", kind

    for name, barrier in fixture["raceBarriers"].items():
        assert barrier["threadRendezvous"] is True, name
        assert len(barrier["writes"]) == 2, name
        assert barrier["refusal"], name
    assert fixture["profiles"]["devon"]["membership"] == "removed"
    assert fixture["profiles"]["emery"]["membership"] == "unjoined"


def test_the_lane_names_are_data_id_suffixed_so_two_lanes_never_share_a_unit() -> None:
    fixture = _fixture()
    data_id = fixture["dataId"]
    assert data_id in fixture["unit"]["name"] and data_id in fixture["unitCampaign"]["name"]
    for event in fixture["events"].values():
        assert data_id in event["locationName"]
    for profile in fixture["profiles"].values():
        assert data_id in profile["name"]
    other_lane = stage3.stage_three_fixture(_clock(DEFAULT_T0, lane_id="L03"))
    assert other_lane["unit"]["name"] != fixture["unit"]["name"]


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
    for required in (
        "duplicate-signup",
        "capacity-full",
        "cross-campaign-overlap",
        "concurrent-over-assignment",
        "removed-member-signup",
        "unjoined-scout-signup",
        "stale-event-version",
    ):
        assert required in refusals
    joined = " ".join(str(row["acceptance"]) for row in stage3.STAGE_THREE_CONFLICT_PAIRS)
    for smoke in ("SS-SM-05", "SS-SM-06", "SS-SM-11"):
        assert smoke in joined


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


# ---------------------------------------------------------------------------
# Idempotency (API-FIX-01/03)
# ---------------------------------------------------------------------------


def test_builders_put_an_idempotency_input_on_every_write() -> None:
    """Every Stage 3 mutation takes ``IdempotencyInput``; no builder may omit it."""
    for type_name, sample in stage3._SAMPLES.items():
        assert "idempotency" in sample, f"{type_name} carries no idempotency input"
        assert "idempotencyKey" in sample["idempotency"]


def test_idempotency_keys_are_deterministic_unique_and_legal() -> None:
    clock = _clock()
    lane = clock.token
    keys = [stage3.idempotency_key_for(op, lane) for op in stage3.STAGE_THREE_WRITES]
    assert keys == [stage3.idempotency_key_for(op, lane) for op in stage3.STAGE_THREE_WRITES]
    assert len(set(keys)) == len(keys)
    assert all(1 <= len(key) <= 128 for key in keys)
    assert stage3.idempotency_key_for(stage3.STAGE_THREE_WRITES[0], lane, "retry").startswith(f"{keys[0]}-")
    other_lane = _clock(DEFAULT_T0, lane_id="L04").token
    assert [stage3.idempotency_key_for(op, other_lane) for op in stage3.STAGE_THREE_WRITES] != keys


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


def test_bind_ids_replaces_placeholders_and_refuses_unbound_ones() -> None:
    bound = stage3.bind_ids({"event": {"ref": "event.slots"}}, {"event.slots": "SHOW#1"})
    assert bound["event"]["ref"] == "SHOW#1"
    with pytest.raises(KeyError, match="event.dst"):
        stage3.bind_ids({"event": {"ref": "event.dst"}}, {"event.slots": "SHOW#1"})


# ---------------------------------------------------------------------------
# The calendar DTO, the captures, and the validator (CAL-01/CAL-02)
# ---------------------------------------------------------------------------


def _dto(**overrides: Any) -> dict[str, Any]:
    clock = _clock()
    dto = stage3.calendar_invite_dto(
        unit_id="UNIT#pack-3149",
        unit_campaign_id="UNITCAMP#pack-3149-ss-sm-06-l01",
        unit_campaign_name="Fall Popcorn 2026",
        show_and_sell_id="SSE#library-on-main",
        slot_id="SLOT#first-sales",
        profile_id="PROFILE#avery-scout",
        location_name="Library on Main",
        slot_start_at=clock.iso(days=7, hours=1),
        slot_end_at=clock.iso(days=7, hours=2, minutes=30),
        slot_label="First Sales",
    )
    dto.update(overrides)
    return dto


def test_the_calendar_dto_shape_matches_the_sdl_type() -> None:
    """Every field the browser reads out of ``CalendarInviteData`` is declared, and the shape is legal."""
    members = stage2._type_member_map(_sdl())["CalendarInviteData"]
    for field in stage3.CALENDAR_DTO_FIELDS:
        assert field in members, f"CalendarInviteData declares no {field}"
    assert stage3.calendar_dto_violations(_dto()) == []


def test_a_dto_the_browser_cannot_turn_into_an_invite_is_named() -> None:
    assert any("timezone" in line for line in stage3.calendar_dto_violations(_dto(timezone="Mars/Phobos")))
    assert any("slotStartAt" in line for line in stage3.calendar_dto_violations(_dto(slotStartAt="")))
    dto = _dto()
    assert any(
        "does not run after" in line
        for line in stage3.calendar_dto_violations({**dto, "slotEndAt": dto["slotStartAt"]})
    )


def test_the_invite_uid_is_the_browser_identity_tuple_and_carries_no_clock() -> None:
    """CAL-01's stability comes from the shape: four ids and no timestamp — the stamp is DTSTAMP's job."""
    uid = stage3.calendar_invite_uid("UC#x", "S#x", "SL#x", "P#x")
    assert uid == "kernelworx-show-and-sell-UC#x-S#x-SL#x-P#x@kernelworx.app"
    assert stage3.calendar_invite_uid("UC#x", "S#x", "SL#x", "P#x") == uid
    local, domain = uid.split("@")
    assert domain == "kernelworx.app"
    assert not any(len(part) >= 14 and part[:8].isdigit() for part in local.split("-")), f"{local} carries a stamp"


def test_the_capture_pair_is_two_downloads_of_the_documented_dto() -> None:
    """The captures are assertable against a constant, so the file on disk cannot quietly drift.

    The UID is rebuilt from :data:`ICS_CAPTURE_DTO`, the two stamps from :data:`ICS_CAPTURE_CLOCKS`, and
    the interval from the DTO's own ``slotStartAt``/``slotEndAt``: a hand-written stand-in fails here
    rather than passing a shape check.
    """
    first_name, repeat_name = stage3.ICS_CAPTURE_NAMES
    first, repeat = _capture(first_name), _capture(repeat_name)
    uid = _capture_uid()
    assert stage3.calendar_dto_violations(stage3.ICS_CAPTURE_DTO) == []
    assert first and repeat and first != repeat, "the pair must differ, and only by the clock"
    assert stage3.ics_uid(first) == uid == stage3.ics_uid(repeat)
    stamps = (stage3.ics_property_value(first, "DTSTAMP"), stage3.ics_property_value(repeat, "DTSTAMP"))
    assert stamps == tuple(_ics_instant(stamp) for stamp in stage3.ICS_CAPTURE_CLOCKS)
    assert stamps[0] != stamps[1], "two downloads built at one clock prove nothing about a re-download"
    assert stage3.ics_property_value(first, "DTSTART") == _ics_instant(str(stage3.ICS_CAPTURE_DTO["slotStartAt"]))
    assert stage3.ics_property_value(first, "DTEND") == _ics_instant(str(stage3.ICS_CAPTURE_DTO["slotEndAt"]))
    assert _minutes(str(stage3.ICS_CAPTURE_DTO["slotStartAt"]), str(stage3.ICS_CAPTURE_DTO["slotEndAt"])) == 90


def test_the_capture_dto_is_the_same_scenario_the_tree_plans() -> None:
    """One scenario, one shape: the capture's Unit and Campaign names are the fixture's, unprefixed."""
    fixture = _fixture()
    dto = stage3.ICS_CAPTURE_DTO
    assert fixture["unit"]["name"].startswith(f"{dto['unitDisplayName']} ")
    assert fixture["unitCampaign"]["name"].startswith(f"{dto['unitCampaignName']} ")
    location = str(dto["locationName"]).split(" — ")[0]
    assert any(event["locationName"].startswith(f"{location} ") for event in fixture["events"].values())


def test_the_validator_accepts_both_captures_as_the_bytes_the_browser_wrote() -> None:
    """CAL-02: what passes is what ``buildInvite`` emits — UTC with ``Z``, no TZID, no VTIMEZONE."""
    uid = _capture_uid()
    for name in stage3.ICS_CAPTURE_NAMES:
        text = _capture(name)
        assert stage3.validate_ics(text, uid) == (), f"{name}: {stage3.validate_ics(text, uid)}"
        assert "TZID" not in text and "VTIMEZONE" not in text
        assert stage3.ics_property_value(text, "DTSTART").endswith("Z")


def test_the_uid_survives_the_second_download_and_a_moved_uid_is_refused() -> None:
    """CAL-01: two downloads, one identity — and the validator refuses the file that broke it."""
    first, repeat = (_capture(name) for name in stage3.ICS_CAPTURE_NAMES)
    uid = _capture_uid()
    assert stage3.ics_uid(first) == stage3.ics_uid(repeat) == uid
    moved = stage3.calendar_invite_uid(
        str(stage3.ICS_CAPTURE_DTO["unitCampaignId"]),
        "SSE#another-event",
        str(stage3.ICS_CAPTURE_DTO["slotId"]),
        str(stage3.ICS_CAPTURE_DTO["profileId"]),
    )
    problems = stage3.validate_ics(repeat, moved)
    assert any("UID" in line and "CAL-01" in line for line in problems), problems


def test_a_real_uid_must_be_folded_and_the_capture_folds_it_inside_the_rfc_limit() -> None:
    """The identity is longer than a line, so folding is not optional — and the capture does it."""
    first = _capture(stage3.ICS_CAPTURE_NAMES[0])
    uid = _capture_uid()
    assert len(f"UID:{uid}") > stage3.ICS_MAX_LINE_OCTETS
    octets = stage3.ics_physical_line_octets(first)
    assert all(count <= stage3.ICS_MAX_LINE_OCTETS for count in octets), octets
    assert "\r\n " in first, "no continuation line, so the identity above could not have fit"
    assert stage3.ics_uid(first) == uid, "unfolding has to put the folded identity back together"


def test_the_captures_widest_line_is_the_emitter_fold_plus_the_continuation_space() -> None:
    """74, not 73: ``foldIcsLine`` budgets 73 octets per segment and the break adds a leading space.

    This is why the acceptance limit is RFC 5545's 75 and not the emitter's own budget: a limit of 73
    would reject the file the browser actually downloaded.
    """
    first = _capture(stage3.ICS_CAPTURE_NAMES[0])
    octets = stage3.ics_physical_line_octets(first)
    widest = max(octets)
    assert widest == stage3.ICS_FOLD_OCTETS + 1 == 74
    assert stage3.ICS_MAX_LINE_OCTETS == 75
    assert widest <= stage3.ICS_MAX_LINE_OCTETS
    assert sum(1 for count in octets if count > stage3.ICS_FOLD_OCTETS) >= 1
    assert any("75-octet" in check for check in stage3.ICS_CHECKS)


def test_a_tzid_without_a_vtimezone_is_named_as_the_hour_out_invite() -> None:
    """The old validator demanded a TZID; the emitter deliberately writes none. That is now a rejection."""
    problems = stage3.validate_ics(
        _invite(replace=(("DTSTART:20260328T150000Z", "DTSTART;TZID=America/Denver:20260328T090000"),)),
        _synthetic_uid(),
    )
    assert any("TZID" in line and "VTIMEZONE" in line for line in problems), problems
    assert any("explicit Z" in line for line in problems)


def test_a_vtimezone_block_is_refused_because_the_emitter_writes_no_zone_definitions() -> None:
    body = _invite(
        replace=(("BEGIN:VEVENT", "BEGIN:VTIMEZONE\r\nTZID:America/Denver\r\nEND:VTIMEZONE\r\nBEGIN:VEVENT"),)
    )
    problems = stage3.validate_ics(body, _synthetic_uid())
    assert any("VTIMEZONE" in line for line in problems), problems


def test_a_floating_local_datetime_is_refused() -> None:
    """CAL-02's hour-out failure mode: a date-time with no zone designator at all."""
    problems = stage3.validate_ics(
        _invite(replace=(("DTSTART:20260328T150000Z", "DTSTART:20260328T090000"),)), _synthetic_uid()
    )
    assert any("DTSTART" in line and "explicit Z" in line for line in problems), problems


def test_a_second_vevent_is_refused() -> None:
    body = _invite(replace=(("END:VEVENT", "END:VEVENT\r\nBEGIN:VEVENT\r\nUID:x\r\nEND:VEVENT"),))
    problems = stage3.validate_ics(body, _synthetic_uid())
    assert any("exactly one event" in line for line in problems), problems


def test_a_missing_required_property_is_named_per_component() -> None:
    for omitted, message in (("UID", "no UID"), ("DTSTAMP", "no DTSTAMP"), ("VERSION", "no VERSION:2.0")):
        problems = stage3.validate_ics(_invite(omit=(omitted,)), _synthetic_uid())
        assert any(message in line for line in problems), (omitted, problems)


def test_an_unbalanced_component_is_refused() -> None:
    problems = stage3.validate_ics(_invite(omit=("END",)), _synthetic_uid())
    assert any("left open" in line or "closes" in line for line in problems), problems


def test_an_overlong_unfolded_line_is_refused() -> None:
    problems = stage3.validate_ics(
        _invite(replace=(("LOCATION:Library on Main", f"LOCATION:{'y' * 90}"),)), _synthetic_uid()
    )
    assert any("octets" in line for line in problems), problems


def test_bad_text_escapes_are_named_against_what_escape_ics_text_writes() -> None:
    problems = stage3.validate_ics(
        _invite(replace=(("LOCATION:Library on Main", "LOCATION:Library\\q on Main"),)), _synthetic_uid()
    )
    assert any("is not an escape" in line for line in problems), problems
    problems = stage3.validate_ics(
        _invite(replace=(("LOCATION:Library on Main", "LOCATION:Library, Main"),)), _synthetic_uid()
    )
    assert any("unescaped" in line for line in problems), problems


def test_a_file_that_does_not_use_crlf_is_refused() -> None:
    """A text-mode read of a capture would produce exactly this file, which is the point of the check."""
    body = _invite().replace("END:VCALENDAR\r\n", "END:VCALENDAR\n")
    problems = stage3.validate_ics(body, _synthetic_uid())
    assert any("CRLF" in line or "bare LF" in line for line in problems), problems


def test_a_quoted_parameter_containing_a_colon_and_a_semicolon_is_parsed_not_split() -> None:
    """The validator is a scanner with a component stack, not a set of greps.

    A regex that split a property on the first ``;`` or ``:`` would report this legal line as broken;
    the parser reads it as one property and keeps checking the rest of the file.
    """
    body = _invite(replace=(("LOCATION:Library on Main", 'LOCATION;X-LOC="Denver; CO":Library on Main'),))
    assert stage3.validate_ics(body, _synthetic_uid()) == (), stage3.validate_ics(body, _synthetic_uid())


def test_a_folded_property_is_unfolded_before_it_is_parsed() -> None:
    body = _invite(replace=(("SUMMARY:Show & Sell: First Sales", "SUMMARY:Show & Sell:\r\n  First Sales"),))
    assert stage3.validate_ics(body, _synthetic_uid()) == ()


def test_no_server_artifact_is_in_the_checks() -> None:
    """RPT-00: the checks own only what the browser produces; no download URL is a Stage 3 concept."""
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
# The cleanup plan (SS-SM-05/06/11 lane cleanup, TTL-gated)
#
# What is executed here is the *plan*.  The delete, the read-back and the canary are executed against a
# fake DynamoDB in ``tests/unit/test_show_sell_stage3_scenario.py``, because a plan nobody deleted
# against is only a list.
# ---------------------------------------------------------------------------


def _bound_ids(fixture: dict[str, Any]) -> dict[str, str]:
    """The ids a lane that ran the whole scenario would have collected."""
    ids: dict[str, str] = {
        "actorAccount": "ACCOUNT#qa-admin",
        "account.admin": "ACCOUNT#qa-admin",
        "scope": "SS-SM-05",
        "unit": "11111111-1111-4111-8111-111111111111",
        "unit-campaign": "22222222-2222-4222-8222-222222222222",
    }
    ids |= {f"event.{name}": f"SSE#{name}" for name in fixture["events"]}
    ids |= {f"slot.{name}": f"SLOT#{name}" for name in fixture["slots"]}
    ids |= {f"profile.{name}": f"PROFILE#{name}" for name in fixture["profiles"]}
    ids |= {f"account.{name}": f"ACCOUNT#{name}" for name in fixture["profiles"]}
    return ids


def test_the_cleanup_plan_names_a_table_and_a_key_for_every_row_it_wants_gone() -> None:
    clock = _clock()
    fixture = stage3.stage_three_fixture(clock)
    plan = stage3.stage_three_cleanup_plan(clock, fixture, ids=_bound_ids(fixture))
    deletable = [row for row in plan if row["kind"] != "sweep"]
    assert deletable and all(row["table"] == stage3.show_and_sells_table() for row in deletable)
    assert stage3.show_and_sells_table() == stage3.DEV_SHOW_AND_SELLS_TABLE == "kernelworx-show-and-sells-ue1-dev"
    for row in deletable:
        assert {"pk", "sk"} <= set(row["key"]), row
        assert all(stage3.UNBOUND_KEY_MARKER not in str(cell) for cell in row["key"].values()), row
    assert {row["kind"] for row in plan} == {"slot", "signup", "event", "marker", "sweep"}


def test_an_unbound_lane_keeps_placeholders_in_its_keys_so_no_delete_is_a_guess() -> None:
    clock = _clock()
    fixture = stage3.stage_three_fixture(clock)
    plan = stage3.stage_three_cleanup_plan(clock, fixture)
    deletable = [row for row in plan if row["kind"] != "sweep"]
    assert deletable
    for row in deletable:
        assert any(stage3.UNBOUND_KEY_MARKER in str(cell) for cell in row["key"].values()), row
    half = _bound_ids(fixture)
    half.pop("unit-campaign")
    partial = stage3.stage_three_cleanup_plan(clock, fixture, ids=half)
    markers = [row for row in partial if row["kind"] == "marker"]
    creates = [row for row in markers if row["operation"] == "createShowAndSell"]
    assert creates and all("<unit-campaign>" in row["key"]["pk"] for row in creates), creates
    assert all("<unit-campaign>" not in row["key"]["pk"] for row in markers if row["operation"] != "createShowAndSell")


def test_the_plan_orders_slots_then_signups_then_events_then_markers_then_the_sweep() -> None:
    """A row that still holds a signup cannot be deleted first, or the lane learns nothing."""
    clock = _clock()
    fixture = stage3.stage_three_fixture(clock)
    plan = stage3.stage_three_cleanup_plan(clock, fixture, ids=_bound_ids(fixture))
    kinds = [row["kind"] for row in plan]
    first_of = {kind: kinds.index(kind) for kind in ("slot", "signup", "event", "marker", "sweep")}
    assert first_of["slot"] < first_of["signup"] < first_of["event"] < first_of["marker"] < first_of["sweep"]
    assert plan[-1]["kind"] == "sweep" and plan[-1]["key"] == {}
    assert "typed token" in plan[-1]["summary"] or "sweep" in plan[-1]["summary"]


def test_the_plan_carries_a_marker_row_for_every_write_and_names_the_ttl_it_refuses_to_wait_for() -> None:
    clock = _clock()
    fixture = stage3.stage_three_fixture(clock)
    plan = stage3.stage_three_cleanup_plan(clock, fixture, ids=_bound_ids(fixture))
    markers = [row for row in plan if row["kind"] == "marker"]
    assert len(markers) == len(stage3.stage_three_write_steps(fixture, clock.token)) > len(stage3.STAGE_THREE_WRITES)
    assert {row["operation"] for row in markers} == set(stage3.STAGE_THREE_WRITES)
    assert all(row["acceptance"] == "API-FIX-03" for row in markers)
    joined = " ".join(row["summary"] for row in markers)
    assert str(stage3.MARKER_TTL_SECONDS // 3600) in joined and "TTL" in joined
    assert all(row["key"]["sk"].startswith("IDEM#") for row in markers)


def test_the_plan_covers_every_slot_signup_and_event_the_tree_plans() -> None:
    clock = _clock()
    fixture = stage3.stage_three_fixture(clock)
    plan = stage3.stage_three_cleanup_plan(clock, fixture, ids=_bound_ids(fixture))
    counts = {kind: sum(1 for row in plan if row["kind"] == kind) for kind in ("slot", "signup", "event")}
    assert counts["slot"] == len(fixture["slots"])
    assert counts["signup"] == len(fixture["signups"])
    assert counts["event"] == len(fixture["events"])
    assert all(row["lane"] == clock.token for row in plan)


def test_the_canary_row_belongs_to_another_lane_token() -> None:
    clock = _clock()
    other = _clock(DEFAULT_T0, lane_id="L07")
    canary = stage3.stage_three_cleanup_canary(other.token)
    assert canary["kind"] == "canary"
    assert canary["lane"] == other.token != clock.token
    assert canary["table"] == stage3.show_and_sells_table()
    assert {"pk", "sk"} <= set(canary["key"])


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


def test_the_ledger_addresses_a_campaign_marker_on_the_campaign_table() -> None:
    """``removeUnitCampaignMembership`` writes its marker on the campaign aggregate table, not the event one.

    The handler chooses the table the mutation writes (``_campaign_marker`` versus ``_show_and_sell_marker``),
    so a lane that cleaned every marker on ``show_and_sells`` would leave that row under the TTL and report
    a clean teardown it did not have.
    """
    ledger = stage3.WriteLedger(stage3.lane_token(9001))
    ledger.record(
        field="removeUnitCampaignMembership",
        actor="account.admin",
        variables={
            "input": {
                "unitCampaignId": "22222222-2222-4222-8222-222222222222",
                "profileId": "PROFILE#devon",
                "idempotency": {"idempotencyKey": "stage3-9001-remove-devon"},
            }
        },
    )
    (row,) = ledger.marker_rows({"account.admin": "ACCOUNT#qa-admin"})
    assert row["table"] == stage3.unit_campaigns_table() == stage3.DEV_UNIT_CAMPAIGNS_TABLE
    assert row["key"]["pk"].startswith("IDEM#ACCOUNT%23qa-admin#removeUnitCampaignMembership#22222222")
    assert row["key"]["sk"] == "IDEM#stage3-9001-remove-devon"
    assert stage3.MARKER_TABLE_KEY["removeUnitCampaignMembership"] == "unit_campaigns"
    assert stage3.MARKER_SCOPE_ARGUMENT["removeUnitCampaignMembership"] == "unitCampaignId"


def _load_qa_fixture() -> Any:
    """``scripts/qa_fixture.py`` as a module: the sweeper's own table map is the contract here."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "qa_fixture.py"
    spec = importlib.util.spec_from_file_location("qa_fixture_contract", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_census_covers_every_table_the_sanctioned_sweeper_scans_for_a_lane() -> None:
    """The census is keyed on the sweeper's own table labels, not on a table the lane invented.

    ``scripts/qa_fixture.py`` sweeps ``LANE_TABLES`` — inventory, orders and order-fulfillments — and those
    are the three tables measured on ``dev`` to deny ``dynamodb:Scan`` to the fixture identity.  A census
    with a name the sweeper never prints (an "inventory-movements" table, say: movement rows live **on** the
    inventory table) would leave every real ``BLOCKED`` line unproven with no path to prove even an empty
    lane, which is the failure this test pins shut.
    """
    fixture = _load_qa_fixture()
    assert set(stage3.STAGE_THREE_RESIDUE_TABLES) == set(fixture.LANE_TABLES), (
        "every lane-swept table needs a product read, or its residue can never be proven"
    )
    for key, tables in stage3.STAGE_THREE_RESIDUE_TABLES.items():
        assert tables == (fixture.LANE_TABLES[key][0],), key
    assert set(stage3.STAGE_THREE_RESIDUE_READS) == set(stage3.STAGE_THREE_RESIDUE_TABLES)
    assert set(stage3.STAGE_THREE_RESIDUE_SCOPES) == set(stage3.STAGE_THREE_RESIDUE_TABLES)
    for documents in stage3.STAGE_THREE_RESIDUE_READS.values():
        for document in documents:
            # The census documents are the two shipped halves merged: ``showAndSells`` — the read the
            # Show & Sell table joined to the sweep needs — is minted only by the Stage 3 module.
            assert document in stage2.STAGE_TWO_DOCUMENTS or document in stage3.STAGE_THREE_DOCUMENTS, (
                f"{document} is not a document the lane can send"
            )
    # The movements the amendment keeps are read through the inventory table's own query.
    assert "inventoryMovements" in stage3.STAGE_THREE_RESIDUE_READS["inventory"]
    # Longest key first, so a fulfillment line cannot be answered by the Order read.
    assert stage3._swept_table_key("kernelworx-order-fulfillments-ue1-dev") == "order-fulfillments"
    assert stage3._swept_table_key("kernelworx-orders-ue1-dev") == "orders"
    assert stage3._swept_table_key("kernelworx-inventory-ue1-dev") == "inventory"
    assert stage3._swept_table_key("kernelworx-units-ue1-dev") == "", "a readable table is not residue"
    assert stage3._swept_table_key("") == ""


def test_every_census_read_resolves_in_the_merged_document_map() -> None:
    """The census transport looks each read up by name, so every read name must resolve there.

    ``stage_three_residue_probe`` swallows a transport exception — correctly, because a read that
    cannot run proves nothing — which means a document name missing from the transport's map would
    answer ``""`` for its table instead of raising, and a ``KeyError('showAndSells')`` once did exactly
    that on the real lane. The lookup is pinned directly so it can never pass unseen again: every
    name in :data:`STAGE_THREE_RESIDUE_READS` resolves in :data:`STAGE_THREE_CENSUS_DOCUMENTS`, the one
    merged map the lane transport uses, the query text actually selects that field, and a census run
    against a transport that enforces that lookup answers the Show & Sell table rather than shrugging
    at it.
    """
    documents = stage3.STAGE_THREE_CENSUS_DOCUMENTS
    for reads in stage3.STAGE_THREE_RESIDUE_READS.values():
        for document in reads:
            query = documents[document]
            assert document in query, f"{document} is not selected by its own query text"

    resolved: list[str] = []

    def transport(document: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        resolved.append(document)
        assert document in documents, f"the lane transport would raise {document!r}"
        return {"data": {document: {"items": []}}}

    census = stage3.stage_three_residue_census(transport, ["UC#1"], [], [])
    assert "showAndSells for UC#1 answered 0 row(s)" in census["kernelworx-show-and-sells-ue1-dev"]
    assert "showAndSells" in resolved


def test_the_residue_census_answers_only_reads_that_ran() -> None:
    """A census entry is what a read answered; a refused, missing or broken read answers nothing.

    Three shapes must **not** produce an answer, because they are what a lane reaches for when it wants a
    clean teardown: an ``AccessDenied`` it reads as "nothing there", a ``NOT_FOUND`` on the Campaign after the
    teardown took the row the read is keyed on, and an exception from a transport that never connected. Each
    leaves its table unproven, which keeps the sweep step non-clean.
    """
    rows = {
        "inventoryPositions": 2,
        "scoutCustodyBalances": 1,
        "inventoryMovements": 5,
        "unitScoutCampaignOrders": 1,
        "orderFulfillments": 3,
        "showAndSells": 2,
    }
    seen: list[tuple[str, dict[str, str]]] = []

    def answering(field: str, variables: dict[str, str]) -> dict[str, Any]:
        seen.append((field, dict(variables)))
        if field == "unitScoutCampaignOrders":
            return {"data": {field: {"items": [{"orderId": "ORDER#answered"}]}}}
        return {"data": {field: {"items": [{}] * rows[field]}}}

    census = stage3.stage_three_residue_census(answering, ["UC#1"], ["SC#1"], ["ORDER#sold"])
    assert set(census) == {
        "kernelworx-inventory-ue1-dev",
        "kernelworx-orders-ue1-dev",
        "kernelworx-order-fulfillments-ue1-dev",
        "kernelworx-show-and-sells-ue1-dev",
    }
    assert census["kernelworx-inventory-ue1-dev"] == (
        "inventoryPositions for UC#1 answered 2 row(s); scoutCustodyBalances for UC#1 answered 1 row(s); "
        "inventoryMovements for UC#1 answered 5 row(s)"
    )
    assert census["kernelworx-orders-ue1-dev"] == "unitScoutCampaignOrders for UC#1/SC#1 answered 1 row(s)"
    assert census["kernelworx-order-fulfillments-ue1-dev"] == (
        "orderFulfillments for Order ORDER#answered answered 3 row(s); "
        "orderFulfillments for Order ORDER#sold answered 3 row(s)"
    ), "a fulfillment row is partitioned by its Order, so the ids come from the Order read as well as the lane's own"
    assert census["kernelworx-show-and-sells-ue1-dev"] == "showAndSells for UC#1 answered 2 row(s)"
    assert all(stage3.is_census_statement(answer) for answer in census.values())
    assert ("unitScoutCampaignOrders", {"unitCampaignId": "UC#1", "campaignId": "SC#1"}) in seen, (
        "the Order census is scoped to this lane's Unit and Scout Campaigns, never to the stack"
    )
    assert stage3.stage_three_residue_probe(answering, ["UC#1"], ["SC#1"])("kernelworx-orders-ue1-dev") != ""

    def refused(field: str, variables: dict[str, str]) -> dict[str, Any]:
        return {"errors": [{"code": "AccessDenied", "message": f"dynamodb:Scan on {field} is not granted"}]}

    assert all(answer == "" for answer in stage3.stage_three_residue_census(refused, ["UC#1"], ["SC#1"]).values())

    def not_found(field: str, variables: dict[str, str]) -> dict[str, Any]:
        return {"errors": [{"code": "NOT_FOUND", "message": "the Unit Campaign is gone"}]}

    assert all(answer == "" for answer in stage3.stage_three_residue_census(not_found, ["UC#1"], ["SC#1"]).values())

    def broken(field: str, variables: dict[str, str]) -> dict[str, Any]:
        raise RuntimeError("no route to the API")

    assert all(answer == "" for answer in stage3.stage_three_residue_census(broken, ["UC#1"], ["SC#1"]).values())
    assert stage3.stage_three_residue_probe(answering, [])("kernelworx-inventory-ue1-dev") == "", (
        "a census with no ids to scope to is not an empty table, it is a census that was not taken"
    )


def test_an_empty_lane_is_counted_not_left_unproven() -> None:
    """A lane that sold nothing still answers the fulfillment table, because the read ran and closed the key.

    ``orderFulfillments`` has no Campaign-level query: an Order id is the only key its rows can have.  When
    the Order read answers nothing, that absence **is** the measurement, and it is stated in the census in
    the lane's own words — distinguishable from a failed read, which answers nothing at all.
    """

    def empty(field: str, variables: dict[str, str]) -> dict[str, Any]:
        return {"data": {field: {"items": []}}}

    census = stage3.stage_three_residue_census(empty, ["UC#1"], ["SC#1"])
    assert census["kernelworx-orders-ue1-dev"] == "unitScoutCampaignOrders for UC#1/SC#1 answered 0 row(s)"
    assert census["kernelworx-order-fulfillments-ue1-dev"] == stage3.NO_ORDER_NOTE
    assert stage3.is_census_statement(census["kernelworx-order-fulfillments-ue1-dev"])
    assert stage3.is_census_statement(census["kernelworx-inventory-ue1-dev"]), "three reads ran and each counted zero"
    assert not stage3.is_census_statement(
        "inventoryPositions for UC#1 answered 0 row(s); the movements are definitely gone"
    ), "one clause that is not a read answer invalidates the entry"


def test_a_census_entry_is_only_evidence_in_the_shape_a_read_emits() -> None:
    """The lane cannot grant itself residue by writing a sentence into the census."""
    for statement in (
        "inventoryMovements answered 0 row(s)",
        "inventoryPositions for UC#1 answered 12 row(s)",
        "inventoryPositions for UC#1 answered 2 row(s); inventoryMovements for UC#1 answered 1 row(s)",
    ):
        assert stage3.is_census_statement(statement)
    for claim in (
        "",
        "the inventory rows are still there",
        "inventoryMovements answered many rows",
        "answered 3",
        "inventoryPositions for UC#1 answered 2 row(s); the movements are definitely gone",
    ):
        assert not stage3.is_census_statement(claim), claim


def test_marker_address_comes_from_the_writer_s_function_not_the_plan_s_strings() -> None:
    """``derived_marker_address`` recomputes the address production wrote, on the right table.

    A membership removal's marker rides ``unit_campaigns`` (``_campaign_marker``), every other Stage 3 write
    rides ``show_and_sells``, and the actor segment is escaped the way ``marker_partition_key`` escapes it.
    Those are the three things a hand-built address gets wrong, and they are why a planned row can only be
    deleted when this function agrees with it.
    """
    row = {
        "operation": "removeUnitCampaignMembership",
        "actorField": "account.admin",
        "scopeField": "22222222-2222-4222-8222-222222222222",
        "idempotencyKey": "stage3-9001-remove-devon",
    }
    table, pk, sk = stage3.derived_marker_address(row, ids={"account.admin": "ACCOUNT#qa-admin"})
    assert table == stage3.unit_campaigns_table() == stage3.DEV_UNIT_CAMPAIGNS_TABLE
    assert pk == "IDEM#ACCOUNT%23qa-admin#removeUnitCampaignMembership#22222222-2222-4222-8222-222222222222"
    assert sk == "IDEM#stage3-9001-remove-devon"
    assert stage3.plan_row_address({"table": table, "key": {"pk": pk, "sk": sk}}) == (table, pk, sk)

    event_row = {
        "operation": "signupScoutForShowAndSellSlot",
        "actorField": "account.avery",
        "scopeField": "SSE#7",
        "idempotencyKey": "stage3-9001-race-a",
    }
    assert stage3.derived_marker_address(event_row, ids={"account.avery": "ACCOUNT#avery"})[0] == (
        stage3.show_and_sells_table()
    )


def test_an_address_cannot_be_derived_for_a_write_the_lane_has_not_identified() -> None:
    """No actor id, no scope, a placeholder scope or an unknown operation: the address is refused, not guessed."""
    base = {
        "operation": "upsertShowAndSellSlot",
        "actorField": "account.admin",
        "scopeField": "SSE#7",
        "idempotencyKey": "k" * 12,
    }
    bound = {"account.admin": "ACCOUNT#qa-admin"}
    for row, ids, reason in (
        (base, {}, "actor ref"),
        (dict(base, scopeField=""), bound, "no scope"),
        (dict(base, scopeField="<event.future>"), bound, "placeholder"),
        (dict(base, operation="showAndSell"), bound, "not a Stage 3 idempotent write"),
        (dict(base, idempotencyKey=""), bound, "no idempotencyKey"),
    ):
        with pytest.raises(ValueError) as error:
            stage3.derived_marker_address(row, ids=ids)
        assert reason in str(error.value), reason


def test_the_ledger_refuses_a_write_it_cannot_address() -> None:
    """A missing scope, a missing key, or a query recorded as a write is a lane bug, named at once."""
    ledger = stage3.WriteLedger(stage3.lane_token(9001))
    for variables, reason in (
        ({"input": {"idempotencyKey": "stage3-9001-upsert-x"}}, "no scope"),
        ({"input": {"showAndSellId": "SSE#1"}}, "no idempotencyKey"),
    ):
        with pytest.raises(ValueError) as error:
            ledger.record(field="upsertShowAndSellSlot", actor="account.admin", variables=variables)
        assert reason in str(error.value), reason
    with pytest.raises(ValueError) as error:
        ledger.record(field="showAndSell", actor="account.admin", variables={"showAndSellId": "SSE#1"})
    assert "not a Stage 3 idempotent write" in str(error.value)
    with pytest.raises(ValueError) as error:
        ledger.record(
            field="upsertShowAndSellSlot",
            actor="",
            variables={"input": {"showAndSellId": "SSE#1", "idempotencyKey": "stage3-9001-upsert-x"}},
        )
    assert "no identity behind it" in str(error.value)
    assert ledger.records == []


def test_sweep_tokens_are_typed_and_add_only_idem() -> None:
    """Stage 3 sweeps with Stage 2's tokens plus ``idem`` — no free text."""
    tokens = stage3.stage_three_sweep_tokens("ab12")
    kinds = [token.split("=", 1)[0] for token in tokens]
    assert kinds == [*stage2.LANE_TOKEN_KINDS, "idem"]
    assert stage3.STAGE_THREE_LANE_TOKEN_KINDS == (*stage2.LANE_TOKEN_KINDS, "idem")
    assert all(token == f"{kind}=ab12" for kind, token in zip(kinds, tokens, strict=True))
