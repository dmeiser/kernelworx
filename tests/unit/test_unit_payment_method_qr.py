"""Leaf 4.1.2 — Unit payment-method QR upload, download, and object cleanup.

The cases this work order names, driven through the same handler entrypoint as
4.1.1, with S3 real (moto) rather than stubbed so the object lifecycle — put,
head, ranged read, delete — is the client contract and not a call list:

- valid upload — request mints a key under THIS method's own prefix, the object
  lands there, and confirm references it on a versioned write;
- invalid upload — an object that was never uploaded is NOT_FOUND, and an object
  that is not the image its key claims (wrong magic numbers, or over the 5 MB the
  pre-signed POST pinned) is refused and purged from the bucket;
- foreign key — an ``s3Key`` under another method's, another Unit's, or the
  legacy account prefix is refused before S3 or DynamoDB is touched;
- stale confirm / stale delete — ``expectedVersion`` decides, and the loser
  writes nothing, which is also what stops a replacement from deleting the wrong
  object;
- removed admin — every QR field answers the same NOT_FOUND as the rest of the
  Unit surface, with no writes;
- replacement cleanup — confirming a second image deletes the object it
  displaced and only that object;
- download authorization — the GET is signed from the stored reference, for a
  Unit Admin only, so the field cannot be pointed at another tenant's object.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest
from botocore.exceptions import ClientError

from src.handlers.unit_operations import (
    CONFIRM_PAYMENT_QR_FIELD,
    CREATE_PAYMENT_METHOD_FIELD,
    DELETE_PAYMENT_QR_FIELD,
    PAYMENT_QR_DOWNLOAD_FIELD,
    REQUEST_PAYMENT_QR_FIELD,
    handle_unit_operation,
)
from src.utils import qr_objects
from src.utils.errors import AppError, ErrorCode
from src.utils.qr_objects import (
    MAX_QR_BYTES,
    QR_DOWNLOAD_TTL_SECONDS,
    content_type_for_qr_key,
    delete_qr_object,
    image_magic_matches_key,
    qr_extension_for_content_type,
    qr_object_is_permitted_image,
)
from src.utils.unit_payment_models import (
    UNIT_QR_ROOT,
    new_unit_qr_object_key,
    unit_qr_key_is_mine,
    unit_qr_prefix,
)
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

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 64
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"VP8 " + b"\x00" * 32
LEGACY_KEY = "payment-qr-codes/account-9/wave.png"


def _seed(units_table: Any, unit_id: str, admins: List[str], *, label: str = "Pack", number: int = 3149) -> None:
    """Write a Unit plus one grant per listed admin."""
    units_table.put_item(
        Item=unit_item(unit_id, label, number, "Aurora", "CO", created_by=AVERY, admin_count=len(admins))
    )
    for admin in admins:
        units_table.put_item(Item=grant_item(unit_id, admin, created_by=AVERY))


def _payment_row(units_table: Any, name: str, pk: str = PACK_PK) -> Dict[str, Any]:
    """One stored custom-method row, by normalized name."""
    rows = [row for row in units_table.scan()["Items"] if row["pk"] == pk and row["sk"] == f"PAYMENT#{name}"]
    assert len(rows) == 1, f"expected exactly one PAYMENT#{name} row, got {rows!r}"
    return rows[0]


def _attach_qr(units_table: Any, s3_bucket: Any, *, name: str = "Wise", body: bytes = PNG_BYTES) -> tuple[str, str]:
    """Create a method, upload its image, and confirm it: returns the id and key."""
    payment_method_id = _create(AVERY, display_name=name)
    requested = _request(AVERY, payment_method_id)
    assert isinstance(requested, dict), requested
    s3_key = str(requested["s3Key"])
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=s3_key, Body=body)
    confirmed = _confirm(AVERY, payment_method_id, s3_key)
    assert isinstance(confirmed, dict) and confirmed.get("qrCodeS3Key") == s3_key, confirmed
    return payment_method_id, s3_key


def _stored_qr(units_table: Any, s3_key: str, *, name: str = "wise", pk: str = PACK_PK) -> None:
    """Point a stored method at an object directly, bypassing the confirm path."""
    units_table.update_item(
        Key={"pk": pk, "sk": f"PAYMENT#{name}"},
        UpdateExpression="SET #qr = :qr",
        ExpressionAttributeNames={"#qr": "qrCodeS3Key"},
        ExpressionAttributeValues={":qr": s3_key},
    )


def _keys(s3_bucket: Any) -> List[str]:
    listed = s3_bucket.list_objects_v2(Bucket=os.environ["EXPORTS_BUCKET"])
    return [str(item["Key"]) for item in listed.get("Contents", [])]


def _create(caller: Any, *, unit_id: str = PACK_ID, key: str = "create-1", display_name: str = "Wise") -> str:
    """Create a custom method and return its paymentMethodId."""
    payload = {"unitId": unit_id, "displayName": display_name, "idempotency": {"idempotencyKey": key}}
    created = handle_unit_operation(unit_operation_event(CREATE_PAYMENT_METHOD_FIELD, caller, input=payload), None)
    assert isinstance(created, dict) and "paymentMethodId" in created, created
    return str(created["paymentMethodId"])


def _request(
    caller: Any,
    payment_method_id: str,
    *,
    unit_id: str = PACK_ID,
    key: str = "qr-req-1",
    content_type: Any = "image/png",
) -> Any:
    payload = {
        "unitId": unit_id,
        "paymentMethodId": payment_method_id,
        "contentType": content_type,
        "idempotency": {"idempotencyKey": key},
    }
    return handle_unit_operation(unit_operation_event(REQUEST_PAYMENT_QR_FIELD, caller, input=payload), None)


def _confirm(
    caller: Any,
    payment_method_id: str,
    s3_key: str,
    *,
    unit_id: str = PACK_ID,
    key: str = "qr-confirm-1",
    version: int = 1,
) -> Any:
    payload = {
        "unitId": unit_id,
        "paymentMethodId": payment_method_id,
        "s3Key": s3_key,
        "version": {"expectedVersion": version},
        "idempotency": {"idempotencyKey": key},
    }
    return handle_unit_operation(unit_operation_event(CONFIRM_PAYMENT_QR_FIELD, caller, input=payload), None)


def _delete(
    caller: Any,
    payment_method_id: str,
    *,
    unit_id: str = PACK_ID,
    key: str = "qr-delete-1",
    version: int = 1,
) -> Any:
    payload = {
        "unitId": unit_id,
        "paymentMethodId": payment_method_id,
        "version": {"expectedVersion": version},
        "idempotency": {"idempotencyKey": key},
    }
    return handle_unit_operation(unit_operation_event(DELETE_PAYMENT_QR_FIELD, caller, input=payload), None)


def _download(caller: Any, payment_method_id: str, *, unit_id: str = PACK_ID) -> Any:
    arguments = {"unitId": unit_id, "paymentMethodId": payment_method_id}
    return handle_unit_operation(unit_operation_event(PAYMENT_QR_DOWNLOAD_FIELD, caller, arguments=arguments), None)


# --- The key contract every QR path is decided by ---------------------------------


def test_every_qr_key_sits_under_the_methods_own_prefix() -> None:
    """The key shape is what makes a foreign key detectable and the IAM grant narrow."""
    prefix = unit_qr_prefix(PACK_ID, "pm-1f0d")
    assert prefix == f"{UNIT_QR_ROOT}/{PACK_ID}/pm-1f0d"

    key = new_unit_qr_object_key(PACK_ID, "pm-1f0d", "png")
    assert key.startswith(f"{prefix}/") and key.endswith(".png")
    assert unit_qr_key_is_mine(key, PACK_ID, "pm-1f0d")
    # One object name per upload, so a replacement is never the object it displaces.
    assert new_unit_qr_object_key(PACK_ID, "pm-1f0d", "png") != key


def test_a_key_is_only_mine_inside_my_own_prefix_and_object_shape() -> None:
    """Foreign shapes: another method, another Unit, the legacy scheme, a smuggled name."""
    mine = new_unit_qr_object_key(PACK_ID, "pm-1f0d", "png")

    assert not unit_qr_key_is_mine(new_unit_qr_object_key(PACK_ID, "pm-2e1c", "png"), PACK_ID, "pm-1f0d")
    assert not unit_qr_key_is_mine(new_unit_qr_object_key(TROOP_ID, "pm-1f0d", "png"), PACK_ID, "pm-1f0d")
    assert not unit_qr_key_is_mine(LEGACY_KEY, PACK_ID, "pm-1f0d")
    smuggled = f"{unit_qr_prefix(PACK_ID, 'pm-1f0d')}/../{mine.rsplit('/', 1)[-1]}"
    assert not unit_qr_key_is_mine(smuggled, PACK_ID, "pm-1f0d")
    assert not unit_qr_key_is_mine(f"{unit_qr_prefix(PACK_ID, 'pm-1f0d')}/notes.txt", PACK_ID, "pm-1f0d")
    assert not unit_qr_key_is_mine(f"{UNIT_QR_ROOT}/{PACK_ID}/pm-1f0d-2/x.png", PACK_ID, "pm-1f0d")


def test_a_qr_prefix_refuses_a_segment_that_is_not_one_key_segment() -> None:
    """An unchecked segment would let ``a/..`` match another tenant's prefix."""
    for bad in ("", "pack/..", "pack sub", "a" * 65):
        with pytest.raises(AppError) as raised:
            unit_qr_prefix(bad, "pm-1f0d")
        assert raised.value.error_code == ErrorCode.INVALID_INPUT
        assert raised.value.message == "unitId cannot address a QR object"


