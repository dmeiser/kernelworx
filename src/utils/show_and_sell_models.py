"""Show & Sell event persistence (delivery checklist §3.1.1; data model §5.10, §6.4, §9.1).

One event lives on the ``show_and_sells`` table at the physical key shapes of data
model §6.4::

    SHOW_AND_SELL#<showAndSellId>   / METADATA                    (§5.10, this leaf)
    SHOW_AND_SELL#<showAndSellId>   / SLOT#<slotId>               (§5.12, §3.3 writes these)
    SHOW_AND_SELL#<showAndSellId>   / SIGNUP#<slotId>#<profileId> (§5.13, §3.4 writes these)

The event aggregate is the serialization point for everything else in the event:
allocations, signups, sales and finalization all condition on its ``version``, which
is why §3.1.4 names ONE write owner for event aggregate writes. This module is the
persistence half of that owner — it owns the row shape, the invariants, the writable
field set, and the conditional writes. It answers no question about WHO may call it:
authorization is the resolver's job (the ``showAndSell*`` resolvers in
:mod:`src.handlers.unit_operations` plus :mod:`src.utils.unit_auth`), exactly as the
other model modules hold that line.

The invariants enforced here:

- ``endAt > startAt`` and neither instant is writable after the create. Rescheduling
  is not supported (spec SSE-07): the workflow is cancel-and-recreate, and an
  immutable interval is what makes "cancellable only before start" decidable later.
- ``status`` is not a stored clock. The stored row records the workflow writes
  (``CANCELLED``, ``FINALIZED``, ``REOPENED``); the clock states
  ``SCHEDULED``/``ACTIVE``/``ENDED`` are DERIVED from the immutable interval
  (:func:`derive_event_status`) because nothing in this design advances a clock by
  writing a row, and a stored state that a missing scheduled job failed to move
  would silently freeze an event in the wrong state.
- ``FINALIZED`` requires ``approvedFinalizationId`` and ``REOPENED`` requires it null
  (:func:`event_invariant_violations`), so the credit pointer and the state can never
  disagree.
- ``productIds`` is cumulative and uncapped (:func:`merge_product_ids`): it is the
  authoritative way to find an event's allocation rows (§6.3 note), so a product that
  was ever allocated or sold must stay listed.
- Cancellation audit (``cancelledByAccountId``/``cancelledAt``/``cancellationReason``)
  is written in the same transaction as the state change, never afterwards.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import AbstractSet, Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, TypeGuard

from . import inventory_models
from .dynamodb import batch_get_chunked, tables
from .errors import AppError, ErrorCode
from .ids import ensure_profile_id
from .inventory_models import (
    ALLOCATED_QTY,
    ALLOCATION_CANCELLED,
    ALLOCATION_ENTITY_TYPE,
    ALLOCATION_OPEN,
    PRODUCT_ID_ATTRIBUTE,
    RELEASED_QTY,
    REMAINING_QTY,
    SOLD_QTY,
    require_allocation_transition,
)
from .mutations import wire_key, wire_value
from .pagination import query_all_items
from .unit_models import MAX_ID_LENGTH, METADATA_SK, normalize_enum, normalize_optional_text, normalize_required_text

# --- Key layout (data model §6.4) ------------------------------------------------

SHOW_AND_SELL_PK_PREFIX = "SHOW_AND_SELL"
SLOT_SK_PREFIX = "SLOT"
SIGNUP_SK_PREFIX = "SIGNUP"
SALE_SK_PREFIX = "SALE"
FINALIZATION_SK_PREFIX = "FINALIZATION"
CREDIT_SK_PREFIX = "CREDIT"
WE_OWE_SK_PREFIX = "WE_OWE"

# --- Event state vocabulary (data model §5.10, §9.1; SDL enum ShowAndSellStatus) --

STATUS_SCHEDULED = "SCHEDULED"
STATUS_ACTIVE = "ACTIVE"
STATUS_ENDED = "ENDED"
STATUS_REOPENED = "REOPENED"
STATUS_FINALIZED = "FINALIZED"
STATUS_CANCELLED = "CANCELLED"

EVENT_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_SCHEDULED,
        STATUS_ACTIVE,
        STATUS_ENDED,
        STATUS_REOPENED,
        STATUS_FINALIZED,
        STATUS_CANCELLED,
    }
)

#: The clock states, in the order the calendar moves through them. They are never
#: stored: :func:`derive_event_status` computes them from the immutable interval.
#: ``SCHEDULED`` is the stored placeholder a create writes; ``ACTIVE`` and ``ENDED``
#: are what that placeholder reads as once the clock passes each end of the interval,
#: so a row that stored either one would be a second, staler answer to the same
#: question -- and a later writer could freeze an event at ``ACTIVE`` forever.
DERIVED_STATUSES: frozenset[str] = frozenset({STATUS_SCHEDULED, STATUS_ACTIVE, STATUS_ENDED})

#: The two states that must never reach a row. Writing one is the bug where a later
#: wave "helpfully" persists the derived answer: nothing recomputes it, so the event
#: keeps reporting ``ACTIVE`` after it ended and ``require_cancellable`` starts
#: agreeing with the row instead of with the interval.
NEVER_STORED_STATUSES: frozenset[str] = frozenset({STATUS_ACTIVE, STATUS_ENDED})

#: States in which the event's own settings may still change (API contract §3.5).
#: ``REOPENED`` is on the list because a reopened event's edits are drafts — they
#: change nothing that was approved until the event is finalized again (§5.3.2) —
#: and ``FINALIZED``/``CANCELLED`` are absent because those answers are settled.
EDITABLE_STATUSES: frozenset[str] = frozenset({STATUS_SCHEDULED, STATUS_ACTIVE, STATUS_ENDED, STATUS_REOPENED})

#: States in which an opportunity is still an opportunity for a Scout: a finished or
#: cancelled event is history, not something to sign up for.
OPEN_STATUSES: frozenset[str] = frozenset({STATUS_SCHEDULED, STATUS_ACTIVE})

SPLIT_METHOD_EQUAL = "EQUAL"
SPLIT_METHOD_TIME_WORKED = "TIME_WORKED"
DEFAULT_SPLIT_METHOD = SPLIT_METHOD_EQUAL

#: We Owe obligation states (§5.15, SDL ``WeOweStatus``). The obligation rows
#: themselves are Wave 4's to write; this leaf only reads them, because
#: ``updateShowAndSell`` may not turn We Owe off while an obligation is still OPEN
#: and the answer to "is it still open" needs the vocabulary here, not a string
#: literal in two places (EVT-M-02-02).
WE_OWE_STATUS_OPEN = "OPEN"
WE_OWE_STATUS_CLOSED = "CLOSED"

# --- Attributes ------------------------------------------------------------------

ENTITY_TYPE_EVENT = "ShowAndSell"
ENTITY_TYPE_SLOT = "ShowAndSellSlot"
ENTITY_TYPE_SIGNUP = "ShowAndSellSignup"

#: Signup and commitment states (§5.13, §9.3). A cancelled signup keeps its row: the
#: record of who was signed up is history, and SSE-05 keeps it for the reports that
#: read a cancelled event.
SIGNUP_ACTIVE = "ACTIVE"
SIGNUP_CANCELLED = "CANCELLED"

#: The only legal move for a signup or its commitment projection (§5.13, §9.3):
#: holding a place, then having given it back. Terminal once given back.
SIGNUP_TRANSITIONS: Dict[str, frozenset[str]] = {
    SIGNUP_ACTIVE: frozenset({SIGNUP_CANCELLED}),
    SIGNUP_CANCELLED: frozenset(),
}

#: Sort-key prefixes of the §5.13 projection pair on ``unit_campaigns`` (§6.2).
COMMITMENT_SK_PREFIX = "COMMITMENT"
COMMITMENT_GUARD_SK = "COMMITMENT_GUARD"

SHOW_AND_SELL_ID_ATTRIBUTE = "showAndSellId"
UNIT_ID_ATTRIBUTE = "unitId"
UNIT_CAMPAIGN_ID_ATTRIBUTE = "unitCampaignId"
LOCATION_NAME_ATTRIBUTE = "locationName"
ADDRESS_ATTRIBUTE = "address"
START_AT_ATTRIBUTE = "startAt"
END_AT_ATTRIBUTE = "endAt"
STATUS_ATTRIBUTE = "status"
SPLIT_METHOD_ATTRIBUTE = "splitMethod"
WE_OWE_ENABLED_ATTRIBUTE = "weOweEnabled"
PRODUCT_IDS_ATTRIBUTE = "productIds"
ROUNDING_DRAFT_ATTRIBUTE = "roundingDraftByProfileId"

#: The Kernel's draft stock targets for a reopened event, keyed by product id
#: (§3.2.3: while ``REOPENED`` the mutation writes "only draft inputs"). Stored on the
#: event aggregate as a map, exactly like :data:`ROUNDING_DRAFT_ATTRIBUTE`, because it
#: is the same kind of fact: an input that has been entered but not approved, and an
#: input that re-finalization (§5.3.2) validates and applies. It is deliberately not an
#: ``EventInventoryAllocation`` row — §5.11 allows ONE row per
#: (campaign, product, event), finalization has already released that row to a terminal
#: state (§9.2), and a second row for the same product would mean finalization's
#: product walk finds two answers for one product. The data model names the behaviour
#: ("Re-finalization validates the new allocation/return inputs", §8.6) without naming
#: the attribute; this is the attribute, and Stage 5 owns reading it.
ALLOCATION_DRAFT_ATTRIBUTE = "draftAllocationByProductId"
APPROVED_FINALIZATION_ID_ATTRIBUTE = "approvedFinalizationId"
LATEST_FINALIZATION_ID_ATTRIBUTE = "latestFinalizationId"
VERSION_ATTRIBUTE = "version"
CREATED_AT_ATTRIBUTE = "createdAt"
UPDATED_AT_ATTRIBUTE = "updatedAt"
CREATED_BY_ATTRIBUTE = "createdByAccountId"
UPDATED_BY_ATTRIBUTE = "updatedByAccountId"
CANCELLED_BY_ATTRIBUTE = "cancelledByAccountId"
CANCELLED_AT_ATTRIBUTE = "cancelledAt"
CANCELLATION_REASON_ATTRIBUTE = "cancellationReason"

SLOT_ID_ATTRIBUTE = "slotId"
PROFILE_ID_ATTRIBUTE = "profileId"
CAMPAIGN_ID_ATTRIBUTE = "campaignId"
LABEL_ATTRIBUTE = "label"
CAPACITY_ATTRIBUTE = "capacity"
ACTIVE_SIGNUP_COUNT_ATTRIBUTE = "activeSignupCount"

#: Confirmed-work and signup-audit attributes (§5.13). ``actualMinutes`` is zero
#: until a Kernel confirms the work, and the audit fields stay on the administrative
#: surface: a participant sees their own signup without the actor who placed it.
ACTUAL_MINUTES_ATTRIBUTE = "actualMinutes"
SIGNED_UP_BY_ATTRIBUTE = "signedUpByAccountId"
CONFIRMED_BY_ATTRIBUTE = "confirmedByAccountId"
CONFIRMED_AT_ATTRIBUTE = "confirmedAt"

#: Row types of the §5.13 projection pair on ``unit_campaigns`` (§6.2).
ENTITY_TYPE_COMMITMENT = "ScoutCommitment"
ENTITY_TYPE_COMMITMENT_GUARD = "ScoutCommitmentGuard"

#: The commitment projection's own identity attribute (§5.13): "same identity as
#: the signup". It is spelled with :func:`signup_sk`, because that is exactly the
#: signup's identity inside its aggregate — one name for one fact, so a reader
#: holding a commitment can point at the signup row it came from.
COMMITMENT_ID_ATTRIBUTE = "commitmentId"

#: The guard's version attribute (§5.13). Named here because the guard increment
#: (:func:`bump_commitment_guard_action`) and the guard builder must spell it alike.
COMMITMENT_VERSION_ATTRIBUTE = "commitmentVersion"

#: Every attribute a METADATA row may carry (§5.10, in full). An extra attribute
#: would be a fact the model never declares, so no read projects it and no test covers it.
EVENT_ROW_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "pk",
        "sk",
        "entityType",
        SHOW_AND_SELL_ID_ATTRIBUTE,
        UNIT_ID_ATTRIBUTE,
        UNIT_CAMPAIGN_ID_ATTRIBUTE,
        LOCATION_NAME_ATTRIBUTE,
        ADDRESS_ATTRIBUTE,
        START_AT_ATTRIBUTE,
        END_AT_ATTRIBUTE,
        STATUS_ATTRIBUTE,
        SPLIT_METHOD_ATTRIBUTE,
        WE_OWE_ENABLED_ATTRIBUTE,
        PRODUCT_IDS_ATTRIBUTE,
        ROUNDING_DRAFT_ATTRIBUTE,
        ALLOCATION_DRAFT_ATTRIBUTE,
        APPROVED_FINALIZATION_ID_ATTRIBUTE,
        LATEST_FINALIZATION_ID_ATTRIBUTE,
        VERSION_ATTRIBUTE,
        CREATED_AT_ATTRIBUTE,
        UPDATED_AT_ATTRIBUTE,
        CREATED_BY_ATTRIBUTE,
        UPDATED_BY_ATTRIBUTE,
        CANCELLED_BY_ATTRIBUTE,
        CANCELLED_AT_ATTRIBUTE,
        CANCELLATION_REASON_ATTRIBUTE,
    }
)

#: Every attribute a ``SLOT#`` row may carry (§5.12, in full). Same rule as
#: :data:`EVENT_ROW_ATTRIBUTES`: an extra attribute is a fact the design never
#: declares, so no read projects it and no test covers it.
SLOT_ROW_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "pk",
        "sk",
        "entityType",
        SHOW_AND_SELL_ID_ATTRIBUTE,
        SLOT_ID_ATTRIBUTE,
        LABEL_ATTRIBUTE,
        START_AT_ATTRIBUTE,
        END_AT_ATTRIBUTE,
        CAPACITY_ATTRIBUTE,
        ACTIVE_SIGNUP_COUNT_ATTRIBUTE,
        VERSION_ATTRIBUTE,
        CREATED_AT_ATTRIBUTE,
        UPDATED_AT_ATTRIBUTE,
    }
)

#: Every attribute a ``SIGNUP#`` row may carry (§5.13, in full). The signup is
#: written by §3.4, but the row shape is declared here because §3.3 owns the
#: aggregate's storage contract: the slot counter, the update revalidation, and the
#: cancellation reads all reason about this row.
SIGNUP_ROW_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "pk",
        "sk",
        "entityType",
        SHOW_AND_SELL_ID_ATTRIBUTE,
        SLOT_ID_ATTRIBUTE,
        PROFILE_ID_ATTRIBUTE,
        UNIT_CAMPAIGN_ID_ATTRIBUTE,
        CAMPAIGN_ID_ATTRIBUTE,
        STATUS_ATTRIBUTE,
        ACTUAL_MINUTES_ATTRIBUTE,
        SIGNED_UP_BY_ATTRIBUTE,
        CONFIRMED_BY_ATTRIBUTE,
        CONFIRMED_AT_ATTRIBUTE,
        VERSION_ATTRIBUTE,
        CREATED_AT_ATTRIBUTE,
        UPDATED_AT_ATTRIBUTE,
    }
)

#: The ``COMMITMENT#`` projection row (§5.13) and the one-row-per-Scout guard.
COMMITMENT_ROW_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "pk",
        "sk",
        "entityType",
        PROFILE_ID_ATTRIBUTE,
        UNIT_CAMPAIGN_ID_ATTRIBUTE,
        COMMITMENT_ID_ATTRIBUTE,
        SHOW_AND_SELL_ID_ATTRIBUTE,
        SLOT_ID_ATTRIBUTE,
        START_AT_ATTRIBUTE,
        END_AT_ATTRIBUTE,
        STATUS_ATTRIBUTE,
        VERSION_ATTRIBUTE,
        CREATED_AT_ATTRIBUTE,
        UPDATED_AT_ATTRIBUTE,
    }
)

COMMITMENT_GUARD_ROW_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "pk",
        "sk",
        "entityType",
        PROFILE_ID_ATTRIBUTE,
        COMMITMENT_VERSION_ATTRIBUTE,
        UPDATED_AT_ATTRIBUTE,
    }
)

#: The fields ``updateShowAndSell`` may write (API contract §6.2). Everything else
#: on the row is either derived, server-owned, or immutable, and :func:`writable_changes`
#: refuses a payload that smuggles one in — including ``startAt``/``endAt``, which is
#: how "no rescheduling" is enforced rather than merely undocumented (SSE-07).
WRITABLE_FIELDS: frozenset[str] = frozenset(
    {
        LOCATION_NAME_ATTRIBUTE,
        ADDRESS_ATTRIBUTE,
        SPLIT_METHOD_ATTRIBUTE,
        WE_OWE_ENABLED_ATTRIBUTE,
    }
)

IMMUTABLE_FIELDS: frozenset[str] = frozenset(
    {
        SHOW_AND_SELL_ID_ATTRIBUTE,
        UNIT_ID_ATTRIBUTE,
        UNIT_CAMPAIGN_ID_ATTRIBUTE,
        START_AT_ATTRIBUTE,
        END_AT_ATTRIBUTE,
    }
)

# --- Limits (API contract §3.4) --------------------------------------------------

MAX_LOCATION_NAME_LENGTH = 100
MAX_ADDRESS_LENGTH = 500
MAX_REASON_LENGTH = 500

# --- Slot and capacity limits (API contract §3.4/§6.3, data model §5.12) ---------

#: A slot holds at least one Scout: capacity 0 would be a slot nobody can ever
#: fill, and an admin who wants a slot gone deletes it (§3.3.3).
MIN_SLOT_CAPACITY = 1
#: The ceiling §3.3.2 enforces as input validation — a "1000-person booth" is a
#: typo at the keyboard, not a Scout roster.
MAX_SLOT_CAPACITY = 100
#: An event carries at most 20 slots (§3.3.2). The count is decided against the
#: event's own slot partition under the event-version condition, so two concurrent
#: creations cannot each count 20 and land 21.
MAX_SLOTS_PER_EVENT = 20
#: A slot label is display text for the signup screen; 100 characters covers every
#: real booth name and keeps the row small (§5.12's label is optional text).
MAX_SLOT_LABEL_LENGTH = 100

_MOMENT_PATTERN_HINT = "must be an ISO 8601 date-time with a time zone"


# --- Normalization and validation ------------------------------------------------


def _invalid(field: str, rule: str) -> AppError:
    """One INVALID_INPUT rejection, spelled the same way everywhere in this module."""
    return AppError(ErrorCode.INVALID_INPUT, f"{field} {rule}")


def new_show_and_sell_id() -> str:
    """A stable event identity, generated before the write (§5.10).

    A UUID rather than a counter: the id is the event's partition key, so two
    Kernels creating an event at the same moment must not collide on a key either
    of them guessed.
    """
    return str(uuid.uuid4())


def new_slot_id() -> str:
    """A stable slot identity, generated before the write (§5.12).

    The slot id is the suffix of the slot row's sort key inside the event's
    partition, so two Kernels adding a slot to the same event at the same moment
    must not collide on one the other guessed — and an id the browser sent could
    collide with a slot that event already has, which would read as a duplicate
    rather than as the new slot that was asked for.
    """
    return str(uuid.uuid4())


def normalize_event_id(value: Any, field: str = SHOW_AND_SELL_ID_ATTRIBUTE) -> str:
    """Validate an id that sits inside the event's partition key (§6.4).

    A ``#`` inside an id is allowed, because that is how this application spells
    ids elsewhere; an EMPTY ``#`` segment is refused, because it lets two different
    rows collide on one key.
    """
    text = normalize_required_text(value, field, MAX_ID_LENGTH)
    if "#" in text and (text.startswith("#") or text.endswith("#") or "##" in text):
        raise _invalid(field, "must not contain an empty # segment")
    return text


def normalize_location_name(value: Any, field: str = LOCATION_NAME_ATTRIBUTE) -> str:
    """The required short location name, 1-100 trimmed characters (§3.4, AC-15)."""
    return normalize_required_text(value, field, MAX_LOCATION_NAME_LENGTH)


def normalize_address(value: Any, field: str = ADDRESS_ATTRIBUTE) -> Optional[str]:
    """The optional address, at most 500 characters (§3.4)."""
    return normalize_optional_text(value, field, MAX_ADDRESS_LENGTH)


def normalize_cancellation_reason(value: Any, field: str = CANCELLATION_REASON_ATTRIBUTE) -> str:
    """The reason a cancellation is required to carry: 1-500 trimmed characters.

    §3.1.4 requires the reason, and the shared reason limit (§3.4) caps it at 500.
    It is validated on the way in rather than at the write, because the reason is part
    of the same transaction as the state change — a reason that failed validation
    after the release writes were staged would abort a cancellation the admin intended
    to complete, and a truncated one would be an audit trail that stops mid-sentence.
    """
    return normalize_required_text(value, field, MAX_REASON_LENGTH)


def normalize_moment(value: Any, field: str) -> str:
    """Canonicalize an instant to the one UTC spelling every writer uses.

    Every interval comparison in this feature — cancel-before-start, opportunity
    visibility, the §3.2 overlap rule — is a string comparison over sort keys, and
    that is chronological only when the spelling is fixed. A zone-less value is
    refused rather than assumed to be UTC, because an assumed zone is a wrong
    timestamp no later read can detect.
    """
    if not isinstance(value, str) or not value.strip():
        raise _invalid(field, _MOMENT_PATTERN_HINT)
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise _invalid(field, _MOMENT_PATTERN_HINT) from None
    if parsed.tzinfo is None:
        raise _invalid(field, _MOMENT_PATTERN_HINT)
    return parsed.astimezone(timezone.utc).isoformat()


def normalize_interval(start_at: Any, end_at: Any) -> Tuple[str, str]:
    """Validate the immutable event interval: both instants, and end after start.

    SSE-03 says end must be after start, and SSE-03 also says the application must
    not assume one-hour increments — so the only rule here is ordering, never
    duration or alignment.
    """
    start = normalize_moment(start_at, START_AT_ATTRIBUTE)
    end = normalize_moment(end_at, END_AT_ATTRIBUTE)
    if end <= start:
        raise _invalid(END_AT_ATTRIBUTE, "must be after startAt")
    return (start, end)


def normalize_split_method(value: Any) -> str:
    """The event's split override, in the same vocabulary as the Unit default."""
    return normalize_enum(
        value,
        SPLIT_METHOD_ATTRIBUTE,
        frozenset({SPLIT_METHOD_EQUAL, SPLIT_METHOD_TIME_WORKED}),
        DEFAULT_SPLIT_METHOD,
    )


