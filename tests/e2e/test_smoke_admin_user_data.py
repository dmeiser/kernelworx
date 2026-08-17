"""Smoke tests for the admin user-data drill-down page.

Exercises issue #83: an admin searches for a user on the Users tab, clicks the
row to navigate to ``/admin/user-data/{accountId}``, and verifies every tab
renders its expected heading and either data tables or empty-state alerts.
"""

import os

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.admin_page import AdminPage
from tests.e2e.pages.user_data_page import UserDataPage


@pytest.mark.smoke
def test_admin_user_data_tabs(owner_page: Page) -> None:
    """Search for the contributor user and inspect every user-data tab."""
    contributor_email = os.environ["TEST_CONTRIBUTOR_EMAIL"]

    admin = AdminPage(owner_page)
    admin.goto()
    admin.switch_to_users()
    admin.search_user(contributor_email)

    contributor_cell = owner_page.get_by_role("cell", name=contributor_email).first
    expect(contributor_cell).to_be_visible(timeout=10_000)
    contributor_cell.click()
    owner_page.wait_for_url("**/admin/user-data/**", timeout=10_000)

    user_data = UserDataPage(owner_page)
    user_data.wait_for_loading()
    expect(owner_page.get_by_text("User Data Management").first).to_be_visible(timeout=15_000)
    assert "/admin/user-data/" in owner_page.url, (
        f"Expected /admin/user-data/ in URL; got: {owner_page.url}"
    )

    # Profiles tab.
    expect(user_data._tabpanel_heading("Seller Profiles").first).to_be_visible(timeout=10_000)
    expect(
        owner_page.get_by_text("No profiles found for this user.").first
        .or_(owner_page.locator('[role="tabpanel"]:not([hidden]) table tbody tr').first)
    ).to_be_visible(timeout=10_000)

    # Catalogs tab.
    user_data.switch_to_catalogs()
    expect(user_data._tabpanel_heading("Product Catalogs").first).to_be_visible(timeout=10_000)
    expect(
        owner_page.get_by_text("No catalogs found for this user.").first
        .or_(owner_page.locator('[role="tabpanel"]:not([hidden]) table tbody tr').first)
    ).to_be_visible(timeout=10_000)

    # Campaigns tab.
    user_data.switch_to_campaigns()
    expect(user_data._tabpanel_heading("Profile Campaigns").first).to_be_visible(timeout=10_000)
    expect(
        owner_page.get_by_text("No profiles to manage campaigns for.").first
        .or_(owner_page.get_by_text("No campaigns found for this profile.").first)
        .or_(owner_page.locator('[role="tabpanel"]:not([hidden]) table tbody tr').first)
        .or_(owner_page.locator('[role="tabpanel"]:not([hidden]) button').first)
    ).to_be_visible(timeout=10_000)

    # Shared Campaigns tab.
    user_data.switch_to_shared_campaigns()
    expect(user_data._tabpanel_heading("Shared Campaigns Created by User").first).to_be_visible(
        timeout=10_000
    )
    expect(
        owner_page.get_by_text("No shared campaigns found for this user.").first
        .or_(owner_page.locator('[role="tabpanel"]:not([hidden]) table tbody tr').first)
    ).to_be_visible(timeout=10_000)

    # Shares tab.
    user_data.switch_to_shares()
    expect(user_data._tabpanel_heading("Profile Shares").first).to_be_visible(timeout=10_000)
    expect(
        owner_page.get_by_text("No profiles to manage shares for.").first
        .or_(owner_page.get_by_text("No shares found for this profile.").first)
        .or_(owner_page.locator('[role="tabpanel"]:not([hidden]) table tbody tr').first)
        .or_(owner_page.locator('[role="tabpanel"]:not([hidden]) button').first)
    ).to_be_visible(timeout=10_000)