def test_content_type_and_key_extension_agree() -> None:
    """The POST declares the type the confirm step then checks the bytes against."""
    assert qr_extension_for_content_type("image/png") == "png"
    assert qr_extension_for_content_type("  IMAGE/JPEG ") == "jpg"
    assert qr_extension_for_content_type("image/webp") == "webp"
    assert content_type_for_qr_key("payment-qr-codes/units/u/p/x.jpg") == "image/jpeg"

    for bad in (None, "text/plain", 7):
        with pytest.raises(AppError) as raised:
            qr_extension_for_content_type(bad)
        assert raised.value.error_code == ErrorCode.INVALID_INPUT
    with pytest.raises(AppError) as raised:
        content_type_for_qr_key("payment-qr-codes/units/u/p/x.txt")
    assert raised.value.error_code == ErrorCode.INVALID_INPUT


def test_magic_numbers_are_checked_against_the_keys_own_extension() -> None:
    """The #559 case: a JPEG under a .png key would be served as an image/png URL."""
    assert image_magic_matches_key(PNG_BYTES, "a/x.png")
    assert image_magic_matches_key(JPEG_BYTES, "a/x.jpg")
    assert image_magic_matches_key(JPEG_BYTES, "a/x.jpeg")
    assert image_magic_matches_key(WEBP_BYTES, "a/x.webp")
    assert not image_magic_matches_key(JPEG_BYTES, "a/x.png")
    assert not image_magic_matches_key(PNG_BYTES, "a/x.unknown")
    assert not image_magic_matches_key(b"<html>not an image</html>", "a/x.png")


