"""
Centralized boto3 client factories with endpoint-override validation (#523, #575).

The single construction path for the S3, admin-Cognito, and DynamoDB clients,
so retry/botocore config or endpoint handling changes once, in one reviewed
place. Endpoint overrides (S3_ENDPOINT, COGNITO_ENDPOINT, DYNAMODB_ENDPOINT)
are validated here rather than at each call site: a set value must be an
http(s) URL with a host.

The pre-token-generation trigger builds its Cognito client once at module scope
on purpose (warm-start connection reuse, #458), and the account-deletion and
pre-signup handlers construct their own per-call Cognito clients, so those
three sites are not routed through here.
"""

import os
from typing import TYPE_CHECKING, Any, Optional, cast
from urllib.parse import urlparse

import boto3

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_s3.client import S3Client


def validated_endpoint_override(env_name: str) -> Optional[str]:
    """Read a service endpoint override from the environment and validate it.

    Args:
        env_name: Name of the environment variable holding the override

    Returns:
        The override value, or None when the variable is unset

    Raises:
        ValueError: If the variable is set but is not an http(s) URL with a host
    """
    value = os.getenv(env_name)
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid {env_name} '{value}': must be an http(s) URL with a host")
    return value


def get_cognito_client() -> Any:
    """Get a Cognito IDP client, honoring the COGNITO_ENDPOINT override."""
    return boto3.client("cognito-idp", endpoint_url=validated_endpoint_override("COGNITO_ENDPOINT"))


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
