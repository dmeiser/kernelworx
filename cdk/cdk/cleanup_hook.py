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


def _is_cf_managed_resource(resource_type: str, physical_id: str, environment_name: str) -> bool:
    """
    Check if a resource is managed by CloudFormation.

    Safety-first: returns True (managed) if we cannot determine ownership to avoid
    accidentally deleting CloudFormation-managed resources.

    Args:
        resource_type: CloudFormation resource type (e.g., 'AWS::AppSync::GraphQLApi')
        physical_id: Physical resource ID to check (e.g., API ID, ARN, or domain name)
        environment_name: Environment name (e.g., 'dev') to build the stack name

    Returns:
        True if resource is CloudFormation-managed or unknown, False if unmanaged
    """
    region = os.getenv("AWS_REGION") or "us-east-1"
    region_abbrevs = {
        "us-east-1": "ue1",
        "us-east-2": "ue2",
        "us-west-1": "uw1",
        "us-west-2": "uw2",
    }
    region_abbrev = region_abbrevs.get(region, region[:3])
    stack_name = f"kernelworx-{region_abbrev}-{environment_name}"

    cfn_client = boto3.client("cloudformation", region_name=region)
    try:
        paginator = cfn_client.get_paginator("list_stack_resources")
        for page in paginator.paginate(StackName=stack_name):
            for resource in page.get("StackResourceSummaries", []):
                if resource.get("ResourceType") == resource_type:
                    cf_physical_id = resource.get("PhysicalResourceId", "")
                    # Check exact match OR if physical_id is contained in CF's physical ID
                    # (handles cases where CF stores ARN but we have just the ID)
                    if cf_physical_id == physical_id or physical_id in cf_physical_id:
                        return True
    except Exception as e:
        print(f"   ⚠️  Could not list CloudFormation stack resources for {stack_name}: {e}")
        # Fail safe: treat as managed to avoid accidental deletion
        return True

    return False


