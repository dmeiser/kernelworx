"""DNS and ACM certificate configuration for the Popcorn Sales Manager stack.

This module creates and configures:
- Route53 hosted zone lookup
- ACM certificates for API, site, and Cognito domains
- Domain name configuration based on environment
"""

import os
from typing import Any

from aws_cdk import RemovalPolicy
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_route53 as route53
from constructs import Construct


def create_dns_and_certificates(
    scope: Construct,
    env_name: str,
) -> dict[str, Any]:
    """Create Route53 and ACM certificate resources.

    Args:
        scope: CDK construct scope
        env_name: Environment name (dev, prod, etc.)

    Returns:
        Dictionary containing hosted_zone, certificates, and domain names
    """
    # Load configuration from environment variables
    base_domain = os.getenv("BASE_DOMAIN", "kernelworx.app")

    # Import existing hosted zone
    hosted_zone = route53.HostedZone.from_lookup(
        scope,
        "HostedZone",
        domain_name=base_domain,
    )

    # Define domain names based on environment
    if env_name == "prod":
        site_domain = base_domain
        api_domain = f"api.{base_domain}"
        cognito_domain = f"login.{base_domain}"
    else:
        site_domain = f"{env_name}.{base_domain}"
        api_domain = f"api.{env_name}.{base_domain}"
        cognito_domain = f"login.{env_name}.{base_domain}"

    # ACM Certificate for AppSync API
    api_certificate = acm.Certificate(
        scope,
        "ApiCertificateV2",  # Changed from ApiCertificate to force recreation
        domain_name=api_domain,
        validation=acm.CertificateValidation.from_dns(hosted_zone),
    )
    api_certificate.apply_removal_policy(RemovalPolicy.RETAIN)

    # ACM Certificate for CloudFront (site domain)
    print(f"Creating CloudFront Certificate: {site_domain}")
    site_certificate = acm.Certificate(
        scope,
        "SiteCertificateV3",  # Changed from V2 to force recreation
        domain_name=site_domain,
        validation=acm.CertificateValidation.from_dns(hosted_zone),
    )
    site_certificate.apply_removal_policy(RemovalPolicy.RETAIN)

    # Separate ACM Certificate for Cognito custom domain
    print(f"Creating Cognito Certificate: {cognito_domain}")
    cognito_certificate = acm.Certificate(
        scope,
        "CognitoCertificateV2",  # Changed from CognitoCertificate to force recreation
        domain_name=cognito_domain,
        validation=acm.CertificateValidation.from_dns(hosted_zone),
    )
    cognito_certificate.apply_removal_policy(RemovalPolicy.RETAIN)

    return {
        "hosted_zone": hosted_zone,
        "site_domain": site_domain,
        "api_domain": api_domain,
        "cognito_domain": cognito_domain,
        "api_certificate": api_certificate,
        "site_certificate": site_certificate,
        "cognito_certificate": cognito_certificate,
    }
