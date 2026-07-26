"""
Payment Methods Domain Lambda Handler
Handles payment methods listing, creation, S3 presigned QR upload requests, and confirmation.
"""

import json
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


def render_payment_methods_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render payment methods management page."""
    caller_id = get_caller_id(event)
    accounts_table = tables.accounts

    res = accounts_table.get_item(Key={"accountId": caller_id})
    item = res.get("Item", {})
    pms = item.get("paymentMethods", [{"name": "Cash"}, {"name": "Venmo"}])

    html = render_template("pages/payment_methods.html", {"payment_methods": pms, "is_authenticated": True})
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def render_qr_upload_form_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render QR upload modal fragment."""
    query_params = event.get("queryStringParameters") or {}
    name = query_params.get("name", "Payment Method")
    html = render_template("fragments/qr_upload_dialog.html", {"name": name})
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def api_request_qr_upload_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Generate S3 presigned POST URL for QR image upload."""
    caller_id = get_caller_id(event)
    body = json.loads(event.get("body") or "{}")
    pm_name = body.get("name", "cash")
    key = f"qr-codes/{caller_id}/{pm_name}.png"

    # Presigned POST info simulation/call
    presigned_info = {
        "url": "https://s3.amazonaws.com/kernelworx-exports-ue1-dev",
        "fields": {
            "key": key,
            "Content-Type": "image/png",
        },
    }

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(presigned_info),
    }


def api_confirm_qr_upload_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Confirm QR upload and store S3 key in user account preferences in DynamoDB."""
    caller_id = get_caller_id(event)
    body = json.loads(event.get("body") or "{}")
    key = body.get("key", "")

    # Update account preferences in DynamoDB
    tables.accounts.update_item(
        Key={"accountId": caller_id},
        UpdateExpression="SET qrCodeKey = :k",
        ExpressionAttributeValues={":k": key},
    )

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"success": True}),
    }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway proxy entrypoint for the payment methods domain."""
    method = event.get("httpMethod", "GET")
    path = event.get("path") or "/"
    if path == "/payment-methods" and method == "GET":
        return render_payment_methods_handler(event, context)
    if path == "/api/payment-methods/qr-upload-form" and method == "GET":
        return render_qr_upload_form_handler(event, context)
    if path == "/api/payment-methods/qr-upload" and method == "POST":
        return api_request_qr_upload_handler(event, context)
    if path == "/api/payment-methods/qr-confirm" and method == "POST":
        return api_confirm_qr_upload_handler(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
