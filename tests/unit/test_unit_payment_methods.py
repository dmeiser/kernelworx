"""Leaf 4.1.1 — Unit payment-method persistence and resolvers.

The tests the leaf names — duplicate/reserved-name, 50/51, stale-version,
``AUTH-U``, and snapshot coverage — driven through the handler entrypoint with
the Stage 1 fixture event builder:

- ``PAY-M-01-02`` — Cash/Check/Other and their case variants are refused without
  creating a method; a duplicate normalized name is refused, and the conditional
  Put (not the read before it) settles the race.
- ``PAY-M-01-03`` — the 51st active custom method is refused; deactivating one
  frees exactly one slot, never more than 50 active.
- ``PAY-M-02-*`` — rename moves the key while ``paymentMethodId``, creation
  audit, active state, and QR reference stay stable; a stale ``expectedVersion``
  writes nothing; built-in ids cannot be renamed.
- ``PAY-M-03-*`` — deactivation is a soft flip preserving everything else;
  ``includeInactive`` separates the new-sale list from the history list.
- ``AUTH-U`` — a revoked admin, a non-admin, and a cross-Unit id are all
  answered ``NOT_FOUND`` with no writes; a session-less caller is ``UNAUTHORIZED``.
- ``VER-01``/``IDEM`` — stale versions ``CONFLICT``, an identical retry replays
  the original result with no second effect, and a same-key different-content
  retry is refused.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.handlers.unit_operations import (
    CREATE_PAYMENT_METHOD_FIELD,
    DEACTIVATE_PAYMENT_METHOD_FIELD,
    UNIT_PAYMENT_METHODS_FIELD,
    UPDATE_PAYMENT_METHOD_FIELD,
    handle_unit_operation,
)
from src.utils.errors import AppError, ErrorCode
from src.utils.unit_payment_models import MAX_ACTIVE_PAYMENT_METHODS, build_payment_item
from tests.unit.show_sell_fixtures import (
    account_id,
    assert_is_error,
    grant_item,
    unit_item,
    unit_operation_event,
)

AVERY = account_id("Avery")
DEVON = account_id("Devon")
RILEY = account_id("Riley")

PACK_ID = "unit-pack-3149-aurora"
TROOP_ID = "unit-troop-7150-boulder"

PACK_PK = f"UNIT#{PACK_ID}"
TROOP_PK = f"UNIT#{TROOP_ID}"

QR_KEY = "payment-qr-codes/unit/legacy.png"


def _seed(units_table: Any, unit_id: str, admins: List[str], *, label: str = "Pack", number: int = 3149) -> None:
    """Write a Unit plus one grant per listed admin."""
    units_table.put_item(
        Item=unit_item(unit_id, label, number, "Aurora", "CO", created_by=AVERY, admin_count=len(admins))
    )
    for admin in admins:
        units_table.put_item(Item=grant_item(unit_id, admin, created_by=AVERY))


def _payment_rows(units_table: Any, pk: str = PACK_PK) -> List[Dict[str, Any]]:
    """This Unit's stored payment rows, in key order."""
    return [row for row in units_table.scan()["Items"] if row["pk"] == pk and str(row["sk"]).startswith("PAYMENT#")]


def _markers(units_table: Any) -> List[Dict[str, Any]]:
    """Idempotency markers written on the Units table."""
    return [row for row in units_table.scan()["Items"] if str(row["pk"]).startswith("IDEM#")]


def _create(units_table: Any, caller: Any, *, unit_id: str = PACK_ID, key: str = "create-1", **input: Any) -> Any:
    payload = {"unitId": unit_id, **input, "idempotency": {"idempotencyKey": key}}
    return handle_unit_operation(unit_operation_event(CREATE_PAYMENT_METHOD_FIELD, caller, input=payload), None)


