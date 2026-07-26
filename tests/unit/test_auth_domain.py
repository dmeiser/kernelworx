"""
Unit tests for Auth Domain Lambda Handlers.
"""

import os
from unittest.mock import MagicMock, patch

from src.handlers.auth_domain import (
    _site_domain,
    api_auth_login_handler,
    api_auth_signup_handler,
    handler,
    render_landing_handler,
    render_login_handler,
    render_privacy_handler,
    render_signup_handler,
    render_story_handler,
)


def test_render_public_pages() -> None:
    """Test rendering of public page templates."""
    for handler, expected_title in [
        (render_landing_handler, "KernelWorx"),
        (render_login_handler, "Sign In"),
        (render_signup_handler, "Create Account"),
        (render_privacy_handler, "Privacy Policy"),
        (render_story_handler, "Our Story"),
    ]:
        res = handler({}, None)
        assert res["statusCode"] == 200
        assert res["headers"]["Content-Type"] == "text/html"
        assert expected_title in res["body"]


@patch("src.handlers.auth_domain.cognito_client")
def test_api_auth_login_success(mock_cognito: MagicMock) -> None:
    """Test successful login via Cognito initiate_auth."""
    mock_cognito.initiate_auth.return_value = {
        "AuthenticationResult": {
            "IdToken": "fake-id-token",
            "AccessToken": "fake-access-token",
            "RefreshToken": "fake-refresh-token",
        }
    }
    event = {"body": '{"email": "user@example.com", "password": "Password123"}'}
    res = api_auth_login_handler(event, None)
    assert res["statusCode"] == 200
    assert "fake-id-token" in res["body"]


@patch("src.handlers.auth_domain.cognito_client")
def test_api_auth_login_mfa_required(mock_cognito: MagicMock) -> None:
    """Test login triggering MFA challenge."""
    mock_cognito.initiate_auth.return_value = {
        "ChallengeName": "SOFTWARE_TOKEN_MFA",
        "Session": "mfa-session-id",
    }
    event = {"body": '{"email": "user@example.com", "password": "Password123"}'}
    res = api_auth_login_handler(event, None)
    assert res["statusCode"] == 200
    assert "mfaRequired" in res["body"]


@patch("src.handlers.auth_domain.cognito_client")
def test_api_auth_login_failure(mock_cognito: MagicMock) -> None:
    """Test login exception error response."""
    mock_cognito.initiate_auth.side_effect = Exception("Invalid credentials")
    event = {"body": '{"email": "user@example.com", "password": "wrong"}'}
    res = api_auth_login_handler(event, None)
    assert res["statusCode"] == 400
    assert "Invalid credentials" in res["body"]


@patch("src.handlers.auth_domain.cognito_client")
def test_api_auth_signup_success(mock_cognito: MagicMock) -> None:
    """Test successful user registration."""
    mock_cognito.sign_up.return_value = {}
    event = {"body": '{"email": "newuser@example.com", "password": "Password123"}'}
    res = api_auth_signup_handler(event, None)
    assert res["statusCode"] == 200
    assert "true" in res["body"]


@patch("src.handlers.auth_domain.cognito_client")
def test_api_auth_signup_failure(mock_cognito: MagicMock) -> None:
    """Test signup exception error response."""
    mock_cognito.sign_up.side_effect = Exception("User already exists")
    event = {"body": '{"email": "existing@example.com", "password": "Password123"}'}
    res = api_auth_signup_handler(event, None)
    assert res["statusCode"] == 400
    assert "User already exists" in res["body"]


def test_site_domain_from_env(monkeypatch: object) -> None:
    """_site_domain returns SITE_DOMAIN env var when configured."""
    import os as _os

    _os.environ["SITE_DOMAIN"] = "example.kernelworx.app"
    try:
        result = _site_domain({})
        assert result == "example.kernelworx.app"
    finally:
        _os.environ.pop("SITE_DOMAIN", None)


def test_site_domain_from_host_header() -> None:
    """_site_domain falls back to Host header when SITE_DOMAIN is unset."""
    import os as _os

    _os.environ.pop("SITE_DOMAIN", None)
    result = _site_domain({"headers": {"Host": "dev.kernelworx.app"}})
    assert result == "dev.kernelworx.app"


def test_site_domain_empty_fallback() -> None:
    """_site_domain returns empty string when no env var and no Host header."""
    import os as _os

    _os.environ.pop("SITE_DOMAIN", None)
    result = _site_domain({})
    assert result == ""


def test_handler_unknown_route() -> None:
    """handler returns 404 for unknown routes."""
    event = {"httpMethod": "GET", "path": "/unknown"}
    res = handler(event, None)
    assert res["statusCode"] == 404


def test_handler_all_routes() -> None:
    """handler dispatches every GET and POST route."""
    from unittest.mock import MagicMock, patch

    # GET routes
    for path in ["/", "/login", "/signup", "/privacy", "/story"]:
        res = handler({"httpMethod": "GET", "path": path}, None)
        assert res["statusCode"] == 200

    # POST /api/auth/login
    with patch("src.handlers.auth_domain.cognito_client") as mock_c:
        mock_c.initiate_auth.return_value = {
            "AuthenticationResult": {"IdToken": "t", "AccessToken": "a", "RefreshToken": "r"}
        }
        res = handler(
            {"httpMethod": "POST", "path": "/api/auth/login", "body": '{"email":"u@x.com","password":"p"}'},
            None,
        )
        assert res["statusCode"] == 200

    # POST /api/auth/signup
    with patch("src.handlers.auth_domain.cognito_client") as mock_c:
        mock_c.sign_up.return_value = {}
        res = handler(
            {"httpMethod": "POST", "path": "/api/auth/signup", "body": '{"email":"u@x.com","password":"p"}'},
            None,
        )
        assert res["statusCode"] == 200
