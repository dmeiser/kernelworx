"""Smoke tests for authorization boundaries.

The HTMX redesign has NO client-side route protection (no ``ProtectedRoute``
equivalent) and the local test server treats every request as the SAME fake
authenticated user (a fixed Cognito ``sub`` claim).  There is therefore no
real unauthenticated-redirect or cross-user access boundary to exercise
locally.  The original scenarios are preserved here as explicit skips with
clear reasons so the suite structure stays intact and the scenarios can be
re-enabled against a deployed environment.
"""

import pytest
from playwright.sync_api import Page

from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.dashboard_page import DashboardPage

# ---------------------------------------------------------------------------
# Module-scoped state fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _auth_boundary_state() -> dict[str, str]:
    """Mutable dict shared across all tests in this module."""
    return {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_unauthenticated_redirect_to_login(page: Page) -> None:
    """Unauthenticated access to a protected route must redirect to /login.

    SKIPPED locally: the HTMX app has no client-side route protection and the
    local server serves ``/scouts`` as authenticated (fixed fake ``sub``) to
    every request, so no redirect occurs.
    """
    pytest.skip(
        "No client-side route protection / unauthenticated redirect in the HTMX "
        "redesign; the local server treats every request as authenticated."
    )


@pytest.mark.smoke
def test_owner_profile_id_for_boundary(
    owner_page: Page, _auth_boundary_state: dict[str, str], ensure_owner_profile: str
) -> None:
    """Capture the owner's first profile ID for use by the contributor boundary test.

    This setup test still runs locally (it just navigates the dashboard and
    extracts a profile ID), even though the downstream boundary test is
    skipped.
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

    # Navigate to the campaigns page and capture the profile ID from the URL.
    dashboard.click_profile(profiles[0])
    import re
    import urllib.parse

    match = re.search(r"/scouts/([^/]+)/campaigns", owner_page.url)
    if not match:
        pytest.skip(f"Could not extract profile_id from campaigns URL: {owner_page.url}")
    _auth_boundary_state["profile_id"] = urllib.parse.unquote(match.group(1))


@pytest.mark.smoke
def test_contributor_cannot_access_unshared_profile(
    contributor_page: Page, _auth_boundary_state: dict[str, str]
) -> None:
    """Contributor sees an access-denied alert for an owner profile with no share.

    SKIPPED locally: the local server uses a single fixed fake ``sub`` for all
    requests, so the “contributor” is indistinguishable from the “owner” and
    sees the same campaigns.  There is no real second Cognito user to test a
    cross-account access boundary.
    """
    pytest.skip(
        "No real second Cognito user locally — the local server uses one fixed "
        "fake sub for every request, so cross-user access boundaries cannot be "
        "exercised."
    )
