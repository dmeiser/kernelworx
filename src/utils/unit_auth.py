"""Consistent Unit-grant authorization (checklist leaf 1.1.2).

The single place that answers "may this Account act on this Unit?". Data model
§5.2 makes the ``UnitAccessGrant`` row the only thing that grants Unit
administration, so this module deliberately never consults:

- ``src.utils.auth.is_admin`` — the global ADMIN group is a separate surface for
  account administration. A global ADMIN with no grant has no Unit access
  (AUTH-U-03: global ADMIN is never a Unit-admin shortcut), and this module
  cannot be talked into it because it never reads a token claim at all;
- legacy Unit metadata (``unitType``/``unitNumber``/profile rows) — identity is
  not a credential, and ``metadataKey`` never authorizes (§5.1).

Reads are strongly consistent for the same reason every mutation read is: an
administrative decision made against a stale grant row lets a revoked admin
through for a request, which AUTH-U-02 forbids.

Denial shape (API contract §3.3, AUTH-U-02/05): a Unit is visible only to its
own admins, so a caller with no grant is answered exactly like a caller who
named a Unit that does not exist — ``NOT_FOUND``, with no disclosure that the
resource exists. ``FORBIDDEN`` is reserved for a caller who may see the resource
but lacks the specific action; that distinction is made by the resolver, which
is why the helpers here return the grant rather than a verdict code.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from boto3.dynamodb.conditions import Key

from .dynamodb import tables
from .errors import AppError, ErrorCode
from .pagination import query_all_items
from .unit_models import GRANT_SK_PREFIX, grant_key, read_unit, unit_pk

_NOT_FOUND = "Unit not found"


def _as_item(value: Any) -> Optional[Dict[str, Any]]:
    """Narrow a DynamoDB response value to an item mapping, or None."""
    return value if isinstance(value, dict) else None


def read_grant(unit_id: str, account_id: str) -> Optional[Dict[str, Any]]:
    """Strongly consistent read of one Account's grant on one Unit.

    Keyed directly rather than queried: ``(unitId, accountId)`` is the grant's
    sort key, so a lookup can never match another Account's grant or another
    Unit's.
    """
    response = tables.units.get_item(Key=grant_key(unit_id, account_id), ConsistentRead=True)
    return _as_item(response.get("Item"))


def is_unit_admin(account_id: str, unit_id: str) -> bool:
    """True only when the Account holds a grant on that Unit."""
    return read_grant(unit_id, account_id) is not None


def require_unit_admin(account_id: Optional[str], unit_id: str) -> Dict[str, Any]:
    """Return the caller's grant, denying everything else.

    Args:
        account_id: The caller's Cognito sub, or None for an unauthenticated or
            API-key caller.
        unit_id: The Unit being acted on.

    Returns:
        The caller's ``UnitAccessGrant`` item.

    Raises:
        AppError: UNAUTHORIZED for an absent caller (no session to authorize);
            NOT_FOUND for an unknown Unit, a Unit in another tenant, or a grant
            that was revoked — all three read identically, so a denial never
            confirms that a Unit exists.
    """
    if not account_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "A signed-in account is required")
    if read_unit(unit_id) is None:
        raise AppError(ErrorCode.NOT_FOUND, _NOT_FOUND)
    grant = read_grant(unit_id, account_id)
    if grant is None:
        raise AppError(ErrorCode.NOT_FOUND, _NOT_FOUND)
    return grant


def list_unit_grants(unit_id: str) -> List[Dict[str, Any]]:
    """Every current grant on a Unit, by ascending account id.

    A grant row's existence IS the membership: revocation deletes the row, so a
    revoked admin disappears from this list immediately and needs no status
    filter. ``adminCount`` on the Unit remains the authoritative count; this
    listing is what §1.2.3 and the admin roster check against it.
    """
    items = query_all_items(
        tables.units,
        {
            "KeyConditionExpression": Key("pk").eq(unit_pk(unit_id)) & Key("sk").begins_with(GRANT_SK_PREFIX),
            "ConsistentRead": True,
        },
    )
    return [item for item in items if _as_item(item) is not None]


def list_unit_ids_for_account(account_id: str) -> List[str]:
    """The Unit ids on which the Account holds a grant (``accountId-unitId-index``).

    Discovery only — it returns ids, not Units, so a caller can never read a
    Unit it was not granted on. Backs ``myUnits`` (§1.3.4).
    """
    items = query_all_items(
        tables.units,
        {
            "IndexName": "accountId-unitId-index",
            "KeyConditionExpression": Key("accountId").eq(account_id),
            "FilterExpression": "begins_with(#sk, :grant_prefix)",
            "ExpressionAttributeNames": {"#sk": "sk"},
            "ExpressionAttributeValues": {":grant_prefix": GRANT_SK_PREFIX},
        },
    )
    unit_ids = [str(item["unitId"]) for item in items if item.get("unitId")]
    return sorted(set(unit_ids))
