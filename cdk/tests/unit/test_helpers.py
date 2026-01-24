"""Tests for CDK helper utilities."""

import os
from unittest.mock import MagicMock, patch

from cdk.helpers import (
    REGION_ABBREVIATIONS,
    get_context_bool,
    get_domain_names,
    get_known_user_pool_id,
    get_region,
    get_region_abbrev,
    make_resource_namer,
)


class TestRegionAbbreviations:
    """Tests for REGION_ABBREVIATIONS constant."""

    def test_us_east_1(self):
        """US East 1 abbreviation is ue1."""
        assert REGION_ABBREVIATIONS["us-east-1"] == "ue1"

    def test_us_east_2(self):
        """US East 2 abbreviation is ue2."""
        assert REGION_ABBREVIATIONS["us-east-2"] == "ue2"

    def test_eu_west_1(self):
        """EU West 1 abbreviation is ew1."""
        assert REGION_ABBREVIATIONS["eu-west-1"] == "ew1"

    def test_ap_northeast_1(self):
        """AP Northeast 1 abbreviation is ane1."""
        assert REGION_ABBREVIATIONS["ap-northeast-1"] == "ane1"


class TestGetRegion:
    """Tests for get_region function."""

    def test_returns_aws_region_env_var(self):
        """Returns AWS_REGION environment variable when set."""
        with patch.dict(os.environ, {"AWS_REGION": "us-west-2"}, clear=True):
            assert get_region() == "us-west-2"

    def test_returns_cdk_default_region_if_aws_region_not_set(self):
        """Returns CDK_DEFAULT_REGION when AWS_REGION is not set."""
        with patch.dict(os.environ, {"CDK_DEFAULT_REGION": "eu-west-1"}, clear=True):
            # Remove AWS_REGION if it exists
            os.environ.pop("AWS_REGION", None)
            assert get_region() == "eu-west-1"

    def test_returns_us_east_1_as_default(self):
        """Returns us-east-1 when no region environment variables are set."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_region() == "us-east-1"


class TestGetRegionAbbrev:
    """Tests for get_region_abbrev function."""

    def test_known_region(self):
        """Returns abbreviation for known region."""
        assert get_region_abbrev("us-east-1") == "ue1"

    def test_unknown_region_uses_first_three_chars(self):
        """Returns first 3 chars for unknown region."""
        assert get_region_abbrev("unknown-region") == "unk"

    def test_reads_from_env_when_none(self):
        """Reads from environment when region is None."""
        with patch.dict(os.environ, {"AWS_REGION": "us-west-2"}, clear=True):
            assert get_region_abbrev() == "uw2"


class TestMakeResourceNamer:
    """Tests for make_resource_namer factory."""

    def test_creates_naming_function(self):
        """Factory creates a function that generates resource names."""
        rn = make_resource_namer("ue1", "dev")
        assert rn("kernelworx") == "kernelworx-ue1-dev"

    def test_naming_function_with_different_env(self):
        """Naming function works with different environment."""
        rn = make_resource_namer("ue1", "prod")
        assert rn("kernelworx") == "kernelworx-ue1-prod"

    def test_naming_function_with_different_region(self):
        """Naming function works with different region abbreviation."""
        rn = make_resource_namer("ew1", "dev")
        assert rn("kernelworx") == "kernelworx-ew1-dev"

    def test_naming_function_allows_override(self):
        """Naming function allows overriding default region and env."""
        rn = make_resource_namer("ue1", "dev")
        # The rn function accepts abbrev and env parameters
        assert rn("kernelworx", "uw2", "prod") == "kernelworx-uw2-prod"


class TestGetDomainNames:
    """Tests for get_domain_names function."""

    def test_dev_environment(self):
        """Dev environment has subdomain prefix."""
        domains = get_domain_names("kernelworx.app", "dev")
        assert domains["site_domain"] == "dev.kernelworx.app"
        assert domains["api_domain"] == "api.dev.kernelworx.app"
        assert domains["cognito_domain"] == "login.dev.kernelworx.app"

    def test_prod_environment(self):
        """Prod environment uses root domain."""
        domains = get_domain_names("kernelworx.app", "prod")
        assert domains["site_domain"] == "kernelworx.app"
        assert domains["api_domain"] == "api.kernelworx.app"
        assert domains["cognito_domain"] == "login.kernelworx.app"

    def test_staging_environment(self):
        """Staging environment has subdomain prefix like dev."""
        domains = get_domain_names("kernelworx.app", "staging")
        assert domains["site_domain"] == "staging.kernelworx.app"
        assert domains["api_domain"] == "api.staging.kernelworx.app"
        assert domains["cognito_domain"] == "login.staging.kernelworx.app"


class TestGetKnownUserPoolId:
    """Tests for get_known_user_pool_id function."""

    def test_returns_dev_user_pool_id(self):
        """Returns known User Pool ID for dev environment."""
        pool_id = get_known_user_pool_id("dev")
        assert pool_id is not None
        assert pool_id.startswith("us-east-1_")

    def test_returns_none_for_unknown_environment(self):
        """Returns None for unknown environment."""
        assert get_known_user_pool_id("unknown") is None


class TestGetContextBool:
    """Tests for get_context_bool function."""

    def test_returns_default_when_key_not_found(self):
        """Returns default when context key doesn't exist."""
        mock_construct = MagicMock()
        mock_construct.node.try_get_context.return_value = None

        result = get_context_bool(mock_construct, "missing_key", default=True)
        assert result is True

        result = get_context_bool(mock_construct, "missing_key", default=False)
        assert result is False

    def test_returns_bool_value_directly(self):
        """Returns boolean value directly when context is boolean."""
        mock_construct = MagicMock()

        mock_construct.node.try_get_context.return_value = True
        assert get_context_bool(mock_construct, "key") is True

        mock_construct.node.try_get_context.return_value = False
        assert get_context_bool(mock_construct, "key") is False

    def test_parses_string_false(self):
        """Parses string 'false' as False."""
        mock_construct = MagicMock()
        mock_construct.node.try_get_context.return_value = "false"

        assert get_context_bool(mock_construct, "key") is False

    def test_parses_string_FALSE(self):
        """Parses string 'FALSE' as False (case insensitive)."""
        mock_construct = MagicMock()
        mock_construct.node.try_get_context.return_value = "FALSE"

        assert get_context_bool(mock_construct, "key") is False

    def test_parses_string_true_as_true(self):
        """Parses any non-'false' string as True."""
        mock_construct = MagicMock()

        mock_construct.node.try_get_context.return_value = "true"
        assert get_context_bool(mock_construct, "key") is True

        mock_construct.node.try_get_context.return_value = "yes"
        assert get_context_bool(mock_construct, "key") is True

        mock_construct.node.try_get_context.return_value = "1"
        assert get_context_bool(mock_construct, "key") is True
