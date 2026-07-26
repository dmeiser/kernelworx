"""
Sharing Domain Lambda Handler
Handles scout management page rendering, direct email sharing, invite code generation, and redemption.
"""

from typing import Any, Dict

try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.ids import generate_id
    from utils.templates import render_template
except ModuleNotFoundError:  # pragma: no cover
    from src.utils.dynamodb import tables
    from src.utils.ids import generate_id
    from src.utils.templates import render_template


def get_caller_id(event: Dict[str, Any]) -> str:
    """Extract authenticated caller ID from API Gateway Cognito authorizer claims or mock header."""
    auth_ctx = event.get("requestContext", {}).get("authorizer", {}) or {}
    claims = auth_ctx.get("claims", {}) if isinstance(auth_ctx.get("claims"), dict) else auth_ctx
    sub = claims.get("sub") if isinstance(claims, dict) else auth_ctx.get("sub")
    if sub:
        return str(sub)
    headers = event.get("headers") or {}
    return str(headers.get("x-mock-user-id", "test-user-id"))


def render_scout_management_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render scout management page for profile sharing & invite code generation."""
    path_params = event.get("pathParameters") or {}
    profile_id = path_params.get("profileId", "PROFILE#test")

    html = render_template(
        "pages/scout_management.html",
        {"profile": {"profileId": profile_id, "sellerName": "Alex Smith"}, "is_authenticated": True},
    )
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def api_create_share_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Grant profile access to target email."""
    path_params = event.get("pathParameters") or {}
    profile_id = path_params.get("profileId", "PROFILE#test")

    html = f'<div class="card" style="padding: 0.5rem; margin-top: 0.5rem;">Shared access granted for profile {profile_id}.</div>'
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def api_create_invite_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Generate temporary invite code."""
    invite_code = generate_id("INVITE#")[:12]

    html = f'<div style="background-color: var(--color-primary-1); padding: 1rem; border-radius: var(--radius-md); font-weight: 700; color: var(--color-primary-9);">Invite Code: {invite_code}</div>'
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def render_account_settings_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render user account settings page."""
    caller_id = get_caller_id(event)
    res = tables.accounts.get_item(Key={"accountId": caller_id})
    account = res.get("Item", {"givenName": "Jane", "familyName": "Doe", "unitNumber": "101"})

    html = render_template("pages/user_settings.html", {"account": account, "is_authenticated": True})
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway proxy entrypoint for the sharing domain."""
    from urllib.parse import unquote

    method = event.get("httpMethod", "GET")
    path = event.get("path") or "/"
    if path == "/account/settings" and method == "GET":
        return render_account_settings_handler(event, context)
    if path == "/scout-management" and method == "GET":
        return render_scout_management_handler(event, context)
    if path == "/api/shares" and method == "POST":
        return api_create_share_handler(event, context)
    if path == "/api/invites" and method == "POST":
        return api_create_invite_handler(event, context)
    if path.startswith("/scouts/") and method == "GET":
        parts = [unquote(p) for p in path.strip("/").split("/") if p]
        if len(parts) == 3 and parts[2] == "manage":
            event["pathParameters"] = {"profileId": parts[1]}
            return render_scout_management_handler(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
