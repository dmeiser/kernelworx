"""
Resource Lookup Helper

Discovers existing AWS resources by name patterns using boto3.
This allows CDK to import resources instead of creating new ones.
"""

import functools
import os
from typing import Any, Optional

import boto3

# Cache boto3 clients
_clients: dict[str, Any] = {}


def get_client(service: str) -> Any:
    """Get a cached boto3 client."""
    if service not in _clients:
        region = os.getenv("AWS_REGION") or os.getenv("CDK_DEFAULT_REGION", "us-east-1")
        _clients[service] = boto3.client(service, region_name=region)  # type: ignore[call-overload]
    return _clients[service]


@functools.lru_cache(maxsize=128)
def lookup_user_pool_by_name(name_prefix: str) -> Optional[dict[str, str]]:
    """Find a Cognito User Pool by name prefix."""
    client = get_client("cognito-idp")
    try:
        paginator = client.get_paginator("list_user_pools")
        for page in paginator.paginate(MaxResults=60):
            for pool in page.get("UserPools", []):
                if pool["Name"].startswith(name_prefix):
                    return {
                        "user_pool_id": pool["Id"],
                        "user_pool_name": pool["Name"],
                    }
    except Exception:
        pass
    return None


@functools.lru_cache(maxsize=128)
def lookup_user_pool_client(
    user_pool_id: str, client_name_prefix: str = ""
) -> Optional[dict[str, str]]:
    """Find a Cognito User Pool Client by name prefix. If prefix empty, return first client."""
    client = get_client("cognito-idp")
    try:
        paginator = client.get_paginator("list_user_pool_clients")
        for page in paginator.paginate(UserPoolId=user_pool_id, MaxResults=60):
            for app_client in page.get("UserPoolClients", []):
                if not client_name_prefix or app_client["ClientName"].startswith(
                    client_name_prefix
                ):
                    return {
                        "client_id": app_client["ClientId"],
                        "client_name": app_client["ClientName"],
                    }
    except Exception:
        pass
    return None


@functools.lru_cache(maxsize=128)
def lookup_dynamodb_table(table_name: str) -> Optional[dict[str, str]]:
    """Check if a DynamoDB table exists and get its ARN."""
    client = get_client("dynamodb")
    try:
        response = client.describe_table(TableName=table_name)
        return {
            "table_name": response["Table"]["TableName"],
            "table_arn": response["Table"]["TableArn"],
        }
    except client.exceptions.ResourceNotFoundException:
        return None
    except Exception:
        return None


@functools.lru_cache(maxsize=128)
def lookup_s3_bucket(bucket_name: str) -> bool:
    """Check if an S3 bucket exists."""
    client = get_client("s3")
    try:
        client.head_bucket(Bucket=bucket_name)
        return True
    except Exception:
        return False


@functools.lru_cache(maxsize=128)
def lookup_s3_bucket_policy(bucket_name: str) -> bool:
    """Check if an S3 bucket has a policy attached."""
    client = get_client("s3")
    try:
        client.get_bucket_policy(Bucket=bucket_name)
        return True  # Policy exists
    except client.exceptions.NoSuchBucket:
        return False
    except Exception as e:
        # NoSuchBucketPolicy is not a named exception in botocore, catch generic error
        if "NoSuchBucketPolicy" in str(e) or "policy does not exist" in str(e):
            return False  # Bucket exists but no policy
        # Re-raise other exceptions
        raise


@functools.lru_cache(maxsize=128)
def lookup_cloudfront_distribution(domain_name: str) -> Optional[dict[str, str]]:
    """Find a CloudFront distribution by domain alias."""
    client = get_client("cloudfront")
    try:
        paginator = client.get_paginator("list_distributions")
        for page in paginator.paginate():
            for dist in page.get("DistributionList", {}).get("Items", []):
                aliases = dist.get("Aliases", {}).get("Items", [])
                if domain_name in aliases:
                    return {
                        "distribution_id": dist["Id"],
                        "domain_name": dist["DomainName"],
                    }
    except Exception:
        pass
    return None


@functools.lru_cache(maxsize=128)
def lookup_oai(comment_prefix: str) -> Optional[dict[str, str]]:
    """Find a CloudFront Origin Access Identity by comment prefix."""
    client = get_client("cloudfront")
    try:
        paginator = client.get_paginator("list_cloud_front_origin_access_identities")
        for page in paginator.paginate():
            for oai in page.get("CloudFrontOriginAccessIdentityList", {}).get("Items", []):
                if oai.get("Comment", "").startswith(comment_prefix):
                    return {
                        "oai_id": oai["Id"],
                        "s3_canonical_user_id": oai.get("S3CanonicalUserId", ""),
                    }
    except Exception:
        pass
    return None


