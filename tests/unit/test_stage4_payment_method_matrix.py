"""Leaf 4.6.1 — the payment-method and QR surface, validated with a sale on the desk.

§4.6.1 asks for validation of built-in and custom methods, reserved-name handling, the 50/51
active limit, rename and deactivation snapshots, and the four QR paths' authorization, foreign
key rejection and replacement cleanup. §4.1.1 and §4.1.2 built that surface and proved it row by
row, so this module does not repeat those rows. What it adds is the one thing those leaves could
not have — a **recorded sale that names the method**, and a QR object being served while the
method is renamed, re-imaged, deactivated and deleted — because that is the state where a
payment-method change either does or does not reach money:

- one read answers the three computed built-ins and this Unit's customs, in the order the sale
  desk renders them, and a neighbouring Unit's method appears in neither answer;
- no custom method may take a built-in's name, at create or at rename, once a sale has been paid
  under that built-in — expected Cash is only unambiguous while ``CASH`` cannot be manufactured;
- the 50/51 limit is enforced around a method a live sale already used, and the slot a
  deactivation gives back is exactly one;
- AC-18: renaming or deactivating a method reaches every event's *new* sales and leaves every
  existing snapshot alone — in the row, in the sale answer, and in what expected Cash counts;
- all four QR fields refuse another Unit's ``paymentMethodId`` and another Unit's ``s3Key``, and
  the refusal writes nothing to any table and no object to the bucket;
- replacement and delete cleanup leave exactly the object the row serves, while the sales rung up
  under the displaced image still read exactly as they were rung up.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import pytest

from src.handlers.unit_operations import (
    CONFIRM_PAYMENT_QR_FIELD,
    DELETE_PAYMENT_QR_FIELD,
    PAYMENT_QR_DOWNLOAD_FIELD,
    REQUEST_PAYMENT_QR_FIELD,
    handle_unit_operation,
)
from src.utils import show_and_sell_sale_models as sm
from src.utils import unit_payment_models as upm
from src.utils.errors import ErrorCode
from tests.unit.show_sell_fixtures import (
    PACK_3149,
    TROOP_7150,
    account_id,
    assert_is_error,
    seed_show_sell_fixtures,
    unit_operation_event,
)
from tests.unit.test_show_and_sell_sales import (
    ACTIVE_EVENT,
    PRICE_CENTS,
    PRODUCT,
    _method,
    _offer_products,
    _ok,
    _seed_event,
    _seed_stock,
    _stored_sale,
)
from tests.unit.test_show_and_sell_sales import (
    _create as _create_sale,
)
from tests.unit.test_unit_payment_method_qr import (
    WEBP_BYTES,
    _attach_qr,
)
from tests.unit.test_unit_payment_method_qr import (
    _confirm as _qr_confirm,
)
from tests.unit.test_unit_payment_method_qr import (
    _delete as _qr_delete,
)
from tests.unit.test_unit_payment_method_qr import (
    _download as _qr_download,
)
from tests.unit.test_unit_payment_method_qr import (
    _keys as _s3_keys,
)
from tests.unit.test_unit_payment_method_qr import (
    _request as _qr_request,
)
from tests.unit.test_unit_payment_methods import (
    _capacity_counter,
    _payment_rows,
    _plant_active_methods,
)
from tests.unit.test_unit_payment_methods import (
    _create as _new_method,
)
from tests.unit.test_unit_payment_methods import (
    _deactivate as _deactivate_method,
)
from tests.unit.test_unit_payment_methods import (
    _list as _list_methods,
)
from tests.unit.test_unit_payment_methods import (
    _rename as _rename_method,
)

AVERY = account_id("Avery")
RILEY = account_id("Riley")

PACK_PK = f"UNIT#{PACK_3149}"
TROOP_PK = f"UNIT#{TROOP_7150}"

#: A planted custom method with an id this module names, so a sale can be rung up on it before
#: any of the lifecycle mutations run.
WISE_METHOD_ID = "pm-wise-desk"

#: The three computed built-ins, in the display order every read answers them.
BUILT_IN_IDS = ["CASH", "CHECK", "OTHER"]

#: The four fields §4.6.1 names: request, confirm, download, delete.
QR_FIELDS: List[str] = [
    REQUEST_PAYMENT_QR_FIELD,
    CONFIRM_PAYMENT_QR_FIELD,
    PAYMENT_QR_DOWNLOAD_FIELD,
    DELETE_PAYMENT_QR_FIELD,
]


@pytest.fixture
def desk(
    units_table: Any,
    unit_campaigns_table: Any,
    catalogs_table: Any,
    profiles_table: Any,
    campaigns_table: Any,
    shares_table: Any,
    inventory_table: Any,
    show_and_sells_table: Any,
    s3_bucket: Any,
) -> Dict[str, Any]:
    """The Stage 1 world, one running event with stock on it, and the QR bucket.

    A live event with assigned stock is what makes this a payment-method validation and not a
    CRUD test: every case below rings up at least one sale, so a snapshot that moved is visible
    in the sale row rather than only in the method row.
    """
    seed_show_sell_fixtures(
        units_table,
        unit_campaigns_table=unit_campaigns_table,
        catalogs_table=catalogs_table,
        profiles_table=profiles_table,
        campaigns_table=campaigns_table,
        shares_table=shares_table,
    )
    _offer_products(catalogs_table, 4)
    _seed_event(show_and_sells_table, ACTIVE_EVENT, product_ids=[PRODUCT])
    world = {
        "units": units_table,
        "catalogs": catalogs_table,
        "inventory": inventory_table,
        "show_and_sells": show_and_sells_table,
        "s3": s3_bucket,
    }
    _seed_stock(world)
    return world


# --- helpers ----------------------------------------------------------------------


def _wise(desk: Dict[str, Any]) -> str:
    """One custom method with a known id, written the way ``createUnitPaymentMethod`` writes it."""
    _method(desk["units"], payment_method_id=WISE_METHOD_ID, display_name="Wise")
    return WISE_METHOD_ID


def _custom(method_id: str) -> str:
    """The methodCode a sale carries for a custom method."""
    return f"CUSTOM:{method_id}"


def _sold(desk: Dict[str, Any], method_code: str, *, key: str, version: int = 1) -> Dict[str, Any]:
    """Ring up one $5 sale under ``method_code`` and return the answer."""
    return _ok(_create_sale(paymentMethodCode=method_code, key=key, version=version))


def _row(desk: Dict[str, Any], normalized: str, pk: str = PACK_PK) -> Dict[str, Any]:
    """One stored payment-method row, by normalized name."""
    rows = [row for row in desk["units"].scan()["Items"] if row["pk"] == pk and row["sk"] == f"PAYMENT#{normalized}"]
    assert len(rows) == 1, f"expected one PAYMENT#{normalized} row, got {rows!r}"
    return rows[0]


def _snapshot(desk: Dict[str, Any], sale_id: str) -> Dict[str, Any]:
    """One stored sale's snapshot, with the drawer arithmetic the row implies.

    The two extra keys are the point of the helper: a payment-method change that reached a sale
    would show up either as a changed snapshot or as a changed Cash expectation, and this answers
    both from the stored row rather than from whatever the write happened to return.
    """
    stored = _stored_sale(desk["show_and_sells"], ACTIVE_EVENT, str(sale_id))
    assert stored is not None
    return {
        **dict(stored[sm.PAYMENT_SNAPSHOT_ATTRIBUTE]),
        "_expected": sm.sale_expected_cash_cents(stored),
        "_total": int(stored[sm.TOTAL_CENTS_ATTRIBUTE]),
    }


def _names(answer: List[Dict[str, Any]]) -> List[str]:
    return [str(method["displayName"]) for method in answer]


def _qr_call(field: str, caller: str, *, unit_id: str, payment_method_id: str) -> Any:
    """One QR field, addressed at a method id the caller's Unit does not own."""
    if field == PAYMENT_QR_DOWNLOAD_FIELD:
        event = unit_operation_event(field, caller, arguments={"unitId": unit_id, "paymentMethodId": payment_method_id})
        return handle_unit_operation(event, None)

    payload: Dict[str, Any] = {
        "unitId": unit_id,
        "paymentMethodId": payment_method_id,
        "idempotency": {"idempotencyKey": f"qr-cross-{field}"},
    }
    if field == REQUEST_PAYMENT_QR_FIELD:
        payload["contentType"] = "image/png"
        payload["sha256"] = "0" * 64
    else:
        payload["version"] = {"expectedVersion": 2}
        if field == CONFIRM_PAYMENT_QR_FIELD:
            payload["s3Key"] = f"{upm.UNIT_QR_ROOT}/{unit_id}/{payment_method_id}/uploads/{'0' * 64}-00000000.png"
    return handle_unit_operation(unit_operation_event(field, caller, input=payload), None)


