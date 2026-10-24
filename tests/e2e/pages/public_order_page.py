"""Page objects for the public order surface (spec section 10.5, campaign-scoped).

Three routes share this module because they are one feature and one URL family:

* :class:`PublicOrderSettingsPage` — the seller's Public Orders section on the
  campaign settings tab (``/scouts/{profileId}/campaigns/{campaignId}/settings``).
* :class:`PublicOrderPage` — the anonymous buyer's ``/o/{campaignId}/{token}``
  offer page.
* :class:`PublicReceiptPage` — the anonymous buyer's
  ``/r/{campaignId}/{orderSuffix}/{receiptToken}`` receipt page.

Public orders are a CAMPAIGN-level setting (the spec's REV 7 amendment), so the
seller half lives on the campaign, not under Manage Scout, and the share URL is
``/o/<bare campaign id>/<token>``.

Navigation note
---------------
The buyer pages are loaded with a **hard** ``page.goto`` rather than
:meth:`BasePage.navigate`'s client-side ``pushState``. The ``pushState`` dance
exists only because a hard load of ``/login`` reaches Cognito's managed page
through the CloudFront ``/l*`` behavior; ``/o/`` and ``/r/`` are ordinary SPA
paths, and a hard load is the faithful test of them — it is what a buyer
scanning a QR code does, and it is what proves the route is not behind
``ProtectedRoute``. The settings page uses :meth:`BasePage.navigate` like every
other protected page object, so the Amplify session restore has settled before
the page reads its settings.

Mutation-completion note
------------------------
The campaign settings UI renders no spinner or success banner for the public
orders actions, so :meth:`PublicOrderSettingsPage._await_mutation` waits on the
GraphQL **response** for the operation it just triggered and asserts it carried
no errors. Polling a DOM flag would race the refetch and could read the
pre-mutation render.
"""

import json
import time
import urllib.parse
from collections.abc import Callable

from playwright.sync_api import Locator, expect

from .base_page import BasePage

#: Copy rendered by ``PublicPageUnavailable`` for every unusable link. The server
#: answers a bad token, a disabled campaign, a dead catalog and a deleted order
#: with the identical NOT_FOUND, so this one string is the whole not-available
#: state — and it must stay equally generic, disclosing none of those reasons.
UNAVAILABLE_TITLE = "This order link is not available."

#: ``frontend/src/components/NoIndexMeta.tsx`` — asserted on both public routes.
NOINDEX_CONTENT = "noindex"

#: The two enable-time acknowledgements, verbatim from
#: ``frontend/src/components/public/PublicSettingsAckCheckboxes.tsx``. Duplicated
#: on purpose: the smoke test must fail when the copy changes without the spec's
#: D4/D5 disclosure decisions being revisited, which importing the constant could
#: never do.
ACK_PAYMENT_TEXT = (
    "KernelWorx does not collect payment. You are responsible for verifying "
    "that the buyer has actually paid before fulfilling the order."
)
ACK_DISCLOSURE_TEXT = (
    "Buyers will see the QR image you uploaded for any enabled payment method. "
    "Public buyers' name, contact details, and email become visible to people "
    "you share this profile with and appear in unit reports/exports."
)


def _graphql_response_for(operation: str) -> Callable:
    """Return a predicate matching a GraphQL response whose body names *operation*."""

    def matches(response) -> bool:
        if "/graphql" not in response.url:
            return False
        body = response.request.post_data or ""
        return operation in body

    return matches


