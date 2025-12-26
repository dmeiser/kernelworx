"""
Shared helper utilities for CDK stack construction.

This module provides:
- Region abbreviation mapping for resource naming
- Resource naming function (rn)
- Environment configuration utilities
"""

import os
from typing import Optional

# Region abbreviation mapping for resource naming
# Pattern: {name}-{region_abbrev}-{env} e.g. kernelworx-ue1-dev
REGION_ABBREVIATIONS: dict[str, str] = {
    "us-east-1": "ue1",
    "us-east-2": "ue2",
    "us-west-1": "uw1",
    "us-west-2": "uw2",
    "eu-west-1": "ew1",
    "eu-west-2": "ew2",
    "eu-west-3": "ew3",
    "eu-central-1": "ec1",
    "eu-north-1": "en1",
    "ap-northeast-1": "ane1",  # Tokyo
    "ap-northeast-2": "ane2",  # Seoul
    "ap-northeast-3": "ane3",  # Osaka
    "ap-southeast-1": "ase1",  # Singapore
    "ap-southeast-2": "ase2",  # Sydney
    "ap-south-1": "as1",  # Mumbai
    "sa-east-1": "se1",  # São Paulo
    "ca-central-1": "cc1",  # Canada
}


def get_region() -> str:
    """Get the AWS region from environment variables or default to us-east-1."""
    return os.getenv("AWS_REGION") or os.getenv("CDK_DEFAULT_REGION") or "us-east-1"


def get_region_abbrev(region: Optional[str] = None) -> str:
    """Get the region abbreviation for resource naming.

    Args:
        region: AWS region code. If None, reads from environment.

    Returns:
        Region abbreviation (e.g., 'ue1' for 'us-east-1')
    """
    if region is None:
        region = get_region()
    return REGION_ABBREVIATIONS.get(region, region[:3])


def make_resource_namer(region_abbrev: str, env_name: str):
    """Create a resource naming function.

    Args:
        region_abbrev: Region abbreviation (e.g., 'ue1')
        env_name: Environment name (e.g., 'dev', 'prod')

    Returns:
        A function that takes a base name and returns a fully qualified name
    """

    def rn(name: str, abbrev: str = region_abbrev, env: str = env_name) -> str:
        """Generate resource name with region and environment suffix."""
        return f"{name}-{abbrev}-{env}"

    return rn


def get_domain_names(base_domain: str, env_name: str) -> dict[str, str]:
    """Get domain names for the given environment.

    Args:
        base_domain: Base domain (e.g., 'kernelworx.app')
        env_name: Environment name (e.g., 'dev', 'prod')

    Returns:
        Dict with 'site_domain', 'api_domain', 'cognito_domain'
    """
    if env_name == "prod":
        return {
            "site_domain": base_domain,
            "api_domain": f"api.{base_domain}",
            "cognito_domain": f"login.{base_domain}",
        }
    else:
        return {
            "site_domain": f"{env_name}.{base_domain}",
            "api_domain": f"api.{env_name}.{base_domain}",
            "cognito_domain": f"login.{env_name}.{base_domain}",
        }


# Known User Pool IDs for each environment (prevents creating duplicates)
KNOWN_USER_POOL_IDS: dict[str, str] = {
    "dev": "us-east-1_sDiuCOarb",
    # Add prod when ready: "prod": "us-east-1_XXXXX",
}


def get_known_user_pool_id(env_name: str) -> Optional[str]:
    """Get the known User Pool ID for an environment if it exists.

    Args:
        env_name: Environment name (e.g., 'dev', 'prod')

    Returns:
        User Pool ID if known, None otherwise
    """
    return KNOWN_USER_POOL_IDS.get(env_name)
