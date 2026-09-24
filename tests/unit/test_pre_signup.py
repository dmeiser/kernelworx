"""
Tests for Pre-Signup Lambda trigger

Tests automatic linking of federated identities to existing users.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.pre_signup import FederatedIdentityLinkedException, lambda_handler
from src.utils.logging import mask_email


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


class TestSmokeAutoConfirm:
    """Tests for the dev/ephemeral-only smoke-test auto-confirm gate.

    The gate has three parts, all of which must hold for auto-confirm:
    the trigger source is a native ``PreSignUp_SignUp``, the
    ``AUTO_CONFIRM_SMOKE_USERS`` environment variable is exactly "true"
    (set by OpenTofu in dev/ephemeral only), and the email matches the
    smoke-test shape ``smoke+...@example-test.invalid``. Production keeps
    the env var absent, so its signups always pass through untouched.
    """

    @pytest.fixture
    def smoke_signup_event(self, native_signup_event: dict[str, Any]) -> dict[str, Any]:
        """Native sign-up event carrying a smoke-test email address."""
        native_signup_event["request"]["userAttributes"]["email"] = (
            "smoke+abc123def@example-test.invalid"
        )
        return native_signup_event

    def test_smoke_signup_auto_confirmed_when_enabled(
        self,
        smoke_signup_event: dict[str, Any],
        lambda_context: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Dev/ephemeral (flag on): smoke sign-up is auto-confirmed, email auto-verified."""
        monkeypatch.setenv("AUTO_CONFIRM_SMOKE_USERS", "true")

        result = lambda_handler(smoke_signup_event, lambda_context)

        assert result["response"]["autoConfirmUser"] is True
        assert result["response"]["autoVerifyEmail"] is True

    def test_normal_signup_untouched_when_enabled(
        self,
        native_signup_event: dict[str, Any],
        lambda_context: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Flag on but a non-smoke email: normal confirmation flow is untouched."""
        monkeypatch.setenv("AUTO_CONFIRM_SMOKE_USERS", "true")

        result = lambda_handler(native_signup_event, lambda_context)

        assert result["response"]["autoConfirmUser"] is False
        assert result["response"]["autoVerifyEmail"] is False

    def test_smoke_signup_untouched_when_flag_absent(
        self,
        smoke_signup_event: dict[str, Any],
        lambda_context: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Production (flag absent): even a smoke-shaped email keeps normal confirmation."""
        monkeypatch.delenv("AUTO_CONFIRM_SMOKE_USERS", raising=False)

        result = lambda_handler(smoke_signup_event, lambda_context)

        assert result["response"]["autoConfirmUser"] is False
        assert result["response"]["autoVerifyEmail"] is False

    def test_smoke_signup_untouched_when_flag_false(
        self,
        smoke_signup_event: dict[str, Any],
        lambda_context: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An explicit 'false' value also keeps the normal flow (prod-safe)."""
        monkeypatch.setenv("AUTO_CONFIRM_SMOKE_USERS", "false")

        result = lambda_handler(smoke_signup_event, lambda_context)

        assert result["response"]["autoConfirmUser"] is False

    @pytest.mark.parametrize(
        "email",
        [
            "smoke+abc@example-test.invalid.evil.com",  # suffix on the TLD
            "smoke@example-test.invalid",  # no +tag
            "smoke+tag@example.com",  # deliverable domain
            "xsmoke+tag@example-test.invalid",  # prefix before the local tag
            "smoke+tag@sub.example-test.invalid",  # subdomain of the TLD
        ],
    )
    def test_smoke_pattern_rejects_lookalikes(
        self,
        smoke_signup_event: dict[str, Any],
        lambda_context: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        email: str,
    ) -> None:
        """Only the exact smoke shape auto-confirms; lookalikes never do."""
        monkeypatch.setenv("AUTO_CONFIRM_SMOKE_USERS", "true")
        smoke_signup_event["request"]["userAttributes"]["email"] = email

        result = lambda_handler(smoke_signup_event, lambda_context)

        assert result["response"]["autoConfirmUser"] is False

    def test_federated_signup_ignores_smoke_gate(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The smoke gate applies to native sign-ups only, never federated ones."""
        monkeypatch.setenv("AUTO_CONFIRM_SMOKE_USERS", "true")

        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": []}
            mock_client.return_value = mock_cognito

            result = lambda_handler(federated_signup_event, lambda_context)

        # Federated handling is unchanged (auto-confirmed by its own path).
        assert result["response"]["autoConfirmUser"] is True

    def test_flag_reads_current_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sanity: the gate reads os.environ at invoke time, not import time."""
        from src.handlers.pre_signup import _smoke_auto_confirm_enabled

        monkeypatch.delenv("AUTO_CONFIRM_SMOKE_USERS", raising=False)
        assert _smoke_auto_confirm_enabled() is False
        monkeypatch.setenv("AUTO_CONFIRM_SMOKE_USERS", "TRUE")
        assert _smoke_auto_confirm_enabled() is True
        monkeypatch.setenv("AUTO_CONFIRM_SMOKE_USERS", "yes")
        assert _smoke_auto_confirm_enabled() is False


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
        """Federated sign-up without email should still be auto-confirmed."""
        del federated_signup_event["request"]["userAttributes"]["email"]

        result = lambda_handler(federated_signup_event, lambda_context)

        # Can't check for duplicates without email, but don't block the sign-up.
        assert result["response"]["autoConfirmUser"] is True
        assert result["response"]["autoVerifyEmail"] is False


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
                            {"Name": "email_verified", "Value": "true"},
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
            assert isinstance(exc_info.value, FederatedIdentityLinkedException)

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
                        "Attributes": [{"Name": "email_verified", "Value": "true"}],
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
                        "Attributes": [{"Name": "email_verified", "Value": "true"}],
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


class TestExistingUserStateCheck:
    """Tests that linking is refused when the existing account is not confirmed/verified."""

    @staticmethod
    def _run_with_existing_user(
        user: dict[str, Any], event: dict[str, Any], context: MagicMock
    ) -> tuple[MagicMock, str]:
        """Patch boto3 with a ListUsers result of ``user`` and run the handler.

        Returns (mock_cognito, raised_message); always raises FederatedIdentityLinkedException.
        """
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [user]}
            mock_client.return_value = mock_cognito
            with pytest.raises(FederatedIdentityLinkedException) as exc_info:
                lambda_handler(event, context)
            return mock_cognito, str(exc_info.value)

    def test_unconfirmed_existing_user_does_not_link(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """An unconfirmed existing native signup must not receive the federated identity."""
        mock_cognito, message = self._run_with_existing_user(
            {
                "Username": "existing-user-uuid",
                "UserStatus": "UNCONFIRMED",
                "Attributes": [{"Name": "email_verified", "Value": "true"}],
            },
            federated_signup_event,
            lambda_context,
        )

        mock_cognito.admin_link_provider_for_user.assert_not_called()
        assert "not fully set up" in message

    def test_pending_existing_user_does_not_link(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """A PENDING existing account must not receive the federated identity."""
        mock_cognito, message = self._run_with_existing_user(
            {"Username": "existing-user-uuid", "UserStatus": "PENDING"},
            federated_signup_event,
            lambda_context,
        )

        mock_cognito.admin_link_provider_for_user.assert_not_called()
        assert "not fully set up" in message

    def test_missing_user_status_does_not_link(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """A ListUsers result without UserStatus must fail closed."""
        mock_cognito, message = self._run_with_existing_user(
            {
                "Username": "existing-user-uuid",
                "Attributes": [{"Name": "email_verified", "Value": "true"}],
            },
            federated_signup_event,
            lambda_context,
        )

        mock_cognito.admin_link_provider_for_user.assert_not_called()
        assert "not fully set up" in message

    def test_unverified_email_does_not_link(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """A confirmed account whose email is not verified must not be linked."""
        mock_cognito, message = self._run_with_existing_user(
            {
                "Username": "existing-user-uuid",
                "UserStatus": "CONFIRMED",
                "Attributes": [
                    {"Name": "email", "Value": "user@example.com"},
                    {"Name": "email_verified", "Value": "false"},
                ],
            },
            federated_signup_event,
            lambda_context,
        )

        mock_cognito.admin_link_provider_for_user.assert_not_called()
        assert "email is not verified" in message

    def test_missing_email_verified_attribute_does_not_link(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """A confirmed account without an email_verified attribute must not be linked."""
        mock_cognito, message = self._run_with_existing_user(
            {
                "Username": "existing-user-uuid",
                "UserStatus": "CONFIRMED",
                "Attributes": [{"Name": "email", "Value": "user@example.com"}],
            },
            federated_signup_event,
            lambda_context,
        )

        mock_cognito.admin_link_provider_for_user.assert_not_called()
        assert "email is not verified" in message


class TestErrorHandling:
    """Tests for error handling scenarios"""

    def test_link_already_exists_error(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Should handle case where link already exists"""
        from botocore.exceptions import ClientError

        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "existing-user-uuid",
                        "UserStatus": "CONFIRMED",
                        "Attributes": [{"Name": "email_verified", "Value": "true"}],
                    }
                ]
            }
            mock_cognito.admin_link_provider_for_user.side_effect = ClientError(
                {
                    "Error": {
                        "Code": "InvalidParameterException",
                        "Message": "Link already exists",
                    }
                },
                "AdminLinkProviderForUser",
            )
            mock_client.return_value = mock_cognito

            with pytest.raises(Exception) as exc_info:
                lambda_handler(federated_signup_event, lambda_context)

            # Should still raise exception to prevent duplicate
            assert "already exists" in str(exc_info.value)
            assert isinstance(exc_info.value, FederatedIdentityLinkedException)

    def test_cognito_invalid_parameter_without_link_message(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Should handle Cognito InvalidParameterException that is not a duplicate link."""
        from botocore.exceptions import ClientError

        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "existing-user-uuid",
                        "UserStatus": "CONFIRMED",
                        "Attributes": [{"Name": "email_verified", "Value": "true"}],
                    }
                ]
            }
            mock_cognito.admin_link_provider_for_user.side_effect = ClientError(
                {
                    "Error": {
                        "Code": "InvalidParameterException",
                        "Message": "Invalid source user",
                    }
                },
                "AdminLinkProviderForUser",
            )
            mock_client.return_value = mock_cognito

            with pytest.raises(Exception) as exc_info:
                lambda_handler(federated_signup_event, lambda_context)

            assert "already exists" in str(exc_info.value)
            assert mask_email(federated_signup_event["request"]["userAttributes"]["email"]) in str(exc_info.value)
            assert isinstance(exc_info.value, FederatedIdentityLinkedException)

    def test_cognito_api_error_raises(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Unexpected errors should fail the signup to avoid duplicate accounts."""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.side_effect = Exception("Network error")
            mock_cognito.exceptions = MagicMock()
            mock_cognito.exceptions.InvalidParameterException = type("InvalidParameterException", (Exception,), {})
            mock_client.return_value = mock_cognito

            with pytest.raises(Exception, match="Network error"):
                lambda_handler(federated_signup_event, lambda_context)

    def test_unexpected_username_format(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Should reject malformed federated usernames to prevent duplicate accounts."""
        federated_signup_event["userName"] = "malformed-username-no-underscore"

        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "existing-user-uuid",
                        "UserStatus": "CONFIRMED",
                        "Attributes": [{"Name": "email_verified", "Value": "true"}],
                    }
                ]
            }
            mock_client.return_value = mock_cognito

            with pytest.raises(Exception) as exc_info:
                lambda_handler(federated_signup_event, lambda_context)

            assert "invalid username format" in str(exc_info.value).lower()
            assert isinstance(exc_info.value, FederatedIdentityLinkedException)


class TestFederatedSignupEmailVerification:
    """Tests for the email_verified claim requirement and email sanitization."""

    def test_unverified_email_does_not_link(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """An unverified provider email must not be linked to an existing account."""
        federated_signup_event["request"]["userAttributes"]["email_verified"] = "false"

        with patch("boto3.client") as mock_client:
            result = lambda_handler(federated_signup_event, lambda_context)

        mock_client.assert_not_called()
        assert result["response"]["autoConfirmUser"] is True
        assert result["response"]["autoVerifyEmail"] is False

    def test_missing_email_verified_does_not_link(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """If the provider supplies no email_verified claim, do not link."""
        del federated_signup_event["request"]["userAttributes"]["email_verified"]

        with patch("boto3.client") as mock_client:
            result = lambda_handler(federated_signup_event, lambda_context)

        mock_client.assert_not_called()
        assert result["response"]["autoConfirmUser"] is True
        assert result["response"]["autoVerifyEmail"] is False

    def test_invalid_email_does_not_link(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """An unsafe/invalid provider email must not be interpolated into ListUsers."""
        federated_signup_event["request"]["userAttributes"]["email"] = 'user@example.com" OR 1=1'

        with patch("boto3.client") as mock_client:
            result = lambda_handler(federated_signup_event, lambda_context)

        mock_client.assert_not_called()
        assert result["response"]["autoConfirmUser"] is True
        assert result["response"]["autoVerifyEmail"] is False

    def test_list_users_uses_validated_email_filter(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """The ListUsers filter must use the validated, sanitized email address."""
        federated_signup_event["request"]["userAttributes"]["email"] = "  user@example.com  "

        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": []}
            mock_client.return_value = mock_cognito

            lambda_handler(federated_signup_event, lambda_context)

            mock_cognito.list_users.assert_called_once_with(
                UserPoolId="us-east-1_TEST123",
                Filter='email = "user@example.com"',
                Limit=1,
            )

    def test_non_string_email_does_not_link(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """A non-string email attribute must not be interpolated into ListUsers."""
        federated_signup_event["request"]["userAttributes"]["email"] = 12345

        with patch("boto3.client") as mock_client:
            result = lambda_handler(federated_signup_event, lambda_context)

        mock_client.assert_not_called()
        assert result["response"]["autoConfirmUser"] is True
        assert result["response"]["autoVerifyEmail"] is False

    def test_overlong_email_does_not_link(
        self,
        federated_signup_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """An email exceeding 254 characters must not be interpolated into ListUsers."""
        local = "a" * 250
        federated_signup_event["request"]["userAttributes"]["email"] = f"{local}@x.co"

        with patch("boto3.client") as mock_client:
            result = lambda_handler(federated_signup_event, lambda_context)

        mock_client.assert_not_called()
        assert result["response"]["autoConfirmUser"] is True
        assert result["response"]["autoVerifyEmail"] is False
