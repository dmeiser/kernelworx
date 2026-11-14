"""Unit, UnitAccessGrant and UnitInvite persistence (delivery checklist leaf 1.1).

Stage 1 lays the Unit tenant down at the physical key shapes of data model §6.1:

    UNIT#<unitId>        / METADATA              the Unit            (§5.1)
    UNIT#<unitId>        / GRANT#<accountId>     the access grant    (§5.2)
    INVITE#<inviteCode>  / UNIT#<unitId>         the invite          (§5.3)

This module owns the persistence rules those leaves name — identity, duplicate
lookup, settings validation, invite shape/expiry/TTL — so the `unit_operations`
resolver (§1.2/§1.3) never re-derives them, and it is the only place a Unit item
is built. Authorization over these rows lives in :mod:`src.utils.unit_auth`;
this module reads and writes no decision about WHO may call it.

Invariants enforced here (data model §5.1-§5.3):

- ``unitId`` is generated identity, never derived from metadata. Two Accounts
  creating the same type/number/city/state get two distinct Units; ``metadataKey``
  exists only to warn about the duplicate and never authorizes anything.
- ``metadataKey`` is the normalized ``unitType#unitNumber#city#state`` fingerprint.
  An equal number in a different city is a different key, so no number-only
  collision workaround is needed (UNIT-M-01-03).
- A grant row is the ONLY thing that makes a caller a Unit Admin. Nothing here
  consults the legacy global ADMIN group.
- An invite code is a 16-character bearer credential, single-use, 14-day expiry
  enforced application-side on ``expiresAt``, with the numeric epoch-seconds
  ``expiresAtEpoch`` TTL attribute that lets DynamoDB delete the row eventually.
  Expired, revoked (deleted) and redeemed (deleted) codes are indistinguishable.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from boto3.dynamodb.conditions import Key

from .dynamodb import tables
from .errors import AppError, ErrorCode
from .pagination import query_all_items
from .validation import validate_unit_number

# --- Key layout (data model §6.1) ------------------------------------------------

UNIT_PK_PREFIX = "UNIT"
METADATA_SK = "METADATA"
GRANT_SK_PREFIX = "GRANT"
INVITE_PK_PREFIX = "INVITE"

# The only stored role (data model §5.2). "Unit Kernel" is a display synonym in
# the product copy, never a second stored value.
UNIT_ROLE_ADMIN = "UNIT_ADMIN"

# --- Settings vocabulary (GraphQL SDL enums) -------------------------------------

SPLIT_METHODS: frozenset[str] = frozenset({"EQUAL", "TIME_WORKED"})
COUNCIL_NEED_BASES: frozenset[str] = frozenset({"PHYSICAL_STOCK", "AFTER_ASSIGNMENTS"})
DEFAULT_SPLIT_METHOD = "EQUAL"
DEFAULT_COUNCIL_NEED_BASIS = "PHYSICAL_STOCK"

# --- Invite credential shape (data model §5.3, API contract §3.4) ----------------

INVITE_CODE_LENGTH = 16
# Unambiguous upper-case base32 alphabet: no I/O/0/1, so a code read aloud or
# transcribed from a screen cannot be silently corrupted into a different code.
INVITE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
INVITE_TTL_DAYS = 14

# --- Text limits (API contract §3.4: Unit/display names 1-100 trimmed) -----------

MAX_NAME_LENGTH = 100
MAX_ID_LENGTH = 100
MAX_TIMEZONE_LENGTH = 64

# IANA timezone names drive display and browser-side ICS generation. Validation
# resolves the name against the tz database rather than pattern-matching it, so a
# typo like "Amerika/Denver" is rejected at write time instead of surfacing as a
# broken calendar months later. The database is shipped explicitly (the `tzdata`
# dependency, exported into the Lambda layer by scripts/build-lambda-layer.sh),
# so validation cannot silently reject every zone because a base image happens to
# carry no tz data.


# --- Key builders ----------------------------------------------------------------


def unit_pk(unit_id: str) -> str:
    """Partition key holding a Unit's metadata and its grant rows."""
    return f"{UNIT_PK_PREFIX}#{unit_id}"


def unit_metadata_key(unit_id: str) -> Dict[str, str]:
    """The Unit item's key pair."""
    return {"pk": unit_pk(unit_id), "sk": METADATA_SK}


