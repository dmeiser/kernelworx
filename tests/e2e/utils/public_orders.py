"""Shared setup for the public order smoke suites (spec 10.5).

Both ``test_smoke_public_orders.py`` and the ``test_smoke_auth_boundary.py``
extension need a profile whose public orders are enabled, because the buyer
route's authorization is the share token itself.  This module owns that setup in
one place so the two suites cannot drift apart, and so the enable-time
acknowledgements are accepted exactly once per run.

Why a **dedicated** profile
--------------------------
The acknowledgement block renders only while the stored acknowledgement version
lags the current constant, so the enable-time warning copy can be asserted only
on a profile that has never accepted it.  Reusing the shared
``ensure_owner_profile`` profile would make that assertion depend on which suite
ran first.  :func:`setup_public_orders` therefore creates its own profile, and
the acknowledgement-UI test creates a second, never-enabled one.

Data shape
----------
:func:`setup_public_orders` returns a plain dict so callers can mutate their own
copy (a token rotation changes the share URL mid-suite) without corrupting the
session fixture other suites read.
"""

import os
import re
import time
import urllib.parse
import uuid
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, expect

from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.payment_page import PaymentPage
from tests.e2e.pages.public_order_page import PublicOrderSettingsPage
from tests.e2e.utils.auth import login_as_owner

#: Payment method created (if absent) and given a QR image, so the buyer page has
#: a method that renders a QR plus its decoded link.
QR_PAYMENT_METHOD: str = "Smoke QR Pay"

#: A method with no QR image: the buyer page must show the *no QR uploaded* alert
#: for it instead of an image.
PLAIN_PAYMENT_METHOD: str = "Cash"

#: QR fixture encoding ``https://pay.example.com/kernelworx-smoke-qr``.  A real
#: QR, not the 1x1 placeholder in ``fixtures/qr.png``: the buyer page decodes the
#: image client-side and renders the link only for an https payload.
_QR_FIXTURE: Path = Path(__file__).resolve().parent.parent / "fixtures" / "payment_qr.png"


def base_url() -> str:
    """Return the app base URL from the environment at call time."""
    return os.getenv("E2E_BASE_URL", "https://localhost:5173").rstrip("/")


def is_site_origin() -> bool:
    """Return ``True`` when the run targets a deployed site origin (dev/prod).

    Ephemeral CI serves the built frontend through a Vite preview on
    ``localhost``, and the CSP baked into that build lists only the dev/prod
    exports-bucket hosts in ``img-src`` (#440 accepted gap).  Anything that needs
    the browser to actually *load* a pre-signed exports-bucket image — the QR
    paint and the client-side QR decode — is only meaningful on a site origin.
    """
    host = urllib.parse.urlparse(base_url()).hostname or ""
    return host not in ("localhost", "127.0.0.1", "::1", "")


def unique_suffix() -> str:
    """Return a short unique token for names that must not collide across runs."""
    return f"{int(time.time())}-{uuid.uuid4().hex[:6]}"


def profile_id_from_url(url: str) -> str:
    """Extract the decoded profile ID from a ``/scouts/{id}/...`` URL.

    Args:
        url: Current browser URL.

    Raises:
        AssertionError: When the URL carries no profile segment.
    """
    match = re.search(r"/scouts/([^/?#]+)", url)
    assert match, f"Could not extract profile_id from URL: {url}"
    return urllib.parse.unquote(match.group(1))


def campaign_id_from_url(url: str) -> str:
    """Extract the decoded campaign ID from a ``/scouts/{id}/campaigns/{id}`` URL.

    Args:
        url: Current browser URL.

    Raises:
        AssertionError: When the URL carries no campaign segment.
    """
    match = re.search(r"/scouts/[^/]+/campaigns/([^/?#]+)", url)
    assert match, f"Could not extract campaign_id from URL: {url}"
    return urllib.parse.unquote(match.group(1))


def create_owned_profile(page: Page, seller_name: str) -> str:
    """Create an owned seller profile named *seller_name* and return its ID.

    Args:
        page: Authenticated owner page.
        seller_name: Seller name for the new profile.

    Returns:
        The new profile's raw ID (``PROFILE#…``).
    """
    dashboard = DashboardPage(page)
    dashboard.goto()
    dashboard._create_scout_button().click()
    dialog = page.get_by_role("dialog")
    page.get_by_label("Scout Name").fill(seller_name)
    page.get_by_role("button", name="Create Scout").click()
    expect(dialog).to_be_hidden(timeout=20_000)
    dashboard.wait_for_loading()

    for _ in range(15):
        if seller_name in dashboard.get_owned_profile_names():
            break
        page.wait_for_timeout(1_000)
    else:
        raise AssertionError(f"Profile {seller_name!r} did not appear in 'Scouts I Own' after creation")

    dashboard.click_profile(seller_name)
    return profile_id_from_url(page.url)


