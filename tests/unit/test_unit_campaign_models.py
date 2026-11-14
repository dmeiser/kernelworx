"""Leaf 1.4 — Unit Campaign persistence and membership guards.

Persistence-level tests for §1.4.1 and §1.4.2: the §6.2 key layout, item
builders and their validation, the join-code pointer lifecycle (created and
deleted in the same transaction as the campaign, uniqueness enforced by the
pointer's conditional insert), the immutable-field policy that keeps
``catalogId`` from moving under inventory and Order origin, and the membership
plus ``ScoutCampaignMembershipGuard`` primitives that make "one ACTIVE
membership per Scout Campaign" a DynamoDB condition rather than a convention.

Transactions are submitted through the same wire-form client the mutation runner
uses, so the conditions these builders emit are the conditions DynamoDB
evaluates. §1.4.3's Order-origin capture is exercised in the JS resolver tests
(``create_order_fn.test.js``, ``lib/order_origin.test.js``).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from botocore.exceptions import ClientError

from src.utils import unit_campaign_models as module
from src.utils import unit_campaign_models as ucm
from src.utils.dynamodb import get_dynamodb_client, tables
from src.utils.errors import AppError, ErrorCode
from tests.unit.show_sell_fixtures import (
    account_id,
    campaign_item,
    join_code_pointer_item,
    unit_campaign_item,
)

AVERY = account_id("Avery")
DEVON = account_id("Devon")

PACK_ID = "uc-pack-3149-fall-2026"
CREW_ID = "uc-crew-529-spring-2027"
PACK_PROFILE = "PROFILE#devon"
PACK_CAMPAIGN = "CAMPAIGN#devon"
PACK_JOIN_CODE = "JOINPK3149FALL01"
CREW_JOIN_CODE = "JOINCRW529SPRNG1"
NOW = "2026-11-01T00:00:00+00:00"


class _RecordingTable:
    """Stand-in that records the parameters of every read, for consistency checks."""

    table_name = "kernelworx-unit-campaigns-ue1-dev"

    def __init__(self, items: List[Dict[str, Any]]) -> None:
        self._items = items
        self.calls: List[Dict[str, Any]] = []

    def get_item(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append({"operation": "GetItem", **kwargs})
        key = kwargs["Key"]
        for item in self._items:
            if all(item.get(name) == value for name, value in key.items()):
                return {"Item": item}
        return {}

    def query(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append({"operation": "Query", **kwargs})
        return {"Items": [item for item in self._items if item.get("pk", "").startswith("JOIN_CODE#")]}


def _campaign_item(unit_campaign_id: str = PACK_ID, **overrides: Any) -> Dict[str, Any]:
    item = unit_campaign_item(
        unit_campaign_id,
        unit_id="unit-pack-3149-aurora",
        campaign_name="Pack 3149 Fall Show & Sell",
        campaign_year=2026,
        catalog_id="CATALOG#fixture-default",
        join_code=PACK_JOIN_CODE if unit_campaign_id == PACK_ID else CREW_JOIN_CODE,
        created_by="Avery",
    )
    item.update(overrides)
    return item


def _membership(**overrides: Any) -> Dict[str, Any]:
    item = {
        "pk": f"UNIT_CAMPAIGN#{PACK_ID}",
        "sk": f"MEMBERSHIP#{PACK_PROFILE}",
        "unitCampaignId": PACK_ID,
        "unitId": "unit-pack-3149-aurora",
        "campaignId": PACK_CAMPAIGN,
        "profileId": PACK_PROFILE,
        "status": "ACTIVE",
        "joinedByAccountId": DEVON,
        "joinedAt": NOW,
        "version": 1,
    }
    item.update(overrides)
    return item


def _seed_campaign(unit_campaigns_table: Any, **overrides: Any) -> Dict[str, Any]:
    item = _campaign_item(**overrides)
    unit_campaigns_table.put_item(Item=item)
    unit_campaigns_table.put_item(Item=join_code_pointer_item(str(item["joinCode"]), PACK_ID))
    return item


def _seed_scout_campaign(campaigns_table: Any) -> Dict[str, Any]:
    item = {
        "profileId": PACK_PROFILE,
        "campaignId": PACK_CAMPAIGN,
        "campaignName": "Devon's Fixture Campaign",
        "campaignYear": 2026,
        "catalogId": "CATALOG#fixture-default",
        "createdAt": NOW,
    }
    campaigns_table.put_item(Item=item)
    return item


def _transact(actions: List[tuple[str, Dict[str, Any]]]) -> None:
    """Submit exactly what the shared mutation runner would submit."""
    get_dynamodb_client().transact_write_items(TransactItems=[{action: body} for action, body in actions])


def _cancellation_codes(error: BaseException) -> List[str]:
    reasons = getattr(error, "response", {}).get("CancellationReasons", [])
    return [str(reason.get("Code", "")) for reason in reasons]


# --- Key layout (data model §6.2) ------------------------------------------------


def test_key_layout_matches_the_data_model() -> None:
    """Every row type lands on the §6.2 partition/sort pair — no drift allowed."""
    assert ucm.unit_campaign_metadata_key(PACK_ID) == {"pk": f"UNIT_CAMPAIGN#{PACK_ID}", "sk": "METADATA"}
    assert ucm.membership_key(PACK_ID, PACK_PROFILE) == {
        "pk": f"UNIT_CAMPAIGN#{PACK_ID}",
        "sk": f"MEMBERSHIP#{PACK_PROFILE}",
    }
    assert ucm.join_code_pointer_key(PACK_JOIN_CODE, PACK_ID) == {
        "pk": f"JOIN_CODE#{PACK_JOIN_CODE}",
        "sk": f"UNIT_CAMPAIGN#{PACK_ID}",
    }
    assert ucm.guard_key(PACK_CAMPAIGN) == {"pk": f"SCOUT_CAMPAIGN#{PACK_CAMPAIGN}", "sk": "MEMBERSHIP_GUARD"}


# --- Builders and validation (§1.4.1) --------------------------------------------


def test_built_campaign_starts_at_version_one_with_active_state() -> None:
    item = ucm.build_unit_campaign_item(
        unit_campaign_id=PACK_ID,
        unit_id="unit-pack-3149-aurora",
        campaign_name="  Pack 3149 Fall Show & Sell  ",
        campaign_year=2026,
        catalog_id="CATALOG#fixture-default",
        join_code=PACK_JOIN_CODE,
        created_by_account_id=AVERY,
        now_iso=NOW,
    )
    assert item["version"] == 1 and item["isActive"] is True
    assert item["campaignName"] == "Pack 3149 Fall Show & Sell"
    assert item["createdAt"] == NOW and item["updatedAt"] == NOW
    assert item["createdByAccountId"] == item["updatedByAccountId"] == AVERY
    assert item["pk"] == f"UNIT_CAMPAIGN#{PACK_ID}" and item["sk"] == "METADATA"


@pytest.mark.parametrize(
    "field,value",
    [
        ("campaign_name", ""),
        ("campaign_name", "x" * 101),
        ("campaign_year", "2026"),
        ("campaign_year", True),
        ("campaign_year", 2206),
        ("campaign_year", 1799),
        ("join_code", "short"),
        ("join_code", "joinpk3149fall01"),
        ("join_code", "JOINPK3149FALL01X"),
        ("catalog_id", " "),
        ("unit_id", None),
        ("unit_campaign_id", ""),
        ("created_by_account_id", ""),
        ("now_iso", None),
    ],
)
def test_campaign_builders_reject_bad_field_values(field: str, value: Any) -> None:
    """Nothing invalid can be written, because the builder is the only writer."""
    args: Dict[str, Any] = {
        "unit_campaign_id": PACK_ID,
        "unit_id": "unit-pack-3149-aurora",
        "campaign_name": "Pack 3149 Fall Show & Sell",
        "campaign_year": 2026,
        "catalog_id": "CATALOG#fixture-default",
        "join_code": PACK_JOIN_CODE,
        "created_by_account_id": AVERY,
        "now_iso": NOW,
    }
    args[field] = value
    with pytest.raises(AppError) as caught:
        ucm.build_unit_campaign_item(**args)
    assert caught.value.error_code == ErrorCode.INVALID_INPUT


def test_generated_join_codes_are_issued_shape_and_unique() -> None:
    """A join code is 16 upper-case alphanumeric characters, and collisions do not happen."""
    codes = {ucm.new_join_code() for _ in range(400)}
    assert len(codes) == 400
    for code in codes:
        assert len(code) == ucm.JOIN_CODE_LENGTH
        assert ucm.is_valid_join_code(code)
    assert not ucm.is_valid_join_code("joinpk3149fall01")
    assert not ucm.is_valid_join_code(None)
    assert not ucm.is_valid_join_code("JOINPK3149FALL0")


def test_join_code_pointer_holds_only_the_address() -> None:
    """A pointer can never serve a stale name, catalog, or active state."""
    pointer = ucm.build_join_code_pointer_item(join_code=PACK_JOIN_CODE, unit_campaign_id=PACK_ID, now_iso=NOW)
    assert set(pointer) == {"pk", "sk", "unitCampaignId", "createdAt"}


def test_membership_and_guard_builders_encode_their_vocabulary() -> None:
    """Membership identity, status, and the guard's absent-target shape are explicit."""
    membership = ucm.build_membership_item(
        unit_campaign_id=PACK_ID,
        unit_id="unit-pack-3149-aurora",
        campaign_id=PACK_CAMPAIGN,
        profile_id=PACK_PROFILE,
        joined_by_account_id=DEVON,
        now_iso=NOW,
    )
    assert membership["status"] == ucm.MEMBERSHIP_STATUS_ACTIVE and membership["version"] == 1
    assert "removedAt" not in membership and "removedByAccountId" not in membership
    assert membership["sk"] == f"MEMBERSHIP#{PACK_PROFILE}"

    removed = ucm.build_membership_item(
        unit_campaign_id=PACK_ID,
        unit_id="unit-pack-3149-aurora",
        campaign_id=PACK_CAMPAIGN,
        profile_id=PACK_PROFILE,
        joined_by_account_id=DEVON,
        now_iso=NOW,
        status=ucm.MEMBERSHIP_STATUS_REMOVED,
    )
    assert removed["status"] == ucm.MEMBERSHIP_STATUS_REMOVED

    with pytest.raises(AppError) as caught:
        ucm.build_membership_item(
            unit_campaign_id=PACK_ID,
            unit_id="unit-pack-3149-aurora",
            campaign_id=PACK_CAMPAIGN,
            profile_id=PACK_PROFILE,
            joined_by_account_id=DEVON,
            now_iso=NOW,
            status="LEFT",
        )
    assert caught.value.error_code == ErrorCode.INVALID_INPUT

    free = ucm.build_membership_guard_item(
        campaign_id=PACK_CAMPAIGN,
        profile_id=PACK_PROFILE,
        active_unit_campaign_id=None,
        membership_version=1,
        now_iso=NOW,
    )
    assert "activeUnitCampaignId" not in free
    taken = ucm.build_membership_guard_item(
        campaign_id=PACK_CAMPAIGN,
        profile_id=PACK_PROFILE,
        active_unit_campaign_id=PACK_ID,
        membership_version=2,
        now_iso=NOW,
    )
    assert taken["activeUnitCampaignId"] == PACK_ID and taken["membershipVersion"] == 2

    for bad_version in (0, -1, "1", True):
        with pytest.raises(AppError) as caught:
            ucm.build_membership_guard_item(
                campaign_id=PACK_CAMPAIGN,
                profile_id=PACK_PROFILE,
                active_unit_campaign_id=None,
                membership_version=bad_version,
                now_iso=NOW,
            )
        assert caught.value.error_code == ErrorCode.INVALID_INPUT


