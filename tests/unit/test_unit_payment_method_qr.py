"""Leaf 4.1.2 — Unit payment-method QR upload, download, and object cleanup.

The cases this work order names, driven through the same handler entrypoint as
4.1.1, with S3 real (moto) rather than stubbed so the object lifecycle — put,
head, ranged read, delete — is the client contract and not a call list:

- valid upload — request mints a key under THIS method's own prefix naming the
  SHA-256 of the bytes the browser says it is uploading, the object lands there,
  and confirm references it on a versioned write;
- invalid upload — an object that was never uploaded is NOT_FOUND, a read S3
  refuses is FORBIDDEN rather than a missing upload, and an object that is not
  the image its key claims (wrong magic numbers, bytes that do not match the
  digest in the key, or over the 5 MB the pre-signed POST pinned) is refused and
  purged from the bucket;
- foreign key — an ``s3Key`` under another method's, another Unit's, or the
  legacy account prefix is refused before S3 or DynamoDB is touched;
- stale confirm / stale delete — ``expectedVersion`` and the row's own
  ``paymentMethodId`` decide, and the loser writes nothing, which is also what
  stops a replacement from deleting the wrong object;
- removed admin — every QR field answers the same NOT_FOUND as the rest of the
  Unit surface, with no writes;
- replacement cleanup — confirming a second image deletes the object it
  displaced and only that object, and an S3 delete that fails stays recorded on
  the row so the next write on that method retries it;
- the write window — a twin with the same idempotencyKey that commits between
  this handler's replay check and its transaction is replayed, touching no object,
  and a cleanup ledger whose clear write fails is paid by the next write;
- download authorization — the GET is signed from the stored reference, for a
  Unit Admin only, so the field cannot be pointed at another tenant's object.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import pytest
from botocore.exceptions import ClientError

from src.handlers import unit_operations
from src.handlers.unit_operations import (
    CONFIRM_PAYMENT_QR_FIELD,
    CREATE_PAYMENT_METHOD_FIELD,
    DELETE_PAYMENT_QR_FIELD,
    PAYMENT_QR_DOWNLOAD_FIELD,
    REQUEST_PAYMENT_QR_FIELD,
    UPDATE_PAYMENT_METHOD_FIELD,
    handle_unit_operation,
)
from src.utils import qr_objects
from src.utils.errors import AppError, ErrorCode
from src.utils.mutations import IdempotentMutationRunner
from src.utils.qr_objects import (
    MAX_QR_BYTES,
    QR_DOWNLOAD_TTL_SECONDS,
    content_type_for_qr_key,
    delete_qr_object,
    image_magic_matches_key,
    qr_extension_for_content_type,
    qr_object_bytes,
)
from src.utils.unit_payment_models import (
    UNIT_QR_ROOT,
    new_unit_qr_object_key,
    normalize_qr_digest,
    unit_qr_key_digest,
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

QR_FIELDS_BY_OPERATION = {
    "request": REQUEST_PAYMENT_QR_FIELD,
    "confirm": CONFIRM_PAYMENT_QR_FIELD,
    "delete": DELETE_PAYMENT_QR_FIELD,
}
QR_TWIN_IDEMPOTENCY_KEYS = {"request": "qr-req-2", "confirm": "qr-cfm-2", "delete": "qr-del-2"}


def _digest(body: bytes) -> str:
    """The SHA-256 the browser declares for the bytes it is about to POST."""
    return hashlib.sha256(body).hexdigest()


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


_BODY_DIGEST = object()


def _request(
    caller: Any,
    payment_method_id: str,
    *,
    unit_id: str = PACK_ID,
    key: str = "qr-req-1",
    content_type: Any = "image/png",
    body: bytes = PNG_BYTES,
    sha256: Any = _BODY_DIGEST,
) -> Any:
    payload = {
        "unitId": unit_id,
        "paymentMethodId": payment_method_id,
        "contentType": content_type,
        "sha256": _digest(body) if sha256 is _BODY_DIGEST else sha256,
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


def _rename(
    caller: Any,
    payment_method_id: str,
    display_name: str,
    *,
    unit_id: str = PACK_ID,
    key: str = "rename-1",
    version: int = 1,
) -> Any:
    payload = {
        "unitId": unit_id,
        "paymentMethodId": payment_method_id,
        "displayName": display_name,
        "version": {"expectedVersion": version},
        "idempotency": {"idempotencyKey": key},
    }
    return handle_unit_operation(unit_operation_event(UPDATE_PAYMENT_METHOD_FIELD, caller, input=payload), None)


# --- The key contract every QR path is decided by ---------------------------------


def test_every_qr_key_sits_under_the_methods_own_prefix_naming_its_bytes() -> None:
    """The key shape is what makes a foreign key detectable and the grant narrow."""
    prefix = unit_qr_prefix(PACK_ID, "pm-1f0d")
    assert prefix == f"{UNIT_QR_ROOT}/{PACK_ID}/pm-1f0d"

    digest = _digest(PNG_BYTES)
    key = new_unit_qr_object_key(PACK_ID, "pm-1f0d", digest, "png")
    assert key.startswith(f"{prefix}/{digest}-") and key.endswith(".png")
    assert unit_qr_key_is_mine(key, PACK_ID, "pm-1f0d")
    assert unit_qr_key_digest(key, PACK_ID, "pm-1f0d") == digest
    # One object name per upload request, so a replacement is never the object it
    # displaces and a second POST can never name bytes another request committed.
    assert new_unit_qr_object_key(PACK_ID, "pm-1f0d", digest, "png") != key


def test_a_digest_is_accepted_only_in_the_form_the_key_can_carry() -> None:
    """The browser declares hex; anything else cannot name an object, so refuse it."""
    digest = _digest(PNG_BYTES)
    assert normalize_qr_digest(f"  {digest.upper()} ") == digest
    for bad in (None, "", "x" * 64, digest[:63], digest + "0", 7, digest.replace("0", "é")):
        with pytest.raises(AppError) as raised:
            normalize_qr_digest(bad)
        assert raised.value.error_code == ErrorCode.INVALID_INPUT


def test_a_key_is_only_mine_inside_my_own_prefix_and_object_shape() -> None:
    """Foreign shapes: another method, another Unit, the legacy scheme, a smuggled name."""
    digest = _digest(PNG_BYTES)
    mine = new_unit_qr_object_key(PACK_ID, "pm-1f0d", digest, "png")

    assert not unit_qr_key_is_mine(new_unit_qr_object_key(PACK_ID, "pm-2e1c", digest, "png"), PACK_ID, "pm-1f0d")
    assert not unit_qr_key_is_mine(new_unit_qr_object_key(TROOP_ID, "pm-1f0d", digest, "png"), PACK_ID, "pm-1f0d")
    assert not unit_qr_key_is_mine(LEGACY_KEY, PACK_ID, "pm-1f0d")
    smuggled = f"{unit_qr_prefix(PACK_ID, 'pm-1f0d')}/../{mine.rsplit('/', 1)[-1]}"
    assert not unit_qr_key_is_mine(smuggled, PACK_ID, "pm-1f0d")
    assert not unit_qr_key_is_mine(f"{unit_qr_prefix(PACK_ID, 'pm-1f0d')}/notes.txt", PACK_ID, "pm-1f0d")
    assert not unit_qr_key_is_mine(f"{UNIT_QR_ROOT}/{PACK_ID}/pm-1f0d-2/x.png", PACK_ID, "pm-1f0d")
    # A name that declares no digest is not an object this method can attach, and
    # its empty digest matches nothing that could be stored.
    assert not unit_qr_key_is_mine(f"{unit_qr_prefix(PACK_ID, 'pm-1f0d')}/upload.png", PACK_ID, "pm-1f0d")
    assert unit_qr_key_digest(f"{unit_qr_prefix(PACK_ID, 'pm-1f0d')}/upload.png", PACK_ID, "pm-1f0d") == ""
    assert unit_qr_key_digest(mine, TROOP_ID, "pm-1f0d") == ""


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


def test_an_objects_bytes_are_read_once_for_both_checks(s3_bucket: Any) -> None:
    """One GET feeds the format check and the digest check: no second snapshot."""
    bucket = os.environ["EXPORTS_BUCKET"]
    s3_bucket.put_object(Bucket=bucket, Key="a/x.png", Body=PNG_BYTES)

    assert qr_object_bytes(s3_bucket, bucket, "a/x.png") == PNG_BYTES


# --- the digest is what makes an attachment immutable -------------------------------


def test_the_upload_request_puts_the_declared_digest_in_the_object_name(
    units_table: Any, s3_bucket: Any
) -> None:
    """A second request for the same method can never name the same object."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)

    first = _request(AVERY, payment_method_id)
    again = _request(AVERY, payment_method_id, key="qr-req-2")

    prefix = f"{unit_qr_prefix(PACK_ID, payment_method_id)}/{_digest(PNG_BYTES)}-"
    assert str(first["s3Key"]).startswith(prefix) and str(again["s3Key"]).startswith(prefix)
    assert first["s3Key"] != again["s3Key"]
    # The bytes of one request are refused at the other request's key, so a POST
    # can never swap content under a reference that is already current.
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=str(first["s3Key"]), Body=PNG_BYTES)
    refused = assert_is_error(_confirm(AVERY, payment_method_id, str(again["s3Key"])), ErrorCode.NOT_FOUND)
    assert "Upload not found" in refused["message"]