def cleanup_before_deploy(
    domain_names: list[str],
    site_domain: str | None = None,
    environment_name: str = "dev",
    dry_run: bool = False,
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
        dry_run: If True, only report what would be deleted without actually deleting
    """
    if dry_run:
        print("\n" + "=" * 70)
        print("🔍 DRY RUN MODE - No changes will be made")
        print("=" * 70)

    region = os.getenv("AWS_REGION") or "us-east-1"

    # Initialize AWS clients
    acm_client = boto3.client("acm", region_name=region)
    cognito_client = boto3.client("cognito-idp", region_name=region)
    route53_client = boto3.client("route53", region_name=region)

    try:
        # IMPORTANT: Delete resources that USE certificates BEFORE deleting certificates
        # Order matters: AppSync Domain → AppSync API → Cognito Domain → CloudFront → Certificates

        # 0. Clean up orphaned AppSync custom domain (must be deleted before cert)
        print("\n🧹 Checking AppSync custom domains...")
        api_domains_cleaned: list[str] = []
        for domain in domain_names:
            if "api." in domain:
                _delete_orphaned_appsync_domain(domain, environment_name, dry_run=dry_run)
                api_domains_cleaned.append(domain)

        # 0.5. Clean up orphaned Route53 CNAME records for API domains
        print("\n🧹 Checking Route53 CNAME records for API domains...")
        for domain in api_domains_cleaned:
            _delete_api_domain_cname_record(
                route53_client, domain, environment_name, dry_run=dry_run
            )

        # 1. Clean up orphaned AppSync API (may be using api certificate)
        print("\n🧹 Checking AppSync API...")
        _cleanup_orphaned_appsync_api(environment_name, dry_run=dry_run)

        # 2. Disconnect Cognito domains (may be using auth certificate)
        print("\n🧹 Checking Cognito custom domains...")
        for domain in domain_names:
            if "login" in domain or "auth" in domain:
                _disconnect_cognito_domain(
                    cognito_client, domain, environment_name, dry_run=dry_run
                )

        # 3. Disconnect CloudFront from certificate/domain (allows cert deletion without deleting CF)
        if site_domain:
            print("\n🧹 Checking CloudFront certificate binding...")
            _disconnect_cloudfront_from_certificate(site_domain, environment_name, dry_run=dry_run)

            # 3b. Delete orphaned CloudFront distribution so CDK can create a new one
            print("\n🧹 Checking for orphaned CloudFront distribution...")
            _delete_orphaned_cloudfront_distribution(site_domain, environment_name, dry_run=dry_run)

        # 4. NOW we can safely delete certificates
        print("\n🧹 Checking ACM certificates...")

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

                if _is_unmanaged_certificate(cert_arn, environment_name):
                    print(f"   🗑️  Found unmanaged {cert_type} certificate for {domain}")
                    _delete_acm_certificate(acm_client, cert_arn, dry_run=dry_run)
                    deleted_cert_arns.add(cert_arn)
                    if dry_run:
                        print(f"   [DRY RUN] Would delete orphaned {cert_type} certificate")
                    else:
                        print(f"   ✅ Deleted orphaned {cert_type} certificate")
                else:
                    print(
                        f"   ℹ️  {cert_type.title()} certificate exists and is CloudFormation-managed: {domain}"
                    )
            else:
                print(f"   ℹ️  No {cert_type} certificate found for: {domain}")

        # 5. Clean up orphaned Route53 validation records
        print("\n🧹 Checking Route53 validation records...")
        _cleanup_orphaned_route53_records(route53_client, domain_names, dry_run=dry_run)

        # 6. Delete the site domain's A record so CloudFront can claim the domain alias
        if site_domain:
            print(f"\n🧹 Checking Route53 A record for CloudFront domain: {site_domain}...")
            _delete_cloudfront_domain_record(route53_client, site_domain, dry_run=dry_run)

        # 7. Clean up orphaned SMS role (causes conflicts if it exists)
        print("\n🧹 Checking Cognito SMS role...")
        _cleanup_orphaned_sms_role(environment_name, dry_run=dry_run)

        if dry_run:
            print("\n" + "=" * 70)
            print("🔍 DRY RUN COMPLETE - No changes were made")
            print("=" * 70 + "\n")

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


def _is_unmanaged_certificate(cert_arn: str, environment_name: str | None = None) -> bool:
    """Check if a certificate is unmanaged (not by CloudFormation).

    Safety-first: return False (managed) if we cannot determine ownership to avoid
    deleting CloudFormation-managed certificates accidentally.

    The function checks, in this order:
    1. ACM certificate tags for Application=kernelworx and (if provided) Environment=environment_name
    2. CloudFormation stack resources for a certificate with PhysicalResourceId == cert_arn

    Args:
        cert_arn: ARN of the certificate to check
        environment_name: optional environment name (e.g., 'dev') to build the stack name
    Returns:
        True if certificate is unmanaged (safe to delete), False if it's managed or unknown
    """
    acm_client = boto3.client("acm", region_name=os.getenv("AWS_REGION", "us-east-1"))
    region = os.getenv("AWS_REGION") or "us-east-1"

    try:
        cert_detail = acm_client.describe_certificate(CertificateArn=cert_arn)
        tags = cert_detail.get("Certificate", {}).get("Tags", [])
        tag_map = {t.get("Key"): t.get("Value") for t in tags}

        # If tagged as kernelworx application, and environment matches (if provided), treat as managed
        if tag_map.get("Application") == "kernelworx":
            if environment_name is None or tag_map.get("Environment") == environment_name:
                print(
                    "   ℹ️  Certificate has kernelworx tags (Application, Environment). Treating as managed"
                )
                return False

        # If environment_name provided, check CloudFormation stack resources for this cert ARN
        if environment_name:
            region_abbrevs = {
                "us-east-1": "ue1",
                "us-east-2": "ue2",
                "us-west-1": "uw1",
                "us-west-2": "uw2",
            }
            region_abbrev = region_abbrevs.get(region, region[:3])
            stack_name = f"kernelworx-{region_abbrev}-{environment_name}"

            cfn_client = boto3.client("cloudformation", region_name=region)
            try:
                paginator = cfn_client.get_paginator("list_stack_resources")
                for page in paginator.paginate(StackName=stack_name):
                    for resource in page.get("StackResourceSummaries", []):
                        if (
                            resource.get("PhysicalResourceId") == cert_arn
                            and resource.get("ResourceType")
                            == "AWS::CertificateManager::Certificate"
                        ):
                            print(
                                f"   ℹ️  Certificate ARN found in CloudFormation stack resources ({stack_name}); treating as managed"
                            )
                            return False
            except Exception as e:
                print(f"   ⚠️  Could not list CloudFormation stack resources for {stack_name}: {e}")
                # Fail safe: treat as managed
                return False

        # If reached here, certificate doesn't appear to be managed by tag or stack
        return True

    except Exception as e:
        print(f"   ⚠️  Could not describe certificate {cert_arn}: {e}")
        # Fail safe: treat as managed to avoid accidental deletion
        return False


def _delete_acm_certificate(client: Any, cert_arn: str, dry_run: bool = False) -> None:
    """Delete an ACM certificate."""
    if dry_run:
        print(f"   [DRY RUN] Would delete certificate: {cert_arn}")
        return
    try:
        client.delete_certificate(CertificateArn=cert_arn)
    except Exception as e:
        print(f"   ⚠️  Could not delete certificate: {e}")


def _disconnect_cognito_domain(
    client: Any, domain_name: str, environment_name: str, dry_run: bool = False
) -> None:
    """Delete a Cognito custom domain so its certificate can be deleted.

    Only deletes unmanaged (orphaned) domains. CloudFormation-managed domains are skipped.
    """
    try:
        print(f"      ⏳ Checking Cognito domain: {domain_name}")

        # Get the domain description to find the user pool ID
        domain_desc = client.describe_user_pool_domain(Domain=domain_name)
        domain_info = domain_desc.get("DomainDescription", {})

        if not domain_info:
            print("      ℹ️  Domain not found")
            return

        user_pool_id = domain_info.get("UserPoolId")
        if not user_pool_id:
            print("      ⚠️  Could not find UserPoolId for domain")
            return

        # Check if domain is CloudFormation-managed
        if _is_cf_managed_resource("AWS::Cognito::UserPoolDomain", domain_name, environment_name):
            print("      ℹ️  Cognito domain is CloudFormation-managed, skipping")
            return

        if dry_run:
            print(f"      [DRY RUN] Would delete Cognito domain: {domain_name}")
            return

        # Delete the user pool domain (this frees up the certificate)
        client.delete_user_pool_domain(Domain=domain_name, UserPoolId=user_pool_id)
        print("      ✅ Cognito domain deleted")

        # Wait a moment for the deletion to propagate
        import time

        time.sleep(2)

    except Exception as e:
        print(f"      ⚠️  Could not delete Cognito domain: {e}")


def _cleanup_orphaned_route53_records(
    client: Any, domain_names: list[str], dry_run: bool = False
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
                        if dry_run:
                            print(f"   [DRY RUN] Would delete validation record: {record['Name']}")
                        else:
                            _delete_route53_record(client, zone_id, record)
                            print(f"   ✅ Deleted validation record: {record['Name']}")
    except Exception as e:
        print(f"   ⚠️  Could not clean Route53 records: {e}")


def _delete_api_domain_cname_record(
    client: Any, domain_name: str, environment_name: str, dry_run: bool = False
) -> None:
    """
    Delete the Route53 CNAME record for an AppSync API domain alias.

    ONLY deletes records that are NOT managed by CloudFormation.
    This allows AppSync to claim the domain alias without conflicts
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
        region = os.getenv("AWS_REGION") or "us-east-1"
        region_abbrevs = {
            "us-east-1": "ue1",
            "us-east-2": "ue2",
            "us-west-1": "uw1",
            "us-west-2": "uw2",
        }
        region_abbrev = region_abbrevs.get(region, region[:3])
        stack_name = f"kernelworx-{region_abbrev}-{environment_name}"

        # List CloudFormation stack resources to check if record is managed
        # Use pagination to get ALL resources (stacks can have 100+ resources)
        cfn_client = boto3.client("cloudformation", region_name=region)
        managed_record_ids: set[str] = set()
        try:
            paginator = cfn_client.get_paginator("list_stack_resources")
            for page in paginator.paginate(StackName=stack_name):
                for r in page["StackResourceSummaries"]:
                    if r["ResourceType"] == "AWS::Route53::RecordSet":
                        managed_record_ids.add(r["PhysicalResourceId"])
        except Exception:
            managed_record_ids = set()

        # List records in the zone
        records = _list_hosted_zone_records(client, zone_id)

        # Find CNAME records for this domain (exact match with or without trailing dot)
        domain_with_dot = f"{domain_name}."
        found = False

        for record in records:
            record_name = record.get("Name", "")
            record_type = record.get("Type", "")

            # Match the domain name (Route53 returns names with trailing dot)
            if record_name == domain_with_dot or record_name == domain_name:
                if record_type == "CNAME":
                    # Check if this record is managed by CloudFormation
                    if domain_name in managed_record_ids:
                        print("      ℹ️  CNAME record is CloudFormation-managed, skipping")
                        found = True
                        continue

                    print(f"      🗑️  Found unmanaged CNAME record: {record_name}")
                    if dry_run:
                        print(f"      [DRY RUN] Would delete CNAME record for {domain_name}")
                    else:
                        _delete_route53_record(client, zone_id, record)
                        print(f"      ✅ Deleted unmanaged CNAME record for {domain_name}")
                    found = True

        if not found:
            print(f"      ℹ️  No CNAME records found for {domain_name}")

    except Exception as e:
        print(f"      ⚠️  Could not delete Route53 CNAME record for {domain_name}: {e}")


def _delete_cloudfront_domain_record(client: Any, domain_name: str, dry_run: bool = False) -> None:
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
        region_abbrevs = {
            "us-east-1": "ue1",
            "us-east-2": "ue2",
            "us-west-1": "uw1",
            "us-west-2": "uw2",
        }
        region_abbrev = region_abbrevs.get(region, region[:3])
        stack_name = f"kernelworx-{region_abbrev}-{environment_name}"

        # List CloudFormation stack resources to check if record is managed
        # Use pagination to get ALL resources (stacks can have 100+ resources)
        cfn_client = boto3.client("cloudformation", region_name=region)
        managed_record_ids: set[str] = set()
        try:
            paginator = cfn_client.get_paginator("list_stack_resources")
            for page in paginator.paginate(StackName=stack_name):
                for r in page["StackResourceSummaries"]:
                    if r["ResourceType"] == "AWS::Route53::RecordSet":
                        managed_record_ids.add(r["PhysicalResourceId"])
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
                    if dry_run:
                        print(
                            f"      [DRY RUN] Would delete {record_type} record for {domain_name}"
                        )
                    else:
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


def _delete_route53_record(client: Any, hosted_zone_id: str, record: dict[str, Any]) -> None:
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

        client.change_resource_record_sets(HostedZoneId=hosted_zone_id, ChangeBatch=change_batch)
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


def _delete_orphaned_appsync_domain(
    domain_name: str, environment_name: str, dry_run: bool = False
) -> None:
    """
    Delete orphaned AppSync custom domain before deployment.

    AppSync custom domains cannot be imported into CloudFormation, so we must
    delete existing ones before CDK creates new ones.

    Args:
        domain_name: The custom domain name (e.g., "api.dev.kernelworx.app")
        environment_name: Environment name (dev, prod) for stack lookup
        dry_run: If True, only report what would be deleted
    """
    region = os.getenv("AWS_REGION") or "us-east-1"
    appsync_client = boto3.client("appsync", region_name=region)
    cfn_client = boto3.client("cloudformation", region_name=region)

    stack_name = f"kernelworx-ue1-{environment_name}" if environment_name else None

    try:
        # Check if domain exists
        try:
            appsync_client.get_domain_name(domainName=domain_name)
        except appsync_client.exceptions.NotFoundException:
            print(f"      ℹ️  No AppSync domain found for {domain_name}")
            return
        except Exception as e:
            if "NotFoundException" in str(type(e).__name__) or "Not Found" in str(e):
                print(f"      ℹ️  No AppSync domain found for {domain_name}")
                return
            raise

        # Check if this domain is managed by CloudFormation
        if stack_name:
            try:
                paginator = cfn_client.get_paginator("list_stack_resources")
                for page in paginator.paginate(StackName=stack_name):
                    for resource in page.get("StackResourceSummaries", []):
                        if (
                            resource.get("ResourceType") == "AWS::AppSync::DomainName"
                            and resource.get("PhysicalResourceId") == domain_name
                        ):
                            print(
                                f"      ℹ️  AppSync domain {domain_name} is CloudFormation-managed, skipping"
                            )
                            return
            except cfn_client.exceptions.ClientError:
                pass  # Stack doesn't exist

        print(f"      🔍 Found orphaned AppSync domain: {domain_name}")

        if dry_run:
            print(f"      [DRY RUN] Would delete AppSync domain: {domain_name}")
            return

        # First, disassociate any API association
        try:
            assoc = appsync_client.get_api_association(domainName=domain_name)
            if assoc.get("apiAssociation"):
                api_id = assoc["apiAssociation"].get("apiId")
                if api_id:
                    print("      ⏳ Disassociating domain from API...")
                    appsync_client.disassociate_api(domainName=domain_name)
                    print("      ✅ Disassociated domain from API")
        except Exception:
            pass  # No association or already disassociated

        # Delete the domain
        print(f"      🗑️  Deleting AppSync domain {domain_name}...")
        appsync_client.delete_domain_name(domainName=domain_name)
        print(f"      ✅ Deleted orphaned AppSync domain: {domain_name}")

    except Exception as e:
        print(f"      ⚠️  Could not delete AppSync domain {domain_name}: {e}")


def _cleanup_orphaned_appsync_api(environment_name: str, dry_run: bool = False) -> None:
    """
    Delete orphaned AppSync API before deployment.

    Only deletes unmanaged (orphaned) APIs. CloudFormation-managed APIs are skipped.
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
    appsync_client = boto3.client("appsync", region_name=region)

    # Find the API ID
    api_id: str | None = None
    try:
        paginator = appsync_client.get_paginator("list_graphql_apis")
        for page in paginator.paginate():
            for api in page.get("graphqlApis", []):
                if api["name"] == api_name:
                    api_id = api["apiId"]
                    break
            if api_id:
                break
    except Exception as e:
        print(f"   ⚠️  Could not list AppSync APIs: {e}")
        return

    if not api_id:
        print(f"   ℹ️  No AppSync API found: {api_name}")
        return

    # Check if API is CloudFormation-managed
    if _is_cf_managed_resource("AWS::AppSync::GraphQLApi", api_id, environment_name):
        print(f"   ℹ️  AppSync API is CloudFormation-managed, skipping: {api_name}")
        return

    if dry_run:
        print(f"   [DRY RUN] Would delete orphaned AppSync API: {api_name}")
    else:
        delete_appsync_api(api_name)


def _cleanup_orphaned_sms_role(environment_name: str, dry_run: bool = False) -> None:
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
            print("      ℹ️  No SMS role configured on UserPool")
            return

        # Extract role name from ARN
        role_name = sms_role_arn.split("/")[-1]

        # Check if role exists
        print(f"      ⏳ Checking SMS role: {role_name}")
        iam_client.get_role(RoleName=role_name)

        # Ensure it has the required inline policy
        policies = iam_client.list_role_policies(RoleName=role_name)
        if "UserPoolSmsPolicy" not in policies.get("PolicyNames", []):
            if dry_run:
                print(f"      [DRY RUN] Would add SNS permissions to role: {role_name}")
            else:
                print("      📝 Adding SNS permissions (required for import validation)")
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
                    }""",
                )
            print("      ✅ Added SNS permissions to SMS role")
        else:
            print("      ℹ️  SMS role already has SNS permissions")

    except iam_client.exceptions.NoSuchEntityException:
        print("      ℹ️  SMS role not found (CloudFormation will create it)")
    except Exception as e:
        print(f"      ⚠️  Could not configure SMS role: {e}")


