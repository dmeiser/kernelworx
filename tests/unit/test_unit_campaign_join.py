"""Leaves 1.5.4/1.5.5: joinUnitCampaign and removeUnitCampaignMembership.

Named contract tests:

- CAMP-M-03: joinUnitCampaign. The caller must hold WRITE access to the Scout
  campaign (ownership or WRITE share), the join code must resolve to an active
  Unit Campaign in the caller's Unit, and the Scout campaign's guard must not
  already point at a different active Unit Campaign. The join commits the
  membership row, the guard update, and the Campaign joined-scope link in ONE
  DynamoDB transaction (§8.2, all-or-nothing). A removed Scout campaign may
  rejoin and reactivates the same membership row. Retries replay (IDEM-01),
  reused keys with different arguments are rejected (IDEM-02), and unknown or
  inactive codes are NOT_FOUND (CAMP-M-03-04).
- CAMP-M-04: removeUnitCampaignMembership. Unit Admins remove memberships with
  an expected-membership/guard version pair (VER-01 stale -> CONFLICT); the
  membership is retained with REMOVED status and the guard target is cleared,
  but the Campaign keeps its joined-scope link and Orders keep theirs
  (API-FIX-05).
"""

from __future__ import annotations

from typing import Any

from src.handlers.unit_campaign_operations import lambda_handler
from tests.unit import show_sell_fixtures as fx

FALL_CODE = fx.UNIT_CAMPAIGNS[fx.PACK_3149_FALL]["joinCode"]
SPRING_CODE = fx.UNIT_CAMPAIGNS[fx.CREW_529_SPRING]["joinCode"]
OLD_CODE = fx.UNIT_CAMPAIGNS[fx.PACK_3149_OLD]["joinCode"]

# A second ACTIVE Pack 3149 Unit Campaign, seeded locally where a test needs
# two join targets inside the same Unit (the shared fixtures carry only one
# active campaign per Unit).
WINTER_ID = "uc-pack-3149-winter-2026"
WINTER_CODE = "JOINPK3149WINT26"


def _seed_second_pack_campaign(unit_campaigns_table: Any) -> None:
    unit_campaigns_table.put_item(
        Item=fx.unit_campaign_item(
            WINTER_ID,
            unit_id=fx.PACK_3149,
            campaign_name="Winter Sale",
            campaign_year=2026,
            catalog_id="CATALOG#fixture-default",
            join_code=WINTER_CODE,
            created_by="Avery",
        )
    )
    unit_campaigns_table.put_item(Item=fx.join_code_pointer_item(WINTER_CODE, WINTER_ID))


def _seed(
    units_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
) -> dict:
    seeded = fx.seed_show_sell_fixtures(
        units_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
    )
    # joinUnitCampaign gates on units-table ACTIVE membership (§5.2); seeded
    # explicitly because batch A cascade tests require an empty units table.
    fx.seed_unit_memberships(units_table)
    return seeded


def _join_event(
    caller: str,
    *,
    campaign_id: str,
    join_code: str,
    key: str = "join-key-1",
) -> dict:
    return fx.unit_campaign_operation_event(
        "joinUnitCampaign",
        caller,
        input={
            "campaignId": campaign_id,
            "joinCode": join_code,
            "idempotency": {"idempotencyKey": key},
        },
    )


def _join(caller: str, **kwargs: Any) -> Any:
    return lambda_handler(_join_event(caller, **kwargs), None)


def _membership_row(unit_campaigns_table: Any, unit_campaign_id: str, profile_id: str) -> dict:
    return unit_campaigns_table.get_item(
        Key={"pk": f"UNIT_CAMPAIGN#{unit_campaign_id}", "sk": f"MEMBERSHIP#{profile_id}"}, ConsistentRead=True
    )["Item"]


def _guard_row(unit_campaigns_table: Any, campaign_id: str) -> dict:
    return unit_campaigns_table.get_item(
        Key={"pk": f"SCOUT_CAMPAIGN#{campaign_id}", "sk": "MEMBERSHIP_GUARD"}, ConsistentRead=True
    )["Item"]


