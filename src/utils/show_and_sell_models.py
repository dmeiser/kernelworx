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

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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
DERIVED_STATUSES: frozenset[str] = frozenset({STATUS_SCHEDULED, STATUS_ACTIVE, STATUS_ENDED})

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
    exactly what that row can hold — text, integer, boolean, null, and a list of ids.
    """
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, (int, Decimal)):
        return {"N": str(value)}
    if value is None:
        return {"NULL": True}
    if isinstance(value, (list, tuple)):
        return {"L": [wire_item_value(entry) for entry in value]}
    return {"S": str(value)}


def wire_item(item: Mapping[str, Any]) -> Dict[str, Any]:
    """A whole METADATA row in wire form."""
    return {name: wire_item_value(value) for name, value in item.items()}


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
            the condition, each with its own value placeholder.
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
        # A cancellation that raced a finalization must not overwrite a FINALIZED
        # event: the state the caller read is part of the guard, not just the version.
        extra_conditions=((":finalizedCondition", "#status <> :finalizedCondition", STATUS_FINALIZED),),
    )


def cancel_allocation_action(
    *,
    allocation: Mapping[str, Any],
    released_qty: int,
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """Release an open allocation's whole remainder (§8.8 step 3).

    ``releasedQty`` becomes the value the read row's ``releasedQty + remainingQty``
    adds to, and ``remainingQty`` becomes 0. Those are the numbers §8.8 names, taken
    from the row this transaction read, and the read row's ``version`` is the
    condition — so a concurrent allocation mutation that moved the remainder between
    the read and the commit cancels the whole plan rather than releasing an amount
    nobody agreed to.

    ``released_qty`` is the caller's already-computed sum, so the arithmetic that
    decides how much stock goes back on the shelf has exactly one owner (the
    cancellation resolver) and the action here is only what it means in DynamoDB.
    """
    require_allocation_transition(allocation.get(STATUS_ATTRIBUTE), ALLOCATION_CANCELLED)
    return _conditioned_update(
        {"pk": str(allocation["pk"]), "sk": str(allocation["sk"])},
        tables.inventory.table_name,
        expected_version=normalize_required_version(allocation.get(VERSION_ATTRIBUTE, 1)),
        sets={
            VERSION_ATTRIBUTE: normalize_required_version(allocation.get(VERSION_ATTRIBUTE, 1)) + 1,
            RELEASED_QTY: released_qty,
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
    allocation_version: int,
) -> Tuple[str, Dict[str, Any]]:
    """The audit row that says an allocation's remainder went back on the shelf.

    §8.8 step 3 names the release movement alongside the allocation write, and the
    allocation write alone would leave the ledger unable to explain why a later
    ``assignedOpenQty`` dropped. The delta is negative (the assignment is going away)
    and is the only delta ``EVENT_RELEASE`` is allowed to move, so physical stock and
    custody stay untouched — a cancellation releases a reservation, it never moves a
    Kernel.
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
        inventory_version=allocation_version,
    )
    return inventory_models.put_inventory_movement_action(item)


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
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """Cancel one signup record, keeping the row as history (§8.8, SSE-05).

    Cancellation never deletes the signup: §3.1.4 releases the commitment while the
    audit trail of who was signed up stays, and the same is true of sales and We Owe.
    """
    return _conditioned_update(
        {"pk": show_and_sell_pk(show_and_sell_id), "sk": signup_sk(slot_id, profile_id)},
        tables.show_and_sells.table_name,
        expected_version=expected_version,
        sets={STATUS_ATTRIBUTE: SIGNUP_CANCELLED, UPDATED_AT_ATTRIBUTE: updated_at},
    )


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
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """Mark one commitment projection cancelled, conditioned on its read version.

    The commitment is what blocks a later overlapping signup, so leaving it ACTIVE
    after a cancellation would keep a Scout out of a slot she is no longer holding.
    Its version is written to match the signup it mirrors (§5.13).
    """
    return _conditioned_update(
        {"pk": str(commitment["pk"]), "sk": str(commitment["sk"])},
        tables.unit_campaigns.table_name,
        expected_version=normalize_required_version(commitment.get(VERSION_ATTRIBUTE, 1)),
        sets={
            STATUS_ATTRIBUTE: SIGNUP_CANCELLED,
            VERSION_ATTRIBUTE: normalize_required_version(commitment.get(VERSION_ATTRIBUTE, 1)) + 1,
            UPDATED_AT_ATTRIBUTE: updated_at,
        },
    )


def bump_commitment_guard_action(
    *,
    profile_id: str,
    updated_at: str,
) -> Tuple[str, Dict[str, Any]]:
    """Advance one Scout's commitment guard, incrementing it in the write itself.

    The guard is the serialization point for every commitment change across all of a
    Scout's memberships (§5.13), which is how a cancellation and a concurrent signup
    in a different Unit Campaign settle: whichever writes second finds the guard it
    read has moved, and its own plan cancels rather than resurrecting a commitment.

    ``commitmentVersion`` is incremented by DynamoDB rather than written from a read
    value. Two writers that both read the guard and then wrote ``read + 1`` would
    land on the same number and both believe they serialized; ``+ :one`` makes the
    increment itself the lock, and ``attribute_exists`` makes "this Scout never
    signed up, so there is no guard" fail the transaction instead of inventing a row.
    """
    return (
        "Update",
        {
            "TableName": tables.unit_campaigns.table_name,
            "Key": wire_key(commitment_guard_key(profile_id)),
            "UpdateExpression": "SET #commitmentVersion = #commitmentVersion + :one, #updatedAt = :updatedAt",
            "ConditionExpression": "attribute_exists(#pk) AND attribute_exists(#commitmentVersion)",
            "ExpressionAttributeNames": {
                "#commitmentVersion": "commitmentVersion",
                "#updatedAt": UPDATED_AT_ATTRIBUTE,
                "#pk": "pk",
            },
            "ExpressionAttributeValues": wire_values({":one": 1, ":updatedAt": updated_at}),
            "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
        },
    )


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
        ACTIVE_SIGNUP_COUNT_ATTRIBUTE: active,
        "openCapacity": max(capacity - active, 0),
    }


def signup_summary_payload(row: Mapping[str, Any]) -> Dict[str, Any]:
    """One participant's own signup, in the participant-safe shape (§5.13).

    No ``signedUpByAccountId``, no ``confirmedByAccountId``: SEC-04 and AUTH-P-04 keep
    the identity of who placed or confirmed a signup on the administrative surface
    only, and this payload is what the participant-facing queries return.
    """
    return {
        SLOT_ID_ATTRIBUTE: str(row[SLOT_ID_ATTRIBUTE]),
        SHOW_AND_SELL_ID_ATTRIBUTE: str(row[SHOW_AND_SELL_ID_ATTRIBUTE]),
        STATUS_ATTRIBUTE: str(row.get(STATUS_ATTRIBUTE) or ""),
        START_AT_ATTRIBUTE: str(row[START_AT_ATTRIBUTE]),
        END_AT_ATTRIBUTE: str(row[END_AT_ATTRIBUTE]),
        "actualMinutes": int(row.get("actualMinutes") or 0),
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
        "mySignups": [signup_summary_payload(signup) for signup in signups],
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