# --- built-ins and customs, answered as one vocabulary ----------------------------


def test_the_sale_desk_answers_builtins_then_this_units_own_methods(desk: Dict[str, Any]) -> None:
    """AC-18, AC-21, AUTH-U: one read is the whole vocabulary, and it is this Unit's vocabulary."""
    wise_id, wise_qr = _attach_qr(desk["units"], desk["s3"])
    _new_method(desk["units"], AVERY, key="create-venmo", displayName="Venmo Quick")
    troop_method = _new_method(desk["units"], RILEY, unit_id=TROOP_7150, key="create-zelle", displayName="Zelle Cash")

    answer = _list_methods(desk["units"], AVERY)

    builtins, customs = answer[:3], answer[3:]
    assert [method["paymentMethodId"] for method in builtins] == BUILT_IN_IDS
    for method in builtins:
        # Version 0 is the number no stored method can have, so a caller can never stale-check a
        # built-in — and no built-in can carry an image, whatever a Unit tries to attach to it.
        assert (method["version"], method["isActive"], method["qrCodeS3Key"]) == (0, True, None)
    assert _names(customs) == ["Venmo Quick", "Wise"], "customs come back in PAYMENT# key order"
    assert customs[1]["paymentMethodId"] == wise_id
    assert customs[1]["qrCodeS3Key"] == wise_qr, "the QR an event may print is answered with the method"

    assert troop_method not in [method["paymentMethodId"] for method in answer]
    assert "Zelle Cash" not in _names(answer), "another Unit's method is not on this Unit's desk"

    troop_answer = _list_methods(desk["units"], RILEY, unit_id=TROOP_7150)
    assert _names(troop_answer[3:]) == ["Zelle Cash"]
    assert wise_id not in [method["paymentMethodId"] for method in troop_answer]