def normalize_we_owe_enabled(value: Any) -> bool:
    """We Owe on or off. Absent means off: SSE-01 defaults it disabled (§5.10)."""
    if value is None:
        return False
    if not isinstance(value, bool):
        raise _invalid(WE_OWE_ENABLED_ATTRIBUTE, "must be a boolean")
    return value


def normalize_event_status(value: Any, field: str = STATUS_ATTRIBUTE) -> str:
    """Validate a state name against §9.1's six states."""
    text = normalize_required_text(value, field, 32).upper()
    if text not in EVENT_STATUSES:
        raise _invalid(field, f"must be one of {', '.join(sorted(EVENT_STATUSES))}")
    return text


def normalize_product_ids(value: Any, field: str = PRODUCT_IDS_ATTRIBUTE) -> List[str]:
    """Validate a product-id list: every entry a real id, no duplicates.

    There is no event-wide product-count cap (§5.10, EVT-M-01-02), so this function
    never rejects a length. The batch ceiling lives in the write plan, where it is
    counted against what the transaction actually does.
    """
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set)):
        raise _invalid(field, "must be a list of product ids")
    seen: List[str] = []
    for entry in value:
        product_id = normalize_event_id(entry, f"{field}[]")
        if product_id not in seen:
            seen.append(product_id)
    return seen


def merge_product_ids(existing: Any, additions: Iterable[str]) -> List[str]:
    """Add to ``productIds`` without losing or reordering what is already there.

    Cumulative and uncapped: the list is how §8.10 and finalization find every
    allocation the event ever had, so dropping an entry whose allocation was
    released would strand those inventory rows.
    """
    merged = normalize_product_ids(existing)
    for product_id in normalize_product_ids(additions):
        if product_id not in merged:
            merged.append(product_id)
    return merged


def normalize_slot_id(value: Any, field: str = SLOT_ID_ATTRIBUTE) -> str:
    """Validate a slot id by the same id rules as every other key component."""
    return normalize_event_id(value, field)


def normalize_label(value: Any, field: str = LABEL_ATTRIBUTE) -> Optional[str]:
    """The optional slot label (§5.12): an absent or blank label is no label."""
    return normalize_optional_text(value, field, MAX_SLOT_LABEL_LENGTH)


def normalize_capacity(value: Any, field: str = CAPACITY_ATTRIBUTE) -> int:
    """A slot capacity inside 1-100 (§3.3.2).

    The range is validation, not a tunable: 0 is a slot nobody can fill, and a
    four-digit capacity is a keyboard slip that would let a thousand Scouts into
    one booth before any signup write could refuse it.
    """
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise _invalid(field, "must be an integer")
    number = int(value)
    if number < MIN_SLOT_CAPACITY or number > MAX_SLOT_CAPACITY:
        raise _invalid(field, f"must be between {MIN_SLOT_CAPACITY} and {MAX_SLOT_CAPACITY}")
    return number


def normalize_active_count(value: Any, field: str = ACTIVE_SIGNUP_COUNT_ATTRIBUTE) -> int:
    """The maintained counter as a non-negative integer (§5.12)."""
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise _invalid(field, "must be an integer")
    number = int(value)
    if number < 0:
        raise _invalid(field, "must not be negative")
    return number


def normalize_actual_minutes(value: Any, field: str = ACTUAL_MINUTES_ATTRIBUTE) -> int:
    """Confirmed work minutes as a non-negative integer (§5.13): 0 means unconfirmed."""
    return normalize_active_count(value, field)


# --- Key builders ----------------------------------------------------------------


def show_and_sell_pk(show_and_sell_id: str) -> str:
    """Partition key holding one event's aggregate: metadata, slots, signups, sales."""
    return f"{SHOW_AND_SELL_PK_PREFIX}#{show_and_sell_id}"


def event_metadata_key(show_and_sell_id: str) -> Dict[str, str]:
    """The event METADATA row's key pair."""
    return {"pk": show_and_sell_pk(show_and_sell_id), "sk": METADATA_SK}


def slot_sk(slot_id: str) -> str:
    """Sort key of one slot within its event (§6.4)."""
    return f"{SLOT_SK_PREFIX}#{slot_id}"


def slot_key(show_and_sell_id: str, slot_id: str) -> Dict[str, str]:
    """The slot row's key pair."""
    return {"pk": show_and_sell_pk(show_and_sell_id), "sk": slot_sk(slot_id)}


def signup_sk(slot_id: str, profile_id: str) -> str:
    """Sort key of one Scout's signup for one slot (§6.4)."""
    return f"{SIGNUP_SK_PREFIX}#{slot_id}#{profile_id}"


# --- Row builders and invariants -------------------------------------------------


def build_show_and_sell_item(
    *,
    show_and_sell_id: Any,
    unit_id: Any,
    unit_campaign_id: Any,
    location_name: Any,
    start_at: Any,
    end_at: Any,
    created_by_account_id: Any,
    now_iso: Any,
    address: Any = None,
    split_method: Any = DEFAULT_SPLIT_METHOD,
    we_owe_enabled: Any = False,
    product_ids: Any = (),
    status: Any = STATUS_SCHEDULED,
    version: Any = 1,
) -> Dict[str, Any]:
    """The §5.10 event row, in the shape the create path writes.

    The caller supplies only what §6.2 says a caller may choose. ``status`` and
    ``version`` are keyword arguments with the create-time defaults so the §3.2+
    writers that re-emit a row (finalization, reopening) can do so without letting a
    browser pass either one; no resolver accepts them as input.
    """
    event_id = normalize_event_id(show_and_sell_id)
    start, end = normalize_interval(start_at, end_at)
    stamp = normalize_moment(now_iso, CREATED_AT_ATTRIBUTE)
    item: Dict[str, Any] = {
        "pk": show_and_sell_pk(event_id),
        "sk": METADATA_SK,
        "entityType": ENTITY_TYPE_EVENT,
        SHOW_AND_SELL_ID_ATTRIBUTE: event_id,
        UNIT_ID_ATTRIBUTE: normalize_event_id(unit_id, UNIT_ID_ATTRIBUTE),
        UNIT_CAMPAIGN_ID_ATTRIBUTE: normalize_event_id(unit_campaign_id, UNIT_CAMPAIGN_ID_ATTRIBUTE),
        LOCATION_NAME_ATTRIBUTE: normalize_location_name(location_name),
        START_AT_ATTRIBUTE: start,
        END_AT_ATTRIBUTE: end,
        STATUS_ATTRIBUTE: normalize_event_status(status),
        SPLIT_METHOD_ATTRIBUTE: normalize_split_method(split_method),
        WE_OWE_ENABLED_ATTRIBUTE: normalize_we_owe_enabled(we_owe_enabled),
        PRODUCT_IDS_ATTRIBUTE: normalize_product_ids(product_ids),
        APPROVED_FINALIZATION_ID_ATTRIBUTE: None,
        LATEST_FINALIZATION_ID_ATTRIBUTE: None,
        VERSION_ATTRIBUTE: normalize_required_version(version),
        CREATED_AT_ATTRIBUTE: stamp,
        UPDATED_AT_ATTRIBUTE: stamp,
        CREATED_BY_ATTRIBUTE: normalize_event_id(created_by_account_id, CREATED_BY_ATTRIBUTE),
        UPDATED_BY_ATTRIBUTE: normalize_event_id(created_by_account_id, UPDATED_BY_ATTRIBUTE),
        CANCELLED_BY_ATTRIBUTE: None,
        CANCELLED_AT_ATTRIBUTE: None,
        CANCELLATION_REASON_ATTRIBUTE: None,
    }
    if address is not None:
        item[ADDRESS_ATTRIBUTE] = normalize_address(address)
    violations = event_invariant_violations(item)
    if violations:
        raise _invalid(SHOW_AND_SELL_ID_ATTRIBUTE, f"would break the event invariants: {'; '.join(violations)}")
    return item


