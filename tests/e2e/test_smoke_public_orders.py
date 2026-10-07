"""E2E smoke for public order placement (spec section 10.5).

Seller side runs as the owner test user; buyer side runs in a **fresh
unauthenticated browser context**, because the share token in the URL is the
whole authorization and the buyer page must never carry a session.

Test ordering
-------------
The suite mutates one shared configuration, so the tests below run in file
order and later ones read what earlier ones left behind (the same
``_module_state`` convention ``test_smoke_auth_boundary.py`` uses):

1. the acknowledgement block is asserted on its own never-enabled profile, so it
   does not depend on which suite enabled the shared profile first;
2. the share view, the buyer offer render, the QR/method assertions and the
   method un-check all need the feature enabled with both methods;
3. the rotation test replaces the share URL in :data:`_po_state` and records the
   superseded URL, and every later buyer test reads the current one;
4. the disable test runs last — it is the only test that makes the shared share
   URL unusable.

Known gaps (deliberate, not oversights)
---------------------------------------
Four spec items cannot be asserted against the shipped code and are marked at
their sites below. The full evidence for each is in this PR's "Known gaps"
section: ``publicCreateOrder`` and ``publicGetOrderReceipt`` exist in
``tofu/application/schema/schema.graphql`` but have **no resolver anywhere**, so
slice-plan items 5 (public write pipeline) and 6 (receipt read + email) are not
shipped; ``UpdateOrderInput`` has no ``status`` field and no seller UI action
exists (item 7); the report types and exports carry no ``customerEmail`` column
(item 9). The buyer submit/receipt tests below are present with an explicit
``pytest.skip`` line naming the missing slice; that line is what has to be
deleted when the resolvers land, and each skip reason says so.
"""

import re
from collections.abc import Generator
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from tests.e2e.pages.order_page import OrderPage
from tests.e2e.pages.public_order_page import (
    NOINDEX_CONTENT,
    UNAVAILABLE_TITLE,
    PublicOrderPage,
    PublicOrderSettingsPage,
    PublicReceiptPage,
)
from tests.e2e.utils.public_orders import (
    PLAIN_PAYMENT_METHOD,
    QR_PAYMENT_METHOD,
    base_url,
    create_owned_profile,
    is_site_origin,
    unique_suffix,
)

# ---------------------------------------------------------------------------
# Constants mirrored from the frontend (spec 3.1 / constants/publicOrders.ts)
# ---------------------------------------------------------------------------

#: The two enable-time acknowledgements, verbatim from
#: ``frontend/src/constants/publicOrders.ts``.  Duplicated on purpose: the smoke
#: test must fail when the copy changes without the spec's disclosure decision
#: being revisited, which a runtime import of the constant could never do.
ACK_PAYMENT_TEXT = (
    "KernelWorx does not collect payment. You are responsible for verifying "
    "that the buyer has actually paid before fulfilling the order."
)
ACK_DISCLOSURE_TEXT = (
    "Buyers will see the QR image you uploaded for any enabled payment method. "
    "Public buyers' name, contact details, and email become visible to people "
    "you share this profile with and appear in unit reports/exports."
)

#: A payment method the seller never allowlisted; the buyer must not see it even
#: though the settings checklist always offers it.
NEVER_ALLOWED_METHOD = "Check"

