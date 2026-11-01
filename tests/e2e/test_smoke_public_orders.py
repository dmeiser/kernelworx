"""E2E smoke for public order placement (spec section 10.5, campaign-scoped).

Seller side runs as the owner test user on the campaign's settings tab; buyer
side runs in a **fresh unauthenticated browser context**, because the share
token in the URL is the whole authorization and the buyer page must never carry
a session.

Test ordering
-------------
The suite mutates one shared configuration, so the tests below run in file
order and later ones read what earlier ones left behind (the same
``_module_state`` convention ``test_smoke_auth_boundary.py`` uses):

1. the acknowledgement block is asserted on its own never-enabled campaign, so
   it does not depend on which suite enabled the shared campaign first;
2. the share view, the buyer offer render, the QR/method assertions and the
   method un-check all need the feature enabled with both methods;
3. the rotation test replaces the share URL in :data:`_po_state` and records the
   superseded URL, and every later buyer test reads the current one;
4. the two submit tests create the orders the OrdersPage test then reads;
5. the disable test runs last — it is the only test that makes the shared share
   URL unusable.

Environment honesty
-------------------
Two spec items are environment-conditional and are stated at their sites rather
than silently skipped:

* the QR *paint* and the client-side *decoded link* need the browser to load a
  pre-signed exports-bucket image, and the CSP baked into the frontend build
  lists only the dev/prod exports hosts in ``img-src`` (#440 accepted gap), so
  both are skipped explicitly on an ephemeral (localhost preview) run;
* ``confirmationEmailSent`` is true only where SES is configured **and** the
  buyer address is verified in the sending account's SES sandbox. Ephemeral
  instantiates the SES module not at all; a deployed site rejects a recipient
  that is not individually verified. Both cases assert the honest "the email did
  not go out, the order did" copy. The send-succeeded branch runs when
  ``E2E_SES_TEST_RECIPIENT`` names a verified recipient (wired from the
  ``E2E_SES_TEST_RECIPIENT`` repository variable in the deploy smoke job).

Known gaps (deliberate, not oversights)
---------------------------------------
Spec 10.5 item 11 asks for the public order's **source badge** and **buyer email
column** on the Orders page. Neither exists in the shipped frontend: the
``Order`` GraphQL type exposes neither ``orderSource`` nor ``customerEmail``
(only the report types carry ``customerEmail``), and ``OrdersPage`` renders no
badge for them. The status chip and the "confirm payment" action — the halves
that do ship — are asserted below; the badge/email halves are marked at the site
rather than faked.
"""

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Generator
from urllib.parse import parse_qsl, urljoin, urlparse

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from tests.e2e.conftest import _attach_console_log, _dump_console_log_on_failure
from tests.e2e.pages.order_page import OrderPage
from tests.e2e.pages.public_order_page import (
    ACK_DISCLOSURE_TEXT,
    ACK_PAYMENT_TEXT,
    NOINDEX_CONTENT,
    UNAVAILABLE_TITLE,
    PublicOrderPage,
    PublicOrderSettingsPage,
    PublicReceiptPage,
)
from tests.e2e.utils.public_orders import (
    NEVER_ALLOWED_METHOD,
    PLAIN_PAYMENT_METHOD,
    QR_PAYMENT_METHOD,
    base_url,
    create_active_campaign,
    is_site_origin,
    unique_suffix,
)

#: Setting ``E2E_SES_TEST_RECIPIENT`` to an address that is verified in the
#: sending account's SES sandbox switches the emailed-order test onto the send
#: *succeeded* branch. Without it the test uses a random unverified address, and
#: the honest state is "the email did not go out, the order did" — asserted as
#: such, not skipped. The account is still in the SES sandbox (see
#: ``tofu/application/modules/ses/main.tf``), so only individually verified
#: recipients are deliverable there.
_RECIPIENT_ENV: str = "E2E_SES_TEST_RECIPIENT"


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
def buyer_page(browser: Browser, request: pytest.FixtureRequest) -> Generator[Page, None, None]:
    """Yield a Page in a fresh, never-authenticated browser context.

    A separate context (not the ``page`` fixture) is the point: the buyer must
    hold no Cognito session, no cookies and no localStorage.
    """
    context: BrowserContext = browser.new_context(ignore_https_errors=True)
    console_log: list[str] = []
    try:
        page = context.new_page()
        _attach_console_log(page, console_log)
        yield page
    finally:
        _dump_console_log_on_failure(request, console_log)
        context.close()


