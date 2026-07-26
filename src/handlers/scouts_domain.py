"""
Scouts / Seller Profiles Domain Lambda Handler
Handles rendering scout profile lists, creation modals, profile updates, and cascade deletion.
"""

import json
from typing import Any, Dict
from urllib.parse import parse_qs, unquote

try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.ids import ensure_account_id, ensure_profile_id, generate_id
    from utils.proxy_event import get_caller_id, parse_body
    from utils.templates import render_template
except ModuleNotFoundError:  # pragma: no cover
    from src.utils.dynamodb import tables
    from src.utils.ids import ensure_account_id, ensure_profile_id, generate_id
    from src.utils.proxy_event import get_caller_id, parse_body
    from src.utils.templates import render_template


def render_scouts_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render main Scouts seller profiles page."""
    caller_id = get_caller_id(event)
    db_account_id = ensure_account_id(caller_id) or f"ACCOUNT#{caller_id}"

    res = tables.profiles.query(
        KeyConditionExpression="ownerAccountId = :owner",
        ExpressionAttributeValues={":owner": db_account_id},
    )
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
    db_account_id = ensure_account_id(caller_id) or f"ACCOUNT#{caller_id}"

    body = parse_body(event)
    seller_name = body.get("sellerName", "New Scout") or "New Scout"

    profile_id = generate_id("PROFILE#")
    item: Dict[str, Any] = {
        "ownerAccountId": db_account_id,
        "profileId": profile_id,
        "sellerName": seller_name,
        "isOwner": True,
        "permissions": ["READ", "WRITE"],
    }
    tables.profiles.put_item(Item=item)

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
    db_account_id = ensure_account_id(caller_id) or f"ACCOUNT#{caller_id}"
    path_params = event.get("pathParameters") or {}
    profile_id = path_params.get("profileId") or path_params.get("id") or ""
    db_profile_id = ensure_profile_id(profile_id) or f"PROFILE#{profile_id}"

    tables.profiles.delete_item(Key={"ownerAccountId": db_account_id, "profileId": db_profile_id})

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
        profile_id = unquote(path[len("/api/profiles/") :].split("/")[0])
        event["pathParameters"] = {"profileId": profile_id}
        return api_delete_profile_handler(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
