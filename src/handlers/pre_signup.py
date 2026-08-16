"""
Cognito Pre-Sign-Up Lambda Trigger

Automatically links federated identity providers (Google, Facebook) to existing
Cognito users with the same verified email. This prevents duplicate accounts when a user
signs up with email/password first, then later signs in with a social provider.

Trigger: Pre Sign Up
Event: Before a new user is created (for both native and federated sign-ups)

How it works:
1. When a federated user (e.g., Google) attempts to sign in for the first time
2. Cognito triggers Pre Sign Up before creating the user
3. This Lambda checks if a native user with the same email already exists
4. If so, it links the federated identity to the existing user
5. Then raises an exception to prevent duplicate user creation
6. The user is then signed in with the existing account
"""

import logging
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
    logger.info(f"Successfully linked {provider_name} identity to user {existing_username}")
    raise FederatedIdentityLinkedException(
        f"Account with email already exists. Your {provider_name} account has been linked. Please sign in again."
    )


def _handle_existing_user(
    cognito: Any, user_pool_id: str, email: str, username: str, existing_user: Dict[str, Any]
) -> NoReturn:
    """Handle linking when an existing user is found."""
    existing_username = existing_user["Username"]
    logger.info(f"Found existing user {existing_username} for email {mask_email(email)}, linking identity")
    _link_federated_identity(cognito, user_pool_id, existing_username, username)


def _handle_signup_exception(e: Exception, email: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Handle exceptions during federated signup processing."""
    if isinstance(e, FederatedIdentityLinkedException):
        raise e
    if isinstance(e, ClientError) and e.response.get("Error", {}).get("Code") == "InvalidParameterException":
        logger.warning(f"Link may already exist: {e}")
        raise FederatedIdentityLinkedException(f"Account with email {email} already exists. Please sign in again.")
    logger.exception(f"Error in pre-signup trigger: {str(e)}")
    return event


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
