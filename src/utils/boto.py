"""
Centralized boto3 client factories with endpoint-override validation (#523, #575).

The single construction path for the S3, admin-Cognito, and low-level DynamoDB
clients, so retry/botocore config or endpoint handling changes once, in one
reviewed place. Endpoint overrides (S3_ENDPOINT, COGNITO_ENDPOINT,
DYNAMODB_ENDPOINT) are validated here rather than at each call site: a set
value must be an http(s) URL whose host is loopback or in a private range,
because an unvalidated override silently redirects SigV4-signed requests —
and the Lambda's own credentials — to whatever host it names.

The pre-token-generation trigger builds its Cognito client once at module scope
on purpose (warm-start connection reuse, #458), and the account-deletion and
pre-signup handlers construct their own per-call Cognito clients, so those
three sites are not routed through here.
"""

import ipaddress
import os
from typing import TYPE_CHECKING, Any, Optional, cast
from urllib.parse import urlparse

import boto3

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_s3.client import S3Client

# RFC 1918 private ranges, the addresses LocalStack or an internal emulator can
# be reached on. Loopback (127.0.0.0/8, ::1) is checked via ``is_loopback``.
_PRIVATE_NETWORKS = (ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"), ipaddress.ip_network("192.168.0.0/16"))
_LOCAL_HOSTNAMES = ("localhost", "localstack")


def _is_local_endpoint_host(host: str) -> bool:
    """Return True when ``host`` is a loopback address or a private-range host.

    Accepts the RFC 1918 ranges plus the ``localhost``/``localstack`` hostnames
    so a LocalStack container name also resolves.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host.lower() in _LOCAL_HOSTNAMES
    return address.is_loopback or any(address in network for network in _PRIVATE_NETWORKS)


def validated_endpoint_override(env_name: str) -> Optional[str]:
    """Read a service endpoint override from the environment and validate it.

    Args:
        env_name: Name of the environment variable holding the override

    Returns:
        The override value, or None when the variable is unset

    Raises:
        ValueError: If the variable is set but is not an http(s) URL with a host,
            or its host is not a loopback/private address
    """
    value = os.getenv(env_name)
    if value is None:
        return None
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if parsed.scheme not in ("http", "https") or not host:
        raise ValueError(f"Invalid {env_name} '{value}': must be an http(s) URL with a host")
    if not _is_local_endpoint_host(host):
        raise ValueError(
            f"Invalid {env_name} '{value}': endpoint host '{host}' is not a loopback or private address; "
            "endpoint overrides are only for a local emulator"
        )
    return value


def get_cognito_client() -> Any:
    """Get a Cognito IDP client, honoring the COGNITO_ENDPOINT override."""
    return boto3.client("cognito-idp", endpoint_url=validated_endpoint_override("COGNITO_ENDPOINT"))


def get_dynamodb_client() -> Any:
    """Get a low-level DynamoDB client, honoring the DYNAMODB_ENDPOINT override."""
    return boto3.client("dynamodb", endpoint_url=validated_endpoint_override("DYNAMODB_ENDPOINT"))


def get_s3_client(override: Any = None) -> "S3Client":
    """Get an S3 client, honoring the S3_ENDPOINT override.

    Args:
        override: Test slot — when set, returned as-is instead of
            constructing a real client

    Returns:
        The override when provided, otherwise a boto3 S3 client
    """
    if override is not None:
        return cast("S3Client", override)
    return boto3.client("s3", endpoint_url=validated_endpoint_override("S3_ENDPOINT"))
