"""Edge-path contract tests for the ``unit_campaign_operations`` Lambda.

These tests pin the validation, pagination, fault-fallback, dispatch, and
race-replay behavior of every public entry point on the 100%-coverage gate,
complementing the leaf-named suites (``test_unit_campaign_persistence.py``,
``test_unit_campaign_mutations.py``, ``test_unit_campaign_join.py``,
``test_unit_campaign_queries.py``).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.handlers import unit_campaign_operations as ucco
from src.handlers.unit_campaign_operations import lambda_handler
from tests.unit import show_sell_fixtures as fx

FALL_CODE = fx.UNIT_CAMPAIGNS[fx.PACK_3149_FALL]["joinCode"]


def _seed(
    units_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
) -> dict:
    return fx.seed_show_sell_fixtures(
        units_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
    )


def _event(field: str, caller: Any, *, arguments: dict | None = None, input: dict | None = None) -> dict:
    # arguments must stay None for mutations: the fixture builder only wraps
    # ``input`` when arguments is unset.
    return fx.unit_campaign_operation_event(field, caller, arguments=arguments, input=input)


class TestDispatch:
    def test_unknown_field_is_internal_error(self) -> None:
        event = _event("bogusField", "Avery")
        fx.assert_is_error(lambda_handler(event, None), "INTERNAL_ERROR")

    def test_missing_info_field_is_internal_error(self) -> None:
        event = fx.unit_campaign_operation_event("unitCampaigns", "Avery", arguments={"unitId": fx.PACK_3149})
        del event["info"]
        fx.assert_is_error(lambda_handler(event, None), "INTERNAL_ERROR")


class _NoIdentity:
    """Argument-validation and auth edges that need no seeded state."""


class TestValidationEdges:
    def test_create_missing_unit_id(self, units_table: Any) -> None:
        fx.seed_show_sell_fixtures(units_table)
        event = _event(
            "createUnitCampaign",
            "Avery",
            input={
                "campaignName": "x",
                "campaignYear": 2026,
                "catalogId": "CATALOG#fixture-default",
                "idempotency": {"idempotencyKey": "k"},
            },
        )
        fx.assert_is_error(lambda_handler(event, None), "INVALID_INPUT")

    def test_create_missing_catalog_id(self, units_table: Any) -> None:
        fx.seed_show_sell_fixtures(units_table)
        event = _event(
            "createUnitCampaign",
            "Avery",
            input={
                "unitId": fx.PACK_3149,
                "campaignName": "x",
                "campaignYear": 2026,
                "idempotency": {"idempotencyKey": "k"},
            },
        )
        fx.assert_is_error(lambda_handler(event, None), "INVALID_INPUT")

    def test_update_missing_id(self, units_table: Any) -> None:
        fx.seed_show_sell_fixtures(units_table)
        event = _event(
            "updateUnitCampaign",
            "Avery",
            input={"campaignName": "x", "expectedVersion": 1, "idempotency": {"idempotencyKey": "k"}},
        )
        fx.assert_is_error(lambda_handler(event, None), "INVALID_INPUT")

    def test_join_missing_campaign_id(self, units_table: Any) -> None:
        fx.seed_show_sell_fixtures(units_table)
        event = _event(
            "joinUnitCampaign",
            "Avery",
            input={"joinCode": FALL_CODE, "idempotency": {"idempotencyKey": "k"}},
        )
        fx.assert_is_error(lambda_handler(event, None), "INVALID_INPUT")

    def test_remove_missing_unit_campaign_id(self, units_table: Any) -> None:
        fx.seed_show_sell_fixtures(units_table)
        event = _event(
            "removeUnitCampaignMembership",
            "Avery",
            input={
                "profileId": "PROFILE#x",
                "expectedMembershipVersion": 1,
                "expectedGuardVersion": 1,
                "idempotency": {"idempotencyKey": "k"},
            },
        )
        fx.assert_is_error(lambda_handler(event, None), "INVALID_INPUT")

    def test_remove_missing_profile_id(self, units_table: Any) -> None:
        fx.seed_show_sell_fixtures(units_table)
        event = _event(
            "removeUnitCampaignMembership",
            "Avery",
            input={
                "unitCampaignId": "uc-x",
                "expectedMembershipVersion": 1,
                "expectedGuardVersion": 1,
                "idempotency": {"idempotencyKey": "k"},
            },
        )
        fx.assert_is_error(lambda_handler(event, None), "INVALID_INPUT")

    @pytest.mark.parametrize(
        "field,arguments",
        [
            ("unitCampaign", {}),
            ("unitCampaigns", {}),
            ("unitCampaignRoster", {}),
            ("unitCampaignCatalog", {}),
        ],
    )
    def test_query_missing_required_arguments(self, field: str, arguments: dict, units_table: Any) -> None:
        fx.seed_show_sell_fixtures(units_table)
        fx.assert_is_error(lambda_handler(_event(field, "Avery", arguments=arguments), None), "INVALID_INPUT")


class TestAuthEdges:
    @pytest.mark.parametrize(
        "field,input",
        [
            ("createUnitCampaign", {"idempotency": {"idempotencyKey": "k"}}),
            ("updateUnitCampaign", {"idempotency": {"idempotencyKey": "k"}}),
            ("joinUnitCampaign", {"idempotency": {"idempotencyKey": "k"}}),
            ("removeUnitCampaignMembership", {"idempotency": {"idempotencyKey": "k"}}),
        ],
    )
    def test_mutation_without_caller_is_unauthorized(self, field: str, input: dict, units_table: Any) -> None:
        fx.seed_show_sell_fixtures(units_table)
        event = _event(field, "Avery", input=input)
        event["identity"] = None
        fx.assert_is_error(lambda_handler(event, None), "UNAUTHORIZED")

    def test_admin_grant_transport_fault_falls_back_to_forbidden(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The grant read's except-branch: a fault on the GRANT row is not
        admin evidence, so the caller is FORBIDDEN, not crashed."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)

        class _FlakyTable:
            def __init__(self, real: Any) -> None:
                self._real = real

            def get_item(self, **kwargs: Any) -> Any:
                if str(kwargs.get("Key", {}).get("sk", "")).startswith("GRANT#"):
                    raise RuntimeError("injected transport fault")
                return self._real.get_item(**kwargs)

        monkeypatch.setattr(ucco, "_units", lambda: _FlakyTable(units_table))
        payload = lambda_handler(
            _event(
                "updateUnitCampaign",
                "Avery",
                input={
                    "unitCampaignId": fx.PACK_3149_FALL,
                    "campaignName": "x",
                    "expectedVersion": 1,
                    "idempotency": {"idempotencyKey": "k"},
                },
            ),
            None,
        )
        fx.assert_is_error(payload, "FORBIDDEN")


class TestWireHelpers:
    def test_wire_put_without_condition_omits_condition_keys(self) -> None:
        class _Table:
            name = "t"

        action = ucco._wire_put(_Table(), {"pk": "a", "n": 1})
        assert action == {"TableName": "t", "Item": {"pk": {"S": "a"}, "n": {"N": "1"}}}

    def test_find_scout_campaign_base_read_miss_is_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GSI locates a profile key but the consistent base read finds nothing."""

        class _GsiOnly:
            def query(self, **kwargs: Any) -> dict:
                return {"Items": [{"profileId": "PROFILE#ghost"}]}

            def get_item(self, **kwargs: Any) -> dict:
                return {}

        monkeypatch.setattr(ucco, "_campaigns", lambda: _GsiOnly())
        with pytest.raises(ucco.AppError) as excinfo:
            ucco._find_scout_campaign("CAMPAIGN#ghost")
        assert excinfo.value.error_code == "NOT_FOUND"


