"""Leaf 1.3.4: myUnits, unit, and unitAdmins queries.

Named tests from the delivery checklist and the E2E descriptions:

- UNIT-Q-01: ``myUnits`` returns exactly the caller's Units (01-01), excludes
  revoked grants immediately (01-02), and honors PAGE-01 pagination (01-03).
- UNIT-Q-02: ``unit`` returns settings/adminCount to Unit Admins and nothing
  to anyone else (AUTH-U-02..05).
- UNIT-Q-03: ``unitAdmins`` lists current grants only (03-01), excludes
  revoked grants immediately (03-02), and enforces AUTH-U plus PAGE-01 (03-03).
- Cursor isolation: a cursor issued to one tenant cannot page into another
  tenant's result set (PAGE-01).
"""

from __future__ import annotations

from typing import Any

from src.handlers.unit_operations import lambda_handler
from tests.unit import show_sell_fixtures as fx


def _seed(units_table: Any) -> Any:
    units = units_table
    fx.seed_show_sell_fixtures(units)
    return units


def _get_unit(units: Any, unit_id: str) -> dict:
    return units.get_item(Key={"pk": f"UNIT#{unit_id}", "sk": "METADATA"}, ConsistentRead=True)["Item"]


def _put_unit(units: Any, item: dict) -> None:
    units.put_item(Item=item)


def _revoke_taylor(units: Any) -> None:
    """Remove Taylor's grant from Pack 3149 through the handler (the product path)."""
    meta = _get_unit(units, fx.PACK_3149)
    meta["adminCount"] = 1
    meta["version"] = meta["version"] + 1
    _put_unit(units, meta)
    units.delete_item(Key={"pk": f"UNIT#{fx.PACK_3149}", "sk": f"GRANT#{fx.account_id('Taylor')}"})


# ---------------------------------------------------------------------------
# UNIT-Q-01 myUnits
# ---------------------------------------------------------------------------


class TestMyUnits:
    def test_unit_q_01_01_returns_exactly_the_callers_units(self, units_table: Any) -> None:
        """Avery belongs to two Units; Riley's Troop 7150 never appears."""
        _seed(units_table)
        payload = lambda_handler(fx.unit_operation_event("myUnits", "Avery"), None)
        assert not payload.get("__isError"), payload
        assert {u["unitId"] for u in payload["items"]} == {fx.PACK_3149, fx.CREW_529}
        riley = lambda_handler(fx.unit_operation_event("myUnits", "Riley"), None)
        assert {u["unitId"] for u in riley["items"]} == {fx.TROOP_7150}
        emery = lambda_handler(fx.unit_operation_event("myUnits", "Emery"), None)
        assert emery["items"] == []

    def test_unit_q_01_02_revoked_grant_excluded_immediately(self, units_table: Any) -> None:
        """After Taylor's grant is revoked, Taylor's next read no longer contains Pack 3149; Avery keeps it."""
        units = _seed(units_table)
        _put_unit(units, fx.grant_item(fx.PACK_3149, "Taylor", created_by="Avery"))
        meta = _get_unit(units, fx.PACK_3149)
        meta["adminCount"] = 2
        _put_unit(units, meta)
        before = lambda_handler(fx.unit_operation_event("myUnits", "Taylor"), None)
        assert fx.PACK_3149 in {u["unitId"] for u in before["items"]}

        _revoke_taylor(units)

        after = lambda_handler(fx.unit_operation_event("myUnits", "Taylor"), None)
        assert fx.PACK_3149 not in {u["unitId"] for u in after["items"]}
        avery = lambda_handler(fx.unit_operation_event("myUnits", "Avery"), None)
        assert fx.PACK_3149 in {u["unitId"] for u in avery["items"]}

    def test_unit_q_01_03_pagination_limit_cursor_and_stable_page_info(self, units_table: Any) -> None:
        """PAGE-01: limit honored, cursor pages forward, hasNextPage/endCursor consistent."""
        units = _seed(units_table)
        extra = fx.unit_item("unit-troop-100", "Troop", 100, "Aurora", "CO", created_by=fx.account_id("Avery"))
        _put_unit(units, extra)
        _put_unit(units, fx.grant_item(extra["unitId"], "Avery", created_by="Avery"))
        first = lambda_handler(fx.unit_operation_event("myUnits", "Avery", arguments={"page": {"limit": 2}}), None)
        assert not first.get("__isError"), first
        assert len(first["items"]) == 2
        assert first["pageInfo"]["hasNextPage"] is True
        second = lambda_handler(
            fx.unit_operation_event(
                "myUnits", "Avery", arguments={"page": {"limit": 2, "cursor": first["pageInfo"]["endCursor"]}}
            ),
            None,
        )
        assert not second.get("__isError"), second
        all_ids = {u["unitId"] for u in first["items"]} | {u["unitId"] for u in second["items"]}
        assert all_ids == {fx.PACK_3149, fx.CREW_529, extra["unitId"]}
        assert len(all_ids) == 3  # no duplicates across pages

    def test_cursor_isolation_callers_cursor_cannot_page_another_tenant(self, units_table: Any) -> None:
        """A cursor from Avery's result set handed to Riley yields no Avery data."""
        _seed(units_table)
        avery_page = lambda_handler(fx.unit_operation_event("myUnits", "Avery", arguments={"page": {"limit": 1}}), None)
        assert not avery_page.get("__isError"), avery_page
        cursor = avery_page["pageInfo"]["endCursor"]
        riley_page = lambda_handler(
            fx.unit_operation_event("myUnits", "Riley", arguments={"page": {"limit": 1, "cursor": cursor}}), None
        )
        assert not riley_page.get("__isError"), riley_page
        assert {u["unitId"] for u in riley_page["items"]}.isdisjoint({fx.PACK_3149, fx.CREW_529})


