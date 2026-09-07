"""Smoke tests for the account-deletion flow.

Account deletion permanently removes the user and all associated data.  This
module is gated by ``RUN_ACCOUNT_DELETION``.
"""

import os
import random
import re
import string
import time

import boto3
import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.user_settings_page import UserSettingsPage
from tests.e2e.utils.auth import login

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_ACCOUNT_DELETION"),
    reason="Destructive account-deletion test; set RUN_ACCOUNT_DELETION=1 to opt in",
)


@pytest.mark.smoke
def test_account_deletion_ui_is_discoverable(owner_page: Page) -> None:
    """Open account settings and verify the *Delete My Account* flow is present.

    Opens the confirmation dialog and cancels it so no data is actually removed.
    """
    settings = UserSettingsPage(owner_page)
    settings.goto()

    delete_button = owner_page.get_by_role("button", name="Delete My Account")
    if not delete_button.is_visible():
        pytest.fail("Account deletion UI not discoverable")

    delete_button.click()
    dialog = owner_page.get_by_role("dialog")
    expect(dialog).to_be_visible(timeout=10_000)
    expect(dialog.get_by_text("Confirm Account Deletion")).to_be_visible()

    # Cancel the destructive action; this test verifies UI reachability and cancel safety.
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden(timeout=10_000)


@pytest.mark.smoke
def test_account_deletion_happy_path(browser: Browser) -> None:
    """End-to-end happy path test for stepped account deletion.

    Creates a disposable Cognito test user, logs in, creates a seller profile,
    navigates to account settings, executes stepped account deletion, and verifies:
    - Profiles are previewed in the confirmation modal
    - Deletion completes sequentially
    - User is signed out and redirected
    - Account is removed from Cognito
    """
    user_pool_id = os.environ.get("TEST_USER_POOL_ID")
    region = os.environ.get("TEST_REGION", "us-east-1")
    if not user_pool_id:
        pytest.skip("TEST_USER_POOL_ID not set; skipping full account deletion cascade")

    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    email = f"smoke+del_{suffix}@example-test.invalid"
    password = f"SmokeT3st!{int(time.time())}"

    cognito = boto3.client("cognito-idp", region_name=region)
    try:
        cognito.admin_create_user(
            UserPoolId=user_pool_id,
            Username=email,
            TemporaryPassword=password,
            MessageAction="SUPPRESS",
            UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}],
        )
        cognito.admin_set_user_password(
            UserPoolId=user_pool_id,
            Username=email,
            Password=password,
            Permanent=True,
        )
    except Exception as exc:
        pytest.skip(f"Could not provision test user in Cognito: {exc}")

    context: BrowserContext = browser.new_context(ignore_https_errors=True)
    page: Page = context.new_page()

    try:
        # 1. Log in as disposable test user
        login(page, email, password)

        # 2. Create a seller profile so stepped profile deletion runs
        dashboard = DashboardPage(page)
        dashboard.goto()
        dashboard.wait_for_loading()
        scout_name = f"DelScout {suffix}"
        dashboard._create_scout_button().click()
        scout_dialog = page.get_by_role("dialog")
        page.get_by_label("Scout Name").fill(scout_name)
        page.get_by_role("button", name="Create Scout").click()
        expect(scout_dialog).to_be_hidden(timeout=15_000)
        dashboard.wait_for_loading()

        # 3. Navigate to user settings
        settings = UserSettingsPage(page)
        settings.goto()

        # 4. Open delete account dialog
        delete_btn = page.get_by_role("button", name="Delete My Account")
        expect(delete_btn).to_be_visible(timeout=10_000)
        delete_btn.click()

        confirm_dialog = page.get_by_role("dialog")
        expect(confirm_dialog).to_be_visible(timeout=10_000)
        expect(confirm_dialog.get_by_text("Confirm Account Deletion")).to_be_visible()

        # 5. Verify profile preview
        expect(confirm_dialog.get_by_text(scout_name)).to_be_visible(timeout=10_000)

        # 6. Type DELETE to confirm
        confirm_input = confirm_dialog.get_by_placeholder("Type DELETE to confirm")
        confirm_input.fill("DELETE")
        confirm_action_btn = confirm_dialog.get_by_role("button", name="Delete Account")
        expect(confirm_action_btn).to_be_enabled()
        confirm_action_btn.click()

        # 7. Verify stepped deletion progresses to completion
        expect(confirm_dialog.get_by_text("Account Deleted")).to_be_visible(timeout=30_000)

        # 8. Verify sign-out and redirect to root or login
        page.wait_for_url(re.compile(r"(https?://[^/]+/?$|/login)"), timeout=15_000)

        # 9. Verify Cognito user was deleted
        with pytest.raises(Exception):
            cognito.admin_get_user(UserPoolId=user_pool_id, Username=email)

    finally:
        context.close()
        try:
            cognito.admin_delete_user(UserPoolId=user_pool_id, Username=email)
        except Exception:
            pass
