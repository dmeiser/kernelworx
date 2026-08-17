"""Mobile viewport helpers for E2E smoke tests."""

from playwright.sync_api import Page, ViewportSize

#: Viewport matching a modern mobile phone (iPhone 14 dimensions).
MOBILE_VIEWPORT: ViewportSize = {"width": 390, "height": 844}


def use_mobile_viewport(page: Page) -> None:
    """Resize the browser page to a mobile viewport.

    Also sets a mobile user-agent so any UA-based logic sees a phone.

    Args:
        page: Playwright page to resize.
    """
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.context.set_extra_http_headers(
        {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            )
        }
    )
