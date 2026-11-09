"""
Unit tests for src/handlers/unit_operations.py (Show & Sell wave 2).

Covers the tombstone authorization contract, the invite lifecycle with the
spec 5.3 NOT_FOUND suppression and the attempt-11 RATE_LIMIT_EXCEEDED
throttle, committed-replay idempotency, and the dispatcher surface.
"""

from typing import Any, Dict

import boto3
import pytest

from src.handlers.unit_operations import (
    MAX_ACTIVE_INVITES,
    THROTTLE_FAILED_ATTEMPT_LIMIT,
    handler,
)
from src.utils.errors import AppError, ErrorCode

ACCOUNT_A = "ACCOUNT#user-123-456"
ACCOUNT_B = "ACCOUNT#user-789"


@pytest.fixture
def units_table(dynamodb_table: Any) -> Any:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-units-ue1-dev")


@pytest.fixture
def throttles_table(dynamodb_table: Any) -> Any:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-public-order-throttles-ue1-dev")


def _event(field: str, arguments: Dict[str, Any], sub: str = "user-123-456") -> Dict[str, Any]:
    return {
        "arguments": arguments,
        "identity": {"sub": sub, "username": sub},
        "info": {"fieldName": field, "parentTypeName": "Mutation" if not field.startswith("unit") else "Query"},
    }


def _create_unit(field: str, caller_sub: str = "user-123-456", **overrides: Any) -> Dict[str, Any]:
    key = str(overrides.pop("idempotencyKey", "create-key-001"))
    arguments = {
        "input": {
            "unitType": "Pack",
            "unitNumber": "9999",
            "city": "Denver",
            "state": "CO",
            "idempotencyKey": key,
            **overrides,
        }
    }
    return handler(_event(field, arguments, sub=caller_sub), None)


def _seed_unit_with_admin(units_table: Any, admin: str = ACCOUNT_A, unit_id: str = "unit-1") -> None:
    units_table.put_item(
        Item={
            "unitId": unit_id,
            "itemKey": "METADATA",
            "accountId": admin,
            "unitType": "Pack",
            "unitNumber": "9999",
            "city": "Denver",
            "state": "CO",
            "displayName": "Pack 9999 (Denver)",
            "timezone": "America/Denver",
            "splitDefault": "EQUAL",
            "councilNeedBasis": "PHYSICAL_STOCK",
            "metadataKey": "pack|9999|denver|co",
            "adminCount": 1,
            "activeInviteCount": 0,
            "version": 1,
            "createdAt": "2026-11-01T00:00:00Z",
            "updatedAt": "2026-11-01T00:00:00Z",
            "createdByAccountId": admin,
        }
    )
    units_table.put_item(
        Item={
            "unitId": unit_id,
            "itemKey": f"GRANT#{admin}",
            "accountId": admin,
            "role": "UNIT_ADMIN",
            "createdByAccountId": admin,
            "createdAt": "2026-11-01T00:00:00Z",
        }
    )


