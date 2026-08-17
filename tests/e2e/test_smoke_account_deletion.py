"""Placeholder smoke test for the account deletion cascade.

Account deletion permanently removes the user and all associated data.  This
module is gated by ``RUN_ACCOUNT_DELETION`` and does **not** execute the
destructive action; it only verifies that the deletion UI is reachable and can
be canceled.
"""

import os

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.user_settings_page import UserSettingsPage

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_ACCOUNT_DELETION"),
    reason="Destructive account-deletion test; set RUN_ACCOUNT_DELETION=1 to opt in",
)


@pytest.mark.smoke
def test_account_deletion_ui_is_discoverable(owner_page: Page) -> None:
    """Open account settings and verify the *Delete My Account* flow is present.

    If the deletion button is not found, the test skips.  When found, the test
    opens the confirmation dialog and cancels it so no data is actually removed.
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

    # Cancel the destructive action; the full cascade test is not yet implemented.
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden(timeout=10_000)

    pytest.fail(
        "RUN_ACCOUNT_DELETION is enabled but the full account-deletion cascade test is not implemented"
    )