def test_an_empty_object_is_never_a_permitted_image(s3_bucket: Any) -> None:
    """Zero bytes is refused without reading the object at all."""
    assert qr_object_is_permitted_image(s3_bucket, os.environ["EXPORTS_BUCKET"], "a/x.png", 0) is False


# --- requestUnitPaymentMethodQrUpload ---------------------------------------------


def test_request_mints_a_scoped_upload_target_and_stores_nothing_but_the_marker(
    units_table: Any, s3_bucket: Any
) -> None:
    """The upload target exists before the object does; the row is untouched."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)

    requested = _request(AVERY, payment_method_id)

    assert isinstance(requested, dict), requested
    assert set(requested) == {"uploadUrl", "fields", "s3Key"}
    assert requested["uploadUrl"].startswith("https://")
    assert unit_qr_key_is_mine(str(requested["s3Key"]), PACK_ID, payment_method_id)
    assert _payment_row(units_table, "wise").get("qrCodeS3Key") is None
    assert _keys(s3_bucket) == []


def test_request_replays_the_same_object_name_for_the_same_call(units_table: Any, s3_bucket: Any) -> None:
    """IDEM — a retried request never mints a second orphan in the bucket."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)

    first = _request(AVERY, payment_method_id)
    again = _request(AVERY, payment_method_id)

    assert again == first
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=str(first["s3Key"]), Body=PNG_BYTES)
    assert _confirm(AVERY, payment_method_id, str(first["s3Key"]))["qrCodeS3Key"] == first["s3Key"]
    assert _keys(s3_bucket) == [first["s3Key"]]