def _disconnect_cloudfront_from_certificate(
    site_domain: str, environment_name: str | None = None, dry_run: bool = False
) -> None:
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
        if not _is_unmanaged_certificate(cert_arn, environment_name):
            print("      ℹ️  Certificate is CloudFormation-managed, skipping disconnect")
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
                print(
                    f"      ℹ️  Found CloudFront distribution using certificate: {distribution_id}"
                )

                if dry_run:
                    print(
                        f"      [DRY RUN] Would disconnect CloudFront {distribution_id} from certificate"
                    )
                    continue

                # Get current distribution config
                response = cloudfront_client.get_distribution_config(Id=distribution_id)
                config = response["DistributionConfig"]
                etag = response["ETag"]

                # Remove custom domain aliases
                if config.get("Aliases", {}).get("Items"):
                    print("      🗑️  Removing domain aliases from distribution")
                    config["Aliases"] = {"Quantity": 0, "Items": []}

                # Remove custom certificate (use default CloudFront cert)
                if config.get("ViewerCertificate", {}).get("ACMCertificateArn"):
                    print("      🗑️  Removing custom certificate from distribution")
                    config["ViewerCertificate"] = {
                        "CloudFrontDefaultCertificate": True,
                        "MinimumProtocolVersion": "TLSv1",
                    }

                # Update distribution
                print("      ⏳ Updating CloudFront distribution...")
                cloudfront_client.update_distribution(
                    Id=distribution_id,
                    DistributionConfig=config,
                    IfMatch=etag,
                )
                print("      ✅ Disconnected CloudFront from unmanaged certificate and domain")

                # Wait a moment for the update to start processing
                import time

                time.sleep(2)

        if not in_use_by:  # pragma: no cover
            print("      ℹ️  Certificate not in use by any resources")

    except Exception as e:  # pragma: no cover
        print(f"      ⚠️  Could not disconnect CloudFront: {e}", file=sys.stderr)


