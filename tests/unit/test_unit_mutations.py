"""Leaf 1.2: Unit mutations - createUnit, updateUnit, revokeUnitAccessGrant.

Named tests from the delivery checklist:

- 1.2.1 ``createUnit``: UNIT-M-01 (creator becomes initial admin, adminCount 1,
  stable unitId), exact-metadata duplicate requires ``duplicateConfirmed``,
  bootstrap ``IDEM`` replay (IDEM-01) and changed-content rejection (IDEM-02).
- 1.2.2 ``updateUnit``: removed-admin denial (AUTH-U-02), stale-version
  CONFLICT (VER-01), exact-geography duplicate confirmation, idempotent retry.
- 1.2.3 ``revokeUnitAccessGrant``: final-grant CONFLICT, add/revoke race,
  immediate access loss, idempotent retry.

Error expectations use the canonical ``ErrorCode`` vocabulary surfaced through
the #329 structured payload (``__isError``/``errorCode``).
"""

from __future__ import annotations

from typing import Any

from src.handlers.unit_operations import lambda_handler
from tests.unit import show_sell_fixtures as fx


def _create_input(**overrides: Any) -> dict:
    base = {
        "unitType": "Pack",
        "unitNumber": 99,
        "city": "Aurora",
        "state": "CO",
        "timezone": "America/Denver",
        "idempotency": {"idempotencyKey": "create-key-1"},
    }
    base.update(overrides)
    return base


def _seed(units_table: Any) -> Any:
    units = units_table
    fx.seed_show_sell_fixtures(units)
    return units


def _get_unit(units: Any, unit_id: str) -> dict:
    return units.get_item(Key={"pk": f"UNIT#{unit_id}", "sk": "METADATA"}, ConsistentRead=True)["Item"]


def _all_units(units: Any) -> list:
    return [i for i in units.scan()["Items"] if i["sk"] == "METADATA"]


# ---------------------------------------------------------------------------
# 1.2.1 createUnit
# ---------------------------------------------------------------------------


class TestCreateUnit:
    def test_unit_m_01_01_creator_becomes_initial_admin_with_admin_count_one(self, units_table: Any) -> None:
        units = _seed(units_table)
        event = fx.unit_operation_event("createUnit", "Emery", input=_create_input())
        payload = lambda_handler(event, None)
        assert not payload.get("__isError"), payload
        unit, grant = payload["unit"], payload["grant"]
        assert unit["adminCount"] == 1
        assert unit["version"] == 1
        assert unit["createdByAccountId"] == fx.account_id("Emery")
        assert grant["accountId"] == fx.account_id("Emery")
        assert grant["role"] == "UNIT_ADMIN"
        # The id is stable and retrievable, and exactly one unit was created.
        stored = _get_unit(units, unit["unitId"])
        assert stored["unitId"] == unit["unitId"]
        assert len(_all_units(units)) == len(fx.UNITS) + 1

    def test_unit_m_01_02_exact_duplicate_requires_confirmation(self, units_table: Any) -> None:
        """Same type/number/city/state without duplicateConfirmed fails; with it, a distinct Unit is created (no merging)."""
        units = _seed(units_table)
        pack = _get_unit(units, fx.PACK_3149)
        dupe = _create_input(
            unitType=pack["unitType"],
            unitNumber=pack["unitNumber"],
            city=pack["city"],
            state=pack["state"],
            idempotency={"idempotencyKey": "dupe-unconfirmed"},
        )
        payload = lambda_handler(fx.unit_operation_event("createUnit", "Emery", input=dupe), None)
        fx.assert_is_error(payload, "CONFLICT")
        assert len(_all_units(units)) == len(fx.UNITS)

        confirmed = _create_input(
            unitType=pack["unitType"],
            unitNumber=pack["unitNumber"],
            city=pack["city"],
            state=pack["state"],
            duplicateConfirmed=True,
            idempotency={"idempotencyKey": "dupe-confirmed"},
        )
        payload = lambda_handler(fx.unit_operation_event("createUnit", "Emery", input=confirmed), None)
        assert not payload.get("__isError"), payload
        assert payload["unit"]["unitId"] != fx.PACK_3149
        assert len(_all_units(units)) == len(fx.UNITS) + 1
        # The original is untouched.
        assert _get_unit(units, fx.PACK_3149)["adminCount"] == pack["adminCount"]

    def test_bootstrap_idem_replay_returns_original_result(self, units_table: Any) -> None:
        """IDEM-01 (bootstrap scope): the identical retry returns the original unit and writes nothing."""
        units = _seed(units_table)
        event = fx.unit_operation_event("createUnit", "Emery", input=_create_input())
        first = lambda_handler(event, None)
        assert not first.get("__isError"), first
        second = lambda_handler(event, None)
        assert not second.get("__isError"), second
        assert second["unit"]["unitId"] == first["unit"]["unitId"]
        assert len(_all_units(units)) == len(fx.UNITS) + 1

    def test_bootstrap_idem_changed_content_rejected(self, units_table: Any) -> None:
        """IDEM-02: reusing the key with different normalized content is INVALID_INPUT."""
        _seed(units_table)
        event = fx.unit_operation_event("createUnit", "Emery", input=_create_input())
        lambda_handler(event, None)
        changed = _create_input(city="Boulder")
        payload = lambda_handler(fx.unit_operation_event("createUnit", "Emery", input=changed), None)
        fx.assert_is_error(payload, "INVALID_INPUT")

    def test_missing_caller_is_unauthorized(self, units_table: Any) -> None:
        _seed(units_table)
        event = fx.unit_operation_event("createUnit", None, input=_create_input())
        payload = lambda_handler(event, None)
        fx.assert_is_error(payload, "UNAUTHORIZED")