# ---------------------------------------------------------------------------
# Seller side — enablement and the share view (items 1-3, 5)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_acknowledgements_gate_the_enable_button(owner_page: Page, _po_state: dict[str, str]) -> None:
    """Both warning texts render, and Enable stays disabled until they are checked.

    Runs on its own never-enabled campaign: the acknowledgement requirement
    renders only while the stored acknowledgement version lags the current
    constant, so the shared fixture campaign (already enabled) can no longer
    show it.
    """
    campaign_name = f"PO Ack {unique_suffix()}"
    campaign_id = create_active_campaign(owner_page, _po_state["profile_id"], campaign_name)

    settings = PublicOrderSettingsPage(owner_page)
    settings.goto(_po_state["profile_id"], campaign_id)

    rendered = " ".join(settings.ack_texts())
    assert ACK_PAYMENT_TEXT in rendered, f"payment-liability acknowledgement missing; rendered: {rendered!r}"
    assert ACK_DISCLOSURE_TEXT in rendered, f"buyer-PII disclosure missing; rendered: {rendered!r}"

    assert not settings.enable_is_enabled(), "Enable must be disabled with neither acknowledgement checked"
    settings.check_ack(0)
    assert not settings.enable_is_enabled(), "Enable must stay disabled with only one acknowledgement checked"
    settings.check_ack(1)
    assert not settings.enable_is_enabled(), "Enable must stay disabled with no payment method allowlisted"
    settings.set_method(PLAIN_PAYMENT_METHOD, True)
    assert settings.enable_is_enabled(), "Enable must become clickable with both acknowledgements and one method"

    # Negative half of the same contract: un-checking one acknowledgement puts
    # the gate back up.
    settings.ack_checkboxes()[1].uncheck()
    assert not settings.enable_is_enabled(), "Enable must go back to disabled when an acknowledgement is cleared"


@pytest.mark.smoke
def test_share_view_renders_url_and_qr(owner_page: Page, _po_state: dict[str, str]) -> None:
    """The saved configuration reads back: both methods, the cap line, URL + QR."""
    settings = PublicOrderSettingsPage(owner_page)
    settings.goto(_po_state["profile_id"], _po_state["campaign_id"])

    assert settings.is_enabled(), "The campaign must read back as enabled"
    assert settings.method_checkbox(QR_PAYMENT_METHOD).is_checked(), f"{QR_PAYMENT_METHOD} must be allowlisted"
    assert settings.method_checkbox(PLAIN_PAYMENT_METHOD).is_checked(), f"{PLAIN_PAYMENT_METHOD} must be allowlisted"
    assert settings.cap_notice_text().startswith("You have received 0 out of 500"), (
        f"Cap notice must open at zero of the 500 cap; got: {settings.cap_notice_text()!r}"
    )

    share_url = settings.share_url()
    assert share_url == _po_state["share_url"], "Share URL must be stable across reads (the token is not re-rolled)"
    assert "#" not in share_url, f"Share URL must carry no fragment delimiter; got: {share_url!r}"
    parsed = urlparse(share_url)
    assert parsed.path.startswith("/o/"), f"Share URL must be an /o/... path; got: {share_url!r}"
    # Campaign-scoped keying (REV 7): the first /o/ segment is the bare campaign id.
    assert parsed.path.split("/")[2] == _po_state["campaign_id"].split("#", 1)[-1], (
        f"Share URL must carry the bare campaign id; got: {share_url!r}"
    )
    expect(settings.share_qr()).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_share_view_survives_navigation_copy_and_fullscreen(owner_page: Page, _po_state: dict[str, str]) -> None:
    """Post-creation retrieval: away and back re-renders the same URL and QR.

    The share view is rebuilt client-side from the ``shareToken`` the settings
    read returns, so a seller who navigates away and back (or reloads) gets the
    same scannable link — no stored image and no second write.
    """
    settings = PublicOrderSettingsPage(owner_page)
    settings.goto(_po_state["profile_id"], _po_state["campaign_id"])
    settings.page.goto(f"{base_url()}/scouts")
    settings.goto(_po_state["profile_id"], _po_state["campaign_id"])

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
        f"Campaign line must name the campaign; got {offer.campaign_name()!r}"
    )
    assert offer.product_row_count() >= 1, "The offer must list the campaign catalog's products"

    methods = offer.payment_method_names()
    assert QR_PAYMENT_METHOD in methods, f"Allowlisted QR method missing from the buyer's list: {methods}"
    assert PLAIN_PAYMENT_METHOD in methods, f"Allowlisted plain method missing from the buyer's list: {methods}"
    assert NEVER_ALLOWED_METHOD not in methods, (
        f"A method the seller never allowlisted must not reach the buyer; got: {methods}"
    )


