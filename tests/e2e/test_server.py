"""
Local WSGI Test Server for Playwright E2E Testing.
Translates HTTP requests from Chromium into API Gateway event dictionaries,
invokes Lambda handlers, and returns responses to the browser.
"""

import json
import mimetypes
import os
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple
from wsgiref.simple_server import make_server

from src.handlers.admin_domain import (
    api_admin_search_users_handler,
    render_admin_handler,
    render_admin_user_data_handler,
)
from src.handlers.auth_domain import (
    api_auth_login_handler,
    api_auth_signup_handler,
    render_landing_handler,
    render_login_handler,
    render_privacy_handler,
    render_signup_handler,
    render_story_handler,
)
from src.handlers.campaigns_domain import (
    api_create_campaign_handler,
    api_delete_campaign_handler,
    render_campaigns_handler,
    render_create_campaign_form_handler,
)
from src.handlers.catalogs_domain import api_delete_catalog_handler, render_catalogs_handler
from src.handlers.orders_domain import (
    api_delete_order_handler,
    api_get_orders_handler,
    api_save_order_handler,
    render_order_editor_handler,
    render_orders_handler,
)
from src.handlers.payment_methods_domain import (
    api_confirm_qr_upload_handler,
    api_request_qr_upload_handler,
    render_payment_methods_handler,
    render_qr_upload_form_handler,
)
from src.handlers.scouts_domain import (
    api_create_profile_handler,
    api_delete_profile_handler,
    render_create_profile_form_handler,
    render_scouts_handler,
)
from src.handlers.sharing_domain import (
    api_create_invite_handler,
    api_create_share_handler,
    render_account_settings_handler,
    render_scout_management_handler,
)

STATIC_DIR = Path(__file__).parent.parent.parent / "src" / "static"


def make_lambda_event(
    method: str, path: str, query_string: str, headers: Dict[str, str], body_bytes: bytes
) -> Dict[str, Any]:
    """Convert WSGI request parameters into API Gateway proxy event format."""
    query_params: Dict[str, str] = {}
    if query_string:
        from urllib.parse import parse_qs

        parsed = parse_qs(query_string)
        query_params = {k: v[0] for k, v in parsed.items()}

    return {
        "httpMethod": method,
        "path": path,
        "queryStringParameters": query_params,
        "headers": headers,
        "body": body_bytes.decode("utf-8") if body_bytes else "",
        "requestContext": {
            "authorizer": {
                "claims": {
                    "sub": headers.get("x-test-sub", "e2e-test-user-sub"),
                    "email": "e2e-user@example.com",
                }
            }
        },
    }


