"""Stage 3 (Show & Sell events, allocations, slots, signups, calendar data) support for the deployed-stack acceptance suite.

Checklist §3.6.2 is the work order, verbatim: "Add deterministic event/slot/allocation/conflict fixtures
for ``T0``-relative past/future/ACTIVE/ENDED/REOPENED/FINALIZED/CANCELLED states, four-box events,
16-product catalog, 90/120/180-minute slots, removed members, stale versions, and race barriers.  Add
``API-FIX-01/03``, ``SS-SM-05/06/11``, and lane cleanup tests."  In the leaf shape the card names, it is:
private lane, deterministic fixtures, events/slots/products/allocation, conflict pairs, calendar DTO plus
ICS validator, refusal assertions, inventory ledger, TTL-gated cleanup.  This module is that list as
code, so a Stage 3 lane writes its fixtures from one place and the parts that do not need a deployed
stack are executable by ``tests/unit``.

It lives next to :mod:`tests.e2e.utils.show_sell_graphql`, and for the same reason the evidence helpers
do — outside the spec, so ``tests/unit`` can execute it.  Importing a Stage 3 spec itself from the unit
suite would fail on its ``slow`` marker under the root pytest configuration.

Four rules the whole module follows:

* **A document names the arguments the SDL declares.**  :func:`stage_three_contract_violations` compares
  every document and input builder here against ``tofu/application/schema/schema.graphql``, so a resolver
  rename stops a lane with a named mismatch instead of an AppSync parse error partway through it.  The SDL
  reader is the Stage 2 module's (:mod:`tests.e2e.utils.show_sell_stage2_support`), because a second
  parser is a second thing that can drift.
* **A fixture reproduces itself, and every write it plans is legal at the moment it is planned.**
  Determinism lives in the lane token, the entity names, the tenant key, the idempotency keys, and the
  interval arithmetic — a re-run of the same seed rebuilds the same bytes and recognises the same Unit
  through the same tenant key.  Entity ids are the *server's*: ``createUnit`` and ``createShowAndSell``
  mint UUIDs the caller never names, so the fixture carries ``<ref>`` placeholders and the lane binds the
  ids the answers came back with (:func:`bind_ids`).  States a write cannot produce without bypassing
  the rule under test (``FINALIZED``, ``REOPENED`` — §5's mutations, absent from this SDL) are reported
  blocked by :data:`STAGE_THREE_BLOCKED_STATE_FIXTURES`, never faked.
* **A quantity is checked against the rows it is derived from, never against a stored copy.**  §7
  defines the derived quantities as formulas over balance, allocation and custody rows, computed per
  request by :func:`src.utils.inventory_models.derived_inventory_quantities`; the Stage 2 formula checks
  are reused here verbatim.  A Stage 3 write is allowed to move only the ``assignedDelta`` column of one
  ``EVENT_ASSIGN``/``EVENT_MANUAL_REDUCE``/``EVENT_RELEASE`` movement row — physical stock, sold-in-
  possession, custody and Council-on-order stay untouched by construction (§3.2.3, EVT-M-04's "physical
  stock never changes" claim, measured at the write layer).
* **The ICS validator validates what the *browser* produces.**  No server generates, stores, or serves a
  calendar file (CAL-01, CAL-02, RPT-00): the browser assembles the invite itself from the authorized
  ``showAndSellSignupCalendarData`` read (``frontend/src/lib/showSell.ts``'s ``buildInvite``) and
  downloads it locally.  :func:`validate_ics` is written from RFC 5545 and ``buildInvite``, not from any
  server artifact, and the lane feeds it the bytes the browser actually downloaded.

Cleanup reuses the Stage 2 vocabulary (:data:`STRICT_CLEANUP`, ``CLEANUP_OBSERVED/BLOCKED/FAILED``,
:func:`run_cleanup_step`, :func:`assert_cleanup_clean`, :func:`fixture_sweep`, :func:`sweep_verdict`,
:class:`CleanupBlocked`, :class:`StageTwoCleanupError`) rather than carrying a second copy of it; the
Stage 3 additions are the ordered plan, the typed sweep tokens, and the TTL gate.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.utils import show_and_sell_models
from tests.e2e.utils import show_sell_graphql
from tests.e2e.utils import show_sell_stage2_support as stage_two

__all__ = [
    "BLOCKED_STATE_FIXTURE_NOTE",
    "CALENDAR_DTO_FIELDS",
    "DST_SPRING_FORWARD",
    "ICS_CHECKS",
    "STAGE_THREE_REFUSAL_ANSWERS",
    "MARKER_TTL_ATTRIBUTE",
    "MARKER_TTL_SECONDS",
    "MAX_SLOT_CAPACITY",
    "MAX_SLOTS_PER_EVENT",
    "MAX_WORK_LINES",
    "MIN_SLOT_CAPACITY",
    "MISSING_ENDPOINT_NOTE",
    "NEVER_EXPIRING_ROW_CLASSES",
    "STAGE_THREE_BLOCKED_STATE_FIXTURES",
    "STAGE_THREE_CLEANUP_READS",
    "STAGE_THREE_DOCUMENTS",
    "STAGE_THREE_LANE_TOKEN_KINDS",
    "STAGE_THREE_MOVEMENT_TYPES",
    "STAGE_THREE_READS",
    "STAGE_THREE_REFUSALS",
    "STAGE_THREE_STOCK_COLUMNS",
    "STAGE_THREE_SUPPORT_DOCUMENTS",
    "STAGE_THREE_WRITES",
    "UNIT_TIMEZONE",
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
    "lane_token",
    "missing_stage_three_endpoints",
    "refusal_violations",
    "run_cleanup_step",
    "stage_three_cleanup_plan",
    "stage_three_contract_violations",
    "stage_three_fields_in_schema",
    "stage_three_fixture",
    "stage_three_ledger_invariants",
    "stage_three_refusal",
    "stage_three_selection_violations",
    "stage_three_sweep_tokens",
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

#: The spring-forward boundary the calendar assertions pin: 2026-03-08, when Denver moves from
#: UTC-7 to UTC-6, so 2026-03-07 09:00 local is 16:00 UTC and 2026-03-09 09:00 local is 15:00 UTC
#: (the frontend suite's own DST pair).
DST_SPRING_FORWARD = date(2026, 3, 8)

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
}

#: The acceptance ids each refusal belongs to, keyed the same way.  Kept beside the sentences so a
#: reader of a live lane's ``refusal.json`` sees the id without chasing the table.
STAGE_THREE_REFUSALS: Mapping[str, tuple[str, ...]] = {
    "duplicate-signup": ("SIGN-M-01-02", "SLOT-02", "SS-SM-06 step 3"),
    "capacity-full": ("SIGN-M-01-02", "SLOT-02-02", "SS-SM-06 step 3"),
    "cross-campaign-overlap": ("SIGN-M-01-02", "SLOT-04", "SS-SM-06 step 5"),
    "stale-event-version": ("VER-01", "EVT-M-02-03", "EVT-M-03-03", "SLOT-M-01-03", "SIGN-M-03-03"),
    "slot-limit": ("SLOT-M-01-02", "§3.3.2's 20-slot cap"),
    "capacity-range": ("SLOT-M-01-01/02", "§3.3.2's 1-100 capacity"),
    "work-over-duration": ("SIGN-M-03-02", "SS-SM-06 step 9's 190 minutes in a 210-minute day"),
    "work-batch-cap": ("SIGN-M-03-03", "§3.4.3's 1-100 rows"),
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
}

# ------------------------------------------------------------------
# 3. Deterministic fixture
# ------------------------------------------------------------------
#
# Every id the server will mint is a ``<ref>`` placeholder (``<unit>``,
# ``<campaign.avery>``, ``<event.slots>``, ``<slot.first-sales>``,
# ``<profile.hana>``, ``<product.caramel>``).  The live lane binds the ids the
# answers came back with through :func:`bind_ids` before the first write.
# Every derived value is computed from T0 and the lane token, so one seed
# rebuilds the same bytes.

T0_UTC = "2026-11-15T00:00:00Z"
T0_EPOCH = int(datetime.fromisoformat("2026-11-15T00:00:00+00:00").timestamp())

# The DST fixture pair the checklist pins: 09:00 MDT on both sides of
# 2026-03-08 — 16:00 UTC the Saturday before (MST, UTC-7) and 15:00 UTC the
# Monday after (MDT, UTC-6).
DST_SATURDAY_START_UTC = "2026-03-07T16:00:00Z"
DST_SATURDAY_END_UTC = "2026-03-07T16:30:00Z"
DST_MONDAY_START_UTC = "2026-03-09T15:00:00Z"
DST_MONDAY_END_UTC = "2026-03-09T16:30:00Z"

UNIT_NAME = "Avery Unit"
CAMPAIGN_NAME = "Avery"


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def lane_token(seed: int) -> str:
    """Twelve hex characters; every fixture key, marker and idempotency token
    derives from it, so one seed pins the whole tree."""
    return _sha256_hex(f"stage3:{seed:04d}").rstrip()[:12]


def event_time(offset_days: int, hour: int = 0, minute: int = 0) -> str:
    ts = datetime(2026, 11, 15, tzinfo=timezone.utc) + timedelta(days=offset_days, hours=hour, minutes=minute)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fixture_event(start: str, end: str, location: str) -> dict:
    return {"ref": "event", "locationName": location, "startAt": start, "endAt": end}


def _fixture_slot(start: str, end: str, label: str, capacity: int) -> dict:
    return {"ref": "slot", "label": label, "startAt": start, "endAt": end, "capacity": capacity}


#: The rows every derived status must contain at least, as ``(ref, kind, value)``.
FIXTURE_TREE: tuple[tuple[str, str, object], ...] = (
    ("unit", "name", UNIT_NAME),
    ("campaign.avery", "name", CAMPAIGN_NAME),
    ("event.slots", "locationName", "Slot Showcase"),
    ("event.slots", "start", "2026-11-22T09:00:00Z"),
    ("event.slots", "end", "2026-11-22T12:30:00Z"),
    ("event.active", "start", "2026-11-14T23:00:00Z"),
    ("event.ended", "start", "2026-11-13T09:00:00Z"),
    ("event.ended", "end", "2026-11-14T12:00:00Z"),
    ("event.cancellation", "start", "2026-11-25T16:00:00Z"),
    ("event.cancellation", "end", "2026-11-25T18:00:00Z"),
    ("event.four-boxes", "start", "2026-11-23T09:00:00Z"),
    ("event.four-boxes", "end", "2026-11-23T18:00:00Z"),
    ("event.big", "start", "2026-11-24T09:00:00Z"),
    ("event.big", "end", "2026-11-24T10:00:00Z"),
    ("event.dst", "start", DST_SATURDAY_START_UTC),
    ("event.dst", "end", DST_MONDAY_END_UTC),
    ("slot.first-sales", "label", "First Sales"),
    ("slot.first-sales", "minutes", 90),
    ("slot.first-sales", "capacity", 1),
    ("slot.midday", "label", "Midday"),
    ("slot.midday", "minutes", 120),
    ("slot.midday", "capacity", 1),
    ("slot.full-booth", "label", "Full Booth"),
    ("slot.full-booth", "minutes", 180),
    ("slot.full-booth", "capacity", 100),
    ("slot.morning", "minutes", 180),
    ("slot.afternoon", "minutes", 180),
    ("slot.overlap", "minutes", 60),
    ("profile.hana", "name", "Hana Ito"),
    ("profile.river", "name", "River Okafor"),
    ("profile.sam", "name", "Sam Whitaker"),
    ("product.caramel", "name", "Caramel Corn"),
    ("product.glass", "name", "Glass Jar Set"),
    ("product.tote", "name", "Canvas Tote"),
)


def stage_three_fixture(seed: int = 0) -> dict:
    """The Stage 3 acceptance tree.

    One event in each derived state at T0 (``ended`` = ENDED, ``active`` =
    ACTIVE, ``cancellation`` = SCHEDULED until the lane cancels it, the rest
    SCHEDULED), the DST straddle, the 20-slot boundary event and the 101-row
    confirm event.  Pure in ``(seed,)`` — identical output, byte for byte, on
    every run.
    """
    lane = lane_token(seed)
    events: dict[str, dict] = {
        "slots": dict(_fixture_event(event_time(7, 9), event_time(7, 12, 30), "Slot Showcase"), ref="event.slots"),
        "active": dict(_fixture_event(event_time(0, -1), event_time(0, 1), "Live Booth"), ref="event.active"),
        "ended": dict(_fixture_event(event_time(-2, 9), event_time(-1, 12), "Yesterday's Sale"), ref="event.ended"),
        "cancellation": dict(
            _fixture_event(event_time(10, 16), event_time(10, 18), "Cancellation Drill"), ref="event.cancellation"
        ),
        "four-boxes": dict(_fixture_event(event_time(8, 9), event_time(8, 18), "Four Boxes"), ref="event.four-boxes"),
        "big": dict(_fixture_event(event_time(9, 9), event_time(9, 10), "Twenty Slots"), ref="event.big"),
        "dst": dict(_fixture_event(DST_SATURDAY_START_UTC, DST_MONDAY_END_UTC, "DST Straddle"), ref="event.dst"),
        "confirm": dict(_fixture_event(event_time(8, 18), event_time(8, 19, 30), "Confirm Rows"), ref="event.confirm"),
    }
    slots: dict[str, dict] = {
        "first-sales": dict(
            _fixture_slot(event_time(7, 9), event_time(7, 10, 30), "First Sales", 1), ref="slot.first-sales"
        ),
        "midday": dict(_fixture_slot(event_time(7, 10, 30), event_time(7, 12, 30), "Midday", 1), ref="slot.midday"),
        "full-booth": dict(
            _fixture_slot(event_time(7, 9), event_time(7, 12), "Full Booth", 100), ref="slot.full-booth"
        ),
        "morning": dict(_fixture_slot(event_time(8, 9), event_time(8, 12), "Morning", 4), ref="slot.morning"),
        "afternoon": dict(_fixture_slot(event_time(8, 15), event_time(8, 18), "Afternoon", 4), ref="slot.afternoon"),
        "overlap": dict(
            _fixture_slot(event_time(8, 11, 30), event_time(8, 12, 30), "Overlap Hour", 2), ref="slot.overlap"
        ),
        "dst-saturday": dict(
            _fixture_slot(DST_SATURDAY_START_UTC, DST_SATURDAY_END_UTC, "DST Saturday", 1), ref="slot.dst-saturday"
        ),
        "dst-monday": dict(
            _fixture_slot(DST_MONDAY_START_UTC, DST_MONDAY_END_UTC, "DST Monday", 1), ref="slot.dst-monday"
        ),
    }
    big_slots = [
        dict(_fixture_slot(event_time(9, 9), event_time(9, 10), f"Slot {i + 1}", 1), ref=f"slot.big-{i:02d}")
        for i in range(20)
    ]
    profiles: dict[str, dict] = {
        "hana": {"ref": "profile.hana", "name": "Hana Ito", "role": "Lead"},
        "river": {"ref": "profile.river", "name": "River Okafor", "role": "Steward"},
        "sam": {"ref": "profile.sam", "name": "Sam Whitaker", "role": "Helper"},
    }
    products: dict[str, dict] = {
        "caramel": {"ref": "product.caramel", "name": "Caramel Corn", "cents": 350},
        "glass": {"ref": "product.glass", "name": "Glass Jar Set", "cents": 4800},
        "tote": {"ref": "product.tote", "name": "Canvas Tote", "cents": 1400},
    }
    # Allocation targets: which product each event holds, so the ledger math is pinned.
    allocations = {
        "first-sales": [("profile.hana", "product.caramel", 12)],
        "midday": [("profile.river", "product.glass", 1)],
        "full-booth": [("profile.hana", "product.tote", 40), ("profile.sam", "product.caramel", 100)],
    }
    return {
        "seed": seed,
        "lane": lane,
        "t0": T0_UTC,
        "t0Epoch": T0_EPOCH,
        "unit": {"ref": "unit", "name": UNIT_NAME},
        "campaigns": {"avery": {"ref": "campaign.avery", "name": CAMPAIGN_NAME, "year": 2026}},
        "events": events,
        "slots": slots,
        "bigSlots": big_slots,
        "profiles": profiles,
        "products": products,
        "allocations": allocations,
        "confirmRows": MAX_WORK_LINES + 1,
    }


def bind_ids(payload, ids: Mapping[str, str]):
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


# ------------------------------------------------------------------
# 4. Input builders -- one per Stage 3 write, keyed by operation
# ------------------------------------------------------------------
#
# Every builder puts the SDL's ``IdempotencyInput`` and ``VersionedInput`` in
# nested shape, and the lane derives the key itself: one lane token, one
# deterministic key per write.

_SAMPLE_LANE = "0123456789ab"


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
        event_time(7, 9),
        event_time(7, 12, 30),
        address="14 Grange Way",
        we_owe_enabled=True,
        idempotency_key=idempotency_key_for("createShowAndSell", _SAMPLE_LANE),
    ),
    "UpdateShowAndSellInput": update_event_input(
        "SHOW#x",
        1,
        location_name="Riverside Grange",
        we_owe_enabled=False,
        idempotency_key=idempotency_key_for("updateShowAndSell", _SAMPLE_LANE),
    ),
    "CancelShowAndSellInput": cancel_event_input(
        "SHOW#x", 1, "Vendor conflict", idempotency_key=idempotency_key_for("cancelShowAndSell", _SAMPLE_LANE)
    ),
    "AssignShowAndSellInventoryInput": assign_inventory_input(
        "SHOW#x", [("PROD#x", 12)], 1, idempotency_key=idempotency_key_for("assignShowAndSellInventory", _SAMPLE_LANE)
    ),
    "UpsertShowAndSellSlotInput": upsert_slot_input(
        "SHOW#x",
        1,
        event_time(7, 9),
        event_time(7, 10, 30),
        2,
        slot_id="SLOT#x",
        label="First Sales",
        slot_version=1,
        idempotency_key=idempotency_key_for("upsertShowAndSellSlot", _SAMPLE_LANE),
    ),
    "DeleteShowAndSellSlotInput": delete_slot_input(
        "SHOW#x", "SLOT#x", 1, idempotency_key=idempotency_key_for("deleteShowAndSellSlot", _SAMPLE_LANE)
    ),
    "SignupShowAndSellSlotInput": signup_input(
        "SHOW#x",
        "SLOT#x",
        "CAMP#x",
        "PROFILE#x",
        idempotency_key=idempotency_key_for("signupScoutForShowAndSellSlot", _SAMPLE_LANE),
    ),
    "CancelShowAndSellSignupInput": cancel_signup_input(
        "SHOW#x", "SLOT#x", "PROFILE#x", 1, idempotency_key=idempotency_key_for("cancelShowAndSellSignup", _SAMPLE_LANE)
    ),
    "ConfirmShowAndSellWorkInput": confirm_work_input(
        "SHOW#x",
        1,
        [("SLOT#x", "PROFILE#x", 90)],
        idempotency_key=idempotency_key_for("confirmShowAndSellWork", _SAMPLE_LANE),
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


#: The two workflow states a Stage 3 lane cannot reach: ``finalizeShowAndSell``
#: and ``reopenShowAndSell`` are absent from this SDL — they are §5's mutations,
#: Stage 5's barrier.  A lane reports these states *blocked*, never fakes them.
STAGE_THREE_BLOCKED_STATE_FIXTURES: tuple[str, ...] = ("FINALIZED", "REOPENED")

BLOCKED_STATE_FIXTURE_NOTE = (
    "FINALIZED and REOPENED need §5's finalize/reopen mutations, which this SDL does not declare: "
    "the Stage 3 lane reports these states blocked on the Stage 5 merge, it never fakes them"
)


# ------------------------------------------------------------------
# 8. Calendar data and the ICS the browser produces
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
    "CAL-01: the file the lane validates is the one the browser produced and downloaded",
    "CAL-02: one VCALENDAR with CALSCALE:GREGORIAN and METHOD:PUBLISH, one VEVENT, "
    "a stable UID, TZID-bearing times, and lines folded to at most 73 octets",
    "RPT-00: no server artifact — no download URL, no stored file, no notification",
)

ICS_MAX_LINE_OCTETS = 73


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


def denver_wall_clock(iso_utc: str) -> str:
    """The fixture's display zone for one UTC instant: the local time and the
    zone abbreviation — ``09:00 MST`` before the 2026-03-08 straddle,
    ``09:00 MDT`` after it."""
    moment = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(ZoneInfo(UNIT_TIMEZONE))
    return f"{moment:%Y-%m-%d %H:%M} {moment:%Z}"


def unfold_ics(text: str) -> str:
    """Unfold physical lines (continuations start with a space) into one
    logical line each."""
    logical: list[str] = []
    for physical in text.replace("\r\n", "\n").split("\n"):
        if physical.startswith(" ") and logical:
            logical[-1] += physical[1:]
        else:
            logical.append(physical)
    return "\n".join(logical)


def validate_ics(text: str, uid: str) -> tuple[str, ...]:
    """Validate a browser-produced ICS against CAL-01/CAL-02.

    Returns the violated checks — empty when the file is acceptable: one
    VCALENDAR with ``CALSCALE:GREGORIAN`` and ``METHOD:PUBLISH``, one VEVENT,
    the stable UID the browser signed it with, TZID-bearing start and end, and
    every physical line within 73 octets on a CRLF line break.
    """
    problems: list[str] = []
    if not text.endswith("\r\n"):
        problems.append("file: does not end with a CRLF line break")
    body: list[str] = []
    raw_lines = text.split("\n")
    for index, raw in enumerate(raw_lines):
        if raw == "" and index == len(raw_lines) - 1:
            continue
        if raw.endswith("\r"):
            body.append(raw[:-1])
        else:
            problems.append("file: a line ends with a bare LF, not CRLF")
            body.append(raw)
    if not any(line == "BEGIN:VCALENDAR" for line in body):
        problems.append("VCALENDAR: no BEGIN:VCALENDAR")
    if not any(line == "END:VCALENDAR" for line in body):
        problems.append("VCALENDAR: no END:VCALENDAR")
    if "CALSCALE:GREGORIAN" not in text:
        problems.append("VCALENDAR: no CALSCALE:GREGORIAN")
    if "METHOD:PUBLISH" not in text:
        problems.append("VCALENDAR: no METHOD:PUBLISH")
    for line in body:
        if len(line.encode("utf-8")) > ICS_MAX_LINE_OCTETS:
            problems.append(f"line exceeds {ICS_MAX_LINE_OCTETS} octets: {line[:40]}")
        if "\t" in line:
            problems.append(f"tab inside a line: {line[:40]}")
    unfolded = unfold_ics(text)
    uid_lines = [line for line in unfolded.splitlines() if line.startswith("UID:")]
    if len(uid_lines) != 1 or uid_lines[0] != f"UID:{uid}":
        problems.append(f"UID: expected exactly UID:{uid}, found {uid_lines}")
    if not re.search(r"^DTSTART;TZID=[^,;\s]+", unfolded, re.MULTILINE):
        problems.append("DTSTART: no TZID parameter")
    if not re.search(r"^DTEND;TZID=[^,;\s]+", unfolded, re.MULTILINE):
        problems.append("DTEND: no TZID parameter")
    vevents = [line for line in unfolded.splitlines() if line in ("BEGIN:VEVENT", "END:VEVENT")]
    if vevents.count("BEGIN:VEVENT") != 1 or vevents.count("END:VEVENT") != 1:
        problems.append(
            f"VEVENT: expected exactly one event, found {vevents.count('BEGIN:VEVENT')} BEGIN / {vevents.count('END:VEVENT')} END"
        )
    return tuple(problems)


# ------------------------------------------------------------------
# 9. Cleanup — TTL-gated, Stage 2 vocabulary
# ------------------------------------------------------------------
#
# The vocabulary is the Stage 2 module's (:data:`STRICT_CLEANUP`,
# :func:`run_cleanup_step`, :func:`assert_cleanup_clean`, :func:`fixture_sweep`,
# :func:`sweep_verdict`), imported, not re-implemented.  The Stage 3
# additions: the ordered plan, the typed sweep tokens this lane's sweep may
# name, and the TTL gate that keeps a marker sweepable for seven days and
# nothing else.

#: The reads a cleanup run uses to prove the lane's rows are gone.
STAGE_THREE_CLEANUP_READS: tuple[str, ...] = (
    "showAndSells",
    "showAndSellSignups",
    "eventInventoryAllocations",
    "myScoutCommitments",
)


class StageThreeCleanupError(StageTwoCleanupError):
    """A Stage 3 cleanup row that failed, in the Stage 2 vocabulary."""


def stage_three_cleanup_plan(lane: str) -> list[dict[str, str]]:
    """The ordered cleanup plan for one lane: cancel the signups, cancel the
    event, delete the empty slots, let the idempotency markers ride out their
    TTL, then sweep by typed token.  Every business row is cleaned by the
    write that owns it — a row class in :data:`NEVER_EXPIRING_ROW_CLASSES`
    is never left to the TTL, so "wait for the event to expire" is a
    violation, not a step."""
    rows: list[dict[str, str]] = []
    rows.append(
        stage_two.cleanup_row("SS-SM-06 step 6", "cancelShowAndSellSignup for every lane signup", CLEANUP_OBSERVED)
    )
    rows.append(
        stage_two.cleanup_row(
            "SS-SM-11 step 5",
            "cancelShowAndSell for the lane event, releasing allocations and signups",
            CLEANUP_OBSERVED,
        )
    )
    rows.append(
        stage_two.cleanup_row(
            "SLOT-M-02", "deleteShowAndSellSlot for every lane slot once it holds nobody", CLEANUP_OBSERVED
        )
    )
    rows.append(
        stage_two.cleanup_row(
            "API-FIX-03",
            f"no manual delete of the idem marker for lane {lane}: {MARKER_TTL_ATTRIBUTE} lets the table's TTL sweep it after "
            f"{MARKER_TTL_SECONDS // 3600} hours",
            CLEANUP_OBSERVED,
        )
    )
    rows.append(
        stage_two.cleanup_row(
            "§2.8.7",
            "sweep by typed token — "
            + ", ".join(stage_three_sweep_tokens(lane))
            + " — refusing free text and reporting every row it refused",
            CLEANUP_OBSERVED,
        )
    )
    return rows


def assert_stage_three_cleanup_clean(rows: Iterable[Mapping[str, str]], *, strict: bool | None = None) -> None:
    """The Stage 2 gate with the Stage 3 error type: a failed row fails the
    run, a blocked row is named, and ``strict`` falls back to
    :data:`STRICT_CLEANUP` when the lane did not choose."""
    try:
        stage_two.assert_cleanup_clean(rows, strict=strict)
    except StageTwoCleanupError as error:
        raise StageThreeCleanupError(str(error)) from error


def stage_three_sweep_tokens(lane: str) -> tuple[str, ...]:
    """The typed ``kind=value`` tokens a Stage 3 sweep may name for one lane:
    the lane's own entities plus the ``idem`` marker it wrote."""
    return tuple(f"{kind}={lane}" for kind in (*stage_two.LANE_TOKEN_KINDS, "idem"))


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
# 10. The SDL contract
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
