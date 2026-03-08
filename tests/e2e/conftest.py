"""pytest configuration and fixtures for e2e smoke tests.

Test users are pre-created in the dev Cognito User Pool via
scripts/create-test-users.sh. Credentials are loaded from the .env file at the
repository root.

Cleanup policy
--------------
After the full test suite completes, all DynamoDB records created by test users
are deleted by the TypeScript integration cleanup invoked by ``global_cleanup``.
Cognito users and Account records are
intentionally preserved so the same accounts can be reused across multiple runs.

Fixture hierarchy
-----------------
pytest-playwright already provides:
  page            (function scope) – fresh BrowserContext + Page per test
  browser         (session scope)  – single browser process for the session
  playwright      (session scope)  – Playwright API entry point

This conftest adds:
  owner_page           (function scope) – authenticated Page for the owner role
  contributor_page     (function scope) – authenticated Page for the contributor role
  readonly_page        (function scope) – authenticated Page for the read-only role
  ensure_owner_profile (session scope)  – guarantee owner has at least one seller profile
    global_cleanup       (session scope, autouse) – post-suite TypeScript cleanup
"""

import os
import re
import subprocess
import urllib.parse
import warnings
from collections.abc import Generator
from pathlib import Path
from typing import TypedDict

import pytest
import boto3
from dotenv import load_dotenv
from playwright.sync_api import Browser, BrowserContext, Page, expect

from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.share_page import SharePage
from tests.e2e.utils.auth import login_as_contributor, login_as_owner, login_as_readonly

# ---------------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------------

# Load .env from repo root (three directories above this conftest.py:
#   /repo/tests/e2e/conftest.py  →  /repo/.env)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(dotenv_path=_REPO_ROOT / ".env")

#: Seller name used when ``ensure_owner_profile`` must create a profile from scratch.
_OWNER_ENSURE_PROFILE_NAME: str = "Test Scout"