@functools.lru_cache(maxsize=128)
def lookup_certificate(domain_name: str) -> Optional[str]:
    """Find an ACM certificate by domain name (in us-east-1 for CloudFront)."""
    # Always use us-east-1 for CloudFront certificates
    client = boto3.client("acm", region_name="us-east-1")
    try:
        paginator = client.get_paginator("list_certificates")
        for page in paginator.paginate():
            for cert in page.get("CertificateSummaryList", []):
                if cert["DomainName"] == domain_name:
                    result: str = cert["CertificateArn"]
                    return result
    except Exception:
        pass
    return None


@functools.lru_cache(maxsize=128)
def lookup_appsync_api(api_name: str) -> Optional[dict[str, str]]:
    """Find an AppSync API by name."""
    client = get_client("appsync")
    try:
        paginator = client.get_paginator("list_graphql_apis")
        for page in paginator.paginate():
            for api in page.get("graphqlApis", []):
                if api["name"] == api_name:
                    return {
                        "api_id": api["apiId"],
                        "api_name": api["name"],
                        "arn": api["arn"],
                    }
    except Exception:
        pass
    return None


@functools.lru_cache(maxsize=128)
def lookup_appsync_datasource(api_id: str, datasource_name: str) -> Optional[dict[str, str]]:
    """Find an AppSync DataSource by API ID and name."""
    client = get_client("appsync")
    try:
        response = client.get_data_source(apiId=api_id, name=datasource_name)
        ds = response.get("dataSource", {})
        return {
            "name": ds.get("name"),
            "type": ds.get("type"),
            "datasource_arn": ds.get("dataSourceArn"),
        }
    except client.exceptions.NotFoundException:
        return None
    except Exception:
        pass
    return None


@functools.lru_cache(maxsize=128)
def lookup_appsync_domain_name(domain_name: str) -> Optional[dict[str, str]]:
    """Find an AppSync custom domain by domain name."""
    client = get_client("appsync")
    try:
        response = client.list_domain_names()
        for domain in response.get("domainNameConfigs", []):
            if domain["domainName"] == domain_name:
                return {
                    "domain_name": domain["domainName"],
                    "domain_name_arn": domain["domainNameArn"],
                    "appsync_domain_name": domain["appsyncDomainName"],
                    "certificate_arn": domain["certificateArn"],
                    "hosted_zone_id": domain["hostedZoneId"],
                }
    except Exception:
        pass
    return None


@functools.lru_cache(maxsize=128)
def lookup_iam_role(role_name: str) -> Optional[str]:
    """Find an IAM role by name."""
    client = get_client("iam")
    try:
        response = client.get_role(RoleName=role_name)
        result: str = response["Role"]["Arn"]
        return result
    except client.exceptions.NoSuchEntityException:
        return None
    except Exception:
        return None


@functools.lru_cache(maxsize=128)
def lookup_lambda_function(function_name: str) -> Optional[dict[str, str]]:
    """Find a Lambda function by name."""
    client = get_client("lambda")
    try:
        response = client.get_function(FunctionName=function_name)
        return {
            "function_name": response["Configuration"]["FunctionName"],
            "function_arn": response["Configuration"]["FunctionArn"],
        }
    except client.exceptions.ResourceNotFoundException:
        return None
    except Exception:
        return None


@functools.lru_cache(maxsize=128)
def lookup_lambda_layer(layer_name: str) -> Optional[dict[str, Any]]:
    """Find the latest version of a Lambda layer by name."""
    client = get_client("lambda")
    try:
        response = client.list_layer_versions(LayerName=layer_name, MaxItems=1)
        versions = response.get("LayerVersions", [])
        if versions:
            return {
                "layer_name": layer_name,
                "layer_arn": versions[0]["LayerVersionArn"],
                "version": versions[0]["Version"],
            }
    except Exception:
        pass
    return None


@functools.lru_cache(maxsize=128)
def lookup_user_pool_domain(user_pool_id: str) -> Optional[str]:
    """Check if a Cognito User Pool has a custom domain configured."""
    client = get_client("cognito-idp")
    try:
        response = client.describe_user_pool(UserPoolId=user_pool_id)
        custom_domain: Optional[str] = response.get("UserPool", {}).get("CustomDomain")
        if custom_domain:
            return custom_domain
        # Also check the regular (Cognito-hosted) domain
        domain: Optional[str] = response.get("UserPool", {}).get("Domain")
        if domain:
            return domain
    except Exception:
        pass
    return None