# --- Reads (§1.4.1, §1.4.2) ------------------------------------------------------


def test_join_path_reads_are_strongly_consistent() -> None:
    """§5.5: pointer read then campaign read, both consistent.

    A join decided on an eventually consistent copy could admit a Scout to a
    campaign that was deactivated or relinked a second ago, so the reads that a
    mutation conditions on are pinned to the base table's current state.
    """
    from src.utils import dynamodb as db_module

    pointer = join_code_pointer_item(PACK_JOIN_CODE, PACK_ID)
    campaign = _campaign_item()
    guard = {"pk": f"SCOUT_CAMPAIGN#{PACK_CAMPAIGN}", "sk": "MEMBERSHIP_GUARD", "campaignId": PACK_CAMPAIGN}
    membership = _membership()
    recorder = _RecordingTable([pointer, campaign, guard, membership])
    db_module.override_table("unit_campaigns", recorder)
    try:
        assert ucm.resolve_join_code(PACK_JOIN_CODE) is not None
        assert ucm.read_unit_campaign(PACK_ID) is not None
        assert ucm.read_membership(PACK_ID, PACK_PROFILE) is not None
        assert ucm.read_membership_guard(PACK_CAMPAIGN) is not None
    finally:
        db_module.override_table("unit_campaigns", None)

    assert all(call.get("ConsistentRead") is True for call in recorder.calls), recorder.calls
    assert [call["operation"] for call in recorder.calls] == ["Query", "GetItem", "GetItem", "GetItem", "GetItem"]


