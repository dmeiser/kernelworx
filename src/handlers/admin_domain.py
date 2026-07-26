"""
Admin Domain Lambda Handler
Handles admin user search, admin user list rendering, and user data inspection.
"""

from typing import Any, Dict

try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.templates import render_template
except ModuleNotFoundError:  # pragma: no cover
    from src.utils.dynamodb import tables
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


def render_admin_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render system admin dashboard page."""
    html = render_template("pages/admin.html", {"users": [], "is_authenticated": True, "is_admin": True})
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def api_admin_search_users_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Search users for admin dashboard."""
    query_params = event.get("queryStringParameters") or {}
    query = query_params.get("query", "")

    # Scan accounts table for matching query
    res = tables.accounts.scan()
    items = res.get("Items", [])
    matching = [i for i in items if query.lower() in str(i).lower()] if query else items

    html = render_template(
        "pages/admin.html",
        {"users": matching, "query": query, "is_authenticated": True, "is_admin": True},
    )
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def render_admin_user_data_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render admin user data explorer page."""
    path_params = event.get("pathParameters") or {}
    account_id = path_params.get("accountId", "ACCOUNT#test")

    # Fetch the account record (if present) so we can display email/name/dates.
    account: Dict[str, Any] = {}
    try:
        acct_res = tables.accounts.get_item(Key={"accountId": account_id})
        account = acct_res.get("Item", {}) or {}
    except Exception:  # pragma: no cover - defensive: moto may have no such item
        account = {}

    # Fetch profiles owned by this account (PK == accountId, SK begins with PROFILE#).
    try:
        res = tables.profiles.query(KeyConditionExpression="PK = :pk", ExpressionAttributeValues={":pk": account_id})
        profiles = res.get("Items", [])
    except Exception:  # pragma: no cover - defensive: query may fail on mocked tables
        profiles = []

    html = render_template(
        "pages/admin_user_data.html",
        {
            "account_id": account_id,
            "account": account,
            "profiles": profiles,
            "is_authenticated": True,
            "is_admin": True,
        },
    )
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway proxy entrypoint for the admin domain."""
    from urllib.parse import unquote

    method = event.get("httpMethod", "GET")
    path = event.get("path") or "/"
    if path == "/admin" and method == "GET":
        return render_admin_handler(event, context)
    if path == "/api/admin/search-users" and method == "GET":
        return api_admin_search_users_handler(event, context)
    if path.startswith("/admin/user-data/") and method == "GET":
        event["pathParameters"] = {"accountId": unquote(path[len("/admin/user-data/") :])}
        return render_admin_user_data_handler(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
