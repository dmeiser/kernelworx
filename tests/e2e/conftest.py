"""pytest configuration and fixtures for the local e2e smoke suite.

The original suite targeted a deployed dev environment (real Cognito login via
TEST_OWNER_EMAIL env vars, deployed at E2E_BASE_URL).  This version drives the
LOCAL WSGI test server (``tests/e2e/test_server.py``) running inside a
``moto.mock_aws`` context with ephemeral DynamoDB tables, so the full HTMX app
renders and persists data without any AWS credentials.

Authentication is FAKE: the WSGI app injects a fixed Cognito ``sub`` claim
(``e2e-test-user-sub`` by default) on every request, so every page is treated
as authenticated.  No real Cognito / AppSync / GraphQL is involved.  The
``login_as_owner`` / ``login_as_contributor`` / ``login_as_readonly`` helpers
therefore just navigate to the app — they keep their original names and
signatures so the smoke tests do not need their auth calls changed.

Fixture hierarchy
-----------------
pytest-playwright provides:
    page            (function scope) — fresh BrowserContext + Page per test
    browser         (session scope)  — single browser process for the session

This conftest adds:
    live_http_server  (session scope, autouse) — starts the WSGI server on
        port 8888 inside ``mock_aws()`` with ephemeral DynamoDB tables.
    owner_page        (function scope) — Page navigated to the local app.
    contributor_page  (function scope) — Page navigated to the local app.
    readonly_page    (function scope) — Page navigated to the local app.
    ensure_owner_profile (session scope) — guarantee the owner has one profile.
    ensure_readonly_share (session scope) — kept for API compatibility; the
        share-acceptance flow cannot run locally (no second real Cognito user),
        so this fixture only ensures a profile exists and yields.
"""

from __future__ import annotations

import threading
import urllib.parse
from collections.abc import Generator
from typing import Any, cast
from wsgiref.simple_server import make_server

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws
from playwright.sync_api import Browser, BrowserContext, Page

from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.share_page import SharePage
from tests.e2e.utils.auth import login_as_contributor, login_as_owner, login_as_readonly

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Port the local WSGI test server listens on.
SERVER_PORT: int = 8888

#: Base URL the page objects navigate to.  Also exported via the ``E2E_BASE_URL``
#: environment variable so ``BasePage.navigate`` (which reads ``E2E_BASE_URL``)
#: targets the local server.
BASE_URL: str = f"http://127.0.0.1:{SERVER_PORT}"

#: Seller name used when ``ensure_owner_profile`` must create a profile.
_OWNER_ENSURE_PROFILE_NAME: str = "Test Scout"

#: Fake Cognito ``sub`` claim used by the local server for the owner role.
_OWNER_SUB: str = "e2e-test-user-sub"

# ---------------------------------------------------------------------------
# Mock AWS / DynamoDB table creation
# ---------------------------------------------------------------------------


def create_mock_tables() -> None:
    """Create the ephemeral DynamoDB tables the local handlers query.

    Mirrors ``dev_server._create_mock_tables``.  Must be called inside a
    ``mock_aws()`` context.
    """
    import os

    os.environ.setdefault("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
    os.environ.setdefault("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-v2-ue1-dev")
    os.environ.setdefault("ORDERS_TABLE_NAME", "kernelworx-orders-v2-ue1-dev")
    os.environ.setdefault("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
    os.environ.setdefault("CATALOGS_TABLE_NAME", "kernelworx-catalogs-v2-ue1-dev")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    tables_spec: list[tuple[str, list[tuple[str, str]]]] = [
        ("kernelworx-profiles-v2-ue1-dev", [("PK", "HASH"), ("SK", "RANGE")]),
        ("kernelworx-campaigns-v2-ue1-dev", [("profileId", "HASH"), ("campaignId", "RANGE")]),
        ("kernelworx-orders-v2-ue1-dev", [("campaignId", "HASH"), ("orderId", "RANGE")]),
        ("kernelworx-accounts-ue1-dev", [("accountId", "HASH")]),
        ("kernelworx-catalogs-v2-ue1-dev", [("catalogId", "HASH")]),
    ]
    for tbl_name, keys in tables_spec:
        try:
            dynamodb.create_table(
                TableName=tbl_name,
                KeySchema=[
                    {"AttributeName": k, "KeyType": t}  # type: ignore[typeddict-item]
                    for k, t in keys
                ],
                AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k, _ in keys],
                BillingMode="PAY_PER_REQUEST",
            )
        except ClientError:
            pass


# ---------------------------------------------------------------------------
# Live WSGI server fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def live_http_server() -> Generator[dict[str, Any], None, None]:
    """Start the WSGI test server on ``SERVER_PORT`` inside ``mock_aws()``.

    The server runs for the whole pytest session in a background thread.  The
    ``mock_aws()`` context is held open until the session ends, so the
    ephemeral DynamoDB tables persist across all tests.

    Yields:
        A dict with ``base_url`` (the server's base URL) and ``port``.
    """
    import os

    os.environ["E2E_BASE_URL"] = BASE_URL

    from tests.e2e.test_server import wsgi_app

    with mock_aws():
        create_mock_tables()

        port = SERVER_PORT
        httpd = make_server("127.0.0.1", port, cast(Any, wsgi_app))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        try:
            yield {"base_url": BASE_URL, "port": port}
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)