def _rename(
    units_table: Any,
    caller: Any,
    *,
    unit_id: str = PACK_ID,
    key: str = "rename-1",
    version: int = 1,
    **input: Any,
) -> Any:
    payload = {
        "unitId": unit_id,
        **input,
        "version": {"expectedVersion": version},
        "idempotency": {"idempotencyKey": key},
    }
    return handle_unit_operation(unit_operation_event(UPDATE_PAYMENT_METHOD_FIELD, caller, input=payload), None)


def _deactivate(
    units_table: Any,
    caller: Any,
    *,
    unit_id: str = PACK_ID,
    key: str = "deactivate-1",
    version: int = 1,
    **input: Any,
) -> Any:
    payload = {
        "unitId": unit_id,
        **input,
        "version": {"expectedVersion": version},
        "idempotency": {"idempotencyKey": key},
    }
    return handle_unit_operation(unit_operation_event(DEACTIVATE_PAYMENT_METHOD_FIELD, caller, input=payload), None)


def _list(units_table: Any, caller: Any, *, unit_id: str = PACK_ID, include_inactive: Any = None) -> Any:
    arguments: Dict[str, Any] = {"unitId": unit_id}
    if include_inactive is not None:
        arguments["includeInactive"] = include_inactive
    return handle_unit_operation(unit_operation_event(UNIT_PAYMENT_METHODS_FIELD, caller, arguments=arguments), None)


def _seed_wise_with_qr(units_table: Any) -> Dict[str, Any]:
    """A custom method that already carries a QR reference, for rename/deactivate."""
    _seed(units_table, PACK_ID, [AVERY])
    created = _create(units_table, AVERY, displayName="Wise")
    units_table.update_item(
        Key={"pk": PACK_PK, "sk": "PAYMENT#wise"},
        UpdateExpression="SET #qr = :qr",
        ExpressionAttributeNames={"#qr": "qrCodeS3Key"},
        ExpressionAttributeValues={":qr": QR_KEY},
    )
    return created


# --- unitPaymentMethods read -----------------------------------------------------


def test_read_answers_builtins_then_this_units_customs(units_table: Any) -> None:
    """The list is the three computed built-ins first, then customs by name."""
    _seed(units_table, PACK_ID, [AVERY])
    _create(units_table, AVERY, key="create-2", displayName="apple pay")
    _create(units_table, AVERY, key="create-3", displayName="Wise")

    methods = _list(units_table, AVERY)
    builtins, customs = methods[:3], methods[3:]
    assert [method["paymentMethodId"] for method in builtins] == ["CASH", "CHECK", "OTHER"]
    assert [method["displayName"] for method in builtins] == ["Cash", "Check", "Other"]
    for method in builtins:
        assert method["isActive"] is True
        assert method["version"] == 0
        assert method["qrCodeS3Key"] is None
        assert method["unitId"] == PACK_ID
        assert method["createdAt"] is None

    assert [method["displayName"] for method in customs] == ["apple pay", "Wise"]
    assert all(method["version"] == 1 and method["isActive"] is True for method in customs)
    assert all("pk" not in method and "sk" not in method for method in methods)
    assert all("paymentMethodId" in method and "updatedByAccountId" in method for method in customs)


def test_read_hides_inactive_without_include_inactive(units_table: Any) -> None:
    """PAY-M-03-01 — the new-sale list hides it, the history list names it."""
    _seed(units_table, PACK_ID, [AVERY])
    created = _create(units_table, AVERY, displayName="Wise")
    _deactivate(units_table, AVERY, paymentMethodId=created["paymentMethodId"], version=1)

    assert "Wise" not in [method["displayName"] for method in _list(units_table, AVERY)]
    history = _list(units_table, AVERY, include_inactive=True)
    wise = [method for method in history if method["displayName"] == "Wise"]
    assert len(wise) == 1
    assert wise[0]["paymentMethodId"] == created["paymentMethodId"]
    assert wise[0]["isActive"] is False
    assert wise[0]["version"] == 2


