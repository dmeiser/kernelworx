"""
Cognito Pre Token Generation Lambda Trigger

Injects a custom boolean `mfa` claim into the ID and access tokens that Cognito
issues at sign-in and on token refresh (issue #336).

The claim is ALWAYS set explicitly:
  - false when the session is for a federated identity (e.g. Google sign-in).
          Federated sign-ins can never present an MFA factor in Cognito, so they
          always mint mfa=false to close the enrollment-as-proof hole for social
          users (admin requires a native password sign-in).
  - true  for native users when AdminGetUser reports PreferredMfaSetting is an
          enabled MFA factor (SOFTWARE_TOKEN_MFA / TOTP, or SMS_MFA) -- any
          enabled MFA counts.
  - false otherwise for native users (e.g. no MFA preference, passkey-only,
          missing subject, or any AdminGetUser error).

A missing `mfa` claim therefore unambiguously means this trigger is not in the
token path, so the enforcement guard (#406) can deny on a missing claim. We never
write the reserved `amr` claim: AWS documents that the pre-token-generation
trigger cannot add, modify, or suppress `amr` (it is read-only for this trigger),
which is why a custom claim is used instead of amr.

Passkeys (WebAuthn) are intentionally NOT detected here. A passkey is a first
authentication factor in Cognito -- a peer of password, not a second/MFA factor --
and this trigger has no per-session signal that a given sign-in used one: the
V2_0/V3_0 trigger event carries no auth-method field (only userAttributes/scopes/
groupConfiguration/clientMetadata), and the passkey-credential APIs (for example
ListWebAuthnCredentials) require the signed-in user's own access token -- the very
token being minted -- so they are unavailable to this trigger. AdminGetUser reports
MFA preference only, never passkey state. Whether Cognito stamps a native `amr`
claim on passkey sessions (which the #406 guard may honor) is a property of the
guard, not of this trigger.
"""

import logging
from typing import Any, Dict

import boto3

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Cognito PreferredMfaSetting values (AdminGetUser) that denote an enabled MFA
# factor. The captain uses multiple factors, so any enabled MFA counts; this
# widens the original TOTP-only check to also accept SMS.
SOFTWARE_TOKEN_MFA = "SOFTWARE_TOKEN_MFA"
SMS_MFA = "SMS_MFA"
MFA_PREFERENCES = frozenset({SOFTWARE_TOKEN_MFA, SMS_MFA})
# Custom claim name. Must stay exactly "mfa": the #405 (frontend) and #406
# (backend) guards both read it from the ID token.
MFA_CLAIM = "mfa"


def _is_federated(user_attributes: Dict[str, Any]) -> bool:
    """
    Determine whether the user authenticated via a federated identity provider.

    Cognito populates the `identities` user attribute exclusively for federated
    (social / SAML / OIDC) users as a JSON-encoded array containing provider
    metadata (e.g. providerName, providerType, userId). For native Cognito users
    (email/password), `identities` is absent.

    AWS Documentation reference: Amazon Cognito User Pools Developer Guide,
    'Managing External Identity Provider (IdP) user profiles' and 'User pool
    attributes' (identities attribute). Also documented in trigger event fixtures
    (e.g., src/handlers/post_authentication.py:50).
    """
    identities = user_attributes.get("identities")
    if not identities:
        return False
    if isinstance(identities, str):
        return bool(identities.strip() and identities.strip() != "[]")
    if isinstance(identities, (list, dict)):
        return bool(identities)
    return True


def _resolve_mfa(event: Dict[str, Any]) -> bool:
    """
    Determine the `mfa` claim value for this token issuance.

    Federated (social) identities ALWAYS mint mfa=false: federated sign-ins can
    never present an MFA factor in Cognito, closing the enrollment-as-proof hole
    where a social admin with enrolled TOTP would receive mfa:true without presenting
    a factor code. Admin access requires a native password sign-in.

    For native users, true when the user's preferred MFA is an enabled MFA factor
    (a TOTP software token or SMS). Passkeys are a separate first factor this trigger
    cannot detect (see the module docstring), so they are not counted here. Fails
    closed (False) on a missing subject/user pool or any AdminGetUser error so a
    Cognito API hiccup can never grant MFA access.
    """
    user_attributes = event.get("request", {}).get("userAttributes", {})
    if _is_federated(user_attributes):
        logger.info("pre-token-generation: federated identity -> mfa=false")
        return False

    user_pool_id = event.get("userPoolId", "")
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
    return preferred in MFA_PREFERENCES


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

    Sets the custom boolean `mfa` claim on the issued ID and access tokens:
      - false for federated (social) identities, regardless of MFA enrollment.
      - true for native users when their preferred MFA is an enabled factor
        (TOTP software token or SMS).
      - false for native users without enabled MFA or upon lookup failure.

    The claim is always set explicitly and the handler always returns the event
    so a trigger error can never block sign-in.

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
