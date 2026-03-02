"""Page Object Model classes for Playwright e2e smoke tests."""

from .base_page import BasePage
from .campaign_page import CampaignPage
from .dashboard_page import DashboardPage
from .login_page import LoginPage
from .order_page import OrderPage
from .payment_page import PaymentPage
from .share_page import SharePage

__all__ = [
    "BasePage",
    "CampaignPage",
    "DashboardPage",
    "LoginPage",
    "OrderPage",
    "PaymentPage",
    "SharePage",
]
