"""
S3 Bucket creation for the CDK stack.

Creates:
- Static assets bucket for SPA hosting
- Exports bucket for generated reports
"""

from typing import Callable

from aws_cdk import RemovalPolicy
from aws_cdk import aws_s3 as s3
from constructs import Construct


def create_s3_buckets(stack: Construct, rn: Callable[[str], str]) -> dict[str, s3.Bucket]:
    """Create S3 buckets for the application.

    Args:
        stack: CDK Construct (usually the Stack instance)
        rn: helper function to create resource names (rn(name: str) -> str)

    Returns:
        Dict with 'static_assets_bucket' and 'exports_bucket'
    """
    # Static assets bucket (for SPA hosting)
    static_bucket_name = rn("kernelworx-static")
    static_assets_bucket = s3.Bucket(
        stack,
        "StaticAssets",
        bucket_name=static_bucket_name,
        versioned=True,
        encryption=s3.BucketEncryption.S3_MANAGED,
        block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        removal_policy=RemovalPolicy.RETAIN,
    )

    # Exports bucket (for generated reports and QR codes)
    exports_bucket_name = rn("kernelworx-exports")
    exports_bucket = s3.Bucket(
        stack,
        "Exports",
        bucket_name=exports_bucket_name,
        versioned=False,
        encryption=s3.BucketEncryption.S3_MANAGED,
        block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        removal_policy=RemovalPolicy.RETAIN,
        # NOTE: CORS is configured manually outside CloudFormation
        # to allow presigned URL uploads from specific origins
    )

    return {
        "static_assets_bucket": static_assets_bucket,
        "exports_bucket": exports_bucket,
    }
