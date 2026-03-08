"""Page Object Model classes for Playwright e2e smoke tests."""

from .base_page import BasePage
from .campaign_page import CampaignPage
from .campaign_settings_page import CampaignSettingsPage
from .dashboard_page import DashboardPage
from .login_page import LoginPage
from .manage_page import ManagePage
from .order_page import OrderPage
from .payment_page import PaymentPage
from .reports_page import ReportsPage
from .share_page import SharePage

__all__ = [
    "BasePage",
    "CampaignPage",
    "CampaignSettingsPage",
    "DashboardPage",
    "LoginPage",
    "ManagePage",
    "OrderPage",
    "PaymentPage",
    "ReportsPage",
    "SharePage",
]