#: Skip reason shared by the buyer submit/receipt tests. Delete the ``pytest.skip``
#: call in those tests (not this constant) once the two resolvers ship.
_WRITE_PATH_MISSING = (
    "spec 10.5 buyer flow needs publicCreateOrder/publicGetOrderReceipt, which have no resolver "
    "anywhere in the repo (schema-only): slice-plan item 5 'Public write pipeline' and item 6 "
    "'Receipt read + email' have not shipped — remove this skip when they land"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _po_state(public_orders_setup: dict[str, str]) -> dict[str, str]:
    """Mutable per-module copy of the session's public-order fixture data.

    The rotation test writes a new ``share_url``/``share_token`` here and keeps
    the superseded pair as ``old_share_url``/``old_share_token``, so later tests
    read the current link without touching the session fixture other suites use.
    """
    return dict(public_orders_setup)


@pytest.fixture
def buyer_page(browser: Browser) -> Generator[Page, None, None]:
    """Yield a Page in a fresh, never-authenticated browser context.

    A separate context (not the ``page`` fixture) is the point: the buyer must
    hold no Cognito session, no cookies and no localStorage.
    """
    context: BrowserContext = browser.new_context(ignore_https_errors=True)
    try:
        yield context.new_page()
    finally:
        context.close()


# ---------------------------------------------------------------------------
# Seller side — enablement and the share view (items 1-3, 5)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_acknowledgement_block_requires_both_checks(owner_page: Page) -> None:
    """Both warning texts render, and Save stays disabled until both are checked.

    Runs on its own never-enabled profile: the block renders only while the
    stored acknowledgement version lags the current constant, so the shared
    fixture profile (already enabled) can no longer show it.
    """
    suffix = unique_suffix()
    profile_id = create_owned_profile(owner_page, f"PO Ack {suffix}")

    settings = PublicOrderSettingsPage(owner_page)
    settings.goto(profile_id)
    settings.set_enabled(True)

    expect(settings.page.get_by_test_id("ack-block")).to_be_visible(timeout=10_000)
    assert settings.ack_heading() == "Before you turn this on"

    rendered = " ".join(settings.ack_texts())
    assert ACK_PAYMENT_TEXT in rendered, f"payment-liability acknowledgement missing; rendered: {rendered!r}"
    assert ACK_DISCLOSURE_TEXT in rendered, f"buyer-PII disclosure missing; rendered: {rendered!r}"

    assert not settings.save_is_enabled(), "Save must be disabled with neither acknowledgement checked"
    settings.check_ack(0)
    assert not settings.save_is_enabled(), "Save must stay disabled with only one acknowledgement checked"
    settings.check_ack(1)
    assert settings.save_is_enabled(), "Save must enable once both acknowledgements are checked"


@pytest.mark.smoke
def test_share_view_renders_url_and_qr(owner_page: Page, _po_state: dict[str, str]) -> None:
    """The saved configuration reads back: campaign, both methods, cap line, URL + QR."""
    settings = PublicOrderSettingsPage(owner_page)
    settings.goto(_po_state["profile_id"])

    assert settings.enable_switch().is_checked(), "The enable switch must read back as on"
    assert settings.method_checkbox(QR_PAYMENT_METHOD).is_checked(), f"{QR_PAYMENT_METHOD} must be allowlisted"
    assert settings.method_checkbox(PLAIN_PAYMENT_METHOD).is_checked(), f"{PLAIN_PAYMENT_METHOD} must be allowlisted"
    assert settings.cap_notice_text().startswith("0 of 500"), (
        f"Cap notice must open at zero of the 500 cap; got: {settings.cap_notice_text()!r}"
    )

    assert settings.share_view_is_visible(), "Share link section must render while enabled"
    share_url = settings.share_url()
    assert share_url == _po_state["share_url"], "Share URL must be stable across reads (the token is not re-rolled)"
    assert "#" not in share_url, f"Share URL must carry no fragment delimiter; got: {share_url!r}"
    assert urlparse(share_url).path.startswith("/o/"), f"Share URL must be an /o/... path; got: {share_url!r}"
    expect(settings.share_qr()).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_share_view_survives_navigation_copy_and_fullscreen(owner_page: Page, _po_state: dict[str, str]) -> None:
    """Post-creation retrieval: away and back re-renders the same URL and QR.

    The share view is rebuilt client-side from the ``shareToken`` the settings
    read returns, so a seller who navigates away and back (or reloads) gets the
    same scannable link — no stored image and no server round trip.
    """
    settings = PublicOrderSettingsPage(owner_page)
    settings.goto(_po_state["profile_id"])
    settings.page.goto(f"{base_url()}/scouts")
    settings.goto(_po_state["profile_id"])

    assert settings.share_url() == _po_state["share_url"], "Share URL must survive navigating away and back"
    expect(settings.share_qr()).to_be_visible(timeout=10_000)

    settings.grant_clipboard_permissions()
    copied = settings.copy_share_url()
    assert copied == _po_state["share_url"], f"Copy must put the share URL on the clipboard; got: {copied!r}"

    settings.open_fullscreen_qr()
    expect(settings.fullscreen_qr()).to_be_visible(timeout=10_000)
    settings.close_fullscreen_qr()


# ---------------------------------------------------------------------------
# Buyer side — the offer page (items 6-7)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_offer_renders_seller_products_and_only_allowed_methods(buyer_page: Page, _po_state: dict[str, str]) -> None:
    """An anonymous buyer who opens the share URL sees the offer, not a login wall."""
    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(_po_state["share_url"])

    assert not offer.is_unavailable(), (
        f"Valid share URL must render the offer; got the not-available state at {offer.page.url}"
    )
    assert offer.seller_name() == _po_state["seller_name"], (
        f"Seller name heading must be {_po_state['seller_name']!r}; got {offer.seller_name()!r}"
    )
    assert _po_state["campaign_name"] in offer.campaign_name(), (
        f"Campaign line must name the anchor campaign; got {offer.campaign_name()!r}"
    )
    assert offer.product_row_count() >= 1, "The offer must list the anchor catalog's products"

    methods = offer.payment_method_names()
    assert QR_PAYMENT_METHOD in methods, f"Allowlisted QR method missing from the buyer's list: {methods}"
    assert PLAIN_PAYMENT_METHOD in methods, f"Allowlisted plain method missing from the buyer's list: {methods}"
    assert NEVER_ALLOWED_METHOD not in methods, (
        f"A method the seller never allowlisted must not reach the buyer; got: {methods}"
    )


@pytest.mark.smoke
def test_qr_method_renders_presigned_image_with_referrer_guard(buyer_page: Page, _po_state: dict[str, str]) -> None:
    """Selecting the QR method paints the seller's QR from a pre-signed URL.

    ``referrerPolicy="no-referrer"`` and ``crossOrigin="anonymous"`` are asserted
    as attributes, not behavior: the first keeps the capability-bearing ``/o/``
    path out of S3 access logs, the second is what lets the canvas read in
    ``lib/qrDecode.ts`` run at all. Both hold on every environment, including
    ephemeral where the baked CSP blocks the image *load*.
    """
    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(_po_state["share_url"])
    offer.select_payment_method(QR_PAYMENT_METHOD)

    image = offer.payment_qr_image(QR_PAYMENT_METHOD)
    expect(image).to_be_attached(timeout=10_000)
    src = image.get_attribute("src") or ""
    parsed = urlparse(src)
    assert parsed.scheme == "https", f"Pre-signed QR URL must be https; got: {src!r}"
    assert parsed.netloc.endswith(".amazonaws.com"), f"Pre-signed QR URL must point at S3; got: {src!r}"
    assert "X-Amz-Signature" in src, f"Pre-signed QR URL must be signed; got: {src!r}"
    assert image.get_attribute("referrerPolicy") == "no-referrer", "QR <img> must not leak the page URL as a referrer"
    assert image.get_attribute("crossOrigin") == "anonymous", "QR <img> must be CORS-readable for the decode"


@pytest.mark.smoke
def test_qr_image_decodes_to_https_link_with_rel(buyer_page: Page, _po_state: dict[str, str]) -> None:
    """The client-side decode renders the payment link with ``rel`` hardening.

    Dev/prod only, stated rather than silently skipped: the CSP baked into the
    frontend build lists only the dev/prod exports-bucket hosts in ``img-src``
    (#440 accepted gap), so on an ephemeral run the image never loads and no
    decode can happen. The attribute-level half of this is the test above.
    """
    if not is_site_origin():
        pytest.skip(
            "QR paint and the decoded-link check need the browser to load the pre-signed exports-bucket "
            f"image; the baked CSP img-src omits the ephemeral bucket (base URL {base_url()})"
        )

    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(_po_state["share_url"])
    offer.select_payment_method(QR_PAYMENT_METHOD)

    link = offer.decoded_payment_link()
    expect(link).to_be_visible(timeout=20_000)
    href = link.get_attribute("href") or ""
    assert urlparse(href).scheme == "https", f"Decoded payment link must be https; got: {href!r}"
    assert link.get_attribute("rel") == "noopener noreferrer", (
        f"Decoded payment link must carry rel='noopener noreferrer'; got: {link.get_attribute('rel')!r}"
    )


@pytest.mark.smoke
def test_method_without_qr_shows_no_image_and_no_link(buyer_page: Page, _po_state: dict[str, str]) -> None:
    """A method with no uploaded QR shows the honest hint, never a broken image."""
    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(_po_state["share_url"])
    offer.select_payment_method(PLAIN_PAYMENT_METHOD)

    expect(offer.no_qr_alert()).to_be_visible(timeout=10_000)
    assert buyer_page.locator(f"img[alt='Payment QR code for {PLAIN_PAYMENT_METHOD}']").count() == 0, (
        "A method without an uploaded QR must not render an image"
    )


@pytest.mark.smoke
def test_unchecking_a_method_updates_the_buyer_view(
    owner_page: Page,
    buyer_page: Page,
    _po_state: dict[str, str],
) -> None:
    """Un-checking one method and saving removes it from the buyer's list.

    The buyer-visible list is the settings blob read through the offer, so this
    is the shared-state half of the contract: no cache, no second write.
    """
    settings = PublicOrderSettingsPage(owner_page)
    settings.goto(_po_state["profile_id"])
    settings.set_method(PLAIN_PAYMENT_METHOD, False)
    settings.save()

    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(_po_state["share_url"])
    methods = offer.payment_method_names()
    assert QR_PAYMENT_METHOD in methods, f"Still-allowlisted method vanished: {methods}"
    assert PLAIN_PAYMENT_METHOD not in methods, f"Un-allowlisted method still reaches the buyer: {methods}"


@pytest.mark.smoke
def test_rotating_the_token_replaces_the_share_url(
    owner_page: Page,
    buyer_page: Page,
    _po_state: dict[str, str],
) -> None:
    """Rotate shows the new URL in the share view and kills the old one."""
    settings = PublicOrderSettingsPage(owner_page)
    settings.goto(_po_state["profile_id"])
    old_url = _po_state["share_url"]
    settings.rotate_token()
    new_url = settings.wait_for_share_url_differs_from(old_url)
    assert new_url and new_url != old_url, f"Rotate must produce a new share URL; got: {new_url!r}"
    _po_state["old_share_url"] = old_url
    _po_state["old_share_token"] = _po_state["share_token"]
    _po_state["share_url"] = new_url
    _po_state["share_token"] = new_url.rstrip("/").rsplit("/", 1)[-1]

    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(new_url)
    assert not offer.is_unavailable(), "The rotated share URL must render the offer"

    offer.goto_share_url(old_url)
    assert offer.is_unavailable(), "The superseded share URL must render the not-available state"


# ---------------------------------------------------------------------------
# Negative and static page assertions (items 10, 13)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_tampered_share_token_renders_not_available_without_leaking(
    buyer_page: Page,
    _po_state: dict[str, str],
) -> None:
    """A tampered token yields the generic not-available page with no seller data.

    The server answers a bad token, a disabled profile, a stale campaign and a
    deleted order with the identical NOT_FOUND, so the page must stay equally
    generic and must not disclose the seller name it looked up.
    """
    share_url = _po_state["share_url"]
    tampered = share_url.replace(_po_state["share_token"], "deadbeef" + _po_state["share_token"][:16])
    assert tampered != share_url, "Tampering must actually change the token segment"

    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(tampered)
    expect(offer.page.get_by_text(UNAVAILABLE_TITLE)).to_be_visible(timeout=10_000)

    body = offer.page.locator("body").inner_text()
    assert _po_state["seller_name"] not in body, "The not-available page must not disclose the seller name"
    assert _po_state["campaign_name"] not in body, "The not-available page must not disclose the campaign name"