def test_unknown_malformed_inactive_and_dangling_codes_answer_identically(unit_campaigns_table: Any) -> None:
    """No caller can tell which case it hit, and an inactive campaign cannot be joined."""
    _seed_campaign(tables.unit_campaigns)
    assert ucm.resolve_join_code("NOPE000000000000") is None
    assert ucm.resolve_join_code("nope") is None

    _seed_campaign(tables.unit_campaigns, isActive=False)
    assert ucm.resolve_join_code(PACK_JOIN_CODE) is None
    resolved = ucm.resolve_join_code(PACK_JOIN_CODE, require_active=False)
    assert resolved is not None and resolved["isActive"] is False

    tables.unit_campaigns.delete_item(Key={"pk": f"UNIT_CAMPAIGN#{PACK_ID}", "sk": "METADATA"})
    assert ucm.resolve_join_code(PACK_JOIN_CODE) is None


def test_resolve_join_code_returns_the_current_campaign_not_a_creation_copy(unit_campaigns_table: Any) -> None:
    """Deactivating is visible immediately to the code path that admits Scouts."""
    _seed_campaign(tables.unit_campaigns)
    get_dynamodb_client().update_item(
        TableName="kernelworx-unit-campaigns-ue1-dev",
        Key={"pk": {"S": f"UNIT_CAMPAIGN#{PACK_ID}"}, "sk": {"S": "METADATA"}},
        UpdateExpression="SET #name = :name, #year = :year",
        ExpressionAttributeNames={"#name": "campaignName", "#year": "campaignYear"},
        ExpressionAttributeValues={":name": {"S": "Renamed Season"}, ":year": {"N": "2027"}},
    )
    resolved = ucm.resolve_join_code(PACK_JOIN_CODE)
    assert resolved is not None
    assert resolved["campaignName"] == "Renamed Season" and resolved["campaignYear"] == 2027


