"""Smoke test for the password change flow.

This test changes the owner user's password, verifies that the new password
works by logging in with it, then changes the password back to the original
value so subsequent tests and runs are unaffected.
"""

import os

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from tests.e2e.pages.user_settings_page import UserSettingsPage
from tests.e2e.utils.auth import login


@pytest.mark.smoke
def test_password_change_flow(owner_page: Page, browser: Browser) -> None:
    """Change the owner password, authenticate with the new password, then revert.

    The original password is read from the environment so it can be restored
    after the test.  This keeps the owner account usable for the rest of the
    suite and for future runs.
    """
    email = os.environ["TEST_OWNER_EMAIL"]
    original_password = os.environ["TEST_OWNER_PASSWORD"]
    new_password = f"{original_password}New1!"

    # Change password
    settings = UserSettingsPage(owner_page)
    settings.goto()
    settings.change_password(original_password, new_password)
    assert settings.password_change_succeeded(), (
        "Password change must show a success alert"
    )

    # Verify login with the new password works in a fresh browser context
    new_context: BrowserContext = browser.new_context(ignore_https_errors=True)
    verify_page: Page = new_context.new_page()
    try:
        login(verify_page, email, new_password)
        assert "/home" in verify_page.url, (
            f"Expected redirect to /home with new password; got: {verify_page.url}"
        )

        # Change password back to the original value
        settings = UserSettingsPage(verify_page)
        settings.goto()
        settings.change_password(new_password, original_password)
        assert settings.password_change_succeeded(), (
            "Password revert must show a success alert"
        )
    finally:
        new_context.close()
