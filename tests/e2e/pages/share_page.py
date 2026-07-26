"""Share page object — profile invite creation, acceptance, and revocation.

Covers the sharing UI on ``/scouts/{profileId}/manage``
(``scout_management.html``) and the (not-implemented-locally) ``/accept-invite``
route.

NOTE: The local test server does not wire the invite-generation endpoint at
the path the HTMX template posts to (``/api/profiles/{id}/invites``) nor an
``/accept-invite`` page, and there is no second real Cognito user.  The full
share-create / accept / revoke flow therefore cannot run locally; tests that
exercise it ``pytest.skip`` with a clear reason.  This page object is retained
for API compatibility.
"""

import urllib.parse

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class SharePage(BasePage):
    """Page object covering the profile-sharing flow."""

    _MANAGE_SUFFIX: str = "/manage"
    _ACCEPT_PATH: str = "/accept-invite"

    # Button / label text from scout_management.html
    _GENERATE_INVITE_BTN: str = "Generate New Invite"
    _INVITE_CODE_LABEL: str = "Invite Code"
    _ACCEPT_BTN: str = "Accept Invite"
    _REVOKE_TITLE: str = "Revoke access"

    # Alert text prefix used by the invite-result swap (handler returns
    # "Invite Code: <code>"; the React original used "New Invite Code:").
    _NEW_CODE_PREFIX: str = "Invite Code:"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    def goto(self, profile_id: str) -> None:
        """Navigate to the management page for *profile_id* (URL-encoded)."""
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
        """Return locator for the *Accept Invite* submit button."""
        return self.page.get_by_role("button", name=self._ACCEPT_BTN, exact=True)

    def _new_invite_alert(self) -> Locator:
        """Return locator for the swap that displays the new invite code."""
        return self.page.locator("#invite-result")

    def _revoke_button_for(self, email: str) -> Locator:
        """Return locator for the revoke icon button on the share row for *email*."""
        row = self.page.get_by_role("row").filter(has_text=email)
        return row.locator(f'[title="{self._REVOKE_TITLE}"]')

    # ------------------------------------------------------------------
    # Actions — invite generation
    # ------------------------------------------------------------------

    def create_invite(self, permission_level: str = "READ") -> None:
        """Generate a new invite code with the specified *permission_level*."""
        self._ensure_permission_checked(permission_level)
        self._generate_invite_button().click()
        expect(self._new_invite_alert()).to_be_visible(timeout=10_000)

    def _ensure_permission_checked(self, permission_level: str) -> None:
        """Check the checkbox for *permission_level* if it is not already checked."""
        label_text = (
            "Read (view campaigns and orders)" if permission_level == "READ" else "Write (edit campaigns and orders)"
        )
        checkbox = self.page.get_by_label(label_text, exact=False)
        if not checkbox.is_checked():
            checkbox.check()

    def get_invite_link(self) -> str:
        """Return the raw invite code from the invite-result swap."""
        alert = self._new_invite_alert()
        if not alert.is_visible():
            return ""
        raw = alert.inner_text()
        return self._parse_invite_code(raw)

    @staticmethod
    def _parse_invite_code(alert_text: str) -> str:
        """Extract the invite code from *alert_text*."""
        prefix = "Invite Code:"
        if prefix not in alert_text:
            return ""
        after_prefix = alert_text.split(prefix, 1)[1].strip()
        return after_prefix.split()[0] if after_prefix.split() else ""

    # ------------------------------------------------------------------
    # Actions — invite acceptance
    # ------------------------------------------------------------------

    def accept_invite(self, invite_code: str) -> None:
        """Navigate to ``/accept-invite``, enter *invite_code*, and submit."""
        self.goto_accept()
        self._invite_code_input().fill(invite_code)
        self._accept_button().click()
        expect(self.page.get_by_role("alert")).to_be_visible(timeout=15_000)

    # ------------------------------------------------------------------
    # Actions — revocation
    # ------------------------------------------------------------------

    def revoke_access(self, email: str) -> None:
        """Click the revoke icon button on the share row for *email*."""
        self.page.once("dialog", lambda dlg: dlg.accept())
        self._revoke_button_for(email).click()
        self.wait_for_loading()
        cell = self.page.get_by_role("cell", name=email)
        if cell.first.is_visible():
            expect(cell.first).to_be_hidden(timeout=10_000)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def has_shared_access(self, email: str) -> bool:
        """Return ``True`` when *email* appears in the *Who Has Access* table."""
        cell = self.page.get_by_role("cell", name=email)
        return cell.first.is_visible()
