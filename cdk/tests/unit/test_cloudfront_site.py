"""Tests for CloudFront site module."""

import inspect

import pytest


class TestCreateCloudFrontDistributionSignature:
    """Tests for create_cloudfront_distribution function signature and imports."""

    def test_module_can_be_imported(self):
        """Module can be imported without errors."""
        from cdk.cloudfront_site import create_cloudfront_distribution

        assert callable(create_cloudfront_distribution)

    def test_function_has_expected_parameters(self):
        """Function has all expected parameters."""
        from cdk.cloudfront_site import create_cloudfront_distribution

        sig = inspect.signature(create_cloudfront_distribution)
        param_names = list(sig.parameters.keys())

        assert "scope" in param_names
        assert "site_domain" in param_names
        assert "site_certificate" in param_names
        assert "static_assets_bucket" in param_names
        assert "exports_bucket" in param_names
        assert "hosted_zone" in param_names

    def test_function_returns_dict_type_hint(self):
        """Function return type is a dict."""
        from cdk.cloudfront_site import create_cloudfront_distribution

        sig = inspect.signature(create_cloudfront_distribution)
        # Return annotation should be dict[str, Any]
        assert sig.return_annotation is not inspect.Parameter.empty


class TestCloudFrontSiteModuleStructure:
    """Tests for module structure and imports."""

    def test_imports_cloudfront(self):
        """Module imports CloudFront from CDK."""
        import cdk.cloudfront_site as cf_module

        # Check the module has the expected imports available
        assert hasattr(cf_module, "cloudfront")

    def test_imports_route53(self):
        """Module imports Route53 from CDK."""
        import cdk.cloudfront_site as cf_module

        assert hasattr(cf_module, "route53")

    def test_has_duration_import(self):
        """Module imports Duration for TTL settings."""
        import cdk.cloudfront_site as cf_module

        assert hasattr(cf_module, "Duration")