def test_request_refuses_a_content_type_that_is_not_an_image(units_table: Any, s3_bucket: Any) -> None:
    """The allowed set is the one confirm can validate: PNG, JPEG, and WebP."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)

    refused = assert_is_error(
        _request(AVERY, payment_method_id, content_type="application/pdf"), ErrorCode.INVALID_INPUT
    )
    assert "image/jpeg" in refused["message"]
    assert _payment_row(units_table, "wise").get("qrCodeS3Key") is None


def test_request_refuses_a_builtin_and_an_unknown_method(units_table: Any, s3_bucket: Any) -> None:
    """A built-in has no row to carry a QR reference, so it has no upload either."""
    _seed(units_table, PACK_ID, [AVERY])

    assert_is_error(_request(AVERY, "CASH"), ErrorCode.INVALID_INPUT)
    assert_is_error(_request(AVERY, "no-such-method"), ErrorCode.NOT_FOUND)
    assert_is_error(_request(RILEY, "no-such-method"), ErrorCode.NOT_FOUND)
    assert_is_error(_request(None, "no-such-method"), ErrorCode.UNAUTHORIZED)


# --- confirmUnitPaymentMethodQrUpload ---------------------------------------------


def test_valid_upload_references_the_object_on_a_versioned_write(units_table: Any, s3_bucket: Any) -> None:
    """The named case: request, upload, confirm — the row names the object."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)
    requested = _request(AVERY, payment_method_id)
    s3_key = str(requested["s3Key"])
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=s3_key, Body=PNG_BYTES)

    confirmed = _confirm(AVERY, payment_method_id, s3_key)

    assert confirmed["qrCodeS3Key"] == s3_key
    assert confirmed["version"] == 2
    assert _payment_row(units_table, "wise")["qrCodeS3Key"] == s3_key
    assert _keys(s3_bucket) == [s3_key]