# ---------------------------------------------------------------------------
# 1.2.2 updateUnit
# ---------------------------------------------------------------------------


def _update_input(**overrides: Any) -> dict:
    base = {
        "unitId": fx.PACK_3149,
        "version": {"expectedVersion": 1},
        "idempotency": {"idempotencyKey": "update-key-1"},
    }
    base.update(overrides)
    return base


class TestUpdateUnit:
    def test_removed_admin_denied(self, units_table: Any) -> None:
        """AUTH-U-02: Blake's grant was removed; the update is FORBIDDEN and writes nothing."""
        units = _seed(units_table)
        before = _get_unit(units, fx.PACK_3149)
        payload = lambda_handler(
            fx.unit_operation_event("updateUnit", "Blake", input=_update_input(displayName="Hijacked")),
            None,
        )
        fx.assert_is_error(payload, "FORBIDDEN")
        assert _get_unit(units, fx.PACK_3149) == before

    def test_stale_version_returns_conflict_and_writes_nothing(self, units_table: Any) -> None:
        """VER-01: a stale expectedVersion returns CONFLICT with zero writes."""
        units = _seed(units_table)
        payload = lambda_handler(
            fx.unit_operation_event(
                "updateUnit",
                "Avery",
                input={**_update_input(), "version": {"expectedVersion": 99}},
            ),
            None,
        )
        fx.assert_is_error(payload, "CONFLICT")
        assert _get_unit(units, fx.PACK_3149)["version"] == 1

    def test_admin_update_applies_and_bumps_version(self, units_table: Any) -> None:
        units = _seed(units_table)
        payload = lambda_handler(
            fx.unit_operation_event("updateUnit", "Avery", input=_update_input(displayName="Pack 3149 Aurora")),
            None,
        )
        assert not payload.get("__isError"), payload
        assert payload["displayName"] == "Pack 3149 Aurora"
        assert payload["version"] == 2
        assert _get_unit(units, fx.PACK_3149)["version"] == 2

    def test_exact_geography_duplicate_requires_confirmation(self, units_table: Any) -> None:
        """Rerunning the duplicate check: moving Pack 3149 onto Crew 529's exact metadata fails unconfirmed."""
        units = _seed(units_table)
        crew = _get_unit(units, fx.CREW_529)
        dupe = _update_input(
            unitId=fx.PACK_3149,
            unitType=crew["unitType"],
            unitNumber=crew["unitNumber"],
            city=crew["city"],
            state=crew["state"],
            idempotency={"idempotencyKey": "update-dupe"},
        )
        payload = lambda_handler(fx.unit_operation_event("updateUnit", "Avery", input=dupe), None)
        fx.assert_is_error(payload, "CONFLICT")
        assert _get_unit(units, fx.PACK_3149)["city"] == "Aurora"

        confirmed = dict(dupe, duplicateConfirmed=True, idempotency={"idempotencyKey": "update-dupe-confirmed"})
        payload = lambda_handler(fx.unit_operation_event("updateUnit", "Avery", input=confirmed), None)
        assert not payload.get("__isError"), payload
        assert _get_unit(units, fx.PACK_3149)["city"] == crew["city"]

    def test_idempotent_retry_returns_original_result_without_second_write(self, units_table: Any) -> None:
        """IDEM-01 on updateUnit: the identical retry returns the original result; version does not advance twice."""
        units = _seed(units_table)
        event = fx.unit_operation_event("updateUnit", "Avery", input=_update_input(displayName="Pack 3149 Aurora"))
        first = lambda_handler(event, None)
        assert not first.get("__isError"), first
        second = lambda_handler(event, None)
        assert not second.get("__isError"), second
        assert second["version"] == first["version"]
        assert _get_unit(units, fx.PACK_3149)["version"] == 2


