"""Cognito User Pool authentication configuration for the Popcorn Sales Manager stack.

This module creates and configures:
- Cognito User Pool with email sign-in
- User Pool Client for SPA
- Custom domain for Cognito hosted UI
- Social identity providers (Google, Facebook, Apple) when configured
- SMS role for MFA
- Route53 record for Cognito custom domain
"""

import os
from typing import TYPE_CHECKING, Any

from aws_cdk import CfnOutput, RemovalPolicy
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
from constructs import Construct

if TYPE_CHECKING:
    from aws_cdk import aws_certificatemanager as acm


# Known User Pool IDs for each environment (prevents creating duplicates)
KNOWN_USER_POOL_IDS = {
    "dev": "us-east-1_sDiuCOarb",
    # Add prod when ready: "prod": "us-east-1_XXXXX",
}


def _should_skip_lambda_triggers(scope: Construct) -> bool:
    """Check if Lambda triggers should be skipped (import phase)."""
    skip = scope.node.try_get_context("skip_lambda_triggers")
    if skip is None:
        return False
    if isinstance(skip, str):
        return skip.lower() == "true"
    return bool(skip)


def _build_user_pool_triggers(
    scope: Construct,
    pre_signup_fn: lambda_.Function,
    post_auth_fn: lambda_.Function,
) -> cognito.UserPoolTriggers | None:
    """Build user pool triggers unless in import phase."""
    if _should_skip_lambda_triggers(scope):
        print("⚠️  Skipping Lambda triggers (import phase - will be added on subsequent deploy)")
        return None
    return cognito.UserPoolTriggers(pre_sign_up=pre_signup_fn, post_authentication=post_auth_fn)


def _create_sms_role(scope: Construct, region_abbrev: str, env_name: str) -> iam.Role:
    """Create SMS role for Cognito MFA."""
    sms_role_name = f"kernelworx-{region_abbrev}-{env_name}-UserPoolsmsRole"
    sms_role = iam.Role(
        scope,
        "UserPoolsmsRole",
        assumed_by=iam.ServicePrincipal("cognito-idp.amazonaws.com"),
        role_name=sms_role_name,
        inline_policies={
            "UserPoolSmsPolicy": iam.PolicyDocument(
                statements=[iam.PolicyStatement(actions=["sns:Publish"], resources=["arn:aws:sns:*:*:*"])]
            )
        },
    )
    sms_role.apply_removal_policy(RemovalPolicy.RETAIN)
    return sms_role


def _get_callback_urls(site_domain: str) -> list[str]:
    """Get OAuth callback URLs."""
    return [
        "http://localhost:5173",
        "https://local.dev.appworx.app:5173",
        f"https://{site_domain}",
        f"https://{site_domain}/callback",
    ]


def _get_logout_urls(site_domain: str) -> list[str]:
    """Get OAuth logout URLs."""
    return [
        "http://localhost:5173",
        "https://local.dev.appworx.app:5173",
        f"https://{site_domain}",
    ]


def _create_oauth_settings(site_domain: str) -> cognito.OAuthSettings:
    """Create OAuth settings for user pool client."""
    return cognito.OAuthSettings(
        flows=cognito.OAuthFlows(authorization_code_grant=True, implicit_code_grant=True),
        scopes=[cognito.OAuthScope.EMAIL, cognito.OAuthScope.OPENID, cognito.OAuthScope.PROFILE],
        callback_urls=_get_callback_urls(site_domain),
        logout_urls=_get_logout_urls(site_domain),
    )


def _create_password_policy() -> cognito.PasswordPolicy:
    """Create password policy for user pool."""
    return cognito.PasswordPolicy(
        min_length=8, require_lowercase=True, require_uppercase=True, require_digits=True, require_symbols=True
    )