def grant_sk(account_id: str) -> str:
    """Sort key of one Account's grant on a Unit (unique per ``(unitId, accountId)``)."""
    return f"{GRANT_SK_PREFIX}#{account_id}"


def grant_key(unit_id: str, account_id: str) -> Dict[str, str]:
    """The grant item's key pair."""
    return {"pk": unit_pk(unit_id), "sk": grant_sk(account_id)}


def invite_pk(invite_code: str) -> str:
    """Partition key of an invite, addressed by its bearer credential alone.

    ``redeemUnitInvite`` knows only the code, so the invite is read through a
    Query on this key; the sort key carries the Unit the code joins.
    """
    return f"{INVITE_PK_PREFIX}#{invite_code}"


# --- Normalization and validation ------------------------------------------------


def _invalid(field: str, rule: str) -> AppError:
    return AppError(ErrorCode.INVALID_INPUT, f"{field} {rule}")


def normalize_required_text(value: Any, field: str, max_length: int = MAX_NAME_LENGTH) -> str:
    """Trim a required text field to 1-``max_length`` characters."""
    if not isinstance(value, str) or not value.strip():
        raise _invalid(field, "is required")
    text = value.strip()
    if len(text) > max_length:
        raise _invalid(field, f"must be at most {max_length} characters")
    return text


def normalize_optional_text(value: Any, field: str, max_length: int = MAX_NAME_LENGTH) -> Optional[str]:
    """Trim an optional text field; blank and absent both mean "not supplied"."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid(field, "must be a string")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_length:
        raise _invalid(field, f"must be at most {max_length} characters")
    return text


def normalize_unit_number(value: Any) -> int:
    """Validate the scout unit number (positive integer, shared rule)."""
    return cast(int, validate_unit_number(value, required=True))


def normalize_timezone(value: Any) -> str:
    """Validate an IANA timezone name used for display and calendar generation."""
    text = normalize_required_text(value, "timezone", MAX_TIMEZONE_LENGTH)
    try:
        ZoneInfo(text)
    except ValueError, ZoneInfoNotFoundError:
        raise _invalid("timezone", "must be an IANA timezone name such as America/Denver") from None
    return text


def _require_positive_counter(value: Any, field: str) -> int:
    """Reject a counter below 1 (both the grant count and the version start at 1)."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _invalid(field, "must be at least 1")
    return value


def normalize_enum(value: Any, field: str, allowed: frozenset[str], default: str) -> str:
    """Validate one of the Stage 1 setting enums, applying the Unit-wide default."""
    if value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise _invalid(field, f"must be one of {', '.join(sorted(allowed))}")
    return value


def normalized_metadata_key(unit_type: str, unit_number: int, city: str, state: str) -> str:
    """The normalized duplicate-lookup fingerprint (data model §5.1).

    Case-folded, so "Pack 3149 Aurora CO" and "pack 3149 aurora co" are the same
    Unit for duplicate-warning purposes. Never used for authorization.
    """
    return f"{unit_type}#{unit_number}#{city}#{state}".lower()


def generated_display_name(unit_type: str, unit_number: int, city: str, state: str) -> str:
    """Display name produced when the caller omits one (§5.1 optional/generated)."""
    return f"{unit_type} {unit_number} - {city}, {state}"


# --- Identity and credentials ----------------------------------------------------


def new_unit_id() -> str:
    """A stable Unit identity, generated before any write (never metadata-derived)."""
    return str(uuid.uuid4())


def new_invite_code() -> str:
    """A random 16-character bearer code from the unambiguous alphabet."""
    return "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


def is_valid_invite_code(value: Any) -> bool:
    """True when ``value`` has the shape of an invite credential.

    A malformed code is answered exactly like an unknown one, so this is a
    predicate rather than a validator: it must never tell a caller that a code
    exists.
    """
    return (
        isinstance(value, str)
        and len(value) == INVITE_CODE_LENGTH
        and all(character in INVITE_CODE_ALPHABET for character in value)
    )


# --- Item builders ---------------------------------------------------------------


