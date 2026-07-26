"""
API Gateway custom request authorizer.

Validates a Cognito access token from either the Authorization header or the
kw_access_token cookie. On success it returns an allow policy with the Cognito
sub (UUID) in the authorizer context so backend handlers can identify the caller.
"""

import os
from typing import Any, Dict

import boto3

cognito_client = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _case_insensitive_get(headers: Dict[str, Any], key: str) -> Any:
    """Return a header value using a case-insensitive lookup."""
    if not headers:
        return None
    lowered = key.lower()
    for k, v in headers.items():
        if k.lower() == lowered:
            return v
    return None


def _extract_token(event: Dict[str, Any]) -> str:
    """Extract a Cognito access token from the Authorization header or cookie."""
    headers = event.get("headers") or {}

    auth_header = _case_insensitive_get(headers, "Authorization")
    if auth_header and isinstance(auth_header, str):
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:].strip()
        return auth_header.strip()

    cookie_header = _case_insensitive_get(headers, "Cookie")
    if cookie_header and isinstance(cookie_header, str):
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("kw_access_token="):
                return part[len("kw_access_token=") :].strip()

    return ""


def _deny_policy(method_arn: str) -> Dict[str, Any]:
    return {
        "principalId": "anonymous",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": "Deny",
                    "Resource": method_arn or "*",
                }
            ],
        },
    }


def _allow_policy(method_arn: str, sub: str) -> Dict[str, Any]:
    return {
        "principalId": sub,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": "Allow",
                    "Resource": method_arn or "*",
                }
            ],
        },
        "context": {"sub": sub},
    }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway custom authorizer entrypoint."""
    method_arn = event.get("methodArn") or ""
    token = _extract_token(event)

    if not token:
        return _deny_policy(method_arn)

    try:
        user = cognito_client.get_user(AccessToken=token)
        sub = user.get("Username", "")
        if not sub:
            return _deny_policy(method_arn)
        return _allow_policy(method_arn, sub)
    except Exception:
        return _deny_policy(method_arn)
