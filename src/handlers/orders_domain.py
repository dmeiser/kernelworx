"""
Orders Domain Lambda Handler
Handles rendering orders list, order editor, order CRUD, and dual-mode JSON export endpoints.
"""

import json
from decimal import Decimal
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


def render_orders_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render orders list page for a campaign."""
    path_params = event.get("pathParameters") or {}
    profile_id = path_params.get("profileId", "PROFILE#test")
    campaign_id = path_params.get("campaignId", "CAMPAIGN#test")

    orders_table = tables.orders
    res = orders_table.query(
        KeyConditionExpression="campaignId = :cid", ExpressionAttributeValues={":cid": campaign_id}
    )
    items = res.get("Items", [])

    # Compute summary statistics (mirrors CampaignSummaryTiles)
    total_orders = len(items)
    total_revenue = sum(float(o.get("totalAmount", 0) or 0) for o in items)
    unique_customers = len({o.get("customerName") for o in items if o.get("customerName")})
    total_items_sold = 0
    for o in items:
        for li in o.get("lineItems") or []:
            total_items_sold += int(li.get("quantity", 0) or 0)

    # Friendly names (strip prefixes)
    profile_name = profile_id[len("PROFILE#") :] if profile_id.startswith("PROFILE#") else (profile_id or "")
    campaign_name = campaign_id[len("CAMPAIGN#") :] if campaign_id.startswith("CAMPAIGN#") else (campaign_id or "")

    html = render_template(
        "pages/orders.html",
        {
            "orders": items,
            "profile_id": profile_id,
            "campaign_id": campaign_id,
            "profile_name": profile_name,
            "campaign_name": campaign_name,
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "unique_customers": unique_customers,
            "total_items_sold": total_items_sold,
            "is_authenticated": True,
        },
    )
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def render_order_editor_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render order editor page."""
    path_params = event.get("pathParameters") or {}
    profile_id = path_params.get("profileId", "PROFILE#test")
    campaign_id = path_params.get("campaignId", "CAMPAIGN#test")
    # Determine editing mode from the trailing path segment (React: .../new → create, .../orders/:id/edit → edit)
    raw_path = event.get("path") or ""
    parts = [p for p in raw_path.strip("/").split("/") if p]
    is_editing = len(parts) >= 6 and parts[-1] == "edit"

    html = render_template(
        "pages/order_editor.html",
        {
            "profile_id": profile_id,
            "campaign_id": campaign_id,
            "is_editing": is_editing,
            "is_authenticated": True,
        },
    )
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def api_get_orders_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Dual-mode handler: Returns raw JSON if ?format=json (for SheetJS export) or HTML fragment."""
    query_params = event.get("queryStringParameters") or {}
    path_params = event.get("pathParameters") or {}
    campaign_id = path_params.get("campaignId", "CAMPAIGN#test")
    is_json = query_params.get("format") == "json"

    res = tables.orders.query(
        KeyConditionExpression="campaignId = :cid", ExpressionAttributeValues={":cid": campaign_id}
    )
    items = res.get("Items", [])

    if is_json:
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(items, default=str),
        }

    html = render_template("pages/orders.html", {"orders": items, "campaign_id": campaign_id})
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def api_save_order_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Create or update customer order in DynamoDB."""
    from urllib.parse import parse_qs, quote

    caller_id = get_caller_id(event)
    body_str = event.get("body") or ""
    customer_name = "Jane Doe"
    campaign_id = "CAMPAIGN#test"
    profile_id = "PROFILE#test"
    total_amount = Decimal("15.00")

    if body_str.startswith("{"):
        parsed_json = json.loads(body_str)
        customer_name = parsed_json.get("customerName", "Jane Doe")
        campaign_id = parsed_json.get("campaignId", "CAMPAIGN#test")
        profile_id = parsed_json.get("profileId", profile_id)
        total_amount = Decimal(str(parsed_json.get("totalAmount", "15.00")))
    elif "=" in body_str:
        parsed = parse_qs(body_str)
        customer_name = parsed.get("customerName", [customer_name])[0]
        campaign_id = parsed.get("campaignId", [campaign_id])[0]
        profile_id = parsed.get("profileId", [profile_id])[0]
        # Sum line-item subtotals if provided; fall back to a single totalAmount field.
        total_amount = Decimal("0")
        # Compute total from line items: quantity * price for each row.
        item_count = 0
        for key in parsed.keys():
            if key.endswith("][quantity]"):
                idx = key[len("items[") : key.index("][quantity]")]
                qty_key = f"items[{idx}][quantity]"
                price_key = f"items[{idx}][price]"
                qty = Decimal(parsed.get(qty_key, ["1"])[0])
                price = Decimal(parsed.get(price_key, ["0"])[0])
                total_amount += qty * price
                item_count += 1
        if item_count == 0 and "totalAmount" in parsed:
            total_amount = Decimal(str(parsed["totalAmount"][0]))

    order_id = generate_id("ORDER#")
    item: Dict[str, Any] = {
        "campaignId": campaign_id,
        "orderId": order_id,
        "customerName": customer_name,
        "totalAmount": total_amount,
        "status": "PENDING",
        "ownerAccountId": caller_id,
    }
    tables.orders.put_item(Item=item)

    # Build an order-row fragment (or empty swap) so htmx, which targets body,
    # renders a result. Redirect via HX-Redirect so the browser navigates to the
    # orders list (IDs are URL-encoded so the '#' in prefixed IDs survives).
    orders_url = f"/scouts/{quote(profile_id, safe='')}/campaigns/{quote(campaign_id, safe='')}/orders"
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "text/html",
            "HX-Redirect": orders_url,
        },
        "body": "",
    }