def _delete_orphaned_cloudfront_distribution(
    site_domain: str, environment_name: str | None = None, dry_run: bool = False
) -> None:
    """
    Delete an orphaned CloudFront distribution that is not managed by CloudFormation.

    This is necessary because CloudFront aliases must be unique - a new CDK-managed
    distribution cannot use the same alias as an existing orphaned distribution.

    This function finds distributions by S3 bucket origin (not by alias, since
    orphaned distributions may have had their aliases removed already).

    Args:
        site_domain: The domain alias to find (e.g., "dev.kernelworx.app")
        environment_name: Environment name for stack lookup (dev, prod)
    """
    region = os.getenv("AWS_REGION") or "us-east-1"
    cloudfront_client = boto3.client("cloudfront", region_name=region)
    cfn_client = boto3.client("cloudformation", region_name=region)

    # Build the expected S3 bucket origin domain
    # e.g., kernelworx-static-ue1-dev.s3.us-east-1.amazonaws.com
    s3_bucket_name = f"kernelworx-static-ue1-{environment_name}"
    s3_origin_patterns = [
        f"{s3_bucket_name}.s3.{region}.amazonaws.com",
        f"{s3_bucket_name}.s3.amazonaws.com",
    ]

    stack_name = f"kernelworx-ue1-{environment_name}" if environment_name else None

    # Get list of CloudFormation-managed distribution IDs
    managed_dist_ids: set[str] = set()
    if stack_name:
        try:
            stack_paginator = cfn_client.get_paginator("list_stack_resources")
            for stack_page in stack_paginator.paginate(StackName=stack_name):
                for resource in stack_page.get("StackResourceSummaries", []):
                    if resource.get("ResourceType") == "AWS::CloudFront::Distribution":
                        managed_dist_ids.add(resource.get("PhysicalResourceId", ""))
        except cfn_client.exceptions.ClientError:
            pass  # Stack doesn't exist

    deleted_count = 0
    oais_to_delete: list[str] = []

    try:
        # Find all CloudFront distributions using our S3 bucket
        paginator = cloudfront_client.get_paginator("list_distributions")
        for page in paginator.paginate():
            items = page.get("DistributionList", {}).get("Items", [])
            for dist in items:
                dist_id = dist["Id"]

                # Check if this distribution uses our S3 bucket
                origins = dist.get("Origins", {}).get("Items", [])
                uses_our_bucket = False
                for origin in origins:
                    origin_domain = origin.get("DomainName", "")
                    if any(pattern in origin_domain for pattern in s3_origin_patterns):
                        uses_our_bucket = True
                        # Collect OAI for cleanup
                        oai_path = origin.get("S3OriginConfig", {}).get("OriginAccessIdentity", "")
                        if oai_path:
                            oai_id = oai_path.split("/")[-1]
                            if oai_id:
                                oais_to_delete.append(oai_id)
                        break

                if not uses_our_bucket:
                    continue

                # Skip if managed by CloudFormation
                if dist_id in managed_dist_ids:
                    print(
                        f"      ℹ️  CloudFront distribution {dist_id} is CloudFormation-managed, skipping"
                    )
                    continue

                print(f"      🔍 Found orphaned CloudFront distribution: {dist_id}")

                if dry_run:
                    print(f"      [DRY RUN] Would delete CloudFront distribution: {dist_id}")
                    continue

                # Get current config
                response = cloudfront_client.get_distribution_config(Id=dist_id)
                config = response["DistributionConfig"]
                etag = response["ETag"]

                # Disable if enabled
                if config.get("Enabled"):
                    print(f"      ⏳ Disabling CloudFront distribution {dist_id}...")
                    config["Enabled"] = False
                    # Also remove aliases so CDK can use them
                    if config.get("Aliases", {}).get("Items"):
                        config["Aliases"] = {"Quantity": 0, "Items": []}
                    # Remove custom certificate
                    if config.get("ViewerCertificate", {}).get("ACMCertificateArn"):
                        config["ViewerCertificate"] = {
                            "CloudFrontDefaultCertificate": True,
                            "MinimumProtocolVersion": "TLSv1",
                        }
                    update_response = cloudfront_client.update_distribution(
                        Id=dist_id,
                        DistributionConfig=config,
                        IfMatch=etag,
                    )
                    etag = update_response["ETag"]
                    print(f"      ⏳ Waiting for distribution {dist_id} to be disabled...")
                    waiter = cloudfront_client.get_waiter("distribution_deployed")
                    waiter.wait(Id=dist_id, WaiterConfig={"Delay": 30, "MaxAttempts": 60})

                # Delete the distribution
                print(f"      🗑️  Deleting orphaned CloudFront distribution {dist_id}...")
                cloudfront_client.delete_distribution(Id=dist_id, IfMatch=etag)
                print(f"      ✅ Deleted orphaned CloudFront distribution {dist_id}")
                deleted_count += 1

        # Delete collected OAIs (after distributions are deleted)
        for oai_id in oais_to_delete:
            if dry_run:
                print(f"      [DRY RUN] Would delete OAI: {oai_id}")
                continue
            try:
                oai_response = cloudfront_client.get_cloud_front_origin_access_identity(Id=oai_id)
                oai_etag = oai_response["ETag"]
                cloudfront_client.delete_cloud_front_origin_access_identity(
                    Id=oai_id, IfMatch=oai_etag
                )
                print(f"      ✅ Deleted orphaned OAI: {oai_id}")
            except cloudfront_client.exceptions.NoSuchCloudFrontOriginAccessIdentity:
                pass  # OAI doesn't exist
            except Exception as e:
                # May still be in use by another distribution - ignore
                if "in use" not in str(
                    e
                ).lower() and "CloudFrontOriginAccessIdentityInUse" not in str(e):
                    print(f"      ⚠️  Could not delete OAI {oai_id}: {e}")

        if deleted_count == 0:
            print(f"      ℹ️  No orphaned CloudFront distribution found for {site_domain}")

    except Exception as e:
        print(f"      ⚠️  Could not delete CloudFront distribution: {e}", file=sys.stderr)


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
                physical_id = resource.get("PhysicalResourceId", "")  # pragma: no cover
                stack_resources.add(physical_id)  # pragma: no cover
    except cfn_client.exceptions.ClientError as e:
        if "does not exist" in str(e):
            print("   ℹ️  Stack does not exist yet (first deployment)", file=sys.stderr)
        else:  # pragma: no cover
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

    # Note: CloudFront distribution and ACM Certificates cannot be easily imported
    # due to certificate dependencies and CloudFormation limitations.
    # They will be recreated by CDK after orphaned resources are cleaned up.

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
            resources_to_import.append(
                {
                    "ResourceType": "AWS::DynamoDB::Table",
                    "LogicalResourceId": logical_id,
                    "ResourceIdentifier": {"TableName": physical_table_name},
                }
            )
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
            resources_to_import.append(
                {
                    "ResourceType": "AWS::S3::Bucket",
                    "LogicalResourceId": logical_id,
                    "ResourceIdentifier": {"BucketName": expected_bucket_name},
                }
            )
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
            role_exists = False  # pragma: no cover
        except Exception as e:  # pragma: no cover
            print(
                f"   ⚠️  Could not check SMS role {sms_role_name}: {e}", file=sys.stderr
            )  # pragma: no cover
            role_exists = False  # pragma: no cover

        # If role exists but not in CloudFormation, add to import list
        if role_exists and sms_role_name not in stack_resources:
            resources_to_import.append(
                {
                    "ResourceType": "AWS::IAM::Role",
                    "LogicalResourceId": "UserPoolsmsRole1998E37F",
                    "ResourceIdentifier": {"RoleName": sms_role_name},
                }
            )
            print(f"   🔍 Found unmanaged SMS role: {sms_role_name}", file=sys.stderr)

    # Check if user pool exists and add to import if needed
    pool_exists = bool(pool_details)
    if pool_exists and user_pool_id not in stack_resources:
        resources_to_import.append(
            {
                "ResourceType": "AWS::Cognito::UserPool",
                "LogicalResourceId": "UserPool6BA7E5F2",
                "ResourceIdentifier": {"UserPoolId": user_pool_id},
            }
        )
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
        resources_to_import.append(
            {
                "ResourceType": "AWS::Cognito::UserPoolDomain",
                "LogicalResourceId": "UserPoolDomain5479B217",
                "ResourceIdentifier": {"Domain": custom_domain},
            }
        )
        print(f"   🔍 Found unmanaged user pool domain: {custom_domain}", file=sys.stderr)


