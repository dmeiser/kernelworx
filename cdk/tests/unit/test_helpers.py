"""Tests for the helpers module."""

import os
from unittest.mock import patch

from cdk.helpers import (
    KNOWN_USER_POOL_IDS,
    REGION_ABBREVIATIONS,
    get_domain_names,
    get_known_user_pool_id,
    get_region,
    get_region_abbrev,
    make_resource_namer,
)


class TestRegionAbbreviations:
    """Tests for REGION_ABBREVIATIONS constant."""

    def test_contains_us_east_1(self):
        """US East 1 should map to ue1."""
        assert REGION_ABBREVIATIONS["us-east-1"] == "ue1"

    def test_contains_us_east_2(self):
        """US East 2 should map to ue2."""
        assert REGION_ABBREVIATIONS["us-east-2"] == "ue2"

    def test_contains_eu_west_1(self):
        """EU West 1 should map to ew1."""
        assert REGION_ABBREVIATIONS["eu-west-1"] == "ew1"

    def test_contains_ap_northeast_1(self):
        """AP Northeast 1 (Tokyo) should map to ane1."""
        assert REGION_ABBREVIATIONS["ap-northeast-1"] == "ane1"

    def test_all_abbreviations_are_strings(self):
        """All abbreviations should be non-empty strings."""
        for region, abbrev in REGION_ABBREVIATIONS.items():
            assert isinstance(abbrev, str)
            assert len(abbrev) > 0
            assert isinstance(region, str)


class TestGetRegion:
    """Tests for get_region function."""

    def test_returns_aws_region_when_set(self):
        """Should return AWS_REGION when set."""
        with patch.dict(os.environ, {"AWS_REGION": "eu-west-2"}, clear=False):
            # Clear CDK_DEFAULT_REGION to test AWS_REGION priority
            env = os.environ.copy()
            env.pop("CDK_DEFAULT_REGION", None)
            with patch.dict(os.environ, env, clear=True):
                with patch.dict(os.environ, {"AWS_REGION": "eu-west-2"}):
                    assert get_region() == "eu-west-2"

    def test_returns_cdk_default_when_aws_region_not_set(self):
        """Should return CDK_DEFAULT_REGION when AWS_REGION is not set."""
        with patch.dict(os.environ, {"CDK_DEFAULT_REGION": "ap-southeast-1"}, clear=True):
            assert get_region() == "ap-southeast-1"

    def test_returns_us_east_1_default(self):
        """Should return us-east-1 when no env vars are set."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_region() == "us-east-1"


class TestGetRegionAbbrev:
    """Tests for get_region_abbrev function."""

    def test_known_region(self):
        """Should return known abbreviation for known region."""
        assert get_region_abbrev("us-east-1") == "ue1"
        assert get_region_abbrev("eu-west-1") == "ew1"

    def test_unknown_region(self):
        """Should return first 3 chars for unknown region."""
        assert get_region_abbrev("unknown-region") == "unk"

    def test_uses_environment_when_no_region_provided(self):
        """Should use environment region when not provided."""
        with patch.dict(os.environ, {"AWS_REGION": "us-west-2"}, clear=True):
            assert get_region_abbrev() == "uw2"


class TestMakeResourceNamer:
    """Tests for make_resource_namer function."""

    def test_creates_correct_names(self):
        """Should create names with region and environment suffix."""
        rn = make_resource_namer("ue1", "dev")
        assert rn("kernelworx-api") == "kernelworx-api-ue1-dev"

    def test_custom_abbrev_override(self):
        """Should allow overriding region abbreviation."""
        rn = make_resource_namer("ue1", "dev")
        assert rn("kernelworx-api", abbrev="uw2") == "kernelworx-api-uw2-dev"

    def test_custom_env_override(self):
        """Should allow overriding environment."""
        rn = make_resource_namer("ue1", "dev")
        assert rn("kernelworx-api", env="prod") == "kernelworx-api-ue1-prod"

    def test_both_overrides(self):
        """Should allow overriding both region and environment."""
        rn = make_resource_namer("ue1", "dev")
        assert rn("kernelworx-api", abbrev="ew1", env="staging") == "kernelworx-api-ew1-staging"


class TestGetDomainNames:
    """Tests for get_domain_names function."""

    def test_dev_environment(self):
        """Dev environment should have env prefix."""
        domains = get_domain_names("kernelworx.app", "dev")
        assert domains["site_domain"] == "dev.kernelworx.app"
        assert domains["api_domain"] == "api.dev.kernelworx.app"
        assert domains["cognito_domain"] == "login.dev.kernelworx.app"

    def test_prod_environment(self):
        """Prod environment should not have env prefix."""
        domains = get_domain_names("kernelworx.app", "prod")
        assert domains["site_domain"] == "kernelworx.app"
        assert domains["api_domain"] == "api.kernelworx.app"
        assert domains["cognito_domain"] == "login.kernelworx.app"

    def test_staging_environment(self):
        """Non-prod environments should have env prefix."""
        domains = get_domain_names("example.com", "staging")
        assert domains["site_domain"] == "staging.example.com"
        assert domains["api_domain"] == "api.staging.example.com"
        assert domains["cognito_domain"] == "login.staging.example.com"


class TestGetKnownUserPoolId:
    """Tests for get_known_user_pool_id function."""

    def test_returns_dev_pool_id(self):
        """Should return known dev pool ID."""
        result = get_known_user_pool_id("dev")
        assert result == "us-east-1_sDiuCOarb"

    def test_returns_none_for_unknown_env(self):
        """Should return None for unknown environment."""
        result = get_known_user_pool_id("unknown")
        assert result is None

    def test_returns_none_for_prod(self):
        """Should return None for prod (not yet configured)."""
        # Note: This will need to be updated when prod is configured
        if "prod" in KNOWN_USER_POOL_IDS:
            assert get_known_user_pool_id("prod") is not None
        else:
            assert get_known_user_pool_id("prod") is None