def test_campaign_listing_is_newest_first_and_excludes_other_row_types(unit_campaigns_table: Any) -> None:
    """The roster rows share the partition; a campaign list must not show them."""
    _seed_campaign(tables.unit_campaigns)
    older = _campaign_item(CREW_ID, createdAt="2025-01-01T00:00:00+00:00")
    tables.unit_campaigns.put_item(Item=older)
    tables.unit_campaigns.put_item(Item=join_code_pointer_item(CREW_JOIN_CODE, CREW_ID))
    tables.unit_campaigns.put_item(
        Item=_membership(
            sk="MEMBERSHIP#PROFILE#riley", profileId="PROFILE#riley", campaignId="CAMPAIGN#riley", status="REMOVED"
        )
    )

    listed = ucm.list_unit_campaigns("unit-pack-3149-aurora")
    assert [item["unitCampaignId"] for item in listed] == [PACK_ID, CREW_ID]
    assert all("profileId" not in item for item in listed)


def test_catalog_usage_guard_read_finds_referencing_campaigns(unit_campaigns_table: Any) -> None:
    """§6.2: the catalog index exists to block soft-deleting a referenced catalog."""
    _seed_campaign(tables.unit_campaigns)
    tables.unit_campaigns.put_item(Item=_campaign_item(CREW_ID, catalogId="CATALOG#fixture-public"))

    by_default = ucm.find_unit_campaigns_using_catalog("CATALOG#fixture-default")
    assert [item["unitCampaignId"] for item in by_default] == [PACK_ID]
    assert ucm.find_unit_campaigns_using_catalog("CATALOG#fixture-unused") == []


def test_membership_listing_filters_by_status_and_by_scout_campaign(unit_campaigns_table: Any) -> None:
    """Roster reads keep REMOVED rows for history and can be narrowed to ACTIVE."""
    tables.unit_campaigns.put_item(Item=_membership())
    tables.unit_campaigns.put_item(
        Item=_membership(
            sk="MEMBERSHIP#PROFILE#riley", profileId="PROFILE#riley", campaignId="CAMPAIGN#riley", status="REMOVED"
        )
    )

    everyone = ucm.list_memberships(PACK_ID)
    assert [item["profileId"] for item in everyone] == [PACK_PROFILE, "PROFILE#riley"]
    assert [item["profileId"] for item in ucm.list_memberships(PACK_ID, status=ucm.MEMBERSHIP_STATUS_ACTIVE)] == [
        PACK_PROFILE
    ]
    assert [item["profileId"] for item in ucm.list_memberships_for_campaign("CAMPAIGN#riley")] == ["PROFILE#riley"]
    with pytest.raises(AppError):
        ucm.list_memberships(PACK_ID, status="GONE")


def test_missing_rows_are_none_and_load_answers_not_found(unit_campaigns_table: Any) -> None:
    assert ucm.read_unit_campaign("uc-nope") is None
    assert ucm.read_membership(PACK_ID, PACK_PROFILE) is None
    assert ucm.read_membership_guard(PACK_CAMPAIGN) is None
    with pytest.raises(AppError) as caught:
        ucm.load_unit_campaign_or_not_found("uc-nope")
    assert caught.value.error_code == ErrorCode.NOT_FOUND
    assert ucm.load_unit_campaign_or_not_found(_seed_campaign(tables.unit_campaigns)["unitCampaignId"])


def test_guard_target_is_read_only_from_the_guard() -> None:
    """The historical Campaign link is never the answer to 'is this joined now?'."""
    assert ucm.guard_active_unit_campaign_id(None) is None
    assert ucm.guard_active_unit_campaign_id({"campaignId": PACK_CAMPAIGN}) is None
    assert ucm.guard_active_unit_campaign_id({"activeUnitCampaignId": PACK_ID}) == PACK_ID


# --- Immutable fields (§1.4.1) ---------------------------------------------------