def _check_cloudfront_distribution(
    client: Any,
    stack_resources: set[str],
    resources_to_import: list[dict[str, Any]],
    environment_name: str,
    region_abbrev: str,
) -> None:
    """Check if CloudFront distribution and OAI exist but are not in CloudFormation."""
    # Expected alias for the distribution
    expected_alias = f"{environment_name}.kernelworx.app"

    try:
        # List all distributions and find the one with our alias
        paginator = client.get_paginator("list_distributions")
        for page in paginator.paginate():
            items = page.get("DistributionList", {}).get("Items", [])
            for dist in items:
                aliases = dist.get("Aliases", {}).get("Items", [])
                if expected_alias in aliases:
                    dist_id = dist["Id"]

                    # Get the OAI from the distribution's origin config
                    origins = dist.get("Origins", {}).get("Items", [])
                    for origin in origins:
                        s3_config = origin.get("S3OriginConfig", {})
                        oai_path = s3_config.get("OriginAccessIdentity", "")
                        # Extract OAI ID from path like "origin-access-identity/cloudfront/E1DLJZW45792KZ"
                        if oai_path and "/" in oai_path:
                            oai_id = oai_path.split("/")[-1]
                            if oai_id and oai_id not in stack_resources:
                                resources_to_import.append(
                                    {
                                        "ResourceType": "AWS::CloudFront::CloudFrontOriginAccessIdentity",
                                        "LogicalResourceId": "OAIE1EFC67F",
                                        "ResourceIdentifier": {"Id": oai_id},
                                    }
                                )
                                print(
                                    f"   🔍 Found unmanaged CloudFront OAI: {oai_id}",
                                    file=sys.stderr,
                                )
                                break  # Only need one OAI

                    # Check if distribution already in CloudFormation
                    if dist_id not in stack_resources:
                        resources_to_import.append(
                            {
                                "ResourceType": "AWS::CloudFront::Distribution",
                                "LogicalResourceId": "Distribution830FAC52",
                                "ResourceIdentifier": {"Id": dist_id},
                            }
                        )
                        print(
                            f"   🔍 Found unmanaged CloudFront distribution: {dist_id} ({expected_alias})",
                            file=sys.stderr,
                        )
                    return
    except Exception as e:
        print(f"   ⚠️  Could not check CloudFront distributions: {e}", file=sys.stderr)