@pytest.mark.parametrize(
    "display_name,content_type,body,extension",
    [("Wise", "image/png", PNG_BYTES, ".png"), ("Wave pay", "image/jpeg", JPEG_BYTES, ".jpg")],
)
def test_each_permitted_image_type_round_trips(
    units_table: Any, s3_bucket: Any, display_name: str, content_type: str, body: bytes, extension: str
) -> None:
    """Each allowed type is stored under, and validated against, its own extension."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY, display_name=display_name)
    requested = _request(AVERY, payment_method_id, content_type=content_type)
    s3_key = str(requested["s3Key"])
    assert s3_key.endswith(extension)

    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=s3_key, Body=body)

    assert _confirm(AVERY, payment_method_id, s3_key)["qrCodeS3Key"] == s3_key


def test_confirm_refuses_a_key_that_belongs_to_another_method(units_table: Any, s3_bucket: Any) -> None:
    """The named foreign-key case, in all of its shapes."""
    _seed(units_table, PACK_ID, [AVERY, DEVON])
    first_id, first_key = _attach_qr(units_table, s3_bucket)
    second_id = _create(DEVON, key="create-2", display_name="Wave pay")

    refused = assert_is_error(_confirm(DEVON, second_id, first_key, key="cfm-steal"), ErrorCode.FORBIDDEN)
    assert refused["message"] == "Invalid S3 key - access denied"

    assert _payment_row(units_table, "wave pay").get("qrCodeS3Key") is None
    assert _payment_row(units_table, "wise")["qrCodeS3Key"] == first_key

    foreign = [new_unit_qr_object_key(TROOP_ID, first_id, "png"), LEGACY_KEY, f"{UNIT_QR_ROOT}/{PACK_ID}/x/y.png"]
    for index, key in enumerate(foreign):
        assert_is_error(_confirm(AVERY, second_id, key, key=f"cfm-foreign-{index}"), ErrorCode.FORBIDDEN)
    assert _keys(s3_bucket) == [first_key]


def test_confirm_refuses_an_object_that_was_never_uploaded(units_table: Any, s3_bucket: Any) -> None:
    """Confirm before the browser finished its POST: NOT_FOUND, nothing written."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)
    requested = _request(AVERY, payment_method_id)

    refused = assert_is_error(_confirm(AVERY, payment_method_id, str(requested["s3Key"])), ErrorCode.NOT_FOUND)
    assert "Upload not found" in refused["message"]
    assert _payment_row(units_table, "wise").get("qrCodeS3Key") is None


def test_confirm_refuses_bytes_that_are_not_the_image_the_key_claims(units_table: Any, s3_bucket: Any) -> None:
    """The named invalid-upload case: refuse, and purge the object from the bucket."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)
    requested = _request(AVERY, payment_method_id)
    s3_key = str(requested["s3Key"])
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=s3_key, Body=JPEG_BYTES)

    refused = assert_is_error(_confirm(AVERY, payment_method_id, s3_key), ErrorCode.INVALID_INPUT)
    assert refused["message"] == "Uploaded file is not a valid image"
    assert _keys(s3_bucket) == []
    assert _payment_row(units_table, "wise").get("qrCodeS3Key") is None


def test_confirm_refuses_an_oversized_object_and_purges_it(units_table: Any, s3_bucket: Any) -> None:
    """The pre-signed POST pins 5 MB; confirm re-checks it and leaves nothing behind."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)
    requested = _request(AVERY, payment_method_id)
    s3_key = str(requested["s3Key"])
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=s3_key, Body=PNG_BYTES + b"\x00" * MAX_QR_BYTES)

    refused = assert_is_error(_confirm(AVERY, payment_method_id, s3_key), ErrorCode.INVALID_INPUT)
    assert "larger than 5 MB" in refused["message"]
    assert _keys(s3_bucket) == []


def test_confirm_honours_the_version_and_the_loser_writes_nothing(units_table: Any, s3_bucket: Any) -> None:
    """A stale confirm cannot displace the image another admin attached."""
    _seed(units_table, PACK_ID, [AVERY, DEVON])
    payment_method_id, first_key = _attach_qr(units_table, s3_bucket)
    requested = _request(DEVON, payment_method_id, content_type="image/webp", key="qr-req-2")
    second_key = str(requested["s3Key"])
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=second_key, Body=WEBP_BYTES)

    assert_is_error(_confirm(DEVON, payment_method_id, second_key, key="cfm-stale"), ErrorCode.CONFLICT)

    assert _payment_row(units_table, "wise")["qrCodeS3Key"] == first_key
    assert _payment_row(units_table, "wise")["version"] == 2
    assert sorted(_keys(s3_bucket)) == sorted([first_key, second_key])


