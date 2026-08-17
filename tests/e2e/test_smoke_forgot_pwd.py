"""Smoke tests for the forgot-password page.

These tests exercise the public ``/forgot-password`` route through the
``ForgotPasswordPage`` page object.  They do **not** submit real reset requests
to Cognito; they verify route rendering, form visibility, and front-end
validation only.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.forgot_password_page import ForgotPasswordPage


@pytest.mark.smoke
def test_forgot_password_page_renders(page: Page) -> None:
    """The forgot-password route loads and renders the reset form.

    Uses the ``ForgotPasswordPage`` POM to verify:
    * The browser lands on ``/forgot-password``.
    * The page subtitle ("Reset your password") is visible.
    * The email input is visible and editable.
    * The *Send Reset Code* submit button is present.
    """
    forgot_page = ForgotPasswordPage(page)
    forgot_page.goto()
    forgot_page.expect_loaded()

    send_code_button = page.get_by_role("button", name="Send Reset Code")
    expect(send_code_button).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_forgot_password_email_validation(page: Page) -> None:
    """Submitting the request-code form without an email shows a validation error.

    This exercises the front-end validation path without calling Cognito.
    """
    forgot_page = ForgotPasswordPage(page)
    forgot_page.goto()
    forgot_page.expect_loaded()

    page.get_by_role("button", name="Send Reset Code").click()

    error_alert = page.get_by_role("alert").first
    expect(error_alert).to_be_visible(timeout=10_000)
    expect(error_alert).to_have_text("Email is required")
