"""
Admin managed-catalog handler (extracted from admin_operations, #773).

Provides:
- createManagedCatalog: Create an ADMIN_MANAGED global catalog

The handler stays registered on the shared admin-operations Lambda:
``admin_operations`` imports it for its operation dispatcher map, so the
Lambda entry point (``handlers.admin_operations.lambda_handler``) and the
AppSync handler mapping are unchanged.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Dict

from botocore.exceptions import ClientError

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.appsync_types import get_caller_id
    from utils.auth import require_admin_mfa
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.appsync_types import get_caller_id
    from ..utils.auth import require_admin_mfa
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
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


def _parse_product_price(price: Any) -> Decimal:
    """Convert a product price (number or numeric string) to a validated Decimal.

    A missing price, a non-numeric/unparsable value, or a negative price
    raises INVALID_INPUT.
    """
    if price is None:
        raise AppError(ErrorCode.INVALID_INPUT, "Valid product price is required")

    try:
        price_decimal = Decimal(str(price))
    except InvalidOperation, ValueError, TypeError:
        raise AppError(ErrorCode.INVALID_INPUT, "Product price must be a valid number")

    if price_decimal < 0:
        raise AppError(ErrorCode.INVALID_INPUT, "Valid product price is required")
    return price_decimal


def _validate_and_process_product(product: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and process a catalog product, returning processed product dict.

    Price may arrive as a number or a numeric string (e.g. from AppSync JSON
    deserialization); it is converted to Decimal before validation and storage.
    Non-numeric or unparsable values raise INVALID_INPUT.
    """
    product_name = product.get("productName", "").strip()

    if not product_name:
        raise AppError(ErrorCode.INVALID_INPUT, "Product name is required")

    processed_product: Dict[str, Any] = {
        "productId": f"PRODUCT#{uuid.uuid4()}",
        "productName": product_name,
        "price": _parse_product_price(product.get("price")),
        "sortOrder": product.get("sortOrder", 0),
    }

    description = product.get("description", "").strip()
    if description:
        processed_product["description"] = description

    return processed_product


def _validate_catalog_input(catalog_input: Dict[str, Any]) -> tuple[str, bool, list[Dict[str, Any]]]:
    """Validate catalog input and extract name, isPublic, products."""
    catalog_name = catalog_input.get("catalogName", "").strip()
    is_public = catalog_input.get("isPublic", True)
    products = catalog_input.get("products", [])

    if not catalog_name:
        raise AppError(ErrorCode.INVALID_INPUT, "Catalog name is required")
    if not products:
        raise AppError(ErrorCode.INVALID_INPUT, "Products array cannot be empty")

    return catalog_name, is_public, products


def _build_catalog_item(
    catalog_id: str,
    catalog_name: str,
    is_public: bool,
    caller_id: str,
    processed_products: list[Dict[str, Any]],
    now: str,
) -> Dict[str, Any]:
    """Build the catalog item dictionary for DynamoDB."""
    return {
        "catalogId": catalog_id,
        "catalogName": catalog_name,
        "catalogType": "ADMIN_MANAGED",  # Key difference from regular createCatalog
        "ownerAccountId": f"ACCOUNT#{caller_id}",  # Track who created it
        "isPublic": is_public,
        "isPublicStr": "true" if is_public else "false",  # For GSI queries
        "products": processed_products,
        "createdAt": now,
        "updatedAt": now,
    }


def _persist_catalog(catalog_item: Dict[str, Any], logger: Any) -> None:
    """Persist catalog to DynamoDB."""
    try:
        tables.catalogs.put_item(Item=catalog_item)
    except ClientError as e:
        logger.error("Failed to create catalog", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to create catalog")


def _require_admin_and_get_actor_sub(event: Dict[str, Any]) -> str:
    """Require admin + MFA and return the acting administrator's own ``sub`` (#507).

    The actor counterpart to `_require_admin_and_get_target_account_id`: this
    one returns the caller, whose sub is what the audit line must record.
    """
    require_admin_mfa(event)

    caller_id = get_caller_id(event)
    if not caller_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")

    return str(caller_id)


@with_error_handling(error_message="Failed to create catalog")
def create_managed_catalog(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create an ADMIN_MANAGED catalog (admin only).

    AppSync Lambda resolver for createManagedCatalog mutation.
    Creates a global catalog that is available to all users.

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        Created Catalog object

    Raises:
        AppError: If not admin, validation fails, or creation error
    """
    logger = get_logger(__name__)

    caller_id = _require_admin_and_get_actor_sub(event)

    arguments = event.get("arguments", {})
    catalog_input = arguments.get("input", {})

    catalog_name, is_public, products = _validate_catalog_input(catalog_input)

    catalog_id = f"CATALOG#{uuid.uuid4()}"
    now = datetime.now(timezone.utc).isoformat()

    processed_products = [_validate_and_process_product(product) for product in products]

    catalog_item = _build_catalog_item(catalog_id, catalog_name, is_public, caller_id, processed_products, now)

    _persist_catalog(catalog_item, logger)

    logger.info(
        "Created managed catalog",
        catalog_id=catalog_id,
        catalog_name=catalog_name,
        actor_sub=caller_id,
    )

    return catalog_item
