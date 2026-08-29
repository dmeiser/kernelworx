"""Smoke tests for the payment methods management page.

These tests verify that the owner can view built-in payment methods (Cash and
Check), create a custom payment method, rename it, upload and delete a QR code,
and delete it.  Custom methods are removed in ``finally`` blocks so the shared
owner account does not accumulate test data.
"""

import uuid
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.payment_page import PaymentPage


def _unique_method_name(base: str) -> str:
    """Return a unique payment method name by appending a short UUID suffix."""
    return f"{base} {uuid.uuid4().hex[:8]}"


_QR_FIXTURE_PATH: Path = Path(__file__).resolve().parent / "fixtures" / "qr.png"


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
    try:
        payment_page.add_payment_method(method_name)
        assert payment_page.has_payment_method(method_name), (
            f"Custom payment method '{method_name}' must appear after creation"
        )
    finally:
        if payment_page.has_payment_method(method_name):
            payment_page.delete_payment_method(method_name)


@pytest.mark.smoke
def test_delete_payment_method(owner_page: Page) -> None:
    """Deleting a custom payment method removes it from the list."""
    method_name = _unique_method_name("Zelle")
    payment_page = PaymentPage(owner_page)
    payment_page.goto()
    payment_page.add_payment_method(method_name)
    try:
        assert payment_page.has_payment_method(method_name), (
            f"Custom payment method '{method_name}' must be present before deletion"
        )

        payment_page.delete_payment_method(method_name)
        assert not payment_page.has_payment_method(method_name), (
            f"Custom payment method '{method_name}' must not appear after deletion"
        )
    except Exception:
        # Ensure cleanup even if the assertion path fails.
        if payment_page.has_payment_method(method_name):
            payment_page.delete_payment_method(method_name)
        raise


@pytest.mark.smoke
def test_rename_payment_method(owner_page: Page) -> None:
    """Renaming a custom payment method updates the list."""
    method_name = _unique_method_name("Venmo")
    new_name = f"{method_name} Renamed"
    payment_page = PaymentPage(owner_page)
    payment_page.goto()
    payment_page.add_payment_method(method_name)
    try:
        assert payment_page.has_payment_method(method_name), (
            f"Custom payment method '{method_name}' must be present before rename"
        )

        payment_page.rename_payment_method(method_name, new_name)
        assert not payment_page.has_payment_method(method_name), (
            f"Old payment method name '{method_name}' must not appear after rename"
        )
        assert payment_page.has_payment_method(new_name), (
            f"New payment method name '{new_name}' must appear after rename"
        )
    finally:
        for name in (new_name, method_name):
            if payment_page.has_payment_method(name):
                payment_page.delete_payment_method(name)


@pytest.mark.smoke
def test_upload_and_delete_qr_code(owner_page: Page) -> None:
    """Uploading a QR code shows a preview; deleting it removes the preview."""
    if not _QR_FIXTURE_PATH.exists():
        pytest.skip(f"QR fixture not found: {_QR_FIXTURE_PATH}")

    method_name = _unique_method_name("Zelle")
    payment_page = PaymentPage(owner_page)
    payment_page.goto()
    payment_page.add_payment_method(method_name)
    try:
        assert payment_page.has_payment_method(method_name), (
            f"Custom payment method '{method_name}' must be present before QR upload"
        )

        payment_page.upload_qr_code(method_name, str(_QR_FIXTURE_PATH))
        assert payment_page.has_qr_code(method_name), f"QR code must be visible for '{method_name}' after upload"

        # Exercise the QR preview dialog (required by #85).
        dialog = payment_page.view_qr_code(method_name)
        dialog.get_by_role("button", name="Close").click()
        expect(dialog).to_be_hidden(timeout=10_000)

        payment_page.delete_qr_code(method_name)
        assert not payment_page.has_qr_code(method_name), (
            f"QR code must not be visible for '{method_name}' after deletion"
        )
        assert payment_page.has_payment_method(method_name), (
            f"Payment method '{method_name}' must still exist after QR deletion"
        )
    finally:
        if payment_page.has_payment_method(method_name):
            payment_page.delete_payment_method(method_name)


@pytest.mark.smoke
def test_built_in_methods_read_only(owner_page: Page) -> None:
    """Built-in Cash and Check methods cannot be edited or deleted."""
    payment_page = PaymentPage(owner_page)
    payment_page.goto()

    for method_name in ("Cash", "Check"):
        assert payment_page.has_payment_method(method_name), f"Built-in method '{method_name}' must be visible"
        card = payment_page._card_for(method_name)
        assert card.get_by_role("button", name=f"Edit {method_name}", exact=True).count() == 0, (
            f"Built-in method '{method_name}' must not have an Edit button"
        )
        assert card.get_by_role("button", name=f"Delete {method_name}", exact=True).count() == 0, (
            f"Built-in method '{method_name}' must not have a Delete button"
        )