def test_a_retried_confirm_or_delete_replays_its_own_answer(units_table: Any, s3_bucket: Any) -> None:
    """IDEM — the two QR mutations that write a row replay without writing twice."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)
    requested = _request(AVERY, payment_method_id)
    s3_key = str(requested["s3Key"])
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=s3_key, Body=PNG_BYTES)

    confirmed = _confirm(AVERY, payment_method_id, s3_key)
    assert _confirm(AVERY, payment_method_id, s3_key) == confirmed
    assert _payment_row(units_table, "wise")["version"] == 2

    deleted = _delete(AVERY, payment_method_id, key="qr-delete-1", version=2)
    assert _delete(AVERY, payment_method_id, key="qr-delete-1", version=2) == deleted
    assert _payment_row(units_table, "wise")["version"] == 3
    assert _keys(s3_bucket) == []


def test_a_replacement_deletes_the_object_it_displaced(units_table: Any, s3_bucket: Any) -> None:
    """The cleanup case: one reference, one object, and the old image is gone."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id, first_key = _attach_qr(units_table, s3_bucket)

    requested = _request(AVERY, payment_method_id, content_type="image/webp", key="qr-req-2")
    second_key = str(requested["s3Key"])
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=second_key, Body=WEBP_BYTES)

    assert _confirm(AVERY, payment_method_id, second_key, key="cfm-2", version=2)["qrCodeS3Key"] == second_key
    assert _keys(s3_bucket) == [second_key]


def test_a_stored_reference_outside_the_prefix_is_never_deleted_here(units_table: Any, s3_bucket: Any) -> None:
    """A legacy-scheme reference is another role's object: leave it, and log it."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=LEGACY_KEY, Body=PNG_BYTES)
    _stored_qr(units_table, LEGACY_KEY)
    requested = _request(AVERY, payment_method_id, key="qr-req-2")
    new_key = str(requested["s3Key"])
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=new_key, Body=PNG_BYTES)

    assert _confirm(AVERY, payment_method_id, new_key, key="cfm-2", version=1)["qrCodeS3Key"] == new_key
    assert sorted(_keys(s3_bucket)) == sorted([LEGACY_KEY, new_key])


# --- deleteUnitPaymentMethodQrCode ------------------------------------------------


def test_delete_removes_the_reference_and_the_object(units_table: Any, s3_bucket: Any) -> None:
    """Reference and object go together; no sale row is read or written here."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id, s3_key = _attach_qr(units_table, s3_bucket)

    deleted = _delete(AVERY, payment_method_id, version=2)

    assert deleted["qrCodeS3Key"] is None
    assert deleted["version"] == 3
    assert "qrCodeS3Key" not in _payment_row(units_table, "wise")
    assert _keys(s3_bucket) == []


def test_delete_refuses_a_method_with_no_image_and_a_stale_version(units_table: Any, s3_bucket: Any) -> None:
    """Nothing to remove is INVALID_INPUT; a stale version keeps the reference and the object."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)

    refused = assert_is_error(_delete(AVERY, payment_method_id), ErrorCode.INVALID_INPUT)
    assert "no QR image to remove" in refused["message"]

    _attach_qr(units_table, s3_bucket)
    assert_is_error(_delete(AVERY, payment_method_id, key="qr-delete-2"), ErrorCode.CONFLICT)
    assert _payment_row(units_table, "wise")["qrCodeS3Key"] is not None
    assert len(_keys(s3_bucket)) == 1


# --- unitPaymentMethodQrDownloadUrl -----------------------------------------------


def test_download_url_is_signed_from_the_stored_reference_for_a_unit_admin(
    units_table: Any, s3_bucket: Any
) -> None:
    """The URL names the stored object and expires; it is never a durable link."""
    _seed(units_table, PACK_ID, [AVERY, DEVON])
    payment_method_id, s3_key = _attach_qr(units_table, s3_bucket)

    signed = _download(DEVON, payment_method_id)

    assert set(signed) == {"downloadUrl", "expiresAt"}
    assert s3_key in signed["downloadUrl"]
    assert "Signature=" in signed["downloadUrl"]
    remaining = datetime.fromisoformat(signed["expiresAt"]) - datetime.now(timezone.utc)
    window = timedelta(seconds=QR_DOWNLOAD_TTL_SECONDS)
    assert window - timedelta(seconds=120) < remaining <= window + timedelta(seconds=60)


def test_download_url_requires_a_unit_admin_and_a_stored_image(units_table: Any, s3_bucket: Any) -> None:
    """Nothing is ever signed for a caller-supplied key, and no image means NOT_FOUND."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)

    assert_is_error(_download(AVERY, payment_method_id), ErrorCode.NOT_FOUND)
    assert_is_error(_download(RILEY, payment_method_id), ErrorCode.NOT_FOUND)
    assert_is_error(_download(None, payment_method_id), ErrorCode.UNAUTHORIZED)
    assert_is_error(_download(AVERY, "CASH"), ErrorCode.NOT_FOUND)

    _, s3_key = _attach_qr(units_table, s3_bucket)
    assert s3_key in str(_download(AVERY, payment_method_id)["downloadUrl"])

    _stored_qr(units_table, LEGACY_KEY)
    assert_is_error(_download(AVERY, payment_method_id), ErrorCode.NOT_FOUND)


