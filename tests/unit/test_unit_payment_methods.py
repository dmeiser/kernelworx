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
- the write window — the 50-active ceiling is settled by the counter's condition
  and a reusable name key by its ``paymentMethodId``, both inside the
  transaction, and a twin that commits first is replayed rather than re-applied.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

import pytest

from src.handlers.unit_operations import (
    CREATE_PAYMENT_METHOD_FIELD,
    DEACTIVATE_PAYMENT_METHOD_FIELD,
    UNIT_PAYMENT_METHODS_FIELD,
    UPDATE_PAYMENT_METHOD_FIELD,
    handle_unit_operation,
)
from src.utils import unit_payment_models
from src.utils.errors import AppError, ErrorCode
from src.utils.mutations import IdempotentMutationRunner
from src.utils.unit_payment_models import MAX_ACTIVE_PAYMENT_METHODS, PAYMENT_CAPACITY_SK, build_payment_item
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


def _markers_for(units_table: Any, operation: str) -> List[Dict[str, Any]]:
    """The markers one operation type wrote, whatever else the test seeded."""
    return [row for row in _markers(units_table) if f"#{operation}#" in str(row["pk"])]


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


def test_a_second_admin_who_edits_a_method_is_the_one_who_edited_it(units_table: Any) -> None:
    """The rename audit names the editor; the creator is only ever the creator.

    Two admins, one method: Devon creates it, Avery renames it, Devon retires it.
    Each revision has to say who wrote it, because the account that can be held to
    an edit is the one that made it — and the method that was created may by then
    belong to someone else's Unit grant entirely.
    """
    _seed(units_table, PACK_ID, [DEVON, AVERY])
    created = _create(units_table, DEVON, displayName="Wise")
    payment_method_id = created["paymentMethodId"]

    renamed = _rename(units_table, AVERY, paymentMethodId=payment_method_id, displayName="Wise Mobile")
    assert renamed["createdByAccountId"] == DEVON
    assert renamed["updatedByAccountId"] == AVERY
    assert renamed["createdAt"] == created["createdAt"]

    deactivated = _deactivate(units_table, DEVON, paymentMethodId=payment_method_id, version=2)
    assert deactivated["createdByAccountId"] == DEVON
    assert deactivated["updatedByAccountId"] == DEVON

    rows = _payment_rows(units_table)
    assert len(rows) == 1
    assert [rows[0][key] for key in ("createdByAccountId", "updatedByAccountId", "version", "isActive")] == [
        DEVON,
        DEVON,
        3,
        False,
    ]


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
    assert_is_error(
        _deactivate(units_table, AVERY, key="deactivate-2", paymentMethodId="CASH"), ErrorCode.INVALID_INPUT
    )
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
    assert_is_error(
        _deactivate(units_table, DEVON, key="deactivate-x", paymentMethodId="anything"), ErrorCode.NOT_FOUND
    )

    assert_is_error(
        _rename(
            units_table, AVERY, key="rename-cross", paymentMethodId=created["paymentMethodId"], displayName="Stolen"
        ),
        ErrorCode.NOT_FOUND,
    )
    assert [(row["pk"], row["sk"]) for row in _payment_rows(units_table, TROOP_PK)] == [(TROOP_PK, "PAYMENT#wise")]
    assert _payment_rows(units_table) == []


# --- what decides when two writes race --------------------------------------------


def _capacity_counter(units_table: Any, pk: str = PACK_PK) -> int:
    """The Unit's stored active-method counter."""
    rows = [row for row in units_table.scan()["Items"] if row["pk"] == pk and row["sk"] == PAYMENT_CAPACITY_SK]
    assert len(rows) == 1, f"expected one {PAYMENT_CAPACITY_SK} row, got {rows!r}"
    return int(rows[0]["activeCount"])


def _plant_active_methods(units_table: Any, count: int) -> None:
    """Seed a Unit with `count` active customs and a counter that already agrees."""
    for index in range(count):
        units_table.put_item(
            Item=build_payment_item(
                payment_method_id=f"pm-seeded-{index}",
                unit_id=PACK_ID,
                display_name=f"Method {index}",
                created_by_account_id=AVERY,
                now_iso="2026-11-21T00:00:00+00:00",
            )
        )
    units_table.put_item(
        Item={
            **unit_payment_models.payment_capacity_key(PACK_ID),
            "activeCount": count,
            "updatedAt": "2026-11-21T00:00:00+00:00",
            "updatedByAccountId": AVERY,
        }
    )


