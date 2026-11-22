"""The shared QR-object contract for the exports bucket (checklist §4.1.2, #559).

Every QR image the application stores — an account's own payment-method QR or a
Unit payment method's shared QR — arrives by a browser POST to a pre-signed
form, and S3 validates only the form field that declares the content type. So
the confirm step is the one place that can learn what the bytes actually are,
and it has to decide the same way for every writer: the object must exist, it
must fit the size the pre-signed POST already promised, its magic numbers must
match the format its own key extension claims — a JPEG stored as ``.png`` would
otherwise be served under an ``image/png`` URL (#559) — and its SHA-256 must be
the digest its key names. A rejected object is purged before the error is
raised, so a bad upload cannot linger in the first-party bucket.

What the bytes proved to be are then written a SECOND time, under a name the
browser was never given. That is the half that keeps a served image from moving
under a reader: a pre-signed POST stays usable for its whole window and S3 has no
way to bind it to a request that already finished, so the object a browser can
write is never the object a row references. See
``src/utils/unit_payment_models.py`` for the two-key layout that states this.

This module is the single source for those rules and for the pre-signed POST
and GET builders. It deliberately reads no DynamoDB table: the QR object layer
is not an authorization mechanism (every caller checks its own grant first and
prefix-scopes the key it signs), and a handler that reached a table through
here would carry an IAM grant the QR path must not have.
"""

from __future__ import annotations

import hashlib
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

# S3 answers a HeadObject for a key the caller has no grant on with 403, and —
# without the bucket-level ListBucket that lets it prove a key is simply absent —
# it answers a missing key that way too. Only a real denial is here, so a missing
# upload can never be reported as one, and a denial can never be papered over as
# "upload not found".
_DENIED_OBJECT_CODES = frozenset({"403", "AccessDenied", "AccessDeniedException"})


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


_QR_EXTENSION_BY_CONTENT_TYPE: Dict[str, str] = {
    content_type: extension for content_type, extension in QR_CONTENT_TYPES.items()
}


