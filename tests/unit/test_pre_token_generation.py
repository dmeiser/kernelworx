"""
Tests for the Pre Token Generation Lambda trigger.

Covers injection of the custom boolean `mfa` claim into the ID and access tokens:
  - Federated (social) identities always mint mfa=false, bypassing enrollment checks.
  - Native users mint mfa=true for enabled MFA factors (TOTP or SMS), mfa=false otherwise.
  - Fail-closed behavior on lookup failures.
  - cognito:groups preservation and absence of reserved amr mutations.
"""

import copy
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.pre_token_generation import (
    MFA_CLAIM,
    SMS_MFA,
    SOFTWARE_TOKEN_MFA,
    _is_federated,
    lambda_handler,
)


@pytest.fixture
def pre_token_event() -> dict[str, Any]:
    """Sample Cognito Pre Token Generation (V2_0) event for a native user with groups."""
    return {
        "version": "2",
        "triggerSource": "TokenGeneration_Authentication",
        "region": "us-east-1",
        "userPoolId": "us-east-1_TEST123",
        "userName": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "callerContext": {
            "awsSdkVersion": "aws-sdk-unknown-unknown",
            "clientId": "1example23456789",
        },
        "request": {
            "userAttributes": {
                "sub": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "email": "user@example.com",
            },
            "groupConfiguration": {
                "groupsToOverride": ["admin", "seller"],
                "iamRolesToOverride": ["arn:aws:iam::123456789012:role/sns_caller1"],
                "preferredRole": "arn:aws:iam::123456789012:role/sns_caller",
            },
            "scopes": ["aws.cognito.signin.user.admin", "openid", "email"],
        },
        "response": {"claimsAndScopeOverrideDetails": []},
    }


@pytest.fixture
def federated_pre_token_event(pre_token_event: dict[str, Any]) -> dict[str, Any]:
    """Sample Cognito Pre Token Generation (V2_0) event for a federated (Google) user."""
    event = copy.deepcopy(pre_token_event)
    event["userName"] = "Google_1234567890"
    event["request"]["userAttributes"]["identities"] = (
        '[{"userId":"1234567890","providerName":"Google","providerType":"Google",'
        '"issuer":null,"primary":true,"dateCreated":1726000000000}]'
    )
    return event


@pytest.fixture
def lambda_context() -> MagicMock:
    """Mock Lambda context."""
    context = MagicMock()
    context.function_name = "test-pre-token-generation"
    context.aws_request_id = "test-request-id"
    return context


def _details(event: dict[str, Any]) -> dict[str, Any]:
    return event["response"]["claimsAndScopeOverrideDetails"]


