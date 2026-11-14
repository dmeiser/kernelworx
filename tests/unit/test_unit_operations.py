"""Leaf 1.2 — Unit mutations: createUnit, updateUnit, revokeUnitAccessGrant.

The tests the leaf names, driven through the handler entrypoint with the Stage 1
fixture event builder:

- ``UNIT-M-01`` — creator becomes the initial admin, the exact-metadata gate
  needs ``duplicateConfirmed``, equal numbers in different cities need no
  workaround, and the bootstrap ``IDEM`` contract holds (identical retry replays,
  changed fingerprint is rejected, the bootstrap marker is preserved).
- ``updateUnit`` — removed-admin denial, stale version, duplicate re-check,
  idempotent retry.
- ``revokeUnitAccessGrant`` — final-grant ``CONFLICT``, add/revoke race,
  immediate access loss, idempotent retry, zero partial write on failure.
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.handlers.unit_operations import (
    CREATE_UNIT_FIELD,
    REVOKE_GRANT_FIELD,
    UPDATE_UNIT_FIELD,
    handle_unit_operation,
)
from src.utils.errors import ErrorCode
from tests.unit.show_sell_fixtures import account_id, assert_is_error, grant_item, unit_item, unit_operation_event

AVERY = account_id("Avery")
CASEY = "77777777-7777-4777-8777-777777777777"
MORGAN = "88888888-8888-4888-8888-888888888888"
RILEY = account_id("Riley")

PACK_ID = "unit-pack-3149-aurora"
BOULDER_ID = "unit-pack-3149-boulder"
CREW_ID = "unit-crew-529-denver"

BASE_INPUT: Dict[str, Any] = {
    "unitType": "Pack",
    "unitNumber": 3149,
    "city": "Aurora",
    "state": "CO",
    "timezone": "America/Denver",
}


def _rows(units_table: Any) -> List[Dict[str, Any]]:
    return list(units_table.scan()["Items"])


def _markers(units_table: Any) -> List[Dict[str, Any]]:
    return [row for row in _rows(units_table) if str(row["pk"]).startswith("IDEM#")]


def _seed_unit(
    units_table: Any, unit_id: str, *, admins: List[str], city: str = "Aurora", admin_count: int | None = None
) -> None:
    """Write a Unit plus one grant per listed admin, consistent with adminCount."""
    units_table.put_item(
        Item=unit_item(
            unit_id,
            "Pack",
            3149,
            city,
            "CO",
            created_by=AVERY,
            admin_count=admin_count if admin_count is not None else len(admins),
        )
    )
    for admin in admins:
        units_table.put_item(Item=grant_item(unit_id, admin, created_by=AVERY))


def _create_input(**overrides: Any) -> Dict[str, Any]:
    payload = dict(BASE_INPUT)
    payload["idempotency"] = {"idempotencyKey": overrides.pop("idempotencyKey", "create-1")}
    payload.update(overrides)
    return payload


def _create(units_table: Any, caller: Any, **overrides: Any) -> Dict[str, Any]:
    return handle_unit_operation(
        unit_operation_event(CREATE_UNIT_FIELD, caller, input=_create_input(**overrides)), None
    )


# --- createUnit (UNIT-M-01) ------------------------------------------------------


def test_create_unit_makes_the_caller_the_initial_admin(units_table: Any) -> None:
    """UNIT-M-01-01: stable unitId, adminCount 1, and the creator's grant."""
    payload = _create(units_table, AVERY)

    unit = payload["unit"]
    assert unit["unitId"]
    assert unit["adminCount"] == 1
    assert unit["version"] == 1
    assert unit["unitType"] == "Pack"
    assert unit["unitNumber"] == 3149
    assert unit["displayName"] == "Pack 3149 - Aurora, CO"
    assert unit["metadataKey"] == "pack#3149#aurora#co"
    assert unit["splitDefault"] == "EQUAL"
    assert unit["councilNeedBasis"] == "PHYSICAL_STOCK"
    assert unit["createdByAccountId"] == AVERY
    assert "pk" not in unit and "sk" not in unit

    grant = payload["grant"]
    assert grant["accountId"] == AVERY
    assert grant["role"] == "UNIT_ADMIN"
    assert grant["unitId"] == unit["unitId"]
    assert grant["createdByAccountId"] == AVERY

    stored = _rows(units_table)
    keys = {(row["pk"], row["sk"]) for row in stored}
    assert keys == {
        (f"UNIT#{unit['unitId']}", "METADATA"),
        (f"UNIT#{unit['unitId']}", f"GRANT#{AVERY}"),
        (f"IDEM#{AVERY}#createUnit#BOOTSTRAP", "IDEM#create-1"),
    }