# --- authorization, for all four fields ------------------------------------------


def test_a_removed_admin_reaches_no_qr_field_and_writes_nothing(units_table: Any, s3_bucket: Any) -> None:
    """Revocation closes the QR paths exactly as it closes the rest of the Unit surface."""
    _seed(units_table, PACK_ID, [AVERY, DEVON])
    payment_method_id, s3_key = _attach_qr(units_table, s3_bucket)
    units_table.delete_item(Key={"pk": PACK_PK, "sk": f"GRANT#{DEVON}"})

    assert_is_error(_request(DEVON, payment_method_id, key="qr-req-9"), ErrorCode.NOT_FOUND)
    assert_is_error(_confirm(DEVON, payment_method_id, s3_key, key="cfm-9", version=2), ErrorCode.NOT_FOUND)
    assert_is_error(_delete(DEVON, payment_method_id, key="qr-del-9", version=2), ErrorCode.NOT_FOUND)
    assert_is_error(_download(DEVON, payment_method_id), ErrorCode.NOT_FOUND)

    assert _payment_row(units_table, "wise")["qrCodeS3Key"] == s3_key
    assert _keys(s3_bucket) == [s3_key]


def test_a_cross_unit_payment_method_id_resolves_to_nothing(units_table: Any, s3_bucket: Any) -> None:
    """Tenant isolation: another Unit's paymentMethodId is NOT_FOUND in both directions."""
    _seed(units_table, PACK_ID, [AVERY])
    _seed(units_table, TROOP_ID, [AVERY], label="Troop", number=7150)
    pack_method = _create(AVERY)
    troop_method = _create(AVERY, unit_id=TROOP_ID, key="create-2")

    assert_is_error(_request(AVERY, troop_method), ErrorCode.NOT_FOUND)
    assert_is_error(_download(AVERY, pack_method, unit_id=TROOP_ID), ErrorCode.NOT_FOUND)
    assert _payment_row(units_table, "wise", TROOP_PK)["unitId"] == TROOP_ID


# --- the object layer outside a handler -------------------------------------------


def test_a_refused_object_delete_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    """The DynamoDB reference is already gone, so a failed delete is an orphan to log."""

    class _Denied:
        def delete_object(self, **kwargs: Any) -> Any:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObject")

    monkeypatch.setattr(qr_objects, "get_s3_client", lambda: _Denied())

    assert delete_qr_object("kernelworx-exports-ue1-dev", f"{UNIT_QR_ROOT}/u/p/x.png") is False


def test_a_head_object_answer_that_is_not_missing_is_not_a_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the absent-key answer is NOT_FOUND; a throttled or denied read is not."""

    class _Throttled:
        def head_object(self, **kwargs: Any) -> Any:
            raise ClientError({"Error": {"Code": "ThrottlingException"}}, "HeadObject")

    monkeypatch.setattr(qr_objects, "get_s3_client", lambda: _Throttled())

    with pytest.raises(ClientError):
        qr_objects.validate_uploaded_qr_object("kernelworx-exports-ue1-dev", f"{UNIT_QR_ROOT}/u/p/x.png")
