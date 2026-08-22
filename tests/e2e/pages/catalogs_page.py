"""Catalogs page object — list, create, edit, and delete product catalogs."""

import re
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
    _PRODUCT_NAME_LABEL: str = "Product Name"
    _DESCRIPTION_LABEL: str = "Description (optional)"
    _PRICE_LABEL: str = "Price"
    _ADD_PRODUCT_BTN: str = "Add Product"
    _SAVE_CATALOG_BTN: str = "Save Catalog"

    # Table columns / actions
    _VIEW_BTN: str = "View"
    _CATALOG_NAME_HEADER: str = "Catalog Name"

    # Preview page
    _PREVIEW_CATALOG_NAME_SEL: str = "h5"
    _CREATE_CAMPAIGN_BTN: str = "Create Campaign"
    _CREATE_SHARED_CAMPAIGN_BTN: str = "Create Shared Campaign"

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
        return self.page.get_by_label(self._CATALOG_NAME_LABEL)

    def _save_catalog_button(self) -> Locator:
        """Return locator for the *Save Catalog* dialog button."""
        return self.get_by_role_button(self._SAVE_CATALOG_BTN)

    def _add_product_button(self) -> Locator:
        """Return locator for the *Add Product* button inside the dialog."""
        return self.get_by_role_button(self._ADD_PRODUCT_BTN)

    def _catalog_row(self, name: str) -> Locator:
        """Return a table row locator whose cell text exactly matches *name*.

        Args:
            name: Catalog name text to match.
        """
        return self.page.get_by_role("row").filter(has=self.page.get_by_role("cell", name=name, exact=True))

    def _product_name_input(self, index: int = 0) -> Locator:
        """Return locator for the *Product Name* field of product *index*.

        Args:
            index: Zero-based product index in the dialog.
        """
        return self.page.get_by_label(self._PRODUCT_NAME_LABEL).nth(index)

    def _product_description_input(self, index: int = 0) -> Locator:
        """Return locator for the *Description (optional)* field of product *index*.

        Args:
            index: Zero-based product index in the dialog.
        """
        return self.page.get_by_label(self._DESCRIPTION_LABEL).nth(index)

    def _product_price_input(self, index: int = 0) -> Locator:
        """Return locator for the *Price* field of product *index*.

        Args:
            index: Zero-based product index in the dialog.
        """
        return self.page.get_by_label(self._PRICE_LABEL).nth(index)

    def _remove_product_button(self, index: int = 0) -> Locator:
        """Return the remove icon button for product *index* in the dialog.

        Args:
            index: Zero-based product index in the dialog.
        """
        return self.page.get_by_role("button", name=re.compile(r"Remove product \d+")).nth(index)

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
        """Return ``True`` when a row with the exact catalog name is visible.

        Args:
            name: Catalog name text to search for.
        """
        return self._catalog_row(name).first.is_visible()

    def has_any_catalogs(self) -> bool:
        """Return ``True`` when the current tab lists at least one catalog.

        The catalogs table renders one ``tbody`` row per catalog; the empty
        state renders no table rows at all. Waits for either the table to
        populate or the empty-state text to appear so the count is not read
        while the query is still in flight.
        """
        table_row = self.page.locator("table tbody tr").first
        empty_state = self.page.get_by_text(
            re.compile(
                r"No catalogs yet\. Create your first catalog!|No managed catalogs available\."
            )
        )
        expect(table_row.or_(empty_state)).to_be_visible(timeout=10_000)
        return self.page.locator("table tbody tr").count() > 0

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
                An optional ``description`` key is also supported. A default single
                product is created when omitted.

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
                # Wait for the newly appended product fields to mount before filling.
                expect(self._product_name_input(index)).to_be_visible(timeout=5_000)
            self._product_name_input(index).fill(str(product["productName"]))
            self._product_price_input(index).fill(str(product["price"]))
            description = product.get("description")
            if description is not None:
                self._product_description_input(index).fill(str(description))

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
        # Wait for the row to disappear from the list before returning.
        expect(self._catalog_row(name).first).to_be_hidden(timeout=15_000)

    def edit_catalog_product(
        self,
        catalog_name: str,
        index: int,
        name: str,
        price: float,
        description: str | None = None,
    ) -> None:
        """Open the edit dialog for *catalog_name* and update product *index*.

        Args:
            catalog_name: Existing catalog name to edit.
            index: Zero-based product index in the dialog.
            name: New product name.
            price: New product price.
            description: Optional new product description.
        """
        self._edit_button_for(catalog_name).click()
        dialog = self.wait_for_dialog(self._DIALOG_TITLE_EDIT)

        name_input = self._product_name_input(index)
        name_input.clear()
        name_input.fill(name)

        price_input = self._product_price_input(index)
        price_input.clear()
        price_input.fill(str(price))

        if description is not None:
            desc_input = self._product_description_input(index)
            desc_input.clear()
            desc_input.fill(description)

        self._save_catalog_button().click()
        expect(dialog).to_be_hidden(timeout=15_000)
        self.wait_for_loading()

    def remove_catalog_product(self, catalog_name: str, index: int) -> None:
        """Open the edit dialog for *catalog_name* and remove product *index*.

        Args:
            catalog_name: Existing catalog name to edit.
            index: Zero-based product index in the dialog.
        """
        self._edit_button_for(catalog_name).click()
        dialog = self.wait_for_dialog(self._DIALOG_TITLE_EDIT)
        self._remove_product_button(index).click()
        self._save_catalog_button().click()
        expect(dialog).to_be_hidden(timeout=15_000)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Catalog preview page
    # ------------------------------------------------------------------

    def view_catalog(self, name: str) -> None:
        """Click the *View* button for *name* and wait for the preview page.

        Args:
            name: Catalog name whose preview should be opened.
        """
        row = self._catalog_row(name)
        row.get_by_role("button", name=self._VIEW_BTN, exact=True).click()
        self.page.wait_for_url("**/catalogs/**/preview", timeout=10_000)
        self.wait_for_loading()

    def get_preview_catalog_name(self) -> str:
        """Return the catalog name displayed on the preview page.

        Returns:
            Catalog name rendered as the page heading.
        """
        return self.page.locator(self._PREVIEW_CATALOG_NAME_SEL).first.inner_text()

    def get_preview_product_count_text(self) -> str:
        """Return the product count subtitle text (e.g. ``"2 products"``)."""
        return self.page.get_by_text(re.compile(r"\d+ product")).first.inner_text()

    def get_preview_product_count(self) -> int:
        """Return the numeric product count shown on the preview page.

        Returns:
            Number of products parsed from the subtitle, or ``0`` when no
            count text is present.
        """
        text = self.get_preview_product_count_text()
        match = re.search(r"\d+", text)
        return int(match.group()) if match else 0

    def get_preview_product_names(self) -> list[str]:
        """Return the product names listed in the preview page table.

        Returns:
            List of product name strings in table order.
        """
        name_cells = self.page.locator("table tbody tr td:first-child")
        expect(name_cells.first).to_be_visible(timeout=10_000)
        # The table can render rows with empty text before Apollo fills them;
        # poll until at least one cell has non-empty text.
        for _ in range(15):
            names = [t.strip() for t in name_cells.all_inner_texts() if t.strip()]
            if names:
                return names
            self.page.wait_for_timeout(200)
        return name_cells.all_inner_texts()

    def preview_has_product(self, name: str, price: float) -> bool:
        """Return ``True`` when the preview table contains *name* at *price*.

        Args:
            name: Product name to match.
            price: Expected price. Displayed prices are formatted as
                ``"$xx.xx"``.
        """
        price_str = f"${float(price):.2f}"
        name_cells = self.page.locator("table tbody tr td:first-child")
        price_cells = self.page.locator("table tbody tr td:last-child")
        expect(name_cells.first).to_be_visible(timeout=10_000)
        for _ in range(15):
            names = [t.strip() for t in name_cells.all_inner_texts()]
            prices = [t.strip() for t in price_cells.all_inner_texts()]
            if any(n == name and p == price_str for n, p in zip(names, prices)):
                return True
            self.page.wait_for_timeout(200)
        return False

    def get_preview_create_campaign_button_visible(self) -> bool:
        """Return ``True`` when the *Create Campaign* button is visible."""
        return self.page.get_by_role("button", name=self._CREATE_CAMPAIGN_BTN, exact=True).first.is_visible()

    def get_preview_create_shared_campaign_button_visible(self) -> bool:
        """Return ``True`` when the *Create Shared Campaign* button is visible."""
        return self.page.get_by_role("button", name=self._CREATE_SHARED_CAMPAIGN_BTN, exact=True).first.is_visible()
