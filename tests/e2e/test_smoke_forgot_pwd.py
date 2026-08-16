"""Smoke test for the forgot-password page.

Verifies that the ``/forgot-password`` route renders the branded reset form
instead of redirecting to the marketing page (404 catch-all).
"""

import os
import re

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.smoke
def test_forgot_password_page_loads(page: Page) -> None:
    """The forgot-password page loads with its heading and email field."""
    base_url = os.getenv("E2E_BASE_URL", "https://localhost:5173").rstrip("/")
    page.goto(f"{base_url}/forgot-password")

    expect(page).to_have_url(re.compile(".*/forgot-password"))

    heading = page.get_by_role("heading", name="Reset Password")
    expect(heading).to_be_visible(timeout=10_000)

    email_input = page.get_by_label("Email")
    expect(email_input).to_be_visible()
    expect(email_input).to_be_editable()
