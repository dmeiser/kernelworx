"""Cognito sign-in and AppSync GraphQL helpers for the Show & Sell acceptance harness.

The journey is driven through the browser, but two of its assertions are about
what the *server* answers, not what the page renders:

* an account with no Unit grant must be refused Unit data (cross-Unit denial);
* teardown must be verifiable — the roster really holds no ACTIVE membership.

Those checks are made here, with the same Cognito identity the browser used.
Sign-in goes through the public Cognito REST endpoint (``InitiateAuth`` with
``USER_PASSWORD_AUTH``), which needs no AWS credentials — the app client carries
``ALLOW_USER_PASSWORD_AUTH``, and a public client id is not a secret.

Identities are the standing QA fixture (``qa-show-sell-{admin,admin2,scout,outside}``),
never created or reset here: the fixture is one script with one owner
(WORK-201, ``scripts/qa_fixture.py``), and this harness only reads what that
script publishes — the ``TEST_QA_SHOW_SELL_*`` environment. A second way to
create these users is how the dev pool acquired eighteen app clients named
``KernelWorx-Web``.

Credential discipline: passwords arrive only as environment values and are never
placed in a message, log line, exception, or artifact. ``_cognito_error`` builds
its text from the service's own ``__type``/``message`` fields only, never from
the request body, and the missing-configuration error names the keys that are
absent — never a value that is present.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

__all__ = [
    "GraphQLError",
    "base_url",
    "client_id",
    "error_summaries",
    "gql",
    "gql_raw",
    "my_profiles",
    "my_units",
    "pool_id",
    "publish_base_url",
    "qa_identities",
    "region",
    "sign_in",
    "unit_admins",
    "unit_campaign_roster",
]

#: The four fixture personas, in the order the journey meets them.
PERSONAS: tuple[str, ...] = ("admin", "admin2", "scout", "outside")

#: Persona → the environment pair the fixture publishes for it.
_EMAIL_VARS = {
    "admin": "TEST_QA_SHOW_SELL_ADMIN_EMAIL",
    "admin2": "TEST_QA_SHOW_SELL_ADMIN2_EMAIL",
    "scout": "TEST_QA_SHOW_SELL_SCOUT_EMAIL",
    "outside": "TEST_QA_SHOW_SELL_OUTSIDE_EMAIL",
}
_PASSWORD_VARS = {
    "admin": "TEST_QA_SHOW_SELL_ADMIN_PASSWORD",
    "admin2": "TEST_QA_SHOW_SELL_ADMIN2_PASSWORD",
    "scout": "TEST_QA_SHOW_SELL_SCOUT_PASSWORD",
    "outside": "TEST_QA_SHOW_SELL_OUTSIDE_PASSWORD",
}

_BASE_URL_VARS = ("TEST_QA_SHOW_SELL_BASE_URL", "E2E_BASE_URL")
_CLIENT_ID_VARS = ("TEST_USER_POOL_CLIENT_ID", "TEST_QA_SHOW_SELL_CLIENT_ID")
_REGION_VARS = ("TEST_REGION", "AWS_REGION")
_POOL_ID_VARS = ("TEST_USER_POOL_ID",)


class GraphQLError(RuntimeError):
    """A GraphQL response carried ``errors``.

    Args:
        message: Combined service messages.
        codes: ``extensions.code`` / ``extensions.errorType`` values, in order.
        payload: The full response body, for evidence files.
    """

    def __init__(self, message: str, codes: list[str], payload: dict[str, Any]) -> None:
        """Store the message, the error codes, and the body they came from."""
        super().__init__(message)
        self.codes = codes
        self.payload = payload


def _first_env(names: tuple[str, ...]) -> str:
    """Return the first non-empty value among *names*.

    Args:
        names: environment keys to try, in precedence order.

    Returns:
        The value, or an empty string when none is set.
    """
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _require_env(names: tuple[str, ...], why: str) -> str:
    """Return the first non-empty value among *names*, or say what is missing.

    Only key names appear in the raised text: this module handles passwords, and
    a configuration error that echoes a value is a leaked credential.

    Args:
        names: environment keys to try, in precedence order.
        why: what the value is needed for.

    Returns:
        The configured value.

    Raises:
        EnvironmentError: naming every key that was tried.
    """
    value = _first_env(names)
    if not value:
        raise EnvironmentError(f"{why}: set one of {' or '.join(names)}")
    return value


def qa_identities() -> dict[str, dict[str, str]]:
    """Return the four fixture identities, read from the environment.

    Returns:
        A map of persona to ``{"email": ..., "password": ...}``.

    Raises:
        EnvironmentError: naming each missing key. It never runs partially: a
            journey with three of four identities cannot show the preview gate
            both ways, so a missing identity is a stopped run rather than a
            skipped step. Only key names appear in the text.
    """
    keys = [*_EMAIL_VARS.values(), *_PASSWORD_VARS.values()]
    missing = [key for key in keys if not os.getenv(key, "").strip()]
    if missing:
        raise EnvironmentError(
            "the QA fixture identities are not in this environment: set "
            + ", ".join(missing)
            + " (the fixture script publishes them; see tests/e2e/README.md)"
        )
    return {
        persona: {"email": os.environ[_EMAIL_VARS[persona]], "password": os.environ[_PASSWORD_VARS[persona]]}
        for persona in PERSONAS
    }


def base_url() -> str:
    """Return the deployed app origin, which is also the AppSync proxy origin."""
    return _require_env(_BASE_URL_VARS, "the acceptance run needs the deployed app URL").rstrip("/")


def publish_base_url() -> str:
    """Write the deployment origin into ``E2E_BASE_URL`` so the browser follows it too.

    Two halves of this run reach the same app by different doors: the GraphQL
    probes read ``TEST_QA_SHOW_SELL_BASE_URL``, while every browser navigation goes
    through ``tests/e2e/pages/base_page.py``, which reads ``E2E_BASE_URL`` and falls
    back to ``https://localhost:5173``.  A QA lane holding exactly the card's
    environment would therefore probe the deployed stack while driving a browser at
    a Vite server that is not running, and the journey would stop before step 1.
    Publishing the resolved origin once, before any navigation, is what makes the
    documented recipe runnable from that environment alone.

    ``TEST_QA_SHOW_SELL_BASE_URL`` wins when it is set, including over a stale
    ``E2E_BASE_URL``: the two halves must never aim at different deployments, and
    the card's key is the one its consumers are told to set.  With only
    ``E2E_BASE_URL`` set, it is kept, which is how the other e2e suites already
    choose their target.

    Returns:
        The origin now in effect for the browser and the probes, without a
        trailing slash.

    Raises:
        EnvironmentError: naming both keys when neither is set.
    """
    origin = base_url()
    os.environ["E2E_BASE_URL"] = origin
    return origin


def client_id() -> str:
    """Return the Cognito app client id to sign in with.

    It is taken from the environment rather than looked up by name on purpose:
    the dev pool currently holds many app clients named ``KernelWorx-Web``, and
    only one of them carries ``ALLOW_USER_PASSWORD_AUTH``. A name lookup
    therefore succeeds about as often as it fails, and it fails later, with a
    message that says nothing about the pool (the #567 class).
    """
    return _require_env(_CLIENT_ID_VARS, "the acceptance run needs the app client id")


def region() -> str:
    """Return the pool's region, defaulting to the stack's region."""
    return _first_env(_REGION_VARS) or "us-east-1"


def pool_id() -> str:
    """Return the user pool id for the evidence record, empty when unset.

    Nothing in the run needs it — sign-in is by app client id and the browser
    needs neither — so a missing value is a blank in the record rather than a
    failed journey.
    """
    return _first_env(_POOL_ID_VARS)


def _cognito_error(body: bytes) -> str:
    """Describe a Cognito failure using only the service's own words.

    Args:
        body: The raw JSON error body from the Cognito endpoint.

    Returns:
        ``"<__type>: <message>"``, or the truncated raw body when it is not JSON.
    """
    try:
        parsed = json.loads(body.decode("utf-8"))
    except UnicodeDecodeError, json.JSONDecodeError:
        return body[:400].decode("utf-8", errors="replace")
    error_type = str(parsed.get("__type", "")).rsplit("#", 1)[-1] or "CognitoError"
    message = str(parsed.get("message") or parsed.get("msg") or "no message")
    return f"{error_type}: {message}"


def sign_in(email: str, password: str, app_client_id: str, pool_region: str) -> str:
    """Exchange an email and password for a Cognito ID token.

    Args:
        email: the identity's email.
        password: its password. Never echoed, whatever happens.
        app_client_id: a public client id that allows ``USER_PASSWORD_AUTH``.
        pool_region: the pool's region.

    Returns:
        The ID token, whose ``cognito:groups`` claim is what the preview gate reads.

    Raises:
        RuntimeError: naming the flow and the service's own error, never the password.
    """
    endpoint = f"https://cognito-idp.{pool_region}.amazonaws.com/"
    payload = {
        "AuthFlow": "USER_PASSWORD_AUTH",
        "ClientId": app_client_id,
        "AuthParameters": {"USERNAME": email, "PASSWORD": password},
    }
    request = urllib.request.Request(  # noqa: S310 - the host is the fixed Cognito endpoint
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _cognito_error(exc.read())
        raise RuntimeError(f"sign-in as {email} failed: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"sign-in as {email} could not reach Cognito in {pool_region}: {exc}") from exc
    token = str((body.get("AuthenticationResult") or {}).get("IdToken") or "")
    if not token:
        raise RuntimeError(
            f"sign-in as {email} returned no ID token (challenge: {body.get('ChallengeName') or 'none'})"
        )
    return token


def error_summaries(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Return one ``message``/``code`` pair per GraphQL error in a response body.

    The code has four homes depending on which resolver answered, and reading only
    one of them reports a refusal as codeless: the Lambda path puts it in
    ``extensions.code`` or ``extensions.errorCode``, an APPSYNC_JS resolver puts it
    on the error's own ``errorType`` with a copy in ``errorInfo.errorCode``, and a
    validation error has none at all.  An empty code is kept rather than dropped —
    that is a fact about the answer, not a missing field.

    Args:
        payload: the raw response body.
    """
    summaries = []
    for error in payload.get("errors") or []:
        extensions = error.get("extensions") or {}
        error_info = error.get("errorInfo") or {}
        code = (
            extensions.get("code")
            or extensions.get("errorCode")
            or extensions.get("errorType")
            or error.get("errorType")
            or error_info.get("errorCode")
            or ""
        )
        summaries.append({"message": str(error.get("message", "")), "code": str(code)})
    return summaries


def gql_raw(token: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST a GraphQL operation and return the whole response body.

    Used where the answer itself is the finding — a refusal, or a null with no
    data — so the caller reads the response instead of having it raised.

    Args:
        token: a Cognito ID token.
        query: the operation.
        variables: operation variables.

    Returns:
        The parsed response body.
    """
    body = {"query": query, "variables": variables or {}}
    request = urllib.request.Request(  # noqa: S310 - same-origin GraphQL over the deployed app
        f"{base_url()}/graphql",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode("utf-8") or "{}")


def gql(token: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST a GraphQL operation and return its ``data``, raising on ``errors``.

    Args:
        token: a Cognito ID token.
        query: the operation.
        variables: operation variables.

    Returns:
        The ``data`` object.

    Raises:
        GraphQLError: the response carried ``errors``.
    """
    payload = gql_raw(token, query, variables)
    errors = payload.get("errors") or []
    if errors:
        messages = "; ".join(str(error.get("message", "")) for error in errors)
        codes = [
            str((error.get("extensions") or {}).get("code") or (error.get("extensions") or {}).get("errorType") or "")
            for error in errors
        ]
        raise GraphQLError(messages, codes, payload)
    return payload.get("data") or {}


def my_profiles(token: str) -> list[dict[str, Any]]:
    """Return the caller's owned Scout profiles.

    Args:
        token: the profile owner's ID token.
    """
    data = gql(token, "query { listMyProfiles(limit: 100) { profiles { profileId sellerName } } }")
    return list(((data.get("listMyProfiles") or {}).get("profiles")) or [])


def my_units(token: str) -> list[dict[str, Any]]:
    """Return the Units the caller can see, with the fields the tenant key uses.

    The four metadata fields are what ``createUnit`` matches on, so a re-run can
    recognize the Unit its own DATA_ID already created instead of walking into the
    duplicate answer.

    Args:
        token: the caller's ID token.
    """
    data = gql(
        token,
        "query { myUnits(page: {limit: 50}) { items { unitId unitType unitNumber city state displayName } } }",
    )
    return [dict(item) for item in ((data.get("myUnits") or {}).get("items")) or []]


def unit_admins(token: str, unit_id: str) -> list[dict[str, Any]]:
    """Return a Unit's admin grants.

    Args:
        token: a Unit admin's ID token.
        unit_id: the Unit to read.
    """
    data = gql(
        token,
        """query Admins($unitId: ID!) {
            unitAdmins(unitId: $unitId, page: {limit: 50}) { items { accountId email role } }
          }""",
        {"unitId": unit_id},
    )
    return [dict(item) for item in ((data.get("unitAdmins") or {}).get("items")) or []]


def unit_campaign_roster(token: str, unit_campaign_id: str) -> list[dict[str, Any]]:
    """Return a Unit Campaign's roster, removed history included.

    Args:
        token: a Unit admin's ID token.
        unit_campaign_id: the Unit Campaign to read.
    """
    data = gql(
        token,
        """query Roster($unitCampaignId: ID!) {
            unitCampaignRoster(unitCampaignId: $unitCampaignId, page: {limit: 50}) {
              items { campaignId profileId status guardVersion }
            }
          }""",
        {"unitCampaignId": unit_campaign_id},
    )
    return list(((data.get("unitCampaignRoster") or {}).get("items")) or [])
