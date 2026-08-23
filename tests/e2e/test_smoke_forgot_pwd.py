"""Smoke test for the forgot-password page.

Verifies that the ``/forgot-password`` route renders the branded reset form
instead of redirecting to the marketing page (404 catch-all).
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.base_page import BasePage


@pytest.mark.skip(reason="Disabled pending an email-free password-reset test strategy; see #117")
@pytest.mark.smoke
def test_forgot_password_page_loads(page: Page) -> None:
    """The forgot-password page loads with its heading and email field."""
    base = BasePage(page)
    base.navigate("/forgot-password")
    base.wait_for_url_contains("/forgot-password")

    heading = page.get_by_role("heading", name="Reset Password")
    expect(heading).to_be_visible(timeout=10_000)

    email_input = page.get_by_label("Email")
    expect(email_input).to_be_visible()
    expect(email_input).to_be_editable()

    send_code_button = page.get_by_role("button", name="Send Reset Code")
    expect(send_code_button).to_be_visible()
