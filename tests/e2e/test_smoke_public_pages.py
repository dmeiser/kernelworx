"""Smoke tests for public marketing pages.

These tests verify that the unauthenticated public pages (landing, privacy,
story) render correctly and do not require authentication.
"""

import pytest
from playwright.sync_api import Page

from tests.e2e.pages.public_pages import PublicPages


@pytest.mark.smoke
def test_landing_page_loads(page: Page) -> None:
    """The landing page loads with the hero heading and primary CTA."""
    public = PublicPages(page)
    public.goto_landing()
    assert public.landing_is_visible(), "Landing page hero heading must be visible"
    public.expect_landing_primary_cta()


@pytest.mark.smoke
def test_privacy_policy_page_loads(page: Page) -> None:
    """The privacy policy page loads with its main heading."""
    public = PublicPages(page)
    public.goto_privacy()
    assert public.privacy_is_visible(), "Privacy Policy heading must be visible"


@pytest.mark.smoke
def test_story_page_loads(page: Page) -> None:
    """The story page loads with its main heading."""
    public = PublicPages(page)
    public.goto_story()
    assert public.story_is_visible(), "Story page heading must be visible"


@pytest.mark.smoke
def test_public_pages_header_navigation(page: Page) -> None:
    """Public pages share a header that links between public routes."""
    public = PublicPages(page)
    public.goto_landing()
    page.get_by_role("link", name="Our story").click()
    page.wait_for_url("**/story", timeout=10_000)
    assert public.story_is_visible(), "Story page must be reachable from the landing header"
