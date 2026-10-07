"""Page objects for the public order surface (spec 10.5).

Three routes share this module because they are one feature and one URL family:

* :class:`PublicOrderSettingsPage` — the seller's ``/scouts/{profileId}/public-orders``
  settings and share view.
* :class:`PublicOrderPage` — the anonymous buyer's ``/o/{profileId}/{token}`` offer page.
* :class:`PublicReceiptPage` — the anonymous buyer's ``/r/{campaignId}/{orderSuffix}/{token}``
  receipt page.

Navigation note
---------------
Unlike the protected routes, these are loaded with a **hard** ``page.goto`` rather
than :meth:`BasePage.navigate`'s client-side ``pushState``.  The ``pushState`` dance
exists only because a hard load of ``/login`` reaches Cognito's managed page through
the CloudFront ``/l*`` behavior; ``/o/`` and ``/r/`` are ordinary SPA paths, and a
hard load is the faithful test of them — it is what a buyer scanning a QR code does,
and it is what proves the route is not behind ``ProtectedRoute``.

Selector note
-------------
The public components carry ``data-testid`` attributes throughout (unlike the older
pages), so this module targets them directly instead of visible text wherever a
test id exists.
"""

import time
from urllib.parse import quote, urlparse

from playwright.sync_api import Locator, expect

from .base_page import BasePage

#: Copy rendered by ``PublicPageUnavailable`` for every unusable link.  The server
#: answers a bad token, a disabled profile, a stale campaign and a deleted order
#: with the identical NOT_FOUND, so this one string is the whole not-available state.
UNAVAILABLE_TITLE = "This order link is not available."

#: ``NoIndexMeta.NOINDEX_CONTENT`` — asserted on both public routes.
NOINDEX_CONTENT = "noindex, nofollow"