def _twin_commits_in_the_write_window(monkeypatch: pytest.MonkeyPatch, twin: Callable[[], Any]) -> None:
    """Let an identical concurrent request commit inside one handler's own write window.

    A real twin arrives on a second connection at an unknowable moment, so the
    interleaving is forced at the one place both halves of every mutation pass
    through: the idempotency-marker read. The first read is the handler's replay
    check, the second is inside ``execute``. A twin that lands between them is
    what the marker condition, the ``paymentMethodId`` condition, and the counter
    condition exist for, and it cannot be produced any other way in one thread.
    """
    real_load = IdempotentMutationRunner.load_marker
    state = {"calls": 0, "done": False}

    def load_marker(self: Any, keys: Any) -> Any:
        state["calls"] += 1
        if state["calls"] == 2 and not state["done"]:
            state["done"] = True
            committed = twin()
            assert not isinstance(committed, dict) or "__isError" not in committed, committed
        return real_load(self, keys)

    monkeypatch.setattr(IdempotentMutationRunner, "load_marker", load_marker)


def test_two_creates_competing_for_the_last_slot_settle_on_the_counter(units_table: Any, monkeypatch: Any) -> None:
    """PAY-M-01-03 — the collection count is advice; the counter's condition decides.

    Both competitors read 49 active methods, so the read in front of the write
    cannot be what keeps the Unit at 50: only a counter moved inside the
    transaction, with the ceiling in its condition, refuses the second one whole.
    """
    _seed(units_table, PACK_ID, [AVERY])
    _plant_active_methods(units_table, MAX_ACTIVE_PAYMENT_METHODS - 1)

    assert _create(units_table, AVERY, key="create-last", displayName="Method 49")["isActive"] is True
    assert _capacity_counter(units_table) == MAX_ACTIVE_PAYMENT_METHODS

    real_list = unit_payment_models.list_payment_rows
    monkeypatch.setattr(unit_payment_models, "list_payment_rows", lambda unit_id: real_list(unit_id)[:-1])

    assert_is_error(_create(units_table, AVERY, key="create-twin", displayName="Method 50"), ErrorCode.CONFLICT)
    assert len(_payment_rows(units_table)) == MAX_ACTIVE_PAYMENT_METHODS
    assert _capacity_counter(units_table) == MAX_ACTIVE_PAYMENT_METHODS
    assert len(_markers_for(units_table, CREATE_PAYMENT_METHOD_FIELD)) == 1


def test_deactivating_an_inactive_method_frees_no_second_slot(units_table: Any) -> None:
    """PAY-M-01-03 — one method gives back one slot, and repeating the flip gives none."""
    _seed(units_table, PACK_ID, [AVERY])
    created = _create(units_table, AVERY, displayName="Wise")
    payment_method_id = created["paymentMethodId"]
    _deactivate(units_table, AVERY, paymentMethodId=payment_method_id, version=1)
    assert _capacity_counter(units_table) == 0

    denied = assert_is_error(
        _deactivate(units_table, AVERY, key="deactivate-again", paymentMethodId=payment_method_id, version=2),
        ErrorCode.CONFLICT,
    )
    assert "already inactive" in denied["message"]
    assert _capacity_counter(units_table) == 0
    assert _payment_rows(units_table)[0]["version"] == 2