def qr_key_extension(s3_key: str) -> str:
    """The stored extension one QR object name carries, in the minted spelling.

    An attachment published from an upload target keeps that target's extension,
    so a key minted ``.jpg`` never turns into ``.jpeg`` on the way in: the
    magic-number check, the served content type, and the stored name then all
    speak the same format. A key whose extension is not one this API mints raises
    through :func:`content_type_for_qr_key` rather than returning a guess.
    """
    return _QR_EXTENSION_BY_CONTENT_TYPE[content_type_for_qr_key(s3_key)]


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
    wrote keeps validating after the request path settled on ``jpg``.
    """
    extension = s3_key.rsplit("/", 1)[-1].rpartition(".")[2]
    validator = _IMAGE_VALIDATORS_BY_EXTENSION.get(extension)
    return validator is not None and validator(body)


def qr_object_bytes(s3_client: S3Client, bucket: str, s3_key: str) -> bytes:
    """The object's bytes, read once so the magic numbers and the digest agree.

    The caller has already bounded the size with a HEAD, and one read means the
    format check and the digest check describe the same object rather than two
    snapshots of it.
    """
    return bytes(s3_client.get_object(Bucket=bucket, Key=s3_key)["Body"].read())


def validate_uploaded_qr_object(bucket: str, s3_key: str, expected_digest: str) -> bytes:
    """Validate what the browser actually uploaded, purging it when it is bad.

    Three things have to be true of the object before a row may be built from it:
    it exists, it is the image its own key extension claims, and its SHA-256 is
    the digest the key names. The last two are decided from ONE read of the body,
    which is also the body the caller publishes under the attachment key — so the
    bytes a reference ends up holding are the bytes that passed, with no second
    snapshot in between. A rejected object is deleted before the error, so a bad
    upload cannot linger in the first-party bucket.

    Returns:
        The object's bytes, already proven to be the ``expected_digest`` bytes.

    Raises:
        AppError: NOT_FOUND when the object is missing — the browser has not
            uploaded yet, or the pre-signed window expired before confirm;
            FORBIDDEN when S3 refused the read and a scoped listing proves the
            key is really there (a missing grant is an infrastructure fault,
            never a missing upload); INVALID_INPUT when the object is over the
            cap, is not the image its key claims, or is not the bytes that key
            names.
    """
    log = get_logger(__name__)
    s3_client = get_s3_client()
    try:
        head = s3_client.head_object(Bucket=bucket, Key=s3_key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in _MISSING_OBJECT_CODES:
            raise AppError(ErrorCode.NOT_FOUND, "Upload not found. Please upload the file first.") from exc
        if code in _DENIED_OBJECT_CODES:
            raise _refused_read(s3_client, bucket, s3_key, exc, log) from exc
        raise

    content_length = int(head.get("ContentLength", 0) or 0)
    if content_length > MAX_QR_BYTES:
        _purge_rejected(s3_client, bucket, s3_key, log, content_length)
        raise AppError(ErrorCode.INVALID_INPUT, f"QR image is larger than {MAX_QR_BYTES // (1024 * 1024)} MB")
    body = qr_object_bytes(s3_client, bucket, s3_key)
    if not image_magic_matches_key(body, s3_key):
        _purge_rejected(s3_client, bucket, s3_key, log, content_length)
        raise AppError(ErrorCode.INVALID_INPUT, "Uploaded file is not a valid image")
    if hashlib.sha256(body).hexdigest() != expected_digest:
        _purge_rejected(s3_client, bucket, s3_key, log, content_length)
        raise AppError(ErrorCode.INVALID_INPUT, "Uploaded file does not match the upload request")
    return body


def _refused_read(s3_client: S3Client, bucket: str, s3_key: str, refused: ClientError, log: Any) -> AppError:
    """Decide a HeadObject denial: a key that is not there, or a read that is denied.

    A HeadObject answer of 403 is ambiguous by construction. S3 documents that it
    refuses — rather than answering 404 — a read of a key the caller has no grant
    on, and this role's only bucket-level grant is a ``ListBucket`` conditional on
    an ``s3:prefix`` the HeadObject request itself cannot carry, so a key that is
    simply absent can answer 403 here too. Guessing either way is wrong half the
    time: "upload not found" blames a Scout who uploaded fine, and "access denied"
    blames infrastructure when the object never arrived.

    So the ambiguity is resolved with a request this role provably can make: a
    listing scoped to the exact key. If the key appears in it, the read really was
    denied and that is FORBIDDEN; if it does not, the object is absent and that is
    the same NOT_FOUND the browser would have been given. A listing this role is
    refused as well leaves the question unanswerable, and the answer then stays
    the denial it arrived as.
    """
    try:
        listed = s3_client.list_objects_v2(Bucket=bucket, Prefix=s3_key, MaxKeys=1)
    except ClientError as exc:
        log.warning("QR object listing refused; reporting the denial", s3_key=s3_key, error=str(exc))
        return AppError(ErrorCode.FORBIDDEN, "The uploaded QR image could not be read.")
    contents = listed.get("Contents") or []
    if any(str(entry.get("Key", "")) == s3_key for entry in contents):
        return AppError(ErrorCode.FORBIDDEN, "The uploaded QR image could not be read.")
    log.warning("HeadObject denied the read and the scoped listing shows no such key", s3_key=s3_key)
    return AppError(ErrorCode.NOT_FOUND, "Upload not found. Please upload the file first.")


def _purge_rejected(s3_client: S3Client, bucket: str, s3_key: str, log: Any, content_length: int) -> None:
    """Delete an object that failed validation so it cannot linger in the bucket."""
    log.warning("Rejected QR upload purged from the exports bucket", s3_key=s3_key, content_length=content_length)
    s3_client.delete_object(Bucket=bucket, Key=s3_key)


def publish_qr_attachment(bucket: str, s3_key: str, body: bytes, content_type: str) -> None:
    """Write the validated bytes under the key the row is about to reference.

    This is the step that makes the stored reference serve immutable bytes. The
    upload object is mutable for as long as its pre-signed POST is valid — anyone
    holding those credentials can POST again — so it is never what the row points
    at. The name published here is minted by the handler, is never handed to a
    browser, and holds the exact bytes this call just proved, so no POST can
    change what an existing attachment serves.

    Raises:
        AppError: INTERNAL_ERROR is the caller's verdict if S3 refuses the write;
            nothing is committed on a failure, and the caller purges the orphan.
    """
    get_s3_client().put_object(Bucket=bucket, Key=s3_key, Body=body, ContentType=content_type)


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

    The signature also pins the response's ``Content-Disposition`` to an
    attachment naming the object's own name, because that parameter is part of
    the signed URL: a URL whose signature covers it cannot be edited into a bare
    image GET, and any client that reaches the object directly — a paste into a
    new tab, a save-from-menu — gets a file rather than a rendered image. The
    browser control does its own blob download on top of this, since the HTML
    ``download`` attribute is ignored cross-origin.
    """
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=QR_DOWNLOAD_TTL_SECONDS)
    params = {
        "Bucket": bucket,
        "Key": s3_key,
        "ResponseContentDisposition": f'attachment; filename="{s3_key.rsplit("/", 1)[-1]}"',
    }
    url = get_s3_client().generate_presigned_url("get_object", Params=params, ExpiresIn=QR_DOWNLOAD_TTL_SECONDS)
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
