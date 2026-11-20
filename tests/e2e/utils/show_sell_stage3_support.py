"""Stage 3 (Show & Sell events, allocations, slots, signups, calendar data) support for the deployed-stack acceptance suite.

Checklist §3.6.2 is the work order, verbatim: "Add deterministic event/slot/allocation/conflict fixtures
for ``T0``-relative past/future/ACTIVE/ENDED/REOPENED/FINALIZED/CANCELLED states, four-box events,
16-product catalog, 90/120/180-minute slots, removed members, stale versions, and race barriers.  Add
``API-FIX-01/03``, ``SS-SM-05/06/11``, and lane cleanup tests."  This module is that list as code: every
named state and boundary has a fixture, every fixture instant is an offset from the scenario's ``T0``,
and the parts that do not need a deployed stack are executable by ``tests/unit``.

It lives next to :mod:`tests.e2e.utils.show_sell_graphql`, and for the same reason the evidence helpers
do — outside the spec, so ``tests/unit`` can execute it.  Importing a Stage 3 spec itself from the unit
suite would fail on its ``slow`` marker under the root pytest configuration.  The half of the layer that
*performs* work — the transport-driven conflict lane, the stale-version and removed-member fixtures, the
race barriers, the FINALIZED/REOPENED DynamoDB fixture builder, and the delete-and-read-back cleanup —
is :mod:`tests.e2e.utils.show_sell_stage3_scenario`, which imports this one and never the reverse.

Five rules the whole module follows:

* **Time comes from the scenario, never from a calendar.**  Smoke plan §3.1 says ``T0`` is scenario setup
  time and "Compute event times relative to ``T0``; do not hardcode calendar dates in automation", and
  FIX-AC-03 requires setup to hand every scenario ``RUN_ID``, ``LANE_ID``, ``DATA_ID``, ``T0`` and the Unit
  timezone.  :class:`ScenarioClock` is that hand-off: it is built from a supplied ``t0`` plus the four
  ``DATA_ID`` parts, and every event, slot and boundary instant in this file is an offset from it.  The
  DST fixture pair is *computed* from the clock's year — :func:`spring_forward_date` derives the second
  Sunday in March, and the pair is 09:00 Unit-zone wall clock on the Saturday before and the Monday after
  — because a copied date proves nothing about a year whose boundary falls elsewhere.
* **A missing fixture blocks the scenario; it never excuses it.**  ``API-FIX-01`` in
  ``SHOW_AND_SELL_GRAPHQL_E2E_TEST_DESCRIPTIONS.md`` §1.2 lists ACTIVE/ENDED/REOPENED/FINALIZED/CANCELLED,
  past and future fixtures as acceptance criteria, and the same section closes with "A missing required
  fixture makes the scenario blocked; it does not justify skipping its security assertion."  Every state
  named by §3.6.2 therefore has a fixture here.  Two of them (``FINALIZED``, ``REOPENED``) have no public
  mutation in this SDL, so the scenario module builds them with an explicit DynamoDB fixture builder and
  reports ``BLOCKED`` naming the grant it is denied when the QA identity cannot write the row.
* **A document names the arguments the SDL declares.**  :func:`stage_three_contract_violations` compares
  every document and input builder here against ``tofu/application/schema/schema.graphql``, so a resolver
  rename stops a lane with a named mismatch instead of an AppSync parse error partway through it.  The SDL
  reader is the Stage 2 module's (:mod:`tests.e2e.utils.show_sell_stage2_support`), because a second
  parser is a second thing that can drift.
* **A quantity is checked against the rows it is derived from, never against a stored copy.**  §7
  defines the derived quantities as formulas over balance, allocation and custody rows, computed per
  request by :func:`src.utils.inventory_models.derived_inventory_quantities`; the Stage 2 formula checks
  are reused here verbatim.  A Stage 3 write is allowed to move only the ``assignedDelta`` column of one
  ``EVENT_ASSIGN``/``EVENT_MANUAL_REDUCE``/``EVENT_RELEASE`` movement row — physical stock, sold-in-
  possession, custody and Council-on-order stay untouched by construction (§3.2.3, EVT-M-04's "physical
  stock never changes" claim, measured at the write layer).
* **The ICS validator validates what the *browser* produces.**  No server generates, stores, or serves a
  calendar file (CAL-01, CAL-02, RPT-00): the browser assembles the invite itself from the authorized
  ``showAndSellSignupCalendarData`` read (``frontend/src/lib/showSell.ts``'s ``buildInvite``) and downloads
  it locally.  ``buildInvite`` writes UTC with a trailing ``Z`` and deliberately no ``TZID`` and no
  ``VTIMEZONE``, so :func:`validate_ics` accepts exactly that shape and rejects the opposite: a ``TZID``
  parameter, a ``VTIMEZONE`` block, a floating date-time, a UID that moves between two downloads of the
  same signup, an unfolded line over 75 octets, a missing ``METHOD:PUBLISH``/``BEGIN``/``END``, and text
  the emitter did not escape.  It is a line parser and a component state machine, not a set of regexes
  over the whole document, and the bytes it is fed in ``tests/unit`` are the captured output of
  ``buildInvite`` (``tests/e2e/fixtures/show_sell_stage3_invite_build*.ics``), not a hand-written stand-in.

Cleanup reuses the Stage 2 vocabulary (:data:`STRICT_CLEANUP`, ``CLEANUP_OBSERVED/BLOCKED/FAILED``,
:func:`run_cleanup_step`, :func:`assert_cleanup_clean`, :func:`fixture_sweep`, :func:`sweep_verdict`,
:class:`CleanupBlocked`, :class:`StageTwoCleanupError`) rather than carrying a second copy of it; the
Stage 3 additions are the ordered plan with the table and key of every row it names, the typed sweep
tokens, and the TTL gate.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from datetime import time as wall_clock_time
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

from src.utils import mutations, show_and_sell_models
from tests.e2e.utils import show_sell_graphql
from tests.e2e.utils import show_sell_stage2_support as stage_two

__all__ = [
    "BUILDER_ONLY_STATE_FIXTURE_NOTE",
    "CALENDAR_DTO_FIELDS",
    "DATA_ID_PARTS",
    "DEV_SHOW_AND_SELLS_TABLE",
    "FOUR_BOX_QUANTITY",
    "ICS_CHECKS",
    "ICS_CAPTURE_CLOCKS",
    "ICS_CAPTURE_DTO",
    "ICS_CAPTURE_NAMES",
    "ICS_FOLD_OCTETS",
    "ICS_MAX_LINE_OCTETS",
    "MARKER_TTL_ATTRIBUTE",
    "MARKER_TTL_SECONDS",
    "MAX_SLOT_CAPACITY",
    "MAX_SLOTS_PER_EVENT",
    "MAX_WORK_LINES",
    "MIN_SLOT_CAPACITY",
    "MISSING_ENDPOINT_NOTE",
    "NEVER_EXPIRING_ROW_CLASSES",
    "PRODUCT_CATALOG_SIZE",
    "QA_FIXTURE_IDENTITY",
    "STAGE_THREE_BUILDER_ONLY_STATE_FIXTURES",
    "STAGE_THREE_CLEANUP_READS",
    "UNBOUND_KEY_MARKER",
    "STAGE_THREE_CONFLICT_PAIRS",
    "STAGE_THREE_DOCUMENTS",
    "STAGE_THREE_LANE_TOKEN_KINDS",
    "STAGE_THREE_MOVEMENT_TYPES",
    "STAGE_THREE_READS",
    "STAGE_THREE_REFUSALS",
    "STAGE_THREE_REFUSAL_ANSWERS",
    "STAGE_THREE_STOCK_COLUMNS",
    "STAGE_THREE_SUPPORT_DOCUMENTS",
    "STAGE_THREE_WRITES",
    "UNIT_TIMEZONE",
    "ScenarioClock",
    "StageThreeCleanupError",
    "assert_stage_three_cleanup_clean",
    "assigned_by_product",
    "bind_ids",
    "calendar_dto_violations",
    "calendar_invite_dto",
    "calendar_invite_uid",
    "cleanup_row",
    "conflict_row",
    "create_event_input",
    "denver_wall_clock",
    "fixture_sweep",
    "ics_physical_line_octets",
    "ics_property_value",
    "ics_uid",
    "lane_token",
    "missing_stage_three_endpoints",
    "refusal_violations",
    "show_and_sells_table",
    "stage_three_cleanup_canary",
    "run_cleanup_step",
    "sample_clock",
    "spring_forward_date",
    "stage_three_cleanup_plan",
    "stage_three_contract_violations",
    "stage_three_fixture",
    "stage_three_ledger_invariants",
    "stage_three_refusal",
    "stage_three_selection_violations",
    "stage_three_lane_tokens",
    "stage_three_sweep_tokens",
    "stage_three_write_steps",
    "CENSUS_STATEMENT",
    "STAGE_THREE_RESIDUE_READS",
    "STAGE_THREE_RESIDUE_TABLES",
    "derived_marker_address",
    "plan_row_address",
    "is_census_statement",
    "stage_three_residue_census",
    "stage_three_residue_probe",
    "unit_campaigns_table",
    "MARKER_TABLE_KEY",
    "MARKER_SCOPE_ARGUMENT",
    "WriteLedger",
    "SWEEP_TOKEN_ID_FIELDS",
    "stage_three_ttl_expectation",
    "stock_snapshot",
    "sweep_verdict",
    "ttl_gate_violations",
    "update_event_input",
    "cancel_event_input",
    "assign_inventory_input",
    "upsert_slot_input",
    "delete_slot_input",
    "signup_input",
    "cancel_signup_input",
    "confirm_work_input",
    "validate_dst_pair",
    "validate_ics",
    # Re-exported Stage 2 cleanup vocabulary — one spelling, one owner (stage_two_support).
    "STRICT_CLEANUP",
    "CLEANUP_BLOCKED",
    "CLEANUP_FAILED",
    "CLEANUP_OBSERVED",
    "CleanupBlocked",
    "StageTwoCleanupError",
    "assert_cleanup_clean",
    "cleanup_blocked",
    "cleanup_failures",
    "cleanup_problems",
]

# ---------------------------------------------------------------------------
# Re-exported Stage 2 cleanup vocabulary (imported, not re-implemented)
# ---------------------------------------------------------------------------

STRICT_CLEANUP = stage_two.STRICT_CLEANUP
CLEANUP_OBSERVED = stage_two.CLEANUP_OBSERVED
CLEANUP_BLOCKED = stage_two.CLEANUP_BLOCKED
CLEANUP_FAILED = stage_two.CLEANUP_FAILED
CleanupBlocked = stage_two.CleanupBlocked
StageTwoCleanupError = stage_two.StageTwoCleanupError
assert_cleanup_clean = stage_two.assert_cleanup_clean
cleanup_blocked = stage_two.cleanup_blocked
cleanup_failures = stage_two.cleanup_failures
cleanup_problems = stage_two.cleanup_problems
cleanup_row = stage_two.cleanup_row
run_cleanup_step = stage_two.run_cleanup_step
fixture_sweep = stage_two.fixture_sweep
sweep_verdict = stage_two.sweep_verdict

#: The token kinds a Stage 3 sweep may name.  It is Stage 2's list plus ``idem``: the idempotency
#: markers this lane writes on the ``show_and_sells`` aggregate table are rows the sweeper only
#: deletes when a fixture actor wrote them, and the lane names them by the key it sent.
STAGE_THREE_LANE_TOKEN_KINDS: tuple[str, ...] = (*stage_two.LANE_TOKEN_KINDS, "idem")

# ---------------------------------------------------------------------------
# Vocabulary: the Stage 3 fields the acceptance ids name, and the Unit's zone
# ---------------------------------------------------------------------------

#: The Stage 3 mutations (EVT-M-01..03, EVT-M-04, SLOT-M-01/02, SIGN-M-01..03).
STAGE_THREE_WRITES: tuple[str, ...] = (
    "createShowAndSell",
    "updateShowAndSell",
    "cancelShowAndSell",
    "assignShowAndSellInventory",
    "upsertShowAndSellSlot",
    "deleteShowAndSellSlot",
    "signupScoutForShowAndSellSlot",
    "cancelShowAndSellSignup",
    "confirmShowAndSellWork",
)

#: The Stage 3 queries (EVT-Q-01..05, DATA-Q-03, INV-Q-06, DATA-Q-05).
STAGE_THREE_READS: tuple[str, ...] = (
    "showAndSell",
    "showAndSells",
    "unitCampaignOpportunities",
    "showAndSellOpportunity",
    "eventInventoryAllocations",
    "showAndSellSignups",
    "myScoutCommitments",
    "showAndSellSignupCalendarData",
)

#: Says *why* a Stage 3 lane stopped, in the words a reader of the evidence needs: a build that
#: predates Stage 3 answers none of these endpoints, so §3.6.2's walkthroughs wait on the Stage 3
#: merge SHA's ``Deploy Dev`` run.
MISSING_ENDPOINT_NOTE = (
    "the deployed build answers no Stage 3 endpoint, so §3.6.2 cannot run against this stack: it "
    "waits on the Stage 3 merge SHA's `Deploy Dev` run"
)

#: The Unit zone the acceptance specs pin: ``America/Denver`` (smoke plan §3.1, FIX-AC-03).  Display
#: and ICS math live here; persisted intervals stay unambiguous UTC.
UNIT_TIMEZONE = "America/Denver"

#: Operating limits, read from the model so a change to a limit moves the fixture and the check
#: together (the lane runs from this tree, and the SDL guard catches a *rename*).  ``20`` slots per
#: event (§3.3.2), slot ``capacity`` 1-100 (§3.3.2), and a work batch of at most ``100`` rows
#: (§3.4.3, ``MIN_WORK_LINES``..``MAX_WORK_LINES``).
MAX_SLOTS_PER_EVENT = show_and_sell_models.MAX_SLOTS_PER_EVENT
MIN_SLOT_CAPACITY = show_and_sell_models.MIN_SLOT_CAPACITY
MAX_SLOT_CAPACITY = show_and_sell_models.MAX_SLOT_CAPACITY
MAX_WORK_LINES = show_and_sell_models.MAX_WORK_LINES

#: The movement types a Stage 3 write may append (§4.3, §8.8): only the ``assignedDelta`` column
#: moves, and physical stock, sold-in-possession, custody, and Council-on-order stay at zero.
STAGE_THREE_MOVEMENT_TYPES: tuple[str, ...] = ("EVENT_ASSIGN", "EVENT_MANUAL_REDUCE", "EVENT_RELEASE")

#: The stored ledger columns a Stage 3 write must leave alone, and the derived ones §7 defines.
STAGE_THREE_STOCK_COLUMNS: tuple[str, ...] = (
    "kernelPhysicalQty",
    "soldInPossessionQty",
    "councilOnOrderQty",
    "withScoutQty",
)

#: The idempotency-marker TTL this tree writes (``src/utils/mutations.py``: seven days,
#: ``MARKER_TTL_ATTRIBUTE = "expiresAtEpoch"``), armed on the aggregate tables by OpenTofu.
MARKER_TTL_SECONDS = 7 * 24 * 60 * 60
MARKER_TTL_ATTRIBUTE = "expiresAtEpoch"

#: Business rows (events, slots, signups, commitments, allocations) never carry an expiry — the
#: table's TTL block is for markers only — so a cleanup step that "waits for the event to expire"
#: is a violation, not a plan.
NEVER_EXPIRING_ROW_CLASSES: tuple[str, ...] = (
    "event",
    "slot",
    "signup",
    "commitment",
    "commitment-guard",
    "allocation",
)

# ---------------------------------------------------------------------------
# The scenario clock (smoke plan §3.1, FIX-AC-03)
# ---------------------------------------------------------------------------
#
# Nothing below this banner carries a calendar date.  An instant is always
# ``clock.<something>(days=..., hours=...)``, so the same scenario re-run a year
# later, or on the other side of a DST boundary, builds the same *relationships*
# — which is the only thing the acceptance ids assert.

#: The four parts FIX-AC-03 requires setup to provide; ``DATA_ID`` is them joined
#: with ``-`` in the plan's order, and the fresh ``ATTEMPT_ID`` is what makes a
#: retry of a failed scenario unable to collide with the attempt it replaces.
DATA_ID_PARTS: tuple[str, ...] = ("RUN_ID", "SCENARIO_ID", "LANE_ID", "ATTEMPT_ID")

#: The four-box fixture of SS-SM-05: exactly this many Caramel Popcorn units recorded in
#: the Unit Campaign, assigned 3 + 3 across two sequential events with the third (the
#: overlapping one) refused.  It is a quantity, not an event count.
FOUR_BOX_QUANTITY = 4

#: §3.6.2 names a 16-product catalog: allocation has no event-wide product cap (§3.2.1), so
#: the fixture must reach a 16th product and §3.7.1 runs it in a separate batch.
PRODUCT_CATALOG_SIZE = 16

_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_RUN_EPOCH = re.compile(r"^(\d{9,11})-[0-9a-z]{4,}$")


def spring_forward_date(year: int) -> date:
    """The day America/Denver springs forward in ``year``: the second Sunday in March.

    Computed rather than copied on purpose.  The date moves — 2026-03-08, 2027-03-14 — and
    a fixture pair pinned to one year's calendar silently stops straddling anything in
    another.  :func:`validate_dst_pair` (and the unit suite) prove against ``zoneinfo``
    that the day this returns really is the boundary for the clock's year.
    """
    first = date(year, 3, 1)
    first_sunday = 1 + ((6 - first.weekday()) % 7)
    return date(year, 3, first_sunday + 7)


def denver_wall_clock(iso_utc: str) -> str:
    """The fixture's display zone for one UTC instant: the local time and the zone abbreviation.

    ``09:00 MST`` on the Saturday before a spring-forward, ``09:00 MDT`` on the Monday after
    it — the same wall clock, an hour apart in UTC, which is the fact SS-SM-11's calendar
    assertions pin.
    """
    moment = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(ZoneInfo(UNIT_TIMEZONE))
    return f"{moment:%Y-%m-%d %H:%M} {moment:%Z}"


#: The clock's own persisted spelling (§3.1, "persist unambiguously"): ISO with an explicit ``Z``.
#: Not the same pattern as :data:`_UTC_DATE_TIME`, which is the RFC 5545 ``DTSTAMP`` spelling an
#: invite carries — two different surfaces, and conflating them is how a DST check silently passes.
_ISO_Z_INSTANT = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


def validate_dst_pair(pair: Mapping[str, Any]) -> tuple[str, ...]:
    """Proof that a DST pair really straddles a spring-forward, computed against ``zoneinfo``.

    The point of checking rather than copying is that the boundary moves: it is 2026-03-08 in one
    scenario's year, 2027-03-14 in another, and a pair pinned to either calendar stops straddling
    anything in a third.  So every fact here is derived at call time from the dates in ``pair``:

    * the boundary is the second Sunday in March of its own year, and really a Sunday;
    * the pair is the Saturday before it and the Monday after it — not the same week, not a weekend;
    * both instants read 09:00 on the Unit's wall clock, which is the walkthrough's wording;
    * the two wall clocks are one hour apart in UTC offsets and 47 hours apart in real time, which is
      what "the same 09:00, an hour earlier in UTC" means; and
    * the boundary falls strictly between the two instants.

    Returns:
        The problems, empty when the pair straddles the boundary as SS-SM-11 needs it to.
    """
    problems: list[str] = []
    zone = ZoneInfo(UNIT_TIMEZONE)

    def as_date(value: Any) -> date | None:
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None

    def as_instant(value: Any) -> datetime | None:
        text = str(value or "")
        if not _ISO_Z_INSTANT.match(text):
            return None
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    boundary = as_date(pair.get("boundary"))
    saturday_date = as_date(pair.get("saturdayDate"))
    monday_date = as_date(pair.get("mondayDate"))
    if boundary is None:
        problems.append(f"boundary: {pair.get('boundary')!r} is not an ISO date, so nothing can be straddled")
    if saturday_date is None or monday_date is None:
        problems.append(
            f"saturdayDate/mondayDate: {pair.get('saturdayDate')!r} / {pair.get('mondayDate')!r} are not ISO dates"
        )
    if boundary is not None:
        expected = spring_forward_date(boundary.year)
        if boundary != expected:
            problems.append(
                f"boundary: {boundary} is not the second Sunday in March {boundary.year} ({expected}), "
                "so the pair around it straddles no spring-forward"
            )
        if saturday_date is not None and saturday_date != boundary - timedelta(days=1):
            problems.append(f"saturdayDate: {saturday_date} is not the day before the boundary {boundary}")
        if monday_date is not None and monday_date != boundary + timedelta(days=1):
            problems.append(f"mondayDate: {monday_date} is not the day after the boundary {boundary}")

    saturday = as_instant(pair.get("saturdayStartAt"))
    monday = as_instant(pair.get("mondayStartAt"))
    if saturday is None:
        problems.append(f"saturdayStartAt: {pair.get('saturdayStartAt')!r} is not a UTC instant with an explicit Z")
    if monday is None:
        problems.append(f"mondayStartAt: {pair.get('mondayStartAt')!r} is not a UTC instant with an explicit Z")
    if saturday is not None and monday is not None:
        for label, moment, day in (("saturday", saturday, saturday_date), ("monday", monday, monday_date)):
            local = moment.astimezone(zone)
            if (local.hour, local.minute) != (9, 0):
                problems.append(f"{label}StartAt: {local:%H:%M} is not 09:00 on the Unit's wall clock")
            if day is not None and local.date() != day:
                problems.append(f"{label}StartAt: {local.date()} in {UNIT_TIMEZONE} is not the planned date {day}")
        for label, moment in (("saturday", saturday), ("monday", monday)):
            if moment.astimezone(timezone.utc) != moment:
                problems.append(f"{label}StartAt: not held in UTC")
        shift = monday.astimezone(zone).utcoffset() - saturday.astimezone(zone).utcoffset()
        if shift != timedelta(hours=1):
            problems.append(
                f"the two 09:00 wall clocks are {shift} apart in UTC offset, not the one hour a "
                "spring-forward has to move them"
            )
        elapsed = monday - saturday
        if elapsed != timedelta(hours=47):
            problems.append(
                f"the pair is {elapsed} apart, not the 47 hours between 09:00 on the Saturday before a "
                "spring-forward and 09:00 on the Monday after it"
            )
        if boundary is not None:
            boundary_start = datetime.combine(boundary, wall_clock_time(0, 0), timezone.utc)
            if not saturday < boundary_start < monday:
                problems.append(f"the boundary {boundary} does not fall between the two instants")
    return tuple(problems)


class ScenarioClock:
    """Every instant a Stage 3 scenario uses, as an offset from the scenario's ``T0``.

    FIX-AC-03 requires setup to hand each scenario ``RUN_ID``, ``LANE_ID``, ``DATA_ID``, ``T0`` and the
    Unit timezone; smoke plan §3.1 requires automation to compute event times relative to ``T0`` and to
    hardcode no calendar date.  This class is that contract in one object, so a fixture cannot reach for
    a literal even by accident.

    Args:
        t0: scenario setup time.  Must be timezone-aware; it is stored as UTC.
        run_id: the run identifier, ``<UTC epoch seconds>-<short uuid>`` (§3.1).
        scenario_id: the stable scenario identifier, e.g. ``SS-SM-05``.
        lane_id: the zero-padded lane, e.g. ``L01``.
        attempt_id: a fresh identifier per attempt, so a retry never reuses the attempt it replaces.

    Raises:
        ValueError: ``t0`` is naive, or a part is empty or contains whitespace.
    """

    def __init__(self, *, t0: datetime, run_id: str, scenario_id: str, lane_id: str, attempt_id: str) -> None:
        if t0.tzinfo is None:
            raise ValueError(
                "T0 must carry a timezone; a naive scenario time is a scenario pinned to the writer's clock"
            )
        parts = {"RUN_ID": run_id, "SCENARIO_ID": scenario_id, "LANE_ID": lane_id, "ATTEMPT_ID": attempt_id}
        for name, value in parts.items():
            if not value or value.strip() != value or any(character in value for character in " \t/"):
                raise ValueError(f"{name} must be a non-empty token with no whitespace, got {value!r}")
        self.t0 = t0.astimezone(timezone.utc)
        self.run_id = run_id
        self.scenario_id = scenario_id
        self.lane_id = lane_id
        self.attempt_id = attempt_id
        self.timezone_name = UNIT_TIMEZONE

    @classmethod
    def from_run_id(
        cls, run_id: str, scenario_id: str, lane_id: str, attempt_id: str, *, t0: datetime | None = None
    ) -> ScenarioClock:
        """Build the clock the way §3.1 defines ``RUN_ID``: ``T0`` is the run's own epoch seconds.

        ``RUN_ID`` is "UTC epoch seconds plus a short UUID", so a scenario that is handed only its run
        identifier already has a scenario setup time and never needs a literal date.  A caller that
        captured ``T0`` separately (a lane that started setup before it minted the run id) passes it and
        that value wins.

        Raises:
            ValueError: ``run_id`` does not start with the epoch seconds §3.1 defines it to carry.
        """
        if t0 is not None:
            return cls(t0=t0, run_id=run_id, scenario_id=scenario_id, lane_id=lane_id, attempt_id=attempt_id)
        match = _RUN_EPOCH.match(run_id)
        if match is None:
            raise ValueError(
                f"RUN_ID {run_id!r} does not start with the UTC epoch seconds §3.1 defines: 1735420800-a1b2c3"
            )
        return cls(
            t0=datetime.fromtimestamp(int(match.group(1)), timezone.utc),
            run_id=run_id,
            scenario_id=scenario_id,
            lane_id=lane_id,
            attempt_id=attempt_id,
        )

    @property
    def data_id(self) -> str:
        """The scenario-attempt suffix §3.1 appends to every displayed name."""
        return "-".join((self.run_id, self.scenario_id, self.lane_id, self.attempt_id))

    @property
    def token(self) -> str:
        """Twelve hex characters derived from ``DATA_ID``: the lane token every key, marker and
        idempotency token this scenario writes derives from."""
        return _sha256_hex(f"stage3:{self.data_id}")[:12]

    def offset(self, *, days: int = 0, hours: int = 0, minutes: int = 0) -> datetime:
        """One instant, as an offset from ``T0``.  The only way to name a fixture time."""
        return self.t0 + timedelta(days=days, hours=hours, minutes=minutes)

    def iso(self, *, days: int = 0, hours: int = 0, minutes: int = 0) -> str:
        """The offset as the persisted spelling: UTC with an explicit ``Z`` (§3.1, "persist unambiguously")."""
        return self.offset(days=days, hours=hours, minutes=minutes).strftime("%Y-%m-%dT%H:%M:%SZ")

    def epoch(self, *, days: int = 0, hours: int = 0, minutes: int = 0) -> int:
        """The offset as epoch seconds — what a TTL or a marker expiry needs."""
        return int(self.offset(days=days, hours=hours, minutes=minutes).timestamp())

    def local_date(self, day_offset: int = 0) -> date:
        """The Unit-zone calendar date ``day_offset`` after ``T0``'s Unit-zone date.

        Offsets are counted in the Unit's own calendar, because that is how the walkthroughs count them
        ("Tomorrow, 09:00"), and it is what keeps a scenario whose ``T0`` is 04:00 UTC on a November
        morning from landing a "tomorrow" event on the wrong calendar day.
        """
        return (self.t0.astimezone(ZoneInfo(self.timezone_name)) + timedelta(days=day_offset)).date()

    def at_unit_wall_clock(self, day_offset: int, hhmm: str) -> datetime:
        """The instant the Unit's wall clock reads ``hhmm`` on ``local_date(day_offset)``.

        DST-aware by construction: the wall clock is interpreted in ``self.timezone_name``, so the same
        ``09:00`` is 16:00 UTC in November MST and 15:00 UTC in July MDT.

        Raises:
            ValueError: ``hhmm`` is not a wall clock, or that wall clock does not exist in the Unit zone
                on that date — the spring-forward gap.  Refusing it is the honest answer: a fixture that
                asked for 02:30 on the spring-forward date is asking for an instant that never happened.
        """
        if not _TIME_PATTERN.match(hhmm):
            raise ValueError(f"{hhmm!r} is not a 24-hour wall clock such as 09:00")
        day = self.local_date(day_offset)
        moment = datetime(day.year, day.month, day.day, *_parse_wall_clock(hhmm), tzinfo=ZoneInfo(self.timezone_name))
        if moment.astimezone(timezone.utc).astimezone(ZoneInfo(self.timezone_name)).replace(
            tzinfo=None
        ) != moment.replace(tzinfo=None):
            raise ValueError(
                f"{day.isoformat()} {hhmm} does not exist in {self.timezone_name}: the DST gap has no answer"
            )
        return moment.astimezone(timezone.utc)

    def unit_window(self, day_offset: int, start: str, end: str) -> tuple[str, str]:
        """A start/end pair of UTC ISO strings at Unit-zone wall clocks on one local date."""
        return (
            self.at_unit_wall_clock(day_offset, start).strftime("%Y-%m-%dT%H:%M:%SZ"),
            self.at_unit_wall_clock(day_offset, end).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def spring_forward(self) -> date:
        """The next spring-forward boundary at or after this scenario's ``T0``."""
        year = self.local_date().year
        boundary = spring_forward_date(year)
        if datetime(boundary.year, boundary.month, boundary.day, tzinfo=timezone.utc) < self.t0:
            boundary = spring_forward_date(year + 1)
        return boundary

    def dst_pair(self) -> dict[str, Any]:
        """The computed DST fixture pair: 09:00 Unit-zone wall clock on the Saturday before the
        boundary and the Monday after it, with the UTC instants and offsets that prove the straddle.

        Nothing here is copied from a fixture file: the boundary comes from :func:`spring_forward_date`,
        and the offsets from ``zoneinfo`` for those two dates, so the pair is right for every year the
        scenario runs in.
        """
        boundary = self.spring_forward()
        saturday_local = datetime.combine(
            boundary - timedelta(days=1), wall_clock_time(9, 0), ZoneInfo(self.timezone_name)
        )
        monday_local = datetime.combine(
            boundary + timedelta(days=1), wall_clock_time(9, 0), ZoneInfo(self.timezone_name)
        )
        saturday = saturday_local.astimezone(timezone.utc)
        monday = monday_local.astimezone(timezone.utc)
        return {
            "boundary": boundary.isoformat(),
            "saturdayDate": (boundary - timedelta(days=1)).isoformat(),
            "mondayDate": (boundary + timedelta(days=1)).isoformat(),
            "saturdayStartAt": saturday.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mondayStartAt": monday.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "saturdayOffset": saturday_local.strftime("%z"),
            "mondayOffset": monday_local.strftime("%z"),
            "saturdayWallClock": denver_wall_clock(saturday.strftime("%Y-%m-%dT%H:%M:%SZ")),
            "mondayWallClock": denver_wall_clock(monday.strftime("%Y-%m-%dT%H:%M:%SZ")),
            "elapsedHours": round((monday - saturday).total_seconds() / 3600, 3),
        }