@pytest.mark.smoke
def test_public_pages_carry_noindex_and_robots_disallow(page: Page, _po_state: dict[str, str]) -> None:
    """``robots.txt`` disallows ``/o/`` and ``/r/`` and both pages carry ``noindex``.

    Capability URLs are authorization in the path: an indexed copy is a live
    order link handed to everyone who finds the search result.
    """
    page.goto(f"{base_url()}/robots.txt")
    robots = page.inner_text("body")
    assert "Disallow: /o/" in robots, f"robots.txt must disallow /o/; got:\n{robots}"
    assert "Disallow: /r/" in robots, f"robots.txt must disallow /r/; got:\n{robots}"

    offer = PublicOrderPage(page)
    offer.goto_share_url(_po_state["share_url"])
    assert offer.robots_meta_content() == NOINDEX_CONTENT, (
        f"The offer page must carry the noindex meta; got: {offer.robots_meta_content()!r}"
    )

    receipt = PublicReceiptPage(page)
    receipt.goto_receipt_url(f"{base_url()}/r/probe-campaign/0001/deadbeef")
    assert receipt.robots_meta_content() == NOINDEX_CONTENT, (
        f"The receipt page must carry the noindex meta; got: {receipt.robots_meta_content()!r}"
    )


@pytest.mark.smoke
def test_share_token_never_reaches_console_output(buyer_page: Page, _po_state: dict[str, str]) -> None:
    """The share token never appears in console output.

    Console output is copied into bug reports, screenshots and CI logs; a
    capability URL printed there is a leaked link.
    """
    messages: list[str] = []
    buyer_page.on("console", lambda message: messages.append(f"{message.type}: {message.text}"))
    buyer_page.on("pageerror", lambda error: messages.append(f"pageerror: {error}"))

    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(_po_state["share_url"])
    offer.select_payment_method(QR_PAYMENT_METHOD)
    buyer_page.wait_for_timeout(2_000)

    token = _po_state["share_token"]
    leaked = [line for line in messages if token in line]
    assert not leaked, f"Share token leaked into console output: {leaked}"


