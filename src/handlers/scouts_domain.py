"""
Scouts / Seller Profiles Domain Lambda Handler
Handles rendering scout profile lists, creation modals, profile updates, and cascade deletion.
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
    auth_ctx = event.get("requestContext", {}).get("authorizer", {}).get("claims", {})
    sub = auth_ctx.get("sub")
    if sub:
        return str(sub)
    headers = event.get("headers") or {}
    return str(headers.get("x-mock-user-id", "test-user-id"))


def render_scouts_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render main Scouts seller profiles page."""
    caller_id = get_caller_id(event)
    profiles_table = tables.profiles

    # Query owned profiles
    res = profiles_table.query(KeyConditionExpression="PK = :pk", ExpressionAttributeValues={":pk": caller_id})
    items = res.get("Items", [])
    for item in items:
        item["isOwner"] = True
        item["permissions"] = ["READ", "WRITE"]

    html = render_template("pages/scouts.html", {"profiles": items, "is_authenticated": True})
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def render_create_profile_form_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render create profile modal fragment."""
    html = render_template("fragments/create_profile_dialog.html")
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def api_create_profile_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Create a new seller profile item in DynamoDB."""
    caller_id = get_caller_id(event)
    # Parse form URL encoded or JSON payload
    body_str = event.get("body") or ""
    seller_name = "New Scout"
    if "sellerName=" in body_str:
        from urllib.parse import parse_qs

        parsed = parse_qs(body_str)
        seller_name = parsed.get("sellerName", ["New Scout"])[0]
    elif body_str.startswith("{"):
        import json

        parsed_json = json.loads(body_str)
        seller_name = parsed_json.get("sellerName", "New Scout")

    profile_id = generate_id("PROFILE#")
    item: Dict[str, Any] = {
        "PK": caller_id,
        "SK": profile_id,
        "profileId": profile_id,
        "ownerAccountId": caller_id,
        "sellerName": seller_name,
        "isOwner": True,
        "permissions": ["READ", "WRITE"],
    }
    tables.profiles.put_item(Item=item)

    # Render fragment + OOB Toast notification + OOB remove empty state
    card_html = render_template("fragments/profile_card.html", {"profile": item})
    oob_toast = (
        '<div id="toast-container" hx-swap-oob="afterbegin"><div class="toast toast-success">Profile '
        + seller_name
        + " created successfully!</div></div>"
    )
    oob_clear = '<div id="no-profiles-message" hx-swap-oob="delete"></div>'
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": card_html + oob_toast + oob_clear}


def api_delete_profile_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Delete profile item from DynamoDB."""
    caller_id = get_caller_id(event)
    path_params = event.get("pathParameters") or {}
    profile_id = path_params.get("id") or ""

    tables.profiles.delete_item(Key={"PK": caller_id, "SK": profile_id})

    oob_toast = (
        '<div id="toast-container" hx-swap-oob="afterbegin"><div class="toast toast-success">Profile deleted'
        " successfully.</div></div>"
    )
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": oob_toast}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway proxy entrypoint for the scouts/profiles domain."""
    method = event.get("httpMethod", "GET")
    path = event.get("path") or "/"
    if path == "/scouts" and method == "GET":
        return render_scouts_handler(event, context)
    if path == "/home" and method == "GET":
        return render_scouts_handler(event, context)
    if path == "/api/profiles/new-form" and method == "GET":
        return render_create_profile_form_handler(event, context)
    if path == "/api/profiles" and method == "POST":
        return api_create_profile_handler(event, context)
    if path.startswith("/api/profiles/") and method == "DELETE":
        from urllib.parse import unquote

        event["pathParameters"] = {"id": unquote(path[len("/api/profiles/") :])}
        return api_delete_profile_handler(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
