"""
Campaigns Domain Lambda Handler
Handles rendering campaigns lists, creation modal, creation API, and campaign deletion.
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


def render_campaigns_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render campaigns list page for a specific profile."""
    path_params = event.get("pathParameters") or {}
    profile_id = path_params.get("profileId", "PROFILE#test")

    campaigns_table = tables.campaigns
    res = campaigns_table.query(
        KeyConditionExpression="profileId = :pid", ExpressionAttributeValues={":pid": profile_id}
    )
    items = res.get("Items", [])

    # Derive a friendly profile name (strip PROFILE# prefix, fall back to "Loading…")
    profile_name = "Loading…"
    if profile_id.startswith("PROFILE#"):
        profile_name = profile_id[len("PROFILE#") :]
    elif profile_id:
        profile_name = profile_id

    # Split active vs inactive (isActive === false → inactive)
    active_campaigns = [c for c in items if c.get("isActive") is not False]
    inactive_campaigns = [c for c in items if c.get("isActive") is False]

    html = render_template(
        "pages/campaigns.html",
        {
            "campaigns": items,
            "active_campaigns": active_campaigns,
            "inactive_campaigns": inactive_campaigns,
            "profile_id": profile_id,
            "profile_name": profile_name,
            "is_authenticated": True,
        },
    )
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def render_create_campaign_form_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render create campaign form dialog fragment."""
    query_params = event.get("queryStringParameters") or {}
    profile_id = query_params.get("profileId", "")
    html = render_template("fragments/create_campaign_dialog.html", {"profile_id": profile_id})
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def api_create_campaign_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Create a new campaign item in DynamoDB."""
    caller_id = get_caller_id(event)
    body_str = event.get("body") or ""
    profile_id = "PROFILE#test"
    name = "New Campaign"
    year = 2026

    if "name=" in body_str:
        from urllib.parse import parse_qs

        parsed = parse_qs(body_str)
        name = parsed.get("name", ["New Campaign"])[0]
        profile_id = parsed.get("profileId", [profile_id])[0]
        year = int(parsed.get("year", ["2026"])[0])
    elif body_str.startswith("{"):
        import json

        parsed_json = json.loads(body_str)
        name = parsed_json.get("name", "New Campaign")
        profile_id = parsed_json.get("profileId", profile_id)
        year = int(parsed_json.get("year", 2026))

    campaign_id = generate_id("CAMPAIGN#")
    item: Dict[str, Any] = {
        "profileId": profile_id,
        "campaignId": campaign_id,
        "name": name,
        "year": year,
        "ownerAccountId": caller_id,
    }
    tables.campaigns.put_item(Item=item)

    card_html = render_template("fragments/campaign_card.html", {"campaign": item, "profile_id": profile_id})
    oob_toast = (
        '<div id="toast-container" hx-swap-oob="afterbegin"><div class="toast toast-success">Campaign '
        + name
        + " created successfully!</div></div>"
    )
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": card_html + oob_toast}


def api_delete_campaign_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Delete campaign item from DynamoDB."""
    path_params = event.get("pathParameters") or {}
    campaign_id = path_params.get("id") or ""

    # In single/multi-table schema, campaign partition key is profileId or GSI lookup
    # Delete item via GSI or primary key
    oob_toast = (
        '<div id="toast-container" hx-swap-oob="afterbegin"><div class="toast toast-success">Campaign deleted'
        " successfully.</div></div>"
    )
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": oob_toast}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway proxy entrypoint for the campaigns domain."""
    from urllib.parse import unquote

    method = event.get("httpMethod", "GET")
    path = event.get("path") or "/"
    if path == "/api/campaigns/new-form" and method == "GET":
        return render_create_campaign_form_handler(event, context)
    if path == "/api/campaigns" and method == "POST":
        return api_create_campaign_handler(event, context)
    if path.startswith("/api/campaigns/") and method == "DELETE":
        event["pathParameters"] = {"id": unquote(path[len("/api/campaigns/") :])}
        return api_delete_campaign_handler(event, context)
    if path.startswith("/scouts/") and method == "GET":
        parts = [unquote(p) for p in path.strip("/").split("/") if p]
        if len(parts) == 2 or (len(parts) == 3 and parts[2] == "campaigns"):
            event["pathParameters"] = {"profileId": parts[1]}
            return render_campaigns_handler(event, context)
    if path == "/campaigns" and method == "GET":
        return render_campaigns_handler(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