def _check_acm_certificates(
    client: Any,
    stack_resources: set[str],
    resources_to_import: list[dict[str, Any]],
    environment_name: str,
    region_abbrev: str,
) -> None:
    """Check if ACM certificates exist but are not in CloudFormation."""
    # Certificate configurations: (domain, logical_id)
    cert_configs = [
        (f"{environment_name}.kernelworx.app", "SiteCertificateV30D1C1E75"),
        (f"api.{environment_name}.kernelworx.app", "ApiCertificateV2973B1407"),
        (f"login.{environment_name}.kernelworx.app", "CognitoCertificateV27B4D47C6"),
    ]

    try:
        # List all certificates
        paginator = client.get_paginator("list_certificates")
        certs_by_domain: dict[str, str] = {}
        for page in paginator.paginate():
            for cert in page.get("CertificateSummaryList", []):
                domain = cert.get("DomainName", "")
                arn = cert.get("CertificateArn", "")
                # Only use ISSUED certificates
                if cert.get("Status") == "ISSUED":
                    # Store first matching cert for each domain
                    if domain not in certs_by_domain:
                        certs_by_domain[domain] = arn

        # Check each expected certificate
        for domain, logical_id in cert_configs:
            cert_arn = certs_by_domain.get(domain)
            if cert_arn and cert_arn not in stack_resources:
                resources_to_import.append(
                    {
                        "ResourceType": "AWS::CertificateManager::Certificate",
                        "LogicalResourceId": logical_id,
                        "ResourceIdentifier": {"CertificateArn": cert_arn},
                    }
                )
                print(f"   🔍 Found unmanaged certificate: {domain}", file=sys.stderr)
    except Exception as e:
        print(f"   ⚠️  Could not check ACM certificates: {e}", file=sys.stderr)