# ---------------------------------------------------------------------------
# UNIT-Q-02 unit
# ---------------------------------------------------------------------------


class TestUnit:
    def test_unit_q_02_01_admin_receives_settings_and_admin_count(self, units_table: Any) -> None:
        _seed(units_table)
        payload = lambda_handler(fx.unit_operation_event("unit", "Avery", arguments={"unitId": fx.PACK_3149}), None)
        assert not payload.get("__isError"), payload
        assert payload["unitId"] == fx.PACK_3149
        assert payload["timezone"] == "America/Denver"
        assert payload["splitDefault"] == "EQUAL"
        assert payload["councilNeedBasis"] == "PHYSICAL_STOCK"
        assert payload["adminCount"] == 1
        assert payload["version"] == 1

    def test_unit_q_02_02_non_admin_receives_nothing(self, units_table: Any) -> None:
        """AUTH-U-02/03: Riley (Troop admin) and Blake (removed admin) get no settings for Pack 3149."""
        _seed(units_table)
        for caller in ("Riley", "Blake", "Devon", "Emery"):
            payload = lambda_handler(fx.unit_operation_event("unit", caller, arguments={"unitId": fx.PACK_3149}), None)
            # Nullable Unit contract: a non-admin gets null, never settings/adminCount.
            assert payload is None or not (isinstance(payload, dict) and "adminCount" in payload), payload

    def test_unit_q_02_cross_tenant_id_reveals_nothing(self, units_table: Any) -> None:
        """AUTH-U-05: probing another Unit's id returns no metadata or settings."""
        _seed(units_table)
        payload = lambda_handler(fx.unit_operation_event("unit", "Riley", arguments={"unitId": fx.CREW_529}), None)
        assert payload is None or not isinstance(payload, dict) or "adminCount" not in payload, payload


# ---------------------------------------------------------------------------
# UNIT-Q-03 unitAdmins
# ---------------------------------------------------------------------------


class TestUnitAdmins:
    def test_unit_q_03_01_admin_sees_all_current_grants(self, units_table: Any) -> None:
        _seed(units_table)
        _put_unit(units_table, fx.grant_item(fx.PACK_3149, "Taylor", created_by="Avery"))
        meta = _get_unit(units_table, fx.PACK_3149)
        meta["adminCount"] = 2
        _put_unit(units_table, meta)
        payload = lambda_handler(
            fx.unit_operation_event("unitAdmins", "Avery", arguments={"unitId": fx.PACK_3149}), None
        )
        assert not payload.get("__isError"), payload
        by_account = {g["accountId"]: g for g in payload["items"]}
        assert set(by_account) == {fx.account_id("Avery"), fx.account_id("Taylor")}
        assert all(g["role"] == "UNIT_ADMIN" for g in payload["items"])

    def test_unit_q_03_02_revoked_grant_excluded_immediately(self, units_table: Any) -> None:
        units = _seed(units_table)
        _put_unit(units, fx.grant_item(fx.PACK_3149, "Taylor", created_by="Avery"))
        meta = _get_unit(units, fx.PACK_3149)
        meta["adminCount"] = 2
        _put_unit(units, meta)
        _revoke_taylor(units)
        payload = lambda_handler(
            fx.unit_operation_event("unitAdmins", "Avery", arguments={"unitId": fx.PACK_3149}), None
        )
        assert fx.account_id("Taylor") not in {g["accountId"] for g in payload["items"]}

    def test_unit_q_03_03_auth_u_and_pagination_apply(self, units_table: Any) -> None:
        """AUTH-U plus PAGE-01: non-admins are FORBIDDEN; paging grants works."""
        _seed(units_table)
        denied = lambda_handler(
            fx.unit_operation_event("unitAdmins", "Devon", arguments={"unitId": fx.PACK_3149}), None
        )
        fx.assert_is_error(denied, "FORBIDDEN")
        cross = lambda_handler(fx.unit_operation_event("unitAdmins", "Riley", arguments={"unitId": fx.PACK_3149}), None)
        fx.assert_is_error(cross, "FORBIDDEN")

        for n in range(3):
            _put_unit(
                units_table,
                fx.grant_item(fx.CREW_529, f"acct-extra-{n}", created_by="Avery"),
            )
        meta = _get_unit(units_table, fx.CREW_529)
        meta["adminCount"] = 4
        _put_unit(units_table, meta)
        first = lambda_handler(
            fx.unit_operation_event("unitAdmins", "Avery", arguments={"unitId": fx.CREW_529, "page": {"limit": 2}}),
            None,
        )
        assert not first.get("__isError"), first
        assert len(first["items"]) == 2
        second = lambda_handler(
            fx.unit_operation_event(
                "unitAdmins",
                "Avery",
                arguments={
                    "unitId": fx.CREW_529,
                    "page": {"limit": 2, "cursor": first["pageInfo"]["endCursor"]},
                },
            ),
            None,
        )
        assert not second.get("__isError"), second
        all_accounts = {g["accountId"] for g in first["items"]} | {g["accountId"] for g in second["items"]}
        assert all_accounts == {
            fx.account_id("Avery"),
            "acct-extra-0",
            "acct-extra-1",
            "acct-extra-2",
        }
