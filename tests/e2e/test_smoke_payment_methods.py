"""Smoke tests for the payment methods management page.

These tests verify that the owner can view built-in payment methods (Cash and
Check), create a custom payment method, and delete it.
"""

import uuid

import pytest
from playwright.sync_api import Page

from tests.e2e.pages.payment_page import PaymentPage


def _unique_method_name(base: str) -> str:
    """Return a unique payment method name by appending a short UUID suffix."""
    return f"{base} {uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_payment_methods_page_loads(owner_page: Page) -> None:
    """The payment methods page loads and shows built-in Cash and Check methods."""
    payment_page = PaymentPage(owner_page)
    payment_page.goto()

    assert payment_page.has_payment_method("Cash"), "Cash must be visible as a built-in payment method"
    assert payment_page.has_payment_method("Check"), "Check must be visible as a built-in payment method"


@pytest.mark.smoke
def test_add_payment_method(owner_page: Page) -> None:
    """Adding a custom payment method makes it visible in the list."""
    method_name = _unique_method_name("Venmo")
    payment_page = PaymentPage(owner_page)
    payment_page.goto()
    payment_page.add_payment_method(method_name)
    assert payment_page.has_payment_method(method_name), (
        f"Custom payment method '{method_name}' must appear after creation"
    )


@pytest.mark.smoke
def test_delete_payment_method(owner_page: Page) -> None:
    """Deleting a custom payment method removes it from the list."""
    method_name = _unique_method_name("Zelle")
    payment_page = PaymentPage(owner_page)
    payment_page.goto()
    payment_page.add_payment_method(method_name)
    assert payment_page.has_payment_method(method_name), (
        f"Custom payment method '{method_name}' must be present before deletion"
    )

    payment_page.delete_payment_method(method_name)
    assert not payment_page.has_payment_method(method_name), (
        f"Custom payment method '{method_name}' must not appear after deletion"
    )