class PublicOrderSettingsPage(BasePage):
    """The Public Orders section of ``/scouts/{p}/campaigns/{c}/settings``."""

    _SETTINGS_SUFFIX: str = "/settings"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self, profile_id: str, campaign_id: str) -> None:
        """Open the campaign settings tab that carries the Public Orders section.

        Args:
            profile_id: Raw profile identifier (``PROFILE#…``); URL-encoded here.
            campaign_id: Raw campaign identifier (``CAMPAIGN#…``); URL-encoded here.
        """
        enc_profile = urllib.parse.quote(profile_id, safe="")
        enc_campaign = urllib.parse.quote(campaign_id, safe="")
        self.navigate(f"/scouts/{enc_profile}/campaigns/{enc_campaign}{self._SETTINGS_SUFFIX}")
        self.wait_for_loading()
        expect(self.section_heading()).to_be_visible(timeout=20_000)

    # ------------------------------------------------------------------
    # Section anchors
    # ------------------------------------------------------------------

    def section_heading(self) -> Locator:
        """Return the *Public Orders* section heading."""
        return self.page.get_by_role("heading", name="Public Orders")

    def share_heading(self) -> Locator:
        """Return the *Share Link for …* heading (rendered whenever a token exists)."""
        return self.page.get_by_role("heading", name="Share Link for")

    # ------------------------------------------------------------------
    # Acknowledgements
    # ------------------------------------------------------------------

    def _form_group_after_heading(self, heading: str) -> Locator:
        """Return the checkbox group rendered directly after the *heading*.

        The Public Orders section stacks five blocks, two of which are MUI
        checkbox groups (acknowledgements, then payment methods). Both render
        plain ``Checkbox`` controls with no ``data-testid``, so the block
        heading is the only stable way to scope one group out of the other -
        filtering on text alone would match both.

        Args:
            heading: Exact heading text (``Acknowledgements``,
                ``Allowed Payment Methods``, ``Order Capacity``).
        """
        return self.page.locator("h6", has_text=heading).locator(
            'xpath=following-sibling::*[contains(@class,"MuiFormGroup-root")][1]'
        )

    def ack_checkboxes(self) -> list[Locator]:
        """Return the two acknowledgement checkboxes in render order (payment, disclosure)."""
        return self._form_group_after_heading("Acknowledgements").get_by_role("checkbox").all()

    def check_ack(self, index: int) -> None:
        """Check the acknowledgement checkbox at *index* (0 = payment, 1 = disclosure).

        Args:
            index: Zero-based position in the acknowledgement group.
        """
        self.ack_checkboxes()[index].check()

    def ack_texts(self) -> list[str]:
        """Return the two acknowledgement labels in render order."""
        group = self._form_group_after_heading("Acknowledgements")
        return [label.inner_text() for label in group.locator("label.MuiFormControlLabel-root").all()]

    # ------------------------------------------------------------------
    # Payment-method checklist
    # ------------------------------------------------------------------

    def method_checkbox(self, name: str) -> Locator:
        """Return the checklist checkbox for the payment method *name*.

        Args:
            name: Exact payment method name.
        """
        return self._form_group_after_heading("Allowed Payment Methods").get_by_role("checkbox", name=name, exact=True)

    def set_method(self, name: str, checked: bool) -> None:
        """Set the checklist checkbox for *name* to *checked*.

        Args:
            name: Exact payment method name.
            checked: Desired state.
        """
        box = self.method_checkbox(name)
        if box.is_checked() != checked:
            box.click()

    def method_names(self) -> list[str]:
        """Return the payment-method labels the checklist offers, in render order."""
        group = self._form_group_after_heading("Allowed Payment Methods")
        return [label.inner_text() for label in group.locator("label.MuiFormControlLabel-root").all()]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _button(self, name: str) -> Locator:
        """Return the public-orders action button labelled *name*.

        Args:
            name: Exact button label (``Save``, ``Enable``, ``Disable``,
                ``Rotate Share Token``).
        """
        return self.page.get_by_role("button", name=name, exact=True)

    def enable_button(self) -> Locator:
        """Return the *Enable* button."""
        return self._button("Enable")

    def disable_button(self) -> Locator:
        """Return the *Disable* button."""
        return self._button("Disable")

    def save_button(self) -> Locator:
        """Return the *Save* button."""
        return self._button("Save")

    def rotate_button(self) -> Locator:
        """Return the *Rotate Share Token* button."""
        return self._button("Rotate Share Token")

    def _await_mutation(self, trigger: Callable[[], None], operation: str) -> None:
        """Click *trigger* and wait for the GraphQL response for *operation*.

        Args:
            trigger: Callable that performs the click.
            operation: GraphQL operation name to match in the request body.

        Raises:
            AssertionError: When the mutation returned GraphQL errors.
        """
        with self.page.expect_response(_graphql_response_for(operation), timeout=30_000) as info:
            trigger()
        payload = info.value.json()
        errors = payload.get("errors") or []
        assert not errors, f"{operation} failed: {errors}"
        self.wait_for_loading()

    def enable(self) -> None:
        """Click *Enable* and wait for the settings mutation to land."""
        self._await_mutation(self.enable_button().click, "updateCampaignPublicOrderSettings")

    def disable(self) -> None:
        """Click *Disable* and wait until the share view disappears.

        The share section renders only while a token exists, and the disable
        keeps the token, so the completion signal is the *enabled* state: the
        *Disable* button becoming disabled again (its rule is ``!enabled``).
        """
        self._await_mutation(self.disable_button().click, "updateCampaignPublicOrderSettings")
        expect(self.disable_button()).to_be_disabled(timeout=20_000)

    def save(self) -> None:
        """Click *Save* and wait for the settings mutation to land."""
        self._await_mutation(self.save_button().click, "updateCampaignPublicOrderSettings")

    def rotate_token(self) -> None:
        """Click *Rotate Share Token* and wait for the mutation to land."""
        self._await_mutation(self.rotate_button().click, "updateCampaignPublicOrderSettings")

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_enabled(self) -> bool:
        """Return ``True`` when public orders are enabled for this campaign.

        The *Disable* button is rendered disabled whenever the feature is off
        (``actionDisabled('disable', …)`` is ``!enabled``), which is the only
        enabled-state signal the section carries.
        """
        return self.disable_button().is_enabled()

    def enable_is_enabled(self) -> bool:
        """Return ``True`` when the *Enable* button is clickable.

        ``canEnable`` gates it on both acknowledgements plus a non-empty method
        list, so this is the assertion that the UI cannot submit a save the
        server would reject.
        """
        return self.enable_button().is_enabled()

    def cap_notice_text(self) -> str:
        """Return the *Order Capacity* count line ("You have received N out of M …")."""
        return self.page.locator("h6", has_text="Order Capacity").locator("xpath=following-sibling::*[1]").inner_text()

    # ------------------------------------------------------------------
    # Share view
    # ------------------------------------------------------------------

    def share_url(self) -> str:
        """Return the share URL text (empty when the share view is absent)."""
        field = self.page.get_by_test_id("share-url")
        if field.count() == 0:
            return ""
        return field.inner_text().strip()

    def share_qr(self) -> Locator:
        """Return the share-view QR image."""
        return self.page.get_by_test_id("share-qr")

    def copy_share_url(self) -> str:
        """Click *Copy Link* and return the clipboard text.

        The browser context must hold the ``clipboard-read`` permission for the
        site origin; :meth:`grant_clipboard_permissions` does that.
        """
        self.page.get_by_role("button", name="Copy Link").click()
        expect(self.page.get_by_test_id("copy-copied")).to_be_visible(timeout=10_000)
        self.page.wait_for_timeout(200)
        return str(self.page.evaluate("() => navigator.clipboard.readText()"))

    def grant_clipboard_permissions(self) -> None:
        """Grant clipboard read/write to the current page origin."""
        parsed = urllib.parse.urlparse(self.page.url)
        self.page.context.grant_permissions(
            ["clipboard-read", "clipboard-write"],
            origin=f"{parsed.scheme}://{parsed.netloc}",
        )

    def open_fullscreen_qr(self) -> None:
        """Click the *Fullscreen QR* action."""
        self.page.get_by_role("button", name="Fullscreen QR").click()

    def fullscreen_qr(self) -> Locator:
        """Return the enlarged QR image inside the full-screen dialog."""
        return self.page.get_by_test_id("fullscreen-share-qr")

    def close_fullscreen_qr(self) -> None:
        """Close the full-screen QR dialog."""
        self.page.keyboard.press("Escape")
        expect(self.fullscreen_qr()).to_be_hidden(timeout=10_000)

    def wait_for_share_url_differs_from(self, previous: str, timeout: int = 20_000) -> str:
        """Poll the share view until it shows a URL other than *previous*.

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


class PublicOrderPage(BasePage):
    """Anonymous buyer page at ``/o/{campaignId}/{token}``."""

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto_share_url(self, share_url: str) -> None:
        """Hard-load the share URL *share_url*.

        Args:
            share_url: Absolute ``/o/...`` URL exactly as the seller's share view shows it.
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
        """Return the campaign name line rendered under the seller heading."""
        return self.page.locator("h4 ~ p").first.inner_text()

    def product_names(self) -> list[str]:
        """Return the product names in the picker, in render order."""
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
        """Return the payment methods the buyer is offered, in offer order."""
        return self.page.locator("[data-testid^='payment-label-']").all_inner_texts()

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
        return self.page.get_by_test_id("public-order-success").locator(".MuiAlert-message p").inner_text()

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

    def total_label(self) -> str:
        """Return the ``Total (<payment method>)`` label line."""
        return self.page.locator("p", has_text="Total (").first.inner_text()

    def robots_meta_content(self) -> str:
        """Return the ``robots`` meta content, or ``""`` when absent."""
        return str(self.page.evaluate("() => document.querySelector('meta[name=\"robots\"]')?.content ?? ''"))


def parse_graphql_payload(response) -> dict:
    """Decode a GraphQL response body, tolerating a non-JSON transport error.

    Args:
        response: A Playwright ``Response`` for a ``/graphql`` request.

    Returns:
        The decoded body, or a dict carrying the raw text under ``raw`` when the
        body is not JSON (an HTTP-layer refusal carries a plain body).
    """
    try:
        return json.loads(response.text())
    except ValueError, TypeError:
        return {"raw": response.text()}
