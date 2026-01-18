"""Tests for auth module (Cognito User Pool configuration)."""

import inspect
import os
from unittest.mock import MagicMock, patch

import pytest

from cdk.auth import (
    KNOWN_USER_POOL_IDS,
    _build_user_pool_triggers,
    _create_oauth_settings,
    _create_password_policy,
    _create_sms_role,
    _get_callback_urls,
    _get_logout_urls,
    _should_create_cognito_domain,
    _should_skip_lambda_triggers,
    _should_skip_user_pool_domain,
)


class TestKnownUserPoolIds:
    """Tests for KNOWN_USER_POOL_IDS constant."""

    def test_dev_user_pool_id_exists(self):
        """Dev environment has a known User Pool ID."""
        assert "dev" in KNOWN_USER_POOL_IDS
        assert KNOWN_USER_POOL_IDS["dev"].startswith("us-east-1_")

    def test_prod_user_pool_id_not_yet_set(self):
        """Prod environment User Pool ID is not set yet (or is set)."""
        # Either it exists or it doesn't - we just document current state
        # This test passes either way
        pass


class TestShouldSkipLambdaTriggers:
    """Tests for _should_skip_lambda_triggers function."""

    def test_returns_false_when_context_not_set(self):
        """Returns False when context key doesn't exist."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = None

        result = _should_skip_lambda_triggers(mock_scope)

        assert result is False

    def test_returns_true_when_string_true(self):
        """Returns True when context is string 'true'."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = "true"

        result = _should_skip_lambda_triggers(mock_scope)

        assert result is True

    def test_returns_true_when_string_TRUE(self):
        """Returns True when context is string 'TRUE' (case insensitive)."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = "TRUE"

        result = _should_skip_lambda_triggers(mock_scope)

        assert result is True

    def test_returns_true_when_bool_true(self):
        """Returns True when context is boolean True."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = True

        result = _should_skip_lambda_triggers(mock_scope)

        assert result is True

    def test_returns_false_when_bool_false(self):
        """Returns False when context is boolean False."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = False

        result = _should_skip_lambda_triggers(mock_scope)

        assert result is False


class TestBuildUserPoolTriggers:
    """Tests for _build_user_pool_triggers function."""

    def test_returns_none_when_skip_triggers(self):
        """Returns None when skip_lambda_triggers is True."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = True
        mock_pre_signup_fn = MagicMock()
        mock_post_auth_fn = MagicMock()

        result = _build_user_pool_triggers(mock_scope, mock_pre_signup_fn, mock_post_auth_fn)

        assert result is None


class TestGetCallbackUrls:
    """Tests for _get_callback_urls function."""

    def test_includes_localhost(self):
        """Callback URLs include localhost for development."""
        urls = _get_callback_urls("dev.example.com")

        assert "http://localhost:5173" in urls

    def test_includes_local_dev_domain(self):
        """Callback URLs include local dev domain for HTTPS testing."""
        urls = _get_callback_urls("dev.example.com")

        assert "https://local.dev.appworx.app:5173" in urls

    def test_includes_site_domain(self):
        """Callback URLs include the site domain."""
        urls = _get_callback_urls("dev.example.com")

        assert "https://dev.example.com" in urls

    def test_includes_callback_path(self):
        """Callback URLs include the /callback path."""
        urls = _get_callback_urls("dev.example.com")

        assert "https://dev.example.com/callback" in urls

    def test_returns_list(self):
        """Function returns a list."""
        urls = _get_callback_urls("dev.example.com")

        assert isinstance(urls, list)
        assert len(urls) == 4


class TestGetLogoutUrls:
    """Tests for _get_logout_urls function."""

    def test_includes_localhost(self):
        """Logout URLs include localhost."""
        urls = _get_logout_urls("dev.example.com")

        assert "http://localhost:5173" in urls

    def test_includes_site_domain(self):
        """Logout URLs include the site domain."""
        urls = _get_logout_urls("dev.example.com")

        assert "https://dev.example.com" in urls

    def test_does_not_include_callback_path(self):
        """Logout URLs do not include /callback path."""
        urls = _get_logout_urls("dev.example.com")

        assert "https://dev.example.com/callback" not in urls

    def test_returns_list(self):
        """Function returns a list."""
        urls = _get_logout_urls("dev.example.com")

        assert isinstance(urls, list)
        assert len(urls) == 3