@pytest.mark.smoke
def test_public_graphql_call_reaches_the_api_through_the_public_client(
    buyer_page: Page,
    _po_state: dict[str, str],
) -> None:
    """The public client's own GraphQL call carries the key, no session, and succeeds.

    This is the browser-level half of spec 10.4's scripted API-key assertions:
    the request headers are asserted on the wire, not on the client's config.
    On dev/prod the frontend leaves ``VITE_APPSYNC_ENDPOINT`` unset, so the call
    goes to ``/graphql`` on the site origin and therefore crosses CloudFront —
    which is what proves ``Managed-AllViewerExceptHostHeader`` forwards the
    ``Authorization``-free, ``x-api-key``-bearing request. On ephemeral the
    preview server has no distribution in front of it, so the endpoint is the
    AppSync hostname and the header assertions are the part that still holds.
    """
    graphql_requests = []
    graphql_responses = []
    buyer_page.on("request", lambda request: graphql_requests.append(request) if "/graphql" in request.url else None)
    buyer_page.on(
        "response", lambda response: graphql_responses.append(response) if "/graphql" in response.url else None
    )

    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(_po_state["share_url"])

    expect(buyer_page.locator("h4").first).to_be_visible(timeout=20_000)
    offer_calls = [request for request in graphql_requests if "publicGetOrderOffer" in (request.post_data or "")]
    assert offer_calls, (
        f"the public page must issue a publicGetOrderOffer GraphQL request; saw {len(graphql_requests)} /graphql call(s)"
    )

    site_netloc = urlparse(base_url()).netloc
    request = offer_calls[0]
    if is_site_origin():
        assert urlparse(request.url).netloc == site_netloc, (
            f"On a site origin the public call must go through it, not the AppSync hostname; got: {request.url}"
        )

    headers = request.headers
    assert headers.get("x-api-key"), f"the public client must send x-api-key; headers: {sorted(headers)}"
    assert "authorization" not in headers, f"the public client must never attach a session; headers: {sorted(headers)}"

    succeeded = [response for response in graphql_responses if response.status == 200]
    assert succeeded, f"the public GraphQL call must succeed; statuses: {[r.status for r in graphql_responses]}"
    body = next(
        (r.json() for r in succeeded if "publicGetOrderOffer" in (r.request.post_data or "")),
        {},
    )
    offer_payload = (body.get("data") or {}).get("publicGetOrderOffer")
    assert offer_payload, f"the public offer query must return data through this path; got: {body}"


