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
from typing import Any, Dict

import boto3

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _auto_confirm_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Auto-confirm and auto-verify email for new federated sign-ups."""
    event["response"]["autoConfirmUser"] = True
    event["response"]["autoVerifyEmail"] = True
    return event


def _link_federated_identity(
    cognito: Any, user_pool_id: str, existing_username: str, username: str
) -> None:
    """Link federated identity to existing user."""
    if "_" not in username:
        logger.error(f"Unexpected federated username format: {username}")
        return
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
    raise Exception(
        f"Account with email already exists. "
        f"Your {provider_name} account has been linked. Please sign in again."
    )


def _handle_existing_user(
    cognito: Any, user_pool_id: str, email: str, username: str, existing_user: Dict[str, Any]
) -> None:
    """Handle linking when an existing user is found."""
    existing_username = existing_user["Username"]
    logger.info(f"Found existing user {existing_username} for email {email}, linking identity")
    _link_federated_identity(cognito, user_pool_id, existing_username, username)


def _handle_signup_exception(e: Exception, email: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Handle exceptions during federated signup processing."""
    error_msg = str(e)
    if "already exists" in error_msg or "has been linked" in error_msg:
        raise
    if "InvalidParameterException" in type(e).__name__:
        logger.warning(f"Link may already exist: {e}")
        raise Exception(f"Account with email {email} already exists. Please sign in again.")
    logger.exception(f"Error in pre-signup trigger: {error_msg}")
    return event


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Pre-Sign-Up Lambda Trigger Handler

    Links federated identities to existing users with matching email.

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

    logger.info(f"Pre-signup trigger: source={trigger_source}, username={username}, email={email}")

    # Only process federated sign-ups (external providers)
    if trigger_source != "PreSignUp_ExternalProvider":
        return event

    if not email:
        logger.warning("No email in federated sign-up, cannot check for duplicates")
        return event

    return _process_federated_signup(event, user_pool_id, username, email)


def _process_federated_signup(
    event: Dict[str, Any], user_pool_id: str, username: str, email: str
) -> Dict[str, Any]:
    """Process federated sign-up, linking to existing user if found."""
    try:
        cognito = boto3.client("cognito-idp")
        response = cognito.list_users(UserPoolId=user_pool_id, Filter=f'email = "{email}"', Limit=1)
        existing_users = response.get("Users", [])

        if not existing_users:
            logger.info(f"No existing user for {email}, allowing federated sign-up")
            return _auto_confirm_event(event)

        _handle_existing_user(cognito, user_pool_id, email, username, existing_users[0])
        return event  # Should not reach here due to exception

    except Exception as e:
        return _handle_signup_exception(e, email, event)
