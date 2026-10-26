"""
Dispatcher for the shared admin-operations Lambda (#773).

Owns the operation map and the ``lambda_handler`` entry point: one Lambda
serves every admin operation, and this module routes on the GraphQL field
name to the handler that owns it. The individual handlers live in the
sibling ``admin_*`` modules extracted in #773; this module only imports
them, so the operation map is the single registry of what the admin Lambda
serves.

``admin_operations`` re-exports ``lambda_handler`` so the Terraform-wired
Lambda entry point (``handlers.admin_operations.lambda_handler``) is
unchanged by the split; the AppSync resolver mapping is untouched.
"""

from typing import TYPE_CHECKING, Any, Dict

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.errors import AppError, ErrorCode
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.errors import AppError, ErrorCode

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

# The operation handlers were extracted to their own modules (#773) but stay
# registered on this Lambda. The imports are safe at module load because
# every `admin_*` module imports its shared helpers from `admin_operations`
# inside functions, never at module scope.
from .admin_account_purge import admin_purge_user_account
from .admin_catalog_operations import create_managed_catalog
from .admin_credential_reset import admin_reset_user_password
from .admin_share_campaign_ops import (
    admin_delete_share,
    admin_get_profile_shares,
    admin_update_campaign_shared_code,
)
from .admin_user_deletion import (
    admin_delete_user_campaigns,
    admin_delete_user_orders,
    admin_delete_user_profiles,
    admin_delete_user_shares,
)
from .admin_user_operations import admin_list_users, admin_search_user
from .admin_user_reads import (
    admin_get_user_campaigns,
    admin_get_user_catalogs,
    admin_get_user_profiles,
    admin_get_user_shared_campaigns,
)

# Operation dispatcher map
_OPERATION_HANDLERS = {
    "adminListUsers": admin_list_users,
    "adminSearchUser": admin_search_user,
    "adminResetUserPassword": admin_reset_user_password,
    "adminPurgeUserAccount": admin_purge_user_account,
    "adminDeleteUserOrders": admin_delete_user_orders,
    "adminDeleteUserCampaigns": admin_delete_user_campaigns,
    "adminDeleteUserShares": admin_delete_user_shares,
    "adminDeleteUserProfiles": admin_delete_user_profiles,
    "createManagedCatalog": create_managed_catalog,
    "adminGetUserProfiles": admin_get_user_profiles,
    "adminGetUserCatalogs": admin_get_user_catalogs,
    "adminGetUserCampaigns": admin_get_user_campaigns,
    "adminGetUserSharedCampaigns": admin_get_user_shared_campaigns,
    "adminGetProfileShares": admin_get_profile_shares,
    "adminDeleteShare": admin_delete_share,
    "adminUpdateCampaignSharedCode": admin_update_campaign_shared_code,
}


@with_error_handling(error_message="Failed to execute admin operation")
def lambda_handler(event: Dict[str, Any], context: Any) -> Any:
    """
    Main Lambda handler that dispatches to specific admin operations.

    Determines which operation to call based on the GraphQL field name.
    Wrapped in ``with_error_handling`` (#329) so dispatch-level errors also
    return the structured ``__isError`` payload instead of raising.

    Args:
        event: AppSync event
        context: Lambda context

    Returns:
        Result from the specific operation handler, or a structured error
        payload when the operation fails.
    """
    field_name = event.get("info", {}).get("fieldName", "")
    handler = _OPERATION_HANDLERS.get(field_name)

    if not handler:
        raise AppError(ErrorCode.INVALID_INPUT, f"Unknown admin operation: {field_name}")

    return handler(event, context)