@pytest.mark.smoke
def test_signed_in_user_opening_the_share_url_still_orders_anonymously(
    owner_page: Page,
    _po_state: dict[str, str],
) -> None:
    """A signed-in user who opens ``/o/...`` still gets the anonymous offer page.

    The public routes run on their own API-key-only Apollo client, so an
    existing session must neither be attached nor required. The deterministic
    half of this — asserting the request headers carry no ``Authorization`` — is
    the scripted check in spec 10.4.
    """
    offer = PublicOrderPage(owner_page)
    offer.goto_share_url(_po_state["share_url"])

    assert "/login" not in owner_page.url, f"The public route must not redirect a signed-in user; got {owner_page.url}"
    assert not offer.is_unavailable(), "A signed-in user must still see the offer"
    assert offer.seller_name() == _po_state["seller_name"]


# ---------------------------------------------------------------------------
# Seller after: the Orders page (item 11, authenticated half)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_authenticated_order_carries_no_public_badge_and_no_status_chip(
    owner_page: Page,
    _po_state: dict[str, str],
) -> None:
    """Authenticated order creation is unchanged: no source badge, no status chip.

    Historical and authenticated orders carry neither ``orderSource`` nor
    ``status`` (no backfill), so both cells must render the empty state.
    """
    customer = f"Auth Buyer {unique_suffix()}"
    orders = OrderPage(owner_page)
    orders.goto(_po_state["profile_id"], _po_state["campaign_id"])
    orders.create_order_first_product(customer, qty=1)
    assert orders.has_order(customer), f"Authenticated order for {customer!r} must appear in the orders list"

    row = owner_page.get_by_role("row").filter(has_text=customer).first
    expect(row).to_be_visible(timeout=10_000)
    assert row.locator("[data-testid='public-order-badge']").count() == 0, (
        "An authenticated order must not carry the public-order source badge"
    )
    assert row.locator("[data-testid='order-status-chip']").count() == 0, (
        "An authenticated order has no status and must not render a status chip"
    )

    # TODO(spec 10.5 item 11, public half): the public-order row's source badge,
    # buyer email and NEW status chip, and the "mark payment confirmed" flip to
    # CONFIRMED, are NOT asserted here. The badge/chip half needs slice-plan
    # item 5 (publicCreateOrder has no resolver, so no public order can exist);
    # the flip half needs item 7 (UpdateOrderInput has no `status` field and no
    # seller UI action exists). Both are listed in this PR's Known gaps section.