def api_delete_order_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Delete customer order from DynamoDB."""
    path_params = event.get("pathParameters") or {}
    order_id = path_params.get("id") or ""
    campaign_id = event.get("queryStringParameters", {}).get("campaignId") or ""

    # Best-effort delete: orders table key is (campaignId, orderId). If the
    # campaignId is available (e.g. via query string) use it; otherwise scan.
    if campaign_id:
        tables.orders.delete_item(Key={"campaignId": campaign_id, "orderId": order_id})
    else:
        scan = tables.orders.scan(ProjectionExpression="campaignId,orderId")
        for it in scan.get("Items", []):
            if it.get("orderId") == order_id:
                tables.orders.delete_item(Key={"campaignId": it["campaignId"], "orderId": order_id})
                break

    # Return an empty swap so the targeted row is removed from the DOM.
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": ""}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway proxy entrypoint for the orders domain."""
    from urllib.parse import unquote

    method = event.get("httpMethod", "GET")
    path = event.get("path") or "/"
    if path == "/api/orders" and method == "POST":
        return api_save_order_handler(event, context)
    if path.startswith("/api/orders/") and method == "DELETE":
        event["pathParameters"] = {"id": unquote(path[len("/api/orders/") :])}
        return api_delete_order_handler(event, context)
    if path.startswith("/api/orders") and method == "GET":
        return api_get_orders_handler(event, context)
    if path.startswith("/scouts/") and method == "GET":
        parts = [unquote(p) for p in path.strip("/").split("/") if p]
        # parts == ["scouts", profileId, "campaigns", campaignId, ...]
        if len(parts) >= 4 and parts[2] == "campaigns":
            event["pathParameters"] = {"profileId": parts[1], "campaignId": parts[3]}
            if len(parts) == 4:
                return render_orders_handler(event, context)
            if len(parts) == 5 and parts[4] == "new":
                return render_order_editor_handler(event, context)
            if len(parts) == 5 and parts[4] == "orders":
                return render_orders_handler(event, context)
            if len(parts) == 5:
                return render_order_editor_handler(event, context)
            if len(parts) == 6 and parts[4] == "orders" and parts[5] == "new":
                return render_order_editor_handler(event, context)
            if len(parts) == 7 and parts[4] == "orders" and parts[6] == "edit":
                event["pathParameters"]["orderId"] = parts[5]
                return render_order_editor_handler(event, context)
    if path == "/orders" and method == "GET":
        return render_orders_handler(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
