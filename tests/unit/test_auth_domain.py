"""
Unit tests for Auth Domain Lambda Handlers.
"""

from unittest.mock import MagicMock, patch

from src.handlers.auth_domain import (
    api_auth_login_handler,
    api_auth_signup_handler,
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