def test_read_requires_a_unit_admin(units_table: Any) -> None:
    """AUTH-U-01 — a non-admin's read is NOT_FOUND, a session-less caller is not."""
    _seed(units_table, PACK_ID, [AVERY])
    _create(units_table, AVERY, displayName="Wise")

    assert _payment_rows(units_table)
    denied = assert_is_error(_list(units_table, RILEY), ErrorCode.NOT_FOUND)
    assert denied["message"] == "Unit not found"
    assert_is_error(_list(units_table, None), ErrorCode.UNAUTHORIZED)


# --- createUnitPaymentMethod (PAY-M-01) ------------------------------------------


def test_create_writes_one_payment_row_shared_by_the_units_admins(units_table: Any) -> None:
    """PAY-M-01-01 — a second admin creates it and every admin reads it."""
    _seed(units_table, PACK_ID, [AVERY, DEVON])
    created = _create(units_table, DEVON, displayName="  Wise  ")

    assert created["displayName"] == "Wise"
    assert created["isActive"] is True
    assert created["version"] == 1
    assert created["unitId"] == PACK_ID
    assert created["paymentMethodId"]
    assert created["createdByAccountId"] == DEVON
    assert created["updatedByAccountId"] == DEVON
    assert created["createdAt"] == created["updatedAt"]
    assert created["qrCodeS3Key"] is None

    rows = _payment_rows(units_table)
    assert len(rows) == 1
    assert (rows[0]["pk"], rows[0]["sk"]) == (PACK_PK, "PAYMENT#wise")
    assert rows[0]["paymentMethodId"] == created["paymentMethodId"]
    assert len(_markers(units_table)) == 1
    assert "Wise" in [method["displayName"] for method in _list(units_table, AVERY)]


def test_create_refuses_reserved_names_without_writing(units_table: Any) -> None:
    """PAY-M-01-02 — the built-in names in any casing or padding are refused."""
    _seed(units_table, PACK_ID, [AVERY])
    for index, name in enumerate(("Cash", "CASH", "cHeCk", " Other ", "other")):
        assert_is_error(
            _create(units_table, AVERY, key=f"create-reserved-{index}", displayName=name),
            ErrorCode.INVALID_INPUT,
        )
    assert _payment_rows(units_table) == []


def test_create_refuses_a_duplicate_normalized_name(units_table: Any) -> None:
    """PAY-M-01-02 — casing and padding variants collide on the normalized name."""
    _seed(units_table, PACK_ID, [AVERY])
    _create(units_table, AVERY, displayName="Wise")
    denied = assert_is_error(_create(units_table, AVERY, key="create-2", displayName=" WISE "), ErrorCode.CONFLICT)
    assert "already has a payment method" in denied["message"]
    assert len(_payment_rows(units_table)) == 1


def test_create_refuses_the_51st_active_method(units_table: Any) -> None:
    """PAY-M-01-03 — 50 active customs are accepted, the 51st is refused."""
    _seed(units_table, PACK_ID, [AVERY])
    for index in range(MAX_ACTIVE_PAYMENT_METHODS):
        assert _create(units_table, AVERY, key=f"create-{index}", displayName=f"Method {index}")["isActive"] is True
    assert len(_payment_rows(units_table)) == MAX_ACTIVE_PAYMENT_METHODS

    denied = assert_is_error(
        _create(units_table, AVERY, key="create-overflow", displayName="Method 50"), ErrorCode.CONFLICT
    )
    assert "active payment methods" in denied["message"]
    assert len(_payment_rows(units_table)) == MAX_ACTIVE_PAYMENT_METHODS


