"""Smoke test for the password change flow.

This test changes the owner user's password through the UI, verifies that the
new password works by logging in with it, then changes the password back to the
original value.  A Cognito admin reset in the ``finally`` block guarantees the
owner account is restored even if the UI flow fails mid-way.
"""

import os
import subprocess

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from tests.e2e.pages.user_settings_page import UserSettingsPage
from tests.e2e.utils.auth import login


@pytest.mark.smoke
@pytest.mark.skipif(
    not os.environ.get("RUN_PASSWORD_CHANGE"),
    reason="Mutates the shared dev owner account; set RUN_PASSWORD_CHANGE=1 to opt in",
)
def test_password_change_flow(owner_page: Page, browser: Browser) -> None:
    """Change the owner password, authenticate with the new password, then revert.

    The original password is read from the environment so it can be restored
    after the test.  This keeps the owner account usable for the rest of the
    suite and for future runs.
    """
    email = os.environ["TEST_OWNER_EMAIL"]
    original_password = os.environ["TEST_OWNER_PASSWORD"]
    new_password = f"{original_password}New1!"
    user_pool_id = os.environ["TEST_USER_POOL_ID"]
    region = os.environ.get("TEST_REGION", "us-east-1")

    def _reset_password(password: str) -> None:
        """Force-set the owner password via the Cognito admin CLI.

        Uses ``aws cognito-idp admin-set-user-password`` instead of boto3 so
        the test inherits the same credential source as the local AWS CLI.
        """
        subprocess.run(
            [
                "aws",
                "cognito-idp",
                "admin-set-user-password",
                "--user-pool-id",
                user_pool_id,
                "--username",
                email,
                "--password",
                password,
                "--permanent",
                "--region",
                region,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    try:
        # Change password through the UI
        settings = UserSettingsPage(owner_page)
        settings.goto()
        settings.change_password(original_password, new_password)

        # Verify the new password works by logging in with it, then revert.
        new_context: BrowserContext = browser.new_context(ignore_https_errors=True)
        verify_page: Page = new_context.new_page()
        try:
            login(verify_page, email, new_password)
            assert "/home" in verify_page.url, (
                f"Expected redirect to /home with new password; got: {verify_page.url}"
            )
        finally:
            # Always attempt to revert the password through the UI after a
            # successful change, even if the verification login failed.
            try:
                settings = UserSettingsPage(verify_page)
                settings.goto()
                settings.change_password(new_password, original_password)
            except BaseException:
                pass
            new_context.close()

        # Confirm the original password still works
        final_context: BrowserContext = browser.new_context(ignore_https_errors=True)
        final_page: Page = final_context.new_page()
        try:
            login(final_page, email, original_password)
            assert "/home" in final_page.url, (
                f"Expected redirect to /home with original password; got: {final_page.url}"
            )
        finally:
            final_context.close()
    finally:
        # Guarantee the owner account is restored for the rest of the suite.
        _reset_password(original_password)
