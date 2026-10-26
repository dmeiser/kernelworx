"""
Admin per-entity user deletion handlers (extracted from admin_operations, #773).

Provides:
- adminDeleteUserOrders: Delete all orders for a user's campaigns
- adminDeleteUserCampaigns: Delete all campaigns for a user's profiles
- adminDeleteUserShares: Delete all shares for a user's profiles
- adminDeleteUserProfiles: Delete all profiles owned by a user

The handlers stay registered on the shared admin-operations Lambda:
``admin_operations`` imports them for its operation dispatcher map, so the
Lambda entry point (``handlers.admin_operations.lambda_handler``) and the
AppSync handler mapping are unchanged.
"""

from typing import TYPE_CHECKING, Any, Dict

# Sibling handler modules use a same-package relative import, which resolves both
# in the Lambda zip (package `handlers`) and in unit tests (package `src.handlers`).
from .deletion_cascade import (
    delete_user_campaigns,
    delete_user_orders,
    delete_user_profiles,
    delete_user_shares,
    get_user_profiles,
    normalize_account_id,
)

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.logging import get_logger

# The decorator stays typed for mypy via the relative import below; at runtime
# the absolute import resolves in the Lambda zip (package `utils`) and the
# relative fallback resolves in unit tests (package `src.handlers`).
if TYPE_CHECKING:  # pragma: no cover
    from ..utils.handlers import lambda_handler as with_error_handling
else:  # pragma: no cover
    try:
        from utils.handlers import lambda_handler as with_error_handling
    except ModuleNotFoundError:
        from ..utils.handlers import lambda_handler as with_error_handling


def _user_profiles_for(account_id: str) -> list[Dict[str, Any]]:
    """Sweep the profiles table once for a per-domain admin deletion."""
    return get_user_profiles(normalize_account_id(account_id))


@with_error_handling(error_message="Failed to delete user orders")
def admin_delete_user_orders(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all orders for all campaigns of all profiles owned by a user (admin only).

    Verifies with strongly consistent reads that each deleted order is gone
    from the orders table before returning success.

    Returns the count of deleted orders.
    """
    from .admin_operations import _require_admin_and_get_target_account_id

    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    deleted_count = delete_user_orders(_user_profiles_for(account_id), logger)
    logger.info("Admin deleted user orders", account_id=account_id, count=deleted_count, actor_sub=actor_sub)
    return deleted_count


@with_error_handling(error_message="Failed to delete user campaigns")
def admin_delete_user_campaigns(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all campaigns for all profiles owned by a user (admin only).

    Verifies with strongly consistent reads that each deleted campaign is gone
    from the campaigns table before returning success.

    Returns the count of deleted campaigns.
    """
    from .admin_operations import _require_admin_and_get_target_account_id

    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    deleted_count = delete_user_campaigns(_user_profiles_for(account_id), logger)
    logger.info("Admin deleted user campaigns", account_id=account_id, count=deleted_count, actor_sub=actor_sub)
    return deleted_count


@with_error_handling(error_message="Failed to delete user shares")
def admin_delete_user_shares(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all shares for all profiles owned by a user (admin only).

    Returns the count of deleted shares.
    """
    from .admin_operations import _require_admin_and_get_target_account_id

    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    deleted_count = delete_user_shares(_user_profiles_for(account_id), logger)
    logger.info("Admin deleted user shares", account_id=account_id, count=deleted_count, actor_sub=actor_sub)
    return deleted_count


@with_error_handling(error_message="Failed to delete user profiles")
def admin_delete_user_profiles(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all profiles owned by a user (admin only).

    Returns the count of deleted profiles.
    """
    from .admin_operations import _require_admin_and_get_target_account_id

    logger = get_logger(__name__)

    account_id, actor_sub = _require_admin_and_get_target_account_id(event)
    deleted_count = delete_user_profiles(account_id, _user_profiles_for(account_id), logger)
    logger.info("Admin deleted user profiles", account_id=account_id, count=deleted_count, actor_sub=actor_sub)
    return deleted_count