def test_create_unit_writes_one_grant_and_a_completed_bootstrap_marker(units_table: Any) -> None:
    """The marker rides in the same transaction and is answerable for a retry."""
    payload = _create(units_table, AVERY)
    marker = _markers(units_table)[0]

    assert marker["pk"] == f"IDEM#{AVERY}#createUnit#BOOTSTRAP"
    assert marker["status"] == "COMPLETED"
    assert marker["resultId"] == payload["unit"]["unitId"]
    assert marker["expiresAtEpoch"] > 0
    assert int(marker["expiresAtEpoch"]) - _epoch_now() <= 7 * 24 * 3600


def _epoch_now() -> int:
    from datetime import datetime, timezone

    return int(datetime.now(timezone.utc).timestamp())


def test_duplicate_metadata_requires_confirmation_then_creates_a_distinct_unit(units_table: Any) -> None:
    """UNIT-M-01-02: the gate warns, and confirming creates a separate Unit."""
    first = _create(units_table, AVERY)["unit"]

    denied = handle_unit_operation(unit_operation_event(CREATE_UNIT_FIELD, CASEY, input=_create_input()), None)
    assert_is_error(denied, ErrorCode.INVALID_INPUT)
    assert "duplicateConfirmed" in denied["message"]
    assert len([row for row in _rows(units_table) if row["sk"] == "METADATA"]) == 1

    confirmed = _create(units_table, CASEY, duplicateConfirmed=True, idempotencyKey="create-2")["unit"]
    assert confirmed["unitId"] != first["unitId"]
    assert confirmed["metadataKey"] == first["metadataKey"] == "pack#3149#aurora#co"
    # No merge and no shared administration: each caller owns only their own Unit.
    cross_denied = handle_unit_operation(
        unit_operation_event(
            UPDATE_UNIT_FIELD,
            CASEY,
            input={
                "unitId": first["unitId"],
                "version": {"expectedVersion": 1},
                "city": "Denver",
                "idempotency": {"idempotencyKey": "x-1"},
            },
        ),
        None,
    )
    assert_is_error(cross_denied, ErrorCode.NOT_FOUND)


def test_equal_numbers_in_different_cities_need_no_workaround(units_table: Any) -> None:
    """UNIT-M-01-03: the city discriminates, so no confirmation is demanded."""
    first = _create(units_table, AVERY)["unit"]
    second = _create(units_table, CASEY, city="Boulder", idempotencyKey="create-2")["unit"]

    assert first["unitId"] != second["unitId"]
    assert second["metadataKey"] == "pack#3149#boulder#co"
    assert second["displayName"] == "Pack 3149 - Boulder, CO"


# --- idempotency (bootstrap scope) ----------------------------------------------


def test_identical_create_retry_replays_the_original_result(units_table: Any) -> None:
    """IDEM-01 at the bootstrap scope: one Unit, one grant, original payload."""
    first = _create(units_table, AVERY)
    retry = _create(units_table, AVERY)

    assert retry == first
    rows = _rows(units_table)
    assert len([row for row in rows if row["sk"] == "METADATA"]) == 1
    assert len([row for row in rows if row["sk"] == f"GRANT#{AVERY}"]) == 1
    assert len(_markers(units_table)) == 1
    assert [row for row in rows if row["sk"] == "METADATA"][0]["adminCount"] == 1


