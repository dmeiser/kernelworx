from typing import Any

from aws_cdk import (
    Stack,
    Tags,
)
from constructs import Construct

from .appsync import setup_appsync
from .auth import create_cognito_auth
from .cloudfront_site import create_cloudfront_distribution
from .dns_certificates import create_dns_and_certificates
from .dynamodb_tables import create_dynamodb_tables
from .helpers import get_region_abbrev
from .iam_roles import create_appsync_service_role, create_lambda_execution_role
from .lambdas import create_lambda_functions
from .s3_buckets import create_s3_buckets


class CdkStack(Stack):  # type: ignore[misc]
    """
    Popcorn Sales Manager - Core Infrastructure Stack

    Creates foundational resources:
    - DynamoDB table with single-table design
    - S3 buckets for static assets and exports
    - IAM roles for Lambda functions
    - Cognito User Pool for authentication
    - AppSync GraphQL API
    - CloudFront distribution for SPA
    """

    def _rn(self, name: str) -> str:
        """Generate resource name with region and environment suffix."""
        return f"{name}-{self.region_abbrev}-{self.env_name}"

    def __init__(self, scope: Construct, construct_id: str, env_name: str = "dev", **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.region_abbrev = get_region_abbrev()

        # Apply standard tags to all resources in the stack
        Tags.of(self).add("Application", "kernelworx")
        Tags.of(self).add("Environment", env_name)

        # ====================================================================
        # Route 53 & DNS Configuration
        # ====================================================================

        dns_resources = create_dns_and_certificates(self, self.env_name)
        self.hosted_zone = dns_resources["hosted_zone"]
        self.site_domain = dns_resources["site_domain"]
        self.api_domain = dns_resources["api_domain"]
        self.cognito_domain = dns_resources["cognito_domain"]
        self.api_certificate = dns_resources["api_certificate"]
        self.site_certificate = dns_resources["site_certificate"]
        self.cognito_certificate = dns_resources["cognito_certificate"]

        # ====================================================================
        # DynamoDB Tables - Multi-Table Design
        # ====================================================================

        tables = create_dynamodb_tables(self, self._rn)
        self.accounts_table = tables["accounts_table"]
        self.catalogs_table = tables["catalogs_table"]
        self.profiles_table = tables["profiles_table"]
        self.shares_table = tables["shares_table"]
        self.invites_table = tables["invites_table"]
        self.campaigns_table = tables["campaigns_table"]
        self.orders_table = tables["orders_table"]
        self.shared_campaigns_table = tables["shared_campaigns_table"]

        # ====================================================================
        # S3 Buckets
        # ====================================================================

        s3_resources = create_s3_buckets(self, self._rn)
        self.static_assets_bucket = s3_resources["static_assets_bucket"]
        self.exports_bucket = s3_resources["exports_bucket"]

        # ====================================================================
        # IAM Roles
        # ====================================================================

        self.lambda_execution_role = create_lambda_execution_role(
            self, self._rn, tables, self.exports_bucket
        )

        # AppSync excludes shared_campaigns_table from GSI access (no GSIs on that table)
        self.appsync_service_role = create_appsync_service_role(
            self, self._rn, tables, tables_without_gsi=["shared_campaigns_table"]
        )

        # ====================================================================
        # Lambda Functions
        # ====================================================================

        lambda_resources = create_lambda_functions(
            scope=self,
            rn=self._rn,
            lambda_execution_role=self.lambda_execution_role,
            accounts_table=self.accounts_table,
            catalogs_table=self.catalogs_table,
            profiles_table=self.profiles_table,
            campaigns_table=self.campaigns_table,
            orders_table=self.orders_table,
            shares_table=self.shares_table,
            invites_table=self.invites_table,
            shared_campaigns_table=self.shared_campaigns_table,
            exports_bucket=self.exports_bucket,
        )
        self.shared_layer = lambda_resources["shared_layer"]
        self.list_my_shares_fn = lambda_resources["list_my_shares_fn"]
        self.create_profile_fn = lambda_resources["create_profile_fn"]
        self.request_campaign_report_fn = lambda_resources["request_campaign_report_fn"]
        self.unit_reporting_fn = lambda_resources["unit_reporting_fn"]
        self.list_unit_catalogs_fn = lambda_resources["list_unit_catalogs_fn"]
        self.list_unit_campaign_catalogs_fn = lambda_resources["list_unit_campaign_catalogs_fn"]
        self.campaign_operations_fn = lambda_resources["campaign_operations_fn"]
        self.delete_profile_orders_cascade_fn = lambda_resources["delete_profile_orders_cascade_fn"]
        self.update_my_account_fn = lambda_resources["update_my_account_fn"]
        self.transfer_ownership_fn = lambda_resources["transfer_ownership_fn"]
        self.post_auth_fn = lambda_resources["post_auth_fn"]
        self.pre_signup_fn = lambda_resources["pre_signup_fn"]
        self.request_qr_upload_fn = lambda_resources["request_qr_upload_fn"]
        self.confirm_qr_upload_fn = lambda_resources["confirm_qr_upload_fn"]
        self.generate_qr_code_presigned_url_fn = lambda_resources["generate_qr_code_presigned_url_fn"]
        self.delete_qr_code_fn = lambda_resources["delete_qr_code_fn"]
        self.validate_payment_method_fn = lambda_resources["validate_payment_method_fn"]

        # ====================================================================
        # Cognito User Pool - Authentication (Essentials tier)
        # ====================================================================

        auth_resources = create_cognito_auth(
            scope=self,
            rn=self._rn,
            env_name=env_name,
            region_abbrev=self.region_abbrev,
            site_domain=self.site_domain,
            cognito_domain=self.cognito_domain,
            cognito_certificate=self.cognito_certificate,
            hosted_zone=self.hosted_zone,
            post_auth_fn=self.post_auth_fn,
            pre_signup_fn=self.pre_signup_fn,
        )
        self.user_pool = auth_resources["user_pool"]
        self.user_pool_client = auth_resources["user_pool_client"]
        if "user_pool_domain" in auth_resources:
            self.user_pool_domain = auth_resources["user_pool_domain"]
        if "user_pool_sms_role" in auth_resources:
            self.user_pool_sms_role = auth_resources["user_pool_sms_role"]
        if "cognito_domain_record" in auth_resources:
            self.cognito_domain_record = auth_resources["cognito_domain_record"]

        # ====================================================================
        # AppSync GraphQL API
        # ====================================================================
        # Refactored into cdk/appsync.py module
        appsync_resources = setup_appsync(
            scope=self,
            env_name=env_name,
            resource_name=self._rn,
            user_pool=self.user_pool,
            api_domain=self.api_domain,
            api_certificate=self.api_certificate,
            hosted_zone=self.hosted_zone,
            tables={
                "accounts": self.accounts_table,
                "catalogs": self.catalogs_table,
                "profiles": self.profiles_table,
                "campaigns": self.campaigns_table,
                "orders": self.orders_table,
                "shares": self.shares_table,
                "invites": self.invites_table,
                "shared_campaigns": self.shared_campaigns_table,
            },
            lambda_functions={
                "list_my_shares_fn": self.list_my_shares_fn,
                "create_profile_fn": self.create_profile_fn,
                "request_campaign_report_fn": self.request_campaign_report_fn,
                "unit_reporting_fn": self.unit_reporting_fn,
                "list_unit_catalogs_fn": self.list_unit_catalogs_fn,
                "list_unit_campaign_catalogs_fn": self.list_unit_campaign_catalogs_fn,
                "campaign_operations_fn": self.campaign_operations_fn,
                "delete_profile_orders_cascade_fn": self.delete_profile_orders_cascade_fn,
                "update_my_account_fn": self.update_my_account_fn,
                "transfer_ownership_fn": self.transfer_ownership_fn,
                "request_qr_upload_fn": self.request_qr_upload_fn,
                "confirm_qr_upload_fn": self.confirm_qr_upload_fn,
                "generate_qr_code_presigned_url_fn": self.generate_qr_code_presigned_url_fn,
                "delete_qr_code_fn": self.delete_qr_code_fn,
                "validate_payment_method_fn": self.validate_payment_method_fn,
            },
        )
        self.api = appsync_resources.api
        self.api_domain_name = appsync_resources.domain_name
        self.api_domain_association = appsync_resources.domain_association
        self.api_domain_record = appsync_resources.dns_record

        # ====================================================================
        # CloudFront Distribution for SPA
        # ====================================================================

        cloudfront_resources = create_cloudfront_distribution(
            self,
            self.site_domain,
            self.site_certificate,
            self.static_assets_bucket,
            self.exports_bucket,
            self.hosted_zone,
        )
        self.origin_access_identity = cloudfront_resources["origin_access_identity"]
        self.distribution = cloudfront_resources["distribution"]
        self.site_domain_record = cloudfront_resources["site_domain_record"]

        # Add dependency: UserPoolDomain requires the parent domain A record to exist
        if hasattr(self, "user_pool_domain") and hasattr(self.user_pool_domain, "node"):
            self.user_pool_domain.node.add_dependency(self.site_domain_record)
