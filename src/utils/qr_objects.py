"""The shared QR-object contract for the exports bucket (checklist §4.1.2, #559).

Every QR image the application stores — an account's own payment-method QR or a
Unit payment method's shared QR — arrives by a browser POST to a pre-signed
form, and S3 validates only the form field that declares the content type. So
the confirm step is the one place that can learn what the bytes actually are,
and it has to decide the same way for every writer: the object must exist, it
must fit the size the pre-signed POST already promised, and its magic numbers
must match the format its own key extension claims — a JPEG stored as ``.png``
would otherwise be served under an ``image/png`` URL (#559). A rejected object
is purged before the error is raised, so a bad upload cannot linger in the
first-party bucket.

This module is the single source for those rules and for the pre-signed POST
and GET builders. It deliberately reads no DynamoDB table: the QR object layer
is not an authorization mechanism (every caller checks its own grant first and
prefix-scopes the key it signs), and a handler that reached a table through
here would carry an IAM grant the QR path must not have.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict

from botocore.exceptions import ClientError

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_s3 import S3Client

from .boto import get_s3_client
from .errors import AppError, ErrorCode
from .logging import get_logger

# The upload cap the pre-signed POST pins and the confirm step re-checks.
MAX_QR_BYTES = 5 * 1024 * 1024

# The content types an upload may declare, and the extension each is stored
# under. A declared type outside this map is refused at request time, so the
# magic-number table below is closed over exactly the same set.
QR_CONTENT_TYPES: Dict[str, str] = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}

# A pre-signed POST is handed to a browser to complete, so it gets the same
# 15-minute window the legacy payment-method upload has always used.
QR_UPLOAD_TTL_SECONDS = 900

# A QR image is embedded in a screen or a printable sheet, so the GET window is
# the same short-lived one: it is never a durable share link.
QR_DOWNLOAD_TTL_SECONDS = 900

# The head-object answers that mean "this key is not here".
_MISSING_OBJECT_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


def qr_extension_for_content_type(content_type: Any) -> str:
    """The stored extension for a declared content type, else INVALID_INPUT."""
    extension = QR_CONTENT_TYPES.get(content_type.strip().lower()) if isinstance(content_type, str) else None
    if extension is None:
        raise AppError(ErrorCode.INVALID_INPUT, "QR images must be one of: " + ", ".join(sorted(QR_CONTENT_TYPES)))
    return extension


def content_type_for_qr_key(s3_key: str) -> str:
    """The content type a stored object name declares, for the pre-signed POST.

    The extension is decided once, when the upload target is minted, so the POST
    a browser uses declares exactly the type that object will be checked against.
    """
    extension = s3_key.rsplit("/", 1)[-1].rpartition(".")[2]
    for content_type, mapped in QR_CONTENT_TYPES.items():
        if mapped == extension:
            return content_type
    raise AppError(ErrorCode.INVALID_INPUT, "QR image key has an unknown extension")


def _is_png(body: bytes) -> bool:
    """True for a PNG signature."""
    return body.startswith(b"\x89PNG\r\n\x1a\n")


def _is_jpeg(body: bytes) -> bool:
    """True for a JPEG SOI marker."""
    return body.startswith(b"\xff\xd8\xff")


def _is_webp(body: bytes) -> bool:
    """True for a RIFF container whose form type is WEBP."""
    return body.startswith(b"RIFF") and body[8:12] == b"WEBP"


_IMAGE_VALIDATORS_BY_EXTENSION: Dict[str, Any] = {"png": _is_png, "jpg": _is_jpeg, "jpeg": _is_jpeg, "webp": _is_webp}


def image_magic_matches_key(body: bytes, s3_key: str) -> bool:
    """True when the bytes carry the magic numbers of the key's own extension.

    ``jpg`` and ``jpeg`` both name the JPEG format, so a key an older upload
    wrote keeps validating after the request path standardised on ``jpg``.
    """
    extension = s3_key.rsplit("/", 1)[-1].rpartition(".")[2]
    validator = _IMAGE_VALIDATORS_BY_EXTENSION.get(extension)
    return validator is not None and validator(body)


def qr_object_is_permitted_image(s3_client: S3Client, bucket: str, s3_key: str, content_length: int) -> bool:
    """Check the object's leading bytes against the format its key claims.

    Only the first 12 bytes are read (the WEBP form type sits at offset 8), so
    the check stays a fixed-cost peek regardless of how large the object is.
    """
    if content_length == 0:
        return False
    response = s3_client.get_object(Bucket=bucket, Key=s3_key, Range="bytes=0-11")
    return image_magic_matches_key(response["Body"].read(), s3_key)


def validate_uploaded_qr_object(bucket: str, s3_key: str) -> None:
    """Validate what the browser actually uploaded, purging it when it is bad.

    Raises:
        AppError: NOT_FOUND when the object is missing — the browser has not
            uploaded yet, or the pre-signed window expired before confirm;
            INVALID_INPUT when the object is over the cap or is not the image
            its key claims. A rejected object is deleted before that error.
    """
    log = get_logger(__name__)
    s3_client = get_s3_client()
    try:
        head = s3_client.head_object(Bucket=bucket, Key=s3_key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in _MISSING_OBJECT_CODES:
            raise AppError(ErrorCode.NOT_FOUND, "Upload not found. Please upload the file first.") from exc
        raise

    content_length = int(head.get("ContentLength", 0) or 0)
    if content_length > MAX_QR_BYTES:
        _purge_rejected(s3_client, bucket, s3_key, log, content_length)
        raise AppError(ErrorCode.INVALID_INPUT, f"QR image is larger than {MAX_QR_BYTES // (1024 * 1024)} MB")
    if not qr_object_is_permitted_image(s3_client, bucket, s3_key, content_length):
        _purge_rejected(s3_client, bucket, s3_key, log, content_length)
        raise AppError(ErrorCode.INVALID_INPUT, "Uploaded file is not a valid image")


def _purge_rejected(s3_client: S3Client, bucket: str, s3_key: str, log: Any, content_length: int) -> None:
    """Delete an object that failed validation so it cannot linger in the bucket."""
    log.warning("Rejected QR upload purged from the exports bucket", s3_key=s3_key, content_length=content_length)
    s3_client.delete_object(Bucket=bucket, Key=s3_key)


def presigned_qr_upload(bucket: str, s3_key: str, content_type: str) -> Dict[str, Any]:
    """The pre-signed POST the browser uploads one QR image with.

    The POST pins the declared content type and the size range, so an object
    that reaches confirm has already been held to both — confirm still reads the
    bytes, because S3 never inspects them.
    """
    post = get_s3_client().generate_presigned_post(
        Bucket=bucket,
        Key=s3_key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, MAX_QR_BYTES],
        ],
        ExpiresIn=QR_UPLOAD_TTL_SECONDS,
    )
    return {"uploadUrl": post["url"], "fields": post["fields"], "s3Key": s3_key}


def presigned_qr_download(bucket: str, s3_key: str) -> Dict[str, str]:
    """A short-lived pre-signed GET URL for one QR object, with its expiry.

    ``expiresAt`` rides with the URL so a screen can say when the image stops
    loading instead of showing a broken image for no stated reason.
    """
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=QR_DOWNLOAD_TTL_SECONDS)
    url = get_s3_client().generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": s3_key}, ExpiresIn=QR_DOWNLOAD_TTL_SECONDS
    )
    return {"downloadUrl": url, "expiresAt": expires_at.isoformat()}


def delete_qr_object(bucket: str, s3_key: str) -> bool:
    """Delete one QR object, reporting whether S3 accepted the delete.

    Callers use this only after the DynamoDB reference is already gone, so an
    accepted delete is the whole job and a refused one is an orphan to log —
    never a reason to undo the committed write.
    """
    log = get_logger(__name__)
    try:
        get_s3_client().delete_object(Bucket=bucket, Key=s3_key)
    except ClientError as exc:
        log.warning("QR object delete failed", s3_key=s3_key, error=str(exc))
        return False
    return True