def test_create_retry_with_changed_content_is_rejected(units_table: Any) -> None:
    """IDEM-02: same key, different normalized content, nothing written."""
    first = _create(units_table, AVERY)
    changed = handle_unit_operation(
        unit_operation_event(CREATE_UNIT_FIELD, AVERY, input=_create_input(city="Boulder")), None
    )
    assert_is_error(changed, ErrorCode.INVALID_INPUT)

    rows = _rows(units_table)
    assert len([row for row in rows if row["sk"] == "METADATA"]) == 1
    assert [row for row in rows if row["sk"] == "METADATA"][0]["unitId"] == first["unit"]["unitId"]


def test_the_same_key_from_a_different_caller_creates_its_own_unit(units_table: Any) -> None:
    """The marker is scoped to actor + operation + resource scope."""
    first = _create(units_table, AVERY)
    second = _create(units_table, CASEY, city="Boulder")

    assert second["unit"]["unitId"] != first["unit"]["unitId"]
    assert len([row for row in _rows(units_table) if row["sk"] == "METADATA"]) == 2


def test_a_blank_idempotency_key_is_rejected(units_table: Any) -> None:
    denied = handle_unit_operation(
        unit_operation_event(CREATE_UNIT_FIELD, AVERY, input={**BASE_INPUT, "idempotency": {"idempotencyKey": "   "}}),
        None,
    )
    assert_is_error(denied, ErrorCode.INVALID_INPUT)
    assert _rows(units_table) == []


# --- input and authentication shape --------------------------------------------


def test_unauthenticated_caller_is_denied_with_no_write(units_table: Any) -> None:
    denied = handle_unit_operation(unit_operation_event(CREATE_UNIT_FIELD, None, input=_create_input()), None)
    assert_is_error(denied, ErrorCode.UNAUTHORIZED)
    assert _rows(units_table) == []


def test_missing_input_is_invalid(units_table: Any) -> None:
    event = unit_operation_event(CREATE_UNIT_FIELD, AVERY, arguments={})
    assert_is_error(handle_unit_operation(event, None), ErrorCode.INVALID_INPUT)


def test_missing_idempotency_block_is_invalid(units_table: Any) -> None:
    denied = handle_unit_operation(unit_operation_event(CREATE_UNIT_FIELD, AVERY, input=dict(BASE_INPUT)), None)
    assert_is_error(denied, ErrorCode.INVALID_INPUT)
    assert _rows(units_table) == []


def test_invalid_settings_are_rejected_without_writing(units_table: Any) -> None:
    for bad in (
        {"timezone": "Mars/Olympus"},
        {"unitNumber": 0},
        {"city": "   "},
        {"splitDefault": "SPLIT"},
        {"councilNeedBasis": "COUNCIL"},
        {"unitType": "x" * 101},
    ):
        payload = handle_unit_operation(
            unit_operation_event(CREATE_UNIT_FIELD, AVERY, input=_create_input(**bad)), None
        )
        assert_is_error(payload, ErrorCode.INVALID_INPUT)
    assert _rows(units_table) == []


def test_an_unsupported_field_name_is_an_internal_fault(units_table: Any) -> None:
    event = unit_operation_event("deleteUnit", AVERY, input=_create_input())
    assert_is_error(handle_unit_operation(event, None), ErrorCode.INTERNAL_ERROR)


# --- updateUnit (UNIT-M-02) ------------------------------------------------------


def _update(
    units_table: Any, caller: Any, unit_id: str, expected_version: int, *, key: str = "update-1", **fields: Any
) -> Dict[str, Any]:
    payload = {
        "unitId": unit_id,
        "version": {"expectedVersion": expected_version},
        "idempotency": {"idempotencyKey": key},
    }
    payload.update(fields)
    return handle_unit_operation(unit_operation_event(UPDATE_UNIT_FIELD, caller, input=payload), None)