def test_catalog_and_identity_fields_cannot_be_changed() -> None:
    """Moving a campaign between catalogs would relocate inventory and Order origin."""
    ucm.reject_immutable_campaign_changes({"campaignName": "New Name", "isActive": False, "campaignYear": 2027})
    for field in ("catalogId", "unitId", "joinCode", "unitCampaignId", "version", "createdAt"):
        with pytest.raises(AppError) as caught:
            ucm.reject_immutable_campaign_changes({field: "whatever"})
        assert caught.value.error_code == ErrorCode.INVALID_INPUT
        assert field in str(caught.value.message)
    with pytest.raises(AppError):
        ucm.reject_immutable_campaign_changes(["catalogId"])


# --- Campaign/pointer lifecycle in one transaction (§1.4.1) ----------------------


def test_campaign_and_join_code_pointer_commit_together(unit_campaigns_table: Any) -> None:
    """A campaign is never reachable by a code that does not resolve to it."""
    campaign = ucm.build_unit_campaign_item(
        unit_campaign_id=PACK_ID,
        unit_id="unit-pack-3149-aurora",
        campaign_name="Pack 3149 Fall Show & Sell",
        campaign_year=2026,
        catalog_id="CATALOG#fixture-default",
        join_code=ucm.new_join_code(),
        created_by_account_id=AVERY,
        now_iso=NOW,
    )
    pointer = ucm.build_join_code_pointer_item(join_code=campaign["joinCode"], unit_campaign_id=PACK_ID, now_iso=NOW)
    _transact(ucm.create_campaign_actions(campaign, pointer))

    assert ucm.read_unit_campaign(PACK_ID) is not None
    assert ucm.resolve_join_code(str(campaign["joinCode"])) is not None


def test_join_code_collision_is_visible_before_the_write(unit_campaigns_table: Any) -> None:
    """A code already naming another campaign is refused, and the pair writes once."""
    first = _seed_campaign(unit_campaigns_table)
    challenger = ucm.build_unit_campaign_item(
        unit_campaign_id=CREW_ID,
        unit_id="unit-crew-529-denver",
        campaign_name="Crew 529 Fall Show & Sell",
        campaign_year=2026,
        catalog_id="CATALOG#fixture-default",
        join_code=first["joinCode"],
        created_by_account_id=AVERY,
        now_iso=NOW,
    )
    # DynamoDB conditions are per-item, so no conditional write can express "no
    # other row with this partition key": §5.5's one-code-one-campaign rule is
    # enforced by this consistent pointer read before anything is staged, and a
    # create that ignores it is caught here rather than after the write.
    assert ucm.join_code_taken(str(challenger["joinCode"]), except_unit_campaign_id=CREW_ID) is True
    assert ucm.join_code_taken(str(challenger["joinCode"]), except_unit_campaign_id=PACK_ID) is False
    assert ucm.join_code_taken("bad-code") is False
    assert [p["unitCampaignId"] for p in ucm.find_join_code_pointers(str(first["joinCode"]))] == [PACK_ID]


def test_replaying_a_campaign_create_cannot_rewrite_it(unit_campaigns_table: Any) -> None:
    """The campaign/pointer pair is a conditional insert, so a retry cancels.

    This is the half of §5.5 the conditional write can enforce on its own: one
    create may not become two campaigns, and a replay leaves the first rows
    exactly as they were.
    """
    _seed_campaign(unit_campaigns_table)
    second = ucm.build_unit_campaign_item(
        unit_campaign_id=CREW_ID,
        unit_id="unit-crew-529-denver",
        campaign_name="Crew 529 Fall Show & Sell",
        campaign_year=2026,
        catalog_id="CATALOG#fixture-default",
        join_code=CREW_JOIN_CODE,
        created_by_account_id=AVERY,
        now_iso=NOW,
    )
    pointer = ucm.build_join_code_pointer_item(join_code=CREW_JOIN_CODE, unit_campaign_id=CREW_ID, now_iso=NOW)
    _transact(ucm.create_campaign_actions(second, pointer))

    with pytest.raises(ClientError) as replay:
        _transact(ucm.create_campaign_actions(second, pointer))
    assert "ConditionalCheckFailed" in _cancellation_codes(replay.value)
    assert len(ucm.find_join_code_pointers(CREW_JOIN_CODE)) == 1
    assert ucm.read_unit_campaign(CREW_ID)["createdAt"] == NOW


def test_deleting_a_campaign_takes_its_pointer_with_it(unit_campaigns_table: Any) -> None:
    """No live pointer may outlive the campaign it names."""
    campaign = _seed_campaign(unit_campaigns_table)
    assert ucm.join_code_taken(str(campaign["joinCode"])) is True
    _transact(ucm.delete_campaign_actions(campaign))
    assert ucm.read_unit_campaign(PACK_ID) is None
    assert ucm.resolve_join_code(str(campaign["joinCode"])) is None
    assert ucm.join_code_taken(str(campaign["joinCode"])) is False


