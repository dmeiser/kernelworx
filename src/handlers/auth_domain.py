"""
Auth Domain Lambda Handler
Handles public page rendering and Cognito authentication operations.
"""

import json
import os
from typing import Any, Dict

import boto3

try:  # pragma: no cover
    from utils.templates import render_template
except ModuleNotFoundError:  # pragma: no cover
    from src.utils.templates import render_template

cognito_client = boto3.client("cognito-idp", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _is_authenticated(event: Dict[str, Any]) -> bool:
    headers = event.get("headers", {}) or {}
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    return auth.startswith("Bearer ") and len(auth) > len("Bearer ")


def _site_domain(event: Dict[str, Any]) -> str:
    """Return the configured public site domain, falling back to the Host header."""
    configured = os.environ.get("SITE_DOMAIN", "")
    if configured:
        return configured
    headers = event.get("headers", {}) or {}
    for key in ("Host", "host", "HOST"):
        value = headers.get(key)
        if value:
            return str(value)
    return ""


def _public_context(event: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "is_authenticated": _is_authenticated(event),
        "cognito_domain": os.environ.get("COGNITO_DOMAIN", ""),
        "cognito_client_id": os.environ.get("COGNITO_CLIENT_ID", ""),
        "site_domain": _site_domain(event),
    }


def render_landing_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render public landing page."""
    html = render_template("pages/landing.html", _public_context(event))
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def render_login_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render login page."""
    html = render_template("pages/login.html", _public_context(event))
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def render_signup_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render signup page."""
    html = render_template("pages/signup.html", _public_context(event))
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def render_privacy_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render privacy policy page."""
    html = render_template("pages/privacy.html", _public_context(event))
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def render_story_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Render story page."""
    html = render_template("pages/story.html", _public_context(event))
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}


def api_auth_login_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle password authentication and MFA challenges against Cognito."""
    body = json.loads(event.get("body") or "{}")
    email = body.get("email", "")
    password = body.get("password", "")
    client_id = os.environ.get("COGNITO_CLIENT_ID", "")

    try:
        response = cognito_client.initiate_auth(
            ClientId=client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        )
        if "ChallengeName" in response:
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"mfaRequired": True, "session": response.get("Session")}),
            }
        auth_result = response.get("AuthenticationResult", {})
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {
                    "tokens": {
                        "id_token": auth_result.get("IdToken"),
                        "access_token": auth_result.get("AccessToken"),
                        "refresh_token": auth_result.get("RefreshToken"),
                    }
                }
            ),
        }
    except Exception as e:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }


def api_auth_signup_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle user registration against Cognito User Pool."""
    body = json.loads(event.get("body") or "{}")
    email = body.get("email", "")
    password = body.get("password", "")
    client_id = os.environ.get("COGNITO_CLIENT_ID", "")

    try:
        cognito_client.sign_up(
            ClientId=client_id,
            Username=email,
            Password=password,
            UserAttributes=[{"Name": "email", "Value": email}],
        )
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"success": True}),
        }
    except Exception as e:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway proxy entrypoint. Dispatch by method + path to the auth-domain handlers."""
    method = event.get("httpMethod", "GET")
    path = event.get("path") or "/"
    if path == "/" and method == "GET":
        return render_landing_handler(event, context)
    if path == "/login" and method == "GET":
        return render_login_handler(event, context)
    if path == "/signup" and method == "GET":
        return render_signup_handler(event, context)
    if path == "/privacy" and method == "GET":
        return render_privacy_handler(event, context)
    if path == "/story" and method == "GET":
        return render_story_handler(event, context)
    if path == "/api/auth/login" and method == "POST":
        return api_auth_login_handler(event, context)
    if path == "/api/auth/signup" and method == "POST":
        return api_auth_signup_handler(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