def test_unit_admin_updates_metadata_and_settings(units_table: Any) -> None:
    """UNIT-M-02-01: identity and adminCount are untouched; version advances."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY, CASEY])

    payload = _update(units_table, AVERY, PACK_ID, 1, city="Boulder", splitDefault="TIME_WORKED")

    assert payload["unitId"] == PACK_ID
    assert payload["adminCount"] == 2
    assert payload["version"] == 2
    assert payload["city"] == "Boulder"
    assert payload["metadataKey"] == "pack#3149#boulder#co"
    assert payload["splitDefault"] == "TIME_WORKED"
    assert payload["displayName"] == "Pack 3149 - Aurora, CO"  # stored name is not renamed implicitly
    assert payload["createdAt"] == payload["updatedAt"] or payload["updatedAt"] >= payload["createdAt"]


def test_removed_admin_cannot_update_and_nothing_changes(units_table: Any) -> None:
    """UNIT-M-02-02: revocation takes the update path away immediately."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY, CASEY])
    units_table.delete_item(Key={"pk": f"UNIT#{PACK_ID}", "sk": f"GRANT#{CASEY}"})

    denied = _update(units_table, CASEY, PACK_ID, 1, city="Denver")
    assert_is_error(denied, ErrorCode.NOT_FOUND)
    stored = [row for row in _rows(units_table) if row["sk"] == "METADATA"][0]
    assert stored["version"] == 1 and stored["city"] == "Aurora"
    assert _markers(units_table) == []


def test_a_global_admin_in_another_unit_is_denied(units_table: Any) -> None:
    """Cross-Unit denial on the update path, with no disclosure of the Unit."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_unit(units_table, CREW_ID, admins=[RILEY])

    denied = _update(units_table, RILEY, PACK_ID, 1, city="Denver")
    assert_is_error(denied, ErrorCode.NOT_FOUND)
    assert [row for row in _rows(units_table) if row["sk"] == "METADATA" and row["unitId"] == PACK_ID][0][
        "version"
    ] == 1


def test_stale_expected_version_conflicts(units_table: Any) -> None:
    """VER-01: the loser of a version race gets CONFLICT and zero writes."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY, CASEY])
    _update(units_table, AVERY, PACK_ID, 1, city="Boulder")

    stale = _update(units_table, CASEY, PACK_ID, 1, city="Denver", key="update-2")
    assert_is_error(stale, ErrorCode.CONFLICT)
    stored = [row for row in _rows(units_table) if row["sk"] == "METADATA"][0]
    assert stored["city"] == "Boulder" and stored["version"] == 2
    # Only the winner kept a marker; the loser's transaction is cancelled whole.
    assert [marker["pk"] for marker in _markers(units_table)] == [f"IDEM#{AVERY}#updateUnit#{PACK_ID}"]


def test_metadata_change_reruns_the_duplicate_gate(units_table: Any) -> None:
    """A geography change into an existing fingerprint needs confirmation again."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _seed_unit(units_table, BOULDER_ID, admins=[CASEY], city="Boulder")

    denied = _update(units_table, AVERY, PACK_ID, 1, city="Boulder", key="update-a")
    assert_is_error(denied, ErrorCode.INVALID_INPUT)
    assert [row for row in _rows(units_table) if row["unitId"] == PACK_ID and row["sk"] == "METADATA"][0][
        "city"
    ] == "Aurora"

    confirmed = _update(units_table, AVERY, PACK_ID, 1, city="Boulder", duplicateConfirmed=True, key="update-b")
    assert confirmed["metadataKey"] == "pack#3149#boulder#co"


def test_update_retry_replays_and_bumps_the_version_once(units_table: Any) -> None:
    """An idempotent retry may not re-apply the version increment."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])

    first = _update(units_table, AVERY, PACK_ID, 1, city="Boulder")
    retry = _update(units_table, AVERY, PACK_ID, 1, city="Boulder")

    assert retry == first
    stored = [row for row in _rows(units_table) if row["sk"] == "METADATA"][0]
    assert stored["version"] == 2
    assert len(_markers(units_table)) == 1