@functools.lru_cache(maxsize=128)
def lookup_cognito_domain_cloudfront(domain: str) -> Optional[str]:
    """Get the CloudFront distribution target for a Cognito custom domain.

    When you create a custom domain for Cognito, AWS creates a CloudFront
    distribution and returns its domain name in the describe_user_pool_domain
    response as 'CloudFrontDistribution'.
    """
    client = get_client("cognito-idp")
    try:
        response = client.describe_user_pool_domain(Domain=domain)
        domain_desc = response.get("DomainDescription", {})
        cf_distribution: Optional[str] = domain_desc.get("CloudFrontDistribution")
        if cf_distribution:
            return cf_distribution
    except Exception:
        pass
    return None


@functools.lru_cache(maxsize=128)
def lookup_user_pool_by_id(user_pool_id: str) -> Optional[dict[str, Optional[str]]]:
    """Get a Cognito User Pool by ID (not by name)."""
    client = get_client("cognito-idp")
    try:
        response = client.describe_user_pool(UserPoolId=user_pool_id)
        pool = response.get("UserPool", {})
        return {
            "user_pool_id": pool["Id"],
            "user_pool_name": pool["Name"],
            "custom_domain": pool.get("CustomDomain"),
        }
    except client.exceptions.ResourceNotFoundException:
        return None
    except Exception:
        return None


@functools.lru_cache(maxsize=128)
def lookup_appsync_domain(domain_name: str) -> Optional[dict[str, Optional[str]]]:
    """Find an AppSync custom domain by name."""
    client = get_client("appsync")
    try:
        response = client.get_domain_name(domainName=domain_name)
        config = response.get("domainNameConfig", {})
        return {
            "domain_name": config.get("domainName"),
            "appsync_domain_name": config.get("appsyncDomainName"),
            "certificate_arn": config.get("certificateArn"),
            "hosted_zone_id": config.get("hostedZoneId"),
        }
    except client.exceptions.NotFoundException:
        return None
    except Exception:
        return None


@functools.lru_cache(maxsize=128)
def lookup_route53_record(
    hosted_zone_id: str, record_name: str, record_type: str = "A"
) -> Optional[dict[str, Any]]:
    """Check if a Route53 record exists.

    Args:
        hosted_zone_id: The hosted zone ID (e.g., Z039490427CKS98SYWOJN)
        record_name: The full record name with trailing dot (e.g., dev.kernelworx.app.)
        record_type: The record type (A, CNAME, AAAA, etc.)

    Returns:
        Dict with record info if found, None otherwise
    """
    client = get_client("route53")
    # Ensure record name ends with a dot
    if not record_name.endswith("."):
        record_name = record_name + "."
    try:
        response = client.list_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            StartRecordName=record_name,
            StartRecordType=record_type,
            MaxItems="1",
        )
        records = response.get("ResourceRecordSets", [])
        if (
            records
            and records[0].get("Name") == record_name
            and records[0].get("Type") == record_type
        ):
            record = records[0]
            return {
                "name": record["Name"],
                "type": record["Type"],
                "alias_target": record.get("AliasTarget"),
                "resource_records": record.get("ResourceRecords"),
                "ttl": record.get("TTL"),
            }
    except Exception:
        pass
    return None


@functools.lru_cache(maxsize=128)
def lookup_identity_provider(user_pool_id: str, provider_name: str) -> Optional[dict[str, Any]]:
    """Check if a Cognito identity provider exists.

    Args:
        user_pool_id: The Cognito User Pool ID
        provider_name: The provider name (e.g., "Google", "Facebook", "SignInWithApple")

    Returns:
        Dict with provider info if found, None otherwise
    """
    client = get_client("cognito-idp")
    try:
        response = client.describe_identity_provider(
            UserPoolId=user_pool_id,
            ProviderName=provider_name,
        )
        provider = response.get("IdentityProvider", {})
        return {
            "provider_name": provider.get("ProviderName"),
            "provider_type": provider.get("ProviderType"),
            "creation_date": provider.get("CreationDate"),
            "last_modified_date": provider.get("LastModifiedDate"),
        }
    except client.exceptions.ResourceNotFoundException:
        return None
    except Exception:
        return None


def table_exists(table_name: str) -> bool:
    """Check if a DynamoDB table exists."""
    return lookup_dynamodb_table(table_name) is not None


def bucket_exists(bucket_name: str) -> bool:
    """Check if an S3 bucket exists."""
    return lookup_s3_bucket(bucket_name)