def sample_clock() -> ScenarioClock:
    """The clock the module-level payload samples are built from.

    A documented scenario, not ``now``: :data:`_SAMPLES` only has to be a contract-shaped payload for the
    SDL check, so it must reproduce byte for byte between runs.  The dates in it are the *output* of the
    clock, never an input to a fixture.
    """
    return ScenarioClock(
        t0=datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc),
        run_id="1794753000-a1b2c3",
        scenario_id="SS-SM-06",
        lane_id="L01",
        attempt_id="7d41d8cd",
    )


def _parse_wall_clock(hhmm: str) -> tuple[int, int]:
    hour, _, minute = hhmm.partition(":")
    return int(hour), int(minute)


# ---------------------------------------------------------------------------
# Refusal table: the exact code and sentence a colliding payload earns, and where it is raised
# ---------------------------------------------------------------------------

#: Refusal name → what the server answers.  ``sentence`` is a literal fragment of the raising
#: source (``src/handlers/unit_operations.py`` or ``src/utils/show_and_sell_models.py``), so the
#: unit suite can prove the sentence is the handler's, not an invention; f-string seams keep the
#: static text where the task's acceptance ids name the fact (e.g. ``f"This slot is full: {active}…"``
#: pins the literal prefix).
STAGE_THREE_REFUSAL_ANSWERS: Mapping[str, Mapping[str, str]] = {
    "duplicate-signup": {
        "code": "CONFLICT",
        "subcode": "SIGNUP_DUPLICATE",
        "sentence": "This Scout already holds a place in this slot.",
        "source": "src/handlers/unit_operations.py",
    },
    "capacity-full": {
        "code": "CONFLICT",
        "subcode": "SLOT_CAPACITY",
        "sentence": "This slot is full: ",
        "source": "src/handlers/unit_operations.py",
    },
    "cross-campaign-overlap": {
        "code": "CONFLICT",
        "subcode": "COMMITMENT_OVERLAP",
        "sentence": "This Scout is already committed to another Show & Sell at these hours",
        "source": "src/handlers/unit_operations.py",
    },
    "stale-event-version": {
        "code": "CONFLICT",
        "subcode": "VERSION_MISMATCH",
        "sentence": "changed since you read it.",
        "source": "src/handlers/unit_operations.py",
    },
    "slot-limit": {
        "code": "CONFLICT",
        "subcode": "SLOT_LIMIT",
        "sentence": "one event may hold at most ",
        "source": "src/handlers/unit_operations.py",
    },
    "capacity-range": {
        "code": "INVALID_INPUT",
        "subcode": "",
        "sentence": "must be between ",
        "source": "src/utils/show_and_sell_models.py",
    },
    "work-over-duration": {
        "code": "INVALID_INPUT",
        "subcode": "WORK_OVER_DURATION",
        "sentence": "is longer than this slot runs (",
        "source": "src/handlers/unit_operations.py",
    },
    "work-batch-cap": {
        "code": "INVALID_INPUT",
        "subcode": "",
        "sentence": "may be confirmed at once.",
        "source": "src/handlers/unit_operations.py",
    },
    "work-row-duplicated": {
        "code": "INVALID_INPUT",
        "subcode": "",
        "sentence": "confirm each Scout's slot once.",
        "source": "src/handlers/unit_operations.py",
    },
    "slot-board-closed": {
        "code": "CONFLICT",
        "subcode": "EVENT_STATE",
        "sentence": "Slots can only be changed while the event is scheduled.",
        "source": "src/utils/show_and_sell_models.py",
    },
    "signup-window-closed": {
        "code": "CONFLICT",
        "subcode": "EVENT_STATE",
        "sentence": "Signups close when the event starts. This event is ",
        "source": "src/utils/show_and_sell_models.py",
    },
    "work-window-closed": {
        "code": "CONFLICT",
        "subcode": "EVENT_STATE",
        "sentence": "Work can only be confirmed while the event is active, ended, or reopened.",
        "source": "src/utils/show_and_sell_models.py",
    },
    "edit-state-refusal": {
        "code": "CONFLICT",
        "subcode": "EVENT_STATE",
        "sentence": "A ",
        "source": "src/utils/show_and_sell_models.py",
    },
    "cancel-started-event": {
        "code": "CONFLICT",
        "subcode": "EVENT_STATE",
        "sentence": "Only an event that has not started can be cancelled.",
        "source": "src/utils/show_and_sell_models.py",
    },
    "slot-holds-scouts": {
        "code": "CONFLICT",
        "subcode": "SLOT_HAS_SIGNUPS",
        "sentence": "This slot has ",
        "source": "src/handlers/unit_operations.py",
    },
    "concurrent-over-assignment": {
        "code": "CONFLICT",
        "subcode": "CONCURRENT_OVER_ASSIGNMENT",
        "sentence": "",
        "source": "src/utils/allocation_models.py",
    },
    "idempotency-replayed": {
        "code": "REPLAYED",
        "subcode": "",
        "sentence": "",
        "source": "src/utils/mutations.py",
    },
    "idempotency-changed": {
        "code": "INVALID_INPUT",
        "subcode": "IDEMPOTENCY_FINGERPRINT_MISMATCH",
        "sentence": "This idempotencyKey was already used with different request content.",
        "source": "src/utils/mutations.py",
    },
    "assignment-empty-items": {
        "code": "INVALID_INPUT",
        "subcode": "",
        "sentence": "",
        "source": "src/handlers/unit_operations.py",
    },
    "signup-not-found": {
        "code": "NOT_FOUND",
        "subcode": "",
        "sentence": "Show & Sell signup not found",
        "source": "src/handlers/unit_operations.py",
    },
    "removed-member-signup": {
        "code": "CONFLICT",
        "subcode": "MEMBERSHIP_REMOVED",
        "sentence": "This Scout's roster entry is REMOVED; rejoin before taking a place in a slot",
        "source": "src/handlers/unit_operations.py",
    },
    "unjoined-scout-signup": {
        "code": "NOT_FOUND",
        "subcode": "",
        "sentence": "This Scout is not on this event's Unit Campaign roster",
        "source": "src/handlers/unit_operations.py",
    },
    "cross-campaign-roster": {
        "code": "CONFLICT",
        "subcode": "MEMBERSHIP_CAMPAIGN",
        "sentence": "This Scout's roster entry belongs to a different Scout Campaign",
        "source": "src/handlers/unit_operations.py",
    },
}