def test_update_retry_with_changed_content_is_rejected(units_table: Any) -> None:
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    _update(units_table, AVERY, PACK_ID, 1, city="Boulder")

    changed = _update(units_table, AVERY, PACK_ID, 1, city="Denver")
    assert_is_error(changed, ErrorCode.INVALID_INPUT)
    stored = [row for row in _rows(units_table) if row["sk"] == "METADATA"][0]
    assert stored["city"] == "Boulder" and stored["version"] == 2


def test_update_input_guards_are_typed(units_table: Any) -> None:
    """Missing unitId, unknown Unit, no writable field, and a bad version shape."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])

    cases = [
        (
            {"version": {"expectedVersion": 1}, "idempotency": {"idempotencyKey": "u"}, "city": "Boulder"},
            ErrorCode.INVALID_INPUT,
        ),
        (
            {
                "unitId": "unit-nope",
                "version": {"expectedVersion": 1},
                "idempotency": {"idempotencyKey": "u"},
                "city": "Boulder",
            },
            ErrorCode.NOT_FOUND,
        ),
        (
            {
                "unitId": PACK_ID,
                "version": {"expectedVersion": 1},
                "idempotency": {"idempotencyKey": "u"},
                "adminCount": 9,
            },
            ErrorCode.INVALID_INPUT,
        ),
        ({"unitId": PACK_ID, "idempotency": {"idempotencyKey": "u"}, "city": "Boulder"}, ErrorCode.INVALID_INPUT),
        (
            {
                "unitId": PACK_ID,
                "version": {"expectedVersion": "abc"},
                "idempotency": {"idempotencyKey": "u"},
                "city": "Boulder",
            },
            ErrorCode.INVALID_INPUT,
        ),
        ({"unitId": PACK_ID, "version": {"expectedVersion": 1}, "city": "Boulder"}, ErrorCode.INVALID_INPUT),
    ]
    for payload, code in cases:
        assert_is_error(
            handle_unit_operation(unit_operation_event(UPDATE_UNIT_FIELD, AVERY, input=payload), None), code
        )
    stored = [row for row in _rows(units_table) if row["sk"] == "METADATA"][0]
    assert stored["version"] == 1 and stored["city"] == "Aurora" and stored["adminCount"] == 1


def test_invalid_settings_on_update_leave_the_unit_untouched(units_table: Any) -> None:
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    denied = _update(units_table, AVERY, PACK_ID, 1, timezone="Mars/Olympus")
    assert_is_error(denied, ErrorCode.INVALID_INPUT)
    stored = [row for row in _rows(units_table) if row["sk"] == "METADATA"][0]
    assert stored["timezone"] == "America/Denver" and stored["version"] == 1


# --- revokeUnitAccessGrant (UNIT-M-06) -------------------------------------------


def _revoke(
    units_table: Any, caller: Any, unit_id: str, target: str, expected_version: int, key: str = "revoke-1"
) -> Dict[str, Any]:
    payload = {
        "unitId": unit_id,
        "accountId": target,
        "version": {"expectedVersion": expected_version},
        "idempotency": {"idempotencyKey": key},
    }
    return handle_unit_operation(unit_operation_event(REVOKE_GRANT_FIELD, caller, input=payload), None)


def test_revoking_a_grant_deletes_it_and_decrements_the_count(units_table: Any) -> None:
    """UNIT-M-06-01: one grant removed, adminCount authoritative, access lost now."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY, CASEY])

    payload = _revoke(units_table, AVERY, PACK_ID, CASEY, 1)

    assert payload["adminCount"] == 1
    assert payload["version"] == 2
    rows = _rows(units_table)
    assert (f"UNIT#{PACK_ID}", f"GRANT#{CASEY}") not in {(row["pk"], row["sk"]) for row in rows}
    assert (f"UNIT#{PACK_ID}", f"GRANT#{AVERY}") in {(row["pk"], row["sk"]) for row in rows}

    follow_up = _update(units_table, CASEY, PACK_ID, 2, city="Denver")
    assert_is_error(follow_up, ErrorCode.NOT_FOUND)


