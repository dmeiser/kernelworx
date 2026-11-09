"""
Unit-grant authorization for Show & Sell (spec GraphQL API section 2.1).

Grant authorization reads ONLY the units base table with strongly
consistent reads (spec DATA_MODEL section 6.1: never GSIs — a stale grant
must never authorize). Global application ADMIN confers NO Unit access;
Unit Admin is the only stored Unit role and is derived from the grant row,
not from JWT groups.

Item layout (tofu/application/modules/dynamodb/main.tf, units table):
- METADATA row: itemKey = "METADATA"
- Grant row: itemKey = "GRANT#<accountId>"
- Tombstone row: itemKey = "GRANT_TOMBSTONE#<accountId>" (removed access)

The tombstone contract (spec SEC-02: removed access takes effect
immediately, and the removed admin learns FORBIDDEN while a cross-tenant
caller learns indistinguishable NOT_FOUND — no existence oracle, SEC-03)
is why authorization never answers "no grant row" alone.
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

from .errors import AppError, ErrorCode

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

METADATA_ITEM_KEY = "METADATA"


def grant_item_key(account_id: str) -> str:
    """Item key of a Unit Admin grant row for ``account_id``."""
    return f"GRANT#{account_id}"


def grant_tombstone_item_key(account_id: str) -> str:
    """Item key of the tombstone proving access was removed for ``account_id``."""
    return f"GRANT_TOMBSTONE#{account_id}"


def get_unit(units_table: "Table", unit_id: str) -> Optional[Dict[str, Any]]:
    """Return the Unit METADATA row, or None when the Unit does not exist.

    Strongly consistent base-table read: the existence answer is
    authorization-relevant and must not come from a stale replica.
    """
    response = units_table.get_item(
        Key={"unitId": unit_id, "itemKey": METADATA_ITEM_KEY},
        ConsistentRead=True,
    )
    item = response.get("Item")
    return item if isinstance(item, dict) else None


def get_grant(units_table: "Table", unit_id: str, account_id: str) -> Optional[Dict[str, Any]]:
    """Return the grant row for ``account_id``, or None when absent."""
    response = units_table.get_item(
        Key={"unitId": unit_id, "itemKey": grant_item_key(account_id)},
        ConsistentRead=True,
    )
    item = response.get("Item")
    return item if isinstance(item, dict) else None


def require_unit_admin(units_table: "Table", unit_id: str, actor_account_id: str) -> Dict[str, Any]:
    """Authorize ``actor_account_id`` as a Unit Admin and return the Unit row.

    Distinguishes removed access from cross-tenant absence (spec SEC-02 /
    SEC-03, AUTH-U-02 / AUTH-U-05):

    - Unit absent -> NOT_FOUND (no existence oracle).
    - Grant row present -> authorized; the Unit METADATA row is returned.
    - Tombstone present (no grant row) -> FORBIDDEN: access was removed and
      removal takes effect immediately.
    - Neither -> NOT_FOUND: cross-tenant callers get the same answer as a
      missing Unit.

    The caller identity must already be resolved to the account id by the
    handler (via ``utils.appsync_types.get_caller_id`` and the application's
    account bootstrap); this module deliberately knows nothing about JWTs.
    """
    unit = get_unit(units_table, unit_id)
    if unit is None:
        raise AppError(ErrorCode.NOT_FOUND, "Unit not found")
    if get_grant(units_table, unit_id, actor_account_id) is not None:
        return unit
    tombstone_response = units_table.get_item(
        Key={"unitId": unit_id, "itemKey": grant_tombstone_item_key(actor_account_id)},
        ConsistentRead=True,
    )
    if tombstone_response.get("Item"):
        raise AppError(ErrorCode.FORBIDDEN, "Unit Admin access has been removed")
    raise AppError(ErrorCode.NOT_FOUND, "Unit not found")