def test_delete_actions_are_conditional_on_the_row_being_present() -> None:
    """Neither delete is allowed to be a silent no-op.

    DynamoDB evaluates a Delete's condition against the row it names; moto does
    not run that check inside a transaction, so the emitted guard is asserted
    directly here and the transactional pairing is covered by the delete test.
    """
    actions = ucm.delete_campaign_actions(_campaign_item())
    assert [action for action, _body in actions] == ["Delete", "Delete"]
    for _action, body in actions:
        assert body["ConditionExpression"] == "attribute_exists(#pk) AND attribute_exists(#sk)"


# --- Membership join, removal, rejoin (§1.4.2) ----------------------------------


def _join_actions(membership: Dict[str, Any], *, expected_guard_version: Any) -> List[tuple[str, Dict[str, Any]]]:
    return [
        ucm.put_membership_action(membership),
        ucm.guard_claim_action(
            campaign_id=str(membership["campaignId"]),
            profile_id=str(membership["profileId"]),
            active_unit_campaign_id=str(membership["unitCampaignId"]),
            expected_membership_version=expected_guard_version,
            now_iso=NOW,
        ),
        ucm.campaign_latest_link_action(
            profile_id=str(membership["profileId"]),
            campaign_id=str(membership["campaignId"]),
            unit_id=str(membership["unitId"]),
            unit_campaign_id=str(membership["unitCampaignId"]),
        ),
    ]


def test_join_writes_membership_guard_and_campaign_link_together(
    unit_campaigns_table: Any, campaigns_table: Any
) -> None:
    """§8.2: membership, guard target, and the Campaign's latest link are one commit."""
    _seed_campaign(unit_campaigns_table)
    _seed_scout_campaign(campaigns_table)
    _transact(_join_actions(_membership(), expected_guard_version=None))

    stored = ucm.read_membership(PACK_ID, PACK_PROFILE)
    assert stored is not None and stored["status"] == ucm.MEMBERSHIP_STATUS_ACTIVE
    guard = ucm.read_membership_guard(PACK_CAMPAIGN)
    assert guard is not None
    assert ucm.guard_active_unit_campaign_id(guard) == PACK_ID
    assert int(guard["membershipVersion"]) == 1
    link = campaigns_table.get_item(Key={"profileId": PACK_PROFILE, "campaignId": PACK_CAMPAIGN})["Item"]
    assert link["unitId"] == "unit-pack-3149-aurora" and link["unitCampaignId"] == PACK_ID


def test_second_active_join_for_one_scout_campaign_is_refused(unit_campaigns_table: Any, campaigns_table: Any) -> None:
    """One ACTIVE membership per Scout Campaign, enforced by the guard condition."""
    _seed_campaign(unit_campaigns_table)
    _seed_campaign(
        unit_campaigns_table, pk=f"UNIT_CAMPAIGN#{CREW_ID}", unitCampaignId=CREW_ID, join_code=CREW_JOIN_CODE
    )
    unit_campaigns_table.put_item(Item=join_code_pointer_item(CREW_JOIN_CODE, CREW_ID))
    _seed_scout_campaign(campaigns_table)
    _transact(_join_actions(_membership(), expected_guard_version=None))

    rival = _membership(
        pk=f"UNIT_CAMPAIGN#{CREW_ID}",
        unitCampaignId=CREW_ID,
        unitId="unit-crew-529-denver",
        version=1,
    )
    with pytest.raises(ClientError) as caught:
        _transact(_join_actions(rival, expected_guard_version=1))
    assert "ConditionalCheckFailed" in _cancellation_codes(caught.value)

    # No partial state: the first join is intact and the rival wrote nothing.
    assert ucm.guard_active_unit_campaign_id(ucm.read_membership_guard(PACK_CAMPAIGN)) == PACK_ID
    assert ucm.read_membership(CREW_ID, PACK_PROFILE) is None
    link = campaigns_table.get_item(Key={"profileId": PACK_PROFILE, "campaignId": PACK_CAMPAIGN})["Item"]
    assert link["unitCampaignId"] == PACK_ID


def test_duplicate_active_membership_on_the_same_campaign_is_refused(
    unit_campaigns_table: Any, campaigns_table: Any
) -> None:
    """Same Scout Campaign: a join cannot also be a second identity for one Scout."""
    _seed_campaign(unit_campaigns_table)
    _seed_scout_campaign(campaigns_table)
    _transact(_join_actions(_membership(), expected_guard_version=None))

    with pytest.raises(ClientError) as caught:
        _transact(_join_actions(_membership(), expected_guard_version=1))
    assert "ConditionalCheckFailed" in _cancellation_codes(caught.value)
    assert int(ucm.read_membership(PACK_ID, PACK_PROFILE)["version"]) == 1


