"""
Tests for Pre-Signup Lambda trigger

Tests automatic linking of federated identities to existing users.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from src.handlers.pre_signup import lambda_handler


@pytest.fixture
def federated_signup_event() -> dict[str, Any]:
    """Sample Cognito Pre-Sign-Up event for federated (Google) user"""
    return {
        "version": "1",
        "triggerSource": "PreSignUp_ExternalProvider",
        "region": "us-east-1",
        "userPoolId": "us-east-1_TEST123",
        "userName": "Google_123456789",
        "callerContext": {
            "awsSdkVersion": "aws-sdk-js-2.1055.0",
            "clientId": "1example23456789",
        },
        "request": {
            "userAttributes": {
                "email": "user@example.com",
                "email_verified": "true",
                "given_name": "Test",
                "family_name": "User",
            }
        },
        "response": {
            "autoConfirmUser": False,
            "autoVerifyEmail": False,
            "autoVerifyPhone": False,
        },
    }


@pytest.fixture
def native_signup_event() -> dict[str, Any]:
    """Sample Cognito Pre-Sign-Up event for native (email/password) user"""
    return {
        "version": "1",
        "triggerSource": "PreSignUp_SignUp",
        "region": "us-east-1",
        "userPoolId": "us-east-1_TEST123",
        "userName": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "callerContext": {
            "awsSdkVersion": "aws-sdk-js-2.1055.0",
            "clientId": "1example23456789",
        },
        "request": {
            "userAttributes": {
                "email": "user@example.com",
            }
        },
        "response": {
            "autoConfirmUser": False,
            "autoVerifyEmail": False,
            "autoVerifyPhone": False,
        },
    }


@pytest.fixture
def lambda_context() -> MagicMock:
    """Mock Lambda context"""
    context = MagicMock()
    context.function_name = "test-pre-signup"
    context.aws_request_id = "test-request-id"
    return context


class TestNativeSignup:
    """Tests for native (email/password) sign-ups"""

    def test_native_signup_passes_through(
        self,
        native_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Native sign-ups should pass through without modification"""
        result = lambda_handler(native_signup_event, lambda_context)

        # Should return event unmodified
        assert result == native_signup_event
        assert result["response"]["autoConfirmUser"] is False