def create_active_campaign(page: Page, profile_id: str, campaign_name: str) -> str:
    """Create an active campaign on *profile_id* using the first catalog.

    Args:
        page: Authenticated owner page.
        profile_id: Profile to create the campaign on.
        campaign_name: Campaign name (also the anchor-campaign label substring).

    Returns:
        The new campaign's raw ID (``CAMPAIGN#…``).
    """
    campaign_page = CampaignPage(page)
    campaign_page.goto(profile_id)
    campaign_page.create_campaign_first_catalog(campaign_name, profile_id)
    campaign_page.click_campaign(campaign_name)
    return campaign_id_from_url(page.url)


def ensure_qr_payment_method(page: Page, method_name: str) -> None:
    """Ensure the account has a payment method *method_name* carrying a QR image.

    Args:
        page: Authenticated owner page.
        method_name: Payment method name (account-level, shared by profiles).
    """
    payments = PaymentPage(page)
    payments.goto()
    if not payments.has_payment_method(method_name):
        payments.add_payment_method(method_name)
    if not payments.has_qr_code(method_name):
        payments.upload_qr_code(method_name, str(_QR_FIXTURE))
        assert payments.has_qr_code(method_name), f"QR upload did not stick for {method_name!r}"


def enable_public_orders(
    page: Page,
    profile_id: str,
    campaign_name: str,
    methods: list[str],
) -> str:
    """Enable public orders on *profile_id* and return the share URL.

    Idempotent: an already-enabled profile is left as configured, so a second
    caller does not rotate the token out from under a running suite.

    Args:
        page: Authenticated owner page.
        profile_id: Profile to configure.
        campaign_name: Anchor campaign label substring.
        methods: Payment methods to allowlist.

    Returns:
        The absolute share URL shown in the share view.
    """
    settings = PublicOrderSettingsPage(page)
    settings.goto(profile_id)
    if settings.share_view_is_visible():
        return settings.share_url()

    settings.set_enabled(True)
    settings.select_campaign(campaign_name)
    for name in methods:
        settings.set_method(name, True)
    if settings.ack_block_is_visible():
        for index in range(len(settings.ack_checkboxes())):
            settings.check_ack(index)
    settings.save()

    deadline = time.monotonic() + 20
    share_url = settings.share_url()
    while not share_url and time.monotonic() < deadline:
        page.wait_for_timeout(500)
        share_url = settings.share_url()
    assert share_url, f"Share URL missing after enabling public orders on {profile_id}"
    return share_url


def setup_public_orders(browser: Browser) -> dict[str, str]:
    """Build the public-order fixture data and return it as a dict.

    Creates a dedicated owned profile with one active campaign, ensures a QR
    payment method exists on the account, and enables public orders allowlisting
    :data:`QR_PAYMENT_METHOD` and :data:`PLAIN_PAYMENT_METHOD`.

    Args:
        browser: Session-scoped Playwright browser.

    Returns:
        Dict with ``profile_id``, ``profile_name``, ``campaign_id``,
        ``campaign_name``, ``seller_name``, ``share_url``, ``share_token``,
        ``qr_method`` and ``plain_method``.
    """
    suffix = unique_suffix()
    seller_name = f"PO Smoke {suffix}"
    campaign_name = f"PO Campaign {suffix}"

    context: BrowserContext = browser.new_context(ignore_https_errors=True)
    try:
        page: Page = context.new_page()
        login_as_owner(page)

        profile_id = create_owned_profile(page, seller_name)
        campaign_id = create_active_campaign(page, profile_id, campaign_name)
        ensure_qr_payment_method(page, QR_PAYMENT_METHOD)
        share_url = enable_public_orders(page, profile_id, campaign_name, [QR_PAYMENT_METHOD, PLAIN_PAYMENT_METHOD])
    finally:
        context.close()

    token = share_url.rstrip("/").rsplit("/", 1)[-1]
    return {
        "profile_id": profile_id,
        "profile_name": seller_name,
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "seller_name": seller_name,
        "share_url": share_url,
        "share_token": token,
        "qr_method": QR_PAYMENT_METHOD,
        "plain_method": PLAIN_PAYMENT_METHOD,
    }
