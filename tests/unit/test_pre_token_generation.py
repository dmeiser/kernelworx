"""
Tests for the Pre Token Generation Lambda trigger.

Covers injection of the custom boolean `mfa` claim into the ID and access tokens:
  - Federated (social) identities always mint mfa=false, bypassing enrollment checks.
  - Native users mint mfa=true when at least one MFA method is enabled: a
    recognized PreferredMfaSetting (TOTP, SMS, or passkey MFA / WEB_AUTHN_MFA)
    or any activated method in UserMFASettingList. mfa=false otherwise.
  - Fail-closed behavior on lookup failures.
  - cognito:groups preservation and absence of reserved amr mutations.
"""

import copy
import os
import subprocess
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import NoRegionError

from src.handlers.pre_token_generation import (
    MFA_CLAIM,
    SMS_MFA,
    SOFTWARE_TOKEN_MFA,
    WEB_AUTHN_MFA,
    _cognito_client,
    _is_federated,
    lambda_handler,
)
from tests.unit.test_edge_security import TF_APP, block, first_resource, load_hcl


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
            patch("src.handlers.pre_token_generation._cognito_client") as mock_client,
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
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
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
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
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
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
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
    """Tests for resolving the mfa claim value for native Cognito users from AdminGetUser."""

    def test_totp_preference_sets_mfa_true_in_both_tokens(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """A native user with TOTP software-token preference must set mfa=true on ID and access tokens."""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            result = lambda_handler(pre_token_event, lambda_context)

        details = _details(result)
        assert details["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}
        assert details["accessTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}

    def test_sms_preference_sets_mfa_true(self, pre_token_event: dict[str, Any], lambda_context: MagicMock) -> None:
        """A native user with SMS MFA preference is an enabled MFA factor and must set mfa=true."""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"PreferredMfaSetting": SMS_MFA}
            result = lambda_handler(pre_token_event, lambda_context)

        details = _details(result)
        assert details["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}
        assert details["accessTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}

    def test_passkey_first_factor_only_user_sets_mfa_false(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """
        A native user whose passkey is only a first (passwordless) factor -- no MFA
        method enabled (no UserMFASettingList, PreferredMfaSetting NONE) -- gets
        mfa=false. The trigger is enrollment-based: passkey MFA (an enabled MFA
        method, WEB_AUTHN_MFA) mints true, but a bare first-factor passkey is not
        MFA enrollment.
        """
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {
                "PreferredMfaSetting": "NONE",
                "UserMFASettingList": [],
            }
            result = lambda_handler(pre_token_event, lambda_context)

        details = _details(result)
        assert details["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}
        assert details["accessTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}

    def test_webauthn_preference_sets_mfa_true(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """A native user whose PreferredMfaSetting is WEB_AUTHN_MFA (passkey MFA) is enrolled."""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"PreferredMfaSetting": WEB_AUTHN_MFA}
            result = lambda_handler(pre_token_event, lambda_context)

        details = _details(result)
        assert details["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}
        assert details["accessTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}

    def test_webauthn_in_setting_list_with_no_preference_sets_mfa_true(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """
        Passkey MFA enabled: UserMFASettingList contains the WEB_AUTHN_MFA entry
        (alongside the required co-enabled method) and PreferredMfaSetting is
        absent. Any activated entry in the list is enrollment evidence.
        """
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {
                "UserMFASettingList": [SOFTWARE_TOKEN_MFA, WEB_AUTHN_MFA]
            }
            result = lambda_handler(pre_token_event, lambda_context)

        details = _details(result)
        assert details["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}
        assert details["accessTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}

    def test_webauthn_in_setting_list_with_unrecognized_preference_sets_mfa_true(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """
        The live #336 regression: passkey MFA activation can move the account's
        PreferredMfaSetting off the recognized values (the WebAuthnMfaSettings
        object has no PreferredMfa field, so it may report an unrecognized
        setting). The activated-method list must carry the truth: TOTP plus
        passkey MFA entries with an unrecognized preferred value still mint true.
        """
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {
                "PreferredMfaSetting": "NONE",
                "UserMFASettingList": [SOFTWARE_TOKEN_MFA, WEB_AUTHN_MFA],
            }
            result = lambda_handler(pre_token_event, lambda_context)

        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}

    def test_totp_only_in_setting_list_without_preference_sets_mfa_true(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """TOTP is the only activated method and no preference is reported: still enrolled."""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"UserMFASettingList": [SOFTWARE_TOKEN_MFA]}
            result = lambda_handler(pre_token_event, lambda_context)

        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}

    def test_sms_only_in_setting_list_sets_mfa_true(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """SMS is the only activated method in the list: enrolled."""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"UserMFASettingList": [SMS_MFA]}
            result = lambda_handler(pre_token_event, lambda_context)

        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}

    def test_email_otp_in_setting_list_sets_mfa_true(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """
        Any activated method in UserMFASettingList counts, including EMAIL_OTP
        (email-message MFA per the GetUser API reference): Cognito challenges it
        at sign-in, so it is enabled-MFA enrollment evidence.
        """
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"UserMFASettingList": ["EMAIL_OTP"]}
            result = lambda_handler(pre_token_event, lambda_context)

        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}

    def test_empty_setting_list_and_no_preference_sets_mfa_false(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """An explicitly empty UserMFASettingList with no preferred setting is not enrolled."""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"UserMFASettingList": []}
            result = lambda_handler(pre_token_event, lambda_context)

        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}

    def test_absent_preference_sets_mfa_false(self, pre_token_event: dict[str, Any], lambda_context: MagicMock) -> None:
        """A native user with no PreferredMfaSetting attribute must get mfa=false (never true)."""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {}
            result = lambda_handler(pre_token_event, lambda_context)

        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}

    def test_empty_identities_string_treated_as_native(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """An empty identities string is treated as a native user and proceeds to enrollment check."""
        pre_token_event["request"]["userAttributes"]["identities"] = ""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            result = lambda_handler(pre_token_event, lambda_context)

        mock_client.return_value.admin_get_user.assert_called_once()
        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}

    def test_claim_value_is_boolean_not_string(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """The mfa claim must be a JSON boolean (V2_0), not a string."""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            result = lambda_handler(pre_token_event, lambda_context)

        value = _details(result)["idTokenGeneration"]["claimsToAddOrOverride"][MFA_CLAIM]
        assert isinstance(value, bool)
        assert value is True

    def test_uses_sub_preferred_over_user_name(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """AdminGetUser is called with the sub when it is present."""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            lambda_handler(pre_token_event, lambda_context)

            mock_client.return_value.admin_get_user.assert_called_once_with(
                UserPoolId="us-east-1_TEST123",
                Username="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            )

    def test_falls_back_to_user_name_when_sub_missing(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """When there is no sub, the userName is used as the AdminGetUser identifier."""
        del pre_token_event["request"]["userAttributes"]["sub"]
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            lambda_handler(pre_token_event, lambda_context)

            mock_client.return_value.admin_get_user.assert_called_once_with(
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

        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.side_effect = ClientError(
                {"Error": {"Code": "InternalErrorException", "Message": "boom"}}, "AdminGetUser"
            )
            result = lambda_handler(pre_token_event, lambda_context)

        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}

    def test_missing_identifier_sets_mfa_false_without_api_call(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """With neither a sub nor a userName, no Cognito call is made and mfa is false."""
        del pre_token_event["request"]["userAttributes"]["sub"]
        del pre_token_event["userName"]
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            result = lambda_handler(pre_token_event, lambda_context)

        mock_client.assert_not_called()
        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}

    def test_client_call_failure_still_sets_mfa_false(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """Even a failing cognito client must produce mfa=false, never a raised trigger."""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.side_effect = Exception("no credentials")
            result = lambda_handler(pre_token_event, lambda_context)

        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}

    def test_unexpected_cognito_exception_still_sets_mfa_false(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """Even if the Cognito client raises unexpectedly, mfa is false."""
        with patch(
            "src.handlers.pre_token_generation._cognito_client",
            side_effect=RuntimeError("boom"),
        ):
            result = lambda_handler(pre_token_event, lambda_context)

        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}


class TestNeverRaises:
    """The trigger must always return the event: raising would block every sign-in."""

    def test_malformed_response_fails_closed_without_raising(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """A malformed response object must not escape the handler."""
        pre_token_event["response"] = "not-a-dict"
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            result = lambda_handler(pre_token_event, lambda_context)

        assert result is pre_token_event

    def test_returns_the_event_object(self, pre_token_event: dict[str, Any], lambda_context: MagicMock) -> None:
        """The handler returns the (mutated) event so Cognito can continue."""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            result = lambda_handler(pre_token_event, lambda_context)

        assert result is pre_token_event


class TestGroupPreservation:
    """cognito:groups must be preserved by copying groupConfiguration into the response."""

    def test_group_configuration_copied_to_override(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """The request groupConfiguration is copied into groupOverrideDetails verbatim."""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            result = lambda_handler(pre_token_event, lambda_context)

        assert _details(result)["groupOverrideDetails"] == pre_token_event["request"]["groupConfiguration"]

    def test_absent_group_configuration_means_no_override(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """When there is no groupConfiguration, no groupOverrideDetails is emitted (not emptied)."""
        del pre_token_event["request"]["groupConfiguration"]
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            result = lambda_handler(pre_token_event, lambda_context)

        assert "groupOverrideDetails" not in _details(result)


class TestAmrNotWritten:
    """The trigger must never touch the reserved amr claim (Cognito forbids it)."""

    def test_amr_is_never_written(self, pre_token_event: dict[str, Any], lambda_context: MagicMock) -> None:
        """Neither token generation block may contain an 'amr' claim."""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            result = lambda_handler(pre_token_event, lambda_context)

        details = _details(result)
        assert "amr" not in details["idTokenGeneration"]["claimsToAddOrOverride"]
        assert "amr" not in details["accessTokenGeneration"]["claimsToAddOrOverride"]

    def test_only_mfa_claim_is_added(self, pre_token_event: dict[str, Any], lambda_context: MagicMock) -> None:
        """The handler adds exactly one claim (mfa); it does not fabricate others."""
        with patch("src.handlers.pre_token_generation._cognito_client") as mock_client:
            mock_client.return_value.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            result = lambda_handler(pre_token_event, lambda_context)

        details = _details(result)
        assert set(details["idTokenGeneration"]["claimsToAddOrOverride"]) == {MFA_CLAIM}
        assert set(details["accessTokenGeneration"]["claimsToAddOrOverride"]) == {MFA_CLAIM}


class TestCognitoClientCreatedOnce:
    """
    Regression for issue #458: the Cognito IDP client is created once and reused
    across warm Lambda invocations. Re-instantiating boto3.client inside the
    handler would recreate the client, session, and TLS context on every
    invocation, adding latency to every sign-in. Since #578 the single instance
    is built lazily on first use and memoized, keeping the reuse.
    """

    def test_successive_invocations_reuse_client_without_reinstantiating(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """Two successive handler invocations must build only one client; both
        must go through that one instance."""
        _cognito_client.cache_clear()
        with patch("src.handlers.pre_token_generation.boto3.client") as mock_boto_client:
            mock_boto_client.return_value.admin_get_user.return_value = {"PreferredMfaSetting": SOFTWARE_TOKEN_MFA}
            first = lambda_handler(pre_token_event, lambda_context)
            second = lambda_handler(pre_token_event, lambda_context)

        # The client is built at most once, on the first invocation, and cached.
        assert mock_boto_client.call_count == 1
        # Both invocations used the same cached client instance.
        assert mock_boto_client.return_value.admin_get_user.call_count == 2
        assert _details(first)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}
        assert _details(second)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: True}
        _cognito_client.cache_clear()


class TestLazyClientConstruction:
    """
    Regression for issue #578: the Cognito client used to be built at module
    import, so a region/credential resolution failure (an unset AWS_REGION
    raises botocore.exceptions.NoRegionError inside boto3.client) escaped the
    handler's fail-closed guard and failed the module's initialization instead
    of minting mfa=false. Construction is now deferred to the first invocation,
    where the existing try/except turns it into a logged fail-closed mfa=false.
    """

    def test_import_without_region_does_not_build_client(self) -> None:
        """Importing the module with no resolvable region must succeed: no client
        is constructed at import, so no NoRegionError can escape as an InitError."""
        script = "import src.handlers.pre_token_generation as m; print('imported-without-client-construction')"
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "PYTHONPATH": os.getcwd(),
            # Deny every ambient source of region/credentials the client would
            # otherwise resolve at construction time.
            "AWS_CONFIG_FILE": os.devnull,
            "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
            "AWS_EC2_METADATA_DISABLED": "true",
        }
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        assert "imported-without-client-construction" in completed.stdout

    def test_client_construction_failure_fails_closed(
        self, pre_token_event: dict[str, Any], lambda_context: MagicMock
    ) -> None:
        """A NoRegionError raised while building the real client on first use is
        caught by the handler and mints mfa=false instead of raising."""
        _cognito_client.cache_clear()
        with (
            patch("src.handlers.pre_token_generation.boto3.client", side_effect=NoRegionError()),
            patch("src.handlers.pre_token_generation.logger.warning") as mock_log_warning,
        ):
            result = lambda_handler(pre_token_event, lambda_context)

        _cognito_client.cache_clear()
        assert _details(result)["idTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}
        assert _details(result)["accessTokenGeneration"]["claimsToAddOrOverride"] == {MFA_CLAIM: False}
        assert any("fail-closed" in str(call.args[0]) for call in mock_log_warning.call_args_list)


class TestRegionComesFromTheRuntimeEnvironment:
    """
    Regression for issue #578 (region half). The Cognito client is built with no
    explicit ``region_name``, so botocore resolves the region from the ambient
    Lambda execution environment, which the runtime always provides. Declaring
    the region in the function configuration is not an option: ``AWS_REGION``
    is a Lambda reserved environment variable and the service rejects
    CreateFunction/UpdateFunctionConfiguration when it appears in a function's
    environment ("...contains reserved keys that are currently not supported
    for modification. Reserved keys used in this request: AWS_REGION"), so
    injecting it would fail the next apply in every environment.

    The lambda module is parsed into a semantic model (python-hcl2) to assert
    that no reserved key is ever injected, and the client is built for real in a
    subprocess to assert it picks up the ambient runtime region.
    """

    RESERVED_LAMBDA_ENV_KEYS = frozenset(
        {
            "AWS_REGION",
            "AWS_EXECUTION_ENV",
            "AWS_LAMBDA_FUNCTION_NAME",
            "AWS_LAMBDA_FUNCTION_VERSION",
            "AWS_LAMBDA_LOG_GROUP_NAME",
            "AWS_LAMBDA_RUNTIME_API",
            "LAMBDA_TASK_ROOT",
            "LAMBDA_RUNTIME_DIR",
        }
    )

    def test_no_reserved_lambda_key_is_injected_into_any_function_environment(self) -> None:
        """Neither the shared common environment nor any per-function override may
        set a key Lambda reserves: the service would reject the function update."""
        doc = load_hcl(TF_APP / "modules" / "lambda" / "main.tf")
        locals_ = doc["locals"][0]

        # Both function resources build their environment from common_env (the
        # triggers verbatim, the app functions merged with per-function
        # extra_env), so those two sources are the complete set of keys the
        # module injects; the assertions below prove that wiring first.
        for label in ("functions", "trigger_functions"):
            body = first_resource(doc, "aws_lambda_function", label)
            environment = block(body.get("environment"))
            assert environment, f"aws_lambda_function.{label} declares no environment block"
            assert "local.common_env" in str(environment.get("variables")), (
                f"aws_lambda_function.{label} does not build its environment from local.common_env"
            )

        injected = set(locals_["common_env"])
        for collection in ("functions", "trigger_functions"):
            for spec in locals_.get(collection, {}).values():
                injected |= set(spec.get("extra_env") or {})

        assert injected.isdisjoint(self.RESERVED_LAMBDA_ENV_KEYS), (
            f"Lambda reserved environment keys injected into functions: "
            f"{sorted(injected & self.RESERVED_LAMBDA_ENV_KEYS)}"
        )

    def test_client_resolves_the_ambient_runtime_region(self) -> None:
        """Building the client with no explicit region must use the region the
        execution environment provides (Lambda exports it as AWS_REGION and
        AWS_DEFAULT_REGION), not a hardcoded or injected value."""
        script = "import src.handlers.pre_token_generation as m; print(m._cognito_client().meta.region_name)"
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "PYTHONPATH": os.getcwd(),
            # The region the Lambda runtime exports into the execution environment.
            "AWS_REGION": "us-west-2",
            "AWS_DEFAULT_REGION": "us-west-2",
            # Deny every other region/credentials source so the ambient variables
            # are the only thing the client can resolve from.
            "AWS_CONFIG_FILE": os.devnull,
            "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
            "AWS_EC2_METADATA_DISABLED": "true",
        }
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == "us-west-2"
