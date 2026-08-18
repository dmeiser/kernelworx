"""Smoke tests for the forgot-password page.

Verifies that the ``/forgot-password`` route renders the branded reset form
instead of redirecting to the marketing page (404 catch-all), and that client-
side validation is exercised.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.forgot_password_page import ForgotPasswordPage


@pytest.mark.smoke
def test_forgot_password_page_loads(page: Page) -> None:
    """The forgot-password page loads with its subtitle and email field."""
    forgot = ForgotPasswordPage(page)
    forgot.goto()

    subtitle = page.get_by_text("Reset your password")
    expect(subtitle).to_be_visible(timeout=10_000)

    email_input = page.get_by_label("Email")
    expect(email_input).to_be_visible()
    expect(email_input).to_be_editable()

    expect(page.get_by_role("button", name="Send Reset Code")).to_be_visible()


@pytest.mark.smoke
def test_forgot_password_email_validation(page: Page) -> None:
    """Submitting the empty form triggers the client-side email validation."""
    forgot = ForgotPasswordPage(page)
    forgot.goto()

    # HTML5 constraint validation blocks a plain button click on an empty
    # required field, so dispatch the submit event directly.
    form = page.locator("form").first
    form.evaluate("(el) => el.dispatchEvent(new Event('submit', { bubbles: true }))")

    alert = page.get_by_role("alert")
    expect(alert).to_be_visible(timeout=10_000)
    expect(alert).to_contain_text("Email is required")
