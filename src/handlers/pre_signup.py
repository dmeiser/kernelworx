"""
Cognito Pre-Sign-Up Lambda Trigger

Two responsibilities:

1. Automatically links federated identity providers (Google, Facebook) to existing
Cognito users with the same verified email. This prevents duplicate accounts when a user
signs up with email/password first, then later signs in with a social provider.

2. Auto-confirms smoke-test sign-ups (``smoke+...@example-test.invalid``) in non-production
environments only, gated on the ``AUTO_CONFIRM_SMOKE_USERS`` env var that OpenTofu sets
only in dev/ephemeral. The e2e suites cannot read a mailbox, and each native sign-up burns
one of the account's 50-emails/day Cognito emails; see AGENTS.md "Smoke-test signup
auto-confirm gate". Production signups always keep normal email confirmation.

Trigger: Pre Sign Up
Event: Before a new user is created (for both native and federated sign-ups)

How federated linking works:
1. When a federated user (e.g., Google) attempts to sign in for the first time
2. Cognito triggers Pre Sign Up before creating the user
3. This Lambda checks if a native user with the same email already exists
4. If so, it links the federated identity to the existing user, but ONLY when
   that existing account is CONFIRMED and its email is verified (otherwise it
   fails closed — an unconfirmed signup could be an attacker account created
   with the victim's verified email)
5. Then raises an exception to prevent duplicate user creation
6. The user is then signed in with the existing account
"""

import logging
import os
import re
from typing import Any, Dict, NoReturn, Optional

import boto3
from botocore.exceptions import ClientError

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.logging import mask_email
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.logging import mask_email

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Conservative email pattern used to validate provider-supplied email before it is
# interpolated into a Cognito ListUsers filter string. This rejects characters that
# could break filter syntax or be used for injection (e.g. unescaped quotes/backslashes).
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

# Smoke-test users created by the e2e suites. These addresses live on the
# non-deliverable example-test.invalid TLD, and the suites cannot read a
# mailbox, so Cognito's normal confirmation email is both undeliverable and
# burns the account's 50-emails/day Cognito email quota (which, once
# exhausted, makes every native SignUp fail with LimitExceededException).
# The exact shape produced by tests/e2e (e.g. smoke+<random>@example-test.invalid).
SMOKE_EMAIL_PATTERN = re.compile(r"^smoke\+[a-z0-9._-]+@example-test\.invalid$", re.IGNORECASE)


# Environment-variable gate set by OpenTofu on the pre-signup Lambda in dev and
# ephemeral environments ONLY. It is deliberately absent (or "false") in
# production so production signups always keep normal email confirmation.
def _smoke_auto_confirm_enabled() -> bool:
    return os.environ.get("AUTO_CONFIRM_SMOKE_USERS", "").lower() == "true"


class FederatedIdentityLinkedException(Exception):
    """Raised when a federated identity is linked to an existing native account."""

    pass


def _auto_confirm_event(event: Dict[str, Any], verify_email: bool = True) -> Dict[str, Any]:
    """Auto-confirm a new federated sign-up and optionally auto-verify the email."""
    event["response"]["autoConfirmUser"] = True
    event["response"]["autoVerifyEmail"] = verify_email
    return event


def _is_email_verified(user_attributes: Dict[str, Any]) -> bool:
    """Return True when the federated provider explicitly verified the email address."""
    email_verified = user_attributes.get("email_verified")
    return email_verified is True or str(email_verified).lower() == "true"


def _validate_email(email: object) -> Optional[str]:
    """Validate and return a sanitized email, or None if it is unsafe/invalid."""
    if not isinstance(email, str):
        return None
    email = email.strip()
    if len(email) > 254:
        return None
    if EMAIL_PATTERN.fullmatch(email) is None:
        return None
    return email


def _link_federated_identity(cognito: Any, user_pool_id: str, existing_username: str, username: str) -> NoReturn:
    """Link federated identity to existing user."""
    if "_" not in username:
        logger.error(f"Unexpected federated username format: {username}")
        raise FederatedIdentityLinkedException("Cannot link federated identity: invalid username format")
    provider_name, provider_user_id = username.split("_", 1)
    cognito.admin_link_provider_for_user(
        UserPoolId=user_pool_id,
        DestinationUser={"ProviderName": "Cognito", "ProviderAttributeValue": existing_username},
        SourceUser={
            "ProviderName": provider_name,
            "ProviderAttributeName": "Cognito_Subject",
            "ProviderAttributeValue": provider_user_id,
        },
    )
    logger.info(f"Successfully linked {provider_name} identity to user {mask_email(existing_username)}")
    raise FederatedIdentityLinkedException(
        f"Account with email already exists. Your {provider_name} account has been linked. Please sign in again."
    )


def _existing_user_email_verified(existing_user: Dict[str, Any]) -> bool:
    """Return True when an existing (ListUsers) user's email is verified."""
    for attr in existing_user.get("Attributes", []):
        if attr.get("Name") == "email_verified":
            return str(attr.get("Value", "")).lower() == "true"
    return False