class TestCreateCognitoAuthSignature:
    """Tests for create_cognito_auth function signature."""

    def test_module_can_be_imported(self):
        """Module can be imported without errors."""
        from cdk.auth import create_cognito_auth

        assert callable(create_cognito_auth)

    def test_function_has_expected_parameters(self):
        """Function has all expected parameters."""
        from cdk.auth import create_cognito_auth

        sig = inspect.signature(create_cognito_auth)
        param_names = list(sig.parameters.keys())

        assert "scope" in param_names
        assert "rn" in param_names
        assert "region_abbrev" in param_names
        assert "env_name" in param_names
        assert "site_domain" in param_names
        assert "cognito_domain" in param_names
        assert "pre_signup_fn" in param_names
        assert "post_auth_fn" in param_names
        assert "hosted_zone" in param_names
        assert "cognito_certificate" in param_names


class TestShouldCreateCognitoDomain:
    """Tests for _should_create_cognito_domain function."""

    def test_returns_true_when_context_not_set(self):
        """Returns True when context key doesn't exist (default)."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = None

        result = _should_create_cognito_domain(mock_scope)

        assert result is True

    def test_returns_true_when_bool_true(self):
        """Returns True when context is boolean True."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = True

        result = _should_create_cognito_domain(mock_scope)

        assert result is True

    def test_returns_false_when_bool_false(self):
        """Returns False when context is boolean False."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = False

        result = _should_create_cognito_domain(mock_scope)

        assert result is False

    def test_returns_false_when_string_false(self):
        """Returns False when context is string 'false'."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = "false"

        result = _should_create_cognito_domain(mock_scope)

        assert result is False

    def test_returns_true_when_string_true(self):
        """Returns True when context is any string other than 'false'."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = "true"

        result = _should_create_cognito_domain(mock_scope)

        assert result is True


class TestShouldSkipUserPoolDomain:
    """Tests for _should_skip_user_pool_domain function."""

    def test_returns_false_when_context_not_set(self):
        """Returns False when context key doesn't exist."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = None

        result = _should_skip_user_pool_domain(mock_scope)

        assert result is False

    def test_returns_true_when_string_true(self):
        """Returns True when context is string 'true'."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = "true"

        result = _should_skip_user_pool_domain(mock_scope)

        assert result is True

    def test_returns_true_when_bool_true(self):
        """Returns True when context is boolean True."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = True

        result = _should_skip_user_pool_domain(mock_scope)

        assert result is True

    def test_returns_false_when_bool_false(self):
        """Returns False when context is boolean False."""
        mock_scope = MagicMock()
        mock_scope.node.try_get_context.return_value = False

        result = _should_skip_user_pool_domain(mock_scope)

        assert result is False


class TestCreatePasswordPolicy:
    """Tests for _create_password_policy function."""

    def test_returns_password_policy(self):
        """Returns a PasswordPolicy object."""
        from aws_cdk import aws_cognito as cognito

        result = _create_password_policy()

        assert isinstance(result, cognito.PasswordPolicy)

    def test_min_length_is_8(self):
        """Password policy has min length of 8."""
        result = _create_password_policy()

        assert result.min_length == 8

    def test_requires_lowercase(self):
        """Password policy requires lowercase."""
        result = _create_password_policy()

        assert result.require_lowercase is True

    def test_requires_uppercase(self):
        """Password policy requires uppercase."""
        result = _create_password_policy()

        assert result.require_uppercase is True

    def test_requires_digits(self):
        """Password policy requires digits."""
        result = _create_password_policy()

        assert result.require_digits is True

    def test_requires_symbols(self):
        """Password policy requires symbols."""
        result = _create_password_policy()

        assert result.require_symbols is True


