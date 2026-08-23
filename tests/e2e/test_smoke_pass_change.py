"""Smoke test for the password change flow.

This test changes the owner user's password through the UI, verifies that the
new password works by logging in with it, then changes the password back to the
original value.  A Cognito admin reset in the ``finally`` block guarantees the
owner account is restored even if the UI flow fails mid-way.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from tests.e2e.pages.user_settings_page import UserSettingsPage
from tests.e2e.utils.auth import login


@pytest.mark.smoke
@pytest.mark.skip(reason="Disabled pending an email-free password-change test strategy; see #117")
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

        The password is supplied through ``--cli-input-json`` read from a
        temporary file so it never appears in the process argument list,
        preventing leaks if pytest/CalledProcessError echoes the command.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as input_file:
            json.dump(
                {
                    "UserPoolId": user_pool_id,
                    "Username": email,
                    "Password": password,
                    "Permanent": True,
                },
                input_file,
            )
            input_path = input_file.name

        try:
            subprocess.run(
                [
                    "aws",
                    "cognito-idp",
                    "admin-set-user-password",
                    "--cli-input-json",
                    f"file://{input_path}",
                    "--region",
                    region,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        finally:
            Path(input_path).unlink(missing_ok=True)

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
            assert "/home" in verify_page.url, f"Expected redirect to /home with new password; got: {verify_page.url}"
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