def wsgi_app(environ: Dict[str, Any], start_response: Callable[[str, List[Tuple[str, str]]], None]) -> List[bytes]:
    """WSGI application handling static assets and routing to Lambda handlers."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET")
    query_string = environ.get("QUERY_STRING", "")

    # Handle static files (/static/...)
    if path.startswith("/static/"):
        rel_path = path[len("/static/") :]
        file_path = STATIC_DIR / rel_path
        if file_path.exists() and file_path.is_file():
            mime_type, _ = mimetypes.guess_type(str(file_path))
            start_response("200 OK", [("Content-Type", mime_type or "text/plain")])
            return [file_path.read_bytes()]
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"404 Not Found"]

    # Read body
    content_length = int(environ.get("CONTENT_LENGTH") or 0)
    body_bytes = environ["wsgi.input"].read(content_length) if content_length > 0 else b""

    # Convert WSGI headers
    headers = {}
    for k, v in environ.items():
        if k.startswith("HTTP_"):
            headers[k[5:].lower().replace("_", "-")] = v

    event = make_lambda_event(method, path, query_string, headers, body_bytes)

    # Route matching
    res = None
    if path == "/" and method == "GET":
        res = render_landing_handler(event, None)
    elif path == "/login" and method == "GET":
        res = render_login_handler(event, None)
    elif path == "/signup" and method == "GET":
        res = render_signup_handler(event, None)
    elif path == "/privacy" and method == "GET":
        res = render_privacy_handler(event, None)
    elif path == "/story" and method == "GET":
        res = render_story_handler(event, None)
    elif path == "/scouts" and method == "GET":
        res = render_scouts_handler(event, None)
    elif path == "/api/profiles/new-form" and method == "GET":
        res = render_create_profile_form_handler(event, None)
    elif path == "/api/profiles" and method == "POST":
        res = api_create_profile_handler(event, None)
    elif path.startswith("/api/profiles/") and method == "DELETE":
        from urllib.parse import unquote

        profile_id = unquote(path[len("/api/profiles/") :])
        event["pathParameters"] = {"id": profile_id}
        res = api_delete_profile_handler(event, None)
    elif path == "/api/campaigns/new-form" and method == "GET":
        res = render_create_campaign_form_handler(event, None)
    elif path == "/api/campaigns" and method == "POST":
        res = api_create_campaign_handler(event, None)
    elif path == "/catalogs" and method == "GET":
        res = render_catalogs_handler(event, None)
    elif path == "/payment-methods" and method == "GET":
        res = render_payment_methods_handler(event, None)
    elif path == "/account/settings" and method == "GET":
        res = render_account_settings_handler(event, None)
    elif path == "/admin" and method == "GET":
        res = render_admin_handler(event, None)

    # Dynamic path-parameter routes — parse before the matching branches below.
    # API Gateway decodes path params; mirror that here so handlers receive the
    # raw prefixed IDs (e.g. "CAMPAIGN#uuid").
    elif path.startswith("/api/campaigns/") and method == "DELETE":
        from urllib.parse import unquote

        campaign_id = unquote(path[len("/api/campaigns/") :])
        event["pathParameters"] = {"id": campaign_id}
        res = api_delete_campaign_handler(event, None)
    elif path.startswith("/api/catalogs/") and method == "DELETE":
        from urllib.parse import unquote

        catalog_id = unquote(path[len("/api/catalogs/") :])
        event["pathParameters"] = {"id": catalog_id}
        res = api_delete_catalog_handler(event, None)
    elif path.startswith("/api/orders/") and method == "DELETE":
        from urllib.parse import unquote

        order_id = unquote(path[len("/api/orders/") :])
        event["pathParameters"] = {"id": order_id}
        res = api_delete_order_handler(event, None)
    elif path == "/api/orders" and method == "POST":
        res = api_save_order_handler(event, None)
    elif path.startswith("/api/orders") and method == "GET":
        res = api_get_orders_handler(event, None)
    elif path == "/api/payment-methods/qr-upload-form" and method == "GET":
        res = render_qr_upload_form_handler(event, None)
    elif path == "/api/payment-methods/qr-upload" and method == "POST":
        res = api_request_qr_upload_handler(event, None)
    elif path == "/api/payment-methods/qr-confirm" and method == "POST":
        res = api_confirm_qr_upload_handler(event, None)
    elif path == "/api/shares" and method == "POST":
        res = api_create_share_handler(event, None)
    elif path == "/api/invites" and method == "POST":
        res = api_create_invite_handler(event, None)
    elif path == "/api/admin/search-users" and method == "GET":
        res = api_admin_search_users_handler(event, None)
    # Profile-scoped page routes: /scouts/{profileId}/...
    # API Gateway URL-decodes path parameters before invoking Lambda; the WSGI
    # server receives raw ( %-encoded) segments, so decode each part so handlers
    # receive the real prefixed IDs (e.g. "PROFILE#uuid") they query DynamoDB with.
    elif path.startswith("/scouts/") and method == "GET":
        from urllib.parse import unquote

        parts = [unquote(p) for p in path.strip("/").split("/")]
        # parts == ["scouts", profileId, ...rest]
        profile_id = parts[1]
        event["pathParameters"] = {"profileId": profile_id}
        if len(parts) == 2:
            # /scouts/{profileId} → treat as campaigns list
            res = render_campaigns_handler(event, None)
        elif parts[2] == "campaigns" and len(parts) == 3:
            res = render_campaigns_handler(event, None)
        elif parts[2] == "manage" and len(parts) == 3:
            res = render_scout_management_handler(event, None)
        elif parts[2] == "campaigns" and len(parts) >= 4:
            campaign_id = parts[3]
            event["pathParameters"]["campaignId"] = campaign_id
            if len(parts) == 4:
                res = render_orders_handler(event, None)
            elif len(parts) == 5 and parts[4] == "new":
                res = render_order_editor_handler(event, None)
            elif len(parts) == 5 and parts[4] == "orders":
                res = render_orders_handler(event, None)
            elif len(parts) == 5:
                res = render_order_editor_handler(event, None)
            elif len(parts) == 6 and parts[4] == "orders" and parts[5] == "new":
                res = render_order_editor_handler(event, None)
            elif len(parts) == 7 and parts[4] == "orders" and parts[6] == "edit":
                event["pathParameters"]["orderId"] = parts[5]
                res = render_order_editor_handler(event, None)
    elif path == "/home" and method == "GET":
        res = render_scouts_handler(event, None)
    elif path == "/campaigns" and method == "GET":
        res = render_campaigns_handler(event, None)
    elif path == "/orders" and method == "GET":
        res = render_orders_handler(event, None)
    elif path == "/scout-management" and method == "GET":
        res = render_scout_management_handler(event, None)
    elif path.startswith("/admin/user-data/") and method == "GET":
        account_id = path[len("/admin/user-data/") :]
        event["pathParameters"] = {"accountId": account_id}
        res = render_admin_user_data_handler(event, None)

    if res:
        status_code = res.get("statusCode", 200)
        status_str = f"{status_code} OK" if status_code == 200 else f"{status_code} Redirect"
        res_headers = [(k, v) for k, v in res.get("headers", {}).items()]
        start_response(status_str, res_headers)
        body = res.get("body", "")
        return [body.encode("utf-8")]

    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"404 Page Not Found"]