def _handle_existing_user(
    cognito: Any, user_pool_id: str, email: str, username: str, existing_user: Dict[str, Any]
) -> NoReturn:
    """Handle linking when an existing user is found.

    Only links when the existing account is confirmed and its email is verified.
    An unconfirmed native signup made with the victim's verified email could be
    an attacker account, so fail closed instead of handing it the identity.
    """
    existing_username = existing_user["Username"]

    if existing_user.get("UserStatus") != "CONFIRMED":
        logger.warning(f"Refusing to link: existing user {mask_email(existing_username)} is not confirmed")
        raise FederatedIdentityLinkedException(
            "An account with this email already exists but is not fully set up. "
            "Please resolve the existing account before signing in."
        )

    if not _existing_user_email_verified(existing_user):
        logger.warning(f"Refusing to link: existing user {mask_email(existing_username)} has an unverified email")
        raise FederatedIdentityLinkedException(
            "An account with this email already exists but its email is not verified. "
            "Please resolve the existing account before signing in."
        )

    logger.info(f"Found existing user {mask_email(existing_username)} for email {mask_email(email)}, linking identity")
    _link_federated_identity(cognito, user_pool_id, existing_username, username)


def _handle_signup_exception(e: Exception, email: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Handle exceptions during federated signup processing.

    Unexpected errors are re-raised so that Cognito does not proceed with a
    federated signup that could create a duplicate native account (e.g. on a
    transient ListUsers failure).
    """
    if isinstance(e, FederatedIdentityLinkedException):
        raise e
    if isinstance(e, ClientError) and e.response.get("Error", {}).get("Code") == "InvalidParameterException":
        logger.warning(f"Link may already exist: {e}")
        raise FederatedIdentityLinkedException(
            f"Account with email {mask_email(email)} already exists. Please sign in again."
        )
    logger.exception(f"Error in pre-signup trigger: {str(e)}")
    raise e


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Pre-Sign-Up Lambda Trigger Handler

    Links federated identities to existing native users with matching *verified* email.

    Event structure:
    {
        "version": "1",
        "triggerSource": "PreSignUp_ExternalProvider",
        "region": "us-east-1",
        "userPoolId": "us-east-1_EXAMPLE",
        "userName": "Google_123456789",
        "callerContext": {...},
        "request": {
            "userAttributes": {
                "email": "user@example.com",
                "email_verified": "true"
            }
        },
        "response": {
            "autoConfirmUser": false,
            "autoVerifyEmail": false,
            "autoVerifyPhone": false
        }
    }

    Trigger sources:
    - PreSignUp_SignUp: Native Cognito sign-up
    - PreSignUp_ExternalProvider: Federated sign-up (Google, Facebook, etc.)
    - PreSignUp_AdminCreateUser: Admin-created user

    Args:
        event: Cognito Pre Sign Up trigger event
        context: Lambda context

    Returns:
        event: Modified event (can auto-confirm users)

    Raises:
        Exception: If federated identity is linked to existing user (prevents duplicate)
    """
    trigger_source = event.get("triggerSource", "")
    user_pool_id = event.get("userPoolId", "")
    username = event.get("userName", "")
    user_attributes = event.get("request", {}).get("userAttributes", {})
    email = user_attributes.get("email", "")

    logger.info(f"Pre-signup trigger: source={trigger_source}, username={username}, email={mask_email(email)}")

    # Auto-confirm smoke-test users in non-production environments only.
    # The flag is set by OpenTofu on the Lambda in dev/ephemeral; when it is
    # absent (prod) this branch never runs and native signups keep the normal
    # email-confirmation flow.
    if trigger_source == "PreSignUp_SignUp" and _smoke_auto_confirm_enabled() and SMOKE_EMAIL_PATTERN.fullmatch(email):
        logger.info(f"Auto-confirming smoke-test sign-up for {mask_email(email)} (non-prod gate)")
        return _auto_confirm_event(event)

    # Only process federated sign-ups (external providers)
    if trigger_source != "PreSignUp_ExternalProvider":
        return event

    if not email:
        logger.warning("No email in federated sign-up, cannot check for duplicates")
        return _auto_confirm_event(event, verify_email=False)

    if not _is_email_verified(user_attributes):
        logger.warning("Federated provider did not verify email, skipping auto-link")
        return _auto_confirm_event(event, verify_email=False)

    validated_email = _validate_email(email)
    if not validated_email:
        logger.warning("Invalid or unsafe email from federated provider, skipping auto-link")
        return _auto_confirm_event(event, verify_email=False)

    return _process_federated_signup(event, user_pool_id, username, validated_email)


def _process_federated_signup(event: Dict[str, Any], user_pool_id: str, username: str, email: str) -> Dict[str, Any]:
    """Process federated sign-up, linking to existing user if found."""
    try:
        cognito = boto3.client("cognito-idp")
        response = cognito.list_users(UserPoolId=user_pool_id, Filter=f'email = "{email}"', Limit=1)
        existing_users = response.get("Users", [])

        if not existing_users:
            logger.info(f"No existing user for {mask_email(email)}, allowing federated sign-up")
            return _auto_confirm_event(event)

        _handle_existing_user(cognito, user_pool_id, email, username, existing_users[0])

    except Exception as e:
        return _handle_signup_exception(e, email, event)
