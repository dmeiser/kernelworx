"""Page object for the forgot-password page."""

import os
import re

from playwright.sync_api import Page, expect


class ForgotPasswordPage:
    """Forgot-password / password-reset page."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def goto(self) -> None:
        """Open the forgot-password page."""
        base_url = os.getenv("E2E_BASE_URL", "https://localhost:5173").rstrip("/")
        self.page.goto(f"{base_url}/forgot-password")
        expect(self.page).to_have_url(re.compile(".*/forgot-password"))

    def expect_loaded(self) -> None:
        """Verify the reset form is present."""
        heading = self.page.get_by_role("heading", name="Reset Password")
        expect(heading).to_be_visible(timeout=10_000)
        email_input = self.page.get_by_label("Email")
        expect(email_input).to_be_visible()
        expect(email_input).to_be_editable()