def create_cognito_auth(
    scope: Construct,
    rn: Any,  # Resource naming function
    env_name: str,
    region_abbrev: str,
    site_domain: str,
    cognito_domain: str,
    cognito_certificate: "acm.Certificate",
    hosted_zone: route53.IHostedZone,
    post_auth_fn: lambda_.Function,
    pre_signup_fn: lambda_.Function,
) -> dict[str, Any]:
    """Create Cognito User Pool and related authentication resources.

    Args:
        scope: CDK construct scope
        rn: Resource naming function (name -> formatted name)
        env_name: Environment name (dev, prod, etc.)
        region_abbrev: Region abbreviation (e.g., ue1)
        site_domain: Site domain for callback URLs
        cognito_domain: Custom domain for Cognito hosted UI
        cognito_certificate: ACM certificate for Cognito custom domain
        hosted_zone: Route53 hosted zone for DNS records
        post_auth_fn: Lambda function for post-authentication trigger
        pre_signup_fn: Lambda function for pre-signup trigger

    Returns:
        Dictionary containing user_pool, user_pool_client, user_pool_domain, etc.
    """
    # Get the known pool ID or use context parameter
    known_pool_id = KNOWN_USER_POOL_IDS.get(env_name) or scope.node.try_get_context("user_pool_id")
    existing_user_pool_id = known_pool_id
    user_pool_triggers = _build_user_pool_triggers(scope, pre_signup_fn, post_auth_fn)

    result: dict[str, Any] = {}

    if existing_user_pool_id:
        result = _import_existing_user_pool(
            scope, rn, region_abbrev, env_name, site_domain, existing_user_pool_id, user_pool_triggers
        )
        user_pool = result["user_pool"]
        user_pool_client = result["user_pool_client"]
    else:
        result = _create_new_user_pool(
            scope, rn, site_domain, user_pool_triggers, pre_signup_fn, cognito_domain, cognito_certificate
        )
        user_pool = result["user_pool"]
        user_pool_client = result["user_pool_client"]

    # Handle User Pool Domain for imported pools
    _handle_imported_pool_domain(
        scope, existing_user_pool_id, cognito_domain, cognito_certificate, hosted_zone, user_pool, result
    )

    # Output Cognito Hosted UI URL for easy access
    _output_cognito_urls(scope, result, user_pool_client)

    result["user_pool"] = user_pool
    result["user_pool_client"] = user_pool_client

    return result


def _import_existing_user_pool(
    scope: Construct,
    rn: Any,
    region_abbrev: str,
    env_name: str,
    site_domain: str,
    existing_user_pool_id: str,
    user_pool_triggers: cognito.UserPoolTriggers | None,
) -> dict[str, Any]:
    """Import an existing Cognito User Pool."""
    print(f"Importing existing User Pool: {existing_user_pool_id}")
    result: dict[str, Any] = {}

    # SMS role - will be imported
    user_pool_sms_role = _create_sms_role(scope, region_abbrev, env_name)

    # Define the UserPool for import
    user_pool = cognito.UserPool(
        scope,
        "UserPool",
        user_pool_name=rn("kernelworx-users"),
        sign_in_aliases=cognito.SignInAliases(email=True, username=False),
        self_sign_up_enabled=True,
        auto_verify=cognito.AutoVerifiedAttrs(email=True),
        standard_attributes=cognito.StandardAttributes(
            email=cognito.StandardAttribute(required=True, mutable=True),
        ),
        password_policy=_create_password_policy(),
        account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
        mfa=cognito.Mfa.OPTIONAL,
        mfa_second_factor=cognito.MfaSecondFactor(sms=True, otp=True),
        sms_role=user_pool_sms_role,
        sms_role_external_id="kernelworx-sms-role",
        lambda_triggers=user_pool_triggers,
        removal_policy=RemovalPolicy.RETAIN,
    )
    user_pool.node.add_dependency(user_pool_sms_role)

    # Create/import UserPoolClient
    user_pool_client = cognito.UserPoolClient(
        scope,
        "AppClient",
        user_pool=user_pool,
        user_pool_client_name="KernelWorx-Web",
        auth_flows=cognito.AuthFlow(user_srp=True, user_password=True, user=True),
        o_auth=_create_oauth_settings(site_domain),
        supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
        prevent_user_existence_errors=True,
    )
    user_pool_client.node.default_child.apply_removal_policy(RemovalPolicy.RETAIN)

    result["user_pool_sms_role"] = user_pool_sms_role
    result["user_pool"] = user_pool
    result["user_pool_client"] = user_pool_client
    return result


