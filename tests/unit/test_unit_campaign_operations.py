"""Leaf 1.5 — Unit Campaign and roster resolvers.

Driven through the ``unit_operations`` entrypoint with the Stage 1 fixture event
builder, over the fully seeded Stage 1 fixture set (Units, grants, Scout
profiles/campaigns/shares, Unit Campaigns, join-code pointers, memberships,
guards, catalogs). The e2e descriptions this leaf answers to:

- ``createUnitCampaign`` (§1.5.1) — admin-only, catalog must exist and be
  usable, campaign row + unique join-code pointer commit as one pair, idempotent
  replay, and generated-code collisions retried rather than surfaced.
- ``updateUnitCampaign`` (``CAMP-M-02``, ``VER-01``, ``AUTH-U``, ``IDEM``) —
  name/year/isActive only, ``catalogId`` refused rather than ignored, and a
  deactivation that touches nothing else.
- ``unitCampaignJoinInfo`` (``AUTH-C``, §1.5.3) — any signed-in Account, the
  five-field participant allowlist, and unknown/inactive/dangling codes answering
  identically.
- ``joinUnitCampaign`` (``CAMP-M-03``) — Profile Owner/WRITE, no substituted
  ``campaignId``, one active membership per Scout Campaign, rejoin on the same
  record, three rows moving together, join-code-scoped replay.
- ``removeUnitCampaignMembership`` (``CAMP-M-04``) — two versions because two
  rows move, history preserved, and a signup racing removal losing its condition.
- ``unitCampaign`` / ``unitCampaigns`` / ``unitCampaignCatalog`` /
  ``unitCampaignRoster`` (``UNIT-Q-07``–``09``, ``AUTH-U``, ``PAGE-01``).

An anonymous caller is rejected by the entrypoint before any resolver runs, so
``AUTH-C`` is asserted as "unauthorized and nothing written" rather than as a
per-resolver check.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

import pytest

from src.handlers.unit_operations import (
    CREATE_UNIT_CAMPAIGN_FIELD,
    JOIN_PREVIEW_FIELD,
    JOIN_UNIT_CAMPAIGN_FIELD,
    REMOVE_MEMBERSHIP_FIELD,
    UNIT_CAMPAIGN_CATALOG_FIELD,
    UNIT_CAMPAIGN_FIELD,
    UNIT_CAMPAIGN_ROSTER_FIELD,
    UNIT_CAMPAIGNS_FIELD,
    UPDATE_UNIT_CAMPAIGN_FIELD,
    handle_unit_operation,
)
from src.utils import unit_campaign_models as ucm
from src.utils import unit_models
from src.utils.errors import ErrorCode
from tests.unit.show_sell_fixtures import (
    CREW_529,
    CREW_529_SPRING,
    PACK_3149,
    PACK_3149_FALL,
    PACK_3149_OLD,
    PROFILES,
    TROOP_7150,
    account_id,
    assert_is_error,
    catalog_item,
    seed_show_sell_fixtures,
    unit_campaign_membership_item,
    unit_operation_event,
)

AVERY = account_id("Avery")
BLAKE = account_id("Blake")
TAYLOR = account_id("Taylor")

DEFAULT_CATALOG = "CATALOG#fixture-default"
DELETED_CATALOG = "CATALOG#fixture-deleted"
FALL_CODE = "JOINPK3149FALL01"
SPRING_CODE = "JOINCRW529SPRNG1"
OLD_CODE = "JOINPK3149OLD001"
TAKEN_CODE = FALL_CODE
FREE_CODE = "JOINBLAKE0000001"

_PROFILE_OF = {persona: PROFILES[persona]["profileId"] for persona in PROFILES}
_CAMPAIGN_OF = {persona: PROFILES[persona]["campaignId"] for persona in PROFILES}


@pytest.fixture
def seeded(
    units_table: Any,
    unit_campaigns_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    catalogs_table: Any,
) -> Dict[str, Any]:
    """Every Stage 1 persona fixture, across all six tables this leaf touches."""
    return seed_show_sell_fixtures(
        units_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
    )


def _call(
    field: str,
    caller: Any,
    *,
    input: Dict[str, Any] | None = None,
    arguments: Dict[str, Any] | None = None,
) -> Any:
    """One resolver turn through the Lambda entrypoint (errors arrive as payloads)."""
    return handle_unit_operation(unit_operation_event(field, caller, input=input, arguments=arguments), None)


def _idem(key: str = "op-1") -> Dict[str, Any]:
    return {"idempotencyKey": key}


def _create_input(unit_id: str = PACK_3149, catalog_id: str = DEFAULT_CATALOG, key: str = "op-1") -> Dict[str, Any]:
    return {
        "unitId": unit_id,
        "campaignName": "Pack 3149 Winter Show & Sell",
        "campaignYear": 2027,
        "catalogId": catalog_id,
        "idempotency": _idem(key),
    }


def _read_campaign(unit_campaign_id: str) -> Dict[str, Any]:
    campaign = ucm.read_unit_campaign(unit_campaign_id)
    assert campaign is not None
    return campaign


def _read_membership(unit_campaign_id: str, persona: str) -> Dict[str, Any]:
    membership = ucm.read_membership(unit_campaign_id, _PROFILE_OF[persona])
    assert membership is not None
    return membership


def _scout_campaign(persona: str) -> Dict[str, Any]:
    campaign = ucm.read_scout_campaign(_CAMPAIGN_OF[persona])
    assert campaign is not None
    return campaign


def _scan(table: Any, pk: str) -> List[Dict[str, Any]]:
    return list(table.query(KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": pk})["Items"])


def _membership_rows(table: Any, unit_campaign_id: str) -> List[Dict[str, Any]]:
    return [row for row in _scan(table, f"UNIT_CAMPAIGN#{unit_campaign_id}") if str(row["sk"]).startswith("MEMBERSHIP")]


def _activate_campaign(unit_campaigns_table: Any, unit_campaign_id: str) -> None:
    """Make a fixture campaign joinable again without going through the update path."""
    unit_campaigns_table.update_item(
        Key=ucm.unit_campaign_metadata_key(unit_campaign_id),
        UpdateExpression="SET #active = :true",
        ExpressionAttributeNames={"#active": "isActive"},
        ExpressionAttributeValues={":true": True},
    )


# --- createUnitCampaign (§1.5.1) -------------------------------------------------


def test_create_writes_the_campaign_and_its_pointer_together(seeded: Dict[str, Any], unit_campaigns_table: Any) -> None:
    """One turn produces the metadata row and the credential that resolves it."""
    result = _call(CREATE_UNIT_CAMPAIGN_FIELD, "Avery", input=_create_input())
    assert isinstance(result, dict)
    unit_campaign_id = str(result["unitCampaignId"])
    assert result["campaignName"] == "Pack 3149 Winter Show & Sell"
    assert result["campaignYear"] == 2027
    assert result["catalogId"] == DEFAULT_CATALOG
    assert result["unitId"] == PACK_3149
    assert result["isActive"] is True
    assert result["version"] == 1
    assert result["createdByAccountId"] == AVERY
    assert set(result) == {
        "unitCampaignId",
        "unitId",
        "campaignName",
        "campaignYear",
        "catalogId",
        "joinCode",
        "isActive",
        "version",
        "createdAt",
        "updatedAt",
        "createdByAccountId",
        "updatedByAccountId",
    }

    stored = _read_campaign(unit_campaign_id)
    assert stored["joinCode"] == result["joinCode"]
    assert ucm.is_valid_join_code(str(stored["joinCode"]))
    pointers = _scan(unit_campaigns_table, f"JOIN_CODE#{stored['joinCode']}")
    assert [pointer["unitCampaignId"] for pointer in pointers] == [unit_campaign_id]
    assert ucm.resolve_join_code(str(stored["joinCode"])) is not None


def test_generated_identity_and_code_survive_a_rename(seeded: Dict[str, Any]) -> None:
    """Neither the id nor the code is derived from what the campaign is called."""
    created = _call(CREATE_UNIT_CAMPAIGN_FIELD, "Avery", input=_create_input())
    renamed = _call(
        UPDATE_UNIT_CAMPAIGN_FIELD,
        "Avery",
        input={
            "unitCampaignId": created["unitCampaignId"],
            "campaignName": "Pack 3149 Midwinter Show & Sell",
            "version": {"expectedVersion": created["version"]},
            "idempotency": _idem("op-2"),
        },
    )
    assert renamed["unitCampaignId"] == created["unitCampaignId"]
    assert renamed["joinCode"] == created["joinCode"]
    resolved = ucm.resolve_join_code(str(created["joinCode"]))
    assert resolved is not None and resolved["unitCampaignId"] == created["unitCampaignId"]


def test_create_is_refused_without_a_grant_on_the_unit(seeded: Dict[str, Any], unit_campaigns_table: Any) -> None:
    """A Scout who holds nothing on Pack 3149 cannot open a campaign on it.

    ``require_unit_admin`` answers an unknown Unit, another tenant's Unit, and a
    revoked grant identically, so the denial never confirms the Unit exists.
    """
    payload = assert_is_error(_call(CREATE_UNIT_CAMPAIGN_FIELD, "Blake", input=_create_input()), ErrorCode.NOT_FOUND)
    assert payload["message"] == "Unit not found"
    assert _scan(unit_campaigns_table, f"JOIN_CODE#{FREE_CODE}") == []


def test_create_requires_a_catalog_that_exists_and_is_selectable(seeded: Dict[str, Any]) -> None:
    """``NOT_FOUND`` for a catalog that is not there, refusal for a soft-deleted one."""
    for catalog_id, expected in (
        ("CATALOG#never-seeded", ErrorCode.NOT_FOUND),
        (DELETED_CATALOG, ErrorCode.INVALID_INPUT),
    ):
        assert_is_error(
            _call(CREATE_UNIT_CAMPAIGN_FIELD, "Avery", input=_create_input(catalog_id=catalog_id)),
            expected,
        )


def test_create_validates_name_and_year(seeded: Dict[str, Any]) -> None:
    """The builder's rules run before any write is staged."""
    for index, (name, year) in enumerate(
        (("  ", 2027), ("Valid name", 1899), ("Valid name", 2101), ("Valid name", "soon"))
    ):
        body = _create_input(key=f"op-validate-{index}")
        body["campaignName"] = name
        body["campaignYear"] = year
        assert_is_error(_call(CREATE_UNIT_CAMPAIGN_FIELD, "Avery", input=body), ErrorCode.INVALID_INPUT)


