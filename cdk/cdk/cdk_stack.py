import os
from typing import Any

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
)
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
from aws_cdk import aws_s3 as s3
from constructs import Construct

from .appsync import setup_appsync
from .dynamodb_tables import create_dynamodb_tables
from .helpers import get_context_bool, get_domain_names, get_known_user_pool_id, get_region_abbrev


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

    def _configure_domains(self, base_domain: str) -> None:
        """Configure domain names based on environment using helper."""
        domains = get_domain_names(base_domain, self.env_name)
        self.site_domain = domains["site_domain"]
        self.api_domain = domains["api_domain"]
        self.cognito_domain = domains["cognito_domain"]

    def _setup_google_provider(self, supported_providers: list[cognito.UserPoolClientIdentityProvider]) -> None:
        """Configure Google OAuth provider if credentials are available."""
        if os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"):
            cognito.UserPoolIdentityProviderGoogle(
                self,
                "GoogleProvider",
                user_pool=self.user_pool,
                client_id=os.environ["GOOGLE_CLIENT_ID"],
                client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
                scopes=["email", "profile", "openid"],
                attribute_mapping=cognito.AttributeMapping(
                    email=cognito.ProviderAttribute.GOOGLE_EMAIL,
                    given_name=cognito.ProviderAttribute.GOOGLE_GIVEN_NAME,
                    family_name=cognito.ProviderAttribute.GOOGLE_FAMILY_NAME,
                ),
            )
            supported_providers.append(cognito.UserPoolClientIdentityProvider.GOOGLE)

    def _setup_facebook_provider(self, supported_providers: list[cognito.UserPoolClientIdentityProvider]) -> None:
        """Configure Facebook OAuth provider if credentials are available."""
        if os.environ.get("FACEBOOK_APP_ID") and os.environ.get("FACEBOOK_APP_SECRET"):
            cognito.UserPoolIdentityProviderFacebook(
                self,
                "FacebookProvider",
                user_pool=self.user_pool,
                client_id=os.environ["FACEBOOK_APP_ID"],
                client_secret=os.environ["FACEBOOK_APP_SECRET"],
                scopes=["email", "public_profile"],
                attribute_mapping=cognito.AttributeMapping(
                    email=cognito.ProviderAttribute.FACEBOOK_EMAIL,
                    given_name=cognito.ProviderAttribute.FACEBOOK_FIRST_NAME,
                    family_name=cognito.ProviderAttribute.FACEBOOK_LAST_NAME,
                ),
            )
            supported_providers.append(cognito.UserPoolClientIdentityProvider.FACEBOOK)

    def _setup_apple_provider(self, supported_providers: list[cognito.UserPoolClientIdentityProvider]) -> None:
        """Configure Apple Sign In provider if credentials are available."""
        has_apple_creds = (
            os.environ.get("APPLE_SERVICES_ID")
            and os.environ.get("APPLE_TEAM_ID")
            and os.environ.get("APPLE_KEY_ID")
            and os.environ.get("APPLE_PRIVATE_KEY")
        )
        if has_apple_creds:
            cognito.UserPoolIdentityProviderApple(
                self,
                "AppleProvider",
                user_pool=self.user_pool,
                client_id=os.environ["APPLE_SERVICES_ID"],
                team_id=os.environ["APPLE_TEAM_ID"],
                key_id=os.environ["APPLE_KEY_ID"],
                private_key=os.environ["APPLE_PRIVATE_KEY"],
                scopes=["email", "name"],
                attribute_mapping=cognito.AttributeMapping(
                    email=cognito.ProviderAttribute.APPLE_EMAIL,
                    given_name=cognito.ProviderAttribute.APPLE_FIRST_NAME,
                    family_name=cognito.ProviderAttribute.APPLE_LAST_NAME,
                ),
            )
            supported_providers.append(cognito.UserPoolClientIdentityProvider.APPLE)

    def _setup_social_identity_providers(
        self,
    ) -> list[cognito.UserPoolClientIdentityProvider]:
        """Configure social identity providers (Google, Facebook, Apple)."""
        supported_providers: list[cognito.UserPoolClientIdentityProvider] = [
            cognito.UserPoolClientIdentityProvider.COGNITO
        ]
        self._setup_google_provider(supported_providers)
        self._setup_facebook_provider(supported_providers)
        self._setup_apple_provider(supported_providers)
        return supported_providers

    def __init__(self, scope: Construct, construct_id: str, env_name: str = "dev", **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.region_abbrev = get_region_abbrev()

        # Apply standard tags to all resources in the stack
        Tags.of(self).add("Application", "kernelworx")
        Tags.of(self).add("Environment", env_name)

        # Load configuration from environment variables
        base_domain = os.getenv("BASE_DOMAIN", "kernelworx.app")

        # ====================================================================
        # Route 53 & DNS Configuration
        # ====================================================================

        # Import existing hosted zone
        self.hosted_zone = route53.HostedZone.from_lookup(
            self,
            "HostedZone",
            domain_name=base_domain,
        )

        # Define domain names based on environment
        self._configure_domains(base_domain)

        # ACM Certificate for AppSync API
        # Create new managed certificate (orphaned one cleaned up before deploy)
        self.api_certificate = acm.Certificate(
            self,
            "ApiCertificateV2",  # Changed from ApiCertificate to force recreation
            domain_name=self.api_domain,
            validation=acm.CertificateValidation.from_dns(self.hosted_zone),
        )
        self.api_certificate.apply_removal_policy(RemovalPolicy.RETAIN)

        # ACM Certificate for CloudFront (site domain)
        print(f"Creating CloudFront Certificate: {self.site_domain}")
        self.site_certificate = acm.Certificate(
            self,
            "SiteCertificateV3",  # Changed from V2 to force recreation
            domain_name=self.site_domain,
            validation=acm.CertificateValidation.from_dns(self.hosted_zone),
        )
        self.site_certificate.apply_removal_policy(RemovalPolicy.RETAIN)

        # Separate ACM Certificate for Cognito custom domain
        print(f"Creating Cognito Certificate: {self.cognito_domain}")
        self.cognito_certificate = acm.Certificate(
            self,
            "CognitoCertificateV2",  # Changed from CognitoCertificate to force recreation
            domain_name=self.cognito_domain,
            validation=acm.CertificateValidation.from_dns(self.hosted_zone),
        )
        self.cognito_certificate.apply_removal_policy(RemovalPolicy.RETAIN)

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

        # Static assets bucket (for SPA hosting)
        static_bucket_name = self._rn("kernelworx-static")
        self.static_assets_bucket = s3.Bucket(
            self,
            "StaticAssets",
            bucket_name=static_bucket_name,
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Exports bucket (for generated reports)
        exports_bucket_name = self._rn("kernelworx-exports")
        self.exports_bucket = s3.Bucket(
            self,
            "Exports",
            bucket_name=exports_bucket_name,
            versioned=False,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ====================================================================
        # IAM Roles
        # ====================================================================

        # Lambda execution role (base permissions)
        self.lambda_execution_role = iam.Role(
            self,
            "LambdaExecutionRole",
            role_name=self._rn("kernelworx-lambda-exec"),
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ],
        )

        # Grant Lambda role access to new multi-table design tables
        self.accounts_table.grant_read_write_data(self.lambda_execution_role)
        self.catalogs_table.grant_read_write_data(self.lambda_execution_role)
        self.profiles_table.grant_read_write_data(self.lambda_execution_role)
        self.campaigns_table.grant_read_write_data(self.lambda_execution_role)
        self.orders_table.grant_read_write_data(self.lambda_execution_role)
        self.shares_table.grant_read_write_data(self.lambda_execution_role)
        self.invites_table.grant_read_write_data(self.lambda_execution_role)
        self.shared_campaigns_table.grant_read_write_data(self.lambda_execution_role)

        # Grant Lambda role access to new table GSI indexes
        for table in [
            self.accounts_table,
            self.catalogs_table,
            self.profiles_table,
            self.campaigns_table,
            self.orders_table,
            self.shares_table,
            self.invites_table,
            self.shared_campaigns_table,
        ]:
            self.lambda_execution_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:Query", "dynamodb:Scan"],
                    resources=[f"{table.table_arn}/index/*"],
                )
            )

        # Grant Lambda role access to exports bucket
        self.exports_bucket.grant_read_write(self.lambda_execution_role)

        # Grant Lambda role permission to create CloudFront invalidations
        self.lambda_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudfront:CreateInvalidation"],
                resources=["*"],  # CloudFront invalidation requires wildcard resource
            )
        )

        # AppSync service role (for direct DynamoDB resolvers)
        self.appsync_service_role = iam.Role(
            self,
            "AppSyncServiceRole",
            role_name=self._rn("kernelworx-appsync"),
            assumed_by=iam.ServicePrincipal("appsync.amazonaws.com"),
        )

        # Grant AppSync role access to new multi-table design tables
        self.accounts_table.grant_read_write_data(self.appsync_service_role)
        self.catalogs_table.grant_read_write_data(self.appsync_service_role)
        self.profiles_table.grant_read_write_data(self.appsync_service_role)
        self.campaigns_table.grant_read_write_data(self.appsync_service_role)
        self.orders_table.grant_read_write_data(self.appsync_service_role)
        self.shares_table.grant_read_write_data(self.appsync_service_role)
        self.invites_table.grant_read_write_data(self.appsync_service_role)
        self.shared_campaigns_table.grant_read_write_data(self.appsync_service_role)

        # Grant AppSync role access to new table GSI indexes
        for table in [
            self.accounts_table,
            self.catalogs_table,
            self.profiles_table,
            self.campaigns_table,
            self.orders_table,
            self.shares_table,
            self.invites_table,
        ]:
            self.appsync_service_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:Query", "dynamodb:Scan"],
                    resources=[f"{table.table_arn}/index/*"],
                )
            )

        # ====================================================================
        # Lambda Functions
        # ====================================================================

        # Common Lambda environment variables
        lambda_env = {
            "EXPORTS_BUCKET": self.exports_bucket.bucket_name,
            "POWERTOOLS_SERVICE_NAME": "kernelworx",
            "LOG_LEVEL": "INFO",
            "LAMBDA_VERSION": "2026-01-12",  # Force Lambda update
            # New multi-table design table names
            "ACCOUNTS_TABLE_NAME": self.accounts_table.table_name,
            "CATALOGS_TABLE_NAME": self.catalogs_table.table_name,
            "PROFILES_TABLE_NAME": self.profiles_table.table_name,
            "CAMPAIGNS_TABLE_NAME": self.campaigns_table.table_name,
            "ORDERS_TABLE_NAME": self.orders_table.table_name,
            "SHARES_TABLE_NAME": self.shares_table.table_name,
            "INVITES_TABLE_NAME": self.invites_table.table_name,
            # Shared campaigns table used by create_campaign Lambda
            "SHARED_CAMPAIGNS_TABLE_NAME": self.shared_campaigns_table.table_name,
        }

        # Create Lambda Layer for shared dependencies
        # This reduces function deployment size by sharing common packages
        lambda_layer_path = os.path.join(os.path.dirname(__file__), "..", "lambda-layer")

        # Check if layer exists, if not create it
        if not os.path.exists(lambda_layer_path):
            os.makedirs(lambda_layer_path, exist_ok=True)

        self.shared_layer = lambda_.LayerVersion(
            self,
            "SharedDependenciesLayer",
            layer_version_name=self._rn("kernelworx-deps"),
            code=lambda_.Code.from_asset(lambda_layer_path),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_13],
            description="Shared Python dependencies for Lambda functions",
        )

        # Use only the src directory for Lambda code (not the entire repo)
        lambda_code_path = os.path.join(os.path.dirname(__file__), "..", "..", "src")

        lambda_code = lambda_.Code.from_asset(
            lambda_code_path,
            exclude=[
                "__pycache__",
                "*.pyc",
                ".pytest_cache",
            ],
        )

        # Profile Sharing Lambda Functions
        # NOTE: create_profile_invite Lambda REMOVED - replaced with JS resolver
        # NOTE: redeem_profile_invite Lambda REMOVED - replaced with pipeline resolver
        # NOTE: share_profile_direct Lambda REMOVED - replaced with pipeline resolver
        # NOTE: revoke_share Lambda REMOVED - replaced with VTL DynamoDB resolver
        # NOTE: update_campaign, delete_campaign Lambdas REMOVED - replaced with JS pipeline resolvers

        # List My Shares Lambda - uses Lambda due to AppSync BatchGetItem intermittent issues
        self.list_my_shares_fn = lambda_.Function(
            self,
            "ListMySharesFn",
            function_name=self._rn("kernelworx-list-my-shares"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.profile_sharing.list_my_shares",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(30),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Order Operations Lambda Functions
        # NOTE: create_order Lambda REMOVED - replaced with pipeline resolver

        self.create_profile_fn = lambda_.Function(
            self,
            "CreateProfileFnV2",
            function_name=self._rn("kernelworx-create-profile"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.scout_operations.create_seller_profile",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(30),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        self.request_campaign_report_fn = lambda_.Function(
            self,
            "RequestCampaignReportFnV2",
            function_name=self._rn("kernelworx-request-report"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.report_generation.request_campaign_report",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(60),  # Reports may take longer
            memory_size=512,  # More memory for Excel generation
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        self.unit_reporting_fn = lambda_.Function(
            self,
            "UnitReportingFnV2",
            function_name=self._rn("kernelworx-unit-reporting"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.campaign_reporting.get_unit_report",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(60),  # May need time for large units
            memory_size=512,  # More memory for aggregation
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        self.list_unit_catalogs_fn = lambda_.Function(
            self,
            "ListUnitCatalogsFn",
            function_name=self._rn("kernelworx-list-unit-catalogs"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.list_unit_catalogs.list_unit_catalogs",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(30),
            memory_size=512,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # New list_unit_campaign_catalogs Lambda (uses unitCampaignKey-index for campaign-based queries)
        self.list_unit_campaign_catalogs_fn = lambda_.Function(
            self,
            "ListUnitCampaignCatalogsFn",
            function_name=self._rn("kernelworx-list-unit-campaign-catalogs"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.list_unit_catalogs.list_unit_campaign_catalogs",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(30),
            memory_size=512,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Campaign Operations Lambda (with transaction support for Shared Campaign + share creation)
        self.campaign_operations_fn = lambda_.Function(
            self,
            "CampaignOperationsFn",
            function_name=self._rn("kernelworx-campaign-operations"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.campaign_operations.create_campaign",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(30),
            memory_size=512,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Delete Profile Orders Cascade Lambda (cascade delete of orders when profile is deleted)
        self.delete_profile_orders_cascade_fn = lambda_.Function(
            self,
            "DeleteProfileOrdersCascadeFn",
            function_name=self._rn("kernelworx-delete-profile-orders-cascade"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.delete_profile_orders_cascade.lambda_handler",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(60),  # May take longer for profiles with many orders
            memory_size=512,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Account Operations Lambda Functions
        self.update_my_account_fn = lambda_.Function(
            self,
            "UpdateMyAccountFnV2",
            function_name=self._rn("kernelworx-update-account"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.account_operations.update_my_account",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(10),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Transfer Profile Ownership Lambda
        self.transfer_ownership_fn = lambda_.Function(
            self,
            "TransferProfileOwnershipFn",
            function_name=self._rn("kernelworx-transfer-ownership"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.transfer_profile_ownership.lambda_handler",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(10),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Post-Authentication Lambda (Cognito Trigger)
        self.post_auth_fn = lambda_.Function(
            self,
            "PostAuthenticationFnV2",
            function_name=self._rn("kernelworx-post-auth"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.post_authentication.lambda_handler",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(10),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Pre-Signup Lambda (Cognito Trigger)
        # Links federated identities (Google, Facebook, Apple) to existing users
        # with the same email to prevent duplicate accounts
        self.pre_signup_fn = lambda_.Function(
            self,
            "PreSignupFn",
            function_name=self._rn("kernelworx-pre-signup"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.pre_signup.lambda_handler",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(10),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # ====================================================================
        # Payment Methods Lambda Functions - QR Code Operations
        # ====================================================================

        # Request QR Upload Lambda - Generates pre-signed POST URL for S3
        self.request_qr_upload_fn = lambda_.Function(
            self,
            "RequestQRUploadFn",
            function_name=self._rn("kernelworx-request-qr-upload"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.payment_methods_handlers.request_qr_upload",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(10),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Confirm QR Upload Lambda - Validates S3 object and generates pre-signed GET URL
        self.confirm_qr_upload_fn = lambda_.Function(
            self,
            "ConfirmQRUploadFn",
            function_name=self._rn("kernelworx-confirm-qr-upload"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.payment_methods_handlers.confirm_qr_upload",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(10),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Generate QR Code Presigned URL Lambda - Field resolver for on-demand URL generation
        self.generate_qr_code_presigned_url_fn = lambda_.Function(
            self,
            "GenerateQRCodePresignedURLFn",
            function_name=self._rn("kernelworx-generate-qr-code-presigned-url"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.generate_qr_code_presigned_url.generate_qr_code_presigned_url",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(3),
            memory_size=128,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Delete QR Code Lambda - Deletes QR code from S3 and clears DynamoDB reference
        self.delete_qr_code_fn = lambda_.Function(
            self,
            "DeleteQRCodeFn",
            function_name=self._rn("kernelworx-delete-qr-code"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.payment_methods_handlers.delete_qr_code",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(10),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # Validate Payment Method Lambda - Validates payment method exists during order creation
        self.validate_payment_method_fn = lambda_.Function(
            self,
            "ValidatePaymentMethodFn",
            function_name=self._rn("kernelworx-validate-payment-method"),
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handlers.validate_payment_method.lambda_handler",
            code=lambda_code,
            layers=[self.shared_layer],
            timeout=Duration.seconds(10),
            memory_size=256,
            role=self.lambda_execution_role,
            environment=lambda_env,
        )

        # ====================================================================
        # Cognito User Pool - Authentication (Essentials tier)
        # ====================================================================

        # Get the known pool ID or use context parameter
        known_pool_id = get_known_user_pool_id(env_name) or self.node.try_get_context("user_pool_id")
        existing_user_pool_id = known_pool_id

        if existing_user_pool_id:
            print(f"Importing existing User Pool: {existing_user_pool_id}")

            # SMS role - will be imported
            sms_role_name = f"kernelworx-{self.region_abbrev}-{self.env_name}-UserPoolsmsRole"
            self.user_pool_sms_role = iam.Role(
                self,
                "UserPoolsmsRole",
                assumed_by=iam.ServicePrincipal("cognito-idp.amazonaws.com"),
                role_name=sms_role_name,
                inline_policies={
                    "UserPoolSmsPolicy": iam.PolicyDocument(
                        statements=[
                            iam.PolicyStatement(
                                actions=["sns:Publish"],
                                resources=["arn:aws:sns:*:*:*"],
                            )
                        ]
                    )
                },
            )
            self.user_pool_sms_role.apply_removal_policy(RemovalPolicy.RETAIN)

            # Define the UserPool for import
            self.user_pool = cognito.UserPool(
                self,
                "UserPool",
                user_pool_name=self._rn("kernelworx-users"),
                sign_in_aliases=cognito.SignInAliases(email=True, username=False),
                self_sign_up_enabled=True,
                auto_verify=cognito.AutoVerifiedAttrs(email=True),
                standard_attributes=cognito.StandardAttributes(
                    email=cognito.StandardAttribute(required=True, mutable=True),
                ),
                password_policy=cognito.PasswordPolicy(
                    min_length=8,
                    require_lowercase=True,
                    require_uppercase=True,
                    require_digits=True,
                    require_symbols=True,
                ),
                account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
                mfa=cognito.Mfa.OPTIONAL,
                mfa_second_factor=cognito.MfaSecondFactor(sms=True, otp=True),
                sms_role=self.user_pool_sms_role,
                sms_role_external_id="kernelworx-sms-role",
                lambda_triggers=cognito.UserPoolTriggers(
                    pre_sign_up=self.pre_signup_fn,
                    post_authentication=self.post_auth_fn,
                ),
                removal_policy=RemovalPolicy.RETAIN,
            )

            # CRITICAL: UserPool must depend on SMS role having its inline policy
            # CloudFormation needs to import/update the role with the policy BEFORE validating the UserPool
            self.user_pool.node.add_dependency(self.user_pool_sms_role)

            # Create/import UserPoolClient
            self.user_pool_client = cognito.UserPoolClient(
                self,
                "AppClient",
                user_pool=self.user_pool,
                user_pool_client_name="KernelWorx-Web",
                auth_flows=cognito.AuthFlow(
                    user_srp=True,
                    user_password=True,
                    user=True,
                ),
                o_auth=cognito.OAuthSettings(
                    flows=cognito.OAuthFlows(
                        authorization_code_grant=True,
                        implicit_code_grant=True,
                    ),
                    scopes=[
                        cognito.OAuthScope.EMAIL,
                        cognito.OAuthScope.OPENID,
                        cognito.OAuthScope.PROFILE,
                    ],
                    callback_urls=[
                        "http://localhost:5173",
                        "https://local.dev.appworx.app:5173",
                        f"https://{self.site_domain}",
                        f"https://{self.site_domain}/callback",
                    ],
                    logout_urls=[
                        "http://localhost:5173",
                        "https://local.dev.appworx.app:5173",
                        f"https://{self.site_domain}",
                    ],
                ),
                # Only declare identity providers we know exist on the imported pool
                # For existing pools, only include COGNITO to avoid "provider does not exist" errors
                supported_identity_providers=[
                    cognito.UserPoolClientIdentityProvider.COGNITO,
                ],
                prevent_user_existence_errors=True,
            )
            self.user_pool_client.node.default_child.apply_removal_policy(RemovalPolicy.RETAIN)

        else:
            # No existing pool - create a new one
            self.user_pool = cognito.UserPool(
                self,
                "UserPool",
                user_pool_name=self._rn("kernelworx-users"),
                sign_in_aliases=cognito.SignInAliases(email=True, username=False),
                self_sign_up_enabled=True,
                auto_verify=cognito.AutoVerifiedAttrs(email=True),
                standard_attributes=cognito.StandardAttributes(
                    email=cognito.StandardAttribute(required=True, mutable=True),
                    given_name=cognito.StandardAttribute(required=False, mutable=True),
                    family_name=cognito.StandardAttribute(required=False, mutable=True),
                ),
                password_policy=cognito.PasswordPolicy(
                    min_length=8,
                    require_lowercase=True,
                    require_uppercase=True,
                    require_digits=True,
                    require_symbols=True,
                ),
                account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
                # Enable MFA with TOTP (software tokens) and SMS as options
                mfa=cognito.Mfa.OPTIONAL,
                mfa_second_factor=cognito.MfaSecondFactor(
                    sms=True,  # Allow SMS MFA
                    otp=True,  # Allow TOTP (software tokens like Google Authenticator)
                ),
                # Enable choice-based authentication with password and passkeys
                sign_in_policy=cognito.SignInPolicy(
                    allowed_first_auth_factors=cognito.AllowedFirstAuthFactors(
                        password=True,
                        passkey=True,
                    )
                ),
                # Set WebAuthn Relying Party ID to app domain (not auth domain)
                passkey_relying_party_id=self.site_domain,  # e.g., dev.kernelworx.app
                # User verification preferred (default) - allows authenticators without UV capability
                passkey_user_verification=cognito.PasskeyUserVerification.PREFERRED,
                removal_policy=RemovalPolicy.RETAIN,
                # Lambda triggers
                lambda_triggers=cognito.UserPoolTriggers(
                    pre_sign_up=self.pre_signup_fn,
                    post_authentication=self.post_auth_fn,
                ),
                # Note: Advanced security mode not compatible with Essentials tier
                # UI customization (logo, CSS) is available without advanced_security_mode
            )

            # Pre-signup Lambda needs permission to link identities and list users
            self.pre_signup_fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=[
                        "cognito-idp:AdminLinkProviderForUser",
                        "cognito-idp:ListUsers",
                    ],
                    resources=[self.user_pool.user_pool_arn],
                )
            )

            # Configure user attribute update settings to require verification for email changes
            cfn_user_pool = self.user_pool.node.default_child
            assert cfn_user_pool is not None
            cfn_user_pool.user_attribute_update_settings = cognito.CfnUserPool.UserAttributeUpdateSettingsProperty(
                attributes_require_verification_before_update=["email"]
            )

            # Note: COPPA compliance warning (13+ age requirement) must be displayed
            # in application UI. Lambda trigger for age verification deferred to later phase.

            # Create ADMIN user group
            # Note: Only ADMIN group is needed. Everyone else is a regular user by default.
            # The Lambda checks for ADMIN group membership; all other users have isAdmin=False.
            cognito.CfnUserPoolGroup(
                self,
                "AdminGroup",
                user_pool_id=self.user_pool.user_pool_id,
                group_name="ADMIN",
                description="Administrator users with elevated privileges",
            )

            # Configure social identity providers and get list of supported providers
            supported_providers = self._setup_social_identity_providers()

            # App client for SPA
            self.user_pool_client = self.user_pool.add_client(
                "AppClient",
                user_pool_client_name="KernelWorx-Web",
                auth_flows=cognito.AuthFlow(
                    user_srp=True,
                    user_password=True,
                    user=True,  # Required for WebAuthn/passkeys (ALLOW_USER_AUTH)
                ),
                o_auth=cognito.OAuthSettings(
                    flows=cognito.OAuthFlows(
                        authorization_code_grant=True,
                        implicit_code_grant=True,
                    ),
                    scopes=[
                        cognito.OAuthScope.EMAIL,
                        cognito.OAuthScope.OPENID,
                        cognito.OAuthScope.PROFILE,
                    ],
                    callback_urls=[
                        "http://localhost:5173",
                        "https://local.dev.appworx.app:5173",
                        f"https://{self.site_domain}",
                        f"https://{self.site_domain}/callback",
                    ],
                    logout_urls=[
                        "http://localhost:5173",
                        "https://local.dev.appworx.app:5173",
                        f"https://{self.site_domain}",
                    ],
                ),
                supported_identity_providers=supported_providers,
                prevent_user_existence_errors=True,
            )

            # Support two-stage deploys: some environments prefer creating the
            # site distribution and DNS first, then creating the Cognito
            # custom domain after DNS has propagated. Control this behaviour
            # with the context key `create_cognito_domain` (default: True).
            create_cognito_domain = get_context_bool(self, "create_cognito_domain", default=True)

            # Custom domain configuration (login.{env}.kernelworx.app or login.kernelworx.app)
            if create_cognito_domain:
                self.user_pool_domain = self.user_pool.add_domain(
                    "UserPoolDomain",
                    custom_domain=cognito.CustomDomainOptions(
                        domain_name=self.cognito_domain,
                        certificate=self.cognito_certificate,
                    ),
                )

                # Ensure the certificate is fully validated before creating the domain
                self.user_pool_domain.node.add_dependency(self.cognito_certificate)

            # NOTE: ManagedLoginVersion property removed temporarily - can be added back
            # after initial deployment if needed for Managed Login v2 branding

        # ====================================================================
        # Cognito Custom Domain Configuration (for imported pools)
        # ====================================================================

        # Check if we should skip UserPoolDomain creation (during import)
        # Skip domain creation if explicitly disabled via context
        skip_user_pool_domain = get_context_bool(self, "skip_user_pool_domain", default=False)

        if existing_user_pool_id and not skip_user_pool_domain:
            print(f"Defining User Pool Domain: {self.cognito_domain}")
            self.user_pool_domain = cognito.UserPoolDomain(
                self,
                "UserPoolDomain",
                user_pool=self.user_pool,
                custom_domain=cognito.CustomDomainOptions(
                    domain_name=self.cognito_domain,
                    certificate=self.cognito_certificate,
                ),
            )
            self.user_pool_domain.node.default_child.apply_removal_policy(RemovalPolicy.RETAIN)

            print(f"Defining Route53 A record for Cognito domain: {self.cognito_domain}")
            self.cognito_domain_record = route53.ARecord(
                self,
                "CognitoDomainRecord",
                zone=self.hosted_zone,
                record_name=self.cognito_domain,
                target=route53.RecordTarget.from_alias(targets.UserPoolDomainTarget(self.user_pool_domain)),
            )
            self.cognito_domain_record.apply_removal_policy(RemovalPolicy.RETAIN)
        elif existing_user_pool_id and skip_user_pool_domain:
            print("Skipping User Pool Domain creation (import mode)")
            print("   To enable domain later: remove -c skip_user_pool_domain=true")

        # Output Cognito Hosted UI URL for easy access
        if hasattr(self, "user_pool_domain") and hasattr(self, "user_pool_client"):
            CfnOutput(
                self,
                "CognitoHostedUIUrl",
                value=f"https://{self.user_pool_domain.domain_name}.auth.{self.region}.amazoncognito.com/login?client_id={self.user_pool_client.user_pool_client_id}&response_type=code&redirect_uri=http://localhost:5173",
                description="Cognito Hosted UI URL for testing",
            )

        # Output UserPoolClientId for frontend deployment
        CfnOutput(
            self,
            "UserPoolClientId",
            value=self.user_pool_client.user_pool_client_id,
            description="Cognito User Pool Client ID",
            export_name="kernelworx-ue1-dev-UserPoolClientId",
        )

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

        # Origin Access Identity for S3
        self.origin_access_identity = cloudfront.OriginAccessIdentity(
            self, "OAI", comment="OAI for Popcorn Sales Manager SPA"
        )
        self.origin_access_identity.node.default_child.apply_removal_policy(RemovalPolicy.RETAIN)

        # Grant CloudFront read access to static assets bucket
        self.static_assets_bucket.grant_read(self.origin_access_identity)
        
        # Grant CloudFront read/write access to exports bucket for uploads
        self.exports_bucket.grant_read_write(self.origin_access_identity)

        # CloudFront distribution with custom domain
        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            domain_names=[self.site_domain],  # Custom domain for site
            certificate=self.site_certificate,  # Use dedicated site certificate
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_identity(
                    self.static_assets_bucket,
                    origin_access_identity=self.origin_access_identity,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                compress=True,
            ),
            additional_behaviors={
                "/uploads/*": cloudfront.BehaviorOptions(
                    origin=origins.S3BucketOrigin.with_origin_access_identity(
                        self.exports_bucket,
                        origin_access_identity=self.origin_access_identity,
                    ),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,  # Allow POST/PUT for uploads
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,  # Don't cache uploads
                    compress=False,  # Don't compress binary files
                ),
                # Note: /payment-qr-codes/* is served via signed S3 URLs, not CloudFront
            },
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
        self.distribution.apply_removal_policy(RemovalPolicy.RETAIN)

        # Route53 record for CloudFront distribution
        self.site_domain_record = route53.ARecord(
            self,
            "SiteDomainRecordV2",  # Changed from SiteDomainRecord to force recreation
            zone=self.hosted_zone,
            record_name=self.site_domain,
            target=route53.RecordTarget.from_alias(targets.CloudFrontTarget(self.distribution)),
        )
        self.site_domain_record.node.default_child.apply_removal_policy(RemovalPolicy.RETAIN)

        # Add dependency: UserPoolDomain requires the parent domain A record to exist
        if hasattr(self, "user_pool_domain") and hasattr(self.user_pool_domain, "node"):
            self.user_pool_domain.node.add_dependency(self.site_domain_record)