class TestFederatedSignupNoExistingUser:
    """Tests for federated sign-ups when no existing user with same email"""

    def test_new_federated_user_auto_confirmed(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """New federated users should be auto-confirmed"""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": []}
            mock_client.return_value = mock_cognito

            result = lambda_handler(federated_signup_event, lambda_context)

            # Should auto-confirm and auto-verify
            assert result["response"]["autoConfirmUser"] is True
            assert result["response"]["autoVerifyEmail"] is True

    def test_federated_user_without_email(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Federated sign-up without email should pass through"""
        del federated_signup_event["request"]["userAttributes"]["email"]

        result = lambda_handler(federated_signup_event, lambda_context)

        # Should return event (can't check for duplicates without email)
        assert result == federated_signup_event


class TestFederatedSignupExistingUser:
    """Tests for federated sign-ups when existing user with same email exists"""

    def test_links_identity_and_raises_exception(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Should link identity and raise exception to prevent duplicate"""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "existing-user-uuid",
                        "UserStatus": "CONFIRMED",
                        "Attributes": [
                            {"Name": "email", "Value": "user@example.com"},
                            {"Name": "sub", "Value": "existing-user-uuid"},
                        ],
                    }
                ]
            }
            # Set up the exceptions attribute with proper exception class
            mock_cognito.exceptions = MagicMock()
            mock_cognito.exceptions.InvalidParameterException = type("InvalidParameterException", (Exception,), {})
            mock_client.return_value = mock_cognito

            with pytest.raises(Exception) as exc_info:
                lambda_handler(federated_signup_event, lambda_context)

            # Should link the identity
            mock_cognito.admin_link_provider_for_user.assert_called_once_with(
                UserPoolId="us-east-1_TEST123",
                DestinationUser={
                    "ProviderName": "Cognito",
                    "ProviderAttributeValue": "existing-user-uuid",
                },
                SourceUser={
                    "ProviderName": "Google",
                    "ProviderAttributeName": "Cognito_Subject",
                    "ProviderAttributeValue": "123456789",
                },
            )

            # Should raise exception with helpful message
            assert "already exists" in str(exc_info.value)
            assert "Google" in str(exc_info.value)
            assert "linked" in str(exc_info.value)

    def test_facebook_user_linking(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Should work for Facebook provider"""
        federated_signup_event["userName"] = "Facebook_987654321"

        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "existing-user-uuid",
                        "UserStatus": "CONFIRMED",
                    }
                ]
            }
            # Set up the exceptions attribute with proper exception class
            mock_cognito.exceptions = MagicMock()
            mock_cognito.exceptions.InvalidParameterException = type("InvalidParameterException", (Exception,), {})
            mock_client.return_value = mock_cognito

            with pytest.raises(Exception) as exc_info:
                lambda_handler(federated_signup_event, lambda_context)

            # Should link with Facebook provider
            call_args = mock_cognito.admin_link_provider_for_user.call_args
            assert call_args[1]["SourceUser"]["ProviderName"] == "Facebook"
            assert call_args[1]["SourceUser"]["ProviderAttributeValue"] == "987654321"
            assert "Facebook" in str(exc_info.value)

    def test_apple_user_linking(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Should work for Apple provider"""
        federated_signup_event["userName"] = "SignInWithApple_apple123456"

        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "existing-user-uuid",
                        "UserStatus": "CONFIRMED",
                    }
                ]
            }
            # Set up the exceptions attribute with proper exception class
            mock_cognito.exceptions = MagicMock()
            mock_cognito.exceptions.InvalidParameterException = type("InvalidParameterException", (Exception,), {})
            mock_client.return_value = mock_cognito

            with pytest.raises(Exception) as exc_info:
                lambda_handler(federated_signup_event, lambda_context)

            # Should link with SignInWithApple provider
            call_args = mock_cognito.admin_link_provider_for_user.call_args
            assert call_args[1]["SourceUser"]["ProviderName"] == "SignInWithApple"
            assert call_args[1]["SourceUser"]["ProviderAttributeValue"] == "apple123456"
            assert "SignInWithApple" in str(exc_info.value)


class TestErrorHandling:
    """Tests for error handling scenarios"""

    def test_link_already_exists_error(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Should handle case where link already exists"""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": "existing-user-uuid"}]}
            # Simulate link already exists error
            mock_cognito.exceptions = MagicMock()
            mock_cognito.exceptions.InvalidParameterException = type("InvalidParameterException", (Exception,), {})
            mock_cognito.admin_link_provider_for_user.side_effect = mock_cognito.exceptions.InvalidParameterException(
                "Link already exists"
            )
            mock_client.return_value = mock_cognito

            with pytest.raises(Exception) as exc_info:
                lambda_handler(federated_signup_event, lambda_context)

            # Should still raise exception to prevent duplicate
            assert "already exists" in str(exc_info.value)

    def test_cognito_api_error_allows_signup(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Unexpected errors should not block sign-up"""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.side_effect = Exception("Network error")
            mock_cognito.exceptions = MagicMock()
            mock_cognito.exceptions.InvalidParameterException = type("InvalidParameterException", (Exception,), {})
            mock_client.return_value = mock_cognito

            result = lambda_handler(federated_signup_event, lambda_context)

            # Should return event to allow sign-up (fail open)
            assert result == federated_signup_event

    def test_unexpected_username_format(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Should handle unexpected username format gracefully"""
        federated_signup_event["userName"] = "malformed-username-no-underscore"

        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": "existing-user-uuid"}]}
            mock_client.return_value = mock_cognito

            result = lambda_handler(federated_signup_event, lambda_context)

            # Should return event (can't parse provider)
            assert result == federated_signup_event
