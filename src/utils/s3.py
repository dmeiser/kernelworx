"""Shared S3 helpers for Lambda handlers.

Provides the single retry-aware prefix purge used by both the profile cascade
(report cleanup) and the account-deletion cascade (payment QR cleanup), so a
transient S3 throttle is retried identically on both paths.
"""

import time
from typing import Any

from botocore.exceptions import ClientError
from botocore.exceptions import ConnectionError as BotoConnectionError

try:  # pragma: no cover
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.logging import get_logger

_logger = get_logger(__name__)

# S3 prefix purge retries: bounded attempts with exponential backoff for
# transient errors only (throttling, timeouts, 5xx). Non-transient failures
# (AccessDenied, NoSuchBucket, validation) fail immediately.
S3_MAX_ATTEMPTS = 3
S3_RETRY_BASE_DELAY_SECONDS = 0.5
S3_TRANSIENT_ERROR_CODES = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "RequestTimeout",
        "RequestTimeoutException",
        "SlowDown",
        "InternalError",
        "ServiceUnavailable",
    }
)


def is_transient_s3_error(exc: Exception) -> bool:
    """Classify S3 errors: throttling, timeouts, and 5xx responses are transient."""
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in S3_TRANSIENT_ERROR_CODES:
            return True
        http_status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return isinstance(http_status, int) and http_status >= 500
    return isinstance(exc, BotoConnectionError)


def _delete_s3_prefix(s3_client: Any, bucket: str, prefix: str, log: Any) -> int:
    """Delete all object versions and delete markers under one prefix."""
    deleted_count = 0
    paginator = s3_client.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        delete_items: list[dict[str, str]] = []
        for version in page.get("Versions", []):
            k = version.get("Key")
            vid = version.get("VersionId")
            if k and vid:
                delete_items.append({"Key": k, "VersionId": vid})
        for marker in page.get("DeleteMarkers", []):
            k = marker.get("Key")
            vid = marker.get("VersionId")
            if k and vid:
                delete_items.append({"Key": k, "VersionId": vid})
        if delete_items:
            s3_client.delete_objects(Bucket=bucket, Delete={"Objects": delete_items})
            deleted_count += len(delete_items)
            log.info(f"Deleted {len(delete_items)} object versions from S3 under {prefix}")
    return deleted_count


def purge_s3_prefix(s3_client: Any, bucket: str, prefix: str, *, logger: Any = None) -> int:
    """Delete every object version and delete marker under `prefix`. Retries transient S3 errors.

    A retry restarts the prefix listing; already-deleted versions no longer
    appear, so the scan is idempotent.
    """
    log = logger if logger is not None else _logger
    for attempt in range(1, S3_MAX_ATTEMPTS + 1):
        try:
            return _delete_s3_prefix(s3_client, bucket, prefix, log)
        except Exception as e:
            if not is_transient_s3_error(e):
                raise
            if attempt >= S3_MAX_ATTEMPTS:
                log.error(
                    f"Transient S3 error deleting objects under {prefix} persisted after {attempt} attempts: {str(e)}"
                )
                raise
            delay = S3_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            log.warning(
                f"Transient S3 error deleting objects under {prefix} "
                f"(attempt {attempt}/{S3_MAX_ATTEMPTS}): {str(e)}. Retrying in {delay:.1f}s"
            )
            time.sleep(delay)
    return 0  # pragma: no cover - the loop always returns or raises
