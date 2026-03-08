"""Share page object — profile invite creation, acceptance, and revocation."""

import urllib.parse

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class SharePage(BasePage):
    """Page object covering the profile-sharing flow.

    Two distinct routes are driven:

    * ``/scouts/{profileId}/manage`` – invite code generation, share list,
      and revocation (``ScoutManagementPage``).
    * ``/accept-invite`` – invite code acceptance (``AcceptInvitePage``).

    **Selector notes:**

    * *Generate New Invite* button uses visible text (``getCreateInviteText``
      helper returns ``"Generate New Invite"``).
    * The new invite code is shown in an ``<Alert severity="success">`` whose
      text contains ``"New Invite Code:"``; the actual code follows that prefix.
    * The shares table uses ``<IconButton title="Revoke access">`` per row.
    * The accept-invite form has ``label="Invite Code"`` on the ``<TextField>``
      and a *Accept Invite* ``<Button type="submit">``.

    TODO: add ``data-testid`` attributes to the invite section and share rows
    for more precise targeting.
    """

    _MANAGE_SUFFIX: str = "/manage"
    _ACCEPT_PATH: str = "/accept-invite"

    # Button / label text (verified from component source)
    _GENERATE_INVITE_BTN: str = "Generate New Invite"
    _INVITE_CODE_LABEL: str = "Invite Code"
    _ACCEPT_BTN: str = "Accept Invite"
    _REVOKE_TITLE: str = "Revoke access"

    # Alert text prefix used by NewInviteCodeAlert
    _NEW_CODE_PREFIX: str = "New Invite Code:"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance.

        Args:
            page: Active Playwright :class:`~playwright.sync_api.Page`.
        """
        super().__init__(page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self, profile_id: str) -> None:
        """Navigate to the management page for *profile_id*.

        Args:
            profile_id: Raw profile identifier, URL-encoded automatically.
        """
        encoded = urllib.parse.quote(profile_id, safe="")
        self.navigate(f"/scouts/{encoded}{self._MANAGE_SUFFIX}")
        self.wait_for_loading()

    def goto_accept(self) -> None:
        """Navigate to the ``/accept-invite`` route."""
        self.navigate(self._ACCEPT_PATH)
        expect(self._invite_code_input()).to_be_visible()

    # ------------------------------------------------------------------
    # Locator factories
    # ------------------------------------------------------------------

    def _generate_invite_button(self) -> Locator:
        """Return locator for the *Generate New Invite* button."""
        return self.get_by_role_button(self._GENERATE_INVITE_BTN)

    def _invite_code_input(self) -> Locator:
        """Return locator for the *Invite Code* text field on the accept page."""
        return self.page.get_by_label(self._INVITE_CODE_LABEL)

    def _accept_button(self) -> Locator:
        """Return locator for the *Accept Invite* submit button scoped to main content."""
        return self.page.get_by_role("main").get_by_role("button", name=self._ACCEPT_BTN, exact=True)

    def _new_invite_alert(self) -> Locator:
        """Return locator for the success alert that displays the new invite code."""
        return self.page.get_by_role("alert").filter(has_text=self._NEW_CODE_PREFIX)

    def _revoke_button_for(self, email: str) -> Locator:
        """Return locator for the revoke icon button on the share row for *email*.

        Args:
            email: Email address text visible in the share row.
        """
        row = self.page.get_by_role("row").filter(has_text=email)
        return row.locator(f'[title="{self._REVOKE_TITLE}"]')

    # ------------------------------------------------------------------
    # Actions — invite generation
    # ------------------------------------------------------------------

    def create_invite(self, permission_level: str = "READ") -> None:
        """Generate a new invite code with the specified *permission_level*.

        The permission checkboxes are pre-checked; this method clicks the
        *Generate New Invite* button and waits for the success alert to appear.

        Args:
            permission_level: ``"READ"`` or ``"WRITE"``.  Defaults to
                ``"READ"``.  The appropriate checkbox is checked before
                generating the invite.
        """
        self._ensure_permission_checked(permission_level)
        self._generate_invite_button().click()
        expect(self._new_invite_alert()).to_be_visible(timeout=10_000)

    def _ensure_permission_checked(self, permission_level: str) -> None:
        """Check the checkbox for *permission_level* if it is not already checked.

        Args:
            permission_level: ``"READ"`` or ``"WRITE"``.
        """
        label_text = (
            "Read (view campaigns and orders)" if permission_level == "READ" else "Write (edit campaigns and orders)"
        )
        checkbox = self.page.get_by_label(label_text, exact=False)
        if not checkbox.is_checked():
            checkbox.check()

    def get_invite_link(self) -> str:
        """Return the raw invite code from the success alert.

        Parses the text after ``"New Invite Code:"`` to extract the code
        so callers can pass it to :meth:`accept_invite`.

        Returns:
            The invite code string (e.g. ``"ABC12345"``), or ``""`` when no
            success alert is currently visible.
        """
        alert = self._new_invite_alert()
        if not alert.is_visible():
            return ""
        raw = alert.inner_text()
        return self._parse_invite_code(raw)

    @staticmethod
    def _parse_invite_code(alert_text: str) -> str:
        """Extract the invite code from *alert_text*.

        Looks for the ``"New Invite Code:"`` prefix and returns the following
        token.

        Args:
            alert_text: Full inner text of the invite-code Alert.

        Returns:
            Invite code token, or ``""`` when the prefix is not found.
        """
        prefix = "New Invite Code:"
        if prefix not in alert_text:
            return ""
        after_prefix = alert_text.split(prefix, 1)[1].strip()
        # The code is the first whitespace-separated token
        return after_prefix.split()[0] if after_prefix.split() else ""

    # ------------------------------------------------------------------
    # Actions — invite acceptance
    # ------------------------------------------------------------------

    def accept_invite(self, invite_code: str) -> None:
        """Navigate to ``/accept-invite``, enter *invite_code*, and submit.

        Waits for the success alert before returning.

        Args:
            invite_code: The invite code to redeem (e.g. ``"ABC12345"``).
        """
        self.goto_accept()
        self._invite_code_input().fill(invite_code)
        self._accept_button().click()
        expect(self.page.get_by_role("alert")).to_be_visible(timeout=15_000)

    # ------------------------------------------------------------------
    # Actions — revocation
    # ------------------------------------------------------------------

    def revoke_access(self, email: str) -> None:
        """Click the revoke icon button on the share row for *email*.

        The app shows a ``window.confirm`` dialog before revoking; this
        method accepts it automatically via Playwright's dialog handler.

        Args:
            email: Email address shown in the share row to revoke.
        """
        self.page.once("dialog", lambda dlg: dlg.accept())
        self._revoke_button_for(email).click()
        self.wait_for_loading()
        # Wait for the share row to disappear from the table (confirms revocation completed)
        cell = self.page.get_by_role("cell", name=email)
        if cell.first.is_visible():
            expect(cell.first).to_be_hidden(timeout=10_000)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def has_shared_access(self, email: str) -> bool:
        """Return ``True`` when *email* appears in the *Current Access* table.

        Args:
            email: Email address to check for in the shares table.
        """
        cell = self.page.get_by_role("cell", name=email)
        return cell.first.is_visible()
