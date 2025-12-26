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
        # For native sign-ups, just return the event
        # Could add validation here (e.g., email domain restrictions)
        return event

    # For federated sign-ups, check if a user with this email already exists
    if not email:
        logger.warning("No email in federated sign-up, cannot check for duplicates")
        return event

    try:
        cognito = boto3.client("cognito-idp")

        # Search for existing user with this email
        response = cognito.list_users(
            UserPoolId=user_pool_id,
            Filter=f'email = "{email}"',
            Limit=1,
        )

        existing_users = response.get("Users", [])

        if not existing_users:
            # No existing user, allow the federated sign-up to proceed
            # Auto-confirm and auto-verify since the email is verified by the provider
            event["response"]["autoConfirmUser"] = True
            event["response"]["autoVerifyEmail"] = True
            logger.info(f"No existing user for {email}, allowing federated sign-up")
            return event

        # Found an existing user with this email
        existing_user = existing_users[0]
        existing_username = existing_user["Username"]

        logger.info(f"Found existing user {existing_username} for email {email}, linking identity")

        # Parse the federated username to get provider info
        # Format: "Google_123456789" or "Facebook_123456789"
        if "_" not in username:
            logger.error(f"Unexpected federated username format: {username}")
            return event

        provider_name, provider_user_id = username.split("_", 1)

        # Link the federated identity to the existing user
        cognito.admin_link_provider_for_user(
            UserPoolId=user_pool_id,
            DestinationUser={
                "ProviderName": "Cognito",
                "ProviderAttributeValue": existing_username,
            },
            SourceUser={
                "ProviderName": provider_name,
                "ProviderAttributeName": "Cognito_Subject",
                "ProviderAttributeValue": provider_user_id,
            },
        )

        logger.info(f"Successfully linked {provider_name} identity to user {existing_username}")

        # Raise an exception to prevent duplicate user creation
        # The federated identity is now linked to the existing user
        # Cognito will use the existing user for authentication
        raise Exception(
            f"Account with email {email} already exists. "
            f"Your {provider_name} account has been linked. Please sign in again."
        )

    except cognito.exceptions.InvalidParameterException as e:
        # Link may already exist, which is fine
        logger.warning(f"Link may already exist: {e}")
        raise Exception(f"Account with email {email} already exists. Please sign in again.")

    except Exception as e:
        if "already exists" in str(e) or "has been linked" in str(e):
            # Re-raise our own exception
            raise
        logger.exception(f"Error in pre-signup trigger: {str(e)}")
        # For other errors, allow sign-up to proceed to avoid blocking users
        return event
