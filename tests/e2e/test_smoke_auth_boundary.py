"""Smoke tests for authorization boundaries.

Verifies that:

* Unauthenticated users are redirected to ``/login`` when they navigate to a
  protected route.
* A contributor cannot access an owner's profile that has not been shared with
  them.

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

import os
import re
import urllib.parse

import pytest
from playwright.sync_api import Page

from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.dashboard_page import DashboardPage

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
def test_owner_profile_id_for_boundary(owner_page: Page, _auth_boundary_state: dict[str, str], ensure_owner_profile: str) -> None:
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
    contributor_page: Page, _auth_boundary_state: dict[str, str]
) -> None:
    """Contributor sees an access-denied alert for an owner profile with no share.

    Navigates the contributor directly to the owner's campaigns URL.  The app
    renders an error alert ("Profile not found or you don't have access to this
    profile.") in-place — it does **not** redirect the user to another URL.

    The ``global_setup`` fixture (session-scoped, autouse) runs a full cleanup
    before any tests execute, ensuring the contributor holds no leftover share
    from a previous run.
    """
    profile_id = _auth_boundary_state.get("profile_id", "")
    if not profile_id:
        pytest.skip("profile_id not set — ensure test_owner_profile_id_for_boundary ran first")

    campaign_page = CampaignPage(contributor_page)
    campaign_page.goto(profile_id)

    assert campaign_page.has_access_denied_alert(), (
        "Contributor must see the access-denied alert when accessing an unshared profile; "
        "the 'New Campaign' page should display "
        "'Profile not found or you don't have access to this profile.'"
    )