@pytest.mark.parametrize(
    "sha256",
    [
        None,
        "",
        "not-a-digest",
        _digest(PNG_BYTES)[:63],
        _digest(PNG_BYTES) + "0",
        7,
    ],
)
def test_the_upload_request_refuses_a_digest_that_cannot_name_an_object(
    units_table: Any, s3_bucket: Any, sha256: Any
) -> None:
    """The digest has to be the hex SHA-256 of what the browser is posting."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)

    refused = assert_is_error(_request(AVERY, payment_method_id, sha256=sha256), ErrorCode.INVALID_INPUT)
    assert "sha256" in refused["message"]
    assert _payment_row(units_table, "wise").get("qrCodeS3Key") is None


def test_confirm_refuses_bytes_that_are_not_the_digest_the_key_names(units_table: Any, s3_bucket: Any) -> None:
    """A valid PNG whose bytes differ from the key's digest is refused and purged."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)
    requested = _request(AVERY, payment_method_id)
    s3_key = str(requested["s3Key"])
    substituted = PNG_BYTES[:-1] + b"\x01"
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=s3_key, Body=substituted)

    assert image_magic_matches_key(substituted, s3_key)
    assert _digest(substituted) != _digest(PNG_BYTES)
    refused = assert_is_error(_confirm(AVERY, payment_method_id, s3_key), ErrorCode.INVALID_INPUT)
    assert refused["message"] == "Uploaded file does not match the upload request"
    assert _keys(s3_bucket) == []
    assert _payment_row(units_table, "wise").get("qrCodeS3Key") is None


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
    requested = _request(AVERY, payment_method_id, content_type=content_type, body=body)
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

    foreign = [
        new_unit_qr_object_key(TROOP_ID, first_id, _digest(PNG_BYTES), "png"),
        LEGACY_KEY,
        f"{UNIT_QR_ROOT}/{PACK_ID}/x/y.png",
        f"{unit_qr_prefix(PACK_ID, second_id)}/upload.png",
    ]
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
    requested = _request(DEVON, payment_method_id, content_type="image/webp", body=WEBP_BYTES, key="qr-req-2")
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

    requested = _request(AVERY, payment_method_id, content_type="image/webp", body=WEBP_BYTES, key="qr-req-2")
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