# ---------------------------------------------------------------------------
# 1.2.3 revokeUnitAccessGrant
# ---------------------------------------------------------------------------


def _revoke_input(**overrides: Any) -> dict:
    base = {
        "unitId": fx.PACK_3149,
        "accountId": fx.account_id("Taylor"),
        "version": {"expectedVersion": 2},
        "idempotency": {"idempotencyKey": "revoke-key-1"},
    }
    base.update(overrides)
    return base


class TestRevokeUnitAccessGrant:
    def _seed_two_admins(self, units_table: Any) -> Any:
        units = _seed(units_table)
        units.put_item(Item=fx.grant_item(fx.PACK_3149, "Taylor", created_by="Avery"))
        meta = _get_unit(units, fx.PACK_3149)
        meta["adminCount"] = 2
        meta["version"] = 2
        units.put_item(Item=meta)
        return units

    def test_final_grant_conflict_preserves_grant_and_count(self, units_table: Any) -> None:
        """adminCount == 1: the last grant cannot be revoked (CONFLICT, zero writes)."""
        units = _seed(units_table)  # Crew 529 has exactly one admin (Avery).
        payload = lambda_handler(
            fx.unit_operation_event(
                "revokeUnitAccessGrant",
                "Avery",
                input={
                    "unitId": fx.CREW_529,
                    "accountId": fx.account_id("Avery"),
                    "version": {"expectedVersion": 1},
                    "idempotency": {"idempotencyKey": "revoke-final"},
                },
            ),
            None,
        )
        fx.assert_is_error(payload, "CONFLICT")
        grant = units.get_item(
            Key={"pk": f"UNIT#{fx.CREW_529}", "sk": f"GRANT#{fx.account_id('Avery')}"}, ConsistentRead=True
        )
        assert "Item" in grant
        assert _get_unit(units, fx.CREW_529)["adminCount"] == 1

    def test_add_revoke_race_second_revoke_conflicts(self, units_table: Any) -> None:
        """Both revokes read adminCount 2; the transaction makes one win and the loser CONFLICT."""
        units = self._seed_two_admins(units_table)
        first = lambda_handler(fx.unit_operation_event("revokeUnitAccessGrant", "Avery", input=_revoke_input()), None)
        assert not first.get("__isError"), first
        # The loser reuses the stale expectedVersion 2 (unit is now version 3,
        # adminCount 1): it must not be able to drop the final grant.
        second = lambda_handler(
            fx.unit_operation_event(
                "revokeUnitAccessGrant",
                "Avery",
                input=_revoke_input(accountId=fx.account_id("Avery")),
            ),
            None,
        )
        fx.assert_is_error(second, "CONFLICT")
        meta = _get_unit(units, fx.PACK_3149)
        assert meta["adminCount"] == 1
        remaining = units.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": f"UNIT#{fx.PACK_3149}", ":prefix": "GRANT#"},
            ConsistentRead=True,
        )["Items"]
        assert [g["accountId"] for g in remaining] == [fx.account_id("Avery")]

    def test_immediate_access_loss_for_revoked_account(self, units_table: Any) -> None:
        """The revoked account loses access at once: unitAdmins and myUnits exclude them."""
        self._seed_two_admins(units_table)
        payload = lambda_handler(fx.unit_operation_event("revokeUnitAccessGrant", "Avery", input=_revoke_input()), None)
        assert not payload.get("__isError"), payload
        admins = lambda_handler(
            fx.unit_operation_event("unitAdmins", "Avery", arguments={"unitId": fx.PACK_3149}), None
        )
        assert fx.account_id("Taylor") not in {g["accountId"] for g in admins["items"]}
        mine = lambda_handler(fx.unit_operation_event("myUnits", "Taylor"), None)
        assert fx.PACK_3149 not in {u["unitId"] for u in mine["items"]}
        denied = lambda_handler(
            fx.unit_operation_event("unitAdmins", "Taylor", arguments={"unitId": fx.PACK_3149}), None
        )
        fx.assert_is_error(denied, "FORBIDDEN")

    def test_idempotent_retry_does_not_double_decrement(self, units_table: Any) -> None:
        """IDEM-01 on revocation: the identical retry returns the original result; adminCount drops once."""
        units = self._seed_two_admins(units_table)
        event = fx.unit_operation_event("revokeUnitAccessGrant", "Avery", input=_revoke_input())
        first = lambda_handler(event, None)
        assert not first.get("__isError"), first
        second = lambda_handler(event, None)
        assert not second.get("__isError"), second
        assert _get_unit(units, fx.PACK_3149)["adminCount"] == 1
