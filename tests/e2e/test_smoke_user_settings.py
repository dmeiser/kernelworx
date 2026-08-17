"""Smoke tests for the /account/settings page.

These tests exercise the happy-path account-information edit flow on the User
Settings page.  Password changes, MFA, passkeys, and account deletion are out
of scope.
"""

import time

import pytest
from playwright.sync_api import Page

from tests.e2e.pages.user_settings_page import UserSettingsPage

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_edit_account_info(owner_page: Page) -> None:
    """Edit the owner's profile fields and verify the changes persist.

    Navigates to ``/account/settings`` as the authenticated owner, updates the
    *First Name* and *City* fields with unique timestamped values, saves, and
    asserts the updated values are reflected in the account details.

    Args:
        owner_page: Function-scoped Playwright page authenticated as owner.
    """
    settings = UserSettingsPage(owner_page)
    settings.goto()

    timestamp = int(time.time())
    unique_given_name = f"Smoke {timestamp}"
    unique_city = f"Smoke City {timestamp}"

    settings.edit_given_name_and_city(unique_given_name, unique_city)

    assert settings.get_given_name() == unique_given_name, (
        f"Expected given name '{unique_given_name}' after edit; got '{settings.get_given_name()}'"
    )
    assert settings.get_city() == unique_city, (
        f"Expected city '{unique_city}' after edit; got '{settings.get_city()}'"
    )