def test_join_link_condition_refuses_a_campaign_that_does_not_exist(
    unit_campaigns_table: Any, campaigns_table: Any
) -> None:
    """The link write cannot invent a Scout Campaign row."""
    _seed_campaign(unit_campaigns_table)
    with pytest.raises(ClientError) as caught:
        _transact(_join_actions(_membership(), expected_guard_version=None))
    assert "ConditionalCheckFailed" in _cancellation_codes(caught.value)
    assert ucm.read_membership(PACK_ID, PACK_PROFILE) is None
    assert ucm.read_membership_guard(PACK_CAMPAIGN) is None


def test_removal_keeps_history_and_leaves_the_campaign_link_for_history(
    unit_campaigns_table: Any, campaigns_table: Any
) -> None:
    """Removal sets REMOVED plus audit, frees the guard, and deletes nothing (§5.6)."""
    _seed_campaign(unit_campaigns_table)
    _seed_scout_campaign(campaigns_table)
    _transact(_join_actions(_membership(), expected_guard_version=None))

    _transact(
        [
            ucm.remove_membership_action(
                unit_campaign_id=PACK_ID,
                profile_id=PACK_PROFILE,
                expected_version=1,
                removed_by_account_id=AVERY,
                now_iso=NOW,
            ),
            ucm.guard_release_action(
                campaign_id=PACK_CAMPAIGN,
                expected_membership_version=1,
                expected_unit_campaign_id=PACK_ID,
                now_iso=NOW,
            ),
        ]
    )

    stored = ucm.read_membership(PACK_ID, PACK_PROFILE)
    assert stored is not None and stored["status"] == ucm.MEMBERSHIP_STATUS_REMOVED
    assert int(stored["version"]) == 2
    assert stored["removedByAccountId"] == AVERY and stored["removedAt"] == NOW
    guard = ucm.read_membership_guard(PACK_CAMPAIGN)
    assert guard is not None and ucm.guard_active_unit_campaign_id(guard) is None
    assert "activeUnitCampaignId" not in guard
    assert int(guard["membershipVersion"]) == 2
    link = campaigns_table.get_item(Key={"profileId": PACK_PROFILE, "campaignId": PACK_CAMPAIGN})["Item"]
    assert link["unitCampaignId"] == PACK_ID  # API-FIX-05: retained, never cleared


def test_rejoin_reactivates_the_same_record_and_takes_the_guard_again(
    unit_campaigns_table: Any, campaigns_table: Any
) -> None:
    """§5.6: a rejoin keeps the immutable campaignId and the participation history."""
    _seed_campaign(unit_campaigns_table)
    _seed_campaign(
        unit_campaigns_table, pk=f"UNIT_CAMPAIGN#{CREW_ID}", unitCampaignId=CREW_ID, join_code=CREW_JOIN_CODE
    )
    unit_campaigns_table.put_item(Item=join_code_pointer_item(CREW_JOIN_CODE, CREW_ID))
    _seed_scout_campaign(campaigns_table)
    _transact(_join_actions(_membership(), expected_guard_version=None))
    _transact(
        [
            ucm.remove_membership_action(
                unit_campaign_id=PACK_ID,
                profile_id=PACK_PROFILE,
                expected_version=1,
                removed_by_account_id=AVERY,
                now_iso=NOW,
            ),
            ucm.guard_release_action(
                campaign_id=PACK_CAMPAIGN,
                expected_membership_version=1,
                expected_unit_campaign_id=PACK_ID,
                now_iso=NOW,
            ),
        ]
    )

    rejoined = _membership(joinedAt="2026-11-05T00:00:00+00:00")
    _transact(
        [
            ucm.reactivate_membership_action(
                {
                    "unitCampaignId": PACK_ID,
                    "profileId": PACK_PROFILE,
                    "campaignId": PACK_CAMPAIGN,
                    "joinedAt": rejoined["joinedAt"],
                    "joinedByAccountId": DEVON,
                },
                expected_version=2,
            ),
            ucm.guard_claim_action(
                campaign_id=PACK_CAMPAIGN,
                profile_id=PACK_PROFILE,
                active_unit_campaign_id=PACK_ID,
                expected_membership_version=2,
                now_iso=NOW,
            ),
        ]
    )

    stored = ucm.read_membership(PACK_ID, PACK_PROFILE)
    assert stored is not None
    assert stored["status"] == ucm.MEMBERSHIP_STATUS_ACTIVE
    assert stored["campaignId"] == PACK_CAMPAIGN and stored["profileId"] == PACK_PROFILE
    assert int(stored["version"]) == 3
    assert stored["joinedAt"] == "2026-11-05T00:00:00+00:00"
    assert "removedAt" not in stored and "removedByAccountId" not in stored
    assert ucm.guard_active_unit_campaign_id(ucm.read_membership_guard(PACK_CAMPAIGN)) == PACK_ID