def _refuse_first_object_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make exactly one object delete fail, then let the real one through.

    Refusing every delete would leave nothing for the retry this test is about,
    and ``monkeypatch.undo()`` would unwind the test's AWS environment with it.
    """
    real_delete = qr_objects.delete_qr_object
    state = {"refused": False}

    def delete_once(bucket: str, s3_key: str) -> bool:
        if not state["refused"]:
            state["refused"] = True
            return False
        return real_delete(bucket, s3_key)

    monkeypatch.setattr(qr_objects, "delete_qr_object", delete_once)


def test_a_refused_object_delete_stays_owed_and_the_next_write_pays_it(
    units_table: Any, s3_bucket: Any, monkeypatch: Any
) -> None:
    """A failed S3 delete is cleanup work the row remembers, not a dropped line."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id, first_key = _attach_qr(units_table, s3_bucket)
    requested = _request(AVERY, payment_method_id, content_type="image/webp", body=WEBP_BYTES, key="qr-req-2")
    second_key = str(requested["s3Key"])
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=second_key, Body=WEBP_BYTES)

    _refuse_first_object_delete(monkeypatch)
    confirmed = _confirm(AVERY, payment_method_id, second_key, key="cfm-2", version=2)

    assert confirmed["qrCodeS3Key"] == second_key
    assert _payment_row(units_table, "wise")["pendingQrPurgeKeys"] == {first_key}
    assert sorted(_keys(s3_bucket)) == sorted([first_key, second_key])

    deleted = _delete(AVERY, payment_method_id, key="qr-delete-1", version=3)

    assert deleted["qrCodeS3Key"] is None
    assert _keys(s3_bucket) == []
    assert "pendingQrPurgeKeys" not in _payment_row(units_table, "wise")


