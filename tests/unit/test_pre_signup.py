"""Unit tests for pre_signup Cognito trigger Lambda."""

import os
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from src.handlers.pre_signup import (
    FederatedIdentityLinkedException,
    _auto_confirm_event,
    _is_email_verified,
    _validate_email,
    lambda_handler,
)


def _make_federated_event(
    email: str = "user@example.com",
    email_verified: Any = "true",
    username: str = "Google_1234567890",
    trigger_source: str = "PreSignUp_ExternalProvider",
) -> Dict[str, Any]:
    return {
        "triggerSource": trigger_source,
        "userPoolId": "us-east-1_TEST",
        "userName": username,
        "request": {
            "userAttributes": {
                "email": email,
                "email_verified": email_verified,
            }
        },
        "response": {
            "autoConfirmUser": False,
            "autoVerifyEmail": False,
            "autoVerifyPhone": False,
        },
    }


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


def test_auto_confirm_event_with_email_verify() -> None:
    event: Dict[str, Any] = {"response": {}}
    result = _auto_confirm_event(event, verify_email=True)
    assert result["response"]["autoConfirmUser"] is True
    assert result["response"]["autoVerifyEmail"] is True


def test_auto_confirm_event_without_email_verify() -> None:
    event: Dict[str, Any] = {"response": {}}
    result = _auto_confirm_event(event, verify_email=False)
    assert result["response"]["autoConfirmUser"] is True
    assert result["response"]["autoVerifyEmail"] is False


def test_is_email_verified_true_string() -> None:
    assert _is_email_verified({"email_verified": "true"}) is True


def test_is_email_verified_true_bool() -> None:
    assert _is_email_verified({"email_verified": True}) is True


def test_is_email_verified_false() -> None:
    assert _is_email_verified({"email_verified": "false"}) is False


def test_is_email_verified_missing() -> None:
    assert _is_email_verified({}) is False


def test_validate_email_valid() -> None:
    assert _validate_email("user@example.com") == "user@example.com"


def test_validate_email_strips_whitespace() -> None:
    assert _validate_email("  user@example.com  ") == "user@example.com"


def test_validate_email_too_long() -> None:
    assert _validate_email("a" * 250 + "@b.com") is None


def test_validate_email_invalid_chars() -> None:
    assert _validate_email('user"@example.com') is None


def test_validate_email_not_string() -> None:
    assert _validate_email(12345) is None  # type: ignore[arg-type]


def test_validate_email_no_at_sign() -> None:
    assert _validate_email("notanemail") is None


# ---------------------------------------------------------------------------
# lambda_handler tests
# ---------------------------------------------------------------------------


def test_native_signup_returns_event_unchanged() -> None:
    event = _make_federated_event(trigger_source="PreSignUp_SignUp")
    result = lambda_handler(event, None)
    assert result is event
    assert result["response"].get("autoConfirmUser") is False


def test_admin_create_user_returns_event_unchanged() -> None:
    event = _make_federated_event(trigger_source="PreSignUp_AdminCreateUser")
    result = lambda_handler(event, None)
    assert result is event


def test_federated_no_email_auto_confirms_without_verify() -> None:
    event = _make_federated_event(email="")
    # Remove email from attributes
    event["request"]["userAttributes"] = {"email_verified": "true"}
    result = lambda_handler(event, None)
    assert result["response"]["autoConfirmUser"] is True
    assert result["response"]["autoVerifyEmail"] is False


def test_federated_unverified_email_auto_confirms_without_verify() -> None:
    event = _make_federated_event(email_verified="false")
    result = lambda_handler(event, None)
    assert result["response"]["autoConfirmUser"] is True
    assert result["response"]["autoVerifyEmail"] is False


def test_federated_invalid_email_auto_confirms_without_verify() -> None:
    event = _make_federated_event(email="not-an-email!!")
    result = lambda_handler(event, None)
    assert result["response"]["autoConfirmUser"] is True
    assert result["response"]["autoVerifyEmail"] is False


@patch("src.handlers.pre_signup.boto3.client")
def test_federated_verified_email_no_existing_user(mock_boto3_client: MagicMock) -> None:
    mock_cognito = MagicMock()
    mock_boto3_client.return_value = mock_cognito
    mock_cognito.list_users.return_value = {"Users": []}
    event = _make_federated_event()
    result = lambda_handler(event, None)
    assert result["response"]["autoConfirmUser"] is True
    assert result["response"]["autoVerifyEmail"] is True


@patch("src.handlers.pre_signup.boto3.client")
def test_federated_existing_user_links_identity(mock_boto3_client: MagicMock) -> None:
    mock_cognito = MagicMock()
    mock_boto3_client.return_value = mock_cognito
    mock_cognito.list_users.return_value = {"Users": [{"Username": "native-user"}]}
    mock_cognito.admin_link_provider_for_user.return_value = {}
    event = _make_federated_event(username="Google_99999")
    with pytest.raises(FederatedIdentityLinkedException) as exc_info:
        lambda_handler(event, None)
    assert "linked" in str(exc_info.value).lower() or "sign in again" in str(exc_info.value).lower()
    mock_cognito.admin_link_provider_for_user.assert_called_once()


@patch("src.handlers.pre_signup.boto3.client")
def test_federated_malformed_username_raises(mock_boto3_client: MagicMock) -> None:
    mock_cognito = MagicMock()
    mock_boto3_client.return_value = mock_cognito
    mock_cognito.list_users.return_value = {"Users": [{"Username": "native-user"}]}
    event = _make_federated_event(username="nounderscore")
    with pytest.raises(FederatedIdentityLinkedException):
        lambda_handler(event, None)


@patch("src.handlers.pre_signup.boto3.client")
def test_invalid_parameter_exception_raises_federated_linked(mock_boto3_client: MagicMock) -> None:
    mock_cognito = MagicMock()
    mock_boto3_client.return_value = mock_cognito
    mock_cognito.list_users.return_value = {"Users": [{"Username": "existing"}]}
    err_response = {"Error": {"Code": "InvalidParameterException", "Message": "already linked"}}
    mock_cognito.admin_link_provider_for_user.side_effect = ClientError(err_response, "AdminLinkProviderForUser")
    event = _make_federated_event(username="Google_12345")
    with pytest.raises(FederatedIdentityLinkedException):
        lambda_handler(event, None)


@patch("src.handlers.pre_signup.boto3.client")
def test_generic_exception_returns_event(mock_boto3_client: MagicMock) -> None:
    mock_cognito = MagicMock()
    mock_boto3_client.return_value = mock_cognito
    mock_cognito.list_users.side_effect = Exception("network error")
    event = _make_federated_event()
    result = lambda_handler(event, None)
    assert result is event