def test_revoking_the_final_grant_conflicts(units_table: Any) -> None:
    """UNIT-M-06-02: the sole admin cannot remove the last grant through the API."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])

    denied = _revoke(units_table, AVERY, PACK_ID, AVERY, 1)
    assert_is_error(denied, ErrorCode.CONFLICT)
    rows = _rows(units_table)
    assert (f"UNIT#{PACK_ID}", f"GRANT#{AVERY}") in {(row["pk"], row["sk"]) for row in rows}
    assert [row for row in rows if row["sk"] == "METADATA"][0]["adminCount"] == 1
    assert _markers(units_table) == []


def test_a_stale_revoke_loses_the_race_with_no_partial_write(units_table: Any) -> None:
    """Add/revoke racing: the loser's transaction is cancelled whole."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY, CASEY, MORGAN])

    first = _revoke(units_table, AVERY, PACK_ID, CASEY, 1, key="revoke-a")
    loser = _revoke(units_table, AVERY, PACK_ID, MORGAN, 1, key="revoke-b")

    assert_is_error(loser, ErrorCode.CONFLICT)
    assert first["adminCount"] == 2
    rows = {(row["pk"], row["sk"]) for row in _rows(units_table)}
    assert (f"UNIT#{PACK_ID}", f"GRANT#{MORGAN}") in rows
    assert (f"UNIT#{PACK_ID}", f"GRANT#{CASEY}") not in rows
    assert [row for row in _rows(units_table) if row["sk"] == "METADATA"][0]["adminCount"] == 2
    assert len(_markers(units_table)) == 1


def test_revoke_replay_returns_the_original_result_once(units_table: Any) -> None:
    """An identical retry cannot decrement adminCount twice."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY, CASEY])

    first = _revoke(units_table, AVERY, PACK_ID, CASEY, 1)
    retry = _revoke(units_table, AVERY, PACK_ID, CASEY, 1)

    assert retry == first
    stored = [row for row in _rows(units_table) if row["sk"] == "METADATA"][0]
    assert stored["adminCount"] == 1 and stored["version"] == 2


def test_revoke_denials_leave_everything_in_place(units_table: Any) -> None:
    """Unknown grant, non-admin caller, and a malformed version shape."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY, CASEY])
    _seed_unit(units_table, CREW_ID, admins=[RILEY])

    assert_is_error(_revoke(units_table, AVERY, PACK_ID, MORGAN, 1, key="r1"), ErrorCode.NOT_FOUND)
    assert_is_error(_revoke(units_table, RILEY, PACK_ID, CASEY, 1, key="r2"), ErrorCode.NOT_FOUND)
    bad_version = handle_unit_operation(
        unit_operation_event(
            REVOKE_GRANT_FIELD,
            AVERY,
            input={"unitId": PACK_ID, "accountId": CASEY, "idempotency": {"idempotencyKey": "r3"}},
        ),
        None,
    )
    assert_is_error(bad_version, ErrorCode.INVALID_INPUT)
    missing_ids = handle_unit_operation(
        unit_operation_event(
            REVOKE_GRANT_FIELD,
            AVERY,
            input={"accountId": CASEY, "version": {"expectedVersion": 1}, "idempotency": {"idempotencyKey": "r4"}},
        ),
        None,
    )
    assert_is_error(missing_ids, ErrorCode.INVALID_INPUT)

    rows = _rows(units_table)
    assert [row for row in rows if row["sk"] == "METADATA" and row["unitId"] == PACK_ID][0]["adminCount"] == 2
    assert len([row for row in rows if str(row["sk"]).startswith("GRANT#") and row["pk"] == f"UNIT#{PACK_ID}"]) == 2
    assert _markers(units_table) == []