# ---------------------------------------------------------------------------
# Buyer submit and receipt (items 8-10) — present, explicitly skipped
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_buyer_submit_without_email_offers_the_choice_then_succeeds(
    buyer_page: Page, _po_state: dict[str, str]
) -> None:
    """No email -> dialog; "go back" keeps the form; "continue" -> success screen.

    Skipped: see :data:`_WRITE_PATH_MISSING`.
    """
    pytest.skip(_WRITE_PATH_MISSING)

    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(_po_state["share_url"])
    offer.set_quantity(offer.product_names()[0], 2)
    offer.fill_contact("Smoke", "Buyer", phone="5551234567")
    offer.select_payment_method(QR_PAYMENT_METHOD)
    offer.submit()

    expect(offer.page.get_by_test_id("no-email-go-back")).to_be_visible(timeout=10_000)
    offer.no_email_go_back()
    assert offer.first_name_value() == "Smoke", "Going back must preserve the filled form"

    offer.submit()
    offer.no_email_continue()
    expect(offer.page.get_by_test_id("public-order-success")).to_be_visible(timeout=20_000)
    assert offer.order_reference(), "The success screen must show the order reference"
    assert "No confirmation email was sent" in offer.confirmation_copy(), (
        f"No-email orders must say so plainly; got: {offer.confirmation_copy()!r}"
    )