@pytest.fixture(scope="session", autouse=True)
def _require_live_server(live_http_server: dict[str, Any]) -> None:
    """Autouse fixture ensuring the live WSGI server is started before tests.

    Depends on ``live_http_server`` so the session-scoped server (and its
    ``mock_aws()`` context) is active for every test without each test having
    to declare the fixture explicitly.
    """
    # Nothing to do — the dependency starts (and stops) the server.
    return None


# ---------------------------------------------------------------------------
# Authenticated page fixtures
#
# Each fixture depends on pytest-playwright's function-scoped ``page`` fixture,
# which provides a clean BrowserContext per test (cleared cookies, storage,
# etc.) — no explicit logout is needed between tests.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def owner_page(page: Page) -> Generator[Page, None, None]:
    """Yield a browser Page navigated to the local app as the owner role."""
    login_as_owner(page)
    yield page


@pytest.fixture(scope="function")
def contributor_page(page: Page) -> Generator[Page, None, None]:
    """Yield a browser Page navigated to the local app as the contributor role."""
    login_as_contributor(page)
    yield page


@pytest.fixture(scope="function")
def readonly_page(page: Page) -> Generator[Page, None, None]:
    """Yield a browser Page navigated to the local app as the read-only role."""
    login_as_readonly(page)
    yield page


# ---------------------------------------------------------------------------
# Session-scoped data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ensure_owner_profile(browser: Browser, live_http_server: dict[str, Any]) -> Generator[str, None, None]:
    """Ensure the owner test user has at least one seller profile locally.

    If the owner's ``/scouts`` dashboard shows no profile cards, this fixture
    clicks *Create Scout*, fills the *Scout Name* field with
    :data:`_OWNER_ENSURE_PROFILE_NAME`, and submits the dialog.  This prevents
    every campaign/order/sharing test from failing on a freshly seeded local
    environment (the moto tables are empty at the start of each session).

    Yields:
        The seller name of the first visible profile on the owner dashboard.
    """
    context: BrowserContext = browser.new_context(ignore_https_errors=True)
    page: Page = context.new_page()
    try:
        login_as_owner(page)
        dashboard = DashboardPage(page)
        dashboard.goto()
        dashboard.wait_for_loading()

        # Wait briefly for profile cards to render; an empty dashboard has no <h3>.
        try:
            page.locator("div.card[id^='profile-card-'] h3").first.wait_for(state="visible", timeout=3_000)
        except Exception:  # noqa: BLE001 — no profiles yet; handled below
            pass

        names = dashboard.get_profile_names()
        if not names:
            # No profiles — create one via the UI.
            dashboard._create_scout_button().click()
            page.locator("dialog#create-profile-dialog input#sellerName").wait_for(state="visible", timeout=5_000)
            page.locator("dialog#create-profile-dialog input#sellerName").fill(_OWNER_ENSURE_PROFILE_NAME)
            page.locator("#create-profile-dialog").get_by_role("button", name="Create Scout").click()
            # The HTMX response swaps the new card into #profiles-list.
            page.locator("div.card[id^='profile-card-'] h3").first.wait_for(state="visible", timeout=15_000)
            # Reload the dashboard so the new card is in a clean, sortable DOM.
            dashboard.goto()
            dashboard.wait_for_loading()
            names = dashboard.get_profile_names()
            assert names, "Profile creation failed — no profile cards visible after Create Scout"

        yield names[0]
    finally:
        context.close()


@pytest.fixture(scope="session")
def ensure_readonly_share(browser: Browser, live_http_server: dict[str, Any]) -> Generator[None, None, None]:
    """Ensure the readonly-user setup fixture (kept for API compatibility).

    The original fixture created a READ invite and accepted it as the readonly
    Cognito user.  Locally there is no real second Cognito user and the
    share-acceptance endpoint is not wired, so only the profile-existence part
    runs; the readonly acceptance is intentionally skipped.
    """
    context: BrowserContext = browser.new_context(ignore_https_errors=True)
    page: Page = context.new_page()
    try:
        login_as_owner(page)
        dashboard = DashboardPage(page)
        dashboard.goto()
        dashboard.wait_for_loading()
        # Best-effort: ensure at least one profile exists (do not fail the suite
        # if creation races — downstream tests skip cleanly when no profile).
        try:
            dashboard.wait_for_profiles_loaded()
        except Exception:  # noqa: BLE001
            pass
        yield
    finally:
        context.close()


# ---------------------------------------------------------------------------
# Helpers retained for tests that import them directly
# ---------------------------------------------------------------------------


def _base_url() -> str:
    """Return the local server base URL (mirrors the auth helper)."""
    return BASE_URL


def _extract_profile_id_from_url(url: str) -> str:
    """Extract and URL-decode the profile ID from a ``/scouts/{id}/…`` URL."""
    match = None
    import re

    match = re.search(r"/scouts/([^/]+)/campaigns", url)
    assert match, f"Expected /scouts/{{id}}/campaigns in URL; got: {url}"
    return urllib.parse.unquote(match.group(1))
