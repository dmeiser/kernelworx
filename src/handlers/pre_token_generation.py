"""
Cognito Pre Token Generation Lambda Trigger

Injects a custom boolean `mfa` claim into the ID and access tokens that Cognito
issues at sign-in and on token refresh (issue #336).

The claim is ALWAYS set explicitly:
  - true  when AdminGetUser reports PreferredMfaSetting == SOFTWARE_TOKEN_MFA
  - false otherwise, including a missing subject or any AdminGetUser error

A missing `mfa` claim therefore unambiguously means this trigger is not in the
token path, so the enforcement guard (#406) can deny on a missing claim. We never
write the reserved `amr` claim: AWS documents that the pre-token-generation
trigger cannot add, modify, or suppress `amr` (it is read-only for this trigger),
which is why a custom claim is used instead of amr.
"""

import logging
from typing import Any, Dict

import boto3

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# The Cognito TOTP software-token MFA setting value reported by AdminGetUser.
SOFTWARE_TOKEN_MFA = "SOFTWARE_TOKEN_MFA"
# Custom claim name. Must stay exactly "mfa": the #405 (frontend) and #406
# (backend) guards both read it from the ID token.
MFA_CLAIM = "mfa"


def _resolve_mfa(event: Dict[str, Any]) -> bool:
    """
    Determine the `mfa` claim value for this token issuance.

    True only when the user's preferred MFA is a TOTP software token. Fails
    closed (False) on a missing subject/user pool or any AdminGetUser error so a
    Cognito API hiccup can never grant MFA access.
    """
    user_pool_id = event.get("userPoolId", "")
    user_attributes = event.get("request", {}).get("userAttributes", {})
    sub = user_attributes.get("sub")
    username = sub or event.get("userName", "")
    if not user_pool_id or not username:
        logger.warning("pre-token-generation: missing userPoolId or sub; setting mfa=false")
        return False
    try:
        cognito = boto3.client("cognito-idp")
        response = cognito.admin_get_user(UserPoolId=user_pool_id, Username=username)
    except Exception:
        logger.warning(
            f"pre-token-generation: AdminGetUser failed for sub={sub}; setting mfa=false (fail-closed)",
            exc_info=True,
        )
        return False
    preferred: str | None = response.get("PreferredMfaSetting")
    return preferred == SOFTWARE_TOKEN_MFA


def _set_mfa_claim(event: Dict[str, Any], value: bool) -> None:
    """
    Set the boolean `mfa` claim on both the ID and access tokens and preserve
    cognito:groups.

    Uses the V2_0 event shape (claimsAndScopeOverrideDetails): version one
    responses only accept string claim values, so a boolean claim requires
    version two. Both idTokenGeneration and accessTokenGeneration carry
    claimsToAddOrOverride. The request's groupConfiguration is copied into
    groupOverrideDetails because otherwise Cognito suppresses cognito:groups,
    which admin authorization depends on.
    """
    claims = {MFA_CLAIM: value}
    override: Dict[str, Any] = {
        "idTokenGeneration": {"claimsToAddOrOverride": claims},
        "accessTokenGeneration": {"claimsToAddOrOverride": claims},
    }
    group_configuration = event.get("request", {}).get("groupConfiguration")
    if group_configuration is not None:
        override["groupOverrideDetails"] = group_configuration
    event.setdefault("response", {})["claimsAndScopeOverrideDetails"] = override


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Cognito Pre Token Generation trigger handler.

    Sets the custom boolean `mfa` claim (true only when the user's preferred MFA
    is a TOTP software token) on the issued ID and access tokens. The claim is
    always set explicitly and the handler always returns the event so a trigger
    error can never block sign-in.

    Args:
        event: Cognito Pre Token Generation trigger event (version two)
        context: Lambda context

    Returns:
        event: The event with response.claimsAndScopeOverrideDetails populated
    """
    value = False
    try:
        value = _resolve_mfa(event)
        _set_mfa_claim(event, value)
    except Exception:
        # Never let the trigger raise: a raised pre-token-generation trigger makes
        # Cognito fail token issuance for every sign-in. Fail closed instead.
        logger.warning("pre-token-generation: unexpected error; failing closed (mfa=false)", exc_info=True)
        value = False
        try:
            _set_mfa_claim(event, False)
        except Exception:
            logger.warning(
                "pre-token-generation: could not set mfa=false; returning event unmodified",
                exc_info=True,
            )
    # Static message: do not interpolate the (event-derived) mfa value into the
    # log. CodeQL taint-tracks values derived from the trigger event as sensitive
    # and flags clear-text logging of them (clear-text logging of sensitive info).
    logger.info("pre-token-generation: mfa claim set on issued tokens")
    return event