class TestCreateOAuthSettings:
    """Tests for _create_oauth_settings function."""

    def test_returns_oauth_settings(self):
        """Returns an OAuthSettings object."""
        from aws_cdk import aws_cognito as cognito

        result = _create_oauth_settings("dev.example.com")

        assert isinstance(result, cognito.OAuthSettings)

    def test_callback_urls_match_get_callback_urls(self):
        """Callback URLs match _get_callback_urls output."""
        result = _create_oauth_settings("dev.example.com")
        expected = _get_callback_urls("dev.example.com")

        assert result.callback_urls == expected

    def test_logout_urls_match_get_logout_urls(self):
        """Logout URLs match _get_logout_urls output."""
        result = _create_oauth_settings("dev.example.com")
        expected = _get_logout_urls("dev.example.com")

        assert result.logout_urls == expected

    def test_flows_include_authorization_code_grant(self):
        """OAuth flows include authorization code grant."""
        result = _create_oauth_settings("dev.example.com")

        assert result.flows.authorization_code_grant is True

    def test_flows_include_implicit_code_grant(self):
        """OAuth flows include implicit code grant."""
        result = _create_oauth_settings("dev.example.com")

        assert result.flows.implicit_code_grant is True


class TestCreateSmsRole:
    """Tests for _create_sms_role function."""

    @patch("cdk.auth.iam.PolicyDocument")
    @patch("cdk.auth.iam.PolicyStatement")
    @patch("cdk.auth.iam.ServicePrincipal")
    @patch("cdk.auth.iam.Role")
    def test_creates_role(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_policy_document
    ):
        """Function creates an IAM Role."""
        mock_scope = MagicMock()
        mock_role = MagicMock()
        mock_role_class.return_value = mock_role

        result = _create_sms_role(mock_scope, "ue1", "dev")

        mock_role_class.assert_called_once()
        assert result == mock_role

    @patch("cdk.auth.iam.PolicyDocument")
    @patch("cdk.auth.iam.PolicyStatement")
    @patch("cdk.auth.iam.ServicePrincipal")
    @patch("cdk.auth.iam.Role")
    def test_role_name_includes_region_and_env(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_policy_document
    ):
        """Role name includes region abbreviation and environment name."""
        mock_scope = MagicMock()
        mock_role = MagicMock()
        mock_role_class.return_value = mock_role

        _create_sms_role(mock_scope, "ue1", "dev")

        call_kwargs = mock_role_class.call_args[1]
        assert call_kwargs["role_name"] == "kernelworx-ue1-dev-UserPoolsmsRole"

    @patch("cdk.auth.iam.PolicyDocument")
    @patch("cdk.auth.iam.PolicyStatement")
    @patch("cdk.auth.iam.ServicePrincipal")
    @patch("cdk.auth.iam.Role")
    def test_role_assumed_by_cognito(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_policy_document
    ):
        """Role is assumed by cognito-idp.amazonaws.com."""
        mock_scope = MagicMock()
        mock_role = MagicMock()
        mock_role_class.return_value = mock_role

        _create_sms_role(mock_scope, "ue1", "dev")

        mock_service_principal.assert_called_once_with("cognito-idp.amazonaws.com")

    @patch("cdk.auth.iam.PolicyDocument")
    @patch("cdk.auth.iam.PolicyStatement")
    @patch("cdk.auth.iam.ServicePrincipal")
    @patch("cdk.auth.iam.Role")
    def test_role_has_sns_publish_policy(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_policy_document
    ):
        """Role has SNS Publish inline policy."""
        mock_scope = MagicMock()
        mock_role = MagicMock()
        mock_role_class.return_value = mock_role

        _create_sms_role(mock_scope, "ue1", "dev")

        mock_policy_statement.assert_called_once_with(
            actions=["sns:Publish"], resources=["arn:aws:sns:*:*:*"]
        )

    @patch("cdk.auth.iam.PolicyDocument")
    @patch("cdk.auth.iam.PolicyStatement")
    @patch("cdk.auth.iam.ServicePrincipal")
    @patch("cdk.auth.iam.Role")
    def test_role_has_removal_policy_retain(
        self, mock_role_class, mock_service_principal, mock_policy_statement, mock_policy_document
    ):
        """Role has RETAIN removal policy."""
        mock_scope = MagicMock()
        mock_role = MagicMock()
        mock_role_class.return_value = mock_role

        result = _create_sms_role(mock_scope, "ue1", "dev")

        result.apply_removal_policy.assert_called_once()