def build_unit_item(
    *,
    unit_id: Any,
    unit_type: Any,
    unit_number: Any,
    city: Any,
    state: Any,
    timezone_name: Any,
    created_by_account_id: Any,
    now_iso: str,
    split_default: Any = None,
    council_need_basis: Any = None,
    display_name: Any = None,
    admin_count: int = 1,
    version: int = 1,
) -> Dict[str, Any]:
    """Render a Unit item at ``UNIT#<unitId> / METADATA``.

    Validation runs here rather than in the resolver, so an invalid setting can
    never reach the table from any caller — including a future resolver that
    forgets to check. Inputs are normalized on the way through: text is trimmed,
    the unit number is coerced to an integer, and an omitted display name is
    generated from the metadata.

    ``adminCount`` is the authoritative grant count and starts at 1 because the
    creator always receives a grant in the same transaction (§5.1 keeps it at or
    above 1 for the Unit's whole life); ``version`` starts at 1 so the first
    optimistic-concurrency update has a baseline.
    """
    identity = normalize_required_text(unit_id, "unitId", MAX_ID_LENGTH)
    unit_type_text = normalize_required_text(unit_type, "unitType")
    number = normalize_unit_number(unit_number)
    city_text = normalize_required_text(city, "city")
    state_text = normalize_required_text(state, "state")
    _require_positive_counter(admin_count, "adminCount")
    _require_positive_counter(version, "version")
    return {
        "pk": unit_pk(identity),
        "sk": METADATA_SK,
        "unitId": identity,
        "unitType": unit_type_text,
        "unitNumber": number,
        "city": city_text,
        "state": state_text,
        "displayName": normalize_optional_text(display_name, "displayName")
        or generated_display_name(unit_type_text, number, city_text, state_text),
        "metadataKey": normalized_metadata_key(unit_type_text, number, city_text, state_text),
        "timezone": normalize_timezone(timezone_name),
        "splitDefault": normalize_enum(split_default, "splitDefault", SPLIT_METHODS, DEFAULT_SPLIT_METHOD),
        "councilNeedBasis": normalize_enum(
            council_need_basis, "councilNeedBasis", COUNCIL_NEED_BASES, DEFAULT_COUNCIL_NEED_BASIS
        ),
        "adminCount": admin_count,
        "version": version,
        "createdAt": normalize_required_text(now_iso, "nowIso", 40),
        "updatedAt": now_iso,
        "createdByAccountId": normalize_required_text(created_by_account_id, "createdByAccountId", MAX_ID_LENGTH),
    }


def build_grant_item(*, unit_id: Any, account_id: Any, created_by_account_id: Any, now_iso: Any) -> Dict[str, Any]:
    """Render a UnitAccessGrant at ``UNIT#<unitId> / GRANT#<accountId>``.

    ``accountId`` and ``unitId`` are the GSI keys behind "my Units" discovery, so
    a grant that omits either is invisible to its own holder.
    """
    identity = normalize_required_text(unit_id, "unitId", MAX_ID_LENGTH)
    holder = normalize_required_text(account_id, "accountId", MAX_ID_LENGTH)
    return {
        "pk": unit_pk(identity),
        "sk": grant_sk(holder),
        "unitId": identity,
        "accountId": holder,
        "role": UNIT_ROLE_ADMIN,
        "createdByAccountId": normalize_required_text(created_by_account_id, "createdByAccountId", MAX_ID_LENGTH),
        "createdAt": normalize_required_text(now_iso, "nowIso", 40),
    }


def build_invite_item(
    *,
    invite_code: str,
    unit_id: str,
    created_by_account_id: str,
    created_at: datetime,
    ttl_days: int = INVITE_TTL_DAYS,
) -> Dict[str, Any]:
    """Render a UnitInvite at ``INVITE#<code> / UNIT#<unitId>``.

    ``expiresAt`` is the application-side expiry check the API enforces;
    ``expiresAtEpoch`` is the same instant as epoch seconds for the table's TTL
    attribute (the eventual physical delete only — a row the TTL has not
    collected yet is still unreadable once expired).
    """
    if not is_valid_invite_code(invite_code):
        raise _invalid("inviteCode", f"must be {INVITE_CODE_LENGTH} characters from the invite alphabet")
    identity = normalize_required_text(unit_id, "unitId", MAX_ID_LENGTH)
    expires_at = created_at + timedelta(days=ttl_days)
    return {
        "pk": invite_pk(invite_code),
        "sk": unit_pk(identity),
        "inviteCode": invite_code,
        "unitId": identity,
        "createdByAccountId": normalize_required_text(created_by_account_id, "createdByAccountId", MAX_ID_LENGTH),
        "createdAt": created_at.isoformat(),
        "expiresAt": expires_at.isoformat(),
        "expiresAtEpoch": int(expires_at.timestamp()),
    }