def normalize_required_version(value: Any, field: str = VERSION_ATTRIBUTE) -> int:
    """A version as a positive integer, refusing a bool the way every counter here does."""
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise _invalid(field, "must be an integer")
    number = int(value)
    if number < 1:
        raise _invalid(field, "must be a positive integer")
    return number


def _interval_violations(item: Mapping[str, Any]) -> List[str]:
    """The two invariants the immutable interval carries.

    An event whose ``endAt`` does not follow ``startAt`` makes every derived state,
    overlap rule, and calendar in the feature meaningless, so this is checked on the
    way in rather than at each place that later compares the two.
    """
    start = str(item.get(START_AT_ATTRIBUTE) or "")
    end = str(item.get(END_AT_ATTRIBUTE) or "")
    if not start or not end:
        return ["both startAt and endAt are required"]
    if end <= start:
        return ["endAt must be after startAt"]
    return []


def _state_violations(item: Mapping[str, Any]) -> List[str]:
    """The state-machine invariants of data model §5.10 and §9.1.

    Each one is a state a later mutation would otherwise have to re-derive: a
    ``FINALIZED`` event with no approved finalization would answer a credit question
    with nothing behind it, and a cancelled event with no reason is an audit trail
    that cannot explain why stock and signups disappeared.
    """
    status = str(item.get(STATUS_ATTRIBUTE) or "")
    problems: List[str] = []
    if status not in EVENT_STATUSES:
        problems.append(f"status {status!r} is not one of {', '.join(sorted(EVENT_STATUSES))}")
    elif status in NEVER_STORED_STATUSES:
        problems.append(
            f"{status} is derived from the interval and must never be stored; store {STATUS_SCHEDULED} "
            "or the workflow state that actually happened"
        )
    approved = item.get(APPROVED_FINALIZATION_ID_ATTRIBUTE)
    if status == STATUS_FINALIZED and not approved:
        problems.append("a FINALIZED event requires approvedFinalizationId")
    if status == STATUS_REOPENED and approved:
        problems.append("a REOPENED event must have approvedFinalizationId cleared")
    if status == STATUS_CANCELLED and not item.get(CANCELLATION_REASON_ATTRIBUTE):
        problems.append("a CANCELLED event requires cancellationReason and its audit")
    return problems


def _row_shape_violations(item: Mapping[str, Any]) -> List[str]:
    """The row-shape invariants: no attribute the model leaves out, and a clean ``productIds``.

    ``productIds`` is how an event's allocation rows are found authoritatively
    (§6.3), so a repeated entry would double-count an allocation read, and an
    attribute outside :data:`EVENT_ROW_ATTRIBUTES` is a field nothing in the design
    reads back.
    """
    problems: List[str] = []
    extra = set(item) - EVENT_ROW_ATTRIBUTES
    if extra:
        problems.append(f"attributes the model leaves out: {', '.join(sorted(extra))}")
    product_ids = item.get(PRODUCT_IDS_ATTRIBUTE)
    if not isinstance(product_ids, list):
        problems.append("productIds must be a list")
    elif len(set(product_ids)) != len(product_ids):
        problems.append("productIds must not repeat a product")
    return problems


def event_invariant_violations(item: Mapping[str, Any]) -> List[str]:
    """Every §5.10 invariant this row can break, as plain-language breaches.

    The three families — interval, state, row shape — are checked on the way in and
    asserted by the model tests, so no later mutation has to re-derive any of them.
    """
    return _interval_violations(item) + _state_violations(item) + _row_shape_violations(item)