def test_no_custom_method_may_take_a_builtin_name_once_a_sale_paid_under_it(desk: Dict[str, Any]) -> None:
    """PAY-M-01-02, CASH-01: the reserved names stay reserved while Cash sales are rung up.

    Expected Cash is derived from ``methodCode == "CASH"`` and from nothing else, so the whole
    cash expectation rests on no Unit being able to manufacture that code — by creating a method
    called Cash, or by renaming one into it after the fact.
    """
    cash = _sold(desk, "CASH", key="sale-cash")
    wise_id = _wise(desk)

    for index, name in enumerate(("Cash", "CASH", "cHeCk", " Other ", "other")):
        assert_is_error(
            _new_method(desk["units"], AVERY, key=f"create-reserved-{index}", displayName=name),
            ErrorCode.INVALID_INPUT,
        )
    assert_is_error(
        _rename_method(desk["units"], AVERY, paymentMethodId=wise_id, displayName="CASH", key="rename-reserved"),
        ErrorCode.INVALID_INPUT,
    )

    assert [row["sk"] for row in _payment_rows(desk["units"])] == ["PAYMENT#wise"]
    assert _snapshot(desk, cash["sale"]["saleId"]) == {
        "methodCode": "CASH",
        "displayName": "Cash",
        "otherDetails": None,
        "_expected": PRICE_CENTS,
        "_total": PRICE_CENTS,
    }


# --- the active-method ceiling ----------------------------------------------------


def test_the_fifty_first_active_method_is_refused_around_a_sale_that_used_one_of_the_fifty(
    desk: Dict[str, Any],
) -> None:
    """PAY-M-01-03, AC-18: the limit counts active customs, and a sale holding one changes nothing."""
    _plant_active_methods(desk["units"], upm.MAX_ACTIVE_PAYMENT_METHODS - 1)
    fiftieth = _new_method(desk["units"], AVERY, key="create-fiftieth", displayName="Method 49")
    assert fiftieth["isActive"] is True
    assert _capacity_counter(desk["units"]) == upm.MAX_ACTIVE_PAYMENT_METHODS

    sale = _sold(desk, _custom(str(fiftieth["paymentMethodId"])), key="sale-fiftieth")
    assert _snapshot(desk, sale["sale"]["saleId"])["_expected"] == 0

    denied = assert_is_error(
        _new_method(desk["units"], AVERY, key="create-overflow", displayName="Method 50"), ErrorCode.CONFLICT
    )
    assert "active payment methods" in denied["message"]
    assert _capacity_counter(desk["units"]) == upm.MAX_ACTIVE_PAYMENT_METHODS

    # The method a live sale references is the one that gets retired, and the slot it gives back
    # buys exactly one new method — never a second one, and never a re-write of the sale.
    _deactivate_method(desk["units"], AVERY, paymentMethodId=str(fiftieth["paymentMethodId"]), version=1)
    assert _capacity_counter(desk["units"]) == upm.MAX_ACTIVE_PAYMENT_METHODS - 1
    assert _new_method(desk["units"], AVERY, key="create-replacement", displayName="Method 50")["isActive"] is True
    assert_is_error(_new_method(desk["units"], AVERY, key="create-again", displayName="Method 51"), ErrorCode.CONFLICT)
    assert _capacity_counter(desk["units"]) == upm.MAX_ACTIVE_PAYMENT_METHODS

    assert _snapshot(desk, sale["sale"]["saleId"]) == {
        "methodCode": _custom(str(fiftieth["paymentMethodId"])),
        "displayName": "Method 49",
        "otherDetails": None,
        "_expected": 0,
        "_total": PRICE_CENTS,
    }