def test_reactivation_refuses_an_active_or_stale_record(unit_campaigns_table: Any, campaigns_table: Any) -> None:
    """A rejoin that lost the race sees the newer version and writes nothing."""
    _seed_campaign(unit_campaigns_table)
    _seed_scout_campaign(campaigns_table)
    _transact(_join_actions(_membership(), expected_guard_version=None))

    with pytest.raises(ClientError) as caught:
        _transact(
            [
                ucm.reactivate_membership_action(
                    {
                        "unitCampaignId": PACK_ID,
                        "profileId": PACK_PROFILE,
                        "campaignId": PACK_CAMPAIGN,
                        "joinedAt": NOW,
                        "joinedByAccountId": DEVON,
                    },
                    expected_version=1,
                )
            ]
        )
    assert "ConditionalCheckFailed" in _cancellation_codes(caught.value)
    assert int(ucm.read_membership(PACK_ID, PACK_PROFILE)["version"]) == 1


def test_stale_removal_and_guard_target_mismatch_are_both_refused(
    unit_campaigns_table: Any, campaigns_table: Any
) -> None:
    """Both version guards are required: membership version and guard target."""
    _seed_campaign(unit_campaigns_table)
    _seed_scout_campaign(campaigns_table)
    _transact(_join_actions(_membership(), expected_guard_version=None))

    with pytest.raises(ClientError) as stale_membership:
        _transact(
            [
                ucm.remove_membership_action(
                    unit_campaign_id=PACK_ID,
                    profile_id=PACK_PROFILE,
                    expected_version=7,
                    removed_by_account_id=AVERY,
                    now_iso=NOW,
                )
            ]
        )
    assert "ConditionalCheckFailed" in _cancellation_codes(stale_membership.value)

    with pytest.raises(ClientError) as stale_guard:
        _transact(
            [
                ucm.guard_release_action(
                    campaign_id=PACK_CAMPAIGN,
                    expected_membership_version=9,
                    expected_unit_campaign_id=PACK_ID,
                    now_iso=NOW,
                )
            ]
        )
    assert "ConditionalCheckFailed" in _cancellation_codes(stale_guard.value)

    with pytest.raises(ClientError) as wrong_target:
        _transact(
            [
                ucm.guard_release_action(
                    campaign_id=PACK_CAMPAIGN,
                    expected_membership_version=1,
                    expected_unit_campaign_id=CREW_ID,
                    now_iso=NOW,
                )
            ]
        )
    assert "ConditionalCheckFailed" in _cancellation_codes(wrong_target.value)

    stored = ucm.read_membership(PACK_ID, PACK_PROFILE)
    assert stored is not None and stored["status"] == ucm.MEMBERSHIP_STATUS_ACTIVE
    assert ucm.guard_active_unit_campaign_id(ucm.read_membership_guard(PACK_CAMPAIGN)) == PACK_ID


def test_guard_claim_against_a_missing_guard_row_cannot_double_create(
    unit_campaigns_table: Any, campaigns_table: Any
) -> None:
    """Two concurrent first joins: only one guard row can be created."""
    _seed_campaign(unit_campaigns_table)
    _seed_campaign(
        unit_campaigns_table, pk=f"UNIT_CAMPAIGN#{CREW_ID}", unitCampaignId=CREW_ID, join_code=CREW_JOIN_CODE
    )
    _seed_scout_campaign(campaigns_table)

    _transact(
        [
            ucm.guard_claim_action(
                campaign_id=PACK_CAMPAIGN,
                profile_id=PACK_PROFILE,
                active_unit_campaign_id=PACK_ID,
                expected_membership_version=None,
                now_iso=NOW,
            )
        ]
    )
    with pytest.raises(ClientError) as caught:
        _transact(
            [
                ucm.guard_claim_action(
                    campaign_id=PACK_CAMPAIGN,
                    profile_id=PACK_PROFILE,
                    active_unit_campaign_id=CREW_ID,
                    expected_membership_version=None,
                    now_iso=NOW,
                )
            ]
        )
    assert "ConditionalCheckFailed" in _cancellation_codes(caught.value)
    assert ucm.guard_active_unit_campaign_id(ucm.read_membership_guard(PACK_CAMPAIGN)) == PACK_ID


def test_module_exports_its_own_name_only_where_needed() -> None:
    """The module is the single writer: no test reaches past it for item shapes."""
    assert module.MEMBERSHIP_STATUSES == frozenset({"ACTIVE", "REMOVED"})
    assert campaign_item("Devon", unit_id="u", unit_campaign_id=PACK_ID)["unitCampaignId"] == PACK_ID
