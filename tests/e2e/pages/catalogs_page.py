"""Catalogs page object — list, create, edit, and delete product catalogs."""

import urllib.parse
import uuid

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class CatalogsPage(BasePage):
    """Page object for ``/catalogs``.

    Covers the *My Catalogs* and *Managed Catalogs* tabs plus the
    :class:`CatalogEditorDialog` used to create or edit catalogs.
    """

    PATH: str = "/catalogs"

    # Tab labels
    _MY_CATALOGS_TAB: str = "My Catalogs"
    _MANAGED_CATALOGS_TAB: str = "Managed Catalogs"

    # Page header
    _NEW_CATALOG_BTN: str = "New Catalog"

    # Dialog
    _DIALOG_TITLE_CREATE: str = "Create Catalog"
    _DIALOG_TITLE_EDIT: str = "Edit Catalog"
    _CATALOG_NAME_LABEL: str = "Catalog Name"
    _ADD_PRODUCT_BTN: str = "Add Product"
    _SAVE_CATALOG_BTN: str = "Save Catalog"

    # Table columns / actions
    _VIEW_BTN: str = "View"
    _CATALOG_NAME_HEADER: str = "Catalog Name"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self) -> None:
        """Navigate to ``/catalogs`` and wait for the page to load."""
        self.navigate(self.PATH)
        self.wait_for_loading()

    def goto_preview(self, catalog_id: str) -> None:
        """Navigate to the catalog preview page for *catalog_id*.

        Args:
            catalog_id: Raw catalog identifier (with or without ``CATALOG#`` prefix).
        """
        catalog_uuid = catalog_id.replace("CATALOG#", "")
        encoded = urllib.parse.quote(catalog_uuid, safe="")
        self.navigate(f"/catalogs/{encoded}/preview")
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Locator factories
    # ------------------------------------------------------------------

    def _new_catalog_button(self) -> Locator:
        """Return locator for the *New Catalog* button."""
        return self.get_by_role_button(self._NEW_CATALOG_BTN)

    def _my_catalogs_tab(self) -> Locator:
        """Return locator for the *My Catalogs* tab."""
        return self.page.get_by_role("tab", name=self._MY_CATALOGS_TAB, exact=True)

    def _managed_catalogs_tab(self) -> Locator:
        """Return locator for the *Managed Catalogs* tab."""
        return self.page.get_by_role("tab", name=self._MANAGED_CATALOGS_TAB, exact=True)

    def _catalog_name_input(self) -> Locator:
        """Return locator for the catalog name field inside the dialog."""
        return self.page.get_by_label(self._CATALOG_NAME_LABEL, exact=True)

    def _save_catalog_button(self) -> Locator:
        """Return locator for the *Save Catalog* dialog button."""
        return self.get_by_role_button(self._SAVE_CATALOG_BTN)

    def _add_product_button(self) -> Locator:
        """Return locator for the *Add Product* button inside the dialog."""
        return self.get_by_role_button(self._ADD_PRODUCT_BTN)

    def _catalog_row(self, name: str) -> Locator:
        """Return a table row locator that contains *name*.

        Args:
            name: Catalog name text to match.
        """
        return self.page.get_by_role("row").filter(has_text=name)

    def _product_name_input(self, index: int = 0) -> Locator:
        """Return locator for the *Product Name* field of product *index*.

        Args:
            index: Zero-based product index in the dialog.
        """
        return self.page.get_by_label("Product Name", exact=True).nth(index)

    def _product_price_input(self, index: int = 0) -> Locator:
        """Return locator for the *Price* field of product *index*.

        Args:
            index: Zero-based product index in the dialog.
        """
        return self.page.get_by_label("Price", exact=True).nth(index)

    def _edit_button_for(self, name: str) -> Locator:
        """Return the edit icon button on the row for *name*.

        Args:
            name: Catalog name to locate the row.
        """
        row = self._catalog_row(name)
        return row.locator('[aria-label^="Edit "]')

    def _delete_button_for(self, name: str) -> Locator:
        """Return the delete icon button on the row for *name*.

        Args:
            name: Catalog name to locate the row.
        """
        row = self._catalog_row(name)
        return row.locator('[aria-label^="Delete "]')

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_visible(self) -> bool:
        """Return ``True`` when the catalogs page header is visible."""
        return bool(self._new_catalog_button().is_visible())

    def has_catalog(self, name: str) -> bool:
        """Return ``True`` when *name* appears in the catalogs table.

        Args:
            name: Catalog name text to search for.
        """
        cell = self.page.get_by_role("cell", name=name)
        return cell.first.is_visible()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def switch_to_my_catalogs(self) -> None:
        """Click the *My Catalogs* tab and wait for the table to load."""
        self._my_catalogs_tab().click()
        self.wait_for_loading()

    def switch_to_managed_catalogs(self) -> None:
        """Click the *Managed Catalogs* tab and wait for the table to load."""
        self._managed_catalogs_tab().click()
        self.wait_for_loading()

    def create_catalog(self, name: str | None = None, products: list[dict[str, object]] | None = None) -> str:
        """Create a new private catalog via the UI.

        Args:
            name: Optional catalog name. A unique name is generated when omitted.
            products: Optional list of product dicts with ``productName`` and ``price`` keys.
                A default single product is created when omitted.

        Returns:
            The catalog name used for creation.
        """
        catalog_name = name or f"E2E Catalog {uuid.uuid4().hex[:8]}"
        self._new_catalog_button().click()
        dialog = self.wait_for_dialog(self._DIALOG_TITLE_CREATE)

        self._catalog_name_input().fill(catalog_name)

        product_list = products or [{"productName": "E2E Popcorn", "price": 25.0}]
        for index, product in enumerate(product_list):
            if index > 0:
                self._add_product_button().click()
            self._product_name_input(index).fill(str(product["productName"]))
            self._product_price_input(index).fill(str(product["price"]))

        self._save_catalog_button().click()
        expect(dialog).to_be_hidden(timeout=15_000)
        self.wait_for_loading()
        return catalog_name

    def edit_catalog_name(self, current_name: str, new_name: str) -> None:
        """Open the edit dialog for *current_name* and rename it to *new_name*.

        Args:
            current_name: Existing catalog name to edit.
            new_name: Replacement catalog name.
        """
        self._edit_button_for(current_name).click()
        dialog = self.wait_for_dialog(self._DIALOG_TITLE_EDIT)

        name_input = self._catalog_name_input()
        name_input.clear()
        name_input.fill(new_name)

        self._save_catalog_button().click()
        expect(dialog).to_be_hidden(timeout=15_000)
        self.wait_for_loading()

    def delete_catalog(self, name: str) -> None:
        """Delete the catalog named *name* and confirm the browser dialog.

        Args:
            name: Catalog name to delete.
        """
        self.page.once("dialog", lambda dlg: dlg.accept())
        self._delete_button_for(name).click()
        self.wait_for_loading()
