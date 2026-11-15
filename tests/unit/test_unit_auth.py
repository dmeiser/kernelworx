"""Leaf 1.1.2 — UnitAccessGrant persistence and Unit-admin authorization.

Covers the tests the leaf names: multiple equal admins, one Account in multiple
Units, and cross-Unit denial — including the rule that the lookup IGNORES the
legacy global ADMIN group (AUTH-U-03), because a grant row is the only Unit
credential (data model §5.2).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import pytest
from botocore.exceptions import ClientError

from src.utils.auth import is_admin
from src.utils.errors import AppError, ErrorCode
from src.utils.unit_auth import (
    is_unit_admin,
    list_unit_grants,
    list_unit_ids_for_account,
    read_grant,
    require_unit_admin,
)
from src.utils.unit_models import UNIT_ROLE_ADMIN, build_grant_item, build_unit_item

PACK_ID = "unit-pack-3149-aurora"
CREW_ID = "unit-crew-529-denver"
TROOP_ID = "unit-troop-7150-boulder"

AVERY = "11111111-1111-4111-8111-111111111111"
CASEY = "77777777-7777-4777-8777-777777777777"
RILEY = "44444444-4444-4444-8444-444444444444"

NOW_ISO = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc).isoformat()


def _seed_unit(units_table: Any, unit_id: str, *, admin_count: int = 1) -> None:
    units_table.put_item(
        Item=build_unit_item(
            unit_id=unit_id,
            unit_type="Pack",
            unit_number=3149,
            city="Aurora",
            state="CO",
            timezone_name="America/Denver",
            created_by_account_id=AVERY,
            now_iso=NOW_ISO,
            admin_count=admin_count,
        )
    )


def _grant(units_table: Any, unit_id: str, account_id: str, created_by: str = AVERY) -> Dict[str, Any]:
    item = build_grant_item(unit_id=unit_id, account_id=account_id, created_by_account_id=created_by, now_iso=NOW_ISO)
    units_table.put_item(Item=item)
    return item


# --- multiple equal admins -------------------------------------------------------


def test_multiple_admins_hold_equal_grants(units_table: Any) -> None:
    """Every grant stores the same single role; no grant ranks above another."""
    _seed_unit(units_table, PACK_ID, admin_count=2)
    _grant(units_table, PACK_ID, AVERY)
    _grant(units_table, PACK_ID, CASEY, created_by=AVERY)

    grants = list_unit_grants(PACK_ID)
    assert [grant["accountId"] for grant in grants] == sorted([AVERY, CASEY])
    assert {grant["role"] for grant in grants} == {UNIT_ROLE_ADMIN}
    assert is_unit_admin(AVERY, PACK_ID) and is_unit_admin(CASEY, PACK_ID)
    # Equal role means either one may act; the grant row records who invited whom.
    by_account = {grant["accountId"]: grant for grant in grants}
    assert by_account[AVERY]["createdByAccountId"] == AVERY
    assert by_account[CASEY]["createdByAccountId"] == AVERY


def test_grant_is_unique_per_unit_and_account(units_table: Any) -> None:
    """``(unitId, accountId)`` is the grant identity: a second write cannot duplicate it."""
    _seed_unit(units_table, PACK_ID)
    item = _grant(units_table, PACK_ID, CASEY)
    with pytest.raises(ClientError) as excinfo:
        units_table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(#pk)",
            ExpressionAttributeNames={"#pk": "pk"},
        )
    assert excinfo.value.response["Error"]["Code"] == "ConditionalCheckFailedException"
    assert list_unit_grants(PACK_ID).__len__() == 1


def test_revoked_grant_disappears_immediately(units_table: Any) -> None:
    """Deletion is the revocation: the roster and the check both lose it at once."""
    _seed_unit(units_table, PACK_ID, admin_count=2)
    item = _grant(units_table, PACK_ID, CASEY)
    _grant(units_table, PACK_ID, AVERY)
    assert is_unit_admin(CASEY, PACK_ID)

    units_table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    assert is_unit_admin(CASEY, PACK_ID) is False
    assert read_grant(PACK_ID, CASEY) is None
    assert [grant["accountId"] for grant in list_unit_grants(PACK_ID)] == [AVERY]


# --- one Account in multiple Units -----------------------------------------------


def test_one_account_may_hold_grants_in_several_units(units_table: Any) -> None:
    """Avery administers Pack 3149 and Crew 529; each grant stands alone."""
    _seed_unit(units_table, PACK_ID)
    _seed_unit(units_table, CREW_ID)
    _grant(units_table, PACK_ID, AVERY)
    _grant(units_table, CREW_ID, AVERY, created_by=CASEY)

    assert list_unit_ids_for_account(AVERY) == sorted([CREW_ID, PACK_ID])
    require_unit_admin(AVERY, PACK_ID)
    require_unit_admin(AVERY, CREW_ID)

    # Revoking one Unit leaves the other untouched.
    units_table.delete_item(Key={"pk": f"UNIT#{CREW_ID}", "sk": f"GRANT#{AVERY}"})
    assert list_unit_ids_for_account(AVERY) == [PACK_ID]
    assert is_unit_admin(AVERY, PACK_ID)


def test_discovery_returns_ids_only_and_never_another_units_data(units_table: Any) -> None:
    """``accountId-unitId-index`` is sparse on grants: a Unit row is never returned."""
    _seed_unit(units_table, PACK_ID)
    _grant(units_table, PACK_ID, AVERY)
    rows = [
        row
        for row in units_table.query(
            IndexName="accountId-unitId-index",
            KeyConditionExpression="accountId = :a",
            ExpressionAttributeValues={":a": AVERY},
        )["Items"]
    ]
    assert [row["sk"] for row in rows] == [f"GRANT#{AVERY}"]
    assert list_unit_ids_for_account(RILEY) == []


# --- cross-Unit denial and the global ADMIN rule ---------------------------------


def test_cross_unit_ids_are_denied_without_disclosure(units_table: Any) -> None:
    """Riley administers Troop 7150 and gets the same answer as a nonexistent Unit."""
    _seed_unit(units_table, TROOP_ID)
    _seed_unit(units_table, PACK_ID)
    _grant(units_table, TROOP_ID, RILEY)

    with pytest.raises(AppError) as on_other_unit:
        require_unit_admin(RILEY, PACK_ID)
    with pytest.raises(AppError) as on_missing_unit:
        require_unit_admin(RILEY, "unit-does-not-exist")
    assert on_other_unit.value.error_code == ErrorCode.NOT_FOUND
    assert on_missing_unit.value.error_code == ErrorCode.NOT_FOUND
    assert on_other_unit.value.message == on_missing_unit.value.message
    assert is_unit_admin(RILEY, PACK_ID) is False


def test_global_admin_is_not_a_unit_grant(units_table: Any) -> None:
    """AUTH-U-03: a global ADMIN with no grant has no Unit access.

    The grant lookup never reads a token, so the group cannot leak into the
    decision — proved here by asserting the caller IS a global ADMIN in the
    application's own classifier while still being denied.
    """
    _seed_unit(units_table, PACK_ID)
    admin_event = {"identity": {"sub": RILEY, "claims": {"cognito:groups": ["ADMIN"]}}, "arguments": {}}
    assert is_admin(admin_event) is True

    with pytest.raises(AppError) as excinfo:
        require_unit_admin(RILEY, PACK_ID)
    assert excinfo.value.error_code == ErrorCode.NOT_FOUND
    assert list_unit_ids_for_account(RILEY) == []


def test_absent_caller_is_unauthorized(units_table: Any) -> None:
    """An unauthenticated or API-key caller has no Account to authorize against."""
    _seed_unit(units_table, PACK_ID)
    for caller in (None, ""):
        with pytest.raises(AppError) as excinfo:
            require_unit_admin(caller, PACK_ID)
        assert excinfo.value.error_code == ErrorCode.UNAUTHORIZED


def test_require_unit_admin_returns_the_grant_row(units_table: Any) -> None:
    """The helper hands back the grant so callers can audit who acted."""
    _seed_unit(units_table, PACK_ID)
    _grant(units_table, PACK_ID, CASEY, created_by=AVERY)
    grant = require_unit_admin(CASEY, PACK_ID)
    assert grant["accountId"] == CASEY
    assert grant["role"] == UNIT_ROLE_ADMIN


def test_grant_listing_is_empty_for_a_unit_without_grants(units_table: Any) -> None:
    _seed_unit(units_table, PACK_ID)
    assert list_unit_grants(PACK_ID) == []
    assert list_unit_grants("unit-no-such-unit") == []


def test_authorization_reads_are_consistent_with_just_written_grants(units_table: Any) -> None:
    """Every authorization read is strongly consistent (a revocation must land now)."""
    calls: list[Dict[str, Any]] = []

    class _RecordingTable:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def get_item(self, **kwargs: Any) -> Dict[str, Any]:
            calls.append(kwargs)
            return self._inner.get_item(**kwargs)

        def query(self, **kwargs: Any) -> Dict[str, Any]:
            calls.append(kwargs)
            return self._inner.query(**kwargs)

    from src.utils import dynamodb

    dynamodb.override_table("units", _RecordingTable(units_table))
    _seed_unit(units_table, PACK_ID)
    _grant(units_table, PACK_ID, AVERY)

    require_unit_admin(AVERY, PACK_ID)
    list_unit_grants(PACK_ID)
    assert calls, "expected unit_auth reads to go through the units table"
    for call in calls:
        table_name = call.get("TableName", "kernelworx-units-ue1-dev")
        assert table_name == "kernelworx-units-ue1-dev"
    assert any(call.get("ConsistentRead") is True for call in calls)