def test_settings_only_update_skips_the_geography_work(units_table: Any) -> None:
    """A settings change recomputes nothing geography-shaped."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])

    payload = _update(
        units_table,
        AVERY,
        PACK_ID,
        1,
        splitDefault="TIME_WORKED",
        councilNeedBasis="AFTER_ASSIGNMENTS",
        key="u-settings",
    )

    assert payload["splitDefault"] == "TIME_WORKED"
    assert payload["councilNeedBasis"] == "AFTER_ASSIGNMENTS"
    assert payload["metadataKey"] == "pack#3149#aurora#co"
    stored = [row for row in _rows(units_table) if row["sk"] == "METADATA"][0]
    assert stored["metadataKey"] == "pack#3149#aurora#co" and stored["version"] == 2


def test_a_non_integer_expected_version_is_rejected(units_table: Any) -> None:
    """A version guard that is not a number cannot be guessed into one.

    The tolerant spelling matches ``appsync_types.require_int``: a value that
    converts cleanly to an integer is the guard the caller meant; a boolean, a
    float, or a non-numeric string is not.
    """
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    for bad in (True, "abc", 1.5, None, {"nested": 1}):
        payload = handle_unit_operation(
            unit_operation_event(
                UPDATE_UNIT_FIELD,
                AVERY,
                input={
                    "unitId": PACK_ID,
                    "version": {"expectedVersion": bad},
                    "idempotency": {"idempotencyKey": "v"},
                    "city": "Boulder",
                },
            ),
            None,
        )
        assert_is_error(payload, ErrorCode.INVALID_INPUT)
    stored = [row for row in _rows(units_table) if row["sk"] == "METADATA"][0]
    assert stored["version"] == 1 and stored["city"] == "Aurora"


def test_a_replay_that_cannot_be_answered_is_an_internal_fault(units_table: Any, monkeypatch: Any) -> None:
    """A committed marker whose rows vanished must not be answered by re-writing."""
    from src.utils import unit_auth, unit_models

    created = _create(units_table, AVERY)
    original_read_unit = unit_models.read_unit

    monkeypatch.setattr(unit_models, "read_unit", lambda unit_id: None)
    assert_is_error(_create(units_table, AVERY), ErrorCode.INTERNAL_ERROR)

    monkeypatch.setattr(unit_models, "read_unit", original_read_unit)
    monkeypatch.setattr(unit_auth, "read_grant", lambda unit_id, account_id: None)
    assert_is_error(_create(units_table, AVERY), ErrorCode.INTERNAL_ERROR)

    # Neither broken replay wrote a second Unit or grant.
    rows = _rows(units_table)
    assert len([row for row in rows if row["sk"] == "METADATA"]) == 1
    assert created["unit"]["unitId"]


def test_a_replayed_update_that_lost_its_unit_is_an_internal_fault(units_table: Any, monkeypatch: Any) -> None:
    """The same rule on the update path: no fresh write behind a broken replay."""
    _seed_unit(units_table, PACK_ID, admins=[AVERY])
    updated = _update(units_table, AVERY, PACK_ID, 1, city="Boulder", key="u-lost")
    assert updated["version"] == 2

    units_table.delete_item(Key={"pk": f"UNIT#{PACK_ID}", "sk": "METADATA"})
    replay = _update(units_table, AVERY, PACK_ID, 1, city="Boulder", key="u-lost")
    assert_is_error(replay, ErrorCode.INTERNAL_ERROR)