@pytest.mark.smoke
def test_buyer_order_with_email_lands_and_reopens_the_same_receipt(
    buyer_page: Page,
    _po_state: dict[str, str],
) -> None:
    """An emailed order shows the honest send state and a working receipt link.

    Skipped: see :data:`_WRITE_PATH_MISSING`.  When it activates, the send state
    is environment-appropriate by design: ``confirmationEmailSent`` is false on
    ephemeral (the SES module is created with ``create = false`` there) and the
    dev copy is one of the two honest states until the one-time SES identity
    verification lands; either way the order row must have landed.
    """
    pytest.skip(_WRITE_PATH_MISSING)

    buyer_email = f"smoke+po{unique_suffix()}@example.com"
    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(_po_state["share_url"])
    offer.set_quantity(offer.product_names()[0], 1)
    offer.fill_contact("Smoke", "Emailed", phone="5551234567", email=buyer_email)
    offer.select_payment_method(PLAIN_PAYMENT_METHOD)
    offer.submit()

    expect(offer.page.get_by_test_id("public-order-success")).to_be_visible(timeout=20_000)
    href = offer.receipt_link_href()
    assert href and "#" not in href, f"Receipt link must be a split-segment URL with no '#'; got: {href!r}"
    assert re.search(r"/r/[^/]+/[^/]+/[^/]+$", urlparse(href).path), (
        f"Receipt link must be /r/<campaign>/<suffix>/<token>; got: {href!r}"
    )

    receipt = PublicReceiptPage(buyer_page)
    receipt.goto_receipt_url(href)
    assert not receipt.is_unavailable(), "The receipt URL must re-open the same receipt"
    assert receipt.line_item_count() >= 1, "The receipt must render its line items"
    assert receipt.status_chip_text() == "Awaiting payment confirmation", (
        f"A fresh public order reads NEW on the receipt; got: {receipt.status_chip_text()!r}"
    )


@pytest.mark.smoke
def test_tampered_receipt_token_renders_not_available(buyer_page: Page, _po_state: dict[str, str]) -> None:
    """A tampered receipt token yields the same generic not-available page.

    Skipped: see :data:`_WRITE_PATH_MISSING` (slice-plan item 6 owns
    ``publicGetOrderReceipt``).
    """
    pytest.skip(_WRITE_PATH_MISSING)

    receipt = PublicReceiptPage(buyer_page)
    bare_campaign_id = _po_state["campaign_id"].split("#", 1)[-1]
    receipt.goto_receipt_url(f"{base_url()}/r/{bare_campaign_id}/0001/deadbeefdeadbeefdeadbeefdeadbeef")
    expect(receipt.page.get_by_text(UNAVAILABLE_TITLE)).to_be_visible(timeout=10_000)


# ---------------------------------------------------------------------------
# Seller disables the feature (item 10) — last: it makes the share unusable
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_seller_disabling_public_orders_kills_the_share(
    owner_page: Page,
    buyer_page: Page,
    _po_state: dict[str, str],
) -> None:
    """Disabling public orders turns the live share URL into the not-available state."""
    settings = PublicOrderSettingsPage(owner_page)
    settings.goto(_po_state["profile_id"])
    expect(settings.disable_button()).to_be_visible(timeout=10_000)
    settings.disable()
    assert not settings.share_view_is_visible(), "The share view must disappear once disabled"

    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(_po_state["share_url"])
    assert offer.is_unavailable(), "A disabled profile's share URL must render the not-available state"
