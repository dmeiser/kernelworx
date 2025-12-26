"""CloudFront distribution and static site configuration for the Popcorn Sales Manager stack.

This module creates and configures:
- CloudFront Origin Access Identity (OAI)
- CloudFront distribution with custom domain
- Route53 record for site domain
- S3 bucket grant for CloudFront access
"""

from typing import TYPE_CHECKING, Any

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
from constructs import Construct

if TYPE_CHECKING:
    from aws_cdk import aws_certificatemanager as acm
    from aws_cdk import aws_s3 as s3


def create_cloudfront_distribution(
    scope: Construct,
    site_domain: str,
    site_certificate: "acm.Certificate",
    static_assets_bucket: "s3.Bucket",
    hosted_zone: route53.IHostedZone,
) -> dict[str, Any]:
    """Create CloudFront distribution and related resources.

    Args:
        scope: CDK construct scope
        site_domain: Domain name for the site (e.g., dev.kernelworx.app)
        site_certificate: ACM certificate for the site domain
        static_assets_bucket: S3 bucket for static assets
        hosted_zone: Route53 hosted zone for DNS records

    Returns:
        Dictionary containing distribution, OAI, and DNS record
    """
    # Origin Access Identity for S3
    origin_access_identity = cloudfront.OriginAccessIdentity(
        scope,
        "OAI",
        comment="OAI for Popcorn Sales Manager SPA",
    )
    origin_access_identity.node.default_child.apply_removal_policy(RemovalPolicy.RETAIN)  # type: ignore

    # Grant CloudFront read access to static assets bucket
    static_assets_bucket.grant_read(origin_access_identity)

    # CloudFront distribution with custom domain
    distribution = cloudfront.Distribution(
        scope,
        "Distribution",
        domain_names=[site_domain],
        certificate=site_certificate,
        default_behavior=cloudfront.BehaviorOptions(
            origin=origins.S3BucketOrigin.with_origin_access_identity(
                static_assets_bucket,
                origin_access_identity=origin_access_identity,
            ),
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            compress=True,
        ),
        default_root_object="index.html",
        error_responses=[
            cloudfront.ErrorResponse(
                http_status=403,
                response_http_status=200,
                response_page_path="/index.html",
                ttl=Duration.seconds(0),
            ),
            cloudfront.ErrorResponse(
                http_status=404,
                response_http_status=200,
                response_page_path="/index.html",
                ttl=Duration.seconds(0),
            ),
        ],
        price_class=cloudfront.PriceClass.PRICE_CLASS_100,  # US, Canada, Europe only
        enabled=True,
    )
    distribution.apply_removal_policy(RemovalPolicy.RETAIN)

    # Route53 record for CloudFront distribution
    site_domain_record = route53.ARecord(
        scope,
        "SiteDomainRecordV2",  # Changed from SiteDomainRecord to force recreation
        zone=hosted_zone,
        record_name=site_domain,
        target=route53.RecordTarget.from_alias(targets.CloudFrontTarget(distribution)),
    )
    site_domain_record.node.default_child.apply_removal_policy(RemovalPolicy.RETAIN)  # type: ignore

    return {
        "origin_access_identity": origin_access_identity,
        "distribution": distribution,
        "site_domain_record": site_domain_record,
    }