# --- Reads -----------------------------------------------------------------------


def read_unit(unit_id: str) -> Optional[Dict[str, Any]]:
    """Strongly consistent read of a Unit item, or None when absent.

    Consistent by contract: every mutation conditions on the Unit ``version`` it
    just read, and an eventually consistent read would turn a fresh write into a
    phantom version conflict.
    """
    response = tables.units.get_item(Key=unit_metadata_key(unit_id), ConsistentRead=True)
    item = response.get("Item")
    return cast(Optional[Dict[str, Any]], item) if isinstance(item, dict) else None


def load_unit_or_not_found(unit_id: str) -> Dict[str, Any]:
    """Read a Unit, answering ``NOT_FOUND`` when it does not exist."""
    unit = read_unit(unit_id)
    if unit is None:
        raise AppError(ErrorCode.NOT_FOUND, "Unit not found")
    return unit


def find_units_with_metadata(metadata_key: str) -> List[Dict[str, Any]]:
    """Units whose normalized metadata fingerprint matches, for the duplicate gate.

    Reads the ``metadataKey-createdAt-index`` GSI. The result is advisory — it
    warns the caller and gates ``duplicateConfirmed`` — and never authorizes
    anything, so an eventual-consistency lag here can only delay a warning.
    """
    return list(
        query_all_items(
            tables.units,
            {
                "IndexName": "metadataKey-createdAt-index",
                "KeyConditionExpression": "metadataKey = :metadata_key",
                "ExpressionAttributeValues": {":metadata_key": metadata_key},
            },
        )
    )


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse a stored ISO-8601 timestamp; None when absent or malformed.

    A malformed expiry must behave like an expired invite (denied), never like
    an unparseable crash, so this returns None instead of raising.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def invite_is_active(invite: Dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    """True while an invite row is redeemable (its expiry lies in the future).

    Revoked and redeemed invites are deleted, so absence — not a status field —
    is how they read as unusable; an expired invite may still be physically
    present until the TTL collects it, which is why the expiry is checked here.
    """
    expires_at = parse_timestamp(invite.get("expiresAt"))
    if expires_at is None:
        return False
    reference = now if now is not None else datetime.now(timezone.utc)
    return expires_at > reference


def read_invite(invite_code: str) -> Optional[Dict[str, Any]]:
    """Consistent read of an invite by code alone, or None when unusable.

    Addressed on the base table by ``pk = INVITE#<code>`` because redemption
    knows only the credential, not the Unit. Malformed and unknown codes read
    identically, and an expired row reads as absent: expired, revoked, redeemed
    and unknown codes must stay indistinguishable (§5.3).
    """
    if not is_valid_invite_code(invite_code):
        return None
    response = tables.units.query(
        KeyConditionExpression=Key("pk").eq(invite_pk(invite_code)),
        ConsistentRead=True,
        Limit=1,
    )
    items = response.get("Items", [])
    item = items[0] if items else None
    if not isinstance(item, dict) or not invite_is_active(item):
        return None
    return cast(Dict[str, Any], item)


def list_active_invites(unit_id: str, *, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """The Unit's unused invites, newest first, with expired rows filtered out.

    Uses ``unitId-createdAt-index`` (sparse: only invite items carry both keys),
    which is what bounds the per-Unit active-invite cap in §1.3.1.
    """
    items = query_all_items(
        tables.units,
        {
            "IndexName": "unitId-createdAt-index",
            "KeyConditionExpression": "unitId = :unit_id",
            # The index is sparse on (unitId, createdAt), which Unit metadata and
            # grant rows also carry, so the invite rows are selected by key prefix.
            "FilterExpression": "begins_with(#pk, :invite_prefix)",
            "ExpressionAttributeNames": {"#pk": "pk"},
            "ExpressionAttributeValues": {":unit_id": unit_id, ":invite_prefix": INVITE_PK_PREFIX},
            "ScanIndexForward": False,
        },
    )
    return [item for item in items if invite_is_active(item, now=now)]