def test_the_image_being_attached_is_never_debt_the_ledger_owes(units_table: Any, s3_bucket: Any) -> None:
    """A retry ledger naming the object this write attaches is not a deletion list."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id = _create(AVERY)
    requested = _request(AVERY, payment_method_id)
    s3_key = str(requested["s3Key"])
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=s3_key, Body=PNG_BYTES)
    units_table.update_item(
        Key={"pk": PACK_PK, "sk": "PAYMENT#wise"},
        UpdateExpression="SET #pending = :keys",
        ExpressionAttributeNames={"#pending": "pendingQrPurgeKeys"},
        ExpressionAttributeValues={":keys": {s3_key}},
    )

    assert _confirm(AVERY, payment_method_id, s3_key)["qrCodeS3Key"] == s3_key
    assert _keys(s3_bucket) == [s3_key]
    assert "pendingQrPurgeKeys" not in _payment_row(units_table, "wise")


def test_a_rename_carries_the_cleanup_ledger_to_the_new_key(units_table: Any, s3_bucket: Any) -> None:
    """The debt belongs to the method, and a rename moves the method, not the debt."""
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id, orphan = _attach_qr(units_table, s3_bucket)
    units_table.update_item(
        Key={"pk": PACK_PK, "sk": "PAYMENT#wise"},
        UpdateExpression="SET #pending = :keys",
        ExpressionAttributeNames={"#pending": "pendingQrPurgeKeys"},
        ExpressionAttributeValues={":keys": {orphan}},
    )

    renamed = _rename(AVERY, payment_method_id, "Wave pay", key="rename-1", version=2)

    assert renamed["displayName"] == "Wave pay"
    assert _payment_row(units_table, "wave pay")["pendingQrPurgeKeys"] == {orphan}
    assert _keys(s3_bucket) == [orphan]


# --- what decides when two QR writes race ------------------------------------------


def _markers_for(units_table: Any, operation: str, *, key: Optional[str] = None) -> List[Dict[str, Any]]:
    """The markers one operation type wrote, whatever else the test seeded.

    ``key`` narrows further to one idempotency key, which is the whole point of a
    twin: the loser must leave no marker of its own behind, so the winner's is the
    only one at that address.
    """
    return [
        row
        for row in units_table.scan()["Items"]
        if str(row["pk"]).startswith("IDEM#")
        and f"#{operation}#" in str(row["pk"])
        and (key is None or str(row["sk"]).endswith(f"#{key}"))
    ]


def _twin_commits_in_the_write_window(monkeypatch: pytest.MonkeyPatch, twin: Callable[[], Any]) -> None:
    """Let an identical concurrent request commit inside one handler's own write window.

    The same device as in ``test_unit_payment_methods``: a real twin arrives on a
    second connection at an unknowable moment, so it is forced at the marker read —
    the handler's replay check is the first read, ``execute`` is the second.
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


@pytest.mark.parametrize("operation", ["request", "confirm", "delete"])
def test_a_qr_twin_that_committed_first_answers_its_own_write(
    units_table: Any, s3_bucket: Any, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """The loser of a QR twin replays the twin's answer and touches no object.

    Each of these three handlers mints its own object name or plan before the
    transaction runs. Answering from those after a twin committed would name an
    upload target no marker holds, or re-attach an image the twin's ledger says
    is gone — and the object deletes this attempt skipped belong to the write
    whose ledger is now stored.
    """
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id, first_key = _attach_qr(units_table, s3_bucket)
    twin_key = QR_TWIN_IDEMPOTENCY_KEYS[operation]

    if operation == "request":

        def attempt() -> Any:
            return _request(
                AVERY, payment_method_id, key=twin_key, content_type="image/webp", body=WEBP_BYTES
            )

    elif operation == "confirm":
        requested = _request(AVERY, payment_method_id, key="qr-req-2", content_type="image/webp", body=WEBP_BYTES)
        second_key = str(requested["s3Key"])
        s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=second_key, Body=WEBP_BYTES)

        def attempt() -> Any:
            return _confirm(AVERY, payment_method_id, second_key, key=twin_key, version=2)

    else:

        def attempt() -> Any:
            return _delete(AVERY, payment_method_id, key=twin_key, version=2)

    _twin_commits_in_the_write_window(monkeypatch, attempt)
    answered = attempt()

    assert isinstance(answered, dict) and "__isError" not in answered, answered
    markers = _markers_for(units_table, QR_FIELDS_BY_OPERATION[operation], key=twin_key)
    assert len(markers) == 1
    if operation == "request":
        assert answered["s3Key"] == markers[0]["resultId"]
        assert unit_qr_key_is_mine(str(answered["s3Key"]), PACK_ID, payment_method_id)
        assert answered["s3Key"] != first_key
        assert _keys(s3_bucket) == [first_key]
    else:
        expected_reference = None if operation == "delete" else second_key
        assert answered["qrCodeS3Key"] == expected_reference
        assert answered["version"] == 3
        assert _payment_row(units_table, "wise")["version"] == 3
        assert markers[0]["resultId"] == payment_method_id
        assert _keys(s3_bucket) == ([] if operation == "delete" else [second_key])


