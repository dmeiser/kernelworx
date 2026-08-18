"""Page Object Model classes for Playwright e2e smoke tests."""

from .admin_page import AdminPage
from .base_page import BasePage
from .campaign_page import CampaignPage
from .campaign_reports_page import CampaignReportsPage
from .campaign_settings_page import CampaignSettingsPage
from .catalogs_page import CatalogsPage
from .dashboard_page import DashboardPage
from .home_page import HomePage
from .login_page import LoginPage
from .manage_page import ManagePage
from .order_page import OrderPage
from .payment_page import PaymentPage
from .public_pages import PublicPages
from .reports_page import ReportsPage
from .share_page import SharePage
from .shared_campaigns_page import SharedCampaignsPage
from .user_data_page import UserDataPage
from .user_settings_page import UserSettingsPage

__all__ = [
    "AdminPage",
    "BasePage",
    "CampaignPage",
    "CampaignReportsPage",
    "CampaignSettingsPage",
    "CatalogsPage",
    "DashboardPage",
    "HomePage",
    "LoginPage",
    "ManagePage",
    "OrderPage",
    "PaymentPage",
    "PublicPages",
    "ReportsPage",
    "SharePage",
    "SharedCampaignsPage",
    "UserDataPage",
    "UserSettingsPage",
]
