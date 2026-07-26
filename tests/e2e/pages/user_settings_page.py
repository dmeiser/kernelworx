"""User settings page object — view and edit account information.

Covers the HTMX ``/account/settings`` route (``user_settings.html``).

The account-info rows are ``<li>`` elements each containing a label ``<p>`` and
a value ``<p>``.  The *Edit Profile* button opens a native ``<dialog>``
(``#edit-profile-dialog``) with inputs ``#edit-givenName``, ``#edit-city``,
etc.  The edit form posts to ``/api/account`` (not wired in the local test
server), so edits are not persisted locally — tests that assert persistence
skip with a clear reason.
"""

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class UserSettingsPage(BasePage):
    """Page object for ``/account/settings``."""

    PATH: str = "/account/settings"

    _EDIT_PROFILE_BTN: str = "Edit Profile"
    _DIALOG_TITLE: str = "Edit Profile Information"
    _FIRST_NAME_LABEL: str = "First Name"
    _LAST_NAME_LABEL: str = "Last Name"
    _CITY_LABEL: str = "City"
    _STATE_LABEL: str = "State"
    _SAVE_CHANGES_BTN: str = "Save Changes"
    _DETAIL_ROW_SEL: str = "li"
    # The value is the second <p> inside the <li> (the first <p> is the label).
    _DETAIL_VALUE_SEL: str = "p:nth-of-type(2)"

    # Edit dialog input selectors (by id, since the labels are non-unique).
    _EDIT_FIRST_NAME_SEL: str = "#edit-givenName"
    _EDIT_LAST_NAME_SEL: str = "#edit-familyName"
    _EDIT_CITY_SEL: str = "#edit-city"
    _EDIT_STATE_SEL: str = "#edit-state"
    _EDIT_DIALOG_SEL: str = "#edit-profile-dialog"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

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
        return self.page.locator(self._EDIT_FIRST_NAME_SEL)

    def _last_name_input(self) -> Locator:
        """Return locator for the *Last Name* text field in the edit dialog."""
        return self.page.locator(self._EDIT_LAST_NAME_SEL)

    def _city_input(self) -> Locator:
        """Return locator for the *City* text field in the edit dialog."""
        return self.page.locator(self._EDIT_CITY_SEL)

    def _state_input(self) -> Locator:
        """Return locator for the *State* text field in the edit dialog."""
        return self.page.locator(self._EDIT_STATE_SEL)

    def _save_changes_button(self) -> Locator:
        """Return locator for the *Save Changes* button in the edit dialog."""
        return self.page.locator(self._EDIT_DIALOG_SEL).get_by_role("button", name=self._SAVE_CHANGES_BTN)

    def _detail_row(self, label: str) -> Locator:
        """Return the account detail ``<li>`` row whose label text is *label*."""
        return self.page.locator(self._DETAIL_ROW_SEL).filter(has_text=label).first

    def _detail_value(self, label: str) -> Locator:
        """Return the value element for the row matching *label*."""
        return self._detail_row(label).locator(self._DETAIL_VALUE_SEL)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def get_given_name(self) -> str:
        """Return the displayed *First Name* value from the account details."""
        value = self._detail_value(self._FIRST_NAME_LABEL)
        expect(value).to_be_visible(timeout=10_000)
        return value.inner_text()

    def get_city(self) -> str:
        """Return the displayed *City* value from the account details."""
        value = self._detail_value(self._CITY_LABEL)
        expect(value).to_be_visible(timeout=10_000)
        return value.inner_text()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def edit_given_name_and_city(self, given_name: str, city: str) -> None:
        """Open the edit dialog, update first name and city, and save.

        Note: the local test server does not wire ``/api/account``, so the save
        does not persist; callers that assert persistence should skip locally.
        """
        self._edit_profile_button().click()
        dialog = self.page.locator(self._EDIT_DIALOG_SEL)
        expect(dialog).to_be_visible(timeout=5_000)
        self._first_name_input().fill(given_name)
        self._city_input().fill(city)
        self._save_changes_button().click()
        self.wait_for_loading()