def test_a_cleanup_ledger_that_cannot_be_cleared_is_paid_by_the_next_write(
    units_table: Any, s3_bucket: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lost ledger clear costs a repeat of free deletes, never an orphan.

    The objects this write retired are already gone when the clear fails, so the
    record that stays behind names objects that may not exist. The next write
    retries them — ``DeleteObject`` on a missing key succeeds — and clears it then.
    """
    _seed(units_table, PACK_ID, [AVERY])
    payment_method_id, first_key = _attach_qr(units_table, s3_bucket)
    requested = _request(AVERY, payment_method_id, key="qr-req-2", content_type="image/webp", body=WEBP_BYTES)
    second_key = str(requested["s3Key"])
    s3_bucket.put_object(Bucket=os.environ["EXPORTS_BUCKET"], Key=second_key, Body=WEBP_BYTES)

    real_update = unit_operations.tables.units.update_item
    state = {"refused": False}

    def fail_once(**kwargs: Any) -> Any:
        """Refuse the clear's own write once, as a service fault rather than a race.

        Only once, and by the wrapper turning itself off: the retry this test is
        about has to reach the real table, and ``monkeypatch.undo()`` would unwind
        the test's whole AWS environment with it.
        """
        if not state["refused"] and "REMOVE #pending" in str(kwargs.get("UpdateExpression", "")):
            state["refused"] = True
            raise ClientError({"Error": {"Code": "ServiceUnavailable"}}, "UpdateItem")
        return real_update(**kwargs)

    monkeypatch.setattr(unit_operations.tables.units, "update_item", fail_once)
    confirmed = _confirm(AVERY, payment_method_id, second_key, key="qr-cfm-2", version=2)

    assert confirmed["qrCodeS3Key"] == second_key
    assert _keys(s3_bucket) == [second_key]
    assert _payment_row(units_table, "wise")["pendingQrPurgeKeys"] == {first_key}

    deleted = _delete(AVERY, payment_method_id, key="qr-del-1", version=3)

    assert deleted["qrCodeS3Key"] is None
    assert _keys(s3_bucket) == []
    assert "pendingQrPurgeKeys" not in _payment_row(units_table, "wise")


# --- what S3 answers when the object cannot be read --------------------------------


class _HeadRefuses:
    """An S3 client whose HeadObject always answers with one service code."""

    def __init__(self, code: str) -> None:
        self.code = code

    def head_object(self, **_kwargs: Any) -> Dict[str, Any]:
        raise ClientError({"Error": {"Code": self.code}}, "HeadObject")


@pytest.mark.parametrize(
    "code,expected",
    [
        ("403", ErrorCode.FORBIDDEN),
        ("AccessDenied", ErrorCode.FORBIDDEN),
        ("404", ErrorCode.NOT_FOUND),
        ("NoSuchKey", ErrorCode.NOT_FOUND),
    ],
)
def test_a_read_s3_refuses_is_never_reported_as_a_missing_upload(
    monkeypatch: Any, code: str, expected: ErrorCode
) -> None:
    """Without the bucket-level ListBucket grant, S3 answers a missing key with 403.

    That is an infrastructure fault and must never be shown to a Scout as "upload
    not found", and a real denial must never be papered over either: the two
    answers are decided by the code S3 actually sent.
    """
    monkeypatch.setattr(qr_objects, "get_s3_client", lambda: _HeadRefuses(code))

    with pytest.raises(AppError) as raised:
        qr_objects.validate_uploaded_qr_object("test-exports-bucket", "payment-qr-codes/units/u/p/x.png", _digest(PNG_BYTES))
    assert raised.value.error_code == expected


def test_an_unexpected_s3_answer_is_not_swallowed(monkeypatch: Any) -> None:
    """A service fault that is neither a missing key nor a denial stays a fault."""
    monkeypatch.setattr(qr_objects, "get_s3_client", lambda: _HeadRefuses("ThrottlingException"))

    with pytest.raises(ClientError):
        qr_objects.validate_uploaded_qr_object("test-exports-bucket", "payment-qr-codes/units/u/p/x.png", _digest(PNG_BYTES))


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