def _create_new_user_pool(
    scope: Construct,
    rn: Any,
    site_domain: str,
    user_pool_triggers: cognito.UserPoolTriggers | None,
    pre_signup_fn: lambda_.Function,
    cognito_domain: str,
    cognito_certificate: "acm.Certificate",
) -> dict[str, Any]:
    """Create a new Cognito User Pool."""
    result: dict[str, Any] = {}

    user_pool = cognito.UserPool(
        scope,
        "UserPool",
        user_pool_name=rn("kernelworx-users"),
        sign_in_aliases=cognito.SignInAliases(email=True, username=False),
        self_sign_up_enabled=True,
        auto_verify=cognito.AutoVerifiedAttrs(email=True),
        standard_attributes=cognito.StandardAttributes(
            email=cognito.StandardAttribute(required=True, mutable=True),
            given_name=cognito.StandardAttribute(required=False, mutable=True),
            family_name=cognito.StandardAttribute(required=False, mutable=True),
        ),
        password_policy=_create_password_policy(),
        account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
        mfa=cognito.Mfa.OPTIONAL,
        mfa_second_factor=cognito.MfaSecondFactor(sms=True, otp=True),
        sign_in_policy=cognito.SignInPolicy(
            allowed_first_auth_factors=cognito.AllowedFirstAuthFactors(password=True, passkey=True)
        ),
        passkey_relying_party_id=site_domain,
        passkey_user_verification=cognito.PasskeyUserVerification.PREFERRED,
        removal_policy=RemovalPolicy.RETAIN,
        lambda_triggers=user_pool_triggers,
    )

    # Pre-signup Lambda needs permission to link identities and list users
    pre_signup_fn.add_to_role_policy(
        iam.PolicyStatement(
            actions=["cognito-idp:AdminLinkProviderForUser", "cognito-idp:ListUsers"],
            resources=[user_pool.user_pool_arn],
        )
    )

    # Configure user attribute update settings
    cfn_user_pool = user_pool.node.default_child
    assert cfn_user_pool is not None
    cfn_user_pool.user_attribute_update_settings = cognito.CfnUserPool.UserAttributeUpdateSettingsProperty(
        attributes_require_verification_before_update=["email"]
    )

    # Create ADMIN user group
    cognito.CfnUserPoolGroup(
        scope,
        "AdminGroup",
        user_pool_id=user_pool.user_pool_id,
        group_name="ADMIN",
        description="Administrator users with elevated privileges",
    )

    # Configure social identity providers and create client
    supported_providers = _configure_social_providers(scope, user_pool)
    user_pool_client = user_pool.add_client(
        "AppClient",
        user_pool_client_name="KernelWorx-Web",
        auth_flows=cognito.AuthFlow(user_srp=True, user_password=True, user=True),
        o_auth=_create_oauth_settings(site_domain),
        supported_identity_providers=supported_providers,
        prevent_user_existence_errors=True,
    )

    # Handle domain creation
    _handle_new_pool_domain(scope, user_pool, cognito_domain, cognito_certificate, result)

    result["user_pool"] = user_pool
    result["user_pool_client"] = user_pool_client
    return result


