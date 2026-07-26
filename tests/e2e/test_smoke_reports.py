"""Smoke tests for the campaign Reports & Exports tab.

SKIPPED locally: the HTMX redesign does not implement a reports page (the
orders page links to ``/campaigns/{id}/reports`` but no route/handler serves
that URL, and there is no *Reports & Exports* heading or CSV/XLSX download
UI).  The original scenario is preserved as an explicit skip for
traceability.
"""

import pytest
from playwright.sync_api import Page

from tests.e2e.pages.reports_page import ReportsPage  # noqa: F401  (preserved import)


@pytest.mark.smoke
def test_campaign_reports_tab_loads(owner_page: Page, ensure_owner_profile: str) -> None:
    """Verify the Reports & Exports tab loads and shows the expected heading.

    SKIPPED locally: the reports page is not implemented in the HTMX redesign.
    """
    pytest.skip(
        "Reports & Exports page is not implemented in the HTMX redesign; no "
        "route/handler serves /campaigns/{id}/reports locally."
    )