@pytest.mark.smoke
def test_api_key_call_through_the_site_origin_reaches_appsync() -> None:
    """A scripted ``x-api-key`` call succeeds against the **site origin** ``/graphql``.

    Spec 10.4 asks for this specifically as the CloudFront forwarding proof: the
    integration suite hits the AppSync hostname directly, so only this call
    exercises the distribution's origin-request policy. Skipped on ephemeral,
    where there is no distribution in front of the preview server, and whenever
    the run carries no ``TEST_APPSYNC_API_KEY``.
    """
    api_key = os.environ.get("TEST_APPSYNC_API_KEY", "")
    if not is_site_origin() or not api_key:
        pytest.skip(
            "the through-site-origin API-key call needs a CloudFront-served origin and TEST_APPSYNC_API_KEY; "
            f"base URL {base_url()!r}, key {'set' if api_key else 'unset'}"
        )

    query = '{ publicGetOrderOffer(campaignId: "origin-probe", token: "none") { sellerName } }'
    request = urllib.request.Request(
        f"{base_url()}/graphql",
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, payload = response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        status, payload = exc.code, json.loads(exc.read().decode("utf-8"))

    assert status == 200, f"the site origin must forward the GraphQL call, not reject it; status {status}: {payload}"
    errors = payload.get("errors") or []
    refused = [error for error in errors if isinstance(error, dict) and error.get("errorType") == "Unauthorized"]
    assert not refused, f"the API key must be admitted through the site origin; got: {refused}"


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
    # The pinned boto3/botocore in the Lambda layer pre-signs against the legacy
    # global endpoint with query-string SigV2 (AWSAccessKeyId/Signature/Expires),
    # not SigV4 (X-Amz-Signature) — the image loads and decodes either way, so
    # assert the URL is *signed* without pinning one signature version's spelling.
    query_params = dict(parse_qsl(parsed.query))
    signed = (query_params.get("X-Amz-Signature") or query_params.get("Signature") or "").strip()
    assert signed, f"Pre-signed QR URL must carry a signature parameter; got: {src!r}"
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

    The buyer-visible list is the campaign's allowlist read through the offer, so
    this is the shared-state half of the contract: no cache, no second write.
    """
    settings = PublicOrderSettingsPage(owner_page)
    settings.goto(_po_state["profile_id"], _po_state["campaign_id"])
    settings.set_method(PLAIN_PAYMENT_METHOD, False)
    settings.save()

    try:
        offer = PublicOrderPage(buyer_page)
        offer.goto_share_url(_po_state["share_url"])
        methods = offer.payment_method_names()
        assert QR_PAYMENT_METHOD in methods, f"Still-allowlisted method vanished: {methods}"
        assert PLAIN_PAYMENT_METHOD not in methods, f"Un-allowlisted method still reaches the buyer: {methods}"
    finally:
        # Restore the shared allowlist so later buyer tests see the fixture's
        # two-method state.
        settings.set_method(PLAIN_PAYMENT_METHOD, True)
        settings.save()


@pytest.mark.smoke
def test_rotating_the_token_replaces_the_share_url(
    owner_page: Page,
    buyer_page: Page,
    _po_state: dict[str, str],
) -> None:
    """Rotate shows the new URL in the share view and kills the old one."""
    settings = PublicOrderSettingsPage(owner_page)
    settings.goto(_po_state["profile_id"], _po_state["campaign_id"])
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

    The server answers a bad token, a disabled campaign, a dead catalog and a
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
    the scripted check in spec 10.4 and the wire assertion above.
    """
    offer = PublicOrderPage(owner_page)
    offer.goto_share_url(_po_state["share_url"])

    assert "/login" not in owner_page.url, f"The public route must not redirect a signed-in user; got {owner_page.url}"
    assert not offer.is_unavailable(), "A signed-in user must still see the offer"
    assert offer.seller_name() == _po_state["seller_name"]


# ---------------------------------------------------------------------------
# Buyer submit and receipt (items 8-9)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_buyer_submit_without_email_offers_the_choice_then_succeeds(
    buyer_page: Page, _po_state: dict[str, str]
) -> None:
    """No email -> dialog; "go back" keeps the form; "continue" -> success screen."""
    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(_po_state["share_url"])
    offer.set_quantity(offer.product_names()[0], 2)
    offer.fill_contact("Smoke", "Buyer", phone="5551234567")
    offer.select_payment_method(QR_PAYMENT_METHOD)
    offer.submit()

    expect(buyer_page.get_by_test_id("no-email-go-back")).to_be_visible(timeout=10_000)
    offer.no_email_go_back()
    assert offer.first_name_value() == "Smoke", "Going back must preserve the filled form"

    offer.submit()
    offer.no_email_continue()
    expect(buyer_page.get_by_test_id("public-order-success")).to_be_visible(timeout=20_000)
    assert offer.order_reference(), "The success screen must show the order reference"
    assert "No confirmation email was sent" in offer.confirmation_copy(), (
        f"No-email orders must say so plainly; got: {offer.confirmation_copy()!r}"
    )
    # The receipt link is the order's own capability, not the email's: the
    # success screen offers it to a no-email buyer too, which is what makes the
    # "you will not receive a confirmation email" warning about the email only.
    assert offer.receipt_link_href(), "The success screen must still carry the order's receipt link"


