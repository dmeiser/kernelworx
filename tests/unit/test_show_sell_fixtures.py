"""Leaf 1.7.4: lane-safe personas and cross-lane non-deletion (FIX-AC-01..06).

The fixture module (``tests/unit/show_sell_fixtures.py``) provisions six
personas with concrete cross-lane data: accounts, profiles, campaigns, units,
grants, and invites in the key shapes the data model defines (§5.1-5.3,
§6.1). These tests consume the personas and prove the cross-lane
non-deletion guarantee: the test-only Unit cascade removes all and only one
lane's fixture data and never touches another lane's.
"""

from __future__ import annotations

from typing import Any

from tests.unit import show_sell_fixtures as fx
from tests.unit.show_sell_fixtures import (
    CREW_529,
    PACK_3149,
    TROOP_7150,
    all_personas,
    cascade_delete_unit,
    seed_show_sell_fixtures,
    snapshot_units,
)


def _full_seed(units_table: Any, profiles_table: Any, campaigns_table: Any, shares_table: Any) -> dict:
    return seed_show_sell_fixtures(
        units_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )


def _keys(table: Any) -> set:
    """Identity keys of every row, per table shape, for unchanged-set assertions."""
    resp = table.scan()
    keys = set()
    for item in resp.get("Items", []):
        if "pk" in item:
            keys.add(f"{item['pk']}|{item.get('sk', '')}")
        elif "targetAccountId" in item:
            keys.add(f"{item['profileId']}|{item['targetAccountId']}")
        elif "ownerAccountId" in item:
            keys.add(f"{item['ownerAccountId']}|{item['profileId']}")
        else:
            keys.add(repr(sorted(item)))
    return keys


class TestFixAc01PersonaProvisioning:
    def test_fix_ac_01_six_personas_with_accounts_roles_and_profiles(self) -> None:
        """Every persona has a deterministic account identity, a role, and no global-admin status."""
        personas = all_personas()
        assert set(personas) == {"Blake", "Taylor", "Riley", "Avery", "Devon", "Emery"}
        expected_roles = {
            "Blake": "removed_admin",
            "Taylor": "non_owner_write",
            "Riley": "read_only_share_on_avery",
            "Avery": "multi_unit_owner",
            "Devon": "campaign_joiner",
            "Emery": "independent",
        }
        for name, persona in personas.items():
            assert persona["role"] == expected_roles[name]
            assert persona["accountId"].count("-") == 4  # deterministic Cognito-sub shape
            assert "@fixtures.kernelworx.test" in persona["email"]
            # Lane users are never global application ADMINs.
            assert "global" not in persona["role"]
        assert len({p["accountId"] for p in personas.values()}) == 6


class TestFixAc02ScoutCampaigns:
    def test_fix_ac_02_named_scouts_campaigns_and_shares_seed(
        self, units_table: Any, profiles_table: Any, campaigns_table: Any, shares_table: Any
    ) -> None:
        """Profiles and Scout Campaigns exist for every persona; shares carry the right levels."""
        manifest = _full_seed(units_table, profiles_table, campaigns_table, shares_table)
        assert {p["sellerName"] for p in manifest["profiles"]} == {
            f"{name} Scout Fixture" for name in ("Avery", "Blake", "Devon", "Emery", "Riley", "Taylor")
        }
        assert len(manifest["campaigns"]) == 6
        shares = {(s["profileId"], s["targetAccountId"], s["permissions"][0]) for s in manifest["shares"]}
        assert shares == {
            (fx.PROFILES["Avery"]["profileId"], f"ACCOUNT#{fx.account_id('Riley')}", "READ"),
            (fx.PROFILES["Devon"]["profileId"], f"ACCOUNT#{fx.account_id('Taylor')}", "WRITE"),
        }


class TestFixAcCrossLaneNonDeletion:
    def test_fix_ac_03_pack_cascade_leaves_other_lanes_untouched(
        self, units_table: Any, profiles_table: Any, campaigns_table: Any, shares_table: Any
    ) -> None:
        """Cascading Pack 3149 removes only its items; Crew 529, Troop 7150, personas survive."""
        _full_seed(units_table, profiles_table, campaigns_table, shares_table)
        before = snapshot_units(units_table)
        profiles_before = _keys(profiles_table)
        shares_before = _keys(shares_table)

        cascade_delete_unit(units_table, PACK_3149)

        after = snapshot_units(units_table)
        removed = set(before) - set(after)
        assert all(k.startswith(f"UNIT#{PACK_3149}") or k.startswith("INVITE#PKT3149") for k in removed)
        assert removed  # the cascade actually removed Pack 3149 data
        # Every other lane's rows are byte-identical.
        for key, item in before.items():
            if key in after:
                assert after[key] == item, key
        assert any(k.startswith(f"UNIT#{CREW_529}") for k in after)
        assert any(k.startswith(f"UNIT#{TROOP_7150}") for k in after)
        assert _keys(profiles_table) == profiles_before
        assert _keys(shares_table) == shares_before

    def test_fix_ac_04_crew_cascade_preserves_averys_pack_and_blake_taylor_lanes(
        self, units_table: Any, profiles_table: Any, campaigns_table: Any, shares_table: Any
    ) -> None:
        _full_seed(units_table, profiles_table, campaigns_table, shares_table)
        campaigns_before = _keys(campaigns_table)
        cascade_delete_unit(units_table, CREW_529)
        after = snapshot_units(units_table)
        assert not any(k.startswith(f"UNIT#{CREW_529}") for k in after)
        assert any(k.startswith(f"UNIT#{PACK_3149}") for k in after)
        assert any(k.startswith(f"UNIT#{TROOP_7150}") for k in after)
        assert _keys(campaigns_table) == campaigns_before
        # Avery's Pack 3149 grant row survives her own Crew 529 cleanup.
        assert f"UNIT#{PACK_3149}|GRANT#{fx.account_id('Avery')}" in after

    def test_fix_ac_05_troop_cascade_preserves_rileys_read_share_on_avery(
        self, units_table: Any, profiles_table: Any, campaigns_table: Any, shares_table: Any
    ) -> None:
        """Riley's Unit cleanup never reaches Avery's profile or Riley's share on it."""
        _full_seed(units_table, profiles_table, campaigns_table, shares_table)
        shares_before = _keys(shares_table)
        cascade_delete_unit(units_table, TROOP_7150)
        after = snapshot_units(units_table)
        assert not any(k.startswith(f"UNIT#{TROOP_7150}") for k in after)
        assert any(k.startswith(f"UNIT#{PACK_3149}") for k in after)
        assert _keys(shares_table) == shares_before
        assert _keys(profiles_table) == {
            f"ACCOUNT#{fx.account_id(name)}|PROFILE#prof-{name.lower()}-fixture"
            for name in ("Avery", "Blake", "Devon", "Emery", "Riley", "Taylor")
        }

    def test_fix_ac_06_full_fixture_teardown_removes_only_fixture_items(
        self, units_table: Any, profiles_table: Any, campaigns_table: Any, shares_table: Any
    ) -> None:
        """Cascading every fixture Unit empties the units table and touches no other table."""
        _full_seed(units_table, profiles_table, campaigns_table, shares_table)
        profiles_before = _keys(profiles_table)
        campaigns_before = _keys(campaigns_table)
        shares_before = _keys(shares_table)
        for unit_id in (PACK_3149, CREW_529, TROOP_7150):
            cascade_delete_unit(units_table, unit_id)
        assert snapshot_units(units_table) == {}
        assert _keys(profiles_table) == profiles_before
        assert _keys(campaigns_table) == campaigns_before
        assert _keys(shares_table) == shares_before