# --- AC-18: the snapshots a method change must not reach --------------------------


def test_a_rename_moves_the_name_and_each_sale_keeps_the_name_it_was_paid_under(desk: Dict[str, Any]) -> None:
    """PAY-M-02-01, AC-18: a rename renames the method; it never edits a sale."""
    wise_id = _wise(desk)
    before = _sold(desk, _custom(wise_id), key="sale-before-rename")

    renamed = _rename_method(desk["units"], AVERY, paymentMethodId=wise_id, displayName="Wise Mobile", key="rename-1")
    assert renamed["paymentMethodId"] == wise_id

    after = _sold(desk, _custom(wise_id), key="sale-after-rename", version=2)

    assert [row["sk"] for row in _payment_rows(desk["units"])] == ["PAYMENT#wise mobile"]
    for sale_id, display_name in ((before["sale"]["saleId"], "Wise"), (after["sale"]["saleId"], "Wise Mobile")):
        snapshot = _snapshot(desk, sale_id)
        assert snapshot["methodCode"] == _custom(wise_id), "the id keeps resolving across the rename"
        assert snapshot["displayName"] == display_name, "the name is the one the buyer was rung up under"
        assert snapshot["_expected"] == 0, "a rename cannot move money into the Cash drawer"


def test_deactivating_a_method_leaves_every_sale_that_named_it_readable(desk: Dict[str, Any]) -> None:
    """PAY-M-03-01, AC-18: the method goes out of service; the sales it took do not go anywhere."""
    wise_id = _wise(desk)
    sale = _sold(desk, _custom(wise_id), key="sale-to-retire")
    _deactivate_method(desk["units"], AVERY, paymentMethodId=wise_id, version=1)

    row = _row(desk, "wise")
    assert (row["isActive"], row["version"], row["paymentMethodId"]) == (False, 2, wise_id)
    assert wise_id not in [method["paymentMethodId"] for method in _list_methods(desk["units"], AVERY)]
    assert [method["isActive"] for method in _list_methods(desk["units"], AVERY, include_inactive=True)[3:]] == [False]

    assert _snapshot(desk, sale["sale"]["saleId"]) == {
        "methodCode": _custom(wise_id),
        "displayName": "Wise",
        "otherDetails": None,
        "_expected": 0,
        "_total": PRICE_CENTS,
    }
    assert _stored_sale(desk["show_and_sells"], ACTIVE_EVENT, str(sale["sale"]["saleId"]))[sm.STATUS_ATTRIBUTE] == (
        sm.SALE_STATUS_ACTIVE
    )

    refused = _create_sale(paymentMethodCode=_custom(wise_id), key="sale-retired", version=2)
    assert "no longer available" in assert_is_error(refused, ErrorCode.CONFLICT)["message"]


# --- the four QR paths ------------------------------------------------------------


def test_every_qr_path_refuses_another_units_method_id_in_both_directions(desk: Dict[str, Any]) -> None:
    """AUTH-U, AC-18: a ``paymentMethodId`` is not an access path, whichever Unit holds it."""
    pack_id, pack_qr = _attach_qr(desk["units"], desk["s3"])
    troop_id = str(
        _new_method(desk["units"], RILEY, unit_id=TROOP_7150, key="create-troop-wise", displayName="Wise")[
            "paymentMethodId"
        ]
    )
    before = _s3_keys(desk["s3"])

    for field in QR_FIELDS:
        assert_is_error(_qr_call(field, AVERY, unit_id=PACK_3149, payment_method_id=troop_id), ErrorCode.NOT_FOUND)
        assert_is_error(_qr_call(field, RILEY, unit_id=TROOP_7150, payment_method_id=pack_id), ErrorCode.NOT_FOUND)

    assert _row(desk, "wise")["qrCodeS3Key"] == pack_qr
    troop_row = _row(desk, "wise", TROOP_PK)
    assert troop_row["paymentMethodId"] == troop_id
    assert "qrCodeS3Key" not in troop_row
    assert _s3_keys(desk["s3"]) == before, "a refused QR path may not put, replace or delete an object"