class PublicOrderSettingsPage(BasePage):
    """Seller-side ``/scouts/{profileId}/public-orders`` settings and share view."""

    PATH_SUFFIX: str = "/public-orders"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self, profile_id: str) -> None:
        """Open the public order settings for *profile_id*.

        Uses :meth:`BasePage.navigate` (SPA root + client-side route) like every
        other protected page object, so the Amplify session restore is already
        settled when the page reads its settings.

        Args:
            profile_id: Raw profile identifier (``PROFILE#…``); URL-encoded here.
        """
        self.navigate(f"/scouts/{quote(profile_id, safe='')}{self.PATH_SUFFIX}")
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Enable toggle and acknowledgement block
    # ------------------------------------------------------------------

    def enable_switch(self) -> Locator:
        """Return the *Accept public orders* switch."""
        return self.page.get_by_role("switch", name="Accept public orders")

    def set_enabled(self, enabled: bool) -> None:
        """Turn the *Accept public orders* switch to *enabled*.

        Args:
            enabled: Desired switch state.
        """
        switch = self.enable_switch()
        if switch.is_checked() != enabled:
            switch.click()

    def ack_block_is_visible(self) -> bool:
        """Return ``True`` when the acknowledgement block is rendered.

        The block renders only while the stored acknowledgement version lags the
        current constant, i.e. on a profile that has never accepted the wording.
        """
        return self.page.get_by_test_id("ack-block").is_visible()

    def ack_heading(self) -> str:
        """Return the acknowledgement block's heading text."""
        return self.page.get_by_test_id("ack-block").get_by_text("Before you turn this on").inner_text()

    def ack_texts(self) -> list[str]:
        """Return the two acknowledgement labels in render order."""
        block = self.page.get_by_test_id("ack-block")
        return [label.inner_text() for label in block.locator("label.MuiFormControlLabel-root").all()]

    def ack_checkboxes(self) -> list[Locator]:
        """Return the two acknowledgement checkboxes in render order (payment, disclosure)."""
        block = self.page.get_by_test_id("ack-block")
        return block.get_by_role("checkbox").all()

    def check_ack(self, index: int) -> None:
        """Check the acknowledgement checkbox at *index* (0 = payment, 1 = disclosure).

        Args:
            index: Zero-based position in the acknowledgement block.
        """
        self.ack_checkboxes()[index].check()

    # ------------------------------------------------------------------
    # Campaign and payment-method selection
    # ------------------------------------------------------------------

    def select_campaign(self, campaign_name: str) -> None:
        """Pick the active campaign whose label contains *campaign_name*.

        Args:
            campaign_name: Substring of the ``"{name} ({year})"`` option label.
        """
        self.page.get_by_test_id("campaign-select").click()
        option = self.page.get_by_role("option", name=campaign_name)
        expect(option).to_be_visible(timeout=10_000)
        option.click()

    def method_checkbox(self, name: str) -> Locator:
        """Return the checklist checkbox for the payment method *name*.

        Args:
            name: Exact payment method name.
        """
        return self.page.get_by_test_id("method-checklist").get_by_role("checkbox", name=name, exact=True)

    def set_method(self, name: str, checked: bool) -> None:
        """Set the checklist checkbox for *name* to *checked*.

        Args:
            name: Exact payment method name.
            checked: Desired state.
        """
        box = self.method_checkbox(name)
        if box.is_checked() != checked:
            box.click()

    def cap_notice_text(self) -> str:
        """Return the campaign cap notice text."""
        return self.page.get_by_test_id("cap-notice").inner_text()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def save_button(self) -> Locator:
        """Return the *Save* button."""
        return self.page.get_by_test_id("save-settings")

    def save_is_enabled(self) -> bool:
        """Return ``True`` when *Save* is enabled."""
        return self.save_button().is_enabled()

    def save(self) -> None:
        """Click *Save* and wait for the saved confirmation."""
        self.save_button().click()
        expect(self.page.get_by_test_id("settings-saved")).to_be_visible(timeout=20_000)
        self.wait_for_loading()

    def disable_button(self) -> Locator:
        """Return the *Disable* button (rendered only while enabled)."""
        return self.page.get_by_test_id("disable-public-orders")

    def disable(self) -> None:
        """Click *Disable* and wait for the settings to reload."""
        self.disable_button().click()
        self.wait_for_loading()

    def rotate_token(self) -> None:
        """Click *Rotate link* and wait for the settings reload to repaint the share view."""
        self.page.get_by_test_id("rotate-token").click()
        self.wait_for_loading()

    def wait_for_share_url_differs_from(self, previous: str, timeout: int = 20_000) -> str:
        """Poll the share field until it shows a URL other than *previous*.

        Args:
            previous: The URL that must be replaced.
            timeout: Maximum wait in milliseconds. Defaults to 20 000.

        Returns:
            The new share URL.

        Raises:
            AssertionError: When the field never changes within *timeout*.
        """
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            current = self.share_url()
            if current and current != previous:
                return current
            self.page.wait_for_timeout(500)
        raise AssertionError(f"Share URL did not change from {previous!r} within {timeout}ms")

    # ------------------------------------------------------------------
    # Share view
    # ------------------------------------------------------------------

    def share_view_is_visible(self) -> bool:
        """Return ``True`` when the *Share link* section is rendered."""
        return self.page.get_by_role("heading", name="Share link").is_visible()

    def share_url(self) -> str:
        """Return the share URL shown in the read-only field (empty when absent)."""
        field = self.page.get_by_label("Public order share URL")
        if field.count() == 0:
            return ""
        return field.input_value()

    def share_qr(self) -> Locator:
        """Return the share-view QR image."""
        return self.page.get_by_alt_text("Public order share QR code")

    def copy_share_url(self) -> str:
        """Click *Copy* and return the clipboard text.

        The browser context must hold the ``clipboard-read`` permission for the
        site origin; :meth:`grant_clipboard_permissions` does that.
        """
        self.page.get_by_test_id("copy-share-url").click()
        self.page.wait_for_timeout(300)
        return str(self.page.evaluate("() => navigator.clipboard.readText()"))

    def grant_clipboard_permissions(self) -> None:
        """Grant clipboard read/write to the current page origin."""
        parsed = urlparse(self.page.url)
        self.page.context.grant_permissions(
            ["clipboard-read", "clipboard-write"],
            origin=f"{parsed.scheme}://{parsed.netloc}",
        )

    def open_fullscreen_qr(self) -> None:
        """Click the full-screen QR action."""
        self.page.get_by_test_id("fullscreen-qr").click()

    def fullscreen_qr(self) -> Locator:
        """Return the enlarged QR image inside the full-screen dialog."""
        return self.page.get_by_test_id("fullscreen-qr-dialog").get_by_alt_text("Public order share QR code, enlarged")

    def close_fullscreen_qr(self) -> None:
        """Close the full-screen QR dialog."""
        self.page.keyboard.press("Escape")
        expect(self.page.get_by_test_id("fullscreen-qr-dialog")).to_be_hidden(timeout=10_000)