#: The acceptance ids each refusal belongs to, keyed the same way.  Kept beside the sentences so a
#: reader of a live lane's ``refusal.json`` sees the id without chasing the table.
STAGE_THREE_REFUSALS: Mapping[str, tuple[str, ...]] = {
    "duplicate-signup": ("SIGN-M-01-02", "SLOT-02", "SS-SM-06 step 3"),
    "capacity-full": ("SIGN-M-01-02", "SLOT-02-02", "SS-SM-06 step 3"),
    "cross-campaign-overlap": ("SIGN-M-01-02", "SLOT-04", "SS-SM-06 step 5"),
    "stale-event-version": ("VER-01", "EVT-M-02-03", "EVT-M-03-03", "SLOT-M-01-03", "SIGN-M-03-03", "API-FIX-03"),
    "slot-limit": ("SLOT-M-01-02", "§3.3.2's 20-slot cap", "SS-SM-06 step 5's 20-slot event"),
    "capacity-range": ("SLOT-M-01-01/02", "§3.3.2's 1-100 capacity"),
    "work-over-duration": ("SIGN-M-03-02", "SS-SM-06 step 9's 190 minutes in a 210-minute day"),
    "work-batch-cap": ("SIGN-M-03-03", "§3.3.3's 1-100 rows", "§3.4.3's 1-100 rows"),
    "work-row-duplicated": ("SIGN-M-03-02", "§3.4.3's unique (slotId, profileId) rows"),
    "slot-board-closed": ("SLOT-M-01-02", "EVT-M-02's state matrix"),
    "signup-window-closed": ("SIGN-M-01-01", "§3.4.1's SCHEDULED requirement"),
    "work-window-closed": ("SIGN-M-03-02", "§3.4.3's ACTIVE/ENDED/REOPENED window"),
    "edit-state-refusal": ("EVT-M-02-03", "§3.5's state matrix"),
    "cancel-started-event": ("EVT-M-03-02", "SS-SM-11 step 5"),
    "slot-holds-scouts": ("SLOT-M-02-02", "§3.3.3"),
    "concurrent-over-assignment": ("EVT-M-04-01", "ALLOC-02", "SS-SM-05 step 4"),
    "idempotency-replayed": ("IDEM-01", "EVT-M-01-03", "EVT-M-03-03", "SIGN-M-01-04"),
    "idempotency-changed": ("IDEM-01", "§6.3.4's changed-fingerprint INVALID_INPUT"),
    "assignment-empty-items": ("EVT-M-04", "§6.2's non-empty batch"),
    "signup-not-found": ("SIGN-M-03", "§3.4.3's signup-must-exist rule"),
    "removed-member-signup": ("SIGN-M-01-03", "§3.4.2's after-removal correction", "SS-SM-06 step 7's removal half"),
    "unjoined-scout-signup": ("SIGN-M-01-03", "SLOT-03", "SS-SM-06 step 7's Emery"),
    "cross-campaign-roster": ("SIGN-M-01-03", "§3.4.1's roster-Campaign match"),
}

# ------------------------------------------------------------------
# 2. Deterministic fixture
# ------------------------------------------------------------------
#
# Every id the server will mint is a ``<ref>`` placeholder (``<unit>``,
# ``<campaign.avery>``, ``<event.slots>``, ``<slot.first-sales>``,
# ``<profile.avery>``, ``<product.caramel>``).  The live lane binds the ids the
# answers came back with through :func:`bind_ids` before the first write.  Every
# derived value is computed from the scenario clock and the lane token, so one
# DATA_ID rebuilds the same bytes and a re-run recognises the same Unit.

FIXTURE_CATALOG: tuple[tuple[str, int], ...] = (
    ("Caramel Popcorn", 3000),
    ("Butter Popcorn", 2000),
    ("Chocolate Popcorn", 2500),
    ("Caramel Corn", 350),
    ("Butter Toffee", 425),
    ("Chocolate Bar", 175),
    ("Trail Mix", 600),
    ("Sunflower Seeds", 250),
    ("Pumpkin Seeds", 325),
    ("Caramel Pretzels", 550),
    ("Cheese Crisps", 480),
    ("Apple Cider", 400),
    ("Hot Cocoa Mix", 700),
    ("Cinnamon Sticks", 150),
    ("Maple Candy", 800),
    ("Holiday Tin", 1500),
)


def _fixture_event(clock: ScenarioClock, *, location: str, day_offset: int, start: str, end: str) -> dict[str, Any]:
    start_at, end_at = clock.unit_window(day_offset, start, end)
    return {"ref": "event", "locationName": f"{location} {clock.data_id}", "startAt": start_at, "endAt": end_at}


def _fixture_slot(start_at: str, end_at: str, label: str, capacity: int) -> dict[str, dict[str, Any]]:
    return {"ref": "slot", "label": label, "startAt": start_at, "endAt": end_at, "capacity": capacity}


def stage_three_fixture(clock: ScenarioClock) -> dict[str, Any]:
    """The Stage 3 acceptance tree, every instant an offset from the scenario's ``T0``.

    Every state §3.6.2 names is present and says how it is produced:

    * ``past`` and ``ended`` and ``active`` need no write at all — they are the clock's own answer
      (:func:`src.utils.show_and_sell_models.derive_event_status`), and the row stores ``SCHEDULED``;
    * ``future`` and ``cancelled`` come from Stage 3 mutations (``createShowAndSell``,
      ``cancelShowAndSell`` — §3.5's pre-start-only cancellation);
    * ``FINALIZED`` and ``REOPENED`` have no mutation in this SDL, so their ``setup`` names
      ``fixture-builder``: the explicit DynamoDB fixture builder in
      :mod:`tests.e2e.utils.show_sell_stage3_scenario` (``API-FIX-01``'s "documented test fixture").  It
      is a real, executable builder, and when the QA identity cannot write the row the scenario is
      reported **blocked** naming the missing grant — never dropped from the tree.

    Plus the boundaries the same section names: the four-box allocation triple, the 16-product catalog,
    the 90/120/180-minute slots at capacity 1 and 100, the 20-slot event, the 101-row work batch, the
    removed member, the stale-version setup, the race barriers, and the computed DST pair.
    """
    lane = clock.token
    dst = clock.dst_pair()
    events: dict[str, dict[str, Any]] = {}

    def add_event(
        name: str,
        *,
        location: str,
        day_offset: int,
        start: str,
        end: str,
        stored_status: str,
        setup: dict[str, Any],
    ) -> None:
        event = dict(_fixture_event(clock, location=location, day_offset=day_offset, start=start, end=end))
        event["ref"] = f"event.{name}"
        event["storedStatus"] = stored_status
        event["setup"] = setup
        events[name] = event

    add_event(
        "past",
        location="Yesterday's Sale",
        day_offset=-3,
        start="09:00",
        end="12:00",
        stored_status=show_and_sell_models.STATUS_SCHEDULED,
        setup={"how": "clock", "note": "the interval is wholly before T0; the row stores SCHEDULED and reads ENDED"},
    )
    add_event(
        "ended",
        location="Ended Booth",
        day_offset=-1,
        start="09:00",
        end="12:00",
        stored_status=show_and_sell_models.STATUS_SCHEDULED,
        setup={
            "how": "clock",
            "note": "ended at T0 and waiting for finalization (SSE-04: an ended event is not a finalized one)",
        },
    )
    add_event(
        "active",
        location="Live Booth",
        day_offset=0,
        start="00:00",
        end="23:59",
        stored_status=show_and_sell_models.STATUS_SCHEDULED,
        setup={"how": "clock", "note": "T0 falls inside the interval, so the answer is ACTIVE with nothing stored"},
    )
    add_event(
        "future",
        location="Library on Main",
        day_offset=7,
        start="09:00",
        end="12:30",
        stored_status=show_and_sell_models.STATUS_SCHEDULED,
        setup={"how": "mutation", "op": "createShowAndSell", "note": "SS-SM-06's fixture: no address, three slots"},
    )
    add_event(
        "cancellation",
        location="Park Pavilion",
        day_offset=10,
        start="09:00",
        end="11:00",
        stored_status=show_and_sell_models.STATUS_CANCELLED,
        setup={
            "how": "mutation",
            "op": "cancelShowAndSell",
            "reason": "Vendor conflict",
            "note": "SS-SM-11 steps 2 and 4: cancelled before its start, which is the only state that allows it",
        },
    )
    add_event(
        "started",
        location="Started Pavilion",
        day_offset=-1,
        start="13:00",
        end="16:00",
        stored_status=show_and_sell_models.STATUS_SCHEDULED,
        setup={"how": "clock", "note": "SS-SM-11 step 5: already started, so cancel must be refused"},
    )
    add_event(
        "finalized",
        location="Finalized Sale",
        day_offset=-4,
        start="09:00",
        end="12:00",
        stored_status=show_and_sell_models.STATUS_FINALIZED,
        setup={
            "how": "fixture-builder",
            "builder": "finalize_event_fixture",
            "blockedWhenDenied": True,
            "note": "§5's finalizeShowAndSell is not in this SDL; API-FIX-01 still requires the fixture, so the "
            "scenario writes the row with the documented builder and reports BLOCKED naming the DynamoDB grant "
            "it is denied",
        },
    )
    add_event(
        "reopened",
        location="Reopened Sale",
        day_offset=-5,
        start="09:00",
        end="12:00",
        stored_status=show_and_sell_models.STATUS_REOPENED,
        setup={
            "how": "fixture-builder",
            "builder": "reopen_event_fixture",
            "blockedWhenDenied": True,
            "note": "§5's reopenShowAndSell is not in this SDL; same builder path, and ``approvedFinalizationId`` "
            "is cleared because the model refuses a REOPENED row that still points at an approved finalization",
        },
    )
    add_event(
        "four-box.morning",
        location="Kroger on Monroe",
        day_offset=-1,
        start="09:00",
        end="12:00",
        stored_status=show_and_sell_models.STATUS_SCHEDULED,
        setup={"how": "mutation", "op": "createShowAndSell", "note": "SS-SM-05 morning: 3 of the 4 boxes"},
    )
    add_event(
        "four-box.afternoon",
        location="Kroger on Monroe",
        day_offset=-1,
        start="13:00",
        end="16:00",
        stored_status=show_and_sell_models.STATUS_SCHEDULED,
        setup={"how": "mutation", "op": "createShowAndSell", "note": "SS-SM-05 afternoon: sequential over-assignment"},
    )
    add_event(
        "four-box.overlap",
        location="Kroger on Monroe",
        day_offset=-1,
        start="10:00",
        end="11:00",
        stored_status=show_and_sell_models.STATUS_SCHEDULED,
        setup={"how": "mutation", "op": "createShowAndSell", "note": "SS-SM-05 step 4: the assignment here is refused"},
    )
    add_event(
        "big",
        location="Twenty Slots",
        day_offset=9,
        start="09:00",
        end="10:00",
        stored_status=show_and_sell_models.STATUS_SCHEDULED,
        setup={"how": "mutation", "op": "createShowAndSell", "note": "the 20-slot boundary event"},
    )
    add_event(
        "confirm",
        location="Confirm Rows",
        day_offset=8,
        start="18:00",
        end="19:30",
        stored_status=show_and_sell_models.STATUS_SCHEDULED,
        setup={"how": "mutation", "op": "createShowAndSell", "note": "the 101-row confirm batch"},
    )
    events["dst"] = {
        "ref": "event.dst",
        "locationName": f"DST Straddle {clock.data_id}",
        "startAt": dst["saturdayStartAt"],
        "endAt": _add_minutes(dst["mondayStartAt"], 60),
        "storedStatus": show_and_sell_models.STATUS_SCHEDULED,
        "setup": {
            "how": "computed",
            "dst": dst,
            "note": "the pair is derived from the clock's own spring-forward date",
        },
    }

    slots: dict[str, dict[str, Any]] = {}
    future_start, future_end = events["future"]["startAt"], events["future"]["endAt"]
    slots.update(
        {
            "first-sales": dict(
                _fixture_slot(future_start, _add_minutes(future_start, 90), "First Sales", 1), ref="slot.first-sales"
            ),
            "midday": dict(_fixture_slot(_add_minutes(future_start, 90), future_end, "Midday", 1), ref="slot.midday"),
            "full-booth": dict(
                _fixture_slot(future_start, _add_minutes(future_start, 180), "Full Booth", 1), ref="slot.full-booth"
            ),
            "wide-booth": dict(
                _fixture_slot(future_start, _add_minutes(future_start, 180), "Wide Booth", MAX_SLOT_CAPACITY),
                ref="slot.wide-booth",
            ),
        }
    )
    morning_start = events["four-box.morning"]["startAt"]
    afternoon_start = events["four-box.afternoon"]["startAt"]
    slots.update(
        {
            "morning": dict(
                _fixture_slot(morning_start, _add_minutes(morning_start, 180), "Morning", 4), ref="slot.morning"
            ),
            "afternoon": dict(
                _fixture_slot(afternoon_start, _add_minutes(afternoon_start, 180), "Afternoon", 4),
                ref="slot.afternoon",
            ),
        }
    )
    confirm_start = events["confirm"]["startAt"]
    slots["confirm-row"] = dict(_fixture_slot(confirm_start, _add_minutes(confirm_start, 90), "Confirm Row", 100))
    slots["confirm-row"]["ref"] = "slot.confirm-row"
    slots["dst-saturday"] = dict(
        _fixture_slot(dst["saturdayStartAt"], _add_minutes(dst["saturdayStartAt"], 30), "DST Saturday", 1)
    )
    slots["dst-saturday"]["ref"] = "slot.dst-saturday"
    slots["dst-monday"] = dict(
        _fixture_slot(dst["mondayStartAt"], _add_minutes(dst["mondayStartAt"], 30), "DST Monday", 1)
    )
    slots["dst-monday"]["ref"] = "slot.dst-monday"
    big_start = events["big"]["startAt"]
    big_slots = [
        dict(
            _fixture_slot(big_start, _add_minutes(big_start, 60), f"Slot {index + 1}", MIN_SLOT_CAPACITY),
            ref=f"slot.big-{index:02d}",
        )
        for index in range(MAX_SLOTS_PER_EVENT)
    ]

    products: dict[str, dict[str, Any]] = {}
    for index, (name, cents) in enumerate(FIXTURE_CATALOG, start=1):
        key = f"p{index:02d}"
        products[key] = {
            "ref": f"product.{key}",
            "name": f"{name} {clock.data_id}",
            "cents": cents,
            "catalogIndex": index,
        }

    profiles: dict[str, dict[str, Any]] = {}
    for name, role in (
        ("avery", "joined"),
        ("blake", "joined"),
        ("charlie", "joined"),
        ("devon", "removed"),
        ("emery", "unjoined"),
        ("riley", "read-only non-member"),
    ):
        profiles[name] = {
            "ref": f"profile.{name}",
            "name": f"{name.capitalize()} Scout {clock.data_id}",
            "membership": role,
        }

    caramel = products["p01"]["ref"]
    butter = products["p02"]["ref"]
    allocations: dict[str, list[tuple[str, str, int]]] = {
        "four-box.morning": [("profile.avery", caramel, 3)],
        "four-box.afternoon": [("profile.blake", caramel, 3)],
        "four-box.overlap": [("profile.charlie", caramel, 3)],
        "first-sales": [("profile.avery", butter, 1)],
        "wide-booth": [("profile.avery", butter, MAX_SLOT_CAPACITY)],
    }
    #: Which event each slot belongs to.  The cleanup plan names rows by their partition and sort
    #: key, and a slot key under the wrong event is a row that survives teardown looking deleted.
    slot_events = {
        "first-sales": "future",
        "midday": "future",
        "full-booth": "future",
        "wide-booth": "future",
        "morning": "four-box.morning",
        "afternoon": "four-box.afternoon",
        "confirm-row": "confirm",
        "dst-saturday": "dst",
        "dst-monday": "dst",
    }
    slot_events.update({f"big-{index:02d}": "big" for index in range(MAX_SLOTS_PER_EVENT)})
    #: The signups this scenario holds a row for — the ones the walkthroughs succeed at, not the
    #: refusals (SS-SM-06 steps 1, 4 and 6; SS-SM-05's four past valid signups).  Cleanup iterates
    #: this list, so a signup the tree forgot is a row nobody reads back.
    signups = [
        {"event": "four-box.morning", "slot": "morning", "profile": "avery"},
        {"event": "four-box.morning", "slot": "morning", "profile": "blake"},
        {"event": "four-box.morning", "slot": "morning", "profile": "charlie"},
        {"event": "four-box.morning", "slot": "morning", "profile": "devon"},
        {"event": "future", "slot": "first-sales", "profile": "avery"},
        {"event": "future", "slot": "midday", "profile": "avery"},
        {"event": "future", "slot": "full-booth", "profile": "charlie"},
    ]
    race_barriers = {
        "allocation": {
            "threadRendezvous": True,
            "writes": ["assignShowAndSellInventory", "assignShowAndSellInventory"],
            "refusal": "concurrent-over-assignment",
            "note": "SS-SM-05 step 4 / SS-API-01: both threads pass validation, one write plan wins, the other "
            "is refused, and no partial allocation is saved",
        },
        "capacity": {
            "threadRendezvous": True,
            "writes": ["signupScoutForShowAndSellSlot", "signupScoutForShowAndSellSlot"],
            "refusal": "capacity-full",
            "note": "SLOT-02-02: two signups for the last place in a capacity-1 slot",
        },
        "version": {
            "threadRendezvous": True,
            "writes": ["updateShowAndSell", "updateShowAndSell"],
            "refusal": "stale-event-version",
            "note": "API-FIX-03 / VER-01: two writes that read the same version, one advances it",
        },
    }
    stale_versions = {
        "event": {
            "read": "showAndSell",
            "advance": "upsertShowAndSellSlot",
            "submit": "deleteShowAndSellSlot",
            "refusal": "stale-event-version",
        },
        "signup": {
            "read": "showAndSellSignups",
            "advance": "confirmShowAndSellWork",
            "submit": "cancelShowAndSellSignup",
            "refusal": "stale-event-version",
        },
    }
    return {
        "dataId": clock.data_id,
        "lane": lane,
        "timezone": clock.timezone_name,
        "t0": clock.iso(),
        "t0Epoch": clock.epoch(),
        "unit": {"ref": "unit", "name": f"Smoke Pack 3149 {clock.data_id}"},
        "unitCampaign": {"ref": "unit-campaign", "name": f"Fall Popcorn 2026 {clock.data_id}"},
        "campaigns": {
            name: {"ref": f"campaign.{name}", "name": profiles[name]["name"]}
            for name in ("avery", "blake", "charlie", "devon", "emery")
        },
        "events": events,
        "slots": slots,
        "bigSlots": big_slots,
        "profiles": profiles,
        "products": products,
        "allocations": allocations,
        "slotEvents": slot_events,
        "signups": signups,
        "fourBoxQuantity": FOUR_BOX_QUANTITY,
        "removedMembers": _removed_member_setup(clock, profiles),
        "staleVersions": stale_versions,
        "raceBarriers": race_barriers,
        "confirmRows": MAX_WORK_LINES + 1,
        "dst": dst,
    }