def test_a_name_reused_while_a_write_is_in_flight_refuses_the_stale_write(
    units_table: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sort key is reusable; ``paymentMethodId`` is what says which method was read.

    The rename reads Wise at version 1, then two other writes move it off that
    name key and put a different method on it — at version 1 again, so a version
    condition alone would let the stale write land on the new method. It refuses,
    and both live rows are exactly as the other writes left them.
    """
    _seed(units_table, PACK_ID, [AVERY, DEVON])
    wise_id = _create(units_table, AVERY, displayName="Wise")["paymentMethodId"]

    def twin() -> Any:
        moved = _rename(units_table, DEVON, key="twin-rename", paymentMethodId=wise_id, displayName="Wise Gold")
        assert isinstance(moved, dict) and moved["version"] == 2, moved
        return _create(units_table, DEVON, key="twin-create", displayName="Wise")

    _twin_commits_in_the_write_window(monkeypatch, twin)

    assert_is_error(_rename(units_table, DEVON, paymentMethodId=wise_id, displayName="WISE"), ErrorCode.CONFLICT)

    rows = {str(row["sk"]): row for row in _payment_rows(units_table)}
    assert rows["PAYMENT#wise"]["paymentMethodId"] != wise_id
    assert [rows["PAYMENT#wise"][key] for key in ("displayName", "version", "isActive")] == ["Wise", 1, True]
    assert rows["PAYMENT#wise gold"]["paymentMethodId"] == wise_id
    assert [rows["PAYMENT#wise gold"][key] for key in ("displayName", "version")] == ["Wise Gold", 2]
    assert len(_markers_for(units_table, UPDATE_PAYMENT_METHOD_FIELD)) == 1


@pytest.mark.parametrize(
    "operation,field",
    [
        ("create", CREATE_PAYMENT_METHOD_FIELD),
        ("rename", UPDATE_PAYMENT_METHOD_FIELD),
        ("deactivate", DEACTIVATE_PAYMENT_METHOD_FIELD),
    ],
)
def test_a_twin_that_commits_first_answers_the_caller_its_result(
    units_table: Any, monkeypatch: pytest.MonkeyPatch, operation: str, field: str
) -> None:
    """A mutation whose twin already committed replays instead of writing again.

    The handler minted its own id and built its own plan before the twin landed,
    so answering from those would name a row that was never written. Every branch
    here takes the stored answer, which is also the only answer whose marker the
    table actually holds.
    """

    def attempt() -> Any:
        if operation == "create":
            return _create(units_table, AVERY, displayName="Wise")
        assert method_id
        if operation == "rename":
            return _rename(units_table, AVERY, paymentMethodId=method_id, displayName="Wise Pay")
        return _deactivate(units_table, AVERY, paymentMethodId=method_id)

    _seed(units_table, PACK_ID, [AVERY])
    method_id = None if operation == "create" else _create(units_table, AVERY, displayName="Wise")["paymentMethodId"]

    _twin_commits_in_the_write_window(monkeypatch, attempt)
    answered = attempt()

    rows = _payment_rows(units_table)
    assert len(rows) == 1 and len(_markers_for(units_table, field)) == 1
    assert isinstance(answered, dict) and answered["paymentMethodId"] == rows[0]["paymentMethodId"]
    assert answered["version"] == rows[0]["version"] == (1 if operation == "create" else 2)


def _winner_commits_before_the_domains_own_read(monkeypatch: pytest.MonkeyPatch, winner: Callable[[], Any]) -> Any:
    """Let an identical concurrent request commit after this attempt's replay check.

    :func:`_twin_commits_in_the_write_window` lands the twin inside ``execute``, which
    is the late half of the window. This is the early half, and the one a domain rule
    makes dangerous: the twin commits right after the replay check's marker read, so
    every read this attempt makes afterwards sees the winner's state — the name is
    taken, the 50 slots are full, the method is already inactive — and the attempt is
    about to refuse a caller whose own ``idempotencyKey`` already succeeded. The hook
    is the marker read again, because it is the one call between the two halves that
    every mutation makes, and the winner runs nested inside it.
    """
    real_load = IdempotentMutationRunner.load_marker
    state = {"calls": 0, "done": False, "answered": None}

    def load_marker(self: Any, keys: Any) -> Any:
        marker = real_load(self, keys)
        state["calls"] += 1
        if state["calls"] == 1 and not state["done"]:
            state["done"] = True
            answered = winner()
            assert not isinstance(answered, dict) or "__isError" not in answered, answered
            state["answered"] = answered
        return marker

    monkeypatch.setattr(IdempotentMutationRunner, "load_marker", load_marker)
    return state


def test_a_create_whose_twin_won_the_name_first_answers_the_caller_its_method(
    units_table: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A duplicate-name refusal is wrong when the duplicate is the caller's own write.

    The attempt read no ``PAYMENT#wise`` row, then its twin — same caller, same
    ``idempotencyKey``, same input — committed one. ``createUnitPaymentMethod`` has
    already produced this caller's method, so a CONFLICT would send them to retry a
    name their own request took, forever.
    """
    _seed(units_table, PACK_ID, [AVERY])
    key = "create-wise"

    def winner() -> Any:
        return _create(units_table, AVERY, key=key, displayName="Wise")

    won = _winner_commits_before_the_domains_own_read(monkeypatch, winner)
    answered = _create(units_table, AVERY, key=key, displayName="Wise")

    rows = _payment_rows(units_table)
    assert len(rows) == 1 and len(_markers_for(units_table, CREATE_PAYMENT_METHOD_FIELD)) == 1
    assert answered == won["answered"]
    assert answered["paymentMethodId"] == rows[0]["paymentMethodId"]
    assert [rows[0][k] for k in ("sk", "version", "isActive")] == ["PAYMENT#wise", 1, True]


def test_a_create_that_finds_the_slots_full_after_its_own_win_is_not_refused(
    units_table: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap reads the collection before the write, so the ceiling can be its twin's work.

    49 methods, two identical attempts, one method left to add: the loser's count
    reads 50 because its own key already added the 50th. ``PAYMENT_METHOD_LIMIT_REACHED``
    would tell an admin to deactivate a method they never created.
    """
    _seed(units_table, PACK_ID, [AVERY])
    _plant_active_methods(units_table, MAX_ACTIVE_PAYMENT_METHODS - 1)
    key = "create-last-again"

    def winner() -> Any:
        return _create(units_table, AVERY, key=key, displayName="Method 49")

    won = _winner_commits_before_the_domains_own_read(monkeypatch, winner)
    answered = _create(units_table, AVERY, key=key, displayName="Method 49")

    assert answered == won["answered"]
    assert len(_payment_rows(units_table)) == MAX_ACTIVE_PAYMENT_METHODS
    assert _capacity_counter(units_table) == MAX_ACTIVE_PAYMENT_METHODS
    assert len(_markers_for(units_table, CREATE_PAYMENT_METHOD_FIELD)) == 1


def test_a_deactivation_the_method_already_answered_is_replayed_not_refused(
    units_table: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``already inactive`` is the honest answer for a fresh attempt, not a retried one.

    The twin's deactivation flipped the flag and freed the slot, so the attempt that
    follows reads an inactive row: refusing there would report a failed mutation,
    double-free nothing, and leave the caller unable to confirm the retirement landed.
    """
    _seed(units_table, PACK_ID, [AVERY])
    wise_id = _create(units_table, AVERY, displayName="Wise")["paymentMethodId"]
    key = "deactivate-wise"

    def winner() -> Any:
        return _deactivate(units_table, AVERY, key=key, paymentMethodId=wise_id)

    won = _winner_commits_before_the_domains_own_read(monkeypatch, winner)
    answered = _deactivate(units_table, AVERY, key=key, paymentMethodId=wise_id)

    assert answered == won["answered"]
    assert [answered[k] for k in ("isActive", "version")] == [False, 2]
    assert _capacity_counter(units_table) == 0
    assert len(_markers_for(units_table, DEACTIVATE_PAYMENT_METHOD_FIELD)) == 1
    assert _payment_rows(units_table)[0]["version"] == 2


# --- the stored-row builder this suite seeds --------------------------------------


def test_a_rename_whose_twin_already_moved_the_name_answers_that_rename(
    units_table: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A taken name is the caller's own rename when the twin was the same request.

    The attempt read ``PAYMENT#wise`` and no ``PAYMENT#pay wave``, then its twin —
    same caller, same ``idempotencyKey``, same new name — committed that rename. The
    name it was told is now held by the very row it asked for, so ``CONFLICT`` would
    send the admin to pick a different name for a change that already happened.
    """
    _seed(units_table, PACK_ID, [AVERY])
    wise_id = _create(units_table, AVERY, displayName="Wise")["paymentMethodId"]
    key = "rename-wise"

    def winner() -> Any:
        return _rename(units_table, AVERY, key=key, paymentMethodId=wise_id, displayName="Pay wave")

    won = _winner_commits_before_the_domains_own_read(monkeypatch, winner)
    answered = _rename(units_table, AVERY, key=key, paymentMethodId=wise_id, displayName="Pay wave")

    rows = _payment_rows(units_table)
    assert answered == won["answered"]
    assert answered["displayName"] == "Pay wave"
    assert [(row["sk"], row["version"]) for row in rows] == [("PAYMENT#pay wave", 2)]
    assert rows[0]["paymentMethodId"] == wise_id
    assert len(_markers_for(units_table, UPDATE_PAYMENT_METHOD_FIELD)) == 1


def test_a_retry_whose_winner_stored_no_answer_is_rebuilt_from_the_row(units_table: Any) -> None:
    """A completed marker with no answer is a read, not a fault.

    A twin can die between its commit and the moment its response would have been
    written on the marker. The row that commit wrote is the record of what happened
    and the marker is only a cache of it, so the retry is answered by re-reading —
    and it is the same loader every other replay of this mutation uses, which is why
    a refusal path and a replay path cannot disagree about what the write produced.
    """
    from src.utils.dynamodb import get_dynamodb_client, tables

    _seed(units_table, PACK_ID, [AVERY])
    created = _create(units_table, AVERY, displayName="Wise")
    marker = _markers_for(units_table, CREATE_PAYMENT_METHOD_FIELD)[0]
    get_dynamodb_client().update_item(
        TableName=tables.units.table_name,
        Key={"pk": {"S": marker["pk"]}, "sk": {"S": marker["sk"]}},
        UpdateExpression="REMOVE resultPayload",
    )

    assert _create(units_table, AVERY, key="create-1", displayName="Wise") == created
    assert len(_payment_rows(units_table)) == 1


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