class PublicOrderPage(BasePage):
    """Anonymous buyer page at ``/o/{profileId}/{token}``."""

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto_share_url(self, share_url: str) -> None:
        """Hard-load the share URL *share_url*.

        Args:
            share_url: Absolute ``/o/...`` URL as the seller's share view shows it.
        """
        self.page.goto(share_url)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_unavailable(self) -> bool:
        """Return ``True`` when the not-available state is rendered."""
        return self.page.get_by_text(UNAVAILABLE_TITLE).is_visible()

    def seller_name(self) -> str:
        """Return the seller name heading rendered from the offer."""
        return self.page.locator("h4").first.inner_text()

    def campaign_name(self) -> str:
        """Return the campaign name line rendered from the offer."""
        return self.page.locator("h4 + p").first.inner_text()

    def product_names(self) -> list[str]:
        """Return the product names in the picker, in render order.

        Each row renders the product name as the first ``<p>`` inside the row.
        """
        return [row.locator("p").first.inner_text() for row in self.page.locator("[data-testid^='product-row-']").all()]

    def product_row_count(self) -> int:
        """Return the number of product rows in the picker."""
        return self.page.locator("[data-testid^='product-row-']").count()

    def set_quantity(self, product_name: str, quantity: int) -> None:
        """Set the quantity field for the product *product_name*.

        Args:
            product_name: Exact product name as rendered.
            quantity: Quantity to enter.
        """
        self.page.get_by_label(f"Quantity for {product_name}").fill(str(quantity))

    def estimated_total(self) -> str:
        """Return the estimated-total line."""
        return self.page.get_by_test_id("order-total").inner_text()

    def payment_method_names(self) -> list[str]:
        """Return the payment methods the buyer is offered, in offer order.

        The name is rendered inside the clickable label block, whose test id is
        ``payment-label-{name}``; the label text is the method name itself.
        """
        return self.page.locator("[data-testid^='payment-label-']").all_inner_texts()

    def payment_method_block(self, name: str) -> Locator:
        """Return the block for the payment method *name*.

        Args:
            name: Exact payment method name.
        """
        return self.page.get_by_test_id(f"payment-method-{name}")

    def select_payment_method(self, name: str) -> None:
        """Select the payment method *name* by clicking its label.

        Args:
            name: Exact payment method name.
        """
        self.page.get_by_test_id(f"payment-label-{name}").click()

    def payment_qr_image(self, name: str) -> Locator:
        """Return the seller's QR image for the selected method *name*.

        Args:
            name: Exact payment method name.
        """
        return self.page.get_by_alt_text(f"Payment QR code for {name}")

    def decoded_payment_link(self) -> Locator:
        """Return the decoded payment link rendered from the QR image."""
        return self.page.get_by_test_id("decoded-payment-link")

    def qr_no_link_hint(self) -> Locator:
        """Return the hint rendered when no link could be decoded."""
        return self.page.get_by_test_id("qr-no-link-hint")

    def no_qr_alert(self) -> Locator:
        """Return the *no QR was uploaded* alert for a method without an image."""
        return self.page.get_by_test_id("payment-no-qr")

    # ------------------------------------------------------------------
    # Buyer contact fields
    # ------------------------------------------------------------------

    def fill_contact(
        self,
        first_name: str,
        last_name: str,
        phone: str = "",
        email: str = "",
    ) -> None:
        """Fill the buyer contact fields.

        Args:
            first_name: First name value.
            last_name: Last name value.
            phone: Phone value; empty leaves the field untouched.
            email: Email value; empty leaves the field untouched.
        """
        self.page.get_by_label("First name").fill(first_name)
        self.page.get_by_label("Last name").fill(last_name)
        if phone:
            self.page.get_by_label("Phone", exact=True).fill(phone)
        if email:
            self.page.get_by_label("Email (optional)").fill(email)

    def first_name_value(self) -> str:
        """Return the current *First name* field value (used to prove form retention)."""
        return self.page.get_by_label("First name").input_value()

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    def submit(self) -> None:
        """Click *Place order*."""
        self.page.get_by_test_id("submit-order").click()

    def no_email_dialog_is_visible(self) -> bool:
        """Return ``True`` when the no-email confirmation dialog is open."""
        return self.page.get_by_text("You will not receive a confirmation email.").is_visible()

    def no_email_go_back(self) -> None:
        """Click *Go back and add email*."""
        self.page.get_by_test_id("no-email-go-back").click()

    def no_email_continue(self) -> None:
        """Click *Continue without email*."""
        self.page.get_by_test_id("no-email-continue").click()

    def success_is_visible(self) -> bool:
        """Return ``True`` when the order-success screen is rendered."""
        return self.page.get_by_test_id("public-order-success").is_visible()

    def order_reference(self) -> str:
        """Return the order reference shown on the success screen."""
        return self.page.get_by_test_id("order-reference").inner_text()

    def receipt_link_href(self) -> str:
        """Return the success screen's receipt link href (empty when absent)."""
        link = self.page.get_by_test_id("receipt-link")
        if link.count() == 0:
            return ""
        return link.get_attribute("href") or ""

    def confirmation_copy(self) -> str:
        """Return the confirmation-email copy from the success alert."""
        return self.page.get_by_test_id("public-order-success").locator(".MuiAlert-message p").nth(1).inner_text()

    # ------------------------------------------------------------------
    # Static page assertions
    # ------------------------------------------------------------------

    def robots_meta_content(self) -> str:
        """Return the ``robots`` meta content, or ``""`` when absent."""
        return str(self.page.evaluate("() => document.querySelector('meta[name=\"robots\"]')?.content ?? ''"))


class PublicReceiptPage(BasePage):
    """Anonymous buyer receipt page at ``/r/{campaignId}/{orderSuffix}/{receiptToken}``."""

    def goto_receipt_url(self, receipt_url: str) -> None:
        """Hard-load the receipt URL *receipt_url*.

        Args:
            receipt_url: Absolute three-segment receipt URL.
        """
        self.page.goto(receipt_url)
        self.wait_for_loading()

    def is_unavailable(self) -> bool:
        """Return ``True`` when the not-available state is rendered."""
        return self.page.get_by_text(UNAVAILABLE_TITLE).is_visible()

    def status_chip_text(self) -> str:
        """Return the status chip label."""
        return self.page.get_by_test_id("receipt-status-chip").inner_text()

    def line_item_count(self) -> int:
        """Return the number of rendered line-item rows."""
        return self.page.locator("table tbody tr").count()

    def robots_meta_content(self) -> str:
        """Return the ``robots`` meta content, or ``""`` when absent."""
        return str(self.page.evaluate("() => document.querySelector('meta[name=\"robots\"]')?.content ?? ''"))
