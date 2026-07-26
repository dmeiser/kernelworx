"""
API Gateway proxy event parsing helpers.

Shared utilities for handlers that receive the AWS_PROXY event shape from
API Gateway REST integrations (and from the local WSGI test server, which
mirrors that shape). Centralizes caller-id extraction, body parsing, and
response building so domain handlers stay thin.
"""

import json
from typing import Any, Dict, Optional
from urllib.parse import parse_qs

try:  # pragma: no cover
    from utils.errors import AppError, ErrorCode
except ModuleNotFoundError:  # pragma: no cover
    from .errors import AppError, ErrorCode


def get_caller_id(event: Dict[str, Any]) -> str:
    """Extract the authenticated caller's Cognito sub from the proxy event.

    Reads ``requestContext.authorizer.claims.sub`` (API Gateway Cognito
    authorizer) and falls back to the ``x-mock-user-id`` / ``x-test-sub``
    headers used by the local dev/test servers.
    """
    auth_ctx = event.get("requestContext", {}).get("authorizer", {}).get("claims", {}) or {}
    sub = auth_ctx.get("sub")
    if sub:
        return str(sub)
    headers = event.get("headers") or {}
    return str(headers.get("x-mock-user-id") or headers.get("x-test-sub") or "test-user-id")


def get_path_param(event: Dict[str, Any], name: str, default: str = "") -> str:
    """Return a single URL-decoded API Gateway path parameter."""
    return str((event.get("pathParameters") or {}).get(name) or default)


def get_query_param(event: Dict[str, Any], name: str, default: Optional[str] = None) -> Optional[str]:
    """Return a single query string parameter (or ``default``)."""
    return (event.get("queryStringParameters") or {}).get(name, default)


def parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    """Parse a proxy event body into a dict.

    Handles JSON objects, URL-encoded forms, and empty bodies (returns ``{}``).
    Form fields with repeated keys are collapsed to their first value to mirror
    ``parse_qs`` semantics used by the existing domain handlers.
    """
    body = event.get("body") or ""
    if not body:
        return {}
    if body.lstrip().startswith("{"):
        try:
            parsed = json.loads(body)
            return parsed if isinstance(parsed, dict) else {"_raw": parsed}
        except json.JSONDecodeError:
            return {}
    if "=" in body:
        parsed = parse_qs(body, keep_blank_values=True)
        return {k: v[0] if isinstance(v, list) and v else v for k, v in parsed.items()}
    return {}


def get_authorizer_claims(event: Dict[str, Any]) -> Dict[str, Any]:
    """Return the Cognito authorizer claims dict (compatible with utils.auth.is_admin)."""
    return event.get("requestContext", {}).get("authorizer", {}).get("claims", {}) or {}


def is_admin(event: Dict[str, Any]) -> bool:
    """Check whether the caller is in the ADMIN Cognito group.

    Mirrors :func:`utils.auth.is_admin` but reads from the API Gateway proxy
    event shape (``requestContext.authorizer.claims``).
    """
    try:
        claims = event.get("requestContext", {}).get("authorizer", {}).get("claims", {}) or {}
        groups = claims.get("cognito:groups", [])
        if isinstance(groups, str):
            groups = [groups]
        return "ADMIN" in groups
    except Exception:
        return False


def html_response(body: str, status_code: int = 200, extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Build a text/html proxy response."""
    headers = {"Content-Type": "text/html"}
    if extra_headers:
        headers.update(extra_headers)
    return {"statusCode": status_code, "headers": headers, "body": body}


def json_response(
    payload: Any, status_code: int = 200, extra_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Build an application/json proxy response."""
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    return {"statusCode": status_code, "headers": headers, "body": json.dumps(payload, default=str)}


def error_response(error: Exception, status_code: int = 500) -> Dict[str, Any]:
    """Convert an AppError (or generic Exception) into a JSON proxy response."""
    if isinstance(error, AppError):
        status_code = {
            ErrorCode.UNAUTHORIZED: 401,
            ErrorCode.FORBIDDEN: 403,
            ErrorCode.NOT_FOUND: 404,
            ErrorCode.INVALID_INPUT: 400,
            ErrorCode.ALREADY_EXISTS: 409,
        }.get(error.error_code, status_code)
        message = error.message
    else:
        message = str(error)
    return json_response({"error": message}, status_code=status_code)


def redirect_response(location: str) -> Dict[str, Any]:
    """Build a 302 redirect proxy response."""
    return {
        "statusCode": 302,
        "headers": {"Content-Type": "text/html", "Location": location},
        "body": "",
    }