def test_confirm_refuses_an_upload_key_from_another_units_prefix(desk: Dict[str, Any]) -> None:
    """§4.1.2's key contract from the outside: the key has to sit under the method it names."""
    pack_id, pack_qr = _attach_qr(desk["units"], desk["s3"])
    troop_id = str(
        _new_method(desk["units"], RILEY, unit_id=TROOP_7150, key="create-troop-qr", displayName="Zelle")[
            "paymentMethodId"
        ]
    )
    troop_upload = str(_qr_request(RILEY, troop_id, unit_id=TROOP_7150, key="qr-req-troop")["s3Key"])
    desk["s3"].put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=troop_upload, Body=WEBP_BYTES)

    foreign = assert_is_error(
        _qr_confirm(AVERY, pack_id, troop_upload, key="qr-cfm-foreign", version=2), ErrorCode.FORBIDDEN
    )
    assert foreign["message"] == "Invalid S3 key - access denied"

    assert _row(desk, "wise")["qrCodeS3Key"] == pack_qr
    assert pack_qr in str(_qr_download(AVERY, pack_id)["downloadUrl"])
    assert _s3_keys(desk["s3"]) == [pack_qr, troop_upload]


def test_replacement_and_delete_cleanup_leave_only_the_image_the_method_serves(desk: Dict[str, Any]) -> None:
    """The replacement-cleanup case with sales in flight: one reference, one object, history intact."""
    wise_id, first_key = _attach_qr(desk["units"], desk["s3"])
    under_first = _sold(desk, _custom(wise_id), key="sale-under-first")

    second_upload = str(
        _qr_request(AVERY, wise_id, key="qr-req-2", content_type="image/webp", body=WEBP_BYTES)["s3Key"]
    )
    desk["s3"].put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=second_upload, Body=WEBP_BYTES)
    replacement = str(_qr_confirm(AVERY, wise_id, second_upload, key="qr-cfm-2", version=2)["qrCodeS3Key"])

    # The displaced image and the target this one was published from are both retired, so the
    # bucket holds exactly what the row serves — which is the whole point of the two folders.
    assert replacement not in (first_key, second_upload)
    assert _s3_keys(desk["s3"]) == [replacement]
    assert _row(desk, "wise")["qrCodeS3Key"] == replacement
    assert replacement in str(_qr_download(AVERY, wise_id)["downloadUrl"])

    under_replacement = _sold(desk, _custom(wise_id), key="sale-under-replacement", version=2)

    deleted = _qr_delete(AVERY, wise_id, key="qr-del-1", version=3)
    assert deleted["qrCodeS3Key"] is None
    assert "qrCodeS3Key" not in _row(desk, "wise")
    assert _s3_keys(desk["s3"]) == []
    assert_is_error(_qr_download(AVERY, wise_id), ErrorCode.NOT_FOUND)

    for sale_id in (under_first["sale"]["saleId"], under_replacement["sale"]["saleId"]):
        assert _snapshot(desk, sale_id)["displayName"] == "Wise"


def test_a_rename_does_not_move_the_image_the_method_serves(desk: Dict[str, Any]) -> None:
    """AC-21, PAY-M-02-01: the object sits under the method's id, so a rename cannot orphan it."""
    wise_id, attachment = _attach_qr(desk["units"], desk["s3"])
    sale = _sold(desk, _custom(wise_id), key="sale-with-qr")

    renamed = _rename_method(
        desk["units"], AVERY, paymentMethodId=wise_id, displayName="Wise Mobile", key="rename-qr", version=2
    )
    assert renamed["qrCodeS3Key"] == attachment

    assert _s3_keys(desk["s3"]) == [attachment]
    assert attachment in str(_qr_download(AVERY, wise_id)["downloadUrl"])
    assert upm.unit_qr_attachment_key_is_mine(attachment, PACK_3149, wise_id)
    assert _row(desk, "wise mobile")["qrCodeS3Key"] == attachment
    assert _snapshot(desk, sale["sale"]["saleId"])["displayName"] == "Wise"
