"""Smoke tests for the admin console happy paths.

The dev environment configures the owner test user as an admin (member of the
ADMIN Cognito group), so the owner fixture can access ``/admin``.
"""

import os
import time

import pytest
from playwright.sync_api import Page

from tests.e2e.pages.admin_page import AdminPage


@pytest.mark.smoke
def test_admin_page_loads(owner_page: Page) -> None:
    """The admin console loads for the owner admin user."""
    admin = AdminPage(owner_page)
    admin.goto()
    assert admin.is_visible(), "Admin Console heading must be visible for admin user"


@pytest.mark.smoke
def test_admin_users_tab_search(owner_page: Page) -> None:
    """The Users tab can search for a known test user."""
    admin = AdminPage(owner_page)
    admin.goto()
    admin.switch_to_users()

    contributor_email = os.environ["TEST_CONTRIBUTOR_EMAIL"]
    admin.search_user(contributor_email)
    assert owner_page.get_by_role("cell", name=contributor_email).first.is_visible(), (
        f"Contributor user '{contributor_email}' must appear in admin search results"
    )


@pytest.mark.smoke
def test_admin_catalogs_tab_loads(owner_page: Page) -> None:
    """The Catalogs tab loads and shows the new-catalog action."""
    admin = AdminPage(owner_page)
    admin.goto()
    admin.switch_to_catalogs()
    assert admin._new_catalog_button().is_visible(), "New Catalog button must be visible on the Catalogs tab"


@pytest.mark.smoke
def test_admin_create_and_delete_managed_catalog(owner_page: Page) -> None:
    """Create a managed catalog from the admin console and then delete it."""
    admin = AdminPage(owner_page)
    admin.goto()
    admin.switch_to_catalogs()

    catalog_name = f"E2E Admin Catalog {int(time.time())}"
    admin.create_managed_catalog(catalog_name)
    assert admin.has_catalog(catalog_name), f"Created managed catalog '{catalog_name}' must be visible"

    admin.delete_managed_catalog(catalog_name)
    assert not admin.has_catalog(catalog_name), f"Deleted managed catalog '{catalog_name}' must no longer be visible"


@pytest.mark.smoke
def test_admin_system_info_tab_loads(owner_page: Page) -> None:
    """The System Info tab renders application metadata."""
    admin = AdminPage(owner_page)
    admin.goto()
    admin.switch_to_system_info()
    assert owner_page.get_by_text("Application Version").first.is_visible(), (
        "System Info tab must show the Application Version row"
    )