def _configure_social_providers(
    scope: Construct, user_pool: cognito.UserPool
) -> list[cognito.UserPoolClientIdentityProvider]:
    """Configure social identity providers (Google, Facebook, Apple)."""
    supported_providers: list[cognito.UserPoolClientIdentityProvider] = [cognito.UserPoolClientIdentityProvider.COGNITO]

    # Google OAuth
    if os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"):
        cognito.UserPoolIdentityProviderGoogle(
            scope,
            "GoogleProvider",
            user_pool=user_pool,
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

    # Facebook OAuth
    if os.environ.get("FACEBOOK_APP_ID") and os.environ.get("FACEBOOK_APP_SECRET"):
        cognito.UserPoolIdentityProviderFacebook(
            scope,
            "FacebookProvider",
            user_pool=user_pool,
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

    # Apple Sign In
    if (
        os.environ.get("APPLE_SERVICES_ID")
        and os.environ.get("APPLE_TEAM_ID")
        and os.environ.get("APPLE_KEY_ID")
        and os.environ.get("APPLE_PRIVATE_KEY")
    ):
        cognito.UserPoolIdentityProviderApple(
            scope,
            "AppleProvider",
            user_pool=user_pool,
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

    return supported_providers


def _should_create_cognito_domain(scope: Construct) -> bool:
    """Check if Cognito domain should be created."""
    ctx = scope.node.try_get_context("create_cognito_domain")
    if ctx is None:
        return True
    if isinstance(ctx, bool):
        return ctx
    return str(ctx).lower() != "false"


def _handle_new_pool_domain(
    scope: Construct,
    user_pool: cognito.UserPool,
    cognito_domain: str,
    cognito_certificate: "acm.Certificate",
    result: dict[str, Any],
) -> None:
    """Handle domain creation for new pools."""
    if _should_create_cognito_domain(scope):
        user_pool_domain = user_pool.add_domain(
            "UserPoolDomain",
            custom_domain=cognito.CustomDomainOptions(domain_name=cognito_domain, certificate=cognito_certificate),
        )
        user_pool_domain.node.add_dependency(cognito_certificate)
        result["user_pool_domain"] = user_pool_domain


def _should_skip_user_pool_domain(scope: Construct) -> bool:
    """Check if user pool domain should be skipped."""
    skip = scope.node.try_get_context("skip_user_pool_domain")
    if skip is None:
        return False
    if isinstance(skip, str):
        return skip.lower() == "true"
    return bool(skip)


def _handle_imported_pool_domain(
    scope: Construct,
    existing_user_pool_id: str | None,
    cognito_domain: str,
    cognito_certificate: "acm.Certificate",
    hosted_zone: route53.IHostedZone,
    user_pool: cognito.UserPool,
    result: dict[str, Any],
) -> None:
    """Handle domain for imported pools."""
    if not existing_user_pool_id:
        return

    if _should_skip_user_pool_domain(scope):
        print("Skipping User Pool Domain creation (import mode)")
        print("   To enable domain later: remove -c skip_user_pool_domain=true")
        return

    print(f"Defining User Pool Domain: {cognito_domain}")
    user_pool_domain = cognito.UserPoolDomain(
        scope,
        "UserPoolDomain",
        user_pool=user_pool,
        custom_domain=cognito.CustomDomainOptions(domain_name=cognito_domain, certificate=cognito_certificate),
    )
    user_pool_domain.node.default_child.apply_removal_policy(RemovalPolicy.RETAIN)

    print(f"Defining Route53 A record for Cognito domain: {cognito_domain}")
    cognito_domain_record = route53.ARecord(
        scope,
        "CognitoDomainRecord",
        zone=hosted_zone,
        record_name=cognito_domain,
        target=route53.RecordTarget.from_alias(targets.UserPoolDomainTarget(user_pool_domain)),
    )
    cognito_domain_record.apply_removal_policy(RemovalPolicy.RETAIN)

    result["user_pool_domain"] = user_pool_domain
    result["cognito_domain_record"] = cognito_domain_record


def _output_cognito_urls(scope: Construct, result: dict[str, Any], user_pool_client: cognito.UserPoolClient) -> None:
    """Output Cognito URLs for easy access."""
    if "user_pool_domain" in result:
        region = os.getenv("AWS_REGION") or os.getenv("CDK_DEFAULT_REGION") or "us-east-1"
        CfnOutput(
            scope,
            "CognitoHostedUIUrl",
            value=f"https://{result['user_pool_domain'].domain_name}.auth.{region}.amazoncognito.com/login?client_id={user_pool_client.user_pool_client_id}&response_type=code&redirect_uri=http://localhost:5173",
            description="Cognito Hosted UI URL for testing",
        )

    CfnOutput(
        scope,
        "UserPoolClientId",
        value=user_pool_client.user_pool_client_id,
        description="Cognito User Pool Client ID",
        export_name="kernelworx-ue1-dev-UserPoolClientId",
    )