def test_create_replays_without_a_second_campaign(seeded: Dict[str, Any], unit_campaigns_table: Any) -> None:
    """The same key and body answer the original result; nothing commits twice."""
    turn = _create_input()
    first = _call(CREATE_UNIT_CAMPAIGN_FIELD, "Avery", input=turn)
    second = _call(CREATE_UNIT_CAMPAIGN_FIELD, "Avery", input=turn)
    assert second == first
    assert _scan(unit_campaigns_table, f"UNIT_CAMPAIGN#{first['unitCampaignId']}")
    assert len(_scan(unit_campaigns_table, f"JOIN_CODE#{first['joinCode']}")) == 1


def test_same_key_with_a_different_body_is_refused(seeded: Dict[str, Any]) -> None:
    """One key is one request; a changed body is a different intent."""
    base = _create_input()
    _call(CREATE_UNIT_CAMPAIGN_FIELD, "Avery", input=base)
    assert_is_error(
        _call(CREATE_UNIT_CAMPAIGN_FIELD, "Avery", input={**base, "campaignYear": 2028}), ErrorCode.INVALID_INPUT
    )


def test_a_colliding_join_code_is_regenerated_then_exhausted(
    seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A taken code is retried; a loop that never frees is a conflict, not a stall."""
    codes = iter([TAKEN_CODE, TAKEN_CODE, FREE_CODE])
    monkeypatch.setattr(ucm, "new_join_code", lambda: next(codes))
    result = _call(CREATE_UNIT_CAMPAIGN_FIELD, "Avery", input=_create_input())
    assert result["joinCode"] == FREE_CODE
    assert ucm.resolve_join_code(FREE_CODE) is not None

    monkeypatch.setattr(ucm, "new_join_code", lambda: TAKEN_CODE)
    assert_is_error(
        _call(CREATE_UNIT_CAMPAIGN_FIELD, "Avery", input=_create_input(key="op-exhausted")), ErrorCode.CONFLICT
    )
    assert len(_scan(_table("unit_campaigns"), f"JOIN_CODE#{FREE_CODE}")) == 1


def _table(name: str) -> Any:
    """The live moto table for a table key (used where a fixture is not a parameter)."""
    from src.utils.dynamodb import tables

    return getattr(tables, name)


def test_anonymous_create_writes_nothing(seeded: Dict[str, Any], unit_campaigns_table: Any) -> None:
    """AUTH-C-02: the unauthenticated surface cannot open a campaign."""
    assert_is_error(_call(CREATE_UNIT_CAMPAIGN_FIELD, None, input=_create_input()), ErrorCode.UNAUTHORIZED)
    assert _scan(unit_campaigns_table, f"JOIN_CODE#{FREE_CODE}") == []


# --- updateUnitCampaign (§1.5.2, CAMP-M-02) --------------------------------------


def _update(
    unit_campaign_id: str, caller: str, changes: Dict[str, Any], expected_version: int, key: str = "op-1"
) -> Any:
    return _call(
        UPDATE_UNIT_CAMPAIGN_FIELD,
        caller,
        input={
            "unitCampaignId": unit_campaign_id,
            **changes,
            "version": {"expectedVersion": expected_version},
            "idempotency": _idem(key),
        },
    )


def test_rename_and_deactivate_touch_nothing_else(seeded: Dict[str, Any]) -> None:
    """CAMP-M-02-01: active state is a predicate, not a balance to unwind."""
    before = _read_campaign(PACK_3149_FALL)
    membership_before = _read_membership(PACK_3149_FALL, "Devon")
    guard_before = ucm.read_membership_guard(_CAMPAIGN_OF["Devon"])
    scout_before = _scout_campaign("Devon")

    result = _update(
        PACK_3149_FALL,
        "Avery",
        {"campaignName": "Pack 3149 Fall Show & Sell (closed)", "isActive": False},
        int(before["version"]),
    )
    assert result["campaignName"] == "Pack 3149 Fall Show & Sell (closed)"
    assert result["isActive"] is False
    assert result["version"] == int(before["version"]) + 1
    assert result["updatedByAccountId"] == AVERY

    after = _read_campaign(PACK_3149_FALL)
    assert after["catalogId"] == before["catalogId"]
    assert after["joinCode"] == before["joinCode"]
    assert after["unitId"] == before["unitId"]

    assert _read_membership(PACK_3149_FALL, "Devon") == membership_before
    assert ucm.read_membership_guard(_CAMPAIGN_OF["Devon"]) == guard_before
    assert _scout_campaign("Devon") == scout_before
    # Deactivation does not revoke the credential: the pointer still resolves.
    assert ucm.find_join_code_pointers(str(before["joinCode"]))[0]["unitCampaignId"] == PACK_3149_FALL


def test_immutable_fields_are_refused_not_ignored(seeded: Dict[str, Any]) -> None:
    """CAMP-M-02-02: a different catalog means a different Unit Campaign."""
    for field, value in (
        ("catalogId", "CATALOG#fixture-public"),
        ("unitId", CREW_529),
        ("joinCode", FREE_CODE),
        ("createdAt", "2020-01-01T00:00:00+00:00"),
        ("createdByAccountId", BLAKE),
    ):
        payload = assert_is_error(
            _update(PACK_3149_FALL, "Avery", {field: value}, 1, key=f"op-immutable-{field}"),
            ErrorCode.INVALID_INPUT,
        )
        assert field in str(payload["message"])
    assert _read_campaign(PACK_3149_FALL)["catalogId"] == DEFAULT_CATALOG

    # The concurrency token belongs inside ``version``; a scalar there is not a
    # version input, and nothing is written from it.
    assert_is_error(
        _call(
            UPDATE_UNIT_CAMPAIGN_FIELD,
            "Avery",
            input={
                "unitCampaignId": PACK_3149_FALL,
                "campaignName": "Renamed",
                "version": 1,
                "idempotency": _idem("op-version-scalar"),
            },
        ),
        ErrorCode.INVALID_INPUT,
    )


def test_a_stale_version_loses_the_write(seeded: Dict[str, Any]) -> None:
    """VER-01: the version the caller read is the version the condition holds."""
    assert_is_error(_update(PACK_3149_FALL, "Avery", {"isActive": False}, 7), ErrorCode.CONFLICT)
    assert _read_campaign(PACK_3149_FALL)["isActive"] is True


def test_an_update_must_change_something_and_is_active_is_a_boolean(seeded: Dict[str, Any]) -> None:
    """Nothing is staged for an empty change set or a type the SDL does not allow."""
    assert_is_error(_update(PACK_3149_FALL, "Avery", {}, 1, key="op-empty"), ErrorCode.INVALID_INPUT)
    assert_is_error(_update(PACK_3149_FALL, "Avery", {"isActive": "false"}, 1, key="op-str"), ErrorCode.INVALID_INPUT)
    assert_is_error(
        _update(PACK_3149_FALL, "Avery", {"campaignName": "  "}, 1, key="op-blank"), ErrorCode.INVALID_INPUT
    )


def test_the_campaign_year_moves_with_the_season_it_names(seeded: Dict[str, Any]) -> None:
    """Re-naming a season is a metadata change; the year range is still enforced."""
    renamed = _update(PACK_3149_FALL, "Avery", {"campaignYear": 2027, "campaignName": "Pack 3149 Fall Show & Sell"}, 1)
    assert renamed["campaignYear"] == 2027
    assert renamed["campaignName"] == "Pack 3149 Fall Show & Sell"
    assert_is_error(_update(PACK_3149_FALL, "Avery", {"campaignYear": 1899}, 2, key="op-year"), ErrorCode.INVALID_INPUT)
    assert _read_campaign(PACK_3149_FALL)["campaignYear"] == 2027


def test_a_replayed_create_that_lost_its_campaign_is_an_internal_fault(
    seeded: Dict[str, Any], unit_campaigns_table: Any
) -> None:
    """A committed marker whose rows vanished is not answered by writing again."""
    created = _call(CREATE_UNIT_CAMPAIGN_FIELD, "Avery", input=_create_input())
    unit_campaigns_table.delete_item(Key=ucm.unit_campaign_metadata_key(str(created["unitCampaignId"])))
    assert_is_error(_call(CREATE_UNIT_CAMPAIGN_FIELD, "Avery", input=_create_input()), ErrorCode.INTERNAL_ERROR)
    assert ucm.read_unit_campaign(str(created["unitCampaignId"])) is None


def test_update_is_refused_for_a_campaign_of_another_unit(seeded: Dict[str, Any]) -> None:
    """AUTH-U: a Troop 7150 admin cannot write Pack 3149's campaigns by guessing ids."""
    assert_is_error(_update(PACK_3149_FALL, "Riley", {"isActive": False}, 1, key="op-auth-1"), ErrorCode.NOT_FOUND)
    assert_is_error(_update(CREW_529_SPRING, "Riley", {"isActive": False}, 1, key="op-auth-2"), ErrorCode.NOT_FOUND)
    assert _read_campaign(PACK_3149_FALL)["isActive"] is True
    assert _read_campaign(CREW_529_SPRING)["isActive"] is True


def test_update_replays_without_a_second_version_bump(seeded: Dict[str, Any]) -> None:
    """IDEM: the retry returns the version the first attempt wrote."""
    turn = {"campaignName": "Renamed Once"}
    first = _update(PACK_3149_FALL, "Avery", turn, 1)
    second = _update(PACK_3149_FALL, "Avery", turn, 1)
    assert second == first
    assert _read_campaign(PACK_3149_FALL)["version"] == 2


def test_a_deactivated_campaign_cannot_be_joined(seeded: Dict[str, Any]) -> None:
    """The code still resolves for the admin; it stops answering a join."""
    _update(PACK_3149_FALL, "Avery", {"isActive": False}, 1)
    assert_is_error(
        _call(
            JOIN_UNIT_CAMPAIGN_FIELD,
            "Blake",
            input={"joinCode": FALL_CODE, "campaignId": _CAMPAIGN_OF["Blake"], "idempotency": _idem()},
        ),
        ErrorCode.NOT_FOUND,
    )
    assert ucm.read_membership(PACK_3149_FALL, _PROFILE_OF["Blake"]) is None
    assert ucm.resolve_join_code(FALL_CODE, require_active=False) is not None


# --- unitCampaignJoinInfo (§1.5.3, AUTH-C) ---------------------------------------


def test_any_signed_in_account_sees_only_the_preview_fields(seeded: Dict[str, Any]) -> None:
    """The bare join code buys five display fields — no ids, no code, no settings."""
    unit = unit_models.read_unit(PACK_3149)
    result = _call(JOIN_PREVIEW_FIELD, "Blake", arguments={"joinCode": FALL_CODE})
    assert result == {
        "unitDisplayName": str(unit["displayName"]),
        "campaignName": "Pack 3149 Fall Show & Sell",
        "campaignYear": 2026,
        "catalogName": "Fixture Default Catalog",
        "isActive": True,
    }
    assert not {"unitId", "unitCampaignId", "catalogId", "joinCode", "version"} & set(result)


def test_preview_names_a_unit_with_no_chosen_display_name(seeded: Dict[str, Any], units_table: Any) -> None:
    """``displayName`` is optional storage; the metadata a Unit must carry forms the name."""
    units_table.update_item(
        Key={"pk": f"UNIT#{PACK_3149}", "sk": "METADATA"},
        UpdateExpression="REMOVE #displayName",
        ExpressionAttributeNames={"#displayName": "displayName"},
    )
    unit = unit_models.read_unit(PACK_3149)
    result = _call(JOIN_PREVIEW_FIELD, "Blake", arguments={"joinCode": FALL_CODE})
    assert result["unitDisplayName"] == f"{unit['unitType']} {unit['unitNumber']} ({unit['city']}, {unit['state']})"


def test_unknown_inactive_and_dangling_codes_answer_alike(seeded: Dict[str, Any], unit_campaigns_table: Any) -> None:
    """A probe cannot tell which case it hit; a malformed code never reaches a Query."""
    messages = set()
    for code in ("AAAAAAAAAAAAAAAA", OLD_CODE):
        error = assert_is_error(_call(JOIN_PREVIEW_FIELD, "Blake", arguments={"joinCode": code}), ErrorCode.NOT_FOUND)
        messages.add(str(error["message"]))
    assert len(messages) == 1
    assert_is_error(_call(JOIN_PREVIEW_FIELD, "Blake", arguments={"joinCode": "short"}), ErrorCode.INVALID_INPUT)

    unit_campaigns_table.delete_item(Key=ucm.unit_campaign_metadata_key(PACK_3149_FALL))
    assert_is_error(_call(JOIN_PREVIEW_FIELD, "Blake", arguments={"joinCode": FALL_CODE}), ErrorCode.NOT_FOUND)


def test_preview_cannot_answer_with_a_missing_catalog(seeded: Dict[str, Any], catalogs_table: Any) -> None:
    """The preview's catalog name is non-null, so an unusable code answers unknown."""
    catalogs_table.delete_item(Key={"catalogId": DEFAULT_CATALOG})
    assert_is_error(_call(JOIN_PREVIEW_FIELD, "Blake", arguments={"joinCode": FALL_CODE}), ErrorCode.NOT_FOUND)


def test_anonymous_join_preview_is_refused(seeded: Dict[str, Any]) -> None:
    """AUTH-C-01: no Unit, campaign, or catalog data on the unauthenticated surface."""
    assert_is_error(_call(JOIN_PREVIEW_FIELD, None, arguments={"joinCode": FALL_CODE}), ErrorCode.UNAUTHORIZED)


# --- joinUnitCampaign (§1.5.4, CAMP-M-03) ----------------------------------------


def _join(caller: str, join_code: str, campaign_id: str, key: str = "op-1") -> Any:
    return _call(
        JOIN_UNIT_CAMPAIGN_FIELD,
        caller,
        input={"joinCode": join_code, "campaignId": campaign_id, "idempotency": _idem(key)},
    )


def test_join_moves_membership_guard_and_link_together(seeded: Dict[str, Any]) -> None:
    """CAMP-M-03-01: eligibility starts with the join; no separate approval step."""
    result = _join("Blake", FALL_CODE, _CAMPAIGN_OF["Blake"])
    assert result["unitCampaignId"] == PACK_3149_FALL
    assert result["unitId"] == PACK_3149
    assert result["campaignId"] == _CAMPAIGN_OF["Blake"]
    assert result["profileId"] == _PROFILE_OF["Blake"]
    assert result["status"] == "ACTIVE"
    assert result["joinedByAccountId"] == BLAKE
    assert result["version"] == 1
    assert result["removedAt"] is None and result["removedByAccountId"] is None

    assert _read_membership(PACK_3149_FALL, "Blake")["status"] == "ACTIVE"
    guard = ucm.read_membership_guard(_CAMPAIGN_OF["Blake"])
    assert guard is not None and ucm.guard_active_unit_campaign_id(guard) == PACK_3149_FALL
    scout = _scout_campaign("Blake")
    assert scout["unitId"] == PACK_3149 and scout["unitCampaignId"] == PACK_3149_FALL


def test_a_write_share_may_join_on_the_owner_s_behalf(seeded: Dict[str, Any]) -> None:
    """Owner/WRITE is the existing Scout-side rule, and the member is the Profile's."""
    _remove("Avery", PACK_3149_FALL, _CAMPAIGN_OF["Devon"], 1, 1)
    result = _join("Taylor", SPRING_CODE, _CAMPAIGN_OF["Devon"], key="op-taylor")
    assert result["profileId"] == _PROFILE_OF["Devon"]
    assert result["campaignId"] == _CAMPAIGN_OF["Devon"]
    assert result["joinedByAccountId"] == TAYLOR
    assert _read_membership(CREW_529_SPRING, "Devon")["status"] == "ACTIVE"


def test_read_only_and_substituted_campaigns_are_refused(seeded: Dict[str, Any]) -> None:
    """CAMP-M-03-02: READ cannot join, and another Scout's campaignId is not yours."""
    assert_is_error(_join("Riley", FALL_CODE, _CAMPAIGN_OF["Avery"]), ErrorCode.FORBIDDEN)
    assert_is_error(_join("Emery", FALL_CODE, _CAMPAIGN_OF["Avery"]), ErrorCode.FORBIDDEN)
    assert ucm.read_membership(PACK_3149_FALL, _PROFILE_OF["Avery"]) is None
    assert ucm.read_membership_guard(_CAMPAIGN_OF["Avery"]) is None


def test_join_needs_a_known_campaign_and_a_usable_code(seeded: Dict[str, Any]) -> None:
    """CAMP-M-03-04: unknown campaign, unknown code, and inactive code all answer NOT_FOUND."""
    assert_is_error(_join("Blake", FALL_CODE, "CAMPAIGN#never-seeded"), ErrorCode.NOT_FOUND)
    assert_is_error(_join("Blake", "AAAAAAAAAAAAAAAA", _CAMPAIGN_OF["Blake"]), ErrorCode.NOT_FOUND)
    assert_is_error(_join("Blake", OLD_CODE, _CAMPAIGN_OF["Blake"]), ErrorCode.NOT_FOUND)
    assert_is_error(_join("Blake", "short", _CAMPAIGN_OF["Blake"]), ErrorCode.INVALID_INPUT)


def test_one_scout_campaign_holds_one_active_join(seeded: Dict[str, Any]) -> None:
    """CAMP-M-03-03: the guard's slot is the authority, not the roster row count."""
    assert_is_error(_join("Devon", SPRING_CODE, _CAMPAIGN_OF["Devon"]), ErrorCode.CONFLICT)
    assert ucm.read_membership(CREW_529_SPRING, _PROFILE_OF["Devon"]) is None
    assert ucm.guard_active_unit_campaign_id(ucm.read_membership_guard(_CAMPAIGN_OF["Devon"])) == PACK_3149_FALL


def test_rejoining_the_same_roster_is_a_conflict(seeded: Dict[str, Any]) -> None:
    """An ACTIVE membership is not re-opened; the slot would be claimed twice."""
    assert_is_error(_join("Devon", FALL_CODE, _CAMPAIGN_OF["Devon"]), ErrorCode.CONFLICT)
    assert _read_membership(PACK_3149_FALL, "Devon")["version"] == 1


def test_a_removed_scout_may_join_a_different_unit_campaign(seeded: Dict[str, Any]) -> None:
    """Removal frees the slot; the old roster keeps its removed history."""
    result = _join("Emery", SPRING_CODE, _CAMPAIGN_OF["Emery"])
    assert result["unitCampaignId"] == CREW_529_SPRING
    assert result["status"] == "ACTIVE"
    assert _read_membership(PACK_3149_OLD, "Emery")["status"] == "REMOVED"
    guard = ucm.read_membership_guard(_CAMPAIGN_OF["Emery"])
    assert guard is not None and ucm.guard_active_unit_campaign_id(guard) == CREW_529_SPRING
    assert _read_campaign(PACK_3149_OLD)["isActive"] is False


def test_reactivating_a_removed_membership_keeps_one_record(seeded: Dict[str, Any], unit_campaigns_table: Any) -> None:
    """The same ``(unitCampaignId, profileId)`` row comes back ACTIVE, audit removed."""
    _activate_campaign(unit_campaigns_table, PACK_3149_OLD)
    before = _read_membership(PACK_3149_OLD, "Emery")
    assert before["status"] == "REMOVED"

    result = _join("Emery", OLD_CODE, _CAMPAIGN_OF["Emery"])
    assert result["unitCampaignId"] == PACK_3149_OLD
    assert result["status"] == "ACTIVE"
    assert result["version"] == int(before["version"]) + 1
    assert result["removedAt"] is None and result["removedByAccountId"] is None

    rows = _membership_rows(unit_campaigns_table, PACK_3149_OLD)
    assert len(rows) == 1
    assert "removedAt" not in rows[0] and "removedByAccountId" not in rows[0]
    guard = ucm.read_membership_guard(_CAMPAIGN_OF["Emery"])
    assert guard is not None and ucm.guard_active_unit_campaign_id(guard) == PACK_3149_OLD


def test_join_replays_without_a_second_membership(seeded: Dict[str, Any]) -> None:
    """The join-code marker makes a retry answer the original join."""
    first = _join("Blake", FALL_CODE, _CAMPAIGN_OF["Blake"])
    second = _join("Blake", FALL_CODE, _CAMPAIGN_OF["Blake"])
    assert second == first
    assert _read_membership(PACK_3149_FALL, "Blake")["version"] == 1
    guard = ucm.read_membership_guard(_CAMPAIGN_OF["Blake"])
    assert guard is not None and int(guard["membershipVersion"]) == 1


def test_two_first_joins_cannot_both_claim_the_slot(seeded: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard's conditional insert, not the pre-read, settles the race.

    Both readers see no guard row; only one transaction may create it, and the
    loser's membership and Campaign link roll back with it.
    """
    _join("Taylor", FALL_CODE, _CAMPAIGN_OF["Taylor"])
    monkeypatch.setattr(ucm, "read_membership_guard", lambda campaign_id: None)
    assert_is_error(_join("Taylor", SPRING_CODE, _CAMPAIGN_OF["Taylor"], key="op-race"), ErrorCode.CONFLICT)
    assert ucm.read_membership(CREW_529_SPRING, _PROFILE_OF["Taylor"]) is None
    assert _scout_campaign("Taylor")["unitCampaignId"] == PACK_3149_FALL


def test_a_broken_join_replay_is_an_internal_fault(seeded: Dict[str, Any], campaigns_table: Any) -> None:
    """The retry cannot re-derive a membership that is gone, and does not re-join."""
    _join("Blake", FALL_CODE, _CAMPAIGN_OF["Blake"])
    campaigns_table.delete_item(Key={"profileId": _PROFILE_OF["Blake"], "campaignId": _CAMPAIGN_OF["Blake"]})
    assert_is_error(_join("Blake", FALL_CODE, _CAMPAIGN_OF["Blake"]), ErrorCode.INTERNAL_ERROR)
    assert _read_membership(PACK_3149_FALL, "Blake")["status"] == "ACTIVE"


def test_a_roster_entry_for_another_scout_campaign_conflicts(seeded: Dict[str, Any], unit_campaigns_table: Any) -> None:
    """The membership's immutable Campaign identity is checked, not assumed."""
    unit_campaigns_table.put_item(
        Item=unit_campaign_membership_item(
            PACK_3149_FALL, PACK_3149, _CAMPAIGN_OF["Avery"], _PROFILE_OF["Blake"], joined_by="Blake"
        )
    )
    assert_is_error(_join("Blake", FALL_CODE, _CAMPAIGN_OF["Blake"]), ErrorCode.CONFLICT)
    assert _read_membership(PACK_3149_FALL, "Blake")["campaignId"] == _CAMPAIGN_OF["Avery"]


def test_anonymous_join_writes_nothing(seeded: Dict[str, Any]) -> None:
    """AUTH-C-02: the public/API-key surface cannot join a Scout in."""
    assert_is_error(_join(None, FALL_CODE, _CAMPAIGN_OF["Blake"]), ErrorCode.UNAUTHORIZED)
    assert ucm.read_membership(PACK_3149_FALL, _PROFILE_OF["Blake"]) is None
    assert ucm.read_membership_guard(_CAMPAIGN_OF["Blake"]) is None
    assert _scout_campaign("Blake").get("unitCampaignId") is None


# --- removeUnitCampaignMembership (§1.5.5, CAMP-M-04) ----------------------------


def _remove(
    caller: str,
    unit_campaign_id: str,
    campaign_id: str,
    membership_version: int,
    guard_version: int,
    key: str = "op-1",
) -> Any:
    return _call(
        REMOVE_MEMBERSHIP_FIELD,
        caller,
        input={
            "unitCampaignId": unit_campaign_id,
            "campaignId": campaign_id,
            "expectedMembershipVersion": membership_version,
            "expectedGuardVersion": guard_version,
            "idempotency": _idem(key),
        },
    )


def test_removal_sets_history_and_frees_the_slot(seeded: Dict[str, Any]) -> None:
    """CAMP-M-04-01: the record stays, the guard stops claiming it."""
    result = _remove("Avery", PACK_3149_FALL, _CAMPAIGN_OF["Devon"], 1, 1)
    assert result["status"] == "REMOVED"
    assert result["removedByAccountId"] == AVERY
    assert result["removedAt"] is not None
    assert result["version"] == 2

    guard = ucm.read_membership_guard(_CAMPAIGN_OF["Devon"])
    assert guard is not None
    assert ucm.guard_active_unit_campaign_id(guard) is None
    assert int(guard["membershipVersion"]) == 2


def test_removal_keeps_the_campaign_link_and_the_roster_row(seeded: Dict[str, Any], unit_campaigns_table: Any) -> None:
    """API-FIX-05: joined history survives removal; nothing cascades."""
    link_before = _scout_campaign("Devon")
    _remove("Avery", PACK_3149_FALL, _CAMPAIGN_OF["Devon"], 1, 1)
    assert _scout_campaign("Devon") == link_before
    rows = _membership_rows(unit_campaigns_table, PACK_3149_FALL)
    assert len(rows) == 1
    assert rows[0]["status"] == "REMOVED"


def test_a_signup_racing_removal_loses_its_condition(seeded: Dict[str, Any]) -> None:
    """CAMP-M-04-02: the version a signup holds is exactly what removal bumps.

    Stage 3 signups condition on the membership version they read; this is that
    condition written by hand and replayed after the removal it raced.
    """
    from botocore.exceptions import ClientError

    _remove("Avery", PACK_3149_FALL, _CAMPAIGN_OF["Devon"], 1, 1)
    with pytest.raises(ClientError) as caught:
        _table("unit_campaigns").update_item(
            Key=ucm.membership_key(PACK_3149_FALL, _PROFILE_OF["Devon"]),
            UpdateExpression="SET #signupCount = if_not_exists(#signupCount, :zero) + :one",
            ExpressionAttributeNames={"#signupCount": "signupCount", "#version": "version"},
            ExpressionAttributeValues={":zero": 0, ":one": 1, ":version": 1},
            ConditionExpression="#version = :version",
        )
    assert caught.value.response["Error"]["Code"] == "ConditionalCheckFailedException"
    assert "signupCount" not in _read_membership(PACK_3149_FALL, "Devon")


def test_either_version_being_stale_loses_the_whole_write(seeded: Dict[str, Any]) -> None:
    """CAMP-M-04-03: two rows move, so a caller holding either one stale loses both."""
    assert_is_error(_remove("Avery", PACK_3149_FALL, _CAMPAIGN_OF["Devon"], 9, 1), ErrorCode.CONFLICT)
    assert_is_error(_remove("Avery", PACK_3149_FALL, _CAMPAIGN_OF["Devon"], 1, 9), ErrorCode.CONFLICT)
    assert_is_error(_remove("Avery", PACK_3149_FALL, _CAMPAIGN_OF["Devon"], 9, 9), ErrorCode.CONFLICT)
    assert _read_membership(PACK_3149_FALL, "Devon")["status"] == "ACTIVE"
    assert _scout_campaign("Devon")["unitCampaignId"] == PACK_3149_FALL


def test_removal_requires_the_versions_the_caller_read(seeded: Dict[str, Any]) -> None:
    """A missing, zero, boolean, or unparseable version is a client error."""
    for omitted in ("expectedMembershipVersion", "expectedGuardVersion"):
        body = {
            "unitCampaignId": PACK_3149_FALL,
            "campaignId": _CAMPAIGN_OF["Devon"],
            "expectedMembershipVersion": 1,
            "expectedGuardVersion": 1,
            "idempotency": _idem(),
        }
        body.pop(omitted)
        assert_is_error(_call(REMOVE_MEMBERSHIP_FIELD, "Avery", input=body), ErrorCode.INVALID_INPUT)
    for field, value in (
        ("expectedMembershipVersion", 0),
        ("expectedMembershipVersion", True),
        ("expectedGuardVersion", "one"),
    ):
        body = {
            "unitCampaignId": PACK_3149_FALL,
            "campaignId": _CAMPAIGN_OF["Devon"],
            "expectedMembershipVersion": 1,
            "expectedGuardVersion": 1,
            "idempotency": _idem(),
        }
        body[field] = value
        assert_is_error(_call(REMOVE_MEMBERSHIP_FIELD, "Avery", input=body), ErrorCode.INVALID_INPUT)


def test_removal_needs_an_admin_and_a_real_roster_entry(seeded: Dict[str, Any], unit_campaigns_table: Any) -> None:
    """AUTH-U plus NOT_FOUND for a Scout who is not on this roster."""
    assert_is_error(_remove("Blake", PACK_3149_FALL, _CAMPAIGN_OF["Devon"], 1, 1), ErrorCode.NOT_FOUND)
    assert_is_error(_remove("Avery", PACK_3149_FALL, _CAMPAIGN_OF["Blake"], 1, 1), ErrorCode.NOT_FOUND)
    assert_is_error(_remove("Avery", PACK_3149_FALL, "CAMPAIGN#never-seeded", 1, 1), ErrorCode.NOT_FOUND)
    assert_is_error(_remove("Avery", "uc-nope", _CAMPAIGN_OF["Devon"], 1, 1), ErrorCode.NOT_FOUND)

    # A roster row whose immutable Campaign identity differs is not this entry.
    unit_campaigns_table.put_item(
        Item=unit_campaign_membership_item(
            PACK_3149_FALL, PACK_3149, _CAMPAIGN_OF["Avery"], _PROFILE_OF["Blake"], joined_by="Blake"
        )
    )
    assert_is_error(_remove("Avery", PACK_3149_FALL, _CAMPAIGN_OF["Blake"], 1, 1), ErrorCode.NOT_FOUND)


def test_removal_without_a_guard_row_cannot_half_apply(seeded: Dict[str, Any], unit_campaigns_table: Any) -> None:
    """The release condition needs the guard it is freeing; the roster stays ACTIVE."""
    unit_campaigns_table.delete_item(Key=ucm.guard_key(_CAMPAIGN_OF["Devon"]))
    assert_is_error(_remove("Avery", PACK_3149_FALL, _CAMPAIGN_OF["Devon"], 1, 1), ErrorCode.CONFLICT)
    assert _read_membership(PACK_3149_FALL, "Devon")["status"] == "ACTIVE"


def test_removing_a_removed_scout_conflicts(seeded: Dict[str, Any]) -> None:
    """A second removal is not a silent no-op that bumps the version."""
    membership = _read_membership(PACK_3149_OLD, "Emery")
    guard = ucm.read_membership_guard(_CAMPAIGN_OF["Emery"])
    assert membership["status"] == "REMOVED"
    assert_is_error(
        _remove(
            "Avery",
            PACK_3149_OLD,
            _CAMPAIGN_OF["Emery"],
            int(membership["version"]),
            int(guard["membershipVersion"]) if guard else 1,
        ),
        ErrorCode.CONFLICT,
    )
    assert _read_membership(PACK_3149_OLD, "Emery")["version"] == membership["version"]


def test_removal_replays_without_a_second_transition(seeded: Dict[str, Any]) -> None:
    """IDEM: the retry answers the removal it already made."""
    first = _remove("Avery", PACK_3149_FALL, _CAMPAIGN_OF["Devon"], 1, 1)
    second = _remove("Avery", PACK_3149_FALL, _CAMPAIGN_OF["Devon"], 1, 1)
    assert second == first
    assert _read_membership(PACK_3149_FALL, "Devon")["version"] == 2


# --- campaign and roster queries (§1.5.6, UNIT-Q-07…09) --------------------------


def test_admin_gets_the_campaign_with_its_code_and_version(seeded: Dict[str, Any]) -> None:
    """UNIT-Q-07-01."""
    result = _call(UNIT_CAMPAIGN_FIELD, "Avery", arguments={"unitCampaignId": PACK_3149_FALL})
    assert result["joinCode"] == FALL_CODE
    assert result["catalogId"] == DEFAULT_CATALOG
    assert result["version"] == 1
    assert result["isActive"] is True


def test_the_admin_query_is_closed_to_a_scout(seeded: Dict[str, Any]) -> None:
    """UNIT-Q-07-02 / AUTH-U: the join preview is the only Scout path."""
    for caller in ("Blake", "Devon", "Riley"):
        assert_is_error(
            _call(UNIT_CAMPAIGN_FIELD, caller, arguments={"unitCampaignId": PACK_3149_FALL}), ErrorCode.NOT_FOUND
        )
    assert_is_error(_call(UNIT_CAMPAIGN_FIELD, "Avery", arguments={"unitCampaignId": "uc-nope"}), ErrorCode.NOT_FOUND)
    assert_is_error(_call(UNIT_CAMPAIGN_FIELD, "Avery", arguments={}), ErrorCode.INVALID_INPUT)


def test_campaigns_are_newest_first_and_filterable(seeded: Dict[str, Any]) -> None:
    """UNIT-Q-08-01: only this Unit's campaigns, active and deactivated."""
    everything = _call(UNIT_CAMPAIGNS_FIELD, "Avery", arguments={"unitId": PACK_3149})
    assert [item["unitCampaignId"] for item in everything["items"]] == [PACK_3149_FALL, PACK_3149_OLD]
    assert everything["pageInfo"] == {"endCursor": None, "hasNextPage": False}
    assert all("joinCode" in item for item in everything["items"])

    active = _call(UNIT_CAMPAIGNS_FIELD, "Avery", arguments={"unitId": PACK_3149, "isActive": True})
    assert [item["unitCampaignId"] for item in active["items"]] == [PACK_3149_FALL]
    inactive = _call(UNIT_CAMPAIGNS_FIELD, "Avery", arguments={"unitId": PACK_3149, "isActive": False})
    assert [item["unitCampaignId"] for item in inactive["items"]] == [PACK_3149_OLD]


def test_campaign_listing_is_denied_and_never_crosses_units(seeded: Dict[str, Any]) -> None:
    """AUTH-U: a Troop 7150 admin sees no Pack 3149 campaign, and none of another Unit's."""
    assert_is_error(_call(UNIT_CAMPAIGNS_FIELD, "Riley", arguments={"unitId": PACK_3149}), ErrorCode.NOT_FOUND)
    assert_is_error(_call(UNIT_CAMPAIGNS_FIELD, "Blake", arguments={"unitId": PACK_3149}), ErrorCode.NOT_FOUND)
    assert _call(UNIT_CAMPAIGNS_FIELD, "Riley", arguments={"unitId": TROOP_7150})["items"] == []
    assert_is_error(
        _call(UNIT_CAMPAIGNS_FIELD, "Avery", arguments={"unitId": PACK_3149, "isActive": "yes"}),
        ErrorCode.INVALID_INPUT,
    )


def test_campaign_pages_walk_the_list_and_a_cursor_stays_in_its_scope(seeded: Dict[str, Any]) -> None:
    """PAGE-01: pagination is complete, and the cursor belongs to the filter that issued it."""
    first = _call(UNIT_CAMPAIGNS_FIELD, "Avery", arguments={"unitId": PACK_3149, "page": {"limit": 1}})
    assert len(first["items"]) == 1 and first["pageInfo"]["hasNextPage"] is True
    second = _call(
        UNIT_CAMPAIGNS_FIELD,
        "Avery",
        arguments={"unitId": PACK_3149, "page": {"limit": 1, "cursor": first["pageInfo"]["endCursor"]}},
    )
    assert [item["unitCampaignId"] for item in second["items"]] == [PACK_3149_OLD]
    assert second["pageInfo"]["hasNextPage"] is False

    assert_is_error(
        _call(
            UNIT_CAMPAIGNS_FIELD,
            "Avery",
            arguments={
                "unitId": PACK_3149,
                "isActive": True,
                "page": {"limit": 1, "cursor": first["pageInfo"]["endCursor"]},
            },
        ),
        ErrorCode.INVALID_INPUT,
    )


def test_catalog_products_come_back_in_display_order(seeded: Dict[str, Any], catalogs_table: Any) -> None:
    """The campaign's sales-sheet inputs, in the catalog's own order."""
    catalogs_table.put_item(
        Item=catalog_item(
            "CATALOG#three-products",
            "Three Product Catalog",
            owner="Avery",
            products=[
                {
                    "productId": "p-3",
                    "productName": "Third",
                    "description": "c3",
                    "price": Decimal("3.00"),
                    "sortOrder": 3,
                },
                {"productId": "p-1", "productName": "First", "price": Decimal("1.00"), "sortOrder": 1},
                {
                    "productId": "p-2",
                    "productName": "Second",
                    "description": "c2",
                    "price": Decimal("2.50"),
                    "sortOrder": 2,
                },
            ],
        )
    )
    created = _call(
        CREATE_UNIT_CAMPAIGN_FIELD,
        "Avery",
        input=_create_input(catalog_id="CATALOG#three-products"),
    )
    result = _call(UNIT_CAMPAIGN_CATALOG_FIELD, "Avery", arguments={"unitCampaignId": created["unitCampaignId"]})
    assert result["catalogId"] == "CATALOG#three-products"
    assert result["catalogName"] == "Three Product Catalog"
    assert [product["productId"] for product in result["products"]] == ["p-1", "p-2", "p-3"]
    assert result["products"][0] == {
        "productId": "p-1",
        "productName": "First",
        "description": None,
        "price": 1.0,
        "sortOrder": 1,
    }
    assert isinstance(result["products"][1]["price"], float)


def test_catalog_reads_are_admin_only_and_a_deleted_catalog_still_reads(
    seeded: Dict[str, Any], catalogs_table: Any
) -> None:
    """Admin-only, and a later soft-delete does not blank a campaign's sheet."""
    assert_is_error(
        _call(UNIT_CAMPAIGN_CATALOG_FIELD, "Devon", arguments={"unitCampaignId": PACK_3149_FALL}), ErrorCode.NOT_FOUND
    )
    catalogs_table.update_item(
        Key={"catalogId": DEFAULT_CATALOG},
        UpdateExpression="SET #deleted = :yes",
        ExpressionAttributeNames={"#deleted": "isDeleted"},
        ExpressionAttributeValues={":yes": True},
    )
    result = _call(UNIT_CAMPAIGN_CATALOG_FIELD, "Avery", arguments={"unitCampaignId": PACK_3149_FALL})
    assert result["catalogName"] == "Fixture Default Catalog"

    catalogs_table.delete_item(Key={"catalogId": DEFAULT_CATALOG})
    assert_is_error(
        _call(UNIT_CAMPAIGN_CATALOG_FIELD, "Avery", arguments={"unitCampaignId": PACK_3149_FALL}),
        ErrorCode.NOT_FOUND,
    )


def test_a_catalog_with_no_products_answers_an_empty_sheet(seeded: Dict[str, Any], catalogs_table: Any) -> None:
    """An empty catalog is a real answer, not a fault — events with no sales included."""
    catalogs_table.put_item(Item=catalog_item("CATALOG#empty-products", "Empty Catalog", owner="Avery", products=[]))
    created = _call(CREATE_UNIT_CAMPAIGN_FIELD, "Avery", input=_create_input(catalog_id="CATALOG#empty-products"))
    result = _call(UNIT_CAMPAIGN_CATALOG_FIELD, "Avery", arguments={"unitCampaignId": created["unitCampaignId"]})
    assert result["products"] == []


def test_roster_keeps_removed_history_and_filters_by_status(seeded: Dict[str, Any]) -> None:
    """UNIT-Q-09-01: a removed Scout stays on the roster under the identity they joined with."""
    _remove("Avery", PACK_3149_FALL, _CAMPAIGN_OF["Devon"], 1, 1)
    roster = _call(UNIT_CAMPAIGN_ROSTER_FIELD, "Avery", arguments={"unitCampaignId": PACK_3149_FALL})
    assert [item["campaignId"] for item in roster["items"]] == [_CAMPAIGN_OF["Devon"]]
    assert roster["items"][0]["status"] == "REMOVED"
    assert roster["items"][0]["removedByAccountId"] == AVERY

    removed_only = _call(
        UNIT_CAMPAIGN_ROSTER_FIELD, "Avery", arguments={"unitCampaignId": PACK_3149_FALL, "status": "REMOVED"}
    )
    assert [item["campaignId"] for item in removed_only["items"]] == [_CAMPAIGN_OF["Devon"]]
    active_only = _call(
        UNIT_CAMPAIGN_ROSTER_FIELD, "Avery", arguments={"unitCampaignId": PACK_3149_FALL, "status": "ACTIVE"}
    )
    assert active_only["items"] == []
    scouts = _call(
        UNIT_CAMPAIGN_ROSTER_FIELD, "Avery", arguments={"unitCampaignId": CREW_529_SPRING, "status": "ACTIVE"}
    )
    assert [item["campaignId"] for item in scouts["items"]] == [_CAMPAIGN_OF["Riley"]]


def test_roster_is_admin_only_and_refuses_an_unknown_status(seeded: Dict[str, Any]) -> None:
    """AUTH-U on the roster too, including for the Scout named on it."""
    assert_is_error(
        _call(UNIT_CAMPAIGN_ROSTER_FIELD, "Devon", arguments={"unitCampaignId": PACK_3149_FALL}), ErrorCode.NOT_FOUND
    )
    assert_is_error(
        _call(UNIT_CAMPAIGN_ROSTER_FIELD, "Riley", arguments={"unitCampaignId": PACK_3149_FALL}), ErrorCode.NOT_FOUND
    )
    assert_is_error(
        _call(UNIT_CAMPAIGN_ROSTER_FIELD, "Avery", arguments={"unitCampaignId": PACK_3149_FALL, "status": "GONE"}),
        ErrorCode.INVALID_INPUT,
    )
    assert_is_error(_call(UNIT_CAMPAIGN_ROSTER_FIELD, "Avery", arguments={}), ErrorCode.INVALID_INPUT)


def test_roster_pages_and_the_cursor_belongs_to_its_status_filter(
    seeded: Dict[str, Any], unit_campaigns_table: Any
) -> None:
    """PAGE-01 on the roster: complete pages, and a cursor is refused across filters."""
    for persona in ("Blake", "Emery", "Taylor"):
        unit_campaigns_table.put_item(
            Item=unit_campaign_membership_item(
                PACK_3149_FALL, PACK_3149, _CAMPAIGN_OF[persona], _PROFILE_OF[persona], joined_by=persona
            )
        )
    unit_campaigns_table.put_item(
        Item=unit_campaign_membership_item(
            PACK_3149_FALL,
            PACK_3149,
            _CAMPAIGN_OF["Avery"],
            _PROFILE_OF["Avery"],
            status="REMOVED",
            joined_by="Avery",
            removed_by="Avery",
        )
    )
    first = _call(
        UNIT_CAMPAIGN_ROSTER_FIELD, "Avery", arguments={"unitCampaignId": PACK_3149_FALL, "page": {"limit": 2}}
    )
    assert len(first["items"]) == 2 and first["pageInfo"]["hasNextPage"] is True
    second = _call(
        UNIT_CAMPAIGN_ROSTER_FIELD,
        "Avery",
        arguments={"unitCampaignId": PACK_3149_FALL, "page": {"limit": 2, "cursor": first["pageInfo"]["endCursor"]}},
    )
    assert len(second["items"]) == 2 and second["pageInfo"]["hasNextPage"] is True
    third = _call(
        UNIT_CAMPAIGN_ROSTER_FIELD,
        "Avery",
        arguments={"unitCampaignId": PACK_3149_FALL, "page": {"limit": 2, "cursor": second["pageInfo"]["endCursor"]}},
    )
    assert len(third["items"]) == 1 and third["pageInfo"]["hasNextPage"] is False
    seen = {item["profileId"] for item in first["items"] + second["items"] + third["items"]}
    assert seen == {_PROFILE_OF[persona] for persona in ("Avery", "Blake", "Devon", "Emery", "Taylor")}

    assert_is_error(
        _call(
            UNIT_CAMPAIGN_ROSTER_FIELD,
            "Avery",
            arguments={
                "unitCampaignId": PACK_3149_FALL,
                "status": "ACTIVE",
                "page": {"limit": 2, "cursor": first["pageInfo"]["endCursor"]},
            },
        ),
        ErrorCode.INVALID_INPUT,
    )
