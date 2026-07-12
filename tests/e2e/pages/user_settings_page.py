"""User settings page object — view and edit account information."""

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class UserSettingsPage(BasePage):
    """Page object for ``/account/settings``.

    Provides helpers for viewing account information and editing profile
    fields via the *Edit Profile* dialog.  The happy-path account-info edit
    (given name, city, etc.) is supported; password, MFA, passkey, and account
    deletion flows are out of scope.

    Selector notes:

    * The *Edit Profile* button and *Save Changes* button use visible-text
      selectors because the production components have no ``data-testid``
      attributes.
    * Account detail rows are rendered as MUI ``ListItem`` elements; the
      secondary text (the field value) is read via the
      ``MuiListItemText-secondary`` class.
    """

    PATH: str = "/account/settings"

    _EDIT_PROFILE_BTN: str = "Edit Profile"
    _DIALOG_TITLE: str = "Edit Profile Information"
    _FIRST_NAME_LABEL: str = "First Name"
    _LAST_NAME_LABEL: str = "Last Name"
    _CITY_LABEL: str = "City"
    _STATE_LABEL: str = "State"
    _SAVE_CHANGES_BTN: str = "Save Changes"
    _DETAIL_ROW_SEL: str = "li"
    _DETAIL_VALUE_SEL: str = ".MuiListItemText-secondary"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance.

        Args:
            page: Active Playwright :class:`~playwright.sync_api.Page`.
        """
        super().__init__(page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self) -> None:
        """Navigate to ``/account/settings`` and wait until the page is ready."""
        self.navigate(self.PATH)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Locator factories
    # ------------------------------------------------------------------

    def _edit_profile_button(self) -> Locator:
        """Return locator for the *Edit Profile* button."""
        return self.get_by_role_button(self._EDIT_PROFILE_BTN)

    def _first_name_input(self) -> Locator:
        """Return locator for the *First Name* text field in the edit dialog."""
        return self.page.get_by_label(self._FIRST_NAME_LABEL)

    def _last_name_input(self) -> Locator:
        """Return locator for the *Last Name* text field in the edit dialog."""
        return self.page.get_by_label(self._LAST_NAME_LABEL)

    def _city_input(self) -> Locator:
        """Return locator for the *City* text field in the edit dialog."""
        return self.page.get_by_label(self._CITY_LABEL)

    def _state_input(self) -> Locator:
        """Return locator for the *State* text field in the edit dialog."""
        return self.page.get_by_label(self._STATE_LABEL)

    def _save_changes_button(self) -> Locator:
        """Return locator for the *Save Changes* button in the edit dialog."""
        return self.get_by_role_button(self._SAVE_CHANGES_BTN)

    def _detail_row(self, label: str) -> Locator:
        """Return the account detail ``<li>`` row whose primary text is *label*.

        Args:
            label: Visible label of the detail row (e.g. ``"First Name"``).
        """
        return self.page.locator(self._DETAIL_ROW_SEL).filter(has_text=label).first

    def _detail_value(self, label: str) -> Locator:
        """Return the secondary value element for the row matching *label*.

        Args:
            label: Visible label of the detail row.
        """
        return self._detail_row(label).locator(self._DETAIL_VALUE_SEL)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def get_given_name(self) -> str:
        """Return the displayed *First Name* value from the account details.

        Returns:
            Inner text of the First Name row's secondary value.
        """
        value = self._detail_value(self._FIRST_NAME_LABEL)
        expect(value).to_be_visible(timeout=10_000)
        return value.inner_text()

    def get_city(self) -> str:
        """Return the displayed *City* value from the account details.

        Returns:
            Inner text of the City row's secondary value.
        """
        value = self._detail_value(self._CITY_LABEL)
        expect(value).to_be_visible(timeout=10_000)
        return value.inner_text()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def edit_given_name_and_city(self, given_name: str, city: str) -> None:
        """Open the edit dialog, update first name and city, and save.

        Waits for the dialog to close and the account query to refetch before
        returning.

        Args:
            given_name: New first name value.
            city: New city value.
        """
        self._edit_profile_button().click()
        dialog = self.wait_for_dialog(self._DIALOG_TITLE)
        self._first_name_input().fill(given_name)
        self._city_input().fill(city)
        self._save_changes_button().click()
        expect(dialog).to_be_hidden(timeout=10_000)
        self.wait_for_loading()
