"""Admin page object — admin console users and catalogs tabs."""

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class AdminPage(BasePage):
    """Page object for ``/admin``.

    Covers the Users, Catalogs, and System Info tabs.  The current test
    helpers focus on happy-path visibility and catalog management, which is
    what the dev admin user (the owner account) can exercise through the UI.
    """

    PATH: str = "/admin"

    # Tabs
    _USERS_TAB: str = "Users"
    _CATALOGS_TAB: str = "Catalogs"
    _SYSTEM_INFO_TAB: str = "System Info"

    # Catalogs tab
    _NEW_CATALOG_BTN: str = "New Catalog"
    _EDIT_CATALOG_BTN: str = "Edit catalog"
    _DELETE_CATALOG_BTN: str = "Delete catalog"

    # Users tab
    _SEARCH_FIELD_LABEL: str = "Search User"
    _SEARCH_BTN: str = "Search"

    # Dialog
    _CATALOG_NAME_LABEL: str = "Catalog Name"
    _ADD_PRODUCT_BTN: str = "Add Product"
    _SAVE_CATALOG_BTN: str = "Save Catalog"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self) -> None:
        """Navigate to ``/admin`` and wait for the page to load."""
        self.navigate(self.PATH)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Locator factories
    # ------------------------------------------------------------------

    def _users_tab(self) -> Locator:
        """Return locator for the *Users* tab."""
        return self.page.get_by_role("tab", name=self._USERS_TAB, exact=True)

    def _catalogs_tab(self) -> Locator:
        """Return locator for the *Catalogs* tab."""
        return self.page.get_by_role("tab", name=self._CATALOGS_TAB, exact=True)

    def _system_info_tab(self) -> Locator:
        """Return locator for the *System Info* tab."""
        return self.page.get_by_role("tab", name=self._SYSTEM_INFO_TAB, exact=True)

    def _new_catalog_button(self) -> Locator:
        """Return locator for the *New Catalog* button on the Catalogs tab."""
        return self.get_by_role_button(self._NEW_CATALOG_BTN)

    def _search_field(self) -> Locator:
        """Return locator for the user search text field."""
        return self.page.get_by_label(self._SEARCH_FIELD_LABEL, exact=True)

    def _search_button(self) -> Locator:
        """Return locator for the *Search* button."""
        return self.get_by_role_button(self._SEARCH_BTN)

    def _catalog_card(self, name: str) -> Locator:
        """Return the catalog card/paper containing *name*.

        Args:
            name: Catalog name text to match.
        """
        return self.page.locator("div.MuiPaper-root").filter(has_text=name)

    def _catalog_name_input(self) -> Locator:
        """Return locator for the catalog name field inside the editor dialog."""
        return self.page.get_by_label(self._CATALOG_NAME_LABEL, exact=True)

    def _add_product_button(self) -> Locator:
        """Return locator for the *Add Product* button inside the dialog."""
        return self.get_by_role_button(self._ADD_PRODUCT_BTN)

    def _save_catalog_button(self) -> Locator:
        """Return locator for the *Save Catalog* dialog button."""
        return self.get_by_role_button(self._SAVE_CATALOG_BTN)

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

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_visible(self) -> bool:
        """Return ``True`` when the admin console heading is visible."""
        return self.page.get_by_text("Admin Console").first.is_visible()

    def has_catalog(self, name: str) -> bool:
        """Return ``True`` when a catalog card with *name* is visible.

        Args:
            name: Catalog name text.
        """
        return self._catalog_card(name).first.is_visible()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def switch_to_users(self) -> None:
        """Click the *Users* tab."""
        self._users_tab().click()
        self.wait_for_loading()

    def switch_to_catalogs(self) -> None:
        """Click the *Catalogs* tab."""
        self._catalogs_tab().click()
        self.wait_for_loading()

    def switch_to_system_info(self) -> None:
        """Click the *System Info* tab."""
        self._system_info_tab().click()
        self.wait_for_loading()

    def search_user(self, query: str) -> None:
        """Search for a user by *query* in the Users tab.

        Args:
            query: Email, name, or account ID substring.
        """
        self._search_field().fill(query)
        self._search_button().click()
        self.wait_for_loading()

    def create_managed_catalog(self, name: str) -> None:
        """Create a managed catalog from the Catalogs tab.

        Args:
            name: Catalog name.
        """
        self._new_catalog_button().click()
        dialog = self.wait_for_dialog("Create Catalog")

        self._catalog_name_input().fill(name)
        self._product_name_input(0).fill("E2E Admin Popcorn")
        self._product_price_input(0).fill("30")

        self._save_catalog_button().click()
        expect(dialog).to_be_hidden(timeout=15_000)
        self.wait_for_loading()

    def delete_managed_catalog(self, name: str) -> None:
        """Delete the managed catalog named *name* from the Catalogs tab.

        Args:
            name: Catalog name to delete.
        """
        card = self._catalog_card(name)
        card.locator('[aria-label="Delete catalog"]').click()
        dialog = self.wait_for_dialog("Delete Catalog")
        dialog.get_by_role("button", name="Delete", exact=True).click()
        expect(dialog).to_be_hidden(timeout=15_000)
        self.wait_for_loading()
