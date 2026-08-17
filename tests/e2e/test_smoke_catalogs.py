"""Smoke tests for the catalogs page.

Covers the happy paths for listing, creating, editing, and deleting private
catalogs on the ``/catalogs`` page.
"""

import time

import pytest
from playwright.sync_api import Page

from tests.e2e.pages.catalogs_page import CatalogsPage


@pytest.mark.smoke
def test_catalogs_page_loads(owner_page: Page) -> None:
    """The catalogs page loads and shows the expected tabs."""
    catalogs = CatalogsPage(owner_page)
    catalogs.goto()
    assert catalogs.is_visible(), "Catalogs page header must be visible"


@pytest.mark.smoke
def test_create_catalog(owner_page: Page) -> None:
    """Create a private catalog and verify it appears in the My Catalogs list."""
    catalogs = CatalogsPage(owner_page)
    catalogs.goto()
    catalogs.switch_to_my_catalogs()

    catalog_name = f"E2E Create Catalog {int(time.time())}"
    catalogs.create_catalog(catalog_name)
    assert catalogs.has_catalog(catalog_name), (
        f"Created catalog '{catalog_name}' must appear in the list"
    )


@pytest.mark.smoke
def test_edit_catalog(owner_page: Page) -> None:
    """Edit a catalog name and verify the new name appears in the list."""
    catalogs = CatalogsPage(owner_page)
    catalogs.goto()
    catalogs.switch_to_my_catalogs()

    original_name = f"E2E Edit Catalog {int(time.time())}"
    catalogs.create_catalog(original_name)

    new_name = f"{original_name} Updated"
    catalogs.edit_catalog_name(original_name, new_name)
    assert catalogs.has_catalog(new_name), (
        f"Updated catalog name '{new_name}' must appear in the list"
    )
    assert not catalogs.has_catalog(original_name), (
        f"Original catalog name '{original_name}' must no longer appear"
    )


@pytest.mark.smoke
def test_delete_catalog(owner_page: Page) -> None:
    """Delete a catalog and verify it disappears from the list."""
    catalogs = CatalogsPage(owner_page)
    catalogs.goto()
    catalogs.switch_to_my_catalogs()

    catalog_name = f"E2E Delete Catalog {int(time.time())}"
    catalogs.create_catalog(catalog_name)
    assert catalogs.has_catalog(catalog_name), (
        f"Catalog '{catalog_name}' must exist before deletion"
    )

    catalogs.delete_catalog(catalog_name)
    assert not catalogs.has_catalog(catalog_name), (
        f"Deleted catalog '{catalog_name}' must not appear in the list"
    )


@pytest.mark.smoke
def test_managed_catalogs_tab_loads(owner_page: Page) -> None:
    """The Managed Catalogs tab loads without errors."""
    catalogs = CatalogsPage(owner_page)
    catalogs.goto()
    catalogs.switch_to_managed_catalogs()
    header = owner_page.get_by_role("columnheader", name="Catalog Name")
    assert header.first.is_visible(), "Managed Catalogs tab must render the table header"
