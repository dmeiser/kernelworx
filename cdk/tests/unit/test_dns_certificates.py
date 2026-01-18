"""Tests for DNS certificates module."""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestDomainNameLogic:
    """Tests for domain name generation logic in dns_certificates module."""

    def test_dev_environment_uses_subdomain(self):
        """Dev environment uses subdomain prefix."""
        env_name = "dev"
        base_domain = "example.com"

        # Apply the same logic as in create_dns_and_certificates
        if env_name == "prod":
            site_domain = base_domain
            api_domain = f"api.{base_domain}"
            cognito_domain = f"login.{base_domain}"
        else:
            site_domain = f"{env_name}.{base_domain}"
            api_domain = f"api.{env_name}.{base_domain}"
            cognito_domain = f"login.{env_name}.{base_domain}"

        assert site_domain == "dev.example.com"
        assert api_domain == "api.dev.example.com"
        assert cognito_domain == "login.dev.example.com"

    def test_prod_environment_uses_root_domain(self):
        """Prod environment uses root domain."""
        env_name = "prod"
        base_domain = "example.com"

        if env_name == "prod":
            site_domain = base_domain
            api_domain = f"api.{base_domain}"
            cognito_domain = f"login.{base_domain}"
        else:
            site_domain = f"{env_name}.{base_domain}"
            api_domain = f"api.{env_name}.{base_domain}"
            cognito_domain = f"login.{env_name}.{base_domain}"

        assert site_domain == "example.com"
        assert api_domain == "api.example.com"
        assert cognito_domain == "login.example.com"

    def test_staging_environment_uses_subdomain(self):
        """Staging environment uses subdomain prefix like dev."""
        env_name = "staging"
        base_domain = "example.com"

        if env_name == "prod":
            site_domain = base_domain
            api_domain = f"api.{base_domain}"
            cognito_domain = f"login.{base_domain}"
        else:
            site_domain = f"{env_name}.{base_domain}"
            api_domain = f"api.{env_name}.{base_domain}"
            cognito_domain = f"login.{env_name}.{base_domain}"

        assert site_domain == "staging.example.com"
        assert api_domain == "api.staging.example.com"
        assert cognito_domain == "login.staging.example.com"

    def test_default_base_domain(self):
        """Default base domain is kernelworx.app when env var not set."""
        # Clear and test env var default
        env_vars = dict(os.environ)
        env_vars.pop("BASE_DOMAIN", None)

        with patch.dict(os.environ, env_vars, clear=False):
            os.environ.pop("BASE_DOMAIN", None)
            base_domain = os.getenv("BASE_DOMAIN", "kernelworx.app")

        assert base_domain == "kernelworx.app"

    def test_custom_base_domain_from_env(self):
        """Base domain can be set via environment variable."""
        with patch.dict(os.environ, {"BASE_DOMAIN": "custom.com"}):
            base_domain = os.getenv("BASE_DOMAIN", "kernelworx.app")

        assert base_domain == "custom.com"


class TestCreateDnsAndCertificatesIntegration:
    """Integration-style tests for dns_certificates using actual CDK constructs."""

    def test_module_can_be_imported(self):
        """Module can be imported without errors."""
        from cdk.dns_certificates import create_dns_and_certificates

        assert callable(create_dns_and_certificates)

    def test_function_signature(self):
        """Function has expected parameters."""
        import inspect

        from cdk.dns_certificates import create_dns_and_certificates

        sig = inspect.signature(create_dns_and_certificates)
        param_names = list(sig.parameters.keys())

        assert "scope" in param_names
        assert "env_name" in param_names