def _campaign_row(campaigns_table: Any, profile_id: str, campaign_id: str) -> dict:
    return campaigns_table.get_item(Key={"profileId": profile_id, "campaignId": campaign_id}, ConsistentRead=True)[
        "Item"
    ]


# ---------------------------------------------------------------------------
# CAMP-M-03: joinUnitCampaign
# ---------------------------------------------------------------------------


class TestJoinUnitCampaign:
    def test_owner_joins_their_campaign_and_all_three_rows_commit_together(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """Emery (never joined) joins the FALL campaign: membership, guard, and
        Campaign link all land in the single §8.2 transaction."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        emery = fx.PROFILES["Emery"]
        payload = _join("Emery", campaign_id=emery["campaignId"], join_code=FALL_CODE)
        assert not payload.get("__isError"), payload
        assert payload["status"] == "ACTIVE"
        assert payload["version"] == 1
        assert payload["joinedByAccountId"] == fx.account_id("Emery")
        assert payload["unitCampaignId"] == fx.PACK_3149_FALL

        membership = _membership_row(unit_campaigns_table, fx.PACK_3149_FALL, emery["profileId"])
        assert membership["status"] == "ACTIVE"
        assert membership["campaignId"] == emery["campaignId"]
        guard = _guard_row(unit_campaigns_table, emery["campaignId"])
        assert guard["activeUnitCampaignId"] == fx.PACK_3149_FALL
        assert guard["membershipVersion"] == 1
        # ORD-API-01-01: the joined-scope link is what order creation captures.
        campaign = _campaign_row(campaigns_table, emery["profileId"], emery["campaignId"])
        assert campaign["unitId"] == fx.PACK_3149
        assert campaign["unitCampaignId"] == fx.PACK_3149_FALL

    def test_write_share_holder_can_join_on_behalf(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """Taylor holds a WRITE share on Avery's campaign (seeded here) and may
        join it; the membership is per Scout campaign, so a campaign whose
        owner already joined cannot take a second membership."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        shares_table.put_item(Item=fx.share_item("Avery", "Taylor", "WRITE"))
        avery = fx.PROFILES["Avery"]
        payload = _join("Taylor", campaign_id=avery["campaignId"], join_code=FALL_CODE)
        assert not payload.get("__isError"), payload
        assert payload["joinedByAccountId"] == fx.account_id("Taylor")
        membership = _membership_row(unit_campaigns_table, fx.PACK_3149_FALL, avery["profileId"])
        assert membership["status"] == "ACTIVE"

    def test_read_only_share_holder_cannot_join(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        avery = fx.PROFILES["Avery"]
        payload = _join("Riley", campaign_id=avery["campaignId"], join_code=FALL_CODE)
        assert payload == {
            "__isError": True,
            "errorCode": "FORBIDDEN",
            "message": "Write access to the campaign profile is required",
        }

    def test_substituting_a_morgan_campaign_is_forbidden(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """Taylor may WRITE Devon's campaign but not Emery's: the guard must be
        per Scout campaign, not per caller."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        emery = fx.PROFILES["Emery"]
        payload = _join("Taylor", campaign_id=emery["campaignId"], join_code=FALL_CODE)
        assert payload["errorCode"] == "FORBIDDEN", payload

    def test_unknown_campaign_is_not_found(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        fx.assert_is_error(_join("Emery", campaign_id="CAMPAIGN#ghost", join_code=FALL_CODE), "NOT_FOUND")

    def test_guard_rejects_a_second_active_membership_for_the_same_scout_campaign(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """Devon is ACTIVE in FALL; joining Devon's campaign to the Winter
        campaign (same Unit, valid code, WRITE access) still conflicts: the
        guard allows at most one ACTIVE membership per Scout campaign."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        _seed_second_pack_campaign(unit_campaigns_table)
        devon = fx.PROFILES["Devon"]
        payload = _join("Devon", campaign_id=devon["campaignId"], join_code=WINTER_CODE)
        assert payload == {
            "__isError": True,
            "errorCode": "CONFLICT",
            "message": "This campaign already has an active Unit Campaign membership",
        }
        # Nothing moved.
        guard = _guard_row(unit_campaigns_table, devon["campaignId"])
        assert guard["activeUnitCampaignId"] == fx.PACK_3149_FALL

    def test_duplicate_join_of_the_same_target_conflicts(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        devon = fx.PROFILES["Devon"]
        payload = _join("Devon", campaign_id=devon["campaignId"], join_code=FALL_CODE)
        assert payload["errorCode"] == "CONFLICT", payload

    def test_unknown_and_inactive_codes_are_not_found(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """CAMP-M-03-04: unknown, malformed, and inactive codes all resolve to
        NOT_FOUND without disclosing other Units."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        emery = fx.PROFILES["Emery"]
        for code in ("ZZZZ9999ZZZZ9999", "SHORT", OLD_CODE):
            payload = _join("Emery", campaign_id=emery["campaignId"], join_code=code)
            fx.assert_is_error(payload, "NOT_FOUND")
        # Emery is still unjoined.
        guard = _guard_row(unit_campaigns_table, emery["campaignId"])
        assert "activeUnitCampaignId" not in guard

    def test_code_from_another_unit_is_not_found(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """Emery belongs to Pack 3149; Crew 529's code must not be redeemable."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        emery = fx.PROFILES["Emery"]
        payload = _join("Emery", campaign_id=emery["campaignId"], join_code=SPRING_CODE)
        fx.assert_is_error(payload, "NOT_FOUND")

    def test_missing_idempotency_key_is_invalid_input(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        emery = fx.PROFILES["Emery"]
        event = fx.unit_campaign_operation_event(
            "joinUnitCampaign",
            "Emery",
            input={"campaignId": emery["campaignId"], "joinCode": FALL_CODE},
        )
        fx.assert_is_error(lambda_handler(event, None), "INVALID_INPUT")

    def test_idempotent_retry_replays_the_membership(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        emery = fx.PROFILES["Emery"]
        first = _join("Emery", campaign_id=emery["campaignId"], join_code=FALL_CODE)
        assert not first.get("__isError"), first
        retry = _join("Emery", campaign_id=emery["campaignId"], join_code=FALL_CODE)
        assert retry == first
        emery_profile_rows = [
            i
            for i in unit_campaigns_table.query(
                KeyConditionExpression="pk = :pk",
                ExpressionAttributeValues={":pk": f"UNIT_CAMPAIGN#{fx.PACK_3149_FALL}"},
            )["Items"]
            if i["sk"] == f"MEMBERSHIP#{emery['profileId']}"
        ]
        assert len(emery_profile_rows) == 1

    def test_reused_key_with_different_arguments_is_rejected(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """IDEM-02: the marker is scoped to the join code, so the same key with
        the same code but a different campaignId is a fingerprint mismatch."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        emery = fx.PROFILES["Emery"]
        devon = fx.PROFILES["Devon"]
        first = _join("Emery", campaign_id=emery["campaignId"], join_code=FALL_CODE)
        assert not first.get("__isError"), first
        payload = lambda_handler(
            fx.unit_campaign_operation_event(
                "joinUnitCampaign",
                "Emery",
                input={
                    "campaignId": devon["campaignId"],
                    "joinCode": FALL_CODE,
                    "idempotency": {"idempotencyKey": "join-key-1"},
                },
            ),
            None,
        )
        fx.assert_is_error(payload, "INVALID_INPUT")

    def test_rejoin_after_removal_reactivates_the_same_row(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """Devon's FALL membership is REMOVED at v2; rejoining FALL reactivates
        the SAME row at v3, clearing removedBy/removedAt, and the guard
        re-points at FALL — the Campaign link is retained, not rewritten."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        devon = fx.PROFILES["Devon"]
        removed = lambda_handler(
            _remove_event("Avery", unit_campaign_id=fx.PACK_3149_FALL, profile_id=devon["profileId"]), None
        )
        assert not removed.get("__isError"), removed
        payload = _join("Devon", campaign_id=devon["campaignId"], join_code=FALL_CODE, key="join-key-9")
        assert not payload.get("__isError"), payload
        assert payload["status"] == "ACTIVE"
        assert payload["version"] == 3
        membership = _membership_row(unit_campaigns_table, fx.PACK_3149_FALL, devon["profileId"])
        assert membership["version"] == 3
        assert "removedByAccountId" not in membership
        assert "removedAt" not in membership
        guard = _guard_row(unit_campaigns_table, devon["campaignId"])
        assert guard["activeUnitCampaignId"] == fx.PACK_3149_FALL
        assert guard["membershipVersion"] == 3


# ---------------------------------------------------------------------------
# CAMP-M-04: removeUnitCampaignMembership
# ---------------------------------------------------------------------------


def _remove_event(
    caller: str,
    *,
    unit_campaign_id: str,
    profile_id: str,
    membership_version: Any = 1,
    guard_version: Any = 1,
    key: str = "remove-key-1",
) -> dict:
    return fx.unit_campaign_operation_event(
        "removeUnitCampaignMembership",
        caller,
        input={
            "unitCampaignId": unit_campaign_id,
            "profileId": profile_id,
            "expectedMembershipVersion": membership_version,
            "expectedGuardVersion": guard_version,
            "idempotency": {"idempotencyKey": key},
        },
    )


class TestRemoveUnitCampaignMembership:
    def test_admin_removes_and_history_is_retained(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        devon = fx.PROFILES["Devon"]
        payload = lambda_handler(
            _remove_event("Avery", unit_campaign_id=fx.PACK_3149_FALL, profile_id=devon["profileId"]), None
        )
        assert not payload.get("__isError"), payload
        assert payload["status"] == "REMOVED"
        assert payload["version"] == 2
        assert payload["removedByAccountId"] == fx.account_id("Avery")
        assert payload["removedAt"]

        membership = _membership_row(unit_campaigns_table, fx.PACK_3149_FALL, devon["profileId"])
        assert membership["status"] == "REMOVED"
        guard = _guard_row(unit_campaigns_table, devon["campaignId"])
        assert "activeUnitCampaignId" not in guard
        assert guard["membershipVersion"] == 2
        # API-FIX-05: the Campaign link is retained, so historical orders keep
        # their scope.
        campaign = _campaign_row(campaigns_table, devon["profileId"], devon["campaignId"])
        assert campaign["unitId"] == fx.PACK_3149
        assert campaign["unitCampaignId"] == fx.PACK_3149_FALL

    def test_non_admin_cannot_remove(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        devon = fx.PROFILES["Devon"]
        payload = lambda_handler(
            _remove_event("Devon", unit_campaign_id=fx.PACK_3149_FALL, profile_id=devon["profileId"]), None
        )
        assert payload == {
            "__isError": True,
            "errorCode": "FORBIDDEN",
            "message": "Unit Admin required",
        }

    def test_unknown_membership_is_not_found(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        fx.assert_is_error(
            lambda_handler(
                _remove_event("Avery", unit_campaign_id=fx.PACK_3149_FALL, profile_id="PROFILE#ghost"), None
            ),
            "NOT_FOUND",
        )

    def test_missing_guard_is_not_found(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """A membership row without its guard is an inconsistent state."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        unit_campaigns_table.put_item(
            Item=fx.unit_campaign_membership_item(
                fx.PACK_3149_FALL,
                "unit-pack-3149-aurora",
                "CAMPAIGN#orphan",
                "PROFILE#orphan",
                joined_by="Avery",
                version=1,
            )
        )
        fx.assert_is_error(
            lambda_handler(
                _remove_event("Avery", unit_campaign_id=fx.PACK_3149_FALL, profile_id="PROFILE#orphan"), None
            ),
            "NOT_FOUND",
        )

    def test_stale_membership_version_conflicts(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        devon = fx.PROFILES["Devon"]
        payload = lambda_handler(
            _remove_event(
                "Avery",
                unit_campaign_id=fx.PACK_3149_FALL,
                profile_id=devon["profileId"],
                membership_version=9,
            ),
            None,
        )
        fx.assert_is_error(payload, "CONFLICT")
        membership = _membership_row(unit_campaigns_table, fx.PACK_3149_FALL, devon["profileId"])
        assert membership["status"] == "ACTIVE"

    def test_stale_guard_version_conflicts(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        devon = fx.PROFILES["Devon"]
        payload = lambda_handler(
            _remove_event(
                "Avery",
                unit_campaign_id=fx.PACK_3149_FALL,
                profile_id=devon["profileId"],
                guard_version=7,
            ),
            None,
        )
        fx.assert_is_error(payload, "CONFLICT")

    def test_invalid_version_types_are_rejected(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        devon = fx.PROFILES["Devon"]
        for field in ("membership_version", "guard_version"):
            payload = lambda_handler(
                _remove_event(
                    "Avery",
                    unit_campaign_id=fx.PACK_3149_FALL,
                    profile_id=devon["profileId"],
                    **{field: "1"},
                ),
                None,
            )
            fx.assert_is_error(payload, "INVALID_INPUT")

    def test_retry_replays_the_removed_membership(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        devon = fx.PROFILES["Devon"]
        event = _remove_event("Avery", unit_campaign_id=fx.PACK_3149_FALL, profile_id=devon["profileId"])
        first = lambda_handler(event, None)
        assert not first.get("__isError"), first
        retry = lambda_handler(
            _remove_event("Avery", unit_campaign_id=fx.PACK_3149_FALL, profile_id=devon["profileId"]), None
        )
        assert retry == first

    def test_removed_scout_campaign_can_rejoin_elsewhere(
        self,
        units_table: Any,
        profiles_table: Any,
        campaigns_table: Any,
        shares_table: Any,
        unit_campaigns_table: Any,
        catalogs_table: Any,
    ) -> None:
        """After removal Devon may join the Winter campaign: the guard was the
        only lock, and removal already cleared it. The FALL row stays REMOVED
        history and the Campaign link keeps pointing at FALL."""
        _seed(units_table, profiles_table, campaigns_table, shares_table, unit_campaigns_table, catalogs_table)
        _seed_second_pack_campaign(unit_campaigns_table)
        devon = fx.PROFILES["Devon"]
        removed = lambda_handler(
            _remove_event("Avery", unit_campaign_id=fx.PACK_3149_FALL, profile_id=devon["profileId"]), None
        )
        assert not removed.get("__isError"), removed
        joined = _join("Devon", campaign_id=devon["campaignId"], join_code=WINTER_CODE, key="join-key-9")
        assert not joined.get("__isError"), joined
        assert joined["unitCampaignId"] == WINTER_ID
        assert joined["version"] == 1
        guard = _guard_row(unit_campaigns_table, devon["campaignId"])
        assert guard["activeUnitCampaignId"] == WINTER_ID
        assert guard["membershipVersion"] == 1
        # FALL membership row is untouched REMOVED history.
        fall_membership = _membership_row(unit_campaigns_table, fx.PACK_3149_FALL, devon["profileId"])
        assert fall_membership["status"] == "REMOVED"
        assert fall_membership["version"] == 2
        # The Campaign link tracks the CURRENT join (what new orders capture);
        # retention applies to removal, not to rejoining elsewhere.
        campaign = _campaign_row(campaigns_table, devon["profileId"], devon["campaignId"])
        assert campaign["unitId"] == fx.PACK_3149
        assert campaign["unitCampaignId"] == WINTER_ID
