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
    assert catalogs.has_catalog(catalog_name), f"Created catalog '{catalog_name}' must appear in the list"


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
    assert catalogs.has_catalog(new_name), f"Updated catalog name '{new_name}' must appear in the list"
    assert not catalogs.has_catalog(original_name), f"Original catalog name '{original_name}' must no longer appear"


@pytest.mark.smoke
def test_delete_catalog(owner_page: Page) -> None:
    """Delete a catalog and verify it disappears from the list."""
    catalogs = CatalogsPage(owner_page)
    catalogs.goto()
    catalogs.switch_to_my_catalogs()

    catalog_name = f"E2E Delete Catalog {int(time.time())}"
    catalogs.create_catalog(catalog_name)
    assert catalogs.has_catalog(catalog_name), f"Catalog '{catalog_name}' must exist before deletion"

    catalogs.delete_catalog(catalog_name)
    assert not catalogs.has_catalog(catalog_name), f"Deleted catalog '{catalog_name}' must not appear in the list"


@pytest.mark.smoke
def test_managed_catalogs_tab_loads(owner_page: Page, ensure_managed_catalog) -> None:
    """The Managed Catalogs tab loads without errors."""
    catalogs = CatalogsPage(owner_page)
    catalogs.goto()
    catalogs.switch_to_managed_catalogs()
    header = owner_page.get_by_role("columnheader", name="Catalog Name")
    assert header.first.is_visible(), "Managed Catalogs tab must render the table header"


@pytest.mark.smoke
def test_create_catalog_with_multiple_products(owner_page: Page) -> None:
    """Create a catalog with multiple products including descriptions."""
    catalogs = CatalogsPage(owner_page)
    catalogs.goto()
    catalogs.switch_to_my_catalogs()

    catalog_name = f"E2E Multi Product Catalog {int(time.time())}"
    products = [
        {"productName": "Caramel Popcorn", "price": 25.0, "description": "Sweet and crunchy"},
        {"productName": "Cheese Popcorn", "price": 22.0, "description": "Savory cheddar"},
    ]
    catalogs.create_catalog(catalog_name, products)
    assert catalogs.has_catalog(catalog_name), f"Created catalog '{catalog_name}' must appear in the list"

    catalogs.view_catalog(catalog_name)
    names = catalogs.get_preview_product_names()
    assert "Caramel Popcorn" in names, f"Expected Caramel Popcorn in products; got: {names}"
    assert "Cheese Popcorn" in names, f"Expected Cheese Popcorn in products; got: {names}"
    assert catalogs.preview_has_product("Caramel Popcorn", 25.0)
    assert catalogs.preview_has_product("Cheese Popcorn", 22.0)


@pytest.mark.smoke
def test_edit_catalog_product(owner_page: Page) -> None:
    """Edit a product's name, price, and description in a catalog."""
    catalogs = CatalogsPage(owner_page)
    catalogs.goto()
    catalogs.switch_to_my_catalogs()

    catalog_name = f"E2E Edit Product Catalog {int(time.time())}"
    catalogs.create_catalog(
        catalog_name,
        [
            {"productName": "Original Product", "price": 10.0, "description": "Original description"},
        ],
    )

    catalogs.edit_catalog_product(
        catalog_name,
        index=0,
        name="Updated Product",
        price=15.0,
        description="Updated description",
    )
    catalogs.view_catalog(catalog_name)
    assert catalogs.preview_has_product("Updated Product", 15.0), "Updated product must appear in preview"
    assert not catalogs.preview_has_product("Original Product", 10.0), "Original product must no longer appear"


@pytest.mark.smoke
def test_remove_catalog_product(owner_page: Page) -> None:
    """Remove a product from a catalog via the edit dialog."""
    catalogs = CatalogsPage(owner_page)
    catalogs.goto()
    catalogs.switch_to_my_catalogs()

    catalog_name = f"E2E Remove Product Catalog {int(time.time())}"
    catalogs.create_catalog(
        catalog_name,
        [
            {"productName": "Keep Product", "price": 10.0},
            {"productName": "Remove Product", "price": 20.0},
        ],
    )

    catalogs.remove_catalog_product(catalog_name, index=1)
    catalogs.view_catalog(catalog_name)
    names = catalogs.get_preview_product_names()
    assert "Keep Product" in names, f"Keep Product must remain; got: {names}"
    assert "Remove Product" not in names, f"Remove Product must be removed; got: {names}"
    assert catalogs.get_preview_product_count() == 1, (
        f"Expected product count 1; got {catalogs.get_preview_product_count()}"
    )


@pytest.mark.smoke
def test_catalog_preview_page(owner_page: Page) -> None:
    """Verify the catalog preview page URL, name, count, table, and action buttons."""
    catalogs = CatalogsPage(owner_page)
    catalogs.goto()
    catalogs.switch_to_my_catalogs()

    catalog_name = f"E2E Preview Catalog {int(time.time())}"
    catalogs.create_catalog(
        catalog_name,
        [
            {"productName": "Preview Product", "price": 30.0, "description": "Preview description"},
        ],
    )

    catalogs.view_catalog(catalog_name)
    assert "/catalogs/" in owner_page.url and "/preview" in owner_page.url, (
        f"Expected preview URL; got: {owner_page.url}"
    )
    assert catalogs.get_preview_catalog_name() == catalog_name, (
        f"Expected preview name '{catalog_name}'; got '{catalogs.get_preview_catalog_name()}'"
    )
    assert catalogs.get_preview_product_count() == 1, (
        f"Expected product count 1; got {catalogs.get_preview_product_count()}"
    )
    names = catalogs.get_preview_product_names()
    assert "Preview Product" in names, f"Expected Preview Product in table; got: {names}"
    assert catalogs.preview_has_product("Preview Product", 30.0)
    assert catalogs.get_preview_create_campaign_button_visible(), "Create Campaign button must be visible"
    assert catalogs.get_preview_create_shared_campaign_button_visible(), "Create Shared Campaign button must be visible"