@pytest.mark.smoke
def test_buyer_order_with_email_lands_and_reopens_the_same_receipt(
    buyer_page: Page,
    _po_state: dict[str, str],
) -> None:
    """An emailed order shows the honest send state and a working receipt link.

    The send assertion is environment-appropriate by design, stated not skipped.
    With ``E2E_SES_TEST_RECIPIENT`` set to an address verified in the sending
    account's SES sandbox, the page must report the email went out. Without it —
    and on ephemeral, which instantiates the SES module not at all — the honest
    state is "the email did not go out, the order did", and that is what is
    asserted. Either way the order row must have landed: an email failure never
    fails an order.
    """
    recipient = os.environ.get(_RECIPIENT_ENV, "").strip()
    buyer_email = recipient or f"smoke+po{unique_suffix()}@example.com"
    buyer_first = "Emailed"
    buyer_last = f"Buyer{unique_suffix()}"
    _po_state["email_buyer_name"] = f"{buyer_first} {buyer_last}"

    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(_po_state["share_url"])
    offer.set_quantity(offer.product_names()[0], 1)
    offer.fill_contact(buyer_first, buyer_last, phone="5551234567", email=buyer_email)
    offer.select_payment_method(PLAIN_PAYMENT_METHOD)
    offer.submit()

    expect(buyer_page.get_by_test_id("public-order-success")).to_be_visible(timeout=20_000)
    copy = offer.confirmation_copy()

    href = offer.receipt_link_href()
    assert href and "#" not in href, f"Receipt link must be a split-segment URL with no '#'; got: {href!r}"
    # ``receiptUrl`` is SITE-RELATIVE by design (composePublicOrderReceipt in
    # tofu/application/appsync/js-resolvers/lib/public_order.js: a JS resolver has
    # no environment and the API-key request carries no usable Host, so the client
    # resolves the path against its own origin; only the emailed copy is composed
    # absolutely from SITE_URL). The browser follows a root-relative href, but
    # Playwright's goto needs an absolute URL, hence the urljoin below.
    assert href.startswith("/r/"), f"The success screen's receipt link must be a site-relative /r/ path; got: {href!r}"
    assert re.search(r"/r/[^/]+/[^/]+/[^/]+$", urlparse(href).path), (
        f"Receipt link must be /r/<campaign>/<suffix>/<token>; got: {href!r}"
    )
    _po_state["receipt_url"] = urljoin(base_url(), href)

    if recipient:
        assert "A confirmation email was sent" in copy, (
            f"A sandbox-verified recipient must be told the email went out; got: {copy!r}"
        )
    else:
        why = (
            "the SES sandbox rejects recipients that are not individually verified"
            if is_site_origin()
            else "ephemeral deploys instantiate the SES module not at all"
        )
        assert "could not send the confirmation email" in copy and "still placed" in copy, (
            f"With no deliverable recipient ({why}) the page must say the email did not go out "
            f"and the order did; got: {copy!r}"
        )

    receipt = PublicReceiptPage(buyer_page)
    receipt.goto_receipt_url(_po_state["receipt_url"])
    assert not receipt.is_unavailable(), "The receipt URL must re-open the same receipt"
    assert receipt.line_item_count() >= 1, "The receipt must render its line items"
    assert receipt.status_chip_text() == "Awaiting payment confirmation", (
        f"A fresh public order reads NEW on the receipt; got: {receipt.status_chip_text()!r}"
    )
    assert PLAIN_PAYMENT_METHOD in receipt.total_label(), (
        f"The receipt total names the selected method; got: {receipt.total_label()!r}"
    )