def test_deactivation_frees_exactly_one_active_slot(units_table: Any) -> None:
    """PAY-M-01-03 — one deactivation accepts one new method, never more than 50."""
    _seed(units_table, PACK_ID, [AVERY])
    created = [
        _create(units_table, AVERY, key=f"create-{index}", displayName=f"Method {index}")
        for index in range(MAX_ACTIVE_PAYMENT_METHODS)
    ]
    _deactivate(units_table, AVERY, paymentMethodId=created[0]["paymentMethodId"], version=1)

    accepted = _create(units_table, AVERY, key="create-replacement", displayName="Method 50")
    assert accepted["isActive"] is True
    assert len(_payment_rows(units_table)) == MAX_ACTIVE_PAYMENT_METHODS + 1
    active_customs = [method for method in _list(units_table, AVERY) if method["version"] > 0]
    assert len(active_customs) == MAX_ACTIVE_PAYMENT_METHODS
    assert_is_error(_create(units_table, AVERY, key="create-again", displayName="Method 51"), ErrorCode.CONFLICT)


def test_create_requires_a_display_name_shape(units_table: Any) -> None:
    """API contract §3.4 — 1-100 trimmed characters, so blank and oversize fail."""
    _seed(units_table, PACK_ID, [AVERY])
    assert_is_error(_create(units_table, AVERY, displayName="   "), ErrorCode.INVALID_INPUT)
    assert_is_error(_create(units_table, AVERY, key="create-2", displayName="x" * 101), ErrorCode.INVALID_INPUT)
    assert _payment_rows(units_table) == []


def test_create_requires_a_unit_admin(units_table: Any) -> None:
    """AUTH-U-03/04 — a non-admin cannot create, and an unknown Unit is NOT_FOUND."""
    _seed(units_table, TROOP_ID, [DEVON], label="Troop", number=7150)
    assert_is_error(_create(units_table, RILEY, displayName="Wise"), ErrorCode.NOT_FOUND)
    assert_is_error(_create(units_table, None, displayName="Wise"), ErrorCode.UNAUTHORIZED)
    assert _payment_rows(units_table) == []


def test_mutations_on_an_unknown_unit_are_not_found(units_table: Any) -> None:
    """AUTH-U-01 — naming a Unit that does not exist refuses before domain logic."""
    assert_is_error(_create(units_table, AVERY, unit_id="unit-none", displayName="Wise"), ErrorCode.NOT_FOUND)
    assert_is_error(
        _rename(units_table, AVERY, unit_id="unit-none", paymentMethodId="x", displayName="y"), ErrorCode.NOT_FOUND
    )
    assert_is_error(_deactivate(units_table, AVERY, unit_id="unit-none", paymentMethodId="x"), ErrorCode.NOT_FOUND)
    assert units_table.scan()["Items"] == []


# --- updateUnitPaymentMethod (PAY-M-02) -------------------------------------------


def test_rename_moves_the_key_and_keeps_the_method_stable(units_table: Any) -> None:
    """PAY-M-02-01 — id, creation audit, active state, and QR survive the move."""
    created = _seed_wise_with_qr(units_table)
    renamed = _rename(units_table, AVERY, paymentMethodId=created["paymentMethodId"], displayName="Wise Mobile")

    assert renamed["paymentMethodId"] == created["paymentMethodId"]
    assert renamed["displayName"] == "Wise Mobile"
    assert renamed["version"] == 2
    assert renamed["createdAt"] == created["createdAt"]
    assert renamed["createdByAccountId"] == AVERY
    assert renamed["updatedByAccountId"] == AVERY
    assert renamed["isActive"] is True
    assert renamed["qrCodeS3Key"] == QR_KEY

    rows = _payment_rows(units_table)
    assert [(row["pk"], row["sk"]) for row in rows] == [(PACK_PK, "PAYMENT#wise mobile")]
    assert rows[0]["createdAt"] == created["createdAt"]
    assert rows[0]["createdAt"] != rows[0]["updatedAt"]
    assert rows[0]["paymentMethodId"] == created["paymentMethodId"]