def _run_typescript_cleanup() -> None:
    """Run canonical TypeScript cleanup from ``tests/integration``.

    Raises:
        RuntimeError: If the cleanup command fails.
    """
    integration_dir = _REPO_ROOT / "tests" / "integration"
    result = subprocess.run(
        ["npm", "run", "cleanup"],
        cwd=integration_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "TypeScript cleanup failed with exit code "
            f"{result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def _cleanup_unconfirmed_smoke_users(user_pool_id: str) -> None:
    """Delete UNCONFIRMED Cognito users whose email starts with ``smoke+``."""
    client = boto3.client("cognito-idp")
    paginator = client.get_paginator("list_users")
    for page in paginator.paginate(
        UserPoolId=user_pool_id,
        Filter='email ^= "smoke+"',
    ):
        for user in page["Users"]:
            if user["UserStatus"] == "UNCONFIRMED":
                client.admin_delete_user(
                    UserPoolId=user_pool_id,
                    Username=user["Username"],
                )


# ---------------------------------------------------------------------------
# Test-user registry
# ---------------------------------------------------------------------------


class UserCredentials(TypedDict):
    email: str | None
    password: str | None


TEST_USERS_BY_ROLE: dict[str, UserCredentials] = {
    "owner": {
        "email": os.getenv("TEST_OWNER_EMAIL"),
        "password": os.getenv("TEST_OWNER_PASSWORD"),
    },
    "contributor": {
        "email": os.getenv("TEST_CONTRIBUTOR_EMAIL"),
        "password": os.getenv("TEST_CONTRIBUTOR_PASSWORD"),
    },
    "readonly": {
        "email": os.getenv("TEST_READONLY_EMAIL"),
        "password": os.getenv("TEST_READONLY_PASSWORD"),
    },
}


# ---------------------------------------------------------------------------
# Authenticated page fixtures
# Each fixture depends on pytest-playwright's function-scoped ``page``
# fixture, which provides a clean BrowserContext per test (cleared cookies,
# storage, etc.) — no explicit logout is needed between tests.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ensure_owner_profile(browser: Browser) -> Generator[str, None, None]:
    """Ensure the owner test user has at least one seller profile in the dev environment.

    If the owner's ``/scouts`` dashboard shows no profile cards after login,
    this fixture clicks *Create Scout*, fills the *Scout Name* field with
    :data:`_OWNER_ENSURE_PROFILE_NAME`, and submits the dialog.  This prevents
    every campaign/order/sharing test from failing on a freshly seeded dev
    environment where no profiles have been created yet.

    Scope
    -----
    ``session`` — the check and optional creation run only once per pytest
    session.  The created profile persists in DynamoDB and is reused on
    subsequent runs until ``global_cleanup`` (or manual deletion) removes it.

    autouse
    -------
    ``False`` — tests opt in by declaring ``ensure_owner_profile`` as a
    parameter.  Only tests that actually need a profile need this fixture.

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
            page.locator("h3").first.wait_for(state="visible", timeout=5_000)
        except Exception:  # noqa: BLE001 – no profiles yet; handled below
            pass

        names = dashboard.get_profile_names()
        if not names:
            # No profiles — create one via the UI.
            dashboard._create_scout_button().click()
            dialog = page.get_by_role("dialog")
            page.get_by_label("Scout Name").fill(_OWNER_ENSURE_PROFILE_NAME)
            page.get_by_role("button", name="Create Scout").click()
            expect(dialog).to_be_hidden(timeout=15_000)
            dashboard.wait_for_loading()
            # Wait for the new profile card to appear.
            dashboard.wait_for_profiles_loaded()
            names = dashboard.get_profile_names()
            assert names, "Profile creation failed — no profile cards visible after Create Scout"

        yield names[0]
    finally:
        context.close()


@pytest.fixture(scope="session")
def ensure_readonly_share(browser: Browser) -> Generator[None, None, None]:
    """Ensure the readonly user has a READ share to at least one owner profile.

    If the readonly user already has a share (detected via the share table on
    the owner's profile management page), the fixture is a no-op.  Otherwise
    it:

    1. Logs in as the owner, navigates to the first profile's ``/manage`` page.
    2. Generates a READ invite code.
    3. Logs in as the readonly user and accepts that invite.

    On teardown the share is revoked (if it still exists) so the environment
    is clean for the next run.

    autouse
    -------
    ``False`` — opt in by declaring ``ensure_readonly_share`` as a parameter.

    Yields:
        ``None``
    """
    readonly_email: str = os.getenv("TEST_READONLY_EMAIL", "")

    owner_context: BrowserContext = browser.new_context(ignore_https_errors=True)
    readonly_context: BrowserContext = browser.new_context(ignore_https_errors=True)
    owner_page_: Page = owner_context.new_page()
    readonly_page_: Page = readonly_context.new_page()

    profile_id_for_teardown: str = ""

    try:
        login_as_owner(owner_page_)
        dashboard = DashboardPage(owner_page_)
        dashboard.goto()
        dashboard.wait_for_loading()
        dashboard.wait_for_profiles_loaded()
        profiles = dashboard.get_profile_names()
        assert profiles, "Owner must have at least one profile before setting up readonly share"

        dashboard.click_profile(profiles[0])
        match = re.search(r"/scouts/([^/]+)/campaigns", owner_page_.url)
        assert match, f"Expected /scouts/{{id}}/campaigns URL after profile click; got: {owner_page_.url}"
        profile_id = urllib.parse.unquote(match.group(1))
        profile_id_for_teardown = profile_id

        share_page = SharePage(owner_page_)
        share_page.goto(profile_id)

        if not share_page.has_shared_access(readonly_email):
            share_page.create_invite("READ")
            invite_code = share_page.get_invite_link()
            assert invite_code, "Failed to generate READ invite code for readonly user"

            login_as_readonly(readonly_page_)
            readonly_share_page = SharePage(readonly_page_)
            readonly_share_page.accept_invite(invite_code)

        yield

    finally:
        if profile_id_for_teardown:
            try:
                share_page2 = SharePage(owner_page_)
                share_page2.goto(profile_id_for_teardown)
                if share_page2.has_shared_access(readonly_email):
                    share_page2.revoke_access(readonly_email)
            except Exception:  # noqa: BLE001
                pass
        owner_context.close()
        readonly_context.close()


@pytest.fixture(scope="function")
def owner_page(page: Page) -> Generator[Page, None, None]:
    """Yield a browser Page already logged in as the owner test user."""
    login_as_owner(page)
    yield page


@pytest.fixture(scope="function")
def contributor_page(page: Page) -> Generator[Page, None, None]:
    """Yield a browser Page already logged in as the contributor test user."""
    login_as_contributor(page)
    yield page


@pytest.fixture(scope="function")
def readonly_page(page: Page) -> Generator[Page, None, None]:
    """Yield a browser Page already logged in as the read-only test user."""
    login_as_readonly(page)
    yield page


# ---------------------------------------------------------------------------
# Global post-suite cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def global_setup() -> Generator[None, None, None]:
    """Session-scoped autouse fixture that runs TypeScript cleanup BEFORE tests.

    This ensures each run starts from a clean state even if the previous
    run's post-suite cleanup failed (e.g., due to expired AWS credentials).
    """
    try:
        _run_typescript_cleanup()
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"E2E pre-suite TypeScript cleanup skipped — AWS credentials may be unavailable: {exc}",
            stacklevel=2,
        )

    user_pool_id = os.getenv("TEST_USER_POOL_ID")
    if user_pool_id:
        try:
            _cleanup_unconfirmed_smoke_users(user_pool_id)
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"E2E pre-suite signup cleanup skipped — AWS credentials may be unavailable: {exc}",
                stacklevel=2,
            )

    yield  # all tests run after this point


@pytest.fixture(scope="session", autouse=True)
def global_cleanup() -> Generator[None, None, None]:
    """Session-scoped autouse fixture that runs TypeScript cleanup after tests.

    This reuses the canonical integration cleanup implementation so E2E and
    integration suites share the same DynamoDB cleanup source of truth.
    """
    yield  # ← all tests run here

    try:
        _run_typescript_cleanup()
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"E2E TypeScript cleanup skipped — AWS credentials may be unavailable: {exc}",
            stacklevel=2,
        )

    user_pool_id = os.getenv("TEST_USER_POOL_ID")
    if user_pool_id:
        try:
            _cleanup_unconfirmed_smoke_users(user_pool_id)
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                f"E2E signup cleanup skipped — AWS credentials may be unavailable: {exc}",
                stacklevel=2,
            )