class TestCreateUnit:
    def test_success_with_defaults(self, units_table: Any) -> None:
        result = _create_unit("createUnit")
        assert result["unit"]["splitDefault"] == "EQUAL"
        assert result["unit"]["councilNeedBasis"] == "PHYSICAL_STOCK"
        assert result["unit"]["timezone"] == "America/Denver"
        assert result["unit"]["displayName"] == "Pack 9999 (Denver)"
        assert result["unit"]["adminCount"] == 1
        assert result["unit"]["version"] == 1
        assert result["grant"]["accountId"] == ACCOUNT_A
        # Effect landed: metadata + grant rows exist.
        item = units_table.get_item(Key={"unitId": result["unit"]["unitId"], "itemKey": "METADATA"})["Item"]
        assert item["adminCount"] == 1

    def test_explicit_values(self, units_table: Any) -> None:
        result = _create_unit(
            "createUnit",
            unitType="Troop",
            unitNumber="42",
            city="Aurora",
            state="CO",
            displayName="Troop 42",
            timezone="America/Chicago",
            splitDefault="RATIO",
            councilNeedBasis="KERNEL_STOCK",
        )
        assert result["unit"]["displayName"] == "Troop 42"
        assert result["unit"]["splitDefault"] == "RATIO"

    def test_duplicate_geography_requires_confirmation(self, units_table: Any) -> None:
        _create_unit("createUnit", idempotencyKey="key-10000")
        conflict = _create_unit("createUnit", idempotencyKey="key-20000")
        assert conflict["__isError"] is True
        assert conflict["errorCode"] == ErrorCode.CONFLICT

    def test_duplicate_geography_confirmed(self, units_table: Any) -> None:
        _create_unit("createUnit", idempotencyKey="key-10000")
        result = _create_unit("createUnit", idempotencyKey="key-20000", duplicateConfirmed=True)
        assert result["unit"]["unitType"] == "Pack"

    def test_committed_replay_returns_same_result(self, units_table: Any) -> None:
        first = _create_unit("createUnit", idempotencyKey="same-key")
        second = _create_unit("createUnit", idempotencyKey="same-key")
        assert second == first

    def test_same_key_different_payload_conflicts(self, units_table: Any) -> None:
        _create_unit("createUnit", idempotencyKey="same-key")
        conflict = _create_unit("createUnit", idempotencyKey="same-key", displayName="Other")
        assert conflict["__isError"] is True
        assert conflict["errorCode"] == ErrorCode.CONFLICT

    def test_missing_identity_is_unauthorized(self, units_table: Any) -> None:
        event = _event(
            "createUnit",
            {
                "input": {
                    "unitType": "Pack",
                    "unitNumber": "1",
                    "city": "X",
                    "state": "CO",
                    "idempotencyKey": "k-1000000",
                }
            },
        )
        del event["identity"]
        result = handler(event, None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.UNAUTHORIZED

    @pytest.mark.parametrize(
        "field,value",
        [
            ("state", "COLORADO"),
            ("splitDefault", "MAJORITY"),
            ("councilNeedBasis", "NONE"),
            ("timezone", "MST"),
            ("displayName", "x" * 101),
        ],
    )
    def test_validation_failures(self, units_table: Any, field: str, value: Any) -> None:
        result = _create_unit("createUnit", idempotencyKey="v-key0000", **{field: value})
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT


class TestUpdateUnit:
    def test_success_omitted_display_name_preserved(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        result = handler(
            _event(
                "updateUnit",
                {
                    "input": {
                        "unitId": "unit-1",
                        "city": "Boulder",
                        "expectedVersion": 1,
                        "idempotencyKey": "upd-10000",
                    }
                },
            ),
            None,
        )
        assert result["displayName"] == "Pack 9999 (Denver)"
        assert result["city"] == "Boulder"
        assert result["version"] == 2

    def test_version_mismatch_conflicts(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        result = handler(
            _event(
                "updateUnit",
                {
                    "input": {
                        "unitId": "unit-1",
                        "city": "Boulder",
                        "expectedVersion": 9,
                        "idempotencyKey": "upd-20000",
                    }
                },
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.CONFLICT

    def test_non_admin_not_found(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        result = handler(
            _event(
                "updateUnit",
                {
                    "input": {
                        "unitId": "unit-1",
                        "city": "Boulder",
                        "expectedVersion": 1,
                        "idempotencyKey": "upd-30000",
                    }
                },
                sub="user-789",
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_tombstoned_admin_forbidden(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        units_table.put_item(
            Item={
                "unitId": "unit-1",
                "itemKey": f"GRANT_TOMBSTONE#{ACCOUNT_B}",
                "accountId": ACCOUNT_B,
                "removedAt": "t",
            }
        )
        result = handler(
            _event(
                "updateUnit",
                {
                    "input": {
                        "unitId": "unit-1",
                        "city": "Boulder",
                        "expectedVersion": 1,
                        "idempotencyKey": "upd-40000",
                    }
                },
                sub="user-789",
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

    def test_replay(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        args = {
            "input": {
                "unitId": "unit-1",
                "city": "Boulder",
                "expectedVersion": 1,
                "idempotencyKey": "upd-50000",
            }
        }
        first = handler(_event("updateUnit", args), None)
        second = handler(_event("updateUnit", args), None)
        assert second == first


class TestCreateUnitInvite:
    def _make_invite(self, units_table: Any, key: str = "invitekey0001") -> Dict[str, Any]:
        _seed_unit_with_admin(units_table)
        return handler(_event("createUnitInvite", {"unitId": "unit-1", "idempotencyKey": key.ljust(9, "0")}), None)

    def test_success(self, units_table: Any) -> None:
        result = self._make_invite(units_table)
        assert result["unitId"] == "unit-1"
        assert len(result["inviteCode"]) == 16
        metadata = units_table.get_item(Key={"unitId": "unit-1", "itemKey": "METADATA"})["Item"]
        assert metadata["activeInviteCount"] == 1

    def test_cap_enforced(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        metadata = units_table.get_item(Key={"unitId": "unit-1", "itemKey": "METADATA"})["Item"]
        metadata["activeInviteCount"] = MAX_ACTIVE_INVITES
        units_table.put_item(Item=metadata)
        result = handler(_event("createUnitInvite", {"unitId": "unit-1", "idempotencyKey": "inv-cap00"}), None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.CONFLICT

    def test_non_admin_blocked(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        result = (
            handler(
                _event(
                    "createUnitInvite",
                    {"unitId": "unit-1", "idempotencyKey": "inv-x0000"},
                ),
                None,
            )
            if False
            else handler(
                _event("createUnitInvite", {"unitId": "unit-1", "idempotencyKey": "inv-x0000"}, sub="user-789"),
                None,
            )
        )
        assert result["__isError"] is True

    def test_replay(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        first = handler(_event("createUnitInvite", {"unitId": "unit-1", "idempotencyKey": "inv-replay"}), None)
        again = handler(_event("createUnitInvite", {"unitId": "unit-1", "idempotencyKey": "inv-replay"}), None)
        metadata = units_table.get_item(Key={"unitId": "unit-1", "itemKey": "METADATA"})["Item"]
        assert metadata["activeInviteCount"] == 1
        assert again == first


class TestRevokeUnitInvite:
    def _active_invite(self, units_table: Any) -> str:
        created = TestCreateUnitInvite()._make_invite(units_table, "inv-rev")
        return str(created["inviteCode"])

    def test_success(self, units_table: Any) -> None:
        code = self._active_invite(units_table)
        result = handler(
            _event("revokeUnitInvite", {"unitId": "unit-1", "inviteCode": code, "idempotencyKey": "rev-10000"}),
            None,
        )
        assert result is True
        metadata = units_table.get_item(Key={"unitId": "unit-1", "itemKey": "METADATA"})["Item"]
        assert metadata["activeInviteCount"] == 0

    def test_unknown_or_consumed_not_found(self, units_table: Any) -> None:
        self._active_invite(units_table)
        result = handler(
            _event(
                "revokeUnitInvite",
                {"unitId": "unit-1", "inviteCode": "ZZZZ9999ZZZZ9999", "idempotencyKey": "rev-20000"},
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_replay_returns_true(self, units_table: Any) -> None:
        code = self._active_invite(units_table)
        args = {"unitId": "unit-1", "inviteCode": code, "idempotencyKey": "rev-30000"}
        assert handler(_event("revokeUnitInvite", args), None) is True
        assert handler(_event("revokeUnitInvite", args), None) is True


class TestRedeemUnitInvite:
    def _active_invite(self, units_table: Any) -> str:
        created = TestCreateUnitInvite()._make_invite(units_table, "inv-red")
        return str(created["inviteCode"])

    def test_success_grants_admin(self, units_table: Any, throttles_table: Any) -> None:
        code = self._active_invite(units_table)
        result = handler(
            _event("redeemUnitInvite", {"inviteCode": code, "idempotencyKey": "red-10000"}, sub="user-789"),
            None,
        )
        assert result["accountId"] == ACCOUNT_B
        invite = units_table.get_item(Key={"unitId": "unit-1", "itemKey": f"INVITE#{code}"})["Item"]
        assert invite["status"] == "CONSUMED"
        metadata = units_table.get_item(Key={"unitId": "unit-1", "itemKey": "METADATA"})["Item"]
        assert metadata["activeInviteCount"] == 0
        assert metadata["adminCount"] == 2
        # Success does NOT increment the failure throttle.
        assert not throttles_table.scan()["Items"]

    def test_replay(self, units_table: Any) -> None:
        code = self._active_invite(units_table)
        args = {"inviteCode": code, "idempotencyKey": "red-20000"}
        first = handler(_event("redeemUnitInvite", args, sub="user-789"), None)
        second = handler(_event("redeemUnitInvite", args, sub="user-789"), None)
        assert second == first
        metadata = units_table.get_item(Key={"unitId": "unit-1", "itemKey": "METADATA"})["Item"]
        assert metadata["adminCount"] == 2

    def test_unknown_code_not_found_and_counts_failure(self, units_table: Any, throttles_table: Any) -> None:
        self._active_invite(units_table)
        result = handler(
            _event(
                "redeemUnitInvite", {"inviteCode": "QQQQ8888QQQQ8888", "idempotencyKey": "red-30000"}, sub="user-789"
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND
        rows = throttles_table.scan()["Items"]
        assert len(rows) == 1
        assert int(rows[0]["attempts"]) == 1

    def test_revoked_code_indistinguishable(self, units_table: Any) -> None:
        code = self._active_invite(units_table)
        handler(
            _event("revokeUnitInvite", {"unitId": "unit-1", "inviteCode": code, "idempotencyKey": "rev-x0000"}), None
        )
        result = handler(
            _event("redeemUnitInvite", {"inviteCode": code, "idempotencyKey": "red-40000"}, sub="user-789"),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_expired_code_indistinguishable(self, units_table: Any) -> None:
        code = self._active_invite(units_table)
        invite = units_table.get_item(Key={"unitId": "unit-1", "itemKey": f"INVITE#{code}"})["Item"]
        invite["expiresAtEpoch"] = 1
        units_table.put_item(Item=invite)
        result = handler(
            _event("redeemUnitInvite", {"inviteCode": code, "idempotencyKey": "red-50000"}, sub="user-789"),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_attempt_eleven_rate_limited(self, units_table: Any, throttles_table: Any) -> None:
        self._active_invite(units_table)
        from datetime import datetime, timezone

        from src.handlers.unit_operations import _throttle_key

        now = datetime.now(timezone.utc)
        throttles_table.put_item(Item={"key": _throttle_key(ACCOUNT_B, now), "attempts": THROTTLE_FAILED_ATTEMPT_LIMIT})
        result = handler(
            _event(
                "redeemUnitInvite", {"inviteCode": "QQQQ8888QQQQ8888", "idempotencyKey": "red-60000"}, sub="user-789"
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.RATE_LIMIT_EXCEEDED

    def test_existing_admin_redeem_returns_grant_without_consuming(self, units_table: Any) -> None:
        code = self._active_invite(units_table)
        result = handler(_event("redeemUnitInvite", {"inviteCode": code, "idempotencyKey": "red-70000"}), None)
        assert result["accountId"] == ACCOUNT_A
        invite = units_table.get_item(Key={"unitId": "unit-1", "itemKey": f"INVITE#{code}"})["Item"]
        assert invite["status"] == "ACTIVE"
        metadata = units_table.get_item(Key={"unitId": "unit-1", "itemKey": "METADATA"})["Item"]
        assert metadata["activeInviteCount"] == 1


class TestRevokeUnitAccessGrant:
    def _two_admins(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        handler(
            _event(
                "redeemUnitInvite",
                {
                    "inviteCode": TestCreateUnitInvite()._make_invite(units_table, "inv-2adm")["inviteCode"],
                    "idempotencyKey": "g-1000000",
                },
                sub="user-789",
            ),
            None,
        )
        units_table.update_item(
            Key={"unitId": "unit-1", "itemKey": "METADATA"},
            UpdateExpression="SET version = :v",
            ExpressionAttributeValues={":v": 2},
        )

    def test_success(self, units_table: Any) -> None:
        self._two_admins(units_table)
        result = handler(
            _event(
                "revokeUnitAccessGrant",
                {"unitId": "unit-1", "accountId": ACCOUNT_B, "expectedVersion": 2, "idempotencyKey": "rg-100000"},
            ),
            None,
        )
        assert result["adminCount"] == 1
        grant = units_table.get_item(Key={"unitId": "unit-1", "itemKey": f"GRANT#{ACCOUNT_B}"})
        assert "Item" not in grant
        tombstone = units_table.get_item(Key={"unitId": "unit-1", "itemKey": f"GRANT_TOMBSTONE#{ACCOUNT_B}"})
        assert "Item" in tombstone

    def test_last_admin_blocked(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        result = handler(
            _event(
                "revokeUnitAccessGrant",
                {"unitId": "unit-1", "accountId": ACCOUNT_A, "expectedVersion": 1, "idempotencyKey": "rg-200000"},
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.CONFLICT
        assert result["message"]

    def test_unknown_grant_not_found(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        result = handler(
            _event(
                "revokeUnitAccessGrant",
                {"unitId": "unit-1", "accountId": "ACCOUNT#ghost", "expectedVersion": 1, "idempotencyKey": "rg-300000"},
            ),
            None,
        )
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND


class TestQueries:
    def test_my_units_lists_only_metadata_rows(self, units_table: Any) -> None:
        _create_unit("createUnit", idempotencyKey="q-1000000")
        result = handler(_event("myUnits", {"page": {"limit": 10}}), None)
        assert len(result["items"]) == 1
        assert result["pageInfo"]["hasNextPage"] is False

    def test_my_units_excludes_other_accounts(self, units_table: Any) -> None:
        _create_unit("createUnit", idempotencyKey="q-2000000")
        result = handler(_event("myUnits", {"page": {"limit": 10}}, sub="user-789"), None)
        assert result["items"] == []

    def test_unit_admin_read(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        result = handler(_event("unit", {"unitId": "unit-1"}), None)
        assert result["unitId"] == "unit-1"

    def test_unit_non_admin_not_found(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        result = handler(_event("unit", {"unitId": "unit-1"}, sub="user-789"), None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_unit_admins_lists_grants(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        result = handler(_event("unitAdmins", {"unitId": "unit-1", "page": {"limit": 10}}), None)
        assert [g["accountId"] for g in result["items"]] == [ACCOUNT_A]

    def test_unit_invites_lists_active_only(self, units_table: Any) -> None:
        created = TestCreateUnitInvite()._make_invite(units_table, "inv-li")
        code = str(created["inviteCode"])
        handler(
            _event("revokeUnitInvite", {"unitId": "unit-1", "inviteCode": code, "idempotencyKey": "rv-x00000"}), None
        )
        TestCreateUnitInvite()._make_invite(units_table, "inv-li2")
        result = handler(_event("unitInvites", {"unitId": "unit-1", "page": {"limit": 10}}), None)
        assert len(result["items"]) == 1

    def test_tampered_cursor_rejected(self, units_table: Any) -> None:
        _seed_unit_with_admin(units_table)
        result = handler(_event("unitAdmins", {"unitId": "unit-1", "page": {"cursor": "garbage!!"}}), None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT


class TestDispatcher:
    def test_unknown_field_structured_error(self, units_table: Any) -> None:
        result = handler(_event("noSuchField", {}), None)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

    def test_internal_app_error_raises_to_decorator(self, units_table: Any) -> None:
        from src.handlers.unit_operations import _get_unit

        with pytest.raises(AppError):
            _get_unit(_event("unit", {"unitId": "missing"}), None)
