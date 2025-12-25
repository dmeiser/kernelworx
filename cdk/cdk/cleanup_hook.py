"""
Pre-deployment cleanup for ACM certificates and Route53 validation records.

This module deletes existing ACM certificates and their Route53 validation records
BEFORE deployment so CDK can create fresh ones without conflicts.

This solves the problem: ACM certificates cannot be imported into CloudFormation,
so we must delete existing ones before CDK creates new ones.

Usage:
    from cdk.cleanup_hook import cleanup_before_deploy
    
    cleanup_before_deploy(
        domain_names=["api.dev.kernelworx.app", "login.dev.kernelworx.app"],
        environment_name="dev"
    )
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

import boto3


def cleanup_before_deploy(
    domain_names: list[str],
    site_domain: str | None = None,
    environment_name: str = "dev",
) -> None:
    """
    Delete unmanaged (orphaned) ACM certificates before deployment.
    
    Unmanaged certificates are those not created/managed by CloudFormation.
    These should be cleaned up so CDK can create and manage fresh certificates.
    
    Args:
        domain_names: List of domain names to find and delete certificates for
                      (e.g., ["api.dev.kernelworx.app", "login.dev.kernelworx.app"])
        site_domain: Site domain name for CloudFront (e.g., "dev.kernelworx.app")
                     If provided, its Route53 A record will be deleted so CloudFront
                     can claim the domain alias
        environment_name: Environment name (dev, prod) for logging
    """
    region = os.getenv("AWS_REGION") or "us-east-1"
    
    # Initialize AWS clients
    acm_client = boto3.client("acm", region_name=region)
    cognito_client = boto3.client("cognito-idp", region_name=region)
    route53_client = boto3.client("route53", region_name=region)
    
    try:
        # IMPORTANT: Delete resources that USE certificates BEFORE deleting certificates
        # Order matters: AppSync API → Cognito Domain → CloudFront disconnect → Certificates
        
        # 1. Clean up orphaned AppSync API (may be using api certificate)
        print("\n🧹 Cleaning up orphaned AppSync API...")
        _cleanup_orphaned_appsync_api(environment_name)
        print("   ✅ AppSync API cleanup complete")
        
        # 2. Disconnect Cognito domains (may be using auth certificate)
        print("\n🧹 Disconnecting Cognito custom domains...")
        for domain in domain_names:
            if "login" in domain or "auth" in domain:
                _disconnect_cognito_domain(cognito_client, domain)
        print("   ✅ Cognito domain cleanup complete")
        
        # 3. Disconnect CloudFront from certificate/domain (allows cert deletion without deleting CF)
        if site_domain:
            print(f"\n🧹 Disconnecting CloudFront from certificate and domain...")
            _disconnect_cloudfront_from_certificate(site_domain)
            print("   ✅ CloudFront disconnection complete")
        
        # 4. NOW we can safely delete certificates
        print("\n🧹 Deleting orphaned (unmanaged) ACM certificates...")
        
        # Check for unmanaged certificates that this stack will create
        # Stack creates 3 certificates: api, site, and cognito
        certificates_to_check = []
        
        # Add API domain certificate
        for domain in domain_names:
            if "api." in domain:
                certificates_to_check.append(("api", domain))
        
        # Add site domain certificate  
        if site_domain:
            certificates_to_check.append(("site", site_domain))
        
        # Add Cognito domain certificate
        for domain in domain_names:
            if "auth." in domain or "login." in domain:
                certificates_to_check.append(("cognito", domain))
        
        # Track certificates we've already deleted to avoid duplicate attempts
        deleted_cert_arns = set()
        
        for cert_type, domain in certificates_to_check:
            cert_arn = _find_certificate_arn(acm_client, domain)
            if cert_arn:
                # Skip if we already deleted this certificate
                if cert_arn in deleted_cert_arns:
                    print(f"   ℹ️  Certificate for {domain} already handled")
                    continue
                    
                if _is_unmanaged_certificate(cert_arn):
                    print(f"   🗑️  Found unmanaged {cert_type} certificate for {domain}")
                    _delete_acm_certificate(acm_client, cert_arn)
                    deleted_cert_arns.add(cert_arn)
                    print(f"   ✅ Deleted orphaned {cert_type} certificate")
                else:
                    print(f"   ℹ️  {cert_type.title()} certificate exists and is CloudFormation-managed: {domain}")
            else:
                print(f"   ℹ️  No {cert_type} certificate found for: {domain}")
        
        # 5. Clean up orphaned Route53 validation records
        print("\n🧹 Cleaning up orphaned Route53 validation records...")
        _cleanup_orphaned_route53_records(route53_client, domain_names)
        print("   ✅ Route53 cleanup complete")
        
        # 6. Delete the site domain's A record so CloudFront can claim the domain alias
        if site_domain:
            print(f"\n🧹 Cleaning up Route53 A record for CloudFront domain: {site_domain}...")
            _delete_cloudfront_domain_record(route53_client, site_domain)
            print("   ✅ CloudFront domain A record deleted")
        
        # 7. Clean up orphaned SMS role (causes conflicts if it exists)
        print("\n🧹 Cleaning up orphaned Cognito SMS role...")
        _cleanup_orphaned_sms_role(environment_name)
        print("   ✅ SMS role cleanup complete")
        
    except Exception as e:
        print(f"⚠️  Warning: Cleanup error (proceeding anyway): {e}")
        # Don't fail the deployment - cleanup is optional


def _find_certificate_arn(client: Any, domain_name: str) -> str | None:
    """Find an ACM certificate ARN by domain name."""
    try:
        paginator = client.get_paginator("list_certificates")
        for page in paginator.paginate(CertificateStatuses=["ISSUED", "PENDING_VALIDATION"]):
            for cert in page.get("CertificateSummaryList", []):
                cert_arn = cert.get("CertificateArn")
                cert_domain = cert.get("DomainName")
                
                # Check main domain and SANs
                if cert_domain == domain_name:
                    return cert_arn
                
                # Check subject alternative names
                try:
                    detail = client.describe_certificate(CertificateArn=cert_arn)
                    sans = detail.get("Certificate", {}).get("SubjectAlternativeNames", [])
                    if domain_name in sans:
                        return cert_arn
                except Exception:
                    pass
    except Exception as e:
        print(f"   ⚠️  Could not list certificates: {e}")
    
    return None


def _is_unmanaged_certificate(cert_arn: str) -> bool:
    """Check if a certificate is unmanaged (not by CloudFormation)."""
    acm_client = boto3.client("acm", region_name=os.getenv("AWS_REGION", "us-east-1"))
    try:
        cert_detail = acm_client.describe_certificate(CertificateArn=cert_arn)
        tags = cert_detail.get("Certificate", {}).get("Tags", [])
        
        # Check for CloudFormation stack tag OR our custom Application tag
        for tag in tags:
            key = tag.get("Key")
            # CloudFormation automatically adds this tag
            if key == "aws:cloudformation:stack-name":
                return False
            # Our custom tag from CDK stack
            if key == "Application" and tag.get("Value") == "kernelworx":
                return False
        
        # If no recognized tags, it's unmanaged
        return True
    except Exception:
        # If we can't determine, assume it's unmanaged
        return True


def _delete_acm_certificate(client: Any, cert_arn: str) -> None:
    """Delete an ACM certificate."""
    try:
        client.delete_certificate(CertificateArn=cert_arn)
    except Exception as e:
        print(f"   ⚠️  Could not delete certificate: {e}")


def _disconnect_cognito_domain(client: Any, domain_name: str) -> None:
    """Delete a Cognito custom domain so its certificate can be deleted."""
    try:
        print(f"      ⏳ Deleting Cognito domain: {domain_name}")
        
        # Get the domain description to find the user pool ID
        domain_desc = client.describe_user_pool_domain(Domain=domain_name)
        domain_info = domain_desc.get("DomainDescription", {})
        
        if not domain_info:
            print(f"      ℹ️  Domain not found")
            return
            
        user_pool_id = domain_info.get("UserPoolId")
        if not user_pool_id:
            print(f"      ⚠️  Could not find UserPoolId for domain")
            return
        
        # Delete the user pool domain (this frees up the certificate)
        client.delete_user_pool_domain(
            Domain=domain_name,
            UserPoolId=user_pool_id
        )
        print(f"      ✅ Cognito domain deleted")
        
        # Wait a moment for the deletion to propagate
        import time
        time.sleep(2)
        
    except Exception as e:
        print(f"      ⚠️  Could not delete Cognito domain: {e}")


def _cleanup_orphaned_route53_records(
    client: Any, domain_names: list[str]
) -> None:
    """Clean up orphaned Route53 validation records for deleted certificates."""
    try:
        # Look up hosted zones for these domains
        zones = _find_hosted_zones(client, domain_names)
        
        for zone_id, domain in zones:
            records = _list_hosted_zone_records(client, zone_id)
            
            # Find validation records for this domain
            for record in records:
                if record.get("Type") == "CNAME" and _is_validation_record(record):
                    # Check if this is a validation record for our domain
                    if _matches_domain(record.get("Name", ""), domain):
                        _delete_route53_record(client, zone_id, record)
                        print(f"   ✅ Deleted validation record: {record['Name']}")
    except Exception as e:
        print(f"   ⚠️  Could not clean Route53 records: {e}")


def _delete_cloudfront_domain_record(client: Any, domain_name: str) -> None:
    """
    Delete the Route53 A/AAAA record for a CloudFront domain alias.
    
    ONLY deletes records that are NOT managed by CloudFormation.
    This allows CloudFront to claim the domain alias without conflicts
    from orphaned records, while preserving CloudFormation-managed records.
    """
    try:
        # Find the hosted zone - list all and find the best match
        print(f"      ⏳ Finding hosted zone for {domain_name}")
        all_zones_response = client.list_hosted_zones()
        zones = all_zones_response.get("HostedZones", [])
        
        # Find the best matching zone (longest matching domain)
        best_zone = None
        best_domain_length = 0
        
        for zone in zones:
            zone_domain = zone["Name"].rstrip(".")
            if domain_name.endswith(zone_domain):
                if len(zone_domain) > best_domain_length:
                    best_zone = zone
                    best_domain_length = len(zone_domain)
        
        if not best_zone:
            print(f"      ℹ️  No hosted zones found for {domain_name}")
            return
        
        zone_id = best_zone["Id"].split("/")[-1]
        zone_name = best_zone["Name"].rstrip(".")
        print(f"      ℹ️  Found hosted zone: {zone_name} ({zone_id})")
        
        # Get stack name to check CloudFormation ownership
        environment_name = os.getenv("ENVIRONMENT", "dev")
        region = os.getenv("AWS_REGION") or "us-east-1"
        region_abbrevs = {"us-east-1": "ue1", "us-east-2": "ue2", "us-west-1": "uw1", "us-west-2": "uw2"}
        region_abbrev = region_abbrevs.get(region, region[:3])
        stack_name = f"kernelworx-{region_abbrev}-{environment_name}"
        
        # List CloudFormation stack resources to check if record is managed
        cfn_client = boto3.client("cloudformation", region_name=region)
        try:
            stack_resources = cfn_client.list_stack_resources(StackName=stack_name)
            managed_record_ids = {
                r["PhysicalResourceId"]
                for r in stack_resources["StackResourceSummaries"]
                if r["ResourceType"] == "AWS::Route53::RecordSet"
            }
        except Exception:
            managed_record_ids = set()
        
        # List records in the zone
        records = _list_hosted_zone_records(client, zone_id)
        
        # Find records for this domain (exact match with or without trailing dot)
        domain_with_dot = f"{domain_name}."
        found = False
        
        for record in records:
            record_name = record.get("Name", "")
            record_type = record.get("Type", "")
            
            # Match the domain name (Route53 returns names with trailing dot)
            if record_name == domain_with_dot or record_name == domain_name:
                if record_type in ["A", "AAAA"]:
                    # Check if this record is managed by CloudFormation
                    if domain_name in managed_record_ids:
                        print(f"      ℹ️  {record_type} record is CloudFormation-managed, skipping")
                        found = True
                        continue
                    
                    print(f"      🗑️  Found unmanaged {record_type} record: {record_name}")
                    _delete_route53_record(client, zone_id, record)
                    print(f"      ✅ Deleted unmanaged {record_type} record for {domain_name}")
                    found = True
        
        if not found:
            print(f"      ℹ️  No A/AAAA records found for {domain_name}")
    
    except Exception as e:
        print(f"      ⚠️  Could not delete Route53 record for {domain_name}: {e}")




def _find_hosted_zones(client: Any, domain_names: list[str]) -> list[tuple[str, str]]:
    """Find hosted zone IDs for the given domain names."""
    zones = []
    try:
        paginator = client.get_paginator("list_hosted_zones")
        for page in paginator.paginate():
            for zone in page.get("HostedZones", []):
                zone_id = zone["Id"].split("/")[-1]
                zone_domain = zone["Name"].rstrip(".")
                
                # Check if any of our domains match this zone
                for domain in domain_names:
                    if domain.endswith(zone_domain):
                        zones.append((zone_id, zone_domain))
                        break
    except Exception as e:
        print(f"   ⚠️  Could not list hosted zones: {e}")
    
    return zones


def _list_hosted_zone_records(client: Any, hosted_zone_id: str) -> list[dict[str, Any]]:
    """List all records in a Route53 hosted zone."""
    records = []
    try:
        paginator = client.get_paginator("list_resource_record_sets")
        for page in paginator.paginate(HostedZoneId=hosted_zone_id):
            records.extend(page.get("ResourceRecordSets", []))
    except Exception as e:
        print(f"   ⚠️  Could not list hosted zone records: {e}")
    
    return records


def _is_validation_record(record: dict[str, Any]) -> bool:
    """Check if a record is likely an ACM validation record (CNAME with _acme or similar)."""
    name = record.get("Name", "").lower()
    return "_acme-challenge" in name or "_validation" in name


def _matches_domain(record_name: str, domain: str) -> bool:
    """Check if a Route53 record name corresponds to a domain."""
    record_name = record_name.rstrip(".").lower()
    domain = domain.lower()
    
    return record_name.endswith(domain) or domain.endswith(record_name.split(".")[0])


def _delete_route53_record(
    client: Any, hosted_zone_id: str, record: dict[str, Any]
) -> None:
    """Delete a Route53 record (handles both regular and ALIAS records)."""
    try:
        resource_record_set = {
            "Name": record["Name"],
            "Type": record["Type"],
        }
        
        # Handle ALIAS records (used by CloudFront, ALB, etc)
        if "AliasTarget" in record:
            resource_record_set["AliasTarget"] = record["AliasTarget"]
        else:
            # Regular records have TTL and ResourceRecords
            if "TTL" in record:
                resource_record_set["TTL"] = record["TTL"]
            if "ResourceRecords" in record:
                resource_record_set["ResourceRecords"] = record["ResourceRecords"]
        
        change_batch = {
            "Changes": [
                {
                    "Action": "DELETE",
                    "ResourceRecordSet": resource_record_set,
                }
            ]
        }
        
        client.change_resource_record_sets(
            HostedZoneId=hosted_zone_id, ChangeBatch=change_batch
        )
    except Exception as e:
        print(f"   ⚠️  Could not delete Route53 record {record['Name']}: {e}")


def delete_appsync_api(api_name: str) -> None:
    """
    Delete the AppSync GraphQL API before deployment.
    
    Since AppSync APIs cannot be imported into CloudFormation, we must delete
    the existing one before deployment so CDK can create a fresh one that's
    fully managed.
    
    Args:
        api_name: Name of the AppSync API to delete (e.g., "kernelworx-api-ue1-dev")
    """
    region = os.getenv("AWS_REGION") or "us-east-1"
    appsync_client = boto3.client("appsync", region_name=region)
    
    try:
        # First list all APIs to find the one with matching name
        paginator = appsync_client.get_paginator("list_graphql_apis")
        api_id = None
        for page in paginator.paginate():
            for api in page.get("graphqlApis", []):
                if api["name"] == api_name:
                    api_id = api["apiId"]
                    break
            if api_id:
                break
        
        if not api_id:
            print(f"   ℹ️  AppSync API not found: {api_name}")
            return
        
        # Delete the API
        print(f"   🗑️  Deleting AppSync API: {api_name} ({api_id})")
        appsync_client.delete_graphql_api(apiId=api_id)
        print(f"   ✅ Deleted AppSync API: {api_name}")
    except Exception as e:
        print(f"   ⚠️  Could not delete AppSync API {api_name}: {e}")


def _cleanup_orphaned_appsync_api(environment_name: str) -> None:
    """
    Delete orphaned AppSync API before deployment.
    
    AppSync APIs cannot be imported into CloudFormation, so we must delete
    existing unmanaged APIs before CDK creates a fresh CloudFormation-managed one.
    """
    region = os.getenv("AWS_REGION") or "us-east-1"
    region_abbrev = os.getenv("REGION_ABBREV", region[:3])  # Try to get abbrev from env
    
    # Try common region abbreviations if not provided
    region_abbrevs = {
        "us-east-1": "ue1",
        "us-east-2": "ue2",
        "us-west-1": "uw1",
        "us-west-2": "uw2",
    }
    
    if region in region_abbrevs:
        region_abbrev = region_abbrevs[region]
    
    api_name = f"kernelworx-api-{region_abbrev}-{environment_name}"
    delete_appsync_api(api_name)


def _cleanup_orphaned_sms_role(environment_name: str) -> None:
    """
    Ensure SMS role has required SNS permissions before CloudFormation import.
    
    CloudFormation validates the UserPool configuration during import, which includes
    checking that the SMS role has SNS publish permissions. We must add the policy
    BEFORE the import operation, not as part of it.
    """
    region = os.getenv("AWS_REGION") or "us-east-1"
    
    # Known User Pool IDs
    KNOWN_USER_POOL_IDS = {
        "dev": "us-east-1_sDiuCOarb",
        # Add prod when ready
    }
    
    user_pool_id = KNOWN_USER_POOL_IDS.get(environment_name)
    if not user_pool_id:
        return
    
    try:
        cognito_client = boto3.client("cognito-idp", region_name=region)
        iam_client = boto3.client("iam", region_name=region)
        
        # Get the UserPool to find which SMS role it uses
        pool_desc = cognito_client.describe_user_pool(UserPoolId=user_pool_id)
        pool_details = pool_desc.get("UserPool", {})
        sms_config = pool_details.get("SmsConfiguration", {})
        sms_role_arn = sms_config.get("SnsCallerArn")
        
        if not sms_role_arn:
            print(f"      ℹ️  No SMS role configured on UserPool")
            return
        
        # Extract role name from ARN
        role_name = sms_role_arn.split("/")[-1]
        
        # Check if role exists
        print(f"      ⏳ Checking SMS role: {role_name}")
        iam_client.get_role(RoleName=role_name)
        
        # Ensure it has the required inline policy
        policies = iam_client.list_role_policies(RoleName=role_name)
        if "UserPoolSmsPolicy" not in policies.get("PolicyNames", []):
            print(f"      📝 Adding SNS permissions (required for import validation)")
            iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName="UserPoolSmsPolicy",
                PolicyDocument="""{
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Effect": "Allow",
                        "Action": "sns:Publish",
                        "Resource": "*"
                    }]
                }"""
            )
            print(f"      ✅ Added SNS permissions to SMS role")
        else:
            print(f"      ✅ SMS role already has SNS permissions")
        
    except iam_client.exceptions.NoSuchEntityException:
        print(f"      ℹ️  SMS role not found (CloudFormation will create it)")
    except Exception as e:
        print(f"      ⚠️  Could not configure SMS role: {e}")


def _disconnect_cloudfront_from_certificate(site_domain: str) -> None:
    """
    Disconnect CloudFront distribution from custom domain and certificate.
    
    This allows UNMANAGED certificates to be deleted without deleting the CloudFront distribution.
    Only runs if the certificate is NOT managed by CloudFormation.
    """
    region = os.getenv("AWS_REGION") or "us-east-1"
    cloudfront_client = boto3.client("cloudfront", region_name=region)
    acm_client = boto3.client("acm", region_name=region)
    
    try:
        # First, find the certificate ARN for this domain (might cover multiple domains)
        cert_arn = _find_certificate_arn(acm_client, site_domain)
        if not cert_arn:
            print(f"      ℹ️  No certificate found for {site_domain}")
            return
        
        # CRITICAL: Only disconnect if the certificate is NOT managed by CloudFormation
        if not _is_unmanaged_certificate(cert_arn):
            print(f"      ℹ️  Certificate is CloudFormation-managed, skipping disconnect")
            return
        
        print(f"      ℹ️  Found unmanaged certificate: {cert_arn}")
        
        # Get certificate details to see what's using it
        cert_response = acm_client.describe_certificate(CertificateArn=cert_arn)
        in_use_by = cert_response.get("Certificate", {}).get("InUseBy", [])
        
        # Find CloudFront distributions using this certificate
        for resource_arn in in_use_by:
            if "cloudfront" in resource_arn.lower():
                # Extract distribution ID from ARN: arn:aws:cloudfront::account:distribution/ID
                distribution_id = resource_arn.split("/")[-1]
                print(f"      ℹ️  Found CloudFront distribution using certificate: {distribution_id}")
                
                # Get current distribution config
                response = cloudfront_client.get_distribution_config(Id=distribution_id)
                config = response["DistributionConfig"]
                etag = response["ETag"]
                
                # Remove custom domain aliases
                if config.get("Aliases", {}).get("Items"):
                    print(f"      🗑️  Removing domain aliases from distribution")
                    config["Aliases"] = {"Quantity": 0, "Items": []}
                
                # Remove custom certificate (use default CloudFront cert)
                if config.get("ViewerCertificate", {}).get("ACMCertificateArn"):
                    print(f"      🗑️  Removing custom certificate from distribution")
                    config["ViewerCertificate"] = {
                        "CloudFrontDefaultCertificate": True,
                        "MinimumProtocolVersion": "TLSv1",
                    }
                
                # Update distribution
                print(f"      ⏳ Updating CloudFront distribution...")
                cloudfront_client.update_distribution(
                    Id=distribution_id,
                    DistributionConfig=config,
                    IfMatch=etag,
                )
                print(f"      ✅ Disconnected CloudFront from unmanaged certificate and domain")
                
                # Wait a moment for the update to start processing
                import time
                time.sleep(2)
        
        if not in_use_by:
            print(f"      ℹ️  Certificate not in use by any resources")
        
    except Exception as e:
        print(f"      ⚠️  Could not disconnect CloudFront: {e}", file=sys.stderr)


def generate_import_file(
    stack_name: str,
    environment_name: str,
    region_abbrev: str,
) -> str | None:
    """
    Dynamically generate a resources-to-import.json file for resources that exist
    in AWS but are not yet managed by CloudFormation.
    
    This hook:
    1. Looks up resources in AWS
    2. Checks which are NOT in CloudFormation stack
    3. Generates a temporary import file
    4. Returns the file path (to be used with --resource-file)
    
    The file should be deleted after deployment (handled by deploy.sh).
    
    Args:
        stack_name: CloudFormation stack name (e.g., "kernelworx-ue1-dev")
        environment_name: Environment name (dev, prod)
        region_abbrev: Region abbreviation (ue1, ue2, etc.)
    
    Returns:
        Path to generated import file, or None if no resources need importing
    """
    region = os.getenv("AWS_REGION") or "us-east-1"
    
    # Initialize AWS clients
    cfn_client = boto3.client("cloudformation", region_name=region)
    dynamodb_client = boto3.client("dynamodb", region_name=region)
    s3_client = boto3.client("s3", region_name=region)
    cognito_client = boto3.client("cognito-idp", region_name=region)
    
    print(f"\n🔍 Checking for resources to import into stack: {stack_name}", file=sys.stderr)
    
    # Get existing stack resources (if stack exists)
    stack_resources = set()
    try:
        paginator = cfn_client.get_paginator("list_stack_resources")
        for page in paginator.paginate(StackName=stack_name):
            for resource in page.get("StackResourceSummaries", []):
                physical_id = resource.get("PhysicalResourceId", "")
                stack_resources.add(physical_id)
    except cfn_client.exceptions.ClientError as e:
        if "does not exist" in str(e):
            print(f"   ℹ️  Stack does not exist yet (first deployment)", file=sys.stderr)
        else:
            print(f"   ⚠️  Could not list stack resources: {e}", file=sys.stderr)
    
    # Resources to import
    resources_to_import = []
    
    # Check DynamoDB tables
    _check_dynamodb_tables(
        dynamodb_client, stack_resources, resources_to_import, environment_name, region_abbrev
    )
    
    # Check S3 buckets
    _check_s3_buckets(
        s3_client, stack_resources, resources_to_import, environment_name, region_abbrev
    )
    
    # Check Cognito User Pool
    _check_cognito_user_pool(
        cognito_client, stack_resources, resources_to_import, environment_name, region_abbrev
    )
    
    # If no resources to import, return None
    if not resources_to_import:
        print("   ✅ All resources already in CloudFormation (nothing to import)", file=sys.stderr)
        return None
    
    # Generate import file in CDK format
    # CDK import expects: { "LogicalId": { "IdentifierKey": "PhysicalId" }, ... }
    import_file_path = Path(__file__).parent.parent / ".cdk-import-resources.json"
    
    cdk_import_mapping = {}
    for resource in resources_to_import:
        logical_id = resource["LogicalResourceId"]
        # Keep the ResourceIdentifier structure (e.g., {"TableName": "..."})
        cdk_import_mapping[logical_id] = resource["ResourceIdentifier"]
    
    with open(import_file_path, "w") as f:
        json.dump(cdk_import_mapping, f, indent=2)
    
    print(f"   📝 Generated import file: {import_file_path}", file=sys.stderr)
    print(f"   📦 Resources to import: {len(cdk_import_mapping)}", file=sys.stderr)
    for logical_id, identifier in cdk_import_mapping.items():
        print(f"      - {logical_id}: {identifier}", file=sys.stderr)
    
    return str(import_file_path)


def _check_dynamodb_tables(
    client: Any,
    stack_resources: set[str],
    resources_to_import: list[dict[str, Any]],
    environment_name: str,
    region_abbrev: str,
) -> None:
    """Check if DynamoDB tables exist but are not in CloudFormation."""
    table_configs = [
        ("app", "PsmApp130C1A95"),
        ("profiles", "ProfilesTableV2BDCD95E8"),
        ("campaigns", "CampaignsTableV238708242"),
        ("orders", "OrdersTableV28A3E7102"),
        ("accounts", "AccountsTable81C15AE5"),
        ("catalogs", "CatalogsTableA9E7181D"),
        ("shares", "SharesTableB39A8EF0"),
        ("invites", "InvitesTableE9630325"),
        ("shared-campaigns", "SharedCampaignsTableBA6812A9"),
    ]
    
    for table_suffix, logical_id in table_configs:
        # Table names follow pattern: kernelworx-{suffix}-{region_abbrev}-{env}
        physical_table_name = f"kernelworx-{table_suffix}-{region_abbrev}-{environment_name}"
        
        # Check if table exists in AWS
        try:
            client.describe_table(TableName=physical_table_name)
            table_exists = True
        except client.exceptions.ResourceNotFoundException:
            table_exists = False
        except Exception as e:
            print(f"   ⚠️  Could not check table {physical_table_name}: {e}", file=sys.stderr)
            continue
        
        # If table exists but not in CloudFormation, add to import list
        if table_exists and physical_table_name not in stack_resources:
            resources_to_import.append({
                "ResourceType": "AWS::DynamoDB::Table",
                "LogicalResourceId": logical_id,
                "ResourceIdentifier": {"TableName": physical_table_name},
            })
            print(f"   🔍 Found unmanaged table: {physical_table_name}", file=sys.stderr)


def _check_s3_buckets(
    client: Any,
    stack_resources: set[str],
    resources_to_import: list[dict[str, Any]],
    environment_name: str,
    region_abbrev: str,
) -> None:
    """Check if S3 buckets exist but are not in CloudFormation."""
    bucket_configs = [
        ("static", "StaticAssetsDDEE9873"),
        ("exports", "Exports25637AFB"),
    ]
    
    for bucket_suffix, logical_id in bucket_configs:
        # Bucket names follow pattern: kernelworx-{suffix}-{region_abbrev}-{env}
        expected_bucket_name = f"kernelworx-{bucket_suffix}-{region_abbrev}-{environment_name}"
        
        # Check if bucket exists
        try:
            client.head_bucket(Bucket=expected_bucket_name)
            bucket_exists = True
        except client.exceptions.NoSuchBucket:
            bucket_exists = False
        except Exception as e:
            print(f"   ⚠️  Could not check bucket {expected_bucket_name}: {e}", file=sys.stderr)
            continue
        
        # If bucket exists but not in CloudFormation, add to import list
        if bucket_exists and expected_bucket_name not in stack_resources:
            resources_to_import.append({
                "ResourceType": "AWS::S3::Bucket",
                "LogicalResourceId": logical_id,
                "ResourceIdentifier": {"BucketName": expected_bucket_name},
            })
            print(f"   🔍 Found unmanaged bucket: {expected_bucket_name}", file=sys.stderr)


def _check_cognito_user_pool(
    client: Any,
    stack_resources: set[str],
    resources_to_import: list[dict[str, Any]],
    environment_name: str,
    region_abbrev: str,
) -> None:
    """
    Check if Cognito UserPool, UserPoolDomain, and SMS Role exist but are not in CloudFormation.
    """
    # Known User Pool IDs
    KNOWN_USER_POOL_IDS = {
        "dev": "us-east-1_sDiuCOarb",
        # Add prod when ready
    }
    
    user_pool_id = KNOWN_USER_POOL_IDS.get(environment_name)
    if not user_pool_id:
        return
    
    # Get the UserPool to find which SMS role it uses
    pool_details = None
    try:
        pool_desc = client.describe_user_pool(UserPoolId=user_pool_id)
        pool_details = pool_desc.get("UserPool", {})
    except client.exceptions.ResourceNotFoundException:
        return
    except Exception as e:
        print(f"   ⚠️  Could not check user pool {user_pool_id}: {e}", file=sys.stderr)
        return
    
    # Get the SMS role ARN from the UserPool
    sms_config = pool_details.get("SmsConfiguration", {})
    sms_role_arn = sms_config.get("SnsCallerArn")
    sms_role_name = None
    if sms_role_arn:
        # Extract role name from ARN: arn:aws:iam::ACCOUNT:role/ROLE_NAME
        sms_role_name = sms_role_arn.split("/")[-1]
    
    # Check for SMS role (use the one UserPool actually references)
    if sms_role_name:
        iam_client = boto3.client("iam")
        try:
            iam_client.get_role(RoleName=sms_role_name)
            role_exists = True
        except iam_client.exceptions.NoSuchEntityException:
            role_exists = False
        except Exception as e:
            print(f"   ⚠️  Could not check SMS role {sms_role_name}: {e}", file=sys.stderr)
            role_exists = False
        
        # If role exists but not in CloudFormation, add to import list
        if role_exists and sms_role_name not in stack_resources:
            resources_to_import.append({
                "ResourceType": "AWS::IAM::Role",
                "LogicalResourceId": "UserPoolsmsRole1998E37F",
                "ResourceIdentifier": {"RoleName": sms_role_name},
            })
            print(f"   🔍 Found unmanaged SMS role: {sms_role_name}", file=sys.stderr)
    
    # Check if user pool exists and add to import if needed
    pool_exists = bool(pool_details)
    if pool_exists and user_pool_id not in stack_resources:
        resources_to_import.append({
            "ResourceType": "AWS::Cognito::UserPool",
            "LogicalResourceId": "UserPool6BA7E5F2",
            "ResourceIdentifier": {"UserPoolId": user_pool_id},
        })
        print(f"   🔍 Found unmanaged user pool: {user_pool_id}", file=sys.stderr)
    
    # Check if UserPoolDomain exists
    custom_domain = f"login.{environment_name}.kernelworx.app"
    try:
        domain_desc = client.describe_user_pool_domain(Domain=custom_domain)
        domain_info = domain_desc.get("DomainDescription", {})
        domain_exists = bool(domain_info and domain_info.get("UserPoolId"))
    except client.exceptions.ResourceNotFoundException:
        domain_exists = False
    except Exception as e:
        print(f"   ⚠️  Could not check user pool domain {custom_domain}: {e}", file=sys.stderr)
        domain_exists = False
    
    # If domain exists but not in CloudFormation, add to import list
    if domain_exists and custom_domain not in stack_resources:
        resources_to_import.append({
            "ResourceType": "AWS::Cognito::UserPoolDomain",
            "LogicalResourceId": "UserPoolDomain5479B217",
            "ResourceIdentifier": {"Domain": custom_domain},
        })
        print(f"   🔍 Found unmanaged user pool domain: {custom_domain}", file=sys.stderr)