class TestMembershipIdentity:
    def test_mismatched_membership_profile_conflicts(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """A REMOVED membership row whose profileId does not match the Scout
        campaign's profile is inconsistent state, not a rejoin."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        fx.seed_unit_memberships(units_table)
        devon = fx.PROFILES["Devon"]
        # Overwrite Devon's own membership key with a row whose profileId
        # attribute does not match the Scout campaign's profile: the sk key
        # matches, so the identity check (not the active check) must fire.
        tampered = fx.unit_campaign_membership_item(
            fx.PACK_3149_FALL,
            fx.PACK_3149,
            devon["campaignId"],
            devon["profileId"],
            status="REMOVED",
            joined_by="Devon",
            version=2,
        )
        tampered["profileId"] = "PROFILE#someone-else"
        unit_campaigns_table.put_item(Item=tampered)
        payload = lambda_handler(
            _event(
                "joinUnitCampaign",
                "Devon",
                input={
                    "campaignId": devon["campaignId"],
                    "joinCode": FALL_CODE,
                    "idempotency": {"idempotencyKey": "j"},
                },
            ),
            None,
        )
        fx.assert_is_error(payload, "CONFLICT")


class TestReplayResultLoad:
    def test_replay_whose_membership_row_was_deleted_is_not_found(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """A COMPLETED marker whose result row is gone surfaces NOT_FOUND
        instead of replaying a phantom membership."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        fx.seed_unit_memberships(units_table)
        emery = fx.PROFILES["Emery"]
        join = lambda_handler(
            _event(
                "joinUnitCampaign",
                "Emery",
                input={
                    "campaignId": emery["campaignId"],
                    "joinCode": FALL_CODE,
                    "idempotency": {"idempotencyKey": "j"},
                },
            ),
            None,
        )
        assert not join.get("__isError"), join
        unit_campaigns_table.delete_item(
            Key={"pk": f"UNIT_CAMPAIGN#{fx.PACK_3149_FALL}", "sk": f"MEMBERSHIP#{emery['profileId']}"}
        )
        retry = lambda_handler(
            _event(
                "joinUnitCampaign",
                "Emery",
                input={
                    "campaignId": emery["campaignId"],
                    "joinCode": FALL_CODE,
                    "idempotency": {"idempotencyKey": "j"},
                },
            ),
            None,
        )
        fx.assert_is_error(retry, "NOT_FOUND")


class TestRaceReplay:
    @pytest.mark.parametrize(
        "field, caller, input",
        [
            (
                "createUnitCampaign",
                "Avery",
                {
                    "unitId": fx.PACK_3149,
                    "campaignName": "Race",
                    "campaignYear": 2026,
                    "catalogId": "CATALOG#fixture-default",
                    "idempotency": {"idempotencyKey": "k"},
                },
            ),
            (
                "updateUnitCampaign",
                "Avery",
                {
                    "unitCampaignId": fx.PACK_3149_FALL,
                    "campaignName": "Race",
                    "expectedVersion": 1,
                    "idempotency": {"idempotencyKey": "k"},
                },
            ),
            (
                "joinUnitCampaign",
                "Emery",
                {
                    "campaignId": "CAMPAIGN#camp-emery-fixture",
                    "joinCode": FALL_CODE,
                    "idempotency": {"idempotencyKey": "k"},
                },
            ),
            (
                "removeUnitCampaignMembership",
                "Avery",
                {
                    "unitCampaignId": fx.PACK_3149_FALL,
                    "profileId": "PROFILE#prof-devon-fixture",
                    "expectedMembershipVersion": 1,
                    "expectedGuardVersion": 1,
                    "idempotency": {"idempotencyKey": "k"},
                },
            ),
        ],
    )
    def test_execute_race_replay_returns_the_stored_result(
        self,
        field: str,
        caller: str,
        input: dict,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If the marker completes between the replay gate and the transaction,
        execute answers with the stored result dict and the handler returns it."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        fx.seed_unit_memberships(units_table)
        stored = {"sentinel": "stored-result"}
        monkeypatch.setattr(
            ucco.IdempotentMutationRunner,
            "execute",
            lambda self, mk, plan, **kwargs: stored,
        )
        payload = lambda_handler(_event(field, caller, input=input), None)
        assert payload == stored


class TestPaginationClamps:
    def test_limit_and_cursor_garbage_clamps(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        base = {"unitId": fx.PACK_3149}
        # Non-integer limit falls back to the 50 default; both rows come back.
        payload = lambda_handler(_event("unitCampaigns", "Avery", arguments={**base, "page": {"limit": "bogus"}}), None)
        assert len(payload["items"]) == 2
        # A limit below 1 clamps to 1; above 100 clamps to 100.
        payload = lambda_handler(_event("unitCampaigns", "Avery", arguments={**base, "page": {"limit": 0}}), None)
        assert len(payload["items"]) == 1
        payload = lambda_handler(_event("unitCampaigns", "Avery", arguments={**base, "page": {"limit": 500}}), None)
        assert len(payload["items"]) == 2
        # An unparseable cursor restarts at zero instead of erroring.
        payload = lambda_handler(
            _event("unitCampaigns", "Avery", arguments={**base, "page": {"cursor": "not-a-number"}}), None
        )
        assert len(payload["items"]) == 2
