"""Smoke tests for authorization boundaries.

Verifies that:

* Unauthenticated users are redirected to ``/login`` when they navigate to a
  protected route.
* A contributor cannot access an owner's profile that has not been shared with
  them.
* The public order routes (``/o/<profileId>/<token>``) stay reachable without a
  session while every protected route — including the new
  ``/scouts/<profileId>/public-orders`` settings page — still redirects
  (spec 10.5 item 12).
* The public API key cannot reach the Cognito-only profile fields
  (``getProfile`` / ``listMyProfiles``).

Test ordering
-------------
``test_owner_profile_id_for_boundary`` runs before
``test_contributor_cannot_access_unshared_profile`` and populates
``_auth_boundary_state`` with the owner's first profile ID.  A test that
cannot find required state calls ``pytest.skip`` with a clear reason instead
of raising an ``AssertionError``.

Since this module is named ``test_smoke_auth_boundary``, it runs before the
sharing tests (``test_smoke_sharing``) in the default alphabetical collection
order.  At the start of each run the contributing user should therefore hold
no active share on the owner's profiles, making the boundary test reliable.
The ``pytest.skip`` guard in ``test_contributor_cannot_access_unshared_profile``
protects against stale share records from a previous run that ended before
``global_cleanup`` completed.

Two browser contexts
--------------------
``owner_page`` and ``contributor_page`` both wrap the same pytest-playwright
function-scoped ``page`` fixture, so they must **not** be requested in the
same test function.  The owner's profile ID is captured in a dedicated setup
test (``test_owner_profile_id_for_boundary``) and passed to the contributor
test via the module-scoped ``_auth_boundary_state`` dict.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.public_order_page import PublicOrderPage
from tests.e2e.pages.share_page import SharePage
from tests.e2e.utils.auth import login_as_owner


def _base_url() -> str:
    """Return base URL from env at call time (after load_dotenv has run)."""
    return os.getenv("E2E_BASE_URL", "https://localhost:5173").rstrip("/")


# ---------------------------------------------------------------------------
# Module-scoped state fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _auth_boundary_state() -> dict[str, str]:
    """Mutable dict shared across all tests in this module.

    Keys populated at runtime:

    * ``"profile_id"`` – set by ``test_owner_profile_id_for_boundary``
    """
    return {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_unauthenticated_redirect_to_login(page: Page) -> None:
    """Unauthenticated access to a protected route must redirect to /login.

    Uses the plain ``page`` fixture (no login performed) and navigates
    directly to ``/scouts``.  The app's ``ProtectedRoute`` component must
    redirect to ``/login`` before rendering any protected content.
    """
    page.goto(f"{_base_url()}/scouts")
    page.wait_for_url("**/login", timeout=10_000)
    assert "/login" in page.url, f"Unauthenticated access to /scouts must redirect to /login; current URL: {page.url}"


@pytest.mark.smoke
def test_owner_profile_id_for_boundary(
    owner_page: Page, _auth_boundary_state: dict[str, str], ensure_owner_profile: str
) -> None:
    """Capture the owner's first profile ID for use by the contributor boundary test.

    Navigates the owner to their dashboard, clicks the first visible profile
    card, extracts the profile ID from the resulting URL, and stores it in
    ``_auth_boundary_state``.

    Skips when the owner has no profiles (pristine environment without
    pre-seeded profile data — profiles are typically created during the
    campaign smoke tests which run later alphabetically).
    """
    dashboard = DashboardPage(owner_page)
    dashboard.goto()

    try:
        dashboard.wait_for_profiles_loaded()
    except Exception:  # noqa: BLE001
        pytest.skip("Owner has no visible profiles; cannot populate boundary test state")

    profiles = dashboard.get_profile_names()
    if not profiles:
        pytest.skip("Owner has no profiles — cannot set up authorization boundary test")

    dashboard.click_profile(profiles[0])

    match = re.search(r"/scouts/([^/]+)/campaigns", owner_page.url)
    if not match:
        pytest.skip(f"Could not extract profile_id from campaigns URL: {owner_page.url}")

    _auth_boundary_state["profile_id"] = urllib.parse.unquote(match.group(1))


@pytest.mark.smoke
def test_contributor_cannot_access_unshared_profile(
    contributor_page: Page,
    _auth_boundary_state: dict[str, str],
    browser: Browser,
) -> None:
    """Contributor sees an access-denied alert for an owner profile with no share.

    Navigates the contributor directly to the owner's campaigns URL.  The app
    renders an error alert ("Profile not found or you don't have access to this
    profile.") in-place — it does **not** redirect the user to another URL.

    Because the TypeScript global cleanup may be unavailable in this
    environment, the test first logs in as the owner and revokes any existing
    share for the contributor on the target profile.
    """
    profile_id = _auth_boundary_state.get("profile_id", "")
    if not profile_id:
        pytest.skip("profile_id not set — ensure test_owner_profile_id_for_boundary ran first")

    contributor_email = os.environ.get("TEST_CONTRIBUTOR_EMAIL", "")

    # Ensure the contributor has no share for this profile (cleanup fallback).
    owner_context: BrowserContext = browser.new_context(ignore_https_errors=True)
    try:
        owner_page: Page = owner_context.new_page()
        login_as_owner(owner_page)
        share_page = SharePage(owner_page)
        share_page.goto(profile_id)
        if share_page.has_shared_access(contributor_email):
            share_page.revoke_access(contributor_email)
    finally:
        owner_context.close()

    campaign_page = CampaignPage(contributor_page)
    campaign_page.goto(profile_id)

    assert campaign_page.has_access_denied_alert(), (
        "Contributor must see the access-denied alert when accessing an unshared profile; "
        "the 'New Campaign' page should display "
        "'Profile not found or you don't have access to this profile.'"
    )


# ---------------------------------------------------------------------------
# Public order routes vs. protected routes (spec 10.5 item 12)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.parametrize(
    "path",
    [
        "/home",
        "/catalogs",
        "/payment-methods",
        # The public-order settings page added by this feature is a protected
        # route: the share token authorizes the buyer page, never this one.
        # The '#' is percent-encoded so it stays a path character instead of
        # starting a URL fragment.
        "/scouts/PROFILE%23boundary-probe/public-orders",
    ],
)
def test_protected_routes_still_redirect(page: Page, path: str) -> None:
    """Every protected route still redirects an anonymous visitor to ``/login``.

    Args:
        page: Unauthenticated Playwright page.
        path: Protected path to navigate to directly.
    """
    page.goto(f"{_base_url()}{path}")
    page.wait_for_url("**/login**", timeout=10_000)
    assert "/login" in page.url, f"Unauthenticated access to {path} must redirect to /login; current URL: {page.url}"


@pytest.mark.smoke
def test_anonymous_public_order_route_stays_accessible(page: Page, public_orders_setup: dict[str, str]) -> None:
    """``/o/<profileId>/<token>`` stays reachable with no session at all.

    The token in the path is the whole authorization, so this route must not
    redirect, must not require a session, and must render the offer.
    """
    offer = PublicOrderPage(page)
    offer.goto_share_url(public_orders_setup["share_url"])

    assert "/login" not in page.url, f"The public order route must not redirect; current URL: {page.url}"
    assert not offer.is_unavailable(), f"Valid share URL must render the offer at {page.url}"
    assert offer.seller_name() == public_orders_setup["seller_name"], (
        f"Anonymous offer must show the seller name; got {offer.seller_name()!r}"
    )


# ---------------------------------------------------------------------------
# API-key reachability (spec 10.5 item 12, scripted half)
# ---------------------------------------------------------------------------


def _graphql_with_api_key(query: str, endpoint: str, api_key: str) -> dict[str, object]:
    """POST one GraphQL query with ``x-api-key`` and return the decoded body.

    Args:
        query: GraphQL query text.
        endpoint: AppSync GraphQL endpoint URL.
        api_key: The stack's API_KEY-mode key.

    Returns:
        Decoded JSON response body.
    """
    request = urllib.request.Request(
        endpoint,
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode("utf-8"))


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("query", "field"),
    [
        ('{ getProfile(profileId: "PROFILE#boundary-probe") { sellerName } }', "getProfile"),
        ("{ listMyProfiles(limit: 1) { profiles { profileId } } }", "listMyProfiles"),
    ],
)
def test_public_api_key_cannot_reach_cognito_only_fields(query: str, field: str) -> None:
    """The public API key must not reach the profile fields the app reads with a session.

    These fields carry no auth directive, which in AppSync multi-auth means they
    are reachable only through the DEFAULT (Cognito) mode — that exclusivity is
    what keeps the public key out of every non-public field. The scripted
    counterpart of this check for ``getMyAccount`` lives in
    ``tests/integration/resolvers/publicAuthModes.integration.test.ts``.
    """
    endpoint = os.environ.get("TEST_APPSYNC_ENDPOINT", "")
    api_key = os.environ.get("TEST_APPSYNC_API_KEY", "")
    if not endpoint or not api_key:
        pytest.skip(
            "TEST_APPSYNC_ENDPOINT / TEST_APPSYNC_API_KEY are only exported by the ephemeral stack "
            "(scripts/ephemeral-env.sh); the dev deploy smoke run does not carry them"
        )

    body = _graphql_with_api_key(query, endpoint, api_key)

    errors = body.get("errors") or []
    assert errors, f"An API-key caller must not reach {field}"
    assert any("Unauthorized" in str(error.get("errorType", "")) for error in errors if isinstance(error, dict)), (
        f"{field} must be refused at the auth layer; got: {errors}"
    )
    data = body.get("data") or {}
    assert data.get(field) is None, f"{field} must return no value to an API-key caller; got: {data.get(field)!r}"