def test_rename_within_one_normalized_name_updates_in_place(units_table: Any) -> None:
    """A casing-only rename keeps the key where it is: one conditional Update."""
    _seed(units_table, PACK_ID, [AVERY])
    created = _create(units_table, AVERY, displayName="Wise")
    renamed = _rename(units_table, AVERY, paymentMethodId=created["paymentMethodId"], displayName="WISE")

    assert renamed["displayName"] == "WISE"
    assert renamed["version"] == 2
    assert renamed["paymentMethodId"] == created["paymentMethodId"]
    assert [(row["pk"], row["sk"]) for row in _payment_rows(units_table)] == [(PACK_PK, "PAYMENT#wise")]


def test_rename_with_a_stale_version_conflicts_and_writes_nothing(units_table: Any) -> None:
    """VER-01 on rename — the version guard rides the Delete of the old key."""
    created = _seed_wise_with_qr(units_table)
    denied = assert_is_error(
        _rename(
            units_table,
            AVERY,
            version=99,
            paymentMethodId=created["paymentMethodId"],
            displayName="Wise Mobile",
        ),
        ErrorCode.CONFLICT,
    )
    assert "changed underneath" in denied["message"]
    rows = _payment_rows(units_table)
    assert [(row["pk"], row["sk"]) for row in rows] == [(PACK_PK, "PAYMENT#wise")]
    assert rows[0]["version"] == 1


def test_rename_honours_the_reserved_and_duplicate_rules(units_table: Any) -> None:
    """PAY-M-02-02 — the create rules apply to a rename as well."""
    _seed(units_table, PACK_ID, [AVERY])
    first = _create(units_table, AVERY, displayName="Wise")
    _create(units_table, AVERY, key="create-2", displayName="Pay wave")

    assert_is_error(
        _rename(units_table, AVERY, paymentMethodId=first["paymentMethodId"], displayName="Check"),
        ErrorCode.INVALID_INPUT,
    )
    assert_is_error(
        _rename(units_table, AVERY, key="rename-2", paymentMethodId=first["paymentMethodId"], displayName=" pay wave "),
        ErrorCode.CONFLICT,
    )
    assert {row["sk"] for row in _payment_rows(units_table)} == {"PAYMENT#wise", "PAYMENT#pay wave"}


def test_rename_refuses_builtin_unknown_and_foreign_ids(units_table: Any) -> None:
    """Built-ins are computed and not mutable; unknown/cross-Unit ids are NOT_FOUND."""
    _seed(units_table, PACK_ID, [AVERY])
    _seed(units_table, TROOP_ID, [AVERY], label="Troop", number=7150)
    troop_method = _create(units_table, AVERY, unit_id=TROOP_ID, displayName="Wise")

    assert_is_error(
        _rename(units_table, AVERY, paymentMethodId="CASH", displayName="Cash Mobile"), ErrorCode.INVALID_INPUT
    )
    assert_is_error(
        _rename(units_table, AVERY, key="rename-2", paymentMethodId="no-such-method", displayName="Nope"),
        ErrorCode.NOT_FOUND,
    )
    assert_is_error(
        _rename(
            units_table,
            AVERY,
            key="rename-3",
            paymentMethodId=troop_method["paymentMethodId"],
            displayName="Stolen",
        ),
        ErrorCode.NOT_FOUND,
    )
    assert [(row["pk"], row["sk"]) for row in _payment_rows(units_table, TROOP_PK)] == [(TROOP_PK, "PAYMENT#wise")]
    assert _payment_rows(units_table) == []


# --- deactivateUnitPaymentMethod (PAY-M-03) ---------------------------------------


