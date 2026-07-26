"""
Catalogs Domain Lambda Handler
Handles rendering user & managed catalogs, catalog preview, and catalog deletion.
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
    auth_ctx = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    sub = auth_ctx.get("sub")
    if sub:
        return str(sub)
    headers = event.get("headers") or {}
    return str(headers.get("x-mock-user-id", "test-user-id"))


def render_catalogs_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render catalogs management page."""
    caller_id = get_caller_id(event)
    catalogs_table = tables.catalogs

    res = catalogs_table.scan()
    items = res.get("Items", [])

    # Split catalogs into "My Catalogs" (owned + in-use managed) and "Managed Catalogs" (ADMIN_MANAGED).
    # Mirrors CatalogsPage buildMyCatalogs / extractCatalogs logic.
    my_catalogs = [c for c in items if c.get("catalogType") != "ADMIN_MANAGED" and c.get("isDeleted") is not True]
    managed_catalogs = [c for c in items if c.get("catalogType") == "ADMIN_MANAGED"]
    # Owned catalog ids (for action visibility in My tab)
    my_owned_ids = {c.get("catalogId") for c in my_catalogs}

    html = render_template(
        "pages/catalogs.html",
        {
            "catalogs": items,
            "my_catalogs": my_catalogs,
            "managed_catalogs": managed_catalogs,
            "my_owned_ids": my_owned_ids,
            "is_authenticated": True,
        },
    )
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def api_delete_catalog_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Delete catalog item from DynamoDB."""
    path_params = event.get("pathParameters") or {}
    catalog_id = path_params.get("id") or ""

    tables.catalogs.delete_item(Key={"catalogId": catalog_id})

    oob_toast = (
        '<div id="toast-container" hx-swap-oob="afterbegin"><div class="toast toast-success">Catalog deleted'
        " successfully.</div></div>"
    )
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": oob_toast}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway proxy entrypoint for the catalogs domain."""
    from urllib.parse import unquote

    method = event.get("httpMethod", "GET")
    path = event.get("path") or "/"
    if path == "/catalogs" and method == "GET":
        return render_catalogs_handler(event, context)
    if path.startswith("/api/catalogs/") and method == "DELETE":
        event["pathParameters"] = {"id": unquote(path[len("/api/catalogs/") :])}
        return api_delete_catalog_handler(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