def _removed_member_setup(clock: ScenarioClock, profiles: Mapping[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """API-FIX-03's "read and advance versions" applied to the roster: the removal is a real Stage 2
    mutation, and the signup that follows it is the assertion.  Nothing here edits an expected input —
    the roster row is removed by the same ``removeUnitCampaignMembership`` the product uses, and its
    ``guardVersion``/``membershipVersion`` come from the roster read that precedes the write."""
    return [
        {
            "profile": profiles["devon"]["ref"],
            "campaign": "campaign.devon",
            "steps": [
                {"read": "unitCampaignRoster", "expect": {"status": "ACTIVE"}},
                {
                    "write": "removeUnitCampaignMembership",
                    "versionSource": "unitCampaignRoster",
                    "note": "§3.4.2 keeps the row as removal audit; the status becomes REMOVED",
                },
                {"read": "unitCampaignRoster", "expect": {"status": "REMOVED"}},
                {"write": "signupScoutForShowAndSellSlot", "refusal": "removed-member-signup"},
            ],
        },
        {
            "profile": profiles["emery"]["ref"],
            "campaign": "campaign.emery",
            "steps": [
                {"read": "unitCampaignRoster", "expect": {"absent": True}},
                {"write": "signupScoutForShowAndSellSlot", "refusal": "unjoined-scout-signup"},
            ],
        },
    ]


def _add_minutes(iso_utc: str, minutes: int) -> str:
    """One interval endpoint shifted by minutes, in the same persisted spelling."""
    moment = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (moment + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def bind_ids(payload: Any, ids: Mapping[str, str]) -> Any:
    """Replace the fixture's ``<ref>`` placeholders with the ids the live
    answers came back with.  A string matching an ids key, and a
    ``{"ref": ...}`` cell, are both replaced; an unbound ``{"ref": ...}`` cell
    raises, so a lane cannot ship a placeholder downstream."""
    if isinstance(payload, Mapping):
        bound: dict = {}
        for key, value in payload.items():
            if key == "ref" and value not in ids:
                raise KeyError(f"unbound fixture ref: {value!r}")
            bound[key] = bind_ids(value, ids)
        return bound
    if isinstance(payload, (list, tuple, set)):
        return type(payload)(bind_ids(value, ids) for value in payload)
    if isinstance(payload, str) and payload in ids:
        return ids[payload]
    return payload


def lane_token(seed: int) -> str:
    """Twelve hex characters; every fixture key, marker and idempotency token
    derives from it, so one seed pins the whole tree.

    A scenario that has a :class:`ScenarioClock` uses ``clock.token`` — the same function of its
    ``DATA_ID`` — and never a bare seed.
    """
    return _sha256_hex(f"stage3:{seed:04d}")[:12]


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().rstrip()


# ------------------------------------------------------------------
# 3. Input builders -- one per Stage 3 write, keyed by operation
# ------------------------------------------------------------------
#
# Every builder puts the SDL's ``IdempotencyInput`` and ``VersionedInput`` in
# nested shape, and the lane derives the key itself: one lane token, one
# deterministic key per write.  The sample payloads below are built from
# :func:`sample_clock`, so the times in them are clock output too.

_SAMPLE_CLOCK = sample_clock()


def idempotency_key_for(op: str, lane: str, step: str = "") -> str:
    """The deterministic idempotency key for one write:
    ``stage3-<lane>-<op>[-step]`` (1-128 trimmed characters)."""
    key = f"stage3-{lane}-{op}"
    if step:
        key = f"{key}-{step}"
    return key


def _idempotency(key: str) -> dict[str, str]:
    return {"idempotencyKey": key}


def _version(expected: int) -> dict[str, int]:
    return {"expectedVersion": expected}


def create_event_input(
    unit_campaign_id: str,
    location_name: str,
    start_at: str,
    end_at: str,
    *,
    address: str | None = None,
    we_owe_enabled: bool | None = None,
    idempotency_key: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "unitCampaignId": unit_campaign_id,
        "locationName": location_name,
        "startAt": start_at,
        "endAt": end_at,
        "idempotency": _idempotency(idempotency_key),
    }
    if address is not None:
        body["address"] = address
    if we_owe_enabled is not None:
        body["weOweEnabled"] = we_owe_enabled
    return body


def update_event_input(
    show_and_sell_id: str,
    version: int,
    *,
    location_name: str | None = None,
    address: str | None = None,
    we_owe_enabled: bool | None = None,
    idempotency_key: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "showAndSellId": show_and_sell_id,
        "version": _version(version),
        "idempotency": _idempotency(idempotency_key),
    }
    if location_name is not None:
        body["locationName"] = location_name
    if address is not None:
        body["address"] = address
    if we_owe_enabled is not None:
        body["weOweEnabled"] = we_owe_enabled
    return body


def cancel_event_input(show_and_sell_id: str, version: int, reason: str, *, idempotency_key: str) -> dict[str, Any]:
    return {
        "showAndSellId": show_and_sell_id,
        "version": _version(version),
        "reason": reason,
        "idempotency": _idempotency(idempotency_key),
    }


def assign_inventory_input(
    show_and_sell_id: str,
    targets: Iterable[tuple[str, int]],
    version: int,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    """``targets``: ``(productId, quantity)`` — at most one target per product,
    the event's target (not a delta)."""
    return {
        "showAndSellId": show_and_sell_id,
        "items": [{"productId": product_id, "quantity": quantity} for product_id, quantity in targets],
        "version": _version(version),
        "idempotency": _idempotency(idempotency_key),
    }


def upsert_slot_input(
    show_and_sell_id: str,
    version: int,
    start_at: str,
    end_at: str,
    capacity: int,
    *,
    slot_id: str | None = None,
    label: str | None = None,
    slot_version: int | None = None,
    idempotency_key: str,
) -> dict[str, Any]:
    """A create names no slot and no slot version; an edit names both
    (``slotVersion`` is ``VersionedInput`` — the SDL's own spelling)."""
    body: dict[str, Any] = {
        "showAndSellId": show_and_sell_id,
        "startAt": start_at,
        "endAt": end_at,
        "capacity": capacity,
        "version": _version(version),
        "idempotency": _idempotency(idempotency_key),
    }
    if slot_id is not None:
        body["slotId"] = slot_id
    if label is not None:
        body["label"] = label
    if slot_version is not None:
        body["slotVersion"] = _version(slot_version)
    return body


def delete_slot_input(show_and_sell_id: str, slot_id: str, version: int, *, idempotency_key: str) -> dict[str, Any]:
    return {
        "showAndSellId": show_and_sell_id,
        "slotId": slot_id,
        "version": _version(version),
        "idempotency": _idempotency(idempotency_key),
    }


def signup_input(
    show_and_sell_id: str,
    slot_id: str,
    campaign_id: str,
    profile_id: str,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    return {
        "showAndSellId": show_and_sell_id,
        "slotId": slot_id,
        "campaignId": campaign_id,
        "profileId": profile_id,
        "idempotency": _idempotency(idempotency_key),
    }


def cancel_signup_input(
    show_and_sell_id: str,
    slot_id: str,
    profile_id: str,
    version: int,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    """``version`` is the signup's own ``signupVersion``, not the event's."""
    return {
        "showAndSellId": show_and_sell_id,
        "slotId": slot_id,
        "profileId": profile_id,
        "version": _version(version),
        "idempotency": _idempotency(idempotency_key),
    }


def confirm_work_input(
    show_and_sell_id: str,
    version: int,
    rows: Iterable[tuple[str, str, int]],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    """``rows``: ``(slotId, profileId, actualMinutes)``; ``0`` un-confirms the row,
    1 through the slot's duration confirms it, and the batch is 1-100 rows."""
    return {
        "showAndSellId": show_and_sell_id,
        "work": [
            {"slotId": slot_id, "profileId": profile_id, "actualMinutes": minutes}
            for slot_id, profile_id, minutes in rows
        ],
        "version": _version(version),
        "idempotency": _idempotency(idempotency_key),
    }


_WRITE_INPUT_TYPES: dict[str, str] = {
    "createShowAndSell": "CreateShowAndSellInput",
    "updateShowAndSell": "UpdateShowAndSellInput",
    "cancelShowAndSell": "CancelShowAndSellInput",
    "assignShowAndSellInventory": "AssignShowAndSellInventoryInput",
    "upsertShowAndSellSlot": "UpsertShowAndSellSlotInput",
    "deleteShowAndSellSlot": "DeleteShowAndSellSlotInput",
    "signupScoutForShowAndSellSlot": "SignupShowAndSellSlotInput",
    "cancelShowAndSellSignup": "CancelShowAndSellSignupInput",
    "confirmShowAndSellWork": "ConfirmShowAndSellWorkInput",
}

_BUILDERS: dict[str, tuple[Callable[..., dict[str, Any]], str]] = {
    "createShowAndSell": (create_event_input, "CreateShowAndSellInput"),
    "updateShowAndSell": (update_event_input, "UpdateShowAndSellInput"),
    "cancelShowAndSell": (cancel_event_input, "CancelShowAndSellInput"),
    "assignShowAndSellInventory": (assign_inventory_input, "AssignShowAndSellInventoryInput"),
    "upsertShowAndSellSlot": (upsert_slot_input, "UpsertShowAndSellSlotInput"),
    "deleteShowAndSellSlot": (delete_slot_input, "DeleteShowAndSellSlotInput"),
    "signupScoutForShowAndSellSlot": (signup_input, "SignupShowAndSellSlotInput"),
    "cancelShowAndSellSignup": (cancel_signup_input, "CancelShowAndSellSignupInput"),
    "confirmShowAndSellWork": (confirm_work_input, "ConfirmShowAndSellWorkInput"),
}

#: One worked sample per input type, with contract-shaped arguments, so its
#: keys can be compared to the SDL's member list.
_SAMPLES: dict[str, dict[str, Any]] = {
    "CreateShowAndSellInput": create_event_input(
        "UC#x",
        "Riverside Grange",
        _SAMPLE_CLOCK.iso(days=7),
        _SAMPLE_CLOCK.iso(days=7, hours=3, minutes=30),
        address="14 Grange Way",
        we_owe_enabled=True,
        idempotency_key=idempotency_key_for("createShowAndSell", _SAMPLE_CLOCK.token),
    ),
    "UpdateShowAndSellInput": update_event_input(
        "SHOW#x",
        1,
        location_name="Riverside Grange",
        we_owe_enabled=False,
        idempotency_key=idempotency_key_for("updateShowAndSell", _SAMPLE_CLOCK.token),
    ),
    "CancelShowAndSellInput": cancel_event_input(
        "SHOW#x", 1, "Vendor conflict", idempotency_key=idempotency_key_for("cancelShowAndSell", _SAMPLE_CLOCK.token)
    ),
    "AssignShowAndSellInventoryInput": assign_inventory_input(
        "SHOW#x",
        [("PROD#x", 12)],
        1,
        idempotency_key=idempotency_key_for("assignShowAndSellInventory", _SAMPLE_CLOCK.token),
    ),
    "UpsertShowAndSellSlotInput": upsert_slot_input(
        "SHOW#x",
        1,
        _SAMPLE_CLOCK.iso(days=7),
        _SAMPLE_CLOCK.iso(days=7, hours=1, minutes=30),
        2,
        slot_id="SLOT#x",
        label="First Sales",
        slot_version=1,
        idempotency_key=idempotency_key_for("upsertShowAndSellSlot", _SAMPLE_CLOCK.token),
    ),
    "DeleteShowAndSellSlotInput": delete_slot_input(
        "SHOW#x",
        "SLOT#x",
        1,
        idempotency_key=idempotency_key_for("deleteShowAndSellSlot", _SAMPLE_CLOCK.token),
    ),
    "SignupShowAndSellSlotInput": signup_input(
        "SHOW#x",
        "SLOT#x",
        "CAMP#x",
        "PROFILE#x",
        idempotency_key=idempotency_key_for("signupScoutForShowAndSellSlot", _SAMPLE_CLOCK.token),
    ),
    "CancelShowAndSellSignupInput": cancel_signup_input(
        "SHOW#x",
        "SLOT#x",
        "PROFILE#x",
        1,
        idempotency_key=idempotency_key_for("cancelShowAndSellSignup", _SAMPLE_CLOCK.token),
    ),
    "ConfirmShowAndSellWorkInput": confirm_work_input(
        "SHOW#x",
        1,
        [("SLOT#x", "PROFILE#x", 90)],
        idempotency_key=idempotency_key_for("confirmShowAndSellWork", _SAMPLE_CLOCK.token),
    ),
}


# ------------------------------------------------------------------
# 5. Documents -- the field selections the lane sends
# ------------------------------------------------------------------
#
# Same voice as the Stage 2 module: the documents are GraphQL text, so
# ``stage_two._selection_tree`` / ``_check_selections`` walk them against the
# SDL and a projection that renamed a field fails the contract check before
# any write is sent.

_ADMIN_FIELDS = """
    showAndSellId unitId unitCampaignId locationName address startAt endAt status
    splitMethod weOweEnabled productIds version createdAt updatedAt
    createdByAccountId updatedByAccountId cancelledByAccountId cancelledAt cancellationReason
    allocations {
      unitCampaignId productId showAndSellId startAt endAt status
      allocatedQty soldQty releasedQty remainingQty version
    }
    slots {
      showAndSellId slotId label startAt endAt capacity activeSignupCount version
    }
"""
# approvedFinalizationId and latestFinalizationId are deliberately absent: they
# are §5's finalization pointers and belong to Stage 5.

_OPPORTUNITY_FIELDS = """
    showAndSellId locationName address startAt endAt status splitMethod weOweEnabled
    timezone eventVersion
    slots { slotId label startAt endAt capacity openCapacity }
    mySignups { showAndSellId slotId startAt endAt status actualMinutes signupVersion }
"""

_ALLOC_FIELDS = """
      unitCampaignId productId showAndSellId startAt endAt status
      allocatedQty soldQty releasedQty remainingQty version
"""

_SIGNUP_FIELDS = """
      showAndSellId slotId profileId unitCampaignId campaignId status actualMinutes
      signedUpByAccountId confirmedByAccountId confirmedAt version
"""

_COMMITMENT_FIELDS = """
      showAndSellId slotId startAt endAt status signupVersion
"""

# Slot and signup mutations answer their own rows, not the whole event: an
# upsert returns the slot, a delete a Boolean, and a signup or its cancellation
# returns the participant-safe signup.
_SLOT_FIELDS = """
      showAndSellId slotId label startAt endAt capacity activeSignupCount version
"""

_PARTICIPANT_FIELDS = """
      showAndSellId slotId startAt endAt status actualMinutes signupVersion
"""

_PAGE = "pageInfo { endCursor hasNextPage }"

_DOCUMENTS: dict[str, str] = {
    "showAndSell": (
        "query ShowAndSell($showAndSellId: ID!) {\n"
        "  showAndSell(showAndSellId: $showAndSellId) {" + _ADMIN_FIELDS + "  }\n}\n"
    ),
    "showAndSells": (
        "query ShowAndSells($unitCampaignId: ID!, $status: ShowAndSellStatus, $page: PageInput) {\n"
        "  showAndSells(unitCampaignId: $unitCampaignId, status: $status, page: $page) {\n"
        "    items {" + _ADMIN_FIELDS + "    }\n    " + _PAGE + "\n  }\n}\n"
    ),
    "unitCampaignOpportunities": (
        "query UnitCampaignOpportunities($unitCampaignId: ID!, $includePast: Boolean, $page: PageInput) {\n"
        "  unitCampaignOpportunities(unitCampaignId: $unitCampaignId, includePast: $includePast, page: $page) {\n"
        "    items {" + _OPPORTUNITY_FIELDS + "    }\n    " + _PAGE + "\n  }\n}\n"
    ),
    "showAndSellOpportunity": (
        "query ShowAndSellOpportunity($showAndSellId: ID!, $profileId: ID!) {\n"
        "  showAndSellOpportunity(showAndSellId: $showAndSellId, profileId: $profileId) {"
        + _OPPORTUNITY_FIELDS
        + "  }\n}\n"
    ),
    "eventInventoryAllocations": (
        "query EventInventoryAllocations($unitCampaignId: ID!, $productId: ID, $showAndSellId: ID, $status: AllocationStatus, $page: PageInput) {\n"
        "  eventInventoryAllocations(unitCampaignId: $unitCampaignId, productId: $productId, showAndSellId: $showAndSellId, status: $status, page: $page) {\n"
        "    items {" + _ALLOC_FIELDS + "    }\n    " + _PAGE + "\n  }\n}\n"
    ),
    "showAndSellSignups": (
        "query ShowAndSellSignups($showAndSellId: ID!, $status: SignupStatus, $page: PageInput) {\n"
        "  showAndSellSignups(showAndSellId: $showAndSellId, status: $status, page: $page) {\n"
        "    items {" + _SIGNUP_FIELDS + "    }\n    " + _PAGE + "\n  }\n}\n"
    ),
    "myScoutCommitments": (
        "query MyScoutCommitments($profileId: ID!, $unitId: ID, $includeCancelled: Boolean, $page: PageInput) {\n"
        "  myScoutCommitments(profileId: $profileId, unitId: $unitId, includeCancelled: $includeCancelled, page: $page) {\n"
        "    items {" + _COMMITMENT_FIELDS + "    }\n    " + _PAGE + "\n  }\n}\n"
    ),
    "showAndSellSignupCalendarData": (
        "query ShowAndSellSignupCalendarData($showAndSellId: ID!, $slotId: ID!, $profileId: ID!) {\n"
        "  showAndSellSignupCalendarData(showAndSellId: $showAndSellId, slotId: $slotId, profileId: $profileId) {\n"
        "    unitId unitDisplayName unitCampaignId unitCampaignName showAndSellId slotId\n"
        "    profileId slotLabel locationName address timezone slotStartAt slotEndAt\n"
        "  }\n}\n"
    ),
    "createShowAndSell": (
        "mutation CreateShowAndSell($input: CreateShowAndSellInput!) {\n"
        "  createShowAndSell(input: $input) {" + _ADMIN_FIELDS + "  }\n}\n"
    ),
    "updateShowAndSell": (
        "mutation UpdateShowAndSell($input: UpdateShowAndSellInput!) {\n"
        "  updateShowAndSell(input: $input) {" + _ADMIN_FIELDS + "  }\n}\n"
    ),
    "cancelShowAndSell": (
        "mutation CancelShowAndSell($input: CancelShowAndSellInput!) {\n"
        "  cancelShowAndSell(input: $input) {\n"
        "    event {" + _ADMIN_FIELDS + "    }\n"
        "    releasedAllocations {" + _ALLOC_FIELDS + "    }\n"
        "    cancelledSignups {" + _SIGNUP_FIELDS + "    }\n  }\n}\n"
    ),
    "assignShowAndSellInventory": (
        "mutation AssignShowAndSellInventory($input: AssignShowAndSellInventoryInput!) {\n"
        "  assignShowAndSellInventory(input: $input) {\n"
        "    allocations {" + _ALLOC_FIELDS + "    }\n"
        "    warnings { code productId currentStockQty assignedQty overageQty message }\n"
        "  }\n}\n"
    ),
    "upsertShowAndSellSlot": (
        "mutation UpsertShowAndSellSlot($input: UpsertShowAndSellSlotInput!) {\n"
        "  upsertShowAndSellSlot(input: $input) {" + _SLOT_FIELDS + "  }\n}\n"
    ),
    "deleteShowAndSellSlot": (
        "mutation DeleteShowAndSellSlot($input: DeleteShowAndSellSlotInput!) {\n"
        "  deleteShowAndSellSlot(input: $input)\n}\n"
    ),
    "signupScoutForShowAndSellSlot": (
        "mutation SignupScoutForShowAndSellSlot($input: SignupShowAndSellSlotInput!) {\n"
        "  signupScoutForShowAndSellSlot(input: $input) {" + _PARTICIPANT_FIELDS + "  }\n}\n"
    ),
    "cancelShowAndSellSignup": (
        "mutation CancelShowAndSellSignup($input: CancelShowAndSellSignupInput!) {\n"
        "  cancelShowAndSellSignup(input: $input) {" + _PARTICIPANT_FIELDS + "  }\n}\n"
    ),
    "confirmShowAndSellWork": (
        "mutation ConfirmShowAndSellWork($input: ConfirmShowAndSellWorkInput!) {\n"
        "  confirmShowAndSellWork(input: $input) {\n"
        "    work {" + _SIGNUP_FIELDS + "    }\n"
        "    preview {\n"
        "      eventVersion totalConfirmedMinutes confirmedWorkRows confirmedParticipants\n"
        "      minimumFinalizationActions\n"
        "    }\n  }\n}\n"
    ),
}

#: Field → the document the lane sends for it.
STAGE_THREE_DOCUMENTS: dict[str, str] = dict(_DOCUMENTS)

#: The Stage 3 lane's non-Stage-3 calls are the Stage 2 lane's support
#: documents verbatim — the roster, the Unit Campaign, and the catalog reads
#: it needs before a write.  (``listScoutCampaignJoins`` is deliberately not
#: here: this SDL declares no such query.)
STAGE_THREE_SUPPORT_DOCUMENTS: dict[str, str] = dict(stage_two.STAGE_TWO_SUPPORT_DOCUMENTS)


# ------------------------------------------------------------------
# 6. Conflict pairs -- the colliding calls and the answer each earns
# ------------------------------------------------------------------


def conflict_row(op: str, refusal: str) -> dict[str, object]:
    """One collision: the colliding operation and the named refusal it earns.
    The code, sentence and acceptance ids are looked up, never restated, so
    the refusal table stays the single owner."""
    if op not in _WRITE_INPUT_TYPES:
        raise KeyError(f"{op!r} is not a Stage 3 write")
    answer = STAGE_THREE_REFUSAL_ANSWERS[refusal]
    return {
        "op": op,
        "refusal": refusal,
        "code": answer["code"],
        "subcode": answer["subcode"],
        "acceptance": STAGE_THREE_REFUSALS[refusal],
    }


#: The §3.6.2 conflict pairs: each row is the second call of a collision the
#: walkthrough replays against the deployed stack.
STAGE_THREE_CONFLICT_PAIRS: tuple[dict[str, object], ...] = (
    conflict_row("signupScoutForShowAndSellSlot", "duplicate-signup"),
    conflict_row("signupScoutForShowAndSellSlot", "capacity-full"),
    conflict_row("signupScoutForShowAndSellSlot", "cross-campaign-overlap"),
    conflict_row("signupScoutForShowAndSellSlot", "signup-window-closed"),
    conflict_row("cancelShowAndSellSignup", "stale-event-version"),
    conflict_row("upsertShowAndSellSlot", "slot-limit"),
    conflict_row("upsertShowAndSellSlot", "capacity-range"),
    conflict_row("upsertShowAndSellSlot", "slot-board-closed"),
    conflict_row("deleteShowAndSellSlot", "slot-holds-scouts"),
    conflict_row("confirmShowAndSellWork", "work-over-duration"),
    conflict_row("confirmShowAndSellWork", "work-batch-cap"),
    conflict_row("confirmShowAndSellWork", "work-row-duplicated"),
    conflict_row("confirmShowAndSellWork", "work-window-closed"),
    conflict_row("updateShowAndSell", "edit-state-refusal"),
    conflict_row("cancelShowAndSell", "cancel-started-event"),
    conflict_row("assignShowAndSellInventory", "concurrent-over-assignment"),
    conflict_row("assignShowAndSellInventory", "assignment-empty-items"),
    conflict_row("signupScoutForShowAndSellSlot", "removed-member-signup"),
    conflict_row("signupScoutForShowAndSellSlot", "unjoined-scout-signup"),
    conflict_row("signupScoutForShowAndSellSlot", "cross-campaign-roster"),
)


def stage_three_refusal(name: str) -> Mapping[str, str]:
    """The exact answer a named refusal earns, raising ``KeyError`` for a name
    the table does not carry."""
    return STAGE_THREE_REFUSAL_ANSWERS[name]


def refusal_violations(refusal: str, observed: Sequence[Mapping[str, str]]) -> list[str]:
    """Compare one live error answer to the table.

    ``observed`` rows carry what ``show_sell_graphql.error_summaries`` read
    (the code has four homes; the summary has one spelling per error):
    ``{"code": ..., "message": ...}``.  The first row carrying the expected
    code and sentence fragment satisfies the refusal; nothing does, the
    difference is named.
    """
    answer = STAGE_THREE_REFUSAL_ANSWERS[refusal]
    code, sentence = answer["code"], answer["sentence"]
    for row in observed:
        observed_code = str(row.get("code") or row.get("errorCode") or "")
        observed_message = str(row.get("message") or "")
        if observed_code == code and (not sentence or sentence in observed_message):
            return []
    return [
        f"{refusal}: expected {code}"
        + (f" with {sentence!r}" if sentence else "")
        + f", the lane observed {list(observed)}"
    ]


def refusal_violations_from_response(refusal: str, data: Mapping[str, Any]) -> list[str]:
    """The same check from a raw GraphQL response: the four error-code homes
    are read by ``show_sell_graphql.error_summaries`` first, then compared."""
    return refusal_violations(refusal, show_sell_graphql.error_summaries(data))


# ------------------------------------------------------------------
# 7. Ledger -- inventory, credit and cash must reconcile
# ------------------------------------------------------------------
#
# A Stage 3 write may move only the ``assignedDelta`` column of one
# ``EVENT_ASSIGN`` / ``EVENT_MANUAL_REDUCE`` / ``EVENT_RELEASE`` movement row;
# physical stock, sold-in-possession, custody and Council-on-order stay at
# zero by construction.  The derived quantities a reader recomputes are the
# formulas :func:`src.utils.inventory_models.derived_inventory_quantities`
# computes per request — so the check compares the answer against the rows it
# derives from, never against a stored copy.


def assigned_by_product(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Sum ``allocatedQty`` per product over the event's allocation rows."""
    totals: dict[str, int] = {}
    for row in rows:
        totals[str(row.get("productId", ""))] = totals.get(str(row.get("productId", "")), 0) + int(
            row.get("allocatedQty", 0)
        )
    return totals


def stock_snapshot(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """The four stored columns per product — the ones a Stage 3 write must
    leave alone, in the order :data:`STAGE_THREE_STOCK_COLUMNS` spells them."""
    snapshot: dict[str, dict[str, int]] = {}
    for row in rows:
        product = str(row.get("productId", ""))
        entry = snapshot.setdefault(product, {column: 0 for column in STAGE_THREE_STOCK_COLUMNS})
        for column in STAGE_THREE_STOCK_COLUMNS:
            entry[column] = int(row.get(column, 0))
    return snapshot


def stage_three_ledger_invariants(
    sold_units: list[dict[str, Any]],
    credits: list[dict[str, Any]],
    cash_cents: int,
    sold_cents: int,
) -> tuple[str, ...]:
    """Check the post-finalization ledger against the derived quantities.

    ``sold_units``: ``{"productId": ..., "units": ..., "cents": ...}`` — one row per product.
    ``credits``: ``{"profileId": ..., "cents": ...}`` — one row per Scout whose We Owe
    obligation was approved.  ``sold_cents`` is the recorded sale total and
    ``cash_cents`` the cash that actually landed.  Returns the violated
    invariants — empty when the ledger holds:

    * no negative sold units, cash, or credit;
    * the ledger's sale total equals the recorded ``sold_cents``;
    * ``sold_cents - credits == cash_cents`` (the We Owe balance).
    """
    problems: list[str] = []
    total_units = sum(row["units"] for row in sold_units)
    total_cents = sum(row["units"] * row["cents"] for row in sold_units)
    if total_units < 0:
        problems.append("negative inventory: sold units < 0")
    if total_cents != sold_cents:
        problems.append(f"cash mismatch: ledger {total_cents} != recorded {sold_cents}")
    if cash_cents < 0:
        problems.append("negative cash: cash cents < 0")
    credit_total = sum(row["cents"] for row in credits)
    if credit_total < 0:
        problems.append("negative scout credit: credit cents < 0")
    if sold_cents - credit_total != cash_cents:
        problems.append(f"we-owe mismatch: sold {sold_cents} - credit {credit_total} != cash {cash_cents}")
    return tuple(problems)


# ------------------------------------------------------------------
# 8. The two workflow states no mutation reaches, and the builder that does
# ------------------------------------------------------------------
#
# §3.6.2 names FINALIZED and REOPENED, and ``API-FIX-01`` makes a fixture for
# every one of those states an acceptance criterion, with the section closing:
# "A missing required fixture makes the scenario blocked; it does not justify
# skipping its security assertion."  ``finalizeShowAndSell`` and
# ``reopenShowAndSell`` are §5's mutations and are absent from this SDL, so the
# states cannot be reached through a public write *yet* — which is a reason to
# build them with the documented fixture builder (smoke plan FIX-AC-04's
# "documented test fixtures"), never a reason to drop them from the tree.
#
# :mod:`tests.e2e.utils.show_sell_stage3_scenario` is that builder: it renders the
# ``SHOW_AND_SELL#<id>/METADATA`` row with :func:`src.utils.show_and_sell_models.build_show_and_sell_item`
# (so a row that would break a §5.10 invariant raises instead of landing), reads the
# row back, and returns a named verdict.  When the QA identity
# ``kernelworx-qa-ue1-dev`` cannot read or write that row, the verdict is ``blocked``
# and names the DynamoDB action it is denied — the same way ``scripts/qa_fixture.py``
# reports ``BLOCKED <table>: <action> is not granted to this identity`` rather than
# treating a denied scan as an empty table.

#: The §3.6.2 states this SDL has no public write for.  They are fixture-builder
#: states, not absent ones: a lane that cannot build one reports it blocked.
STAGE_THREE_BUILDER_ONLY_STATE_FIXTURES: tuple[str, ...] = (
    show_and_sell_models.STATUS_FINALIZED,
    show_and_sell_models.STATUS_REOPENED,
)

#: Why a builder is needed, in the words the evidence record needs.
BUILDER_ONLY_STATE_FIXTURE_NOTE = (
    "FINALIZED and REOPENED need §5's finalizeShowAndSell/reopenShowAndSell, which this SDL does not "
    "declare: §3.6.2 and API-FIX-01 still require the fixture, so the lane writes the row with the "
    "documented DynamoDB fixture builder and reports BLOCKED naming the grant it is denied — it never "
    "fakes the state and never drops it"
)

#: The aggregate table every Stage 3 row lives in.  The physical name is the
#: stack's own: ``tofu/application/modules/dynamodb/main.tf`` declares
#: ``${var.name_prefix}-show-and-sells${local.table_suffix}`` and exports it as
#: ``show_and_sells_table_name``, each environment feeds it to Lambda as
#: ``SHOW_AND_SELLS_TABLE_NAME``, and ``tests/unit/conftest.py`` injects the dev value.
DEV_SHOW_AND_SELLS_TABLE = "kernelworx-show-and-sells-ue1-dev"


def show_and_sells_table() -> str:
    """The physical ``show_and_sells`` table this lane's rows live in."""
    return os.environ.get("SHOW_AND_SELLS_TABLE_NAME") or DEV_SHOW_AND_SELLS_TABLE


# ------------------------------------------------------------------
# 9. Calendar data and the ICS the browser produces
# ------------------------------------------------------------------
#
# CAL-01/CAL-02/RPT-00: no server generates, stores, or serves a calendar
# file.  The browser assembles the invite itself from the authorized
# ``showAndSellSignupCalendarData`` read (``frontend/src/lib/showSell.ts``'s
# ``buildInvite``) and downloads it locally.  These helpers own the DTO the
# read answers and the validator the lane feeds the bytes the browser
# actually downloaded.

CALENDAR_DTO_FIELDS: tuple[str, ...] = (
    "unitId",
    "unitDisplayName",
    "unitCampaignId",
    "unitCampaignName",
    "showAndSellId",
    "slotId",
    "profileId",
    "slotLabel",
    "locationName",
    "address",
    "timezone",
    "slotStartAt",
    "slotEndAt",
)

ICS_CHECKS: tuple[str, ...] = (
    "CAL-01: the file the lane validates is the one the browser produced and downloaded, and the UID is "
    "the same on every download of one signup",
    "CAL-02: one VCALENDAR with CALSCALE:GREGORIAN and METHOD:PUBLISH and exactly one VEVENT, date-times "
    "in UTC with an explicit Z and no TZID parameter and no VTIMEZONE block (what buildInvite emits), and "
    "every physical line inside RFC 5545's 75-octet limit",
    "RPT-00: no server artifact — no download URL, no stored file, no notification",
)

#: RFC 5545 §3.1: a line is folded to at most 75 octets, excluding the CRLF.  This is
#: what the validator enforces, because it is the limit a calendar client enforces — and it
#: is deliberately *not* tightened to the emitter's own budget below, because the emitter's
#: continuation lines are ``1 + ICS_FOLD_OCTETS`` = 74 octets wide: ``foldIcsLine`` budgets 73
#: octets for the segment and RFC 5545 folding writes the break as CRLF plus a leading space,
#: so a real capture's widest physical line is 74.  A limit of 73 would reject the file the
#: browser actually downloaded, which is the opposite of what this validator is for.
ICS_MAX_LINE_OCTETS = 75

#: What ``buildInvite`` budgets per folded segment (``ICS_FOLD_OCTETS`` in ``frontend/src/lib/showSell.ts``).
#: Not an acceptance limit: it is the emitter's own number, used to explain a capture's width.
ICS_FOLD_OCTETS = 73

#: The two captures of ``buildInvite`` output the validator is fed: the same signup built
#: twice, so the UID comparison is between two real downloads rather than a claim about one.
ICS_CAPTURE_NAMES: tuple[str, ...] = ("show_sell_stage3_invite_build.ics", "show_sell_stage3_invite_build_repeat.ics")

#: The ``CalendarInviteData`` answer those two captures were built from, and the two clocks they
#: were built at — one build, one repeat of the same download.  The pair is what makes CAL-01
#: executable rather than asserted: the UID is the signup's identity, so two downloads of this
#: DTO must carry the same UID and different ``DTSTAMP`` values, and :func:`calendar_invite_uid`
#: rebuilds that UID from these fields and compares it to the bytes on disk.
#:
#: Re-cut both files after any change to the emitter, from the repository root:
#:
#: .. code-block:: text
#:
#:     node_modules/.bin/esbuild frontend/src/lib/showSell.ts --bundle --format=esm \
#:         --outfile=/tmp/showSell.mjs
#:
#: then import ``buildInvite`` from that bundle and write one file per download, exactly one DTO
#: and one clock each, with the bytes written verbatim (no newline translation):
#:
#: .. code-block:: text
#:
#:     buildInvite(ICS_CAPTURE_DTO, new Date(ICS_CAPTURE_CLOCKS[0]))  # -> show_sell_stage3_invite_build.ics
#:     buildInvite(ICS_CAPTURE_DTO, new Date(ICS_CAPTURE_CLOCKS[1]))  # -> ..._invite_build_repeat.ics
#:
#: The DTO is the SS-SM-06 lane's own shape — a Unit Campaign, an event whose location name carries
#: an address with an ``&`` and commas, and a Scout profile — because escaping and folding only get
#: exercised if the input has something to escape.
ICS_CAPTURE_DTO: Mapping[str, Any] = {
    "unitId": "UNIT#pack-3149",
    "unitDisplayName": "Smoke Pack 3149",
    "unitCampaignId": "UNITCAMP#pack-3149-ss-sm-06-l01",
    "unitCampaignName": "Fall Popcorn 2026",
    "showAndSellId": "SSE#library-on-main",
    "slotId": "SLOT#first-sales",
    "profileId": "PROFILE#avery-scout",
    "slotLabel": "First Sales",
    "locationName": "Library on Main — 200 Main St & Elm",
    "address": "200 Main St, Elm Court, Apt 3",
    "timezone": "America/Denver",
    "slotStartAt": "2026-03-28T15:00:00.000Z",
    "slotEndAt": "2026-03-28T16:30:00.000Z",
}

#: The two ``generatedAt`` clocks behind :data:`ICS_CAPTURE_NAMES`, in that order.
ICS_CAPTURE_CLOCKS: tuple[str, ...] = ("2026-03-21T15:04:05Z", "2026-03-21T15:09:47Z")

_UTC_DATE_TIME = re.compile(r"\A\d{8}T\d{6}Z\Z")
_TEXT_PROPERTIES = ("SUMMARY", "LOCATION", "DESCRIPTION", "COMMENT")
_REQUIRED_VCALENDAR: tuple[tuple[str, str], ...] = (
    ("VERSION", "2.0"),
    ("CALSCALE", "GREGORIAN"),
    ("METHOD", "PUBLISH"),
)
_REQUIRED_VEVENT: tuple[str, ...] = ("UID", "DTSTAMP", "DTSTART", "DTEND")
#: The escape sequences ``escapeIcsText`` can produce: ``\\``, ``\;``, ``\,``, ``\n``.
_TEXT_ESCAPES = frozenset("\\;,nN")
#: Components ``buildInvite`` never writes.  ``VTIMEZONE`` is the one that matters for CAL-02:
#: a ``TZID`` is only meaningful when the same file carries that zone's definitions, and the
#: browser deliberately writes UTC instead of inventing them.
_FORBIDDEN_COMPONENTS = ("VTIMEZONE", "VALARM", "VJOURNAL", "VTODO", "STANDARD", "DAYLIGHT")


class _IcsLine(NamedTuple):
    """One unfolded property: its name, its parameters, and everything after the first colon."""

    name: str
    params: tuple[str, ...]
    value: str


def _physical_lines(text: str) -> tuple[list[str], list[str]]:
    """The file's physical lines, and every way the line breaks or their length break RFC 5545."""
    problems: list[str] = []
    if not text:
        return [], ["file: empty, so there is no calendar to validate"]
    if not text.endswith("\r\n"):
        problems.append("file: does not end with a CRLF line break")
    body = text[:-2] if text.endswith("\r\n") else text
    lines = body.split("\r\n")
    for line in lines:
        if "\r" in line:
            problems.append(f"a bare CR inside a line, which ends the property for any reader: {line[:40]!r}")
        if "\n" in line:
            problems.append(f"a line ends with a bare LF, not CRLF: {line[:40]!r}")
        octets = len(line.encode("utf-8"))
        if octets > ICS_MAX_LINE_OCTETS:
            problems.append(
                f"an unfolded line of {octets} octets exceeds RFC 5545's {ICS_MAX_LINE_OCTETS}-octet limit: {line[:32]!r}"
            )
    return lines, problems


def _unfold(physical: Sequence[str]) -> list[str]:
    """Join RFC 5545 folding: a physical line starting with a space or tab continues the last one."""
    logical: list[str] = []
    for line in physical:
        if line[:1] in (" ", "\t") and logical:
            logical[-1] += line[1:]
        else:
            logical.append(line)
    return logical


def _parse_property(line: str) -> _IcsLine | None:
    """Split one logical line into name, parameters and value.

    A character scanner rather than a regex, because the parameter list can quote a value that
    contains ``;`` and ``:`` (``DTSTART;X-LOC="Denver, CO":…`` is legal), and a regex that splits on
    the first delimiter mis-reads it as a broken property.
    """
    index = 0
    while index < len(line) and (line[index].isalnum() or line[index] in "-_"):
        index += 1
    if index == 0:
        return None
    name = line[:index].upper()
    params: list[str] = []
    buffer: list[str] = []
    quoted = False
    while index < len(line):
        character = line[index]
        if quoted:
            buffer.append(character)
            if character == '"':
                quoted = False
        elif character == '"':
            buffer.append(character)
            quoted = True
        elif character == ";":
            params.append("".join(buffer))
            buffer = []
        elif character == ":":
            params.append("".join(buffer))
            return _IcsLine(name, tuple(params), line[index + 1 :])
        else:
            buffer.append(character)
        index += 1
    return None


def _text_problems(name: str, value: str) -> list[str]:
    """Unescaped delimiters and control characters in a TEXT value.

    ``escapeIcsText`` in ``frontend/src/lib/showSell.ts`` escapes ``\\``, ``;``, ``,``, and every
    carriage return or line feed.  A value that reaches the validator with a bare ``;`` or ``,``,
    or with a backslash that escapes nothing, is a file the browser did not produce — and one a
    reader will parse as fewer properties than the invite holds.
    """
    problems: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\":
            if index + 1 >= len(value):
                problems.append(f"{name}: a trailing backslash escapes nothing")
                break
            following = value[index + 1]
            if following not in _TEXT_ESCAPES:
                problems.append(f"{name}: {character!r}{following!r} is not an escape buildInvite writes")
            index += 2
            continue
        if character in ";,":
            problems.append(f"{name}: an unescaped {character!r} inside a TEXT value")
        elif character in "\r\n\t":
            problems.append(f"{name}: a control character inside a TEXT value")
        index += 1
    return problems


def _parse_utc_date_time(value: str) -> datetime | None:
    """A UTC date-time as RFC 5545 writes it — ``YYYYMMDDTHHMMSSZ`` — or nothing."""
    if not _UTC_DATE_TIME.match(value):
        return None
    return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def validate_ics(text: str, uid: str) -> tuple[str, ...]:
    """Validate a browser-produced invite against CAL-01/CAL-02.

    Returns the violated checks — empty when the file is acceptable.  What it accepts is what
    ``buildInvite`` emits, and what it rejects is the opposite:

    * a ``TZID`` parameter or a ``VTIMEZONE`` block — the invite names UTC with an explicit ``Z``
      precisely so it never has to invent a ``VTIMEZONE`` it does not own;
    * a floating (no ``Z``) or date-only date-time, which lands the invite an hour out in every
      zone but the writer's;
    * a UID that is not the one this signup's identity produces, which is CAL-01's stability claim;
    * an unfolded line over RFC 5545's 75 octets, a missing ``BEGIN``/``END``, or a missing
      ``METHOD:PUBLISH``/``CALSCALE``/``VERSION``;
    * TEXT the emitter did not escape, which a reader parses as extra properties.

    It is a line parser and a component state machine, so a property that only appears after
    ``END:VEVENT`` or only inside the wrong component is caught by structure rather than by a
    whole-document match.
    """
    problems: list[str] = []
    physical, line_problems = _physical_lines(text)
    problems.extend(line_problems)

    stack: list[str] = []
    components: list[str] = []
    event_count = 0
    counts: dict[str, dict[str, int]] = {}
    values: dict[tuple[str, str], str] = {}

    for line in _unfold(physical):
        parsed = _parse_property(line)
        if parsed is None:
            problems.append(f"not a property line: {line[:40]!r}")
            continue
        name, params, value = parsed
        for param in params:
            key = param.split("=", 1)[0].strip().upper()
            if key == "TZID":
                problems.append(
                    f"{name}: a TZID parameter with no VTIMEZONE in this file — buildInvite writes UTC with "
                    "an explicit Z, and a TZID alone is the hour-out invite CAL-02 exists to catch"
                )
        if name == "BEGIN":
            if value.upper() in _FORBIDDEN_COMPONENTS:
                problems.append(f"BEGIN:{value} — the browser emits no {value} block in an invite")
            components.append(value)
            if value == "VEVENT":
                event_count += 1
            stack.append(value)
            continue
        if name == "END":
            if not stack:
                problems.append(f"END:{value} with no matching BEGIN")
            elif stack[-1] != value:
                problems.append(f"END:{value} closes {stack[-1]}, not {value}")
            else:
                stack.pop()
            continue
        if not stack:
            problems.append(f"{name} appears outside any component")
            continue
        component = stack[-1]
        per_component = counts.setdefault(component, {})
        per_component[name] = per_component.get(name, 0) + 1
        values.setdefault((component, name), value)
        if name in _TEXT_PROPERTIES:
            problems.extend(_text_problems(name, value))
        if name in ("DTSTART", "DTEND", "DTSTAMP") and component == "VEVENT":
            if _parse_utc_date_time(value) is None:
                problems.append(f"{name}: {value!r} is not a UTC date-time with an explicit Z (RFC 5545 §3.3.5)")

    if "VCALENDAR" not in components:
        problems.append("VCALENDAR: no BEGIN:VCALENDAR")
    if stack:
        problems.append(f"components left open at the end of the file: {stack}")
    if event_count != 1:
        problems.append(f"VEVENT: expected exactly one event, found {event_count}")

    for required_name, required_value in _REQUIRED_VCALENDAR:
        found = _value_at(values, "VCALENDAR", required_name)
        if found is None:
            problems.append(f"VCALENDAR: no {required_name}:{required_value}")
        elif found != required_value:
            problems.append(f"VCALENDAR: {required_name} is {found!r}, the invite writes {required_value!r}")
    for required_name in _REQUIRED_VEVENT:
        if _value_at(values, "VEVENT", required_name) is None:
            problems.append(f"VEVENT: no {required_name}")
    for component, per_component in counts.items():
        for name, seen in per_component.items():
            if seen > 1 and (component != "VEVENT" or name in _REQUIRED_VEVENT or name in _TEXT_PROPERTIES):
                problems.append(f"{component}.{name}: seen {seen} times, an invite carries one")

    found_uid = _value_at(values, "VEVENT", "UID")
    if found_uid is not None and found_uid != uid:
        problems.append(
            f"UID: expected {uid}, the file writes {found_uid} — CAL-01 makes the UID the signup's identity"
        )

    start = _parse_utc_date_time(_value_at(values, "VEVENT", "DTSTART") or "")
    end = _parse_utc_date_time(_value_at(values, "VEVENT", "DTEND") or "")
    if start and end and end <= start:
        problems.append(f"VEVENT: DTEND {end:%Y%m%dT%H%M%SZ} does not run after DTSTART {start:%Y%m%dT%H%M%SZ}")
    return tuple(problems)


def _value_at(values: Mapping[tuple[str, str], str], component: str, name: str) -> str | None:
    """The first value of ``name`` seen inside ``component``, or nothing if it never appeared."""
    return values.get((component, name))


def ics_property_value(text: str, name: str) -> str:
    """The first unfolded value of one property, for a check that needs a value rather than a verdict.

    Folding is undone first, because the property a check wants may be the one line the emitter had
    to break — the UID of a real signup is 105 characters and never fits in 75 octets.
    """
    for line in _unfold(_physical_lines(text)[0]):
        parsed = _parse_property(line)
        if parsed is not None and parsed.name.upper() == name.upper():
            return parsed.value
    return ""


def ics_uid(text: str) -> str:
    """The UID one invite carries, unfolded first, for the CAL-01 cross-download comparison."""
    return ics_property_value(text, "UID")


def ics_physical_line_octets(text: str) -> tuple[int, ...]:
    """The octet length of every physical line, so a capture can be checked against the
    browser's own 73-octet fold rather than only the RFC's 75-octet ceiling."""
    return tuple(len(line.encode("utf-8")) for line in _physical_lines(text)[0])


def calendar_invite_dto(
    *,
    unit_id: str,
    unit_campaign_id: str,
    unit_campaign_name: str,
    show_and_sell_id: str,
    slot_id: str,
    profile_id: str,
    location_name: str,
    slot_start_at: str,
    slot_end_at: str,
    unit_display_name: str | None = None,
    slot_label: str | None = None,
    address: str | None = None,
    timezone_name: str = UNIT_TIMEZONE,
) -> dict[str, Any]:
    """One ``CalendarInviteData`` answer, shaped the way the SDL spells it."""
    return {
        "unitId": unit_id,
        "unitDisplayName": unit_display_name,
        "unitCampaignId": unit_campaign_id,
        "unitCampaignName": unit_campaign_name,
        "showAndSellId": show_and_sell_id,
        "slotId": slot_id,
        "profileId": profile_id,
        "slotLabel": slot_label,
        "locationName": location_name,
        "address": address,
        "timezone": timezone_name,
        "slotStartAt": slot_start_at,
        "slotEndAt": slot_end_at,
    }


def calendar_dto_violations(dto: Mapping[str, Any]) -> list[str]:
    """A DTO the browser cannot turn into an invite: a missing required field,
    an empty timezone, or an interval that does not run forward."""
    problems: list[str] = []
    for field in CALENDAR_DTO_FIELDS:
        value = dto.get(field)
        required = field not in ("unitDisplayName", "slotLabel", "address")
        if required and not value:
            problems.append(f"{field}: required and missing or empty")
    if dto.get("timezone"):
        try:
            ZoneInfo(str(dto["timezone"]))
        except Exception:
            problems.append(f"timezone: {dto.get('timezone')!r} is not an IANA zone")
    start, end = str(dto.get("slotStartAt", "")), str(dto.get("slotEndAt", ""))
    if start and end and end <= start:
        problems.append(f"slot interval: endAt {end} does not run after startAt {start}")
    return problems


def calendar_invite_uid(unit_campaign_id: str, show_and_sell_id: str, slot_id: str, profile_id: str) -> str:
    """The browser's invite UID — the identity fields make it stable across
    downloads of the same signup (``showSell.ts``'s ``inviteUid``)."""
    return f"kernelworx-show-and-sell-{unit_campaign_id}-{show_and_sell_id}-{slot_id}-{profile_id}@kernelworx.app"


# ------------------------------------------------------------------
# 10. Cleanup — plan, delete, read back, prove the canary survived
# ------------------------------------------------------------------
#
# The vocabulary is the Stage 2 module's (:data:`STRICT_CLEANUP`,
# :func:`run_cleanup_step`, :func:`assert_cleanup_clean`, :func:`fixture_sweep`,
# :func:`sweep_verdict`), imported, not re-implemented.  What Stage 3 adds is a
# plan that names the *table and key of every row* it means to remove, so the
# runner in :mod:`tests.e2e.utils.show_sell_stage3_scenario` can delete each one
# and ``get_item`` it back: a ``delete_item`` that returned without an error is
# not evidence, which is the rule ``scripts/qa_fixture.py`` already applies to a
# sweep (its read-back prints ``LEFT`` for a row the delete did not take).  The
# plan also carries the lane token that owns each row, because a lane that can
# name a row is not a lane that may delete another lane's row — and the canary
# row of a different lane token is what proves the sweep stopped where it should.

#: The reads a cleanup run uses to prove the lane's rows are gone through the application's own API.
STAGE_THREE_CLEANUP_READS: tuple[str, ...] = (
    "showAndSells",
    "showAndSellSignups",
    "eventInventoryAllocations",
    "myScoutCommitments",
)

#: A key cell a live lane never bound.  The runner refuses to send a delete whose key still
#: contains one, rather than deleting whatever a placeholder happens to match.
UNBOUND_KEY_MARKER = "<"

#: What ``scripts/qa_fixture.py`` measured on dev on 2026-11-19: this identity is denied
#: ``dynamodb:Scan`` on ``show-and-sells`` (and ``DeleteItem`` on the Stage 2 lane tables).
#: A fixture builder therefore *measures* its reach with a ``get_item`` and reports the action it
#: is denied; it never assumes a grant it has not seen.
QA_FIXTURE_IDENTITY = "kernelworx-qa-ue1-dev"


class StageThreeCleanupError(StageTwoCleanupError):
    """A Stage 3 cleanup row that failed, in the Stage 2 vocabulary."""


def stage_three_cleanup_plan(
    clock: ScenarioClock,
    fixture: Mapping[str, Any],
    *,
    ids: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """The ordered cleanup plan for one scenario: signups, then slots, then events, then the
    idempotency markers the lane wrote, then the typed-token sweep that catches what the writes missed.

    Each deletable row names its table, its key pair, its row class, and the lane token that owns it.
    Unbound ids stay ``<ref>`` placeholders and the runner refuses them: an unbound key is a row nobody
    identified, and a delete against it is the false clean this gate exists to prevent.
    """
    table = show_and_sells_table()
    lane = clock.token
    rows: list[dict[str, Any]] = []
    slot_events: Mapping[str, str] = fixture["slotEvents"]

    def resolve(value: str) -> str:
        """A bound id when the lane supplied one, otherwise the ``<ref>`` placeholder itself.

        A placeholder in a key is not a bug here: it is the honest answer to "which row?", and
        :func:`tests.e2e.utils.show_sell_stage3_scenario.run_stage_three_cleanup` refuses to send a
        delete for it, so an unbound lane reports blocked rather than deleting a guess.
        """
        key = f"<{value}>"
        if ids is None:
            return key
        return bind_ids(key, {f"<{name}>": bound for name, bound in ids.items()})

    for slot_name in sorted(fixture["slots"]):
        event_name = slot_events.get(slot_name)
        if event_name is None:
            continue
        rows.append(
            {
                "acceptance": "SLOT-M-02",
                "summary": f"delete the lane's slot {slot_name} once it holds nobody",
                "lane": lane,
                "kind": "slot",
                "table": table,
                "key": {
                    "pk": show_and_sell_models.show_and_sell_pk(resolve(f"event.{event_name}")),
                    "sk": show_and_sell_models.slot_sk(resolve(f"slot.{slot_name}")),
                },
            }
        )
    for signup in sorted(fixture["signups"], key=lambda row: (row["event"], row["slot"], row["profile"])):
        rows.append(
            {
                "acceptance": "SS-SM-06 step 6",
                "summary": f"delete the lane's signup for {signup['slot']} by {signup['profile']}",
                "lane": lane,
                "kind": "signup",
                "table": table,
                "key": {
                    "pk": show_and_sell_models.show_and_sell_pk(resolve(f"event.{signup['event']}")),
                    "sk": show_and_sell_models.signup_sk(
                        resolve(f"slot.{signup['slot']}"), resolve(f"profile.{signup['profile']}")
                    ),
                },
            }
        )
    for event_name in sorted(fixture["events"]):
        rows.append(
            {
                "acceptance": "SS-SM-11 step 2",
                "summary": f"delete the lane's event {event_name}",
                "lane": lane,
                "kind": "event",
                "table": table,
                "key": show_and_sell_models.event_metadata_key(resolve(f"event.{event_name}")),
            }
        )
    for step in stage_three_write_steps(fixture, lane):
        rows.append(_marker_row(step, lane=lane, table=table, resolve=resolve))
    # A lane that has already run also has the ledger; the runner unions the two so a write the tree never
    # named is still cleaned.  The rows built here are the *planned* ones, marked so a reader can tell.
    rows.append(
        {
            "acceptance": "§2.8.7",
            "summary": (
                "sweep by typed token — "
                + ", ".join(stage_three_sweep_tokens(lane))
                + " — refusing free text and reporting every row it refused"
            ),
            "lane": lane,
            "kind": "sweep",
            "table": "",
            "key": {},
        }
    )
    return rows


def _marker_row(step: Mapping[str, str], *, lane: str, table: str, resolve: Callable[[str], str]) -> dict[str, Any]:
    """One marker row, addressed the way production addresses it.

    The address comes from :func:`src.utils.mutations.marker_keys` — the same call every Show & Sell
    mutation makes — so the row cleanup names is the row the writer put under the TTL.  Scopes differ by
    operation (an event write scopes to the event, a create to the Unit Campaign), the actor is the
    identity that signed the request, and the sort key is the caller's key, so a hand-assembled
    ``IDEM#actor#op#scope`` with one generic actor and one generic scope addresses nothing.

    A placeholder actor or scope is kept as a placeholder rather than fed to ``marker_keys``, which would
    reject it: the lane has not identified that write, so the row stays blocked instead of addressing a
    marker that was never written.
    """
    actor, scope = resolve(_actor_ref(step)), resolve(step["scopeField"])
    key = idempotency_key_for(step["op"], lane, step["step"])
    if UNBOUND_KEY_MARKER in actor or UNBOUND_KEY_MARKER in scope:
        address = {"pk": f"IDEM#{actor}#{step['op']}#{scope}", "sk": f"IDEM#{key}"}
    else:
        marker = mutations.marker_keys(
            table_key=MARKER_TABLE_KEYS[step["op"]],
            table_name=table,
            actor_id=actor,
            operation=step["op"],
            scope=scope,
            idempotency_key=key,
        )
        address = {"pk": marker.pk, "sk": marker.sk}
    return {
        "acceptance": "API-FIX-03",
        "summary": (
            f"delete the {step['op']} marker this lane wrote with key {key}; the table's TTL would sweep it "
            f"after {MARKER_TTL_SECONDS // 3600} hours, and a lane that waits for the TTL has not cleaned"
        ),
        "lane": lane,
        "kind": "marker",
        "table": table,
        "key": address,
        "idempotencyKey": key,
        "operation": step["op"],
        "actorField": _actor_ref(step),
        "scopeField": step["scopeField"],
    }


#: Every Stage 3 write's marker rides the event aggregate table: ``_show_and_sell_marker`` in
#: ``src/handlers/unit_operations.py`` is the only marker builder these mutations call.
MARKER_TABLE_KEYS: dict[str, str] = dict.fromkeys(STAGE_THREE_WRITES, "show_and_sells")

#: The writes that are one call per scenario rather than one per row of the tree, and the event each one
#: addresses.  These are the mutation ids the walkthrough runs: EVT-M-02 edits an event, EVT-M-03 deletes a
#: slot, SS-SM-11 cancels a signup, and the 101-row confirm runs on the confirm event.
SINGLE_STEP_WRITES: tuple[dict[str, str], ...] = (
    {"op": "updateShowAndSell", "step": "address", "actor": "account.admin", "scopeField": "event.future"},
    {"op": "deleteShowAndSellSlot", "step": "drop", "actor": "account.admin", "scopeField": "event.future"},
    {"op": "cancelShowAndSellSignup", "step": "leave", "actor": "account.charlie", "scopeField": "event.future"},
    {"op": "confirmShowAndSellWork", "step": "rows", "actor": "account.admin", "scopeField": "event.confirm"},
)


def _step_slug(value: str) -> str:
    """A ref in the shape an idempotency key segment may hold, and the shape the sweeper's ``idem`` kind checks."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", str(value))


def stage_three_write_steps(fixture: Mapping[str, Any], lane: str) -> tuple[dict[str, str], ...]:
    """Every idempotent write the scenario sends, with the identity that signs it and the resource that scopes its marker.

    This is derived from the tree rather than listed by hand, so the marker cleanup addresses is the marker
    the writes produce: one create per event, one slot write per planned slot, one assignment per allocation,
    one signup per signup, one cancel per cancelled event, and the four single-step writes.  A refused write
    (the §3.6.2 collisions, the removed-member signup) is **not** here: a rejected mutation writes no marker,
    and a cleanup row for it would delete nothing and prove nothing.
    """
    slot_events: Mapping[str, str] = fixture["slotEvents"]
    steps: list[dict[str, str]] = []
    for name in sorted(fixture["events"]):
        steps.append(
            {
                "op": "createShowAndSell",
                "step": f"create-{_step_slug(name)}",
                "actor": "account.admin",
                "scopeField": "unit-campaign",
            }
        )
        if fixture["events"][name]["setup"].get("op") == "cancelShowAndSell":
            steps.append(
                {
                    "op": "cancelShowAndSell",
                    "step": f"cancel-{_step_slug(name)}",
                    "actor": "account.admin",
                    "scopeField": f"event.{name}",
                }
            )
    for slot in sorted(slot_events):
        steps.append(
            {
                "op": "upsertShowAndSellSlot",
                "step": f"slot-{_step_slug(slot)}",
                "actor": "account.admin",
                "scopeField": f"event.{slot_events[slot]}",
            }
        )
    for group in sorted(fixture["allocations"]):
        event = group if group in fixture["events"] else slot_events.get(group, "")
        for profile_ref, _product, _qty in fixture["allocations"][group]:
            steps.append(
                {
                    "op": "assignShowAndSellInventory",
                    "step": f"assign-{_step_slug(group)}-{_step_slug(str(profile_ref).split('.')[-1])}",
                    "actor": "account.admin",
                    "scopeField": f"event.{event}",
                }
            )
    for entry in fixture["signups"]:
        steps.append(
            {
                "op": "signupScoutForShowAndSellSlot",
                "step": f"signup-{_step_slug(entry['event'])}-{_step_slug(entry['slot'])}-{_step_slug(entry['profile'])}",
                "actor": f"account.{entry['profile']}",
                "scopeField": f"event.{entry['event']}",
            }
        )
    steps += [dict(entry) for entry in SINGLE_STEP_WRITES]
    for step in steps:
        step["idempotencyKey"] = idempotency_key_for(step["op"], lane, step["step"])
    seen: set[str] = set()
    for step in steps:
        key = step["idempotencyKey"]
        if key in seen:
            raise AssertionError(f"two writes share one idempotency address: {key}")
        seen.add(key)
    return tuple(steps)


def _actor_ref(step: Mapping[str, str]) -> str:
    """The id field naming the identity that signs one planned write."""
    return step.get("actorField") or step["actor"]


def stage_three_cleanup_canary(other_lane: str) -> dict[str, Any]:
    """A row that belongs to a *different* lane token and must still be there afterwards.

    The canary is the half of cleanup that a delete-count cannot give: if a sweep removes a row this
    lane never planned, the lane's own read-back still looks clean.  ``scripts/qa_fixture.py``'s sweep
    prints a ``kept`` line for exactly this survivor and treats it as the only survivor that does not
    fail the sweep, and a Stage 3 lane that cannot show one has not shown its teardown stopped anywhere.
    """
    return {
        "acceptance": "SS-SM-11 lane cleanup canary",
        "summary": f"the row lane {other_lane} owns must still be present after this lane's teardown",
        "lane": other_lane,
        "kind": "canary",
        "table": show_and_sells_table(),
        "key": show_and_sell_models.event_metadata_key("canary-event-of-another-lane"),
    }


def stage_three_sweep_tokens(lane: str) -> tuple[str, ...]:
    """The token *kinds* a Stage 3 sweep may name: Stage 2's kinds plus ``idem``.

    This is the vocabulary, not a token list.  A token is ``kind=value``, and the value has to be a real
    id of that kind — see :func:`stage_three_lane_tokens`, which builds the tokens from the ids the lane
    was actually answered.
    """
    return tuple(f"{kind}={lane}" for kind in (*stage_two.LANE_TOKEN_KINDS, "idem"))


#: The ids a Stage 3 lane can name by kind, in the order the sweeper reads them.  Three kinds are absent,
#: each for a reason the reviewer can check rather than a reason the lane decides at run time:
#:
#: * ``order`` and ``join-code`` — this card's lane mints neither an Order nor a join code;
#: * ``data-id`` — the Stage 3 ``DATA_ID`` is ``<run>-<scenario>-<lane>-<attempt>`` and starts with an epoch,
#:   while the sweeper's ``data-id`` rule wants ``[a-z][a-z0-9]*(-[a-z0-9]+)+`` and refuses anything else.
#:   The lane therefore names every row it was *answered* an id for, which is the stronger claim: an id is
#:   compared to the key column of the kind that stores it.
SWEEP_TOKEN_ID_FIELDS: tuple[tuple[str, str], ...] = (("unit", "unit"), ("unit-campaign", "unit-campaign"))
#: The profile and Scout Campaign refs are enumerated from the tree rather than hard-coded, so a lane
#: that adds a persona cannot leave its rows un-named for the sweep.
SWEEP_TOKEN_REF_KINDS: tuple[tuple[str, str], ...] = (("profile", "profile."), ("campaign", "campaign."))


def stage_three_lane_tokens(
    fixture: Mapping[str, Any], ids: Mapping[str, str], keys: Sequence[str] = ()
) -> tuple[str, ...]:
    """The ``kind=value`` tokens one finished Stage 3 lane can honestly name.

    ``scripts/qa_fixture.py sweep`` deletes without a prompt and refuses a token whose value does not
    match the stored shape of its kind, so the lane hands over the ids it was answered — the ``DATA_ID``
    the Unit name and every Scout profile carry, the Unit and Unit Campaign ids, each Scout profile and
    Campaign id, and every idempotency key it sent as ``idem``.  A ref with no bound id is a ``ValueError``
    naming it: a placeholder token is free text with a kind glued on, which is what the sweeper exists to
    refuse.
    """
    tokens: list[str] = []
    for kind, ref in SWEEP_TOKEN_ID_FIELDS:
        tokens.append(f"{kind}={_require_sweep_value(ids.get(ref, ''), ref)}")
    for kind, prefix in SWEEP_TOKEN_REF_KINDS:
        tokens += [
            f"{kind}={_require_sweep_value(ids.get(entry['ref'], ''), entry['ref'])}"
            for entry in _refs_with_prefix(fixture, prefix)
        ]
    tokens += [f"idem={key}" for key in keys]
    return tuple(dict.fromkeys(tokens))


def _require_sweep_value(value: str, ref: str) -> str:
    """A bound value for one sweep token, or the error that says the lane cannot name it yet."""
    if not value or UNBOUND_KEY_MARKER in value:
        raise ValueError(
            f"the sweep token for {ref!r} has no bound value; the lane cannot name a row it never identified"
        )
    return value


def _refs_with_prefix(fixture: Mapping[str, Any], prefix: str) -> list[Mapping[str, Any]]:
    """The tree's entries whose ref starts with one kind prefix, in a stable order."""
    entries: list[Mapping[str, Any]] = []
    for section in ("profiles", "campaigns"):
        entries += [entry for entry in fixture[section].values() if str(entry["ref"]).startswith(prefix)]
    return entries


def assert_stage_three_cleanup_clean(rows: Iterable[Mapping[str, str]], *, strict: bool | None = None) -> None:
    """The Stage 2 gate with the Stage 3 error type: a failed row fails the
    run, a blocked row is named, and ``strict`` falls back to
    :data:`STRICT_CLEANUP` when the lane did not choose."""
    try:
        stage_two.assert_cleanup_clean(rows, strict=strict)
    except StageTwoCleanupError as error:
        raise StageThreeCleanupError(str(error)) from error


def stage_three_ttl_expectation(now_epoch: int) -> dict[str, object]:
    """What a Stage 3 marker row must carry: the TTL attribute set to seven
    days after minting.  Business rows carry no expiry at all."""
    return {"attribute": MARKER_TTL_ATTRIBUTE, "expiresAtEpoch": now_epoch + MARKER_TTL_SECONDS}


def ttl_gate_violations(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Check a set of rows against the TTL gate.

    ``rows``: ``{"class": ..., "expiresAtEpoch": ... | None}``.  A business row
    (a class in :data:`NEVER_EXPIRING_ROW_CLASSES`) that carries an expiry is a
    violation — the table's TTL block is for markers only.  A marker row that
    lacks the TTL attribute is a violation too: it will never sweep.
    """
    problems: list[str] = []
    for row in rows:
        row_class = str(row.get("class", ""))
        expiry = row.get(MARKER_TTL_ATTRIBUTE)
        if row_class in NEVER_EXPIRING_ROW_CLASSES and expiry is not None:
            problems.append(f"{row_class}: business rows never carry {MARKER_TTL_ATTRIBUTE}")
        if row_class == "marker" and expiry is None:
            problems.append(f"{row_class}: no {MARKER_TTL_ATTRIBUTE}, the row will never sweep")
    return problems


# ------------------------------------------------------------------
# 10b. The write ledger: what this lane actually wrote
# ------------------------------------------------------------------
#
# A cleanup plan built by reading the fixture tree is a prediction: it says what a lane of this shape
# *should* have sent.  The lanes also send writes the tree never names — the slot write that advances a
# version so a stale fixture can be built, the winner of each race barrier — and a marker row for a write
# that never happened is a delete that reads back a comfortable absence.  So every accepted mutation is
# recorded at the shared transport path, with the identity that signed it, the scope the payload addressed
# and the key the caller sent, and cleanup derives its marker addresses from that record.


#: Which input field scopes one mutation's marker.  These are the ``scope=`` arguments the handlers pass to
#: ``marker_keys`` in ``src/handlers/unit_operations.py``: an event write scopes to the event it writes, a
#: create has no event id yet and scopes to the Unit Campaign, and a membership removal scopes to the
#: Unit Campaign whose roster changed.
MARKER_SCOPE_ARGUMENT: dict[str, str] = {
    "createShowAndSell": "unitCampaignId",
    "updateShowAndSell": "showAndSellId",
    "cancelShowAndSell": "showAndSellId",
    "assignShowAndSellInventory": "showAndSellId",
    "upsertShowAndSellSlot": "showAndSellId",
    "deleteShowAndSellSlot": "showAndSellId",
    "signupScoutForShowAndSellSlot": "showAndSellId",
    "cancelShowAndSellSignup": "showAndSellId",
    "confirmShowAndSellWork": "showAndSellId",
    "removeUnitCampaignMembership": "unitCampaignId",
}

#: Which logical table one mutation's marker rides: ``_show_and_sell_marker`` writes the event aggregate
#: table, ``_campaign_marker`` the campaign aggregate table (§8.9).
MARKER_TABLE_KEY: dict[str, str] = {
    **dict.fromkeys(STAGE_THREE_WRITES, "show_and_sells"),
    "removeUnitCampaignMembership": "unit_campaigns",
}

#: The physical name of each marker table, resolved the way the app resolves them: the Lambda environment
#: first, the dev stack's name as the lane's own answer.
DEV_UNIT_CAMPAIGNS_TABLE = "kernelworx-unit-campaigns-ue1-dev"


def unit_campaigns_table() -> str:
    """The physical ``unit_campaigns`` table this lane's campaign markers live in."""
    return os.environ.get("UNIT_CAMPAIGNS_TABLE_NAME") or DEV_UNIT_CAMPAIGNS_TABLE


MARKER_TABLE_NAMES: dict[str, Callable[[], str]] = {
    "show_and_sells": show_and_sells_table,
    "unit_campaigns": unit_campaigns_table,
}

#: The two swept tables a Stage 3 fixture identity cannot read, and the product reads that enumerate this
#: lane's rows in each.  Amendment B (checklist §2.8.7) accepts such a table only as residue that is
#: *named and provable*, and the naming is done by **reading** — this map says only which read to run, and
#: carries no verdict of its own.  A blocked table that is not here cannot be proven either way and stays
#: non-clean, exactly as the Stage 2 lane's ``_RESIDUE_READS`` does for its three.
STAGE_THREE_RESIDUE_READS: dict[str, tuple[str, ...]] = {
    "inventory": ("inventoryPositions", "scoutCustodyBalances"),
    "inventory-movements": ("inventoryMovements",),
}

#: One census entry as the lane states it: the document, and how many rows it answered for this lane.
#: Anything else in a census is not evidence, so :func:`is_census_statement` refuses it.
CENSUS_STATEMENT = re.compile(r"^(?P<document>[A-Za-z][A-Za-z0-9]*) answered (?P<rows>\d+) row\(s\)")


def is_census_statement(statement: str) -> bool:
    """Whether one census value came from a read that ran, rather than from prose about a read.

    The shape is emitted by :func:`stage_three_residue_census` alone, so a caller cannot pre-load a census
    with a sentence and have a blocked table read as proven residue.
    """
    return bool(CENSUS_STATEMENT.match(str(statement or "")))


def _swept_table_key(table: str) -> str:
    """Which entry of :data:`STAGE_THREE_RESIDUE_READS` one ``BLOCKED <table>`` line names, or ``""``.

    The sweeper prints the physical name with its environment suffix, so the match is on the logical key,
    longest first so ``inventory-movements`` never falls into ``inventory``.  An unrecognized name is not
    guessed at: it becomes residue the record cannot prove.
    """
    name = str(table).lower()
    for key in sorted(STAGE_THREE_RESIDUE_READS, key=len, reverse=True):
        if key in name:
            return key
    return ""


def stage_three_residue_probe(
    transport: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
    unit_campaign_ids: Sequence[str],
    *,
    documents: Mapping[str, str] | None = None,
    reads: Mapping[str, tuple[str, ...]] | None = None,
    error_summaries: Callable[[Mapping[str, Any]], Sequence[str]] | None = None,
) -> Callable[[str], str]:
    """A read that answers one lane's rows in each table the sweep could not scan.

    Scoped to the ids this lane was answered, never a whole-table read: what matters is what *this* lane
    left behind, and a read spanning the stack would report another tenant's rows as this lane's residue.
    A read that is refused, errors, or cannot run answers **nothing** rather than inventing an answer —
    leaving that table unproven instead of proven absent.  ``NOT_FOUND`` on a Campaign-keyed query means
    the Campaign row is gone, which says nothing about the rows sharing its partition key, so it too
    answers nothing here.
    """
    units = [str(item) for item in unit_campaign_ids if item]
    documents = dict(stage_two.STAGE_TWO_DOCUMENTS if documents is None else documents)
    reads = dict(STAGE_THREE_RESIDUE_READS if reads is None else reads)
    summarize = error_summaries or show_sell_graphql.error_summaries

    def read_rows(document: str, variables: Mapping[str, Any]) -> str:
        try:
            body = transport(document, variables)
        except Exception:  # noqa: BLE001 - a probe that cannot run proves nothing, and must not invent it
            return ""
        if summarize(body):
            return ""
        data = (dict(body.get("data") or {})).get(document)
        items = data.get("items") if isinstance(data, Mapping) else data
        rows = [row for row in (items or []) if isinstance(row, Mapping)]
        return f"{document} answered {len(rows)} row(s)"

    def probe(table: str) -> str:
        key = _swept_table_key(table)
        if not key:
            return ""
        answers: list[str] = []
        for document in reads[key]:
            for unit in units:
                statement = read_rows(document, {"unitCampaignId": unit})
                if statement:
                    answers.append(f"{statement} for {unit}")
        return "; ".join(answers)

    return probe


def stage_three_residue_census(
    transport: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
    unit_campaign_ids: Sequence[str],
    *,
    documents: Mapping[str, str] | None = None,
    reads: Mapping[str, tuple[str, ...]] | None = None,
    error_summaries: Callable[[Mapping[str, Any]], Sequence[str]] | None = None,
) -> dict[str, str]:
    """What this lane leaves in each unreadable swept table, **read** while a read still answers it.

    The window is before the teardown, not after the sweep: the sweep deletes the Unit and Unit Campaign
    rows these reads are keyed on, and afterwards ``inventoryPositions`` answers ``NOT_FOUND`` for the
    Campaign, which proves the Campaign is gone and says nothing at all about the append-only movement rows
    under its partition key.  Each answer is keyed by the swept table's physical name so the sweep step can
    look up exactly what its own ``BLOCKED`` line named.  A probe that failed contributes an empty answer,
    and an empty answer leaves that table unproven.
    """
    probe = stage_three_residue_probe(
        transport,
        unit_campaign_ids,
        documents=documents,
        reads=reads,
        error_summaries=error_summaries,
    )
    census: dict[str, str] = {}
    for key, tables in STAGE_THREE_RESIDUE_TABLES.items():
        for table in tables:
            census[table] = probe(key)
    return census


#: The physical tables the Stage 3 lane expects the sweeper to report as ``BLOCKED`` for this identity,
#: per logical key.  The census is keyed by these names because the sweep line names them.
STAGE_THREE_RESIDUE_TABLES: dict[str, tuple[str, ...]] = {
    "inventory": ("kernelworx-inventory-ue1-dev",),
    "inventory-movements": ("kernelworx-inventory-movements-ue1-dev",),
}


def plan_row_address(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """The ``(table, pk, sk)`` one cleanup plan row names, in the same shape the ledger derives.

    Both sides of the runner's authorization check are read this way, so the comparison is apples to
    apples: the plan's address comes from the row it wrote, the recorded address comes from
    :func:`derived_marker_address`, and neither is assembled by hand.
    """
    key = dict(row.get("key") or {})
    return (str(row.get("table") or ""), str(key.get("pk", "")), str(key.get("sk", "")))


def derived_marker_address(row: Mapping[str, Any], *, ids: Mapping[str, str]) -> tuple[str, str, str]:
    """The address production wrote for one marker row, recomputed from the row's own actor and scope.

    Both the planned row (from :func:`stage_three_write_steps`) and the recorded row (from
    :class:`WriteLedger`) carry ``operation``, ``actorField`` and ``scopeField``, so this is the one place
    that turns either into the ``(table, pk, sk)`` :func:`src.utils.mutations.marker_keys` produces.  The
    cleanup runner compares planned and recorded through it, which is why an ``idempotencyKey`` match alone
    cannot authorize a delete of an address the lane never wrote.

    Raises:
        ValueError: the row names no operation, or its actor or scope ref is unbound — in either case the
            lane cannot name the marker, and an address must not be guessed at.
    """
    operation = str(row.get("operation") or "")
    if operation not in MARKER_TABLE_KEY:
        raise ValueError(f"{operation or '<no operation>'}: not a Stage 3 idempotent write, so no marker address")
    table_key = MARKER_TABLE_KEY[operation]
    actor_ref = str(row.get("actorField") or "")
    scope = str(row.get("scopeField") or "")
    actor = str(ids.get(actor_ref, ""))
    if not actor:
        raise ValueError(f"marker {row.get('idempotencyKey')}: actor ref {actor_ref or '<none>'!r} is unbound")
    if not scope:
        raise ValueError(f"marker {row.get('idempotencyKey')}: no scope to address the marker with")
    if UNBOUND_KEY_MARKER in scope:
        raise ValueError(f"marker {row.get('idempotencyKey')}: scope {scope!r} is a placeholder, not an id")
    key = str(row.get("idempotencyKey") or "")
    if not key:
        raise ValueError(f"{operation}: no idempotencyKey to address the marker with")
    marker = mutations.marker_keys(
        table_key=table_key,
        table_name=MARKER_TABLE_NAMES[table_key](),
        actor_id=actor,
        operation=operation,
        scope=scope,
        idempotency_key=key,
    )
    return (marker.table_name, marker.pk, marker.sk)


class WriteLedger:
    """Every mutation this lane sent **and the server accepted**, with what addresses its marker.

    Records are added at the shared transport path by
    :func:`tests.e2e.utils.show_sell_stage3_scenario.recording_transport`, after the answer arrives, so a
    refused write — every §3.6.2 collision, the removed-member signup — is absent: a rejected mutation
    writes no marker, and a cleanup row for it deletes nothing and proves nothing.

    Each record carries the actor ref the lane authenticated as, the scope value the payload itself
    addressed, and the idempotency key the caller sent.  Those three, plus the operation, are exactly what
    :func:`src.utils.mutations.marker_keys` needs, so the address cleanup names is the address production wrote.
    """

    def __init__(self, lane: str) -> None:
        self.lane = lane
        self.records: list[dict[str, str]] = []

    def record(self, *, field: str, actor: str, variables: Mapping[str, Any]) -> None:
        """Note one accepted mutation: its operation, the identity that signed it, and its payload."""
        if field not in MARKER_SCOPE_ARGUMENT:
            raise ValueError(f"{field}: not a Stage 3 idempotent write, so it has no marker to clean")
        if not actor:
            raise ValueError(f"{field}: the lane recorded a write with no identity behind it")
        payload = dict(variables.get("input") or {})
        scope_argument = MARKER_SCOPE_ARGUMENT[field]
        scope = str(payload.get(scope_argument) or "")
        if not scope:
            raise ValueError(f"{field}: the payload sent no {scope_argument}, so its marker has no scope")
        key = _idempotency_key_of(payload)
        if not key:
            raise ValueError(f"{field}: the lane sent an idempotent write with no idempotencyKey")
        mutations.marker_sort_key(key)
        self.records.append(
            {
                "operation": field,
                "actor": actor,
                "scope": scope,
                "idempotencyKey": key,
                "tableKey": MARKER_TABLE_KEY[field],
            }
        )

    def keys(self) -> tuple[str, ...]:
        """Every idempotency key this lane sent, in send order, for the ``idem`` sweep tokens."""
        return tuple(record["idempotencyKey"] for record in self.records)

    def marker_rows(self, ids: Mapping[str, str]) -> list[dict[str, Any]]:
        """One cleanup row per recorded write, addressed by :func:`src.utils.mutations.marker_keys`.

        ``ids`` resolves the actor ref to the account id the lane signed in as; a ref the lane never bound
        keeps its placeholder so the runner refuses the delete rather than addressing a marker it cannot name.
        """
        rows: list[dict[str, Any]] = []
        for record in self.records:
            actor_ref = record["actor"]
            actor = str(ids.get(actor_ref, "")) or f"<{actor_ref}>"
            rows.append(
                _marker_row_from_record(
                    record,
                    lane=self.lane,
                    actor=actor,
                    table=MARKER_TABLE_NAMES[record["tableKey"]](),
                )
            )
        return rows


def _idempotency_key_of(payload: Mapping[str, Any]) -> str:
    """The key one mutation input carries, in either shape the documents send it in.

    The input objects carry it as a nested ``idempotency`` block (the GraphQL ``IdempotencyInput``); a flat
    ``idempotencyKey`` is what the API accepts at the input level.  Both are read so the ledger describes the
    write the lane really sent rather than the shape this module happens to build.
    """
    nested = payload.get("idempotency")
    if isinstance(nested, Mapping):
        return str(nested.get("idempotencyKey") or "")
    return str(payload.get("idempotencyKey") or "")


def _marker_row_from_record(record: Mapping[str, str], *, lane: str, actor: str, table: str) -> dict[str, Any]:
    """One recorded write, in the cleanup vocabulary, with its production-derived marker address."""
    operation, key, scope = record["operation"], record["idempotencyKey"], record["scope"]
    if UNBOUND_KEY_MARKER in actor:
        address = {"pk": f"IDEM#{actor}#{operation}#{scope}", "sk": f"IDEM#{key}"}
    else:
        marker = mutations.marker_keys(
            table_key=record["tableKey"],
            table_name=table,
            actor_id=actor,
            operation=operation,
            scope=scope,
            idempotency_key=key,
        )
        address = {"pk": marker.pk, "sk": marker.sk}
    return {
        "acceptance": "API-FIX-03",
        "summary": (
            f"delete the {operation} marker this lane wrote with key {key}; the table's TTL would sweep it "
            f"after {MARKER_TTL_SECONDS // 3600} hours, and a lane that waits for the TTL has not cleaned"
        ),
        "lane": lane,
        "kind": "marker",
        "table": table,
        "key": address,
        "idempotencyKey": key,
        "operation": operation,
        "actorField": record["actor"],
        "scopeField": scope,
        "recorded": True,
    }


# ------------------------------------------------------------------
# 11. The SDL contract
# ------------------------------------------------------------------
#
# The reader is the Stage 2 module's, because a second parser is a second
# thing that can drift: :func:`stage_two._block_body`, ``_field_exists``,
# ``_field_arguments``, ``_input_member_names``, ``_type_member_map``,
# ``_selection_tree`` and ``_check_selections`` are called, not copied.


def stage_three_selection_violations(sdl: str) -> list[str]:
    """Every field the Stage 3 documents select that this SDL does not declare.

    The argument-level check is not enough on its own: a document that selects
    ``positions`` where the SDL says ``items``, or asks ``showAndSell`` for a
    ``location`` its answer does not carry, is a document that fails at
    AppSync parse time — partway through a live lane, after the writes it
    precedes.
    """
    types = stage_two._type_member_map(sdl)
    violations: list[str] = []
    for document in STAGE_THREE_DOCUMENTS.values():
        root = "Mutation" if document.startswith("mutation") else "Query"
        stage_two._check_selections(stage_two._selection_tree(document), root, types, "", violations)
    return violations


def stage_three_contract_violations(sdl: str) -> list[str]:
    """Every way the shipped SDL and the Stage 3 suite's documents and payloads disagree.

    An empty list means the suite can be sent to this API: each Stage 3 field
    exists, every argument its document passes is declared, and every key an
    input builder puts in a payload is a member of the SDL input type that
    field takes.
    """
    violations: list[str] = []
    for field, document in STAGE_THREE_DOCUMENTS.items():
        if not (stage_two._field_exists(sdl, "Query", field) or stage_two._field_exists(sdl, "Mutation", field)):
            violations.append(f"{field}: the SDL declares no such field")
            continue
        declared = stage_two._field_arguments(sdl, "Query", field) | stage_two._field_arguments(sdl, "Mutation", field)
        extra = sorted(stage_two._document_arguments(document, field) - declared)
        if extra:
            violations.append(f"{field}: the document sends {extra}, the SDL declares {sorted(declared)}")
    for field, (_builder, type_name) in _BUILDERS.items():
        members = stage_two._input_member_names(sdl, type_name)
        if not members:
            violations.append(f"{field}: the SDL declares no input type {type_name}")
            continue
        sample = _SAMPLES[type_name]
        unknown = sorted(key for key in sample if key not in members)
        if unknown:
            violations.append(f"{field}: the payload sends {unknown}, {type_name} declares {sorted(members)}")
    return violations


def missing_stage_three_endpoints(sdl: str) -> list[str]:
    """Stage 3 fields this SDL does not carry at all.

    A non-empty list is what lets a Stage 3 run say *stopped* rather than
    *passed*: the suite reports the endpoints the deployed build is missing
    and §3.6.2 stays open, with :data:`MISSING_ENDPOINT_NOTE`.
    """
    return [
        field
        for field in (*STAGE_THREE_WRITES, *STAGE_THREE_READS)
        if not (stage_two._field_exists(sdl, "Mutation", field) or stage_two._field_exists(sdl, "Query", field))
    ]


def stage_three_fields_in_schema(schema: Mapping[str, Any]) -> list[str]:
    """Which Stage 3 fields the deployed API's own introspection answers.

    Args:
        schema: the ``data`` object of ``query { __schema { queryType { fields { name } }
            mutationType { fields { name } } } }``.

    Returns:
        The Stage 3 names this API carries, in the order this module lists
        them.  A short list is what stops a live lane: the suite reports the
        endpoints the deployed build is missing instead of failing a step on
        an unknown field.
    """
    root = schema.get("__schema") or {}
    declared: set[str] = set()
    for root_type in ("queryType", "mutationType"):
        for field in (root.get(root_type) or {}).get("fields") or []:
            declared.add(str(field.get("name", "")))
    return [field for field in (*STAGE_THREE_WRITES, *STAGE_THREE_READS) if field in declared]