def test_deactivation_is_a_soft_flip_preserving_everything_else(units_table: Any) -> None:
    """PAY-M-03-01 — the row, id, QR reference, and audit all stay readable."""
    created = _seed_wise_with_qr(units_table)
    deactivated = _deactivate(units_table, AVERY, paymentMethodId=created["paymentMethodId"], version=1)

    assert deactivated["isActive"] is False
    assert deactivated["version"] == 2
    assert deactivated["paymentMethodId"] == created["paymentMethodId"]
    assert deactivated["displayName"] == "Wise"
    assert deactivated["qrCodeS3Key"] == QR_KEY
    assert deactivated["createdAt"] == created["createdAt"]
    assert deactivated["createdByAccountId"] == AVERY
    assert deactivated["updatedByAccountId"] == AVERY

    rows = _payment_rows(units_table)
    assert [(row["pk"], row["sk"]) for row in rows] == [(PACK_PK, "PAYMENT#wise")]


def test_deactivation_with_a_stale_version_or_bad_id_refuses(units_table: Any) -> None:
    """VER-01 plus the built-in and unknown-id refusals on deactivation."""
    created = _seed_wise_with_qr(units_table)
    assert_is_error(
        _deactivate(units_table, AVERY, version=7, paymentMethodId=created["paymentMethodId"]), ErrorCode.CONFLICT
    )
    assert _payment_rows(units_table)[0]["isActive"] is True
    assert_is_error(_deactivate(units_table, AVERY, key="deactivate-2", paymentMethodId="CASH"), ErrorCode.INVALID_INPUT)
    assert_is_error(_deactivate(units_table, AVERY, key="deactivate-3", paymentMethodId="nope"), ErrorCode.NOT_FOUND)


def test_an_identical_deactivation_retry_replays_the_original_result(units_table: Any) -> None:
    """IDEM on deactivate — the retry answers the first result, version stays 2."""
    created = _seed_wise_with_qr(units_table)
    payment_method_id = created["paymentMethodId"]
    first = _deactivate(units_table, AVERY, paymentMethodId=payment_method_id, version=1)
    retry = _deactivate(units_table, AVERY, paymentMethodId=payment_method_id, version=1)

    assert retry == first
    assert retry["isActive"] is False
    assert retry["version"] == 2
    row = _payment_rows(units_table)[0]
    assert (row["version"], row["isActive"]) == (2, False)
    # One marker for the create, one for the deactivate: the retry added none.
    assert len(_markers(units_table)) == 2


def test_deactivation_requires_a_unit_admin(units_table: Any) -> None:
    """AUTH-U-02 — a caller with no grant cannot deactivate."""
    _seed(units_table, PACK_ID, [AVERY])
    created = _create(units_table, AVERY, displayName="Wise")
    assert_is_error(_deactivate(units_table, RILEY, paymentMethodId=created["paymentMethodId"]), ErrorCode.NOT_FOUND)
    assert _payment_rows(units_table)[0]["isActive"] is True


# --- IDEM and AUTH-U across the mutations -----------------------------------------


def test_an_identical_retry_replays_the_original_result(units_table: Any) -> None:
    """IDEM — the retry answers the created method with one row and one marker."""
    _seed(units_table, PACK_ID, [AVERY])
    first = _create(units_table, AVERY, displayName="Wise")
    retry = _create(units_table, AVERY, displayName="Wise")

    assert retry == first
    assert len(_payment_rows(units_table)) == 1
    assert len(_markers(units_table)) == 1


def test_a_replayed_rename_answers_the_snapshot_it_produced(units_table: Any) -> None:
    """The replayed rename answers the first attempt's snapshot, not the row.

    The method is renamed twice, so the row has moved past the first rename's
    version; replaying the first rename must answer that first snapshot rather
    than the current row or a CONFLICT against the version it no longer holds.
    """
    _seed(units_table, PACK_ID, [AVERY])
    created = _create(units_table, AVERY, displayName="Wise")
    assert created["paymentMethodId"]
    payment_method_id = created["paymentMethodId"]
    first = _rename(units_table, AVERY, key="rename-a", paymentMethodId=payment_method_id, displayName="Wise Mobile")
    _rename(units_table, AVERY, key="rename-b", version=2, paymentMethodId=payment_method_id, displayName="Wise Pay")

    replay = _rename(units_table, AVERY, key="rename-a", paymentMethodId=payment_method_id, displayName="Wise Mobile")
    assert replay == first
    assert replay["displayName"] == "Wise Mobile"
    assert replay["version"] == 2
    assert [(row["pk"], row["sk"]) for row in _payment_rows(units_table)] == [(PACK_PK, "PAYMENT#wise pay")]