@pytest.mark.smoke
def test_tampered_receipt_token_renders_not_available(buyer_page: Page, _po_state: dict[str, str]) -> None:
    """A tampered receipt token yields the same generic not-available page."""
    receipt = PublicReceiptPage(buyer_page)
    bare_campaign_id = _po_state["campaign_id"].split("#", 1)[-1]
    receipt.goto_receipt_url(f"{base_url()}/r/{bare_campaign_id}/0001/deadbeefdeadbeefdeadbeefdeadbeef")
    expect(receipt.page.get_by_text(UNAVAILABLE_TITLE)).to_be_visible(timeout=10_000)


# ---------------------------------------------------------------------------
# Seller after: the Orders page (item 11, authenticated half)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_public_order_shows_a_new_status_chip_and_can_be_confirmed(
    owner_page: Page,
    buyer_page: Page,
    _po_state: dict[str, str],
) -> None:
    """The public order lands in OrdersPage, and confirming payment follows through.

    KNOWN GAP (spec 10.5 item 11, half of it): the source badge and the buyer
    email column are NOT asserted. The shipped ``Order`` GraphQL type exposes
    neither ``orderSource`` nor ``customerEmail`` — only the report types carry
    ``customerEmail`` — and ``OrdersPage`` renders no badge, so there is nothing
    in the UI to assert. The status chip and the confirm action are the halves
    that ship.
    """
    buyer_name = _po_state["email_buyer_name"]
    orders = OrderPage(owner_page)
    orders.goto(_po_state["profile_id"], _po_state["campaign_id"])
    assert orders.has_order(buyer_name), f"The public order for {buyer_name!r} must appear in the orders list"

    row = owner_page.get_by_role("row").filter(has_text=buyer_name).first
    expect(row).to_be_visible(timeout=10_000)
    chip = row.get_by_test_id("order-status-chip")
    expect(chip).to_be_visible(timeout=10_000)
    assert chip.inner_text() == "New", f"A fresh public order reads NEW in the list; got: {chip.inner_text()!r}"

    row.get_by_test_id("confirm-payment-button").click()
    dialog = owner_page.get_by_role("dialog")
    expect(dialog).to_be_visible(timeout=10_000)
    dialog.get_by_role("button", name="Confirm payment", exact=True).click()
    expect(dialog).to_be_hidden(timeout=20_000)

    expect(row.get_by_test_id("order-status-chip")).to_have_text("Payment confirmed", timeout=20_000)

    # The buyer's receipt view follows the seller's confirmation.
    receipt = PublicReceiptPage(buyer_page)
    receipt.goto_receipt_url(_po_state["receipt_url"])
    expect(receipt.page.get_by_test_id("receipt-status-chip")).to_have_text("Payment confirmed", timeout=20_000)


@pytest.mark.smoke
def test_authenticated_order_carries_no_status_chip(owner_page: Page, _po_state: dict[str, str]) -> None:
    """Authenticated order creation is unchanged: no status chip, no lifecycle action.

    Historical and authenticated orders carry neither ``orderSource`` nor
    ``status`` (no backfill), so the row must render the empty state.
    """
    customer = f"Auth Buyer {unique_suffix()}"
    orders = OrderPage(owner_page)
    orders.goto(_po_state["profile_id"], _po_state["campaign_id"])
    orders.create_order_first_product(customer, qty=1)
    assert orders.has_order(customer), f"Authenticated order for {customer!r} must appear in the orders list"

    row = owner_page.get_by_role("row").filter(has_text=customer).first
    expect(row).to_be_visible(timeout=10_000)
    assert row.get_by_test_id("order-status-chip").count() == 0, (
        "An authenticated order has no status and must not render a status chip"
    )
    assert row.get_by_test_id("confirm-payment-button").count() == 0, (
        "An authenticated order has no payment-confirmation action"
    )


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
    settings.goto(_po_state["profile_id"], _po_state["campaign_id"])
    expect(settings.disable_button()).to_be_enabled(timeout=10_000)
    settings.disable()
    assert not settings.is_enabled(), "The campaign must read back as disabled"

    offer = PublicOrderPage(buyer_page)
    offer.goto_share_url(_po_state["share_url"])
    assert offer.is_unavailable(), "A disabled campaign's share URL must render the not-available state"