class TestFederatedIdentities:
    """
    Tests that federated (social) identities always mint mfa=false.

    Federated sign-ins can never present an MFA factor in Cognito. Even when a
    social admin has enrolled TOTP in their profile, their social sign-in did not
    challenge for TOTP, so mfa must stay false to close the enrollment-as-proof hole.
    Admin access requires a native password sign-in.
    """

    def test_federated_user_with_totp_enrolled_sets_mfa_false_and_skips_api_call(
        self,
        federated_pre_token_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Federated user with TOTP enrollment must get mfa=false without invoking AdminGetUser."""
        with (
            patch("src.handlers.pre_token_generation.logger.info") as mock_log_info,
            patch("boto3.client") as mock_client,
        ):
            result = lambda_handler(federated_pre_token_event, lambda_context)

        # AdminGetUser must be completely bypassed for federated users
        mock_client.assert_not_called()

        details = _details(result)
        assert details["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}
        assert details["accessTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}
        mock_log_info.assert_any_call("pre-token-generation: federated identity -> mfa=false")

    def test_federated_user_with_sms_enrolled_sets_mfa_false(
        self,
        federated_pre_token_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Federated user with SMS enrollment must still get mfa=false."""
        with patch("boto3.client") as mock_client:
            result = lambda_handler(federated_pre_token_event, lambda_context)

        mock_client.assert_not_called()
        details = _details(result)
        assert details["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}
        assert details["accessTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}

    def test_federated_user_without_mfa_sets_mfa_false(
        self,
        federated_pre_token_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Federated user with no MFA enrolled gets mfa=false."""
        with patch("boto3.client") as mock_client:
            result = lambda_handler(federated_pre_token_event, lambda_context)

        mock_client.assert_not_called()
        details = _details(result)
        assert details["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}
        assert details["accessTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}

    def test_federated_user_with_parsed_list_identities(
        self,
        pre_token_event: dict[str, Any],
        lambda_context: MagicMock,
    ) -> None:
        """Parsed list identities attribute is correctly identified as federated."""
        pre_token_event["request"]["userAttributes"]["identities"] = [{"providerName": "Google"}]
        with patch("boto3.client") as mock_client:
            result = lambda_handler(pre_token_event, lambda_context)

        mock_client.assert_not_called()
        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}

    def test_is_federated_helper_branches(self) -> None:
        """Unit tests covering all branches of _is_federated helper."""
        assert _is_federated({}) is False
        assert _is_federated({"identities": None}) is False
        assert _is_federated({"identities": ""}) is False
        assert _is_federated({"identities": "[]"}) is False
        assert _is_federated({"identities": "  []  "}) is False
        assert _is_federated({"identities": '[{"providerName":"Google"}]'}) is True
        assert _is_federated({"identities": []}) is False
        assert _is_federated({"identities": [{"providerName": "Google"}]}) is True
        assert _is_federated({"identities": {"providerName": "Google"}}) is True
        assert _is_federated({"identities": 12345}) is True


class TestNativeMfaClaimResolution:
    """Tests for resolving the mfa claim value for native Cognito users from PreferredMfaSetting."""

    def test_totp_preference_sets_mfa_true_in_both_tokens(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """A native user with TOTP software-token preference must set mfa=true on ID and access tokens."""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            mock_client.return_value = mock_cognito
            result = lambda_handler(pre_token_event, lambda_context)

        details = _details(result)
        assert details["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}
        assert details["accessTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}

    def test_sms_preference_sets_mfa_true(self, pre_token_event: dict[str, Any], lambda_context: MagicMock) -> None:
        """A native user with SMS MFA preference is an enabled MFA factor and must set mfa=true."""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.return_value = {"PreferredMfaSetting": SMS_MFA}
            mock_client.return_value = mock_cognito
            result = lambda_handler(pre_token_event, lambda_context)

        details = _details(result)
        assert details["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}
        assert details["accessTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}

    def test_passkey_only_user_sets_mfa_false(self, pre_token_event: dict[str, Any], lambda_context: MagicMock) -> None:
        """
        A native passkey-only user has no TOTP/SMS preference (PreferredMfaSetting is
        NONE), so the trigger sets mfa=false. Passkeys are a first factor this
        trigger cannot detect (no per-session signal in the event; the credential
        APIs need the user's own token), so passkey acceptance is not provided by
        this trigger -- it depends on the guard's native-amr handling.
        """
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.return_value = {"PreferredMfaSetting": "NONE"}
            mock_client.return_value = mock_cognito
            result = lambda_handler(pre_token_event, lambda_context)

        details = _details(result)
        assert details["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}
        assert details["accessTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}

    def test_absent_preference_sets_mfa_false(self, pre_token_event: dict[str, Any], lambda_context: MagicMock) -> None:
        """A native user with no PreferredMfaSetting attribute must get mfa=false (never true)."""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.return_value = {}
            mock_client.return_value = mock_cognito
            result = lambda_handler(pre_token_event, lambda_context)

        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}

    def test_empty_identities_string_treated_as_native(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """An empty identities string is treated as a native user and proceeds to enrollment check."""
        pre_token_event["request"]["userAttributes"]["identities"] = ""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            mock_client.return_value = mock_cognito
            result = lambda_handler(pre_token_event, lambda_context)

        mock_cognito.admin_get_user.assert_called_once()
        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}

    def test_claim_value_is_boolean_not_string(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """The mfa claim must be a JSON boolean (V2_0), not a string."""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            mock_client.return_value = mock_cognito
            result = lambda_handler(pre_token_event, lambda_context)

        value = _details(result)["idTokenGeneration"]["claimsToAddOrOverride"][MFA_CLAIM]
        assert isinstance(value, bool)
        assert value is True

    def test_uses_sub_preferred_over_user_name(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """AdminGetUser is called with the sub when it is present."""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            mock_client.return_value = mock_cognito
            lambda_handler(pre_token_event, lambda_context)

            mock_cognito.admin_get_user.assert_called_once_with(
                UserPoolId="us-east-1_TEST123",
                Username="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            )

    def test_falls_back_to_user_name_when_sub_missing(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """When there is no sub, the userName is used as the AdminGetUser identifier."""
        del pre_token_event["request"]["userAttributes"]["sub"]
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            mock_client.return_value = mock_cognito
            lambda_handler(pre_token_event, lambda_context)

            mock_cognito.admin_get_user.assert_called_once_with(
                UserPoolId="us-east-1_TEST123",
                Username=pre_token_event["userName"],
            )


class TestFailClosed:
    """Tests that the trigger fails closed (mfa=false) and never raises."""

    def test_admin_get_user_error_sets_mfa_false(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """A Cognito API error must fail closed (mfa=false), never grant access."""
        from botocore.exceptions import ClientError

        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.side_effect = ClientError(
                {"Error": {"Code": "InternalErrorException", "Message": "boom"}}, "AdminGetUser"
            )
            mock_client.return_value = mock_cognito
            result = lambda_handler(pre_token_event, lambda_context)

        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}

    def test_missing_identifier_sets_mfa_false_without_api_call(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """With neither a sub nor a userName, no Cognito call is made and mfa is false."""
        del pre_token_event["request"]["userAttributes"]["sub"]
        del pre_token_event["userName"]
        with patch("boto3.client") as mock_client:
            result = lambda_handler(pre_token_event, lambda_context)

        mock_client.assert_not_called()
        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}

    def test_client_creation_failure_still_sets_mfa_false(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """Even a failing boto3 client must produce mfa=false, never a raised trigger."""
        with patch("boto3.client", side_effect=Exception("no credentials")):
            result = lambda_handler(pre_token_event, lambda_context)

        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}


class TestNeverRaises:
    """The trigger must always return the event: raising would block every sign-in."""

    def test_malformed_response_fails_closed_without_raising(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """A malformed response object must not escape the handler."""
        pre_token_event["response"] = "not-a-dict"
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            mock_client.return_value = mock_cognito
            result = lambda_handler(pre_token_event, lambda_context)

        assert result is pre_token_event

    def test_returns_the_event_object(self, pre_token_event: dict[str, Any], lambda_context: MagicMock) -> None:
        """The handler returns the (mutated) event so Cognito can continue."""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            mock_client.return_value = mock_cognito
            result = lambda_handler(pre_token_event, lambda_context)

        assert result is pre_token_event


class TestGroupPreservation:
    """cognito:groups must be preserved by copying groupConfiguration into the response."""

    def test_group_configuration_copied_to_override(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """The request groupConfiguration is copied into groupOverrideDetails verbatim."""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            mock_client.return_value = mock_cognito
            result = lambda_handler(pre_token_event, lambda_context)

        assert _details(result)["groupOverrideDetails"] == pre_token_event["request"]["groupConfiguration"]

    def test_absent_group_configuration_means_no_override(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """When there is no groupConfiguration, no groupOverrideDetails is emitted (not emptied)."""
        del pre_token_event["request"]["groupConfiguration"]
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            mock_client.return_value = mock_cognito
            result = lambda_handler(pre_token_event, lambda_context)

        assert "groupOverrideDetails" not in _details(result)


class TestAmrNotWritten:
    """The trigger must never touch the reserved amr claim (Cognito forbids it)."""

    def test_amr_is_never_written(self, pre_token_event: dict[str, Any], lambda_context: MagicMock) -> None:
        """Neither token generation block may contain an 'amr' claim."""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            mock_client.return_value = mock_cognito
            result = lambda_handler(pre_token_event, lambda_context)

        details = _details(result)
        assert "amr" not in details["idTokenGeneration"]["claimsToAddOrOverride"]
        assert "amr" not in details["accessTokenGeneration"]["claimsToAddOrOverride"]

    def test_only_mfa_claim_is_added(self, pre_token_event: dict[str, Any], lambda_context: MagicMock) -> None:
        """The handler adds exactly one claim (mfa); it does not fabricate others."""
        with patch("boto3.client") as mock_client:
            mock_cognito = MagicMock()
            mock_cognito.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            mock_client.return_value = mock_cognito
            result = lambda_handler(pre_token_event, lambda_context)

        details = _details(result)
        assert set(details["idTokenGeneration"]["claimsToAddOrOverride"]) == {MFA_CLAIM}
        assert set(details["accessTokenGeneration"]["claimsToAddOrOverride"]) == {MFA_CLAIM}