def test_a_reused_key_with_different_content_is_refused(units_table: Any) -> None:
    """IDEM — one key carries one request: a second name never writes or replays."""
    _seed(units_table, PACK_ID, [AVERY])
    _create(units_table, AVERY, displayName="Wise")
    assert_is_error(_create(units_table, AVERY, displayName="Pay wave"), ErrorCode.INVALID_INPUT)
    assert len(_payment_rows(units_table)) == 1


def test_a_revoked_admin_and_a_cross_unit_id_are_denied_without_writes(units_table: Any) -> None:
    """AUTH-U-02/03/05 — a revoked grant and another Unit's method are both refused."""
    _seed(units_table, PACK_ID, [AVERY, DEVON])
    _seed(units_table, TROOP_ID, [DEVON], label="Troop", number=7150)
    created = _create(units_table, DEVON, unit_id=TROOP_ID, displayName="Wise")

    units_table.delete_item(Key={"pk": PACK_PK, "sk": f"GRANT#{DEVON}"})
    assert_is_error(_list(units_table, DEVON), ErrorCode.NOT_FOUND)
    assert_is_error(_create(units_table, DEVON, key="create-x", displayName="Pay wave"), ErrorCode.NOT_FOUND)
    assert_is_error(
        _rename(units_table, DEVON, key="rename-x", paymentMethodId="anything", displayName="Nope"), ErrorCode.NOT_FOUND
    )
    assert_is_error(_deactivate(units_table, DEVON, key="deactivate-x", paymentMethodId="anything"), ErrorCode.NOT_FOUND)

    assert_is_error(
        _rename(
            units_table, AVERY, key="rename-cross", paymentMethodId=created["paymentMethodId"], displayName="Stolen"
        ),
        ErrorCode.NOT_FOUND,
    )
    assert [(row["pk"], row["sk"]) for row in _payment_rows(units_table, TROOP_PK)] == [(TROOP_PK, "PAYMENT#wise")]
    assert _payment_rows(units_table) == []


# --- the stored-row builder this suite seeds --------------------------------------


def test_build_payment_item_carries_the_stored_contract() -> None:
    """The seed path's shape is the module's own builder's shape.

    Guards the seeding the QR leaf (4.1.2) reuses: the builder keeps a QR
    reference, numbers an initial revision as version 1, and refuses a version
    below 1 rather than writing an unreachable revision.
    """
    item = build_payment_item(
        payment_method_id="pm-3149-card",
        unit_id=PACK_ID,
        display_name=" Card ",
        created_by_account_id=AVERY,
        now_iso="2026-11-21T00:00:00+00:00",
        qr_code_s3_key=QR_KEY,
    )
    assert (item["pk"], item["sk"]) == (PACK_PK, "PAYMENT#card")
    assert item["paymentMethodId"] == "pm-3149-card"
    assert item["displayName"] == "Card"
    assert item["normalizedName"] == "card"
    assert item["isActive"] is True
    assert item["version"] == 1
    assert item["qrCodeS3Key"] == QR_KEY
    assert item["createdAt"] == item["updatedAt"] == "2026-11-21T00:00:00+00:00"

    with pytest.raises(AppError, match="version must be at least 1"):
        build_payment_item(
            payment_method_id="pm-3149-bad",
            unit_id=PACK_ID,
            display_name="Card",
            created_by_account_id=AVERY,
            now_iso="2026-11-21T00:00:00+00:00",
            version=0,
        )