def writable_changes(changes: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep only the fields an update may write, and say so when something else is offered.

    ``updateShowAndSell`` exposes location, address, split, and We Owe — nothing else
    (§6.2). This is the single place that rule is stated, so a startAt smuggled into
    an update is rejected by the same code path in every state, and the
    cancel-and-recreate rule (SSE-07) has one owner instead of three.
    """
    refused = sorted(key for key in changes if key not in WRITABLE_FIELDS)
    if refused:
        raise _invalid(
            refused[0],
            f"cannot be changed after the event is created; only {', '.join(sorted(WRITABLE_FIELDS))} are writable",
        )
    return dict(changes)


# --- State derivation (data model §9.1) ------------------------------------------


def derive_event_status(item: Mapping[str, Any], now_iso: Optional[str] = None) -> str:
    """The state a caller is told about: the stored state, or the clock's.

    A row stores only what a workflow decided. ``SCHEDULED`` means "nothing has
    happened to this event yet", so the answer a caller needs comes from the
    immutable interval: before ``startAt`` it is scheduled, from ``startAt`` to
    ``endAt`` it is running, at or after ``endAt`` it has ended and waits for
    finalization (SSE-04 — an ended event is not a finalized one).
    """
    stored = str(item.get(STATUS_ATTRIBUTE) or "")
    if stored not in DERIVED_STATUSES:
        return stored
    moment = now_iso if now_iso is not None else datetime.now(timezone.utc).isoformat()
    if moment < str(item[START_AT_ATTRIBUTE]):
        return STATUS_SCHEDULED
    if moment < str(item[END_AT_ATTRIBUTE]):
        return STATUS_ACTIVE
    return STATUS_ENDED


def event_is_editable(item: Mapping[str, Any], now_iso: Optional[str] = None) -> bool:
    """Whether §3.5's state matrix allows an update of these settings."""
    return derive_event_status(item, now_iso) in EDITABLE_STATUSES


def require_editable(item: Mapping[str, Any], now_iso: Optional[str] = None) -> str:
    """Reject an update outside the state matrix, naming the state the caller hit.

    §3.5 fixes the verdict: an operation attempted outside the matrix is ``CONFLICT``,
    while cross-tenant and role denials (``NOT_FOUND``, ``FORBIDDEN``) are decided
    before this point by the resolver.
    """
    state = derive_event_status(item, now_iso)
    if state not in EDITABLE_STATUSES:
        raise AppError(
            ErrorCode.CONFLICT,
            f"A {state} event cannot be edited. Reopen a finalized event first, and a cancelled event is finished.",
            details={"subcode": "EVENT_STATE", "status": state},
        )
    return state


def require_cancellable(item: Mapping[str, Any], now_iso: Optional[str] = None) -> str:
    """Require the event to still be cancellable: SCHEDULED, and now before ``startAt``.

    §5.10 and §9.1 allow cancellation only "before ``startAt``", and §3.5 repeats it as
    a timing rule on top of the state rule. Both are checked, because they catch
    different mistakes: a state the clock has already moved past, and a stored state
    that has not caught up to an event that has started. Either way the answer is
    ``CONFLICT``, not a partial teardown — once Scouts have begun working, the event is
    finished by finalization, and §8.8's release arithmetic no longer describes what
    happened.
    """
    moment = now_iso if now_iso is not None else datetime.now(timezone.utc).isoformat()
    state = derive_event_status(item, moment)
    if state != STATUS_SCHEDULED or moment >= str(item[START_AT_ATTRIBUTE]):
        raise AppError(
            ErrorCode.CONFLICT,
            "Only an event that has not started can be cancelled. An event under way is finished by finalizing it.",
            details={"subcode": "EVENT_STATE", "status": state},
        )
    return state


def require_slots_writable(item: Mapping[str, Any], now_iso: Optional[str] = None) -> str:
    """Require the event to be in the one state §3.3 allows slot writes in.

    §3.3.2 and §3.3.3 both say SCHEDULED, and it is stricter than §3.5's general
    editable matrix on purpose: once the event has started, its slots are facts the
    Scouts already worked against — moving or deleting one after the fact would
    rewrite the schedule people showed up to. ``REOPENED`` is refused here for the
    same reason: what a reopened event edits are the finalization drafts, not the
    shift board.
    """
    state = derive_event_status(item, now_iso)
    if state != STATUS_SCHEDULED:
        raise AppError(
            ErrorCode.CONFLICT,
            "Slots can only be changed while the event is scheduled. Once it has started, its slots stand as signed up.",
            details={"subcode": "EVENT_STATE", "status": state},
        )
    return state


def we_owe_disable_blocked(obligations: Iterable[Mapping[str, Any]]) -> bool:
    """Whether turning We Owe off would strand an obligation that is still open.

    EVT-M-02-02: disabling We Owe is allowed only when it cannot invalidate an
    existing We Owe sale or obligation — an open obligation whose event stopped
    offering We Owe would be an obligation the event can no longer account for. A
    closed obligation is history and does not block the change.
    """
    return any(str(row.get(STATUS_ATTRIBUTE) or "") == WE_OWE_STATUS_OPEN for row in obligations)


# --- Reads -----------------------------------------------------------------------


def read_show_and_sell(show_and_sell_id: str) -> Optional[Dict[str, Any]]:
    """Strongly consistent read of one event's METADATA row (SEC-06)."""
    response = tables.show_and_sells.get_item(Key=event_metadata_key(show_and_sell_id), ConsistentRead=True)
    item = response.get("Item")
    return dict(item) if isinstance(item, dict) else None


def load_show_and_sell_or_not_found(show_and_sell_id: str) -> Dict[str, Any]:
    """Read an event, answering ``NOT_FOUND`` when it does not exist (§3.3)."""
    event = read_show_and_sell(show_and_sell_id)
    if event is None:
        raise AppError(ErrorCode.NOT_FOUND, "Show & Sell not found")
    return event


def read_slot(show_and_sell_id: str, slot_id: str) -> Optional[Dict[str, Any]]:
    """Strongly consistent read of one slot by its parent and its own id (SEC-06).

    The parent id is part of the key, which is what makes a slot id from another
    event simply absent here rather than found and then refused: §3.3.3's
    wrong-parent case is a key fact, not a comparison.
    """
    response = tables.show_and_sells.get_item(Key=slot_key(show_and_sell_id, slot_id), ConsistentRead=True)
    item = response.get("Item")
    return dict(item) if isinstance(item, dict) else None


def load_slot_or_not_found(show_and_sell_id: str, slot_id: str) -> Dict[str, Any]:
    """Read one slot, answering ``NOT_FOUND`` when this event does not hold it."""
    slot = read_slot(show_and_sell_id, slot_id)
    if slot is None:
        raise AppError(ErrorCode.NOT_FOUND, "Slot not found for this Show & Sell")
    return slot


def list_campaign_events(unit_campaign_id: str) -> List[Dict[str, Any]]:
    """A Unit Campaign's events, soonest first.

    ``unitCampaignId-startAt-index`` is the discovery path — the aggregate's
    partition key is the event, so no query over the base table can name a
    campaign's events. Discovery is not authority (SEC-06): every row comes back
    through a strongly consistent read of its own key, so a page never shows a state
    the index had not caught up to, and an event deleted between the index read and
    the base read simply drops out.
    """
    found = query_all_items(
        tables.show_and_sells,
        {
            "IndexName": "unitCampaignId-startAt-index",
            "KeyConditionExpression": "#unitCampaignId = :unitCampaignId",
            "ExpressionAttributeNames": {"#unitCampaignId": UNIT_CAMPAIGN_ID_ATTRIBUTE},
            "ExpressionAttributeValues": {":unitCampaignId": unit_campaign_id},
        },
    )
    ids = sorted({str(row[SHOW_AND_SELL_ID_ATTRIBUTE]) for row in found if row.get(SHOW_AND_SELL_ID_ATTRIBUTE)})
    rows: List[Dict[str, Any]] = []
    batch_get_chunked(
        tables.show_and_sells.table_name,
        [event_metadata_key(event_id) for event_id in ids],
        rows.append,
        consistent_read=True,
    )
    events = [row for row in rows if row.get("entityType") == ENTITY_TYPE_EVENT]
    events.sort(
        key=lambda row: (
            str(row.get(START_AT_ATTRIBUTE) or ""),
            str(row.get(SHOW_AND_SELL_ID_ATTRIBUTE) or ""),
        )
    )
    return events


def event_allocation_key(unit_campaign_id: str, product_id: str, show_and_sell_id: str) -> Dict[str, str]:
    """The allocation row's key pair, on the inventory table (§6.3).

    One allocation per (campaign, product, event): the product prefix keeps it in the
    same query as the balance it competes with, and the event component is what makes
    "what does this event hold" a key lookup rather than a scan of the campaign's
    history.
    """
    return {
        "pk": inventory_models.inventory_pk(unit_campaign_id),
        "sk": inventory_models.allocation_sk(product_id, show_and_sell_id),
    }


def event_allocations(event: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The event's allocation rows, read the authoritative way (§6.3 note).

    ``showAndSellId-index`` exists for display; the authoritative set comes from the
    event's own ``productIds``, because that list is written in the same transaction
    as each allocation and an eventually consistent index can lag behind a write the
    event has already committed.
    """
    product_ids = normalize_product_ids(event.get(PRODUCT_IDS_ATTRIBUTE))
    if not product_ids:
        return []
    rows: List[Dict[str, Any]] = []
    batch_get_chunked(
        tables.inventory.table_name,
        [
            event_allocation_key(
                str(event[UNIT_CAMPAIGN_ID_ATTRIBUTE]), product_id, str(event[SHOW_AND_SELL_ID_ATTRIBUTE])
            )
            for product_id in product_ids
        ],
        rows.append,
        consistent_read=True,
    )
    return [row for row in rows if row.get("entityType") == ALLOCATION_ENTITY_TYPE]


def _partition_rows(show_and_sell_id: str, sk_prefix: str) -> List[Dict[str, Any]]:
    """Every row under one event's partition with a given sort-key prefix."""
    return list(
        query_all_items(
            tables.show_and_sells,
            {
                "KeyConditionExpression": "#pk = :pk AND begins_with(#sk, :prefix)",
                "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
                "ExpressionAttributeValues": {":pk": show_and_sell_pk(show_and_sell_id), ":prefix": f"{sk_prefix}#"},
                "ConsistentRead": True,
            },
        )
    )


def event_slot_rows(show_and_sell_id: str) -> List[Dict[str, Any]]:
    """One event's slots (§5.12). Written by §3.3; read here so an opportunity and a
    cancellation see what actually exists rather than assuming none does."""
    return _partition_rows(show_and_sell_id, SLOT_SK_PREFIX)


def event_signup_rows(show_and_sell_id: str) -> List[Dict[str, Any]]:
    """One event's signups (§5.13), written by §3.4."""
    return _partition_rows(show_and_sell_id, SIGNUP_SK_PREFIX)


def event_we_owe_rows(show_and_sell_id: str) -> List[Dict[str, Any]]:
    """One event's We Owe obligations (§5.15), written by Wave 4.

    Read by the We Owe disable guard: obligations are the reason §3.5 refuses an
    unsafe change, and before Wave 4 the answer is simply that there are none.
    """
    return _partition_rows(show_and_sell_id, WE_OWE_SK_PREFIX)


def commitment_rows(profile_id: str, show_and_sell_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """One Scout's commitment projections (§5.13), read consistently.

    The read is the profile partition, not the ``profileId-unitCampaignId-index``
    GSI: the commitment is what blocks an overlapping signup, so the writer that
    cancels one has to be looking at the same row the blocker reads (§6.2 note,
    SEC-06). ``showAndSellId`` is filtered on the row rather than in the key,
    because the sort key leads with ``startAt`` so that a range read can answer an
    overlap question — the price of that layout is that "this event's commitments"
    is a row filter.
    """
    rows = list(
        query_all_items(
            tables.unit_campaigns,
            {
                "KeyConditionExpression": "#pk = :pk AND begins_with(#sk, :prefix)",
                "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
                "ExpressionAttributeValues": {
                    ":pk": commitment_pk(profile_id),
                    ":prefix": f"{COMMITMENT_SK_PREFIX}#",
                },
                "ConsistentRead": True,
            },
        )
    )
    if show_and_sell_id is not None:
        rows = [row for row in rows if str(row.get(SHOW_AND_SELL_ID_ATTRIBUTE) or "") == show_and_sell_id]
    return rows


def active_commitments(profile_id: str, show_and_sell_id: str) -> List[Dict[str, Any]]:
    """One Scout's ACTIVE commitments for one event.

    A cancellation releases the commitments it is releasing, and nothing else. The
    projection keeps cancelled rows as history (§5.13), so a read of "this event's
    commitments" answers both, and re-writing a terminal row would move an audit
    record backwards and spend a transaction action on a row that cannot change.
    """
    return [
        row
        for row in commitment_rows(profile_id, show_and_sell_id)
        if str(row.get(STATUS_ATTRIBUTE) or "") == SIGNUP_ACTIVE
    ]


def _slot_for(slots: Sequence[Mapping[str, Any]], signup: Mapping[str, Any]) -> Mapping[str, Any]:
    """The slot row one signup belongs to.

    A signup whose slot row is missing is a broken aggregate rather than a payload
    with a blank interval, so this raises: the caller loaded the event's whole slot
    partition, and a signup pointing outside it means the event is inconsistent.
    """
    slot_id = str(signup.get(SLOT_ID_ATTRIBUTE) or "")
    for slot in slots:
        if str(slot.get(SLOT_ID_ATTRIBUTE) or "") == slot_id:
            return slot
    raise KeyError(f"signup names slot {slot_id!r}, which this event does not hold")


def read_commitment_guard(profile_id: str) -> Optional[Dict[str, Any]]:
    """The Scout's commitment guard row, or None when the Scout has none yet.

    Absent is a real state, not an error: §5.13's guard is written by the first
    signup, so an event cancelled before anyone signed up has no guard to bump.
    """
    response = tables.unit_campaigns.get_item(Key=commitment_guard_key(profile_id), ConsistentRead=True)
    item = response.get("Item")
    return dict(item) if isinstance(item, dict) else None


def open_allocations(event: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The event's allocations that still hold a reservation (§9.2 ``OPEN``).

    A cancelled or released allocation has nothing left to release, and re-writing
    one would both double-count the release in ``releasedQty`` and move a terminal
    state backwards.
    """
    return [row for row in event_allocations(event) if str(row.get(STATUS_ATTRIBUTE) or "") == ALLOCATION_OPEN]


def active_signups(show_and_sell_id: str) -> List[Dict[str, Any]]:
    """The event's signups that still hold a place (``ACTIVE``, per §9.3)."""
    return [row for row in event_signup_rows(show_and_sell_id) if str(row.get(STATUS_ATTRIBUTE)) == SIGNUP_ACTIVE]


def slots_holding_signups(show_and_sell_id: str) -> List[Dict[str, Any]]:
    """The event's slots whose active-signup counter is above zero.

    A slot already at zero needs no write, and staging one would spend a
    transaction action — and a version condition — on a row that cannot change.
    """
    return [row for row in event_slot_rows(show_and_sell_id) if int(row.get(ACTIVE_SIGNUP_COUNT_ATTRIBUTE) or 0) > 0]


# --- Conditional transaction actions ---------------------------------------------


def put_show_and_sell_action(item: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Create one event: the conditional insert IS the duplicate guard.

    ``attribute_not_exists`` on both key attributes means two concurrent creates of
    the same id cannot both land, and the loser gets a ``CONFLICT`` rather than an
    overwritten row.
    """
    return (
        "Put",
        {
            "TableName": tables.show_and_sells.table_name,
            "Item": wire_item(item),
            "ConditionExpression": "attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def wire_values(values: Mapping[str, Any]) -> Dict[str, Any]:
    """The ``ExpressionAttributeValues`` map, in the wire form the client expects."""
    return {name: wire_value(value) for name, value in values.items()}


def wire_item_value(value: Any) -> Dict[str, Any]:
    """One event-row attribute in wire form, total over the types §5.10 stores.

    :func:`src.utils.mutations.wire_value` is scalar-only, and ``productIds`` is a
    list: run through it, a product list becomes the string ``"[]"``, and every later
    read of the authoritative allocation locator is then refused as malformed. This
    is the same trap WORK-160 documented for ``lineItems``, and the same remedy: the
    module that stores a non-scalar attribute owns an encoder that is total over
    exactly what that row can hold — text, integer, boolean, null, a list of ids, and
    a map of ids to integers (``roundingDraftByProfileId`` and the assignment draft).
    """
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, (int, Decimal)):
        return {"N": str(value)}
    if value is None:
        return {"NULL": True}
    if isinstance(value, (list, tuple)):
        return {"L": [wire_item_value(entry) for entry in value]}
    if isinstance(value, Mapping):
        return {"M": {str(name): wire_item_value(entry) for name, entry in value.items()}}
    return {"S": str(value)}


def wire_item(item: Mapping[str, Any]) -> Dict[str, Any]:
    """A whole METADATA row in wire form."""
    return {name: wire_item_value(value) for name, value in item.items()}


_ALIAS_PATTERN = re.compile(r"#[A-Za-z0-9_]+")


def _register_aliases(names: Dict[str, str], expression: str) -> None:
    """Register every ``#alias`` an expression uses, so a guard cannot be malformed.

    DynamoDB rejects a write whose expression names an alias its
    ``ExpressionAttributeNames`` map lacks, and an in-memory plan cannot see that: it
    surfaces only at commit. Every alias in this module is spelled ``#<attribute>``, so
    the mapping is derivable from the expression, and deriving it lets a guard name an
    attribute the write does not itself set — the event's ``status`` in
    :func:`bump_event_version_action`, a slot's ``activeSignupCount`` in
    :func:`update_slot_action` — without a second list anyone can forget.
    """
    for token in _ALIAS_PATTERN.findall(expression):
        names.setdefault(token, token[1:])


def _conditioned_update(
    key: Mapping[str, str],
    table_name: str,
    *,
    expected_version: int,
    sets: Mapping[str, Any],
    extra_conditions: Sequence[Tuple[str, str, Any]] = (),
    version_attribute: str = VERSION_ATTRIBUTE,
) -> Tuple[str, Dict[str, Any]]:
    """One versioned update: ``version = expected`` plus the caller's extra guards.

    The version condition is what makes every Show & Sell race resolvable by the
    write itself — a stale read cancels the whole transaction instead of overwriting
    the writer that won.

    Args:
        key: The row's key pair.
        table_name: The table the row lives on.
        expected_version: The version the caller read.
        sets: Attribute name -> new value. The caller's ``version`` entry, when it
            supplies one, is the value the write produces.
        extra_conditions: ``(placeholder, expression, value)`` triples appended to
            the condition, each with its own value placeholder. Any ``#alias`` an
            expression uses is registered in the names map, whether or not the write
            also sets that attribute.
    """
    names: Dict[str, str] = {"#version": VERSION_ATTRIBUTE}
    values: Dict[str, Any] = {":expectedVersion": expected_version}
    set_parts: List[str] = []
    for attribute, value in sets.items():
        names[f"#{attribute}"] = attribute
        values[f":{attribute}"] = value
        set_parts.append(f"#{attribute} = :{attribute}")
    condition_parts: List[str] = ["#version = :expectedVersion"]
    for placeholder, expression, value in extra_conditions:
        _register_aliases(names, expression)
        values[placeholder] = value
        condition_parts.append(expression)
    return (
        "Update",
        {
            "TableName": table_name,
            "Key": wire_key(key),
            "UpdateExpression": "SET " + ", ".join(set_parts),
            "ConditionExpression": " AND ".join(condition_parts),
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": {name: wire_value(value) for name, value in values.items()},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def update_event_settings_action(
    *,
    show_and_sell_id: str,
    expected_version: int,
    changes: Mapping[str, Any],
    updated_by_account_id: str,
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """Write the writable fields and bump the event version in one conditioned update.

    ``changes`` arrives already filtered and validated by :func:`writable_changes`, so
    this action cannot be handed an immutable field even by accident.
    """
    sets: Dict[str, Any] = {
        **dict(changes),
        VERSION_ATTRIBUTE: expected_version + 1,
        UPDATED_BY_ATTRIBUTE: updated_by_account_id,
        UPDATED_AT_ATTRIBUTE: updated_at,
    }
    return _conditioned_update(
        event_metadata_key(show_and_sell_id),
        tables.show_and_sells.table_name,
        expected_version=expected_version,
        sets=sets,
    )


def cancel_event_action(
    *,
    show_and_sell_id: str,
    expected_version: int,
    cancelled_by_account_id: str,
    cancelled_at: str,
    reason: str,
) -> Tuple[str, Dict[str, Any]]:
    """Set the event ``CANCELLED`` with its audit, conditioned on the read version.

    The reason and the actor ride in the same write as the state, because §3.1.4 and
    3.7.4 require the audit to be part of the cancellation — a cancellation that
    committed and then lost its reason would be an untraceable state change.
    """
    sets: Dict[str, Any] = {
        STATUS_ATTRIBUTE: STATUS_CANCELLED,
        VERSION_ATTRIBUTE: expected_version + 1,
        UPDATED_BY_ATTRIBUTE: cancelled_by_account_id,
        UPDATED_AT_ATTRIBUTE: cancelled_at,
        CANCELLED_BY_ATTRIBUTE: cancelled_by_account_id,
        CANCELLED_AT_ATTRIBUTE: cancelled_at,
        CANCELLATION_REASON_ATTRIBUTE: reason,
    }
    return _conditioned_update(
        event_metadata_key(show_and_sell_id),
        tables.show_and_sells.table_name,
        expected_version=expected_version,
        sets=sets,
        # The state this request checked is part of the write, not just the version.
        # "Still SCHEDULED" is the precondition §3.1.4 states, so a row that some other
        # writer cancelled, finalized or reopened between this read and the commit
        # fails the condition instead of having its audit overwritten: a second
        # cancellation would otherwise replace the first one's reason and actor and move
        # the event to a third version, and an event that reached REOPENED or FINALIZED
        # is finished by finalization arithmetic, not by a release plan.
        extra_conditions=((":stateCondition", "#status = :stateCondition", STATUS_SCHEDULED),),
    )


def cancel_allocation_action(
    *,
    allocation: Mapping[str, Any],
    released_total: int,
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """Release an open allocation's whole remainder (§8.8 step 3).

    ``releasedTotal`` is the new cumulative total — the read row's ``releasedQty +
    remainingQty`` — and ``remainingQty`` becomes 0. Those are the numbers §8.8 names,
    taken from the row this transaction read, and the read row's ``version`` is the
    condition — so a concurrent allocation mutation that moved the remainder between
    the read and the commit cancels the whole plan rather than releasing an amount
    nobody agreed to.

    ``released_total`` is the caller's already-computed sum, so the arithmetic that
    decides how much stock goes back on the shelf has exactly one owner (the
    cancellation resolver) and the action here is only what it means in DynamoDB. The
    *cumulative* total belongs on this row and nowhere else: the movement beside it
    reports how much quantity this one request moved, which is a different number
    whenever the allocation was released before.
    """
    require_allocation_transition(allocation.get(STATUS_ATTRIBUTE), ALLOCATION_CANCELLED)
    return _conditioned_update(
        {"pk": str(allocation["pk"]), "sk": str(allocation["sk"])},
        tables.inventory.table_name,
        expected_version=normalize_required_version(allocation.get(VERSION_ATTRIBUTE, 1)),
        sets={
            VERSION_ATTRIBUTE: normalize_required_version(allocation.get(VERSION_ATTRIBUTE, 1)) + 1,
            RELEASED_QTY: released_total,
            REMAINING_QTY: 0,
            STATUS_ATTRIBUTE: ALLOCATION_CANCELLED,
            UPDATED_AT_ATTRIBUTE: updated_at,
        },
        # `CANCELLED` is the allocation's terminal state for a cancellation (§9.2) —
        # `RELEASED` belongs to finalization — and an allocation another path already
        # closed must not be re-released here.
        extra_conditions=((":closedCondition", "#status <> :closedCondition", ALLOCATION_CANCELLED),),
    )


def event_release_movement_action(
    *,
    event: Mapping[str, Any],
    allocation: Mapping[str, Any],
    released_qty: int,
    actor_account_id: str,
    occurred_at: str,
    idempotency_key: str,
) -> Tuple[str, Dict[str, Any]]:
    """The audit row that says an allocation's remainder went back on the shelf.

    §8.8 step 3 names the release movement alongside the allocation write, and the
    allocation write alone would leave the ledger unable to explain why a later
    ``assignedOpenQty`` dropped. The delta is negative (the assignment is going away)
    and is the only delta ``EVENT_RELEASE`` is allowed to move, so physical stock and
    custody stay untouched — a cancellation releases a reservation, it never moves a
    Kernel.

    ``released_qty`` here is the quantity *this* release moves — the allocation's
    remainder as read — not the row's new cumulative ``releasedQty``. A movement is a
    delta, and reporting the cumulative would double-count every earlier release of
    the same allocation in the balance the trail has to sum to.

    ``inventoryVersion`` is deliberately absent: SDL §5.8 makes it non-null only when
    an ``InventoryPosition`` moved, and a cancellation touches the allocation row and
    its own history, never the campaign balance. Stamping the allocation's version
    there would point an audit reader at a balance version that never happened.
    """
    item = inventory_models.build_inventory_movement_item(
        movement_id=inventory_models.new_inventory_movement_id(),
        unit_campaign_id=str(event[UNIT_CAMPAIGN_ID_ATTRIBUTE]),
        product_id=str(allocation[PRODUCT_ID_ATTRIBUTE]),
        movement_type=inventory_models.EVENT_RELEASE,
        actor_account_id=actor_account_id,
        occurred_at=occurred_at,
        idempotency_key=idempotency_key,
        assigned_delta=-abs(released_qty),
        show_and_sell_id=str(event[SHOW_AND_SELL_ID_ATTRIBUTE]),
    )
    return inventory_models.put_inventory_movement_action(item)


# --- Event stock assignment writes (checklist §3.2.3; spec ALLOC-01..08, §8.4) -----


def put_allocation_action(allocation: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Create the one allocation row a first assignment of a product to an event needs.

    The event is the single write owner of this row (§5.11 "The event write owner
    applies stock movement rules"), and the key is
    ``<campaign>#<productId>#<showAndSellId>`` — one row per (product, event). The
    ``attribute_not_exists`` guard is what makes that uniqueness real under a
    concurrent assignment of the same product to the same event: the loser's whole
    transaction is cancelled instead of overwriting a row that another admin's
    target had already produced.
    """
    return (
        "Put",
        {
            "TableName": tables.inventory.table_name,
            "Item": wire_item(allocation),
            "ConditionExpression": "attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def assignment_allocation_action(
    *,
    allocation: Mapping[str, Any],
    allocated_qty: int,
    remaining_qty: int,
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """Write one event's whole stock target for one product (§7 ALLOC-01, ALLOC-04).

    ``allocated_qty`` is the target the admin asked for, not a delta, and
    ``remaining_qty`` is that target minus the row's own sold and released quantities.
    Those two history quantities are read by this request and left untouched here, and the
    pair is computed by the planner rather than re-derived in the write, because
    ``remainingQty`` is stored for the reason §5.11 gives: every consumer of "what is
    still assigned" must see the same number. A target of 0 is therefore the release of
    the remaining allocation: 0 allocated, less what has already sold and been released,
    leaves nothing assigned.

    The status is deliberately not written. ``RELEASED`` and ``CANCELLED`` are the states
    a cancellation or a finalization produces (§9.2), and neither happened here; a manual
    reduction to zero is an allocation that now says "nothing", not a closed allocation,
    and EVT-M-04-02's "automatic reductions can be manually adjusted" is the workflow
    that needs the row to stay open for another target afterwards.

    The ``version`` pin is the §7 "event aggregate version" guard for this row, and the
    ``soldQty <= allocatedQty`` guard is the §5.11 invariant expressed in the database
    rather than only in the resolver: a read-modify-write that raced a sale would
    otherwise lower the target underneath quantity the event has already sold, and the
    ledger would stop reconciling. ``soldQty`` appears here as a bare attribute name
    because this write does not set it, so the placeholder map :func:`_conditioned_update`
    builds from the SET list does not name it — and it is not a DynamoDB reserved word.
    """
    current_version = normalize_required_version(allocation.get(VERSION_ATTRIBUTE, 1))
    return _conditioned_update(
        {"pk": str(allocation["pk"]), "sk": str(allocation["sk"])},
        tables.inventory.table_name,
        expected_version=current_version,
        sets={
            ALLOCATED_QTY: allocated_qty,
            REMAINING_QTY: remaining_qty,
            VERSION_ATTRIBUTE: current_version + 1,
            UPDATED_AT_ATTRIBUTE: updated_at,
        },
        extra_conditions=((":guardTarget", "soldQty <= :guardTarget", allocated_qty),),
    )


def event_assignment_movement_action(
    *,
    event: Mapping[str, Any],
    product_id: str,
    movement_type: str,
    assigned_delta: int,
    inventory_version: Optional[int] = None,
    actor_account_id: str,
    occurred_at: str,
    idempotency_key: str,
) -> Tuple[str, Dict[str, Any]]:
    """The audit row for one product's change of assigned quantity at one event.

    ``EVENT_ASSIGN`` and ``EVENT_MANUAL_REDUCE`` are the two movement types §4.3 names
    for an admin target going up and down, and both are allowed to move only
    ``assignedDelta`` — so physical stock and Scout custody are untouched by
    construction, which is what EVT-M-04's "physical stock never changes" claim rests on
    at the write layer, not only in the planner. ``showAndSellId`` is a required link for
    an event movement, so the trail says which event the stock was assigned to.

    ``inventory_version`` is the balance version this request produced. SDL §5.8 makes
    ``inventoryVersion`` non-null exactly when an ``InventoryPosition`` moved, and an
    assignment bumps that row's version without moving a quantity (the assigned total is
    derived from allocation rows, §7). A product the campaign has never received has no
    balance row to bump, so there is no version to name and the field stays absent.
    """
    item = inventory_models.build_inventory_movement_item(
        movement_id=inventory_models.new_inventory_movement_id(),
        unit_campaign_id=str(event[UNIT_CAMPAIGN_ID_ATTRIBUTE]),
        product_id=product_id,
        movement_type=movement_type,
        actor_account_id=actor_account_id,
        occurred_at=occurred_at,
        idempotency_key=idempotency_key,
        assigned_delta=assigned_delta,
        show_and_sell_id=str(event[SHOW_AND_SELL_ID_ATTRIBUTE]),
        inventory_version=inventory_version,
    )
    return inventory_models.put_inventory_movement_action(item)


def _assignment_event_update(
    show_and_sell_id: str,
    expected_version: int,
    sets: Mapping[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """One versioned event-row write whose values may be a list or a map.

    :func:`_conditioned_update` cannot carry this row's values: it encodes through
    :func:`src.utils.mutations.wire_value`, which is scalar-only, and ``productIds`` is
    a list (the same trap :func:`wire_item_value` exists for). Everything else about the
    write is the same as every other event write — the ``version`` pin is what makes the
    assignment lose a race against a cancellation or a second admin rather than overwrite
    it.

    No state condition: §3.5 allows an assignment in all four editable states, so the
    state that would refuse it is the one the resolver already refused, and the state a
    racing writer would move it to (``FINALIZED``, ``CANCELLED``) also moves ``version``.
    Adding a ``status <> CANCELLED`` style guard would allow ``FINALIZED`` through anyway
    while being a second, drift-prone statement of the state matrix.
    """
    values: Dict[str, Any] = {":expectedVersion": expected_version}
    names: Dict[str, str] = {"#version": VERSION_ATTRIBUTE}
    set_parts: List[str] = []
    for attribute, value in sets.items():
        names[f"#{attribute}"] = attribute
        values[f":{attribute}"] = value
        set_parts.append(f"#{attribute} = :{attribute}")
    return (
        "Update",
        {
            "TableName": tables.show_and_sells.table_name,
            "Key": wire_key(event_metadata_key(show_and_sell_id)),
            "UpdateExpression": "SET " + ", ".join(set_parts),
            "ConditionExpression": "#version = :expectedVersion",
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": {name: wire_item_value(value) for name, value in values.items()},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def assignment_event_action(
    *,
    show_and_sell_id: str,
    expected_version: int,
    product_ids: Sequence[str],
    updated_by_account_id: str,
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """Record the products this assignment made the event hold, and move the aggregate.

    ``productIds`` is written in the same transaction as the allocation rows it points at
    (§8.4): a list that lagged the rows would hide an allocation from the authoritative
    read finalization depends on. The list arrives already merged and de-duplicated from
    :func:`src.utils.allocation_models.planned_product_ids`, which is cumulative and
    uncapped — no product is ever removed.
    """
    return _assignment_event_update(
        show_and_sell_id,
        expected_version,
        {
            PRODUCT_IDS_ATTRIBUTE: list(product_ids),
            VERSION_ATTRIBUTE: expected_version + 1,
            UPDATED_BY_ATTRIBUTE: updated_by_account_id,
            UPDATED_AT_ATTRIBUTE: updated_at,
        },
    )


def assignment_draft_action(
    *,
    show_and_sell_id: str,
    expected_version: int,
    product_ids: Sequence[str],
    draft: Mapping[str, int],
    updated_by_account_id: str,
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """The ``REOPENED`` half of the mutation: draft targets and nothing else (§3.2.3).

    A reopened event's approved stock answer already exists — it is the finalization that
    was suspended — and §5.3.2/§8.6 say a reopened edit is an input that re-finalization
    validates and applies. So this write touches the event aggregate only: the draft map,
    the cumulative ``productIds`` (a product named now has to be findable by
    re-finalization's product walk, §8.6's "adds any newly referenced product to
    ``ShowAndSell.productIds``"), and ``version``. No allocation row, no movement, and no
    balance version moves, which is what "no immediate stock/allocation writes" means in
    the rows.
    """
    return _assignment_event_update(
        show_and_sell_id,
        expected_version,
        {
            PRODUCT_IDS_ATTRIBUTE: list(product_ids),
            ALLOCATION_DRAFT_ATTRIBUTE: dict(draft),
            VERSION_ATTRIBUTE: expected_version + 1,
            UPDATED_BY_ATTRIBUTE: updated_by_account_id,
            UPDATED_AT_ATTRIBUTE: updated_at,
        },
    )


def zero_slot_counter_action(
    *,
    show_and_sell_id: str,
    slot_id: str,
    expected_version: int,
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """Zero one slot's active-signup counter (§8.8 step 3).

    Conditioned on the version the reader saw: the counter is what §3.4's capacity
    check compares against, so a cancellation that raced a signup must not leave a
    slot counting a Scout whose signup this same transaction cancelled.
    """
    return _conditioned_update(
        slot_key(show_and_sell_id, slot_id),
        tables.show_and_sells.table_name,
        expected_version=expected_version,
        sets={
            ACTIVE_SIGNUP_COUNT_ATTRIBUTE: 0,
            VERSION_ATTRIBUTE: expected_version + 1,
            UPDATED_AT_ATTRIBUTE: updated_at,
        },
    )


def cancel_signup_action(
    *,
    show_and_sell_id: str,
    slot_id: str,
    profile_id: str,
    expected_version: int,
    new_version: int,
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """Cancel one signup record, keeping the row as history (§8.8, SSE-05).

    Cancellation never deletes the signup: §3.1.4 releases the commitment while the
    audit trail of who was signed up stays, and the same is true of sales and We Owe.

    The version moves with the state. §5.13 says a ``ScoutCommitment``'s version
    "matches source signup update", so a cancelled signup that kept its old version
    while its commitment advanced would leave the pair readable in two disagreeing
    versions — and §3.4's own cancellation conditions on the signup version, so it
    would be refusing a number no reader can reproduce.
    """
    return _conditioned_update(
        {"pk": show_and_sell_pk(show_and_sell_id), "sk": signup_sk(slot_id, profile_id)},
        tables.show_and_sells.table_name,
        expected_version=expected_version,
        sets={
            STATUS_ATTRIBUTE: SIGNUP_CANCELLED,
            VERSION_ATTRIBUTE: new_version,
            UPDATED_AT_ATTRIBUTE: updated_at,
        },
        # ``CANCELLED`` is terminal for a signup as it is for an allocation: the row is
        # history. The plan read only ACTIVE signups, so a Scout who cancelled her own
        # signup between that read and this commit makes the condition fail the whole
        # plan rather than let this request re-date a row it did not close.
        extra_conditions=((":cancelledCondition", "#status <> :cancelledCondition", SIGNUP_CANCELLED),),
    )


def require_signup_transition(current: Any, target: Any) -> None:
    """Require a signup/commitment state change to be one §5.13 and §9.3 allow.

    Signup and commitment share one transition table because the commitment is the
    signup's projection, not an independent record: ``ACTIVE -> CANCELLED`` is the only
    move, and ``CANCELLED`` is terminal. A projection that could be re-cancelled is a
    history row whose ``updatedAt`` and ``version`` move under a later request, which is
    exactly the audit trail SSE-05 keeps it for.
    """
    from_status = str(current or "")
    to_status = str(target or "")
    if from_status not in SIGNUP_TRANSITIONS or to_status not in SIGNUP_TRANSITIONS[from_status]:
        raise _invalid(STATUS_ATTRIBUTE, f"cannot move a signup or commitment from {from_status} to {to_status}")


def commitment_pk(profile_id: str) -> str:
    """Partition key holding one Scout's whole commitment history (§6.2).

    The commitment projection is partitioned by Scout, not by campaign, precisely so
    the cross-campaign overlap rule (SLOT-04) is one consistent query over the Scout
    rather than a scan across every Unit Campaign the Scout has ever joined.
    """
    return str(ensure_profile_id(profile_id))


def commitment_sk(start_at: str, unit_campaign_id: str, slot_id: str) -> str:
    """Sort key of one commitment: the interval first, so a range read answers overlap."""
    return f"{COMMITMENT_SK_PREFIX}#{start_at}#{unit_campaign_id}#{slot_id}"


def commitment_key(profile_id: str, start_at: str, unit_campaign_id: str, slot_id: str) -> Dict[str, str]:
    """The commitment row's key pair."""
    return {"pk": commitment_pk(profile_id), "sk": commitment_sk(start_at, unit_campaign_id, slot_id)}


def commitment_guard_key(profile_id: str) -> Dict[str, str]:
    """The Scout's commitment guard row (§5.13): one small version per Scout."""
    return {"pk": commitment_pk(profile_id), "sk": COMMITMENT_GUARD_SK}


def cancel_commitment_action(
    *,
    commitment: Mapping[str, Any],
    new_version: int,
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """Mark one ACTIVE commitment projection cancelled, conditioned on its read version.

    The commitment is what blocks a later overlapping signup, so leaving it ACTIVE
    after a cancellation would keep a Scout out of a slot she is no longer holding.
    Its version is written to the value its signup moves to, because §5.13 defines
    ``ScoutCommitment.version`` as matching the source signup's update; the write is
    still conditioned on the commitment's own read version, so a commitment that moved
    between read and commit fails the plan instead of overwriting the other writer.
    """
    require_signup_transition(commitment.get(STATUS_ATTRIBUTE), SIGNUP_CANCELLED)
    return _conditioned_update(
        {"pk": str(commitment["pk"]), "sk": str(commitment["sk"])},
        tables.unit_campaigns.table_name,
        expected_version=normalize_required_version(commitment.get(VERSION_ATTRIBUTE, 1)),
        sets={
            STATUS_ATTRIBUTE: SIGNUP_CANCELLED,
            VERSION_ATTRIBUTE: new_version,
            UPDATED_AT_ATTRIBUTE: updated_at,
        },
        # A commitment that is already cancelled is a history row (§5.13). The plan read
        # only ACTIVE commitments, so this condition is what catches one that another
        # request closed between the read and the commit — the §3.4 signup cancellation
        # releases the same projection — and fails the plan instead of re-dating it.
        extra_conditions=((":cancelledCondition", "#status <> :cancelledCondition", SIGNUP_CANCELLED),),
    )


def move_commitment_action(
    *,
    commitment: Mapping[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """Delete one commitment projection at the interval it was written under.

    A commitment's sort key IS its interval (§6.2), so moving a slot's time cannot update
    the interval in place — the row moves. :func:`put_commitment_action` writes the
    projection that replaces it at the new key as a second transaction action: two
    operations on one item are not allowed in a transaction, and the old and new keys are
    different rows, so the pair is one move.

    The version condition is what makes the move safe rather than destructive: a signup
    or cancellation that re-wrote this projection between the read and this commit moves
    its version, and this plan fails instead of deleting a row it never saw.
    """
    return (
        "Delete",
        {
            "TableName": tables.unit_campaigns.table_name,
            "Key": wire_key({"pk": str(commitment["pk"]), "sk": str(commitment["sk"])}),
            "ConditionExpression": "attribute_exists(#pk) AND #version = :expectedVersion",
            "ExpressionAttributeNames": {"#pk": "pk", "#version": VERSION_ATTRIBUTE},
            "ExpressionAttributeValues": wire_values(
                {":expectedVersion": normalize_required_version(commitment.get(VERSION_ATTRIBUTE, 1))}
            ),
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def put_commitment_action(*, item: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Insert one commitment projection at the interval it now describes.

    ``attribute_not_exists`` on both key attributes is the collision guard: a projection
    already living at the new key belongs to another signup this request never read, and
    overwriting it would answer an overlap question later with a row this write destroyed.
    """
    return (
        "Put",
        {
            "TableName": tables.unit_campaigns.table_name,
            "Item": wire_item(item),
            "ConditionExpression": "attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def bump_commitment_guard_action(
    *,
    profile_id: str,
    updated_at: str,
    expected_commitment_version: Optional[int] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Advance one Scout's commitment guard, incrementing it in the write itself.

    The guard is the serialization point for every commitment change across all of a
    Scout's memberships (§5.13), which is how a cancellation and a concurrent signup
    in a different Unit Campaign settle: whichever writes second finds the guard it
    read has moved, and its own plan cancels rather than resurrecting a commitment.

    ``commitmentVersion`` is incremented by DynamoDB rather than written from a read
    value. Two writers that both read the guard and then wrote ``read + 1`` would
    land on the same number and both believe they serialized; ``+ :one`` makes the
    increment itself the lock.

    ``expected_commitment_version`` is the version the caller validated its plan
    against, and it turns the bump into a compare-and-set. An increment that only
    requires the guard to EXIST serializes nothing: two slot moves on two different
    events each re-validate one Scout's commitments against what that Scout's board
    looked like when it read, each bump succeeds, and the Scout ends up with two
    overlapping commitments at two different Show & Sells — the injury AC-14 forbids,
    and no event-version condition can see it because the two plans touch two
    different events. Pinning the version means the second writer's condition fails
    and its whole plan rolls back. A caller that never read the guard — the
    cancellation in §3.1, whose plan is already serialized by the event version and
    which releases only that event's own commitments — leaves it ``None`` and keeps
    the existence condition.
    """
    if expected_commitment_version is None:
        condition = "attribute_exists(#pk) AND attribute_exists(#commitmentVersion)"
        values: Dict[str, Any] = {":one": 1, ":updatedAt": updated_at}
    else:
        condition = "attribute_exists(#pk) AND #commitmentVersion = :expectedCommitmentVersion"
        values = {
            ":one": 1,
            ":updatedAt": updated_at,
            ":expectedCommitmentVersion": normalize_required_version(expected_commitment_version),
        }
    return (
        "Update",
        {
            "TableName": tables.unit_campaigns.table_name,
            "Key": wire_key(commitment_guard_key(profile_id)),
            "UpdateExpression": "SET #commitmentVersion = #commitmentVersion + :one, #updatedAt = :updatedAt",
            "ConditionExpression": condition,
            "ExpressionAttributeNames": {
                "#commitmentVersion": "commitmentVersion",
                "#updatedAt": UPDATED_AT_ATTRIBUTE,
                "#pk": "pk",
            },
            "ExpressionAttributeValues": wire_values(values),
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


# --- Slots and commitments (data model §5.12–§5.13, checklist §3.3) --------------

# §3.3 owns three row shapes at once: the slot it writes, and the signup/commitment
# pair whose storage contract the slot's writes reason about — the slot's
# ``activeSignupCount`` counts the signup rows, the slot update revalidates them,
# and the slot delete refuses on them. The commitment projection is the row §3.4's
# signup will later write; it is declared here because the cross-campaign overlap
# rule (SLOT-04) that a slot move must respect is decided against exactly this row,
# so the interval rule and the row shape have one owner rather than two.


def slot_bounds_violations(event: Mapping[str, Any], start_at: str, end_at: str) -> List[str]:
    """Whether a slot interval fits inside the event's immutable interval.

    §5.12's bound is ``event.startAt <= slot.startAt < slot.endAt <= event.endAt``:
    a slot may start the moment the event starts and end the moment it ends, but
    not a second outside. ``endAt > startAt`` itself is already enforced by
    :func:`normalize_interval`, so only the two outer bounds live here.
    """
    problems: List[str] = []
    event_start = str(event.get(START_AT_ATTRIBUTE) or "")
    event_end = str(event.get(END_AT_ATTRIBUTE) or "")
    if event_start and start_at < event_start:
        problems.append("the slot starts before the event starts")
    if event_end and end_at > event_end:
        problems.append("the slot ends after the event ends")
    return problems


def build_show_and_sell_slot_item(
    *,
    event: Mapping[str, Any],
    slot_id: Any,
    start_at: Any,
    end_at: Any,
    capacity: Any,
    now_iso: Any,
    label: Any = None,
    active_signup_count: Any = 0,
    version: Any = 1,
) -> Dict[str, Any]:
    """The §5.12 slot row, validated on the way in.

    ``event`` is the event row, not an id: the interval bound is only decidable
    against the interval itself, and reading the event is the resolver's one
    consistent read — passing the row through keeps the bound and the version
    condition about the same event. ``active_signup_count`` and ``version`` carry
    create-time defaults because a create cannot produce either: the counter starts
    at zero because nobody has signed up yet, and §3.3 offers no input that could
    change either one.
    """
    event_id = normalize_event_id(event.get(SHOW_AND_SELL_ID_ATTRIBUTE))
    sid = normalize_slot_id(slot_id)
    start, end = normalize_interval(start_at, end_at)
    stamp = normalize_moment(now_iso, UPDATED_AT_ATTRIBUTE)
    item: Dict[str, Any] = {
        "pk": show_and_sell_pk(event_id),
        "sk": slot_sk(sid),
        "entityType": ENTITY_TYPE_SLOT,
        SHOW_AND_SELL_ID_ATTRIBUTE: event_id,
        SLOT_ID_ATTRIBUTE: sid,
        LABEL_ATTRIBUTE: normalize_label(label),
        START_AT_ATTRIBUTE: start,
        END_AT_ATTRIBUTE: end,
        CAPACITY_ATTRIBUTE: normalize_capacity(capacity),
        ACTIVE_SIGNUP_COUNT_ATTRIBUTE: normalize_active_count(active_signup_count),
        VERSION_ATTRIBUTE: normalize_required_version(version),
        CREATED_AT_ATTRIBUTE: stamp,
        UPDATED_AT_ATTRIBUTE: stamp,
    }
    violations = slot_invariant_violations(item, event)
    if violations:
        raise _invalid(SLOT_ID_ATTRIBUTE, f"would break the slot invariants: {'; '.join(violations)}")
    return item


def _entity_row_shape_violations(item: Mapping[str, Any], entity_type: str, declared: AbstractSet[str]) -> List[str]:
    """Row shape for any Show & Sell row: the entity tag, and only declared attributes.

    The three §3.3 rows share this rule and differ only in which tag and which set,
    so it is one function: an attribute outside the declared set is a fact no write
    in this feature produces, and a missing one is a row a later read would have to
    guess at.
    """
    problems: List[str] = []
    if str(item.get("entityType") or "") != entity_type:
        problems.append(f"entityType is not {entity_type}")
    extra = set(item) - declared
    if extra:
        problems.append(f"attributes the model leaves out: {', '.join(sorted(extra))}")
    missing = declared - set(item)
    if missing:
        problems.append(f"missing attributes: {', '.join(sorted(missing))}")
    return problems


def _is_count(value: Any) -> TypeGuard[int | Decimal]:
    """A Dynamo number, and not a boolean wearing one."""
    return not isinstance(value, bool) and isinstance(value, (int, Decimal))


def _counter_violations(item: Mapping[str, Any], attribute: str) -> List[str]:
    """A counter that must never go negative: ``activeSignupCount``, ``actualMinutes``."""
    value = item.get(attribute)
    if not _is_count(value):
        return [f"{attribute} must be an integer"]
    if int(value) < 0:
        return [f"{attribute} must not be negative"]
    return []


def _capacity_violations(item: Mapping[str, Any]) -> List[str]:
    """Capacity is 1–100 (§5.12): no slot that cannot hold anyone, none a Unit cannot run."""
    capacity = item.get(CAPACITY_ATTRIBUTE)
    if not _is_count(capacity):
        return ["capacity must be an integer"]
    if not MIN_SLOT_CAPACITY <= int(capacity) <= MAX_SLOT_CAPACITY:
        return [f"capacity must be between {MIN_SLOT_CAPACITY} and {MAX_SLOT_CAPACITY}"]
    return []


def _counter_within_capacity_violations(item: Mapping[str, Any]) -> List[str]:
    """The counter cannot exceed the capacity stored beside it (§5.12).

    Only comparable when both sides are numbers: a row whose capacity is a string is
    already reported by :func:`_capacity_violations`, and this would report a second
    breach about a value that cannot be compared.
    """
    count = item.get(ACTIVE_SIGNUP_COUNT_ATTRIBUTE)
    capacity = item.get(CAPACITY_ATTRIBUTE)
    if _is_count(count) and _is_count(capacity) and int(count) > int(capacity):
        return ["activeSignupCount exceeds capacity"]
    return []


def slot_invariant_violations(item: Mapping[str, Any], event: Optional[Mapping[str, Any]] = None) -> List[str]:
    """Every §5.12 invariant one slot row can break, as plain-language breaches.

    Same style as :func:`event_invariant_violations`: the builder runs it before a
    write, and a reader that finds a row violating it is looking at a broken
    aggregate rather than something to repair on read. ``event`` is optional
    because the bound check needs the interval while the row-shape and counter
    checks stand alone.
    """
    problems = _entity_row_shape_violations(item, ENTITY_TYPE_SLOT, SLOT_ROW_ATTRIBUTES)
    problems += _interval_violations(item) + _capacity_violations(item)
    problems += _counter_violations(item, ACTIVE_SIGNUP_COUNT_ATTRIBUTE)
    problems += _counter_within_capacity_violations(item)
    if event is None:
        return problems
    start = str(item.get(START_AT_ATTRIBUTE) or "")
    end = str(item.get(END_AT_ATTRIBUTE) or "")
    if start and end:
        problems += slot_bounds_violations(event, start, end)
    return problems


def normalize_signup_status(value: Any, field: str = STATUS_ATTRIBUTE) -> str:
    """Validate a signup/commitment state against §9.3's two-state vocabulary."""
    text = normalize_required_text(value, field, 32).upper()
    if text not in {SIGNUP_ACTIVE, SIGNUP_CANCELLED}:
        raise _invalid(field, f"must be one of {SIGNUP_ACTIVE}, {SIGNUP_CANCELLED}")
    return text


def build_show_and_sell_signup_item(
    *,
    event: Mapping[str, Any],
    slot_id: Any,
    profile_id: Any,
    campaign_id: Any,
    signed_up_by_account_id: Any,
    now_iso: Any,
    status: Any = SIGNUP_ACTIVE,
    actual_minutes: Any = 0,
    confirmed_by_account_id: Any = None,
    confirmed_at: Any = None,
    version: Any = 1,
) -> Dict[str, Any]:
    """The §5.13 signup row.

    §3.4 writes this row; §3.3 declares it because the slot contract depends on it
    — the counter counts ACTIVE rows of exactly this shape, the update revalidation
    reads them, and the delete refuses while any of them exists. ``unitCampaignId``
    and ``campaignId`` come off the event and the caller: the first is the roster
    and credit scope the event already belongs to, the second is the Scout's own
    Scout Campaign, which §5.13 keeps because credit and Orders retain their
    originating scope after a roster move. The confirmation audit is a build
    argument rather than a post-build patch so §3.4.3 can re-emit a confirmed row
    (a replay of a confirmed signup rewrites the whole row) — and :func:`
    signup_invariant_violations` is what catches the half-written audit that makes.
    """
    event_id = normalize_event_id(event.get(SHOW_AND_SELL_ID_ATTRIBUTE))
    sid = normalize_slot_id(slot_id)
    stamp = normalize_moment(now_iso, UPDATED_AT_ATTRIBUTE)
    item: Dict[str, Any] = {
        "pk": show_and_sell_pk(event_id),
        "sk": signup_sk(sid, normalize_event_id(profile_id, PROFILE_ID_ATTRIBUTE)),
        "entityType": ENTITY_TYPE_SIGNUP,
        SHOW_AND_SELL_ID_ATTRIBUTE: event_id,
        SLOT_ID_ATTRIBUTE: sid,
        PROFILE_ID_ATTRIBUTE: normalize_event_id(profile_id, PROFILE_ID_ATTRIBUTE),
        UNIT_CAMPAIGN_ID_ATTRIBUTE: normalize_event_id(
            event.get(UNIT_CAMPAIGN_ID_ATTRIBUTE), UNIT_CAMPAIGN_ID_ATTRIBUTE
        ),
        CAMPAIGN_ID_ATTRIBUTE: normalize_event_id(campaign_id, CAMPAIGN_ID_ATTRIBUTE),
        STATUS_ATTRIBUTE: normalize_signup_status(status),
        ACTUAL_MINUTES_ATTRIBUTE: normalize_actual_minutes(actual_minutes),
        SIGNED_UP_BY_ATTRIBUTE: normalize_event_id(signed_up_by_account_id, SIGNED_UP_BY_ATTRIBUTE),
        CONFIRMED_BY_ATTRIBUTE: (
            None
            if confirmed_by_account_id is None
            else normalize_event_id(confirmed_by_account_id, CONFIRMED_BY_ATTRIBUTE)
        ),
        CONFIRMED_AT_ATTRIBUTE: None
        if confirmed_at is None
        else normalize_moment(confirmed_at, CONFIRMED_AT_ATTRIBUTE),
        VERSION_ATTRIBUTE: normalize_required_version(version),
        CREATED_AT_ATTRIBUTE: stamp,
        UPDATED_AT_ATTRIBUTE: stamp,
    }
    violations = signup_invariant_violations(item)
    if violations:
        raise _invalid(SLOT_ID_ATTRIBUTE, f"would break the signup invariants: {'; '.join(violations)}")
    return item


def _signup_status_violations(item: Mapping[str, Any]) -> List[str]:
    """The signup and its commitment projection share §9.3's two-state vocabulary."""
    if str(item.get(STATUS_ATTRIBUTE) or "") in {SIGNUP_ACTIVE, SIGNUP_CANCELLED}:
        return []
    return [f"status is not one of {SIGNUP_ACTIVE}, {SIGNUP_CANCELLED}"]


def signup_invariant_violations(item: Mapping[str, Any]) -> List[str]:
    """The §5.13 signup invariants: vocabulary, floor, and confirmation audit.

    "At most one ACTIVE signup per ``(slotId, profileId)``" needs no check here:
    the signup's sort key IS that pair, so the second active signup for one Scout
    in one slot would be the same row. What this function catches is the rest —
    minutes below zero, a state outside the vocabulary, and a confirmation that
    names no confirmer (an audit trail that says work was confirmed but not by whom
    is the trail §3.4.3 exists to prevent).
    """
    problems = _entity_row_shape_violations(item, ENTITY_TYPE_SIGNUP, SIGNUP_ROW_ATTRIBUTES)
    problems += _signup_status_violations(item) + _counter_violations(item, ACTUAL_MINUTES_ATTRIBUTE)
    if item.get(CONFIRMED_AT_ATTRIBUTE) is not None and not item.get(CONFIRMED_BY_ATTRIBUTE):
        problems.append("confirmed work requires confirmedByAccountId")
    return problems


def build_scout_commitment_item(
    *,
    profile_id: Any,
    unit_campaign_id: Any,
    show_and_sell_id: Any,
    slot_id: Any,
    start_at: Any,
    end_at: Any,
    now_iso: Any,
    version: Any,
    status: Any = SIGNUP_ACTIVE,
) -> Dict[str, Any]:
    """The §5.13 cross-campaign commitment projection.

    The interval rides denormalized (as it does on the allocation row, §5.11)
    because the commitment IS the interval — the authoritative answer to "is this
    Scout already somewhere else at that time" is one consistent query over the
    Scout's partition sorted by ``startAt``, and a reader that had to join back to
    each slot row could not run it. ``version`` is supplied, never defaulted:
    §5.13 defines the projection's version as matching the source signup's, so the
    caller that writes the signup passes the number the signup row moves to.
    """
    start, end = normalize_interval(start_at, end_at)
    stamp = normalize_moment(now_iso, UPDATED_AT_ATTRIBUTE)
    sid = normalize_slot_id(slot_id)
    profile = normalize_event_id(profile_id, PROFILE_ID_ATTRIBUTE)
    item: Dict[str, Any] = {
        "pk": commitment_pk(profile),
        "sk": commitment_sk(start, normalize_event_id(unit_campaign_id, UNIT_CAMPAIGN_ID_ATTRIBUTE), sid),
        "entityType": ENTITY_TYPE_COMMITMENT,
        PROFILE_ID_ATTRIBUTE: profile,
        UNIT_CAMPAIGN_ID_ATTRIBUTE: normalize_event_id(unit_campaign_id, UNIT_CAMPAIGN_ID_ATTRIBUTE),
        COMMITMENT_ID_ATTRIBUTE: signup_sk(sid, profile),
        SHOW_AND_SELL_ID_ATTRIBUTE: normalize_event_id(show_and_sell_id),
        SLOT_ID_ATTRIBUTE: sid,
        START_AT_ATTRIBUTE: start,
        END_AT_ATTRIBUTE: end,
        STATUS_ATTRIBUTE: normalize_signup_status(status),
        VERSION_ATTRIBUTE: normalize_required_version(version),
        CREATED_AT_ATTRIBUTE: stamp,
        UPDATED_AT_ATTRIBUTE: stamp,
    }
    # No builder-side invariant pass: every field above is normalized on the way in
    # and the identity is computed rather than supplied, so no build argument can
    # produce a violating row. :func:`commitment_invariant_violations` is the
    # read-side oracle instead — it is what proves a STORED projection still agrees
    # with its source, and §3.3's slot revalidation runs it over the rows it reads.
    return item


def commitment_invariant_violations(item: Mapping[str, Any]) -> List[str]:
    """The §5.13 commitment invariants: the projection agrees with its source.

    A commitment whose ``status`` is outside the signup vocabulary or whose interval
    is inverted would answer the overlap question wrongly for every future signup,
    and an attribute outside the declared set is a fact no signup write produces.
    """
    return (
        _entity_row_shape_violations(item, ENTITY_TYPE_COMMITMENT, COMMITMENT_ROW_ATTRIBUTES)
        + _interval_violations(item)
        + _signup_status_violations(item)
    )


def build_commitment_guard_item(*, profile_id: Any, commitment_version: Any, now_iso: Any) -> Dict[str, Any]:
    """The one-row-per-Scout commitment guard (§5.13).

    Written by the first signup (§3.4), read by every commitment change — and
    declared here because §3.3's slot update reads the commitment partition it
    serializes. ``commitmentVersion`` is required, never defaulted: a guard whose
    version nobody chose is a lock that says nothing about which change it
    witnessed.
    """
    stamp = normalize_moment(now_iso, UPDATED_AT_ATTRIBUTE)
    profile = normalize_event_id(profile_id, PROFILE_ID_ATTRIBUTE)
    return {
        "pk": commitment_pk(profile),
        "sk": COMMITMENT_GUARD_SK,
        "entityType": ENTITY_TYPE_COMMITMENT_GUARD,
        PROFILE_ID_ATTRIBUTE: profile,
        COMMITMENT_VERSION_ATTRIBUTE: normalize_required_version(commitment_version, COMMITMENT_VERSION_ATTRIBUTE),
        UPDATED_AT_ATTRIBUTE: stamp,
    }


def put_slot_action(item: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Create one slot: the conditional insert is also the slot-count race guard.

    Two concurrent 20→21 creations both count 20 slots in their read, but the
    event-version condition on the aggregate bump that rides every slot write
    commits one and fails the other — the insert condition just keeps a second
    create of one slot id from overwriting the first.
    """
    return (
        "Put",
        {
            "TableName": tables.show_and_sells.table_name,
            "Item": wire_item(item),
            "ConditionExpression": "attribute_not_exists(#pk) AND attribute_not_exists(#sk)",
            "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def update_slot_action(
    *,
    show_and_sell_id: str,
    slot_id: str,
    expected_version: int,
    label: Optional[str],
    start_at: str,
    end_at: str,
    capacity: int,
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """Rewrite one slot's writable fields under its version plus a capacity floor.

    An upsert writes the whole slot as offered — label, interval, capacity — because
    that is what an edit screen submits, and it is what makes the fingerprint
    honest: two requests that offer different slots are different requests. The
    ``activeSignupCount <= :capacity`` condition is §5.12's shrink rule expressed on
    the write itself: the resolver refuses a capacity below the count it read, and
    this catches the case where a signup moved the counter between that read and
    this commit without any other writer touching the version the caller sent.
    """
    return _conditioned_update(
        slot_key(show_and_sell_id, slot_id),
        tables.show_and_sells.table_name,
        expected_version=expected_version,
        sets={
            LABEL_ATTRIBUTE: label,
            START_AT_ATTRIBUTE: start_at,
            END_AT_ATTRIBUTE: end_at,
            CAPACITY_ATTRIBUTE: capacity,
            VERSION_ATTRIBUTE: expected_version + 1,
            UPDATED_AT_ATTRIBUTE: updated_at,
        },
        extra_conditions=((":roomCondition", "#activeSignupCount <= :roomCondition", capacity),),
    )


def delete_slot_action(
    *,
    show_and_sell_id: str,
    slot_id: str,
    expected_version: int,
) -> Tuple[str, Dict[str, Any]]:
    """Delete one slot only while it holds nobody and has not moved since the read.

    Three guards in one write, and each catches a different race:
    ``attribute_exists`` is the wrong-parent guard — with the parent in the key, a
    slot id from another event simply has no row here; ``#version`` is the row the
    resolver read, so any signup that touched the slot between read and commit
    moves it; and ``#activeSignupCount = :zero`` is §3.3.3's promise that a
    deletion never silently drops a participant, enforced on the row rather than
    only against the read the resolver made.
    """
    return (
        "Delete",
        {
            "TableName": tables.show_and_sells.table_name,
            "Key": wire_key(slot_key(show_and_sell_id, slot_id)),
            "ConditionExpression": (
                "attribute_exists(#pk) AND #version = :expectedVersion AND #activeSignupCount = :zeroCondition"
            ),
            "ExpressionAttributeNames": {
                "#pk": "pk",
                "#version": VERSION_ATTRIBUTE,
                "#activeSignupCount": ACTIVE_SIGNUP_COUNT_ATTRIBUTE,
            },
            "ExpressionAttributeValues": wire_values({":expectedVersion": expected_version, ":zeroCondition": 0}),
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


def bump_event_version_action(
    *,
    show_and_sell_id: str,
    expected_version: int,
    updated_by_account_id: str,
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """Move the event version because its slot board just moved.

    §8.3's rule for participant-side changes — "an incremented event version
    prevents finalization from approving a stale participant/sale set" — applies to
    the slot rows that define what a signup could have been for: finalization must
    not approve a work set measured against slots that changed under it. The
    version condition makes every concurrent slot write settle against one
    serialization point, and the stored-state condition is §3.3's SCHEDULED
    requirement re-checked at commit: an event that was cancelled, started into a
    terminal workflow, finalized, or reopened between this read and this write
    fails the plan instead of having its slot board edited behind the workflow.
    """
    return _conditioned_update(
        event_metadata_key(show_and_sell_id),
        tables.show_and_sells.table_name,
        expected_version=expected_version,
        sets={
            VERSION_ATTRIBUTE: expected_version + 1,
            UPDATED_BY_ATTRIBUTE: updated_by_account_id,
            UPDATED_AT_ATTRIBUTE: updated_at,
        },
        extra_conditions=((":stateCondition", "#status = :stateCondition", STATUS_SCHEDULED),),
    )


def active_slot_signups(signups: Sequence[Mapping[str, Any]], slot_id: str) -> List[Mapping[str, Any]]:
    """The ACTIVE signups holding one slot — the rows a slot edit must keep legal.

    The rows, not the slot's ``activeSignupCount``: the counter is a projection kept for
    the board's arithmetic, and a §3.3 guard decided on it would be decided on the copy.
    """
    return [
        signup
        for signup in signups
        if str(signup.get(SLOT_ID_ATTRIBUTE) or "") == slot_id
        and str(signup.get(STATUS_ATTRIBUTE) or "") == SIGNUP_ACTIVE
    ]


def active_signup_profiles(signups: Sequence[Mapping[str, Any]], slot_id: str) -> List[str]:
    """The Scouts holding an ACTIVE signup in one slot, in the order a plan stages them.

    Sorted, not insertion-ordered: a slot write commits one commitment per Scout, and two
    requests that stage the same Scout set in different orders would take the guards in
    different orders and could deadlock on each other.
    """
    return sorted({str(signup.get(PROFILE_ID_ATTRIBUTE) or "") for signup in active_slot_signups(signups, slot_id)})


def active_commitment_for(
    commitments: Sequence[Mapping[str, Any]], show_and_sell_id: str, slot_id: str
) -> Optional[Dict[str, Any]]:
    """One Scout's ACTIVE projection for one slot of one event, when the aggregate holds one.

    The ``(showAndSellId, slotId)`` pair is the row's identity, not its key: the sort key is
    the interval (§6.2), so a slot that has been re-timed already carries its projection under
    a different key, and only these two attributes say which slot the row describes.
    """
    for row in commitments:
        if (
            str(row.get(STATUS_ATTRIBUTE) or "") == SIGNUP_ACTIVE
            and str(row.get(SHOW_AND_SELL_ID_ATTRIBUTE) or "") == show_and_sell_id
            and str(row.get(SLOT_ID_ATTRIBUTE) or "") == slot_id
        ):
            return dict(row)
    return None


def slot_commitment_state(
    *,
    show_and_sell_id: str,
    slot_id: str,
    signups: Sequence[Mapping[str, Any]],
    commitments_by_profile: Mapping[str, Sequence[Mapping[str, Any]]],
) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[str]]:
    """``(pairs, violations)`` for the Scouts holding this slot: each one with their projection, and the ones missing it.

    A signup and its projection are one aggregate written by one transaction (§5.13), so an
    ACTIVE signup with no ACTIVE projection is not a state a slot edit may build on. Moving
    such a slot would commit a row at a new interval with nothing at that interval to block
    the next overlapping signup — the Scout could then be signed up twice at the same hour,
    which is exactly what AC-14 says cannot happen. Leaving the slot where it is does not
    repair the aggregate either, so this refuses rather than picking a side: the violation is
    reported, and §3.7's validation owns the repair.
    """
    pairs: List[Tuple[str, Dict[str, Any]]] = []
    violations: List[str] = []
    for profile_id in active_signup_profiles(signups, slot_id):
        projection = active_commitment_for(commitments_by_profile.get(profile_id, ()), show_and_sell_id, slot_id)
        if projection is None:
            violations.append(f"Scout {profile_id} holds a signup on this slot with no ACTIVE commitment row")
        else:
            pairs.append((profile_id, projection))
    return pairs, violations


def _overlapped_sibling_slot(
    *,
    signups: Sequence[Mapping[str, Any]],
    slot_by_id: Mapping[str, Mapping[str, Any]],
    profile_id: str,
    slot_id: str,
    start_at: str,
    end_at: str,
) -> Optional[str]:
    """The first OTHER slot in this event the Scout holds that the new time would overlap.

    A Scout signed up for two slots of the same Show & Sell has two rows and two slot
    rows; moving one of them onto the other is the same breach as moving it onto
    another Show & Sell, and the sibling is the nearer evidence, so it is named first.
    A signup pointing at a slot row this event does not hold is broken on its own and
    is not evidence about this interval.
    """
    for signup in signups:
        sibling_id = str(signup.get(SLOT_ID_ATTRIBUTE) or "")
        sibling = slot_by_id.get(sibling_id)
        if (
            sibling_id != slot_id
            and str(signup.get(PROFILE_ID_ATTRIBUTE) or "") == profile_id
            and str(signup.get(STATUS_ATTRIBUTE) or "") == SIGNUP_ACTIVE
            and sibling is not None
            and intervals_overlap(start_at, end_at, str(sibling[START_AT_ATTRIBUTE]), str(sibling[END_AT_ATTRIBUTE]))
        ):
            return sibling_id
    return None


def _overlapped_commitment(
    *,
    commitments: Sequence[Mapping[str, Any]],
    show_and_sell_id: str,
    slot_id: str,
    start_at: str,
    end_at: str,
) -> Optional[Mapping[str, Any]]:
    """The Scout's first ACTIVE commitment the new time would overlap, other than this slot's.

    The commitment projection is the row §3.4's signup consults, so the cross-campaign
    answer a slot move gets is the answer a later signup would get (SLOT-04). This
    slot's own projection is excluded: the Scout holding this slot necessarily has a
    commitment running when this slot runs, and the move is not allowed to fail
    against the very row that proves she is in it.
    """
    for commitment in commitments:
        if str(commitment.get(STATUS_ATTRIBUTE) or "") != SIGNUP_ACTIVE:
            continue
        same_slot = (
            str(commitment.get(SHOW_AND_SELL_ID_ATTRIBUTE) or "") == show_and_sell_id
            and str(commitment.get(SLOT_ID_ATTRIBUTE) or "") == slot_id
        )
        if not same_slot and intervals_overlap(
            start_at, end_at, str(commitment[START_AT_ATTRIBUTE]), str(commitment[END_AT_ATTRIBUTE])
        ):
            return commitment
    return None


def slot_revalidation_violations(
    *,
    show_and_sell_id: str,
    slot_id: str,
    start_at: str,
    end_at: str,
    capacity: int,
    slots: Sequence[Mapping[str, Any]],
    signups: Sequence[Mapping[str, Any]],
    commitments_by_profile: Mapping[str, Sequence[Mapping[str, Any]]],
) -> List[str]:
    """What an existing-signup revalidation (§3.3.2) would break, as plain sentences.

    A slot edit is legal only while every Scout already signed up for it stays
    legal. Two rules decide that, and each reads the row the later blocker reads:

    - **Capacity floor.** The new capacity cannot be below the ACTIVE signups the
      slot already holds (§5.12). Freeing Scouts is the signup cancellation's job
      (§3.4), never a side effect of a keyboard slip in the capacity box.
    - **No newly-conflicting time.** A Scout signed up for this slot already holds
      a commitment running when this slot runs. Moving the slot may not put that
      commitment — or any other the Scout holds, including one at a different Show
      & Sell, in a different Unit Campaign (SLOT-04) — into overlap with the new
      interval. Adjacency stays legal (:func:`intervals_overlap` never overlaps
      touching ends, SLOT-03).
    """
    problems: List[str] = []
    holding = active_slot_signups(signups, slot_id)
    if len(holding) > capacity:
        problems.append(f"the slot already holds {len(holding)} active signup(s); the capacity cannot drop below that")
    slot_by_id = {str(slot.get(SLOT_ID_ATTRIBUTE) or ""): slot for slot in slots}
    for profile_id in sorted({str(signup.get(PROFILE_ID_ATTRIBUTE) or "") for signup in holding}):
        sibling = _overlapped_sibling_slot(
            signups=signups,
            slot_by_id=slot_by_id,
            profile_id=profile_id,
            slot_id=slot_id,
            start_at=start_at,
            end_at=end_at,
        )
        if sibling is not None:
            problems.append(
                f"the new time would overlap slot {sibling}, which Scout {profile_id} is already signed up for"
            )
            continue
        other = _overlapped_commitment(
            commitments=commitments_by_profile.get(profile_id, ()),
            show_and_sell_id=show_and_sell_id,
            slot_id=slot_id,
            start_at=start_at,
            end_at=end_at,
        )
        if other is not None:
            problems.append(
                "the new time would overlap "
                f"Scout {profile_id}'s commitment at show & sell {other.get(SHOW_AND_SELL_ID_ATTRIBUTE)}"
            )
    return problems


def slot_counter_reconciliation(show_and_sell_id: str) -> List[Tuple[str, int, int]]:
    """``(slotId, stored, expected)`` for every slot whose counter disagrees with its signups.

    ``activeSignupCount`` is maintained transactionally (§5.12), so a disagreement
    is not drift to absorb — it is proof that a write escaped the aggregate's one
    serialization point. The event's own partitions are the authority for both
    sides, read consistently, so this answers the question without touching an
    index, and §3.7's validation runs it as an oracle after every signup-shaped
    mutation.
    """
    expected: Dict[str, int] = {}
    for signup in active_signups(show_and_sell_id):
        slot_id = str(signup.get(SLOT_ID_ATTRIBUTE) or "")
        expected[slot_id] = expected.get(slot_id, 0) + 1
    mismatches: List[Tuple[str, int, int]] = []
    for slot in event_slot_rows(show_and_sell_id):
        slot_id = str(slot.get(SLOT_ID_ATTRIBUTE) or "")
        stored = int(slot.get(ACTIVE_SIGNUP_COUNT_ATTRIBUTE) or 0)
        want = expected.get(slot_id, 0)
        if stored != want:
            mismatches.append((slot_id, stored, want))
    return mismatches


# --- Output projections (API contract §3.2, SEC-04) ------------------------------


def event_admin_payload(item: Mapping[str, Any], now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Project an event row onto the administrative ``ShowAndSellAdmin`` shape.

    ``status`` is the derived state, never the stored one: an admin scheduling a
    cancellation has to see ``ACTIVE`` for an event whose row still says
    ``SCHEDULED``, or the denial that follows makes no sense to them.
    """
    return {
        SHOW_AND_SELL_ID_ATTRIBUTE: str(item[SHOW_AND_SELL_ID_ATTRIBUTE]),
        UNIT_ID_ATTRIBUTE: str(item[UNIT_ID_ATTRIBUTE]),
        UNIT_CAMPAIGN_ID_ATTRIBUTE: str(item[UNIT_CAMPAIGN_ID_ATTRIBUTE]),
        LOCATION_NAME_ATTRIBUTE: str(item[LOCATION_NAME_ATTRIBUTE]),
        ADDRESS_ATTRIBUTE: item.get(ADDRESS_ATTRIBUTE),
        START_AT_ATTRIBUTE: str(item[START_AT_ATTRIBUTE]),
        END_AT_ATTRIBUTE: str(item[END_AT_ATTRIBUTE]),
        STATUS_ATTRIBUTE: derive_event_status(item, now_iso),
        SPLIT_METHOD_ATTRIBUTE: str(item[SPLIT_METHOD_ATTRIBUTE]),
        WE_OWE_ENABLED_ATTRIBUTE: bool(item.get(WE_OWE_ENABLED_ATTRIBUTE) or False),
        PRODUCT_IDS_ATTRIBUTE: normalize_product_ids(item.get(PRODUCT_IDS_ATTRIBUTE)),
        APPROVED_FINALIZATION_ID_ATTRIBUTE: item.get(APPROVED_FINALIZATION_ID_ATTRIBUTE),
        LATEST_FINALIZATION_ID_ATTRIBUTE: item.get(LATEST_FINALIZATION_ID_ATTRIBUTE),
        VERSION_ATTRIBUTE: normalize_required_version(item.get(VERSION_ATTRIBUTE, 1)),
        CREATED_AT_ATTRIBUTE: item.get(CREATED_AT_ATTRIBUTE),
        UPDATED_AT_ATTRIBUTE: item.get(UPDATED_AT_ATTRIBUTE),
        CREATED_BY_ATTRIBUTE: item.get(CREATED_BY_ATTRIBUTE),
        UPDATED_BY_ATTRIBUTE: item.get(UPDATED_BY_ATTRIBUTE),
        CANCELLED_BY_ATTRIBUTE: item.get(CANCELLED_BY_ATTRIBUTE),
        CANCELLED_AT_ATTRIBUTE: item.get(CANCELLED_AT_ATTRIBUTE),
        CANCELLATION_REASON_ATTRIBUTE: item.get(CANCELLATION_REASON_ATTRIBUTE),
    }


def allocation_payload(row: Mapping[str, Any]) -> Dict[str, Any]:
    """One allocation, in the administrative shape §6.1 puts inside ``ShowAndSellAdmin``.

    The interval is the allocation's own denormalized copy (§5.11), not the event's:
    it is what the overlap rule compares, so a reader looking at a page of allocations
    sees the interval the decision was made on. Quantities come straight off the row —
    ``remainingQty`` is stored precisely so no reader has to re-derive it and get a
    different answer than the write that maintained it.
    """
    return {
        UNIT_CAMPAIGN_ID_ATTRIBUTE: str(row[UNIT_CAMPAIGN_ID_ATTRIBUTE]),
        PRODUCT_ID_ATTRIBUTE: str(row[PRODUCT_ID_ATTRIBUTE]),
        SHOW_AND_SELL_ID_ATTRIBUTE: str(row[SHOW_AND_SELL_ID_ATTRIBUTE]),
        START_AT_ATTRIBUTE: str(row[START_AT_ATTRIBUTE]),
        END_AT_ATTRIBUTE: str(row[END_AT_ATTRIBUTE]),
        STATUS_ATTRIBUTE: str(row.get(STATUS_ATTRIBUTE) or ""),
        "allocatedQty": int(row.get(ALLOCATED_QTY) or 0),
        "soldQty": int(row.get(SOLD_QTY) or 0),
        "releasedQty": int(row.get(RELEASED_QTY) or 0),
        "remainingQty": int(row.get(REMAINING_QTY) or 0),
        VERSION_ATTRIBUTE: normalize_required_version(row.get(VERSION_ATTRIBUTE, 1)),
        CREATED_AT_ATTRIBUTE: row.get(CREATED_AT_ATTRIBUTE),
        UPDATED_AT_ATTRIBUTE: row.get(UPDATED_AT_ATTRIBUTE),
    }


def slot_admin_payload(row: Mapping[str, Any]) -> Dict[str, Any]:
    """One slot as an admin sees it (§5.12): the counter and the version included.

    The version is here because the slot's own mutations condition on it (§3.3), and
    the counter is here because capacity arithmetic is the admin's problem — a
    participant sees :func:`slot_opportunity_payload` instead.
    """
    return {
        SHOW_AND_SELL_ID_ATTRIBUTE: str(row[SHOW_AND_SELL_ID_ATTRIBUTE]),
        SLOT_ID_ATTRIBUTE: str(row[SLOT_ID_ATTRIBUTE]),
        LABEL_ATTRIBUTE: row.get(LABEL_ATTRIBUTE),
        START_AT_ATTRIBUTE: str(row[START_AT_ATTRIBUTE]),
        END_AT_ATTRIBUTE: str(row[END_AT_ATTRIBUTE]),
        CAPACITY_ATTRIBUTE: int(row.get(CAPACITY_ATTRIBUTE) or 0),
        ACTIVE_SIGNUP_COUNT_ATTRIBUTE: int(row.get(ACTIVE_SIGNUP_COUNT_ATTRIBUTE) or 0),
        VERSION_ATTRIBUTE: normalize_required_version(row.get(VERSION_ATTRIBUTE, 1)),
        CREATED_AT_ATTRIBUTE: row.get(CREATED_AT_ATTRIBUTE),
        UPDATED_AT_ATTRIBUTE: row.get(UPDATED_AT_ATTRIBUTE),
    }


def signup_admin_payload(row: Mapping[str, Any]) -> Dict[str, Any]:
    """One signup with its audit, for the cancellation result (§5.13).

    Cancellation returns the signups it released, and the caller needs the actor
    fields to see who placed what: this is the administrative surface, where the
    audit lives (:func:`signup_summary_payload` is the participant view, and SEC-04
    is why the two are separate functions).
    """
    return {
        SHOW_AND_SELL_ID_ATTRIBUTE: str(row[SHOW_AND_SELL_ID_ATTRIBUTE]),
        SLOT_ID_ATTRIBUTE: str(row[SLOT_ID_ATTRIBUTE]),
        PROFILE_ID_ATTRIBUTE: str(row[PROFILE_ID_ATTRIBUTE]),
        UNIT_CAMPAIGN_ID_ATTRIBUTE: str(row.get(UNIT_CAMPAIGN_ID_ATTRIBUTE) or ""),
        CAMPAIGN_ID_ATTRIBUTE: str(row.get(CAMPAIGN_ID_ATTRIBUTE) or ""),
        STATUS_ATTRIBUTE: str(row.get(STATUS_ATTRIBUTE) or ""),
        "actualMinutes": int(row.get(ACTUAL_MINUTES_ATTRIBUTE) or 0),
        "signedUpByAccountId": row.get(SIGNED_UP_BY_ATTRIBUTE),
        "confirmedByAccountId": row.get(CONFIRMED_BY_ATTRIBUTE),
        "confirmedAt": row.get(CONFIRMED_AT_ATTRIBUTE),
        VERSION_ATTRIBUTE: normalize_required_version(row.get(VERSION_ATTRIBUTE, 1)),
        CREATED_AT_ATTRIBUTE: row.get(CREATED_AT_ATTRIBUTE),
        UPDATED_AT_ATTRIBUTE: row.get(UPDATED_AT_ATTRIBUTE),
    }


def slot_opportunity_payload(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Project a slot onto the participant-safe view: interval, capacity, and room left.

    Deliberately not the administrative slot: no version, no actor, no signup audit.
    A Scout chooses a slot from when it runs and how many places it has, and
    ``openCapacity`` is computed here so the client cannot invent its own arithmetic
    against a capacity it hopes for (SEC-05).
    """
    capacity = int(row.get(CAPACITY_ATTRIBUTE) or 0)
    active = int(row.get(ACTIVE_SIGNUP_COUNT_ATTRIBUTE) or 0)
    return {
        SLOT_ID_ATTRIBUTE: str(row[SLOT_ID_ATTRIBUTE]),
        LABEL_ATTRIBUTE: row.get(LABEL_ATTRIBUTE),
        START_AT_ATTRIBUTE: str(row[START_AT_ATTRIBUTE]),
        END_AT_ATTRIBUTE: str(row[END_AT_ATTRIBUTE]),
        CAPACITY_ATTRIBUTE: capacity,
        # ``openCapacity`` only, never the maintained ``activeSignupCount``: SDL
        # ``ShowAndSellOpportunitySlot`` declares capacity and places left, and this
        # projection is that type's whole allowlist. Reporting the counter as well would
        # let a second, derivable number reach a Scout and give a later change somewhere
        # to drift.
        "openCapacity": max(capacity - active, 0),
    }


def signup_summary_payload(row: Mapping[str, Any], slot: Mapping[str, Any]) -> Dict[str, Any]:
    """One participant's own signup, in the participant-safe shape (§5.13).

    No ``signedUpByAccountId``, no ``confirmedByAccountId``: SEC-04 and AUTH-P-04 keep
    the identity of who placed or confirmed a signup on the administrative surface
    only, and this payload is what the participant-facing queries return.

    The interval is read off the **slot** row, not the signup row: §5.13 gives
    ``ShowAndSellSignup`` no ``startAt``/``endAt``, because a signup runs when its slot
    runs. Reading them off the signup would work only against a fixture that
    denormalized them and would raise ``KeyError`` on a canonical row.
    """
    return {
        SLOT_ID_ATTRIBUTE: str(row[SLOT_ID_ATTRIBUTE]),
        SHOW_AND_SELL_ID_ATTRIBUTE: str(row[SHOW_AND_SELL_ID_ATTRIBUTE]),
        STATUS_ATTRIBUTE: str(row.get(STATUS_ATTRIBUTE) or ""),
        START_AT_ATTRIBUTE: str(slot[START_AT_ATTRIBUTE]),
        END_AT_ATTRIBUTE: str(slot[END_AT_ATTRIBUTE]),
        "actualMinutes": int(row.get(ACTUAL_MINUTES_ATTRIBUTE) or 0),
        "signupVersion": int(row.get(VERSION_ATTRIBUTE) or 1),
    }


def opportunity_payload(
    event: Mapping[str, Any],
    *,
    timezone_name: str,
    slots: Sequence[Mapping[str, Any]],
    signups: Sequence[Mapping[str, Any]],
    now_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """The participant-safe opportunity for one event (§6.1, EVT-Q-02-01).

    This is the allowlist, expressed by construction: a participant sees what the
    event is, when it runs, where, whether We Owe is offered, how the pool splits,
    the slots and their own signups, and the event version they need to sign up
    against. Nothing about stock, sales, buyers, cash, finalization, actors, or the
    Unit's identity appears here, and SEC-04 is why the administrative projection
    above is a different function rather than the same one with fields removed.
    """
    return {
        SHOW_AND_SELL_ID_ATTRIBUTE: str(event[SHOW_AND_SELL_ID_ATTRIBUTE]),
        LOCATION_NAME_ATTRIBUTE: str(event[LOCATION_NAME_ATTRIBUTE]),
        ADDRESS_ATTRIBUTE: event.get(ADDRESS_ATTRIBUTE),
        START_AT_ATTRIBUTE: str(event[START_AT_ATTRIBUTE]),
        END_AT_ATTRIBUTE: str(event[END_AT_ATTRIBUTE]),
        STATUS_ATTRIBUTE: derive_event_status(event, now_iso),
        SPLIT_METHOD_ATTRIBUTE: str(event[SPLIT_METHOD_ATTRIBUTE]),
        WE_OWE_ENABLED_ATTRIBUTE: bool(event.get(WE_OWE_ENABLED_ATTRIBUTE) or False),
        "timezone": timezone_name,
        "eventVersion": normalize_required_version(event.get(VERSION_ATTRIBUTE, 1)),
        "slots": [slot_opportunity_payload(slot) for slot in slots],
        "mySignups": [signup_summary_payload(signup, _slot_for(slots, signup)) for signup in signups],
    }


# --- Pure interval helper --------------------------------------------------------


def intervals_overlap(first_start: str, first_end: str, second_start: str, second_end: str) -> bool:
    """Whether two instants-intervals overlap, treating touching ends as separate.

    SSE-02 says two events may overlap and overlap is never a rejection reason on its
    own — the rejection lives in §3.2's concurrent-stock rule — and SLOT-03/SLOT-04
    say a Scout may hold adjacent slots but not overlapping ones. One shared rule,
    stated once: touching endpoints do not overlap.
    """
    return first_start < second_end and second_start < first_end
