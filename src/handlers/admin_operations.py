"""
Admin operations handlers for superadmin functionality.

Provides:
- adminResetUserPassword: Send password reset email to user
- adminDeleteUser: Delete user from Cognito and DynamoDB
- createManagedCatalog: Create an ADMIN_MANAGED global catalog
"""

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import is_admin
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import is_admin
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger


def _get_required_env(name: str) -> str:
    """Get required environment variable or raise error."""
    value = os.environ.get(name)
    if not value:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Missing required environment variable: {name}")
    return value


def _get_cognito_client() -> Any:
    """Get Cognito IDP client, supporting localstack endpoint."""
    endpoint_url = os.environ.get("COGNITO_ENDPOINT")
    if endpoint_url:
        return boto3.client("cognito-idp", endpoint_url=endpoint_url)
    return boto3.client("cognito-idp")


def _get_user_groups(cognito: Any, user_pool_id: str, username: str) -> list[str]:
    """Get the groups a user belongs to."""
    try:
        response = cognito.admin_list_groups_for_user(
            UserPoolId=user_pool_id,
            Username=username,
        )
        return [group["GroupName"] for group in response.get("Groups", [])]
    except ClientError:
        return []


def _get_cognito_user_attributes(cognito_user: Dict[str, Any]) -> tuple[str, str, bool, str, bool]:
    """Extract core attributes from a Cognito user dict."""
    username = cognito_user.get("Username", "")
    attributes = {attr["Name"]: attr["Value"] for attr in cognito_user.get("Attributes", [])}
    
    account_id = attributes.get("sub", username)
    email = attributes.get("email", "")
    email_verified = attributes.get("email_verified", "false").lower() == "true"
    user_status = cognito_user.get("UserStatus", "UNKNOWN")
    enabled = cognito_user.get("Enabled", True)
    
    return account_id, email, email_verified, user_status, enabled


def _get_display_name_from_dynamodb(account_id: str, logger: Any) -> str | None:
    """Try to get display name from DynamoDB account record."""
    try:
        db_account_id = f"ACCOUNT#{account_id}"
        db_response = tables.accounts.get_item(Key={"accountId": db_account_id})
        if "Item" in db_response:
            account = db_response["Item"]
            given_name = str(account.get("givenName", ""))
            family_name = str(account.get("familyName", ""))
            if given_name or family_name:
                return f"{given_name} {family_name}".strip()
    except ClientError as e:
        logger.warning("Failed to get DynamoDB account", error=str(e), account_id=account_id)
    return None


def _build_admin_user_dict(
    cognito_user: Dict[str, Any],
    cognito: Any,
    user_pool_id: str,
    logger: Any,
) -> Dict[str, Any]:
    """Build AdminUser dict from Cognito user data and DynamoDB account."""
    account_id, email, email_verified, user_status, enabled = _get_cognito_user_attributes(cognito_user)
    
    created_at = cognito_user.get("UserCreateDate")
    last_modified_at = cognito_user.get("UserLastModifiedDate")
    
    username = cognito_user.get("Username", "")
    groups = _get_user_groups(cognito, user_pool_id, username)
    is_admin_user = "ADMIN" in groups
    
    display_name = _get_display_name_from_dynamodb(account_id, logger)
    
    return {
        "accountId": account_id,
        "email": email,
        "displayName": display_name,
        "status": user_status,
        "enabled": enabled,
        "emailVerified": email_verified,
        "isAdmin": is_admin_user,
        "createdAt": created_at.isoformat() if created_at else None,
        "lastModifiedAt": last_modified_at.isoformat() if last_modified_at else None,
    }


def _list_cognito_users(cognito: Any, user_pool_id: str, limit: int, next_token: str | None, logger: Any) -> tuple[list[Dict[str, Any]], str | None]:
    """Call Cognito list_users API and return (users, pagination_token)."""
    list_params: Dict[str, Any] = {"UserPoolId": user_pool_id, "Limit": limit}
    if next_token:
        list_params["PaginationToken"] = next_token

    try:
        response = cognito.list_users(**list_params)
    except ClientError as e:
        logger.error("Cognito list_users failed", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to list users")

    return response.get("Users", []), response.get("PaginationToken")


def admin_list_users(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    List all Cognito users with their DynamoDB Account data (admin only).

    AppSync Lambda resolver for adminListUsers query.
    Retrieves users from Cognito and enriches with DynamoDB Account data.

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        AdminUserConnection with users array and optional nextToken

    Raises:
        AppError: If not admin or Cognito error
    """
    logger = get_logger(__name__)

    try:
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        arguments = event.get("arguments", {})
        limit = max(1, min(arguments.get("limit", 20), 60))
        next_token = arguments.get("nextToken")

        user_pool_id = _get_required_env("USER_POOL_ID")
        cognito = _get_cognito_client()

        cognito_users, pagination_token = _list_cognito_users(cognito, user_pool_id, limit, next_token, logger)
        admin_users = [
            _build_admin_user_dict(cognito_user, cognito, user_pool_id, logger) for cognito_user in cognito_users
        ]

        logger.info("Listed users", count=len(admin_users), has_more=bool(pagination_token))
        return {"users": admin_users, "nextToken": pagination_token}

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_list_users", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to list users")


def _execute_search_strategy(query: str, cognito: Any, user_pool_id: str, logger: Any) -> dict[str, Dict[str, Any]]:
    """Execute search strategy based on query format."""
    if query.startswith("ACCOUNT#"):
        return _search_by_account_prefix(query, cognito, user_pool_id, logger)
    if _looks_like_uuid(query):
        return _search_by_uuid(query, cognito, user_pool_id, logger)
    return _search_by_general_query(query, cognito, user_pool_id, logger)


def admin_search_user(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Search for users by email, name, or accountId (admin only).

    AppSync Lambda resolver for adminSearchUser query.
    Search strategy:
    1. If query looks like UUID or ACCOUNT#UUID, search Cognito by sub directly (single result)
    2. Otherwise:
       a. Search DynamoDB Accounts table with fuzzy matching (logged-in users)
       b. Search Cognito with prefix matching (all users, including those who haven't logged in)
       c. Merge results, deduplicate by accountId

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        List of AdminUser objects matching the query (empty list if none found)

    Raises:
        AppError: If not admin, missing query, or Cognito error
    """
    logger = get_logger(__name__)

    try:
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        query = str(event.get("arguments", {}).get("query", "")).strip()
        if not query:
            raise AppError(ErrorCode.INVALID_INPUT, "Search query is required")

        user_pool_id = _get_required_env("USER_POOL_ID")
        cognito = _get_cognito_client()

        # Determine search strategy based on query format
        results_map = _execute_search_strategy(query, cognito, user_pool_id, logger)

        return list(results_map.values())

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_search_user", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to search user")


def _search_by_account_prefix(query: str, cognito: Any, user_pool_id: str, logger: Any) -> dict[str, Dict[str, Any]]:
    """Search by ACCOUNT# prefix and return results map."""
    sub_value = query[8:]  # Remove "ACCOUNT#"
    cognito_user = _search_user_by_sub(cognito, user_pool_id, sub_value, logger)
    if cognito_user:
        admin_user = _build_admin_user(cognito, user_pool_id, cognito_user, logger)
        return {admin_user["accountId"]: admin_user}
    return {}


def _search_by_uuid(query: str, cognito: Any, user_pool_id: str, logger: Any) -> dict[str, Dict[str, Any]]:
    """Search by UUID (sub) and return results map."""
    cognito_user = _search_user_by_sub(cognito, user_pool_id, query, logger)
    if cognito_user:
        admin_user = _build_admin_user(cognito, user_pool_id, cognito_user, logger)
        return {admin_user["accountId"]: admin_user}
    return {}


def _validate_admin_and_get_account_id(event: Dict[str, Any]) -> str:
    """Validate admin access and extract account ID from event."""
    if not is_admin(event):
        raise AppError(ErrorCode.FORBIDDEN, "Admin access required")
    
    arguments = event.get("arguments", {})
    account_id = str(arguments.get("accountId", "")).strip()
    
    if not account_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Account ID is required")
    
    return account_id


def _normalize_account_id(account_id: str) -> str:
    """Add ACCOUNT# prefix if not present."""
    return account_id if account_id.startswith("ACCOUNT#") else f"ACCOUNT#{account_id}"


def _add_dynamodb_users_to_map(results_map: dict[str, Dict[str, Any]], query: str, cognito: Any, user_pool_id: str, logger: Any) -> None:
    """Search DynamoDB and add users to results map."""
    accounts = _search_accounts_in_dynamodb(query, logger)
    for account in accounts:
        account_id = account.get("accountId", "")
        if account_id.startswith("ACCOUNT#"):
            sub_value = account_id[8:]
            cognito_user = _search_user_by_sub(cognito, user_pool_id, sub_value, logger)
            if cognito_user:
                admin_user = _build_admin_user(cognito, user_pool_id, cognito_user, logger)
                results_map[admin_user["accountId"]] = admin_user


def _add_cognito_users_to_map(results_map: dict[str, Dict[str, Any]], query: str, cognito: Any, user_pool_id: str, logger: Any) -> None:
    """Search Cognito by email and add users to results map."""
    cognito_users = _search_users_in_cognito_by_email_prefix(cognito, user_pool_id, query, logger)
    for cognito_user in cognito_users:
        admin_user = _build_admin_user(cognito, user_pool_id, cognito_user, logger)
        if admin_user["accountId"] not in results_map:
            results_map[admin_user["accountId"]] = admin_user


def _search_by_general_query(query: str, cognito: Any, user_pool_id: str, logger: Any) -> dict[str, Dict[str, Any]]:
    """Search DynamoDB and Cognito by general query and return merged results map."""
    results_map: dict[str, Dict[str, Any]] = {}
    _add_dynamodb_users_to_map(results_map, query, cognito, user_pool_id, logger)
    _add_cognito_users_to_map(results_map, query, cognito, user_pool_id, logger)
    return results_map


def _matches_query(item: Dict[str, Any], query_lower: str) -> bool:
    """Check if account item matches query (case-insensitive)."""
    email = str(item.get("email", "")).lower()
    given_name = str(item.get("givenName", "")).lower()
    family_name = str(item.get("familyName", "")).lower()
    return query_lower in email or query_lower in given_name or query_lower in family_name


def _filter_matching_accounts(items: list[Dict[str, Any]], query_lower: str, matches: list[Dict[str, Any]], max_results: int) -> None:
    """Filter accounts that match the query and add to matches list."""
    for item in items:
        if len(matches) >= max_results:
            break
        if _matches_query(item, query_lower):
            matches.append(item)


def _scan_accounts_page(paginator_params: Dict[str, Any]) -> tuple[list[Dict[str, Any]], Dict[str, Any] | None]:
    """Scan one page of accounts. Returns (items, last_evaluated_key)."""
    response = tables.accounts.scan(**paginator_params)
    items = response.get("Items", [])
    last_key = response.get("LastEvaluatedKey")
    return items, last_key


def _search_accounts_in_dynamodb(query: str, logger: Any) -> list[Dict[str, Any]]:
    """
    Search DynamoDB Accounts table with case-insensitive partial matching.

    Searches email, givenName, and familyName fields.
    Returns all matching accounts (up to max_results limit).

    Note: For small user bases (<10k), scanning and filtering in Python is acceptable.
    For larger scale, consider adding lowercase GSI fields or using OpenSearch.
    """
    query_lower = query.lower()
    matches: list[Dict[str, Any]] = []
    max_results = 50  # Limit results to prevent overwhelming responses

    try:
        # Scan accounts and filter in Python for case-insensitive matching
        paginator_params: Dict[str, Any] = {}
        scanned_count = 0
        max_scan = 1000  # Safety limit

        while scanned_count < max_scan and len(matches) < max_results:
            items, last_key = _scan_accounts_page(paginator_params)
            
            _filter_matching_accounts(items, query_lower, matches, max_results)
            
            scanned_count += len(items)

            # Check for more pages
            if last_key:
                paginator_params["ExclusiveStartKey"] = last_key
            else:
                break

        return matches

    except ClientError as e:
        logger.warning("DynamoDB search failed", error=str(e), query=query)
        return []


def _looks_like_uuid(value: str) -> bool:
    """Check if a string looks like a UUID."""
    # UUID format: 8-4-4-4-12 hex characters
    import re

    uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    return bool(re.match(uuid_pattern, value.lower()))


def _search_user_by_sub(cognito: Any, user_pool_id: str, sub: str, logger: Any) -> Dict[str, Any] | None:
    """Search for a Cognito user by sub (account ID)."""
    try:
        response = cognito.list_users(
            UserPoolId=user_pool_id,
            Filter=f'sub = "{sub}"',
            Limit=1,
        )
        users = response.get("Users", [])
        return users[0] if users else None
    except ClientError as e:
        logger.warning("Cognito search by sub failed", error=str(e), sub=sub)
        return None


def _search_users_in_cognito_by_email_prefix(
    cognito: Any, user_pool_id: str, query: str, logger: Any
) -> list[Dict[str, Any]]:
    """
    Search Cognito users by email prefix.

    Uses Cognito's email ^= filter for prefix matching.
    This finds users who haven't logged in yet (no DynamoDB record).

    Returns up to 50 matching users.
    """
    try:
        response = cognito.list_users(
            UserPoolId=user_pool_id,
            Filter=f'email ^= "{query}"',  # Prefix match on email
            Limit=50,  # Reasonable limit for search results
        )
        return list(response.get("Users", []))
    except ClientError as e:
        logger.warning("Cognito email prefix search failed", error=str(e), query=query)
        return []


def _extract_cognito_attributes(cognito_user: Dict[str, Any]) -> tuple[str, Dict[str, str]]:
    """Extract username and attributes from Cognito user."""
    username = cognito_user.get("Username", "")
    attributes = {attr["Name"]: attr["Value"] for attr in cognito_user.get("Attributes", [])}
    return username, attributes


def _get_display_name_from_db(account_id: str, logger: Any) -> Optional[str]:
    """Try to get display name from DynamoDB Account table."""
    try:
        db_account_id = f"ACCOUNT#{account_id}"
        db_response = tables.accounts.get_item(Key={"accountId": db_account_id})
        if "Item" in db_response:
            account = db_response["Item"]
            given_name = str(account.get("givenName", ""))
            family_name = str(account.get("familyName", ""))
            if given_name or family_name:
                return f"{given_name} {family_name}".strip()
    except ClientError as e:
        logger.warning("Failed to get DynamoDB account", error=str(e), account_id=account_id)
    return None


def _build_admin_user(cognito: Any, user_pool_id: str, cognito_user: Dict[str, Any], logger: Any) -> Dict[str, Any]:
    """Build an AdminUser object from Cognito user data."""
    # Extract Cognito attributes
    username, attributes = _extract_cognito_attributes(cognito_user)

    # Get sub (accountId) - this is the unique identifier
    account_id = attributes.get("sub", username)
    email = attributes.get("email", "")
    email_verified = attributes.get("email_verified", "false").lower() == "true"

    # Get user status and enabled state from Cognito
    user_status = cognito_user.get("UserStatus", "UNKNOWN")
    enabled = cognito_user.get("Enabled", True)

    # Get timestamps
    created_at = cognito_user.get("UserCreateDate")
    last_modified_at = cognito_user.get("UserLastModifiedDate")

    # Check if user is in ADMIN group
    groups = _get_user_groups(cognito, user_pool_id, username)
    is_admin_user = "ADMIN" in groups

    # Try to get DynamoDB Account data for display name
    display_name = _get_display_name_from_db(account_id, logger)

    return {
        "accountId": account_id,
        "email": email,
        "displayName": display_name,
        "status": user_status,
        "enabled": enabled,
        "emailVerified": email_verified,
        "isAdmin": is_admin_user,
        "createdAt": created_at.isoformat() if created_at else None,
        "lastModifiedAt": last_modified_at.isoformat() if last_modified_at else None,
    }


def _find_cognito_user_by_sub(cognito: Any, user_pool_id: str, account_id: str, logger: Any) -> tuple[str | None, str | None]:
    """Find Cognito user by sub and return (username, email)."""
    try:
        users_response = cognito.list_users(
            UserPoolId=user_pool_id,
            Filter=f'sub = "{account_id}"',
            Limit=1,
        )
        users = users_response.get("Users", [])
        if users:
            username = users[0]["Username"]
            attributes = {attr["Name"]: attr["Value"] for attr in users[0].get("Attributes", [])}
            email = attributes.get("email", "")
            return username, email
    except ClientError as e:
        logger.warning("Could not find Cognito user by sub", error=str(e), account_id=account_id)
    return None, None


def _delete_user_from_cognito(cognito: Any, user_pool_id: str, username: str, email: str, logger: Any) -> None:
    """Delete user from Cognito."""
    try:
        cognito.admin_delete_user(UserPoolId=user_pool_id, Username=username)
        logger.info("Deleted user from Cognito", username=username, email=email)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        logger.error("Cognito admin_delete_user failed", error=str(e), error_code=error_code)
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete user from Cognito")


def _delete_account_from_dynamodb(account_id: str, logger: Any) -> None:
    """Try to delete account from DynamoDB (may not exist if user never logged in)."""
    db_account_id = f"ACCOUNT#{account_id}"
    try:
        tables.accounts.delete_item(Key={"accountId": db_account_id})
        logger.info("Deleted account from DynamoDB", account_id=db_account_id)
    except ClientError as e:
        logger.warning("Could not delete from DynamoDB (may not exist)", error=str(e), account_id=db_account_id)


def _find_user_by_email(cognito: Any, user_pool_id: str, email: str, logger: Any) -> str:
    """Find username by email. Returns username."""
    try:
        response = cognito.list_users(
            UserPoolId=user_pool_id,
            Filter=f'email = "{email}"',
            Limit=1,
        )
    except ClientError as e:
        logger.error("Cognito list_users failed", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to search for user")

    users = response.get("Users", [])
    if not users:
        raise AppError(ErrorCode.NOT_FOUND, f"User with email '{email}' not found")

    return str(users[0]["Username"])


def _initiate_password_reset(cognito: Any, user_pool_id: str, username: str, email: str, logger: Any) -> None:
    """Initiate Cognito password reset for user."""
    try:
        cognito.admin_reset_user_password(
            UserPoolId=user_pool_id,
            Username=username,
        )
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "UserNotFoundException":
            raise AppError(ErrorCode.NOT_FOUND, f"User with email '{email}' not found")
        if error_code == "InvalidParameterException":
            raise AppError(ErrorCode.INVALID_INPUT, "Cannot reset password for this user type")
        logger.error("Cognito admin_reset_user_password failed", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to initiate password reset")


def admin_reset_user_password(event: Dict[str, Any], context: Any) -> bool:
    """
    Send password reset email to user (admin only).

    AppSync Lambda resolver for adminResetUserPassword mutation.

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        True if password reset was initiated successfully

    Raises:
        AppError: If not admin, user not found, or Cognito error
    """
    logger = get_logger(__name__)

    try:
        # Verify caller is admin and extract email
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        arguments = event.get("arguments", {})
        email = arguments.get("email", "").strip().lower()

        if not email:
            raise AppError(ErrorCode.INVALID_INPUT, "Email is required")

        user_pool_id = _get_required_env("USER_POOL_ID")
        cognito = _get_cognito_client()

        # Find user and initiate reset
        username = _find_user_by_email(cognito, user_pool_id, email, logger)
        _initiate_password_reset(cognito, user_pool_id, username, email, logger)

        logger.info("Password reset initiated", email=email, username=username)
        return True

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_reset_user_password", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to reset password")


def _check_not_self_deletion(caller_id: str, account_id: str) -> None:
    """Prevent admin from deleting their own account."""
    if account_id == caller_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Cannot delete your own account")


def admin_delete_user(event: Dict[str, Any], context: Any) -> bool:
    """
    Delete user from Cognito and DynamoDB (admin only).

    AppSync Lambda resolver for adminDeleteUser mutation.
    Deletes user from Cognito User Pool and removes Account record from DynamoDB.

    Args:
        event: AppSync event with identity and arguments
        context: Lambda context

    Returns:
        True if user was deleted successfully

    Raises:
        AppError: If not admin, user not found, or deletion error
    """
    logger = get_logger(__name__)

    try:
        account_id = _validate_admin_and_get_account_id(event)

        identity = event.get("identity", {})
        caller_id = identity.get("sub")
        _check_not_self_deletion(str(caller_id), account_id)

        user_pool_id = _get_required_env("USER_POOL_ID")
        cognito = _get_cognito_client()

        username, email = _find_cognito_user_by_sub(cognito, user_pool_id, account_id, logger)
        if not username:
            raise AppError(ErrorCode.NOT_FOUND, f"User '{account_id}' not found in Cognito")

        _delete_user_from_cognito(cognito, user_pool_id, username, email or "", logger)
        _delete_account_from_dynamodb(account_id, logger)

        logger.info("User deleted successfully", account_id=account_id, email=email)
        return True

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_delete_user", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete user")


def _validate_and_process_product(product: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and process a catalog product, returning processed product dict."""
    product_name = product.get("productName", "").strip()
    price = product.get("price")
    sort_order = product.get("sortOrder", 0)

    if not product_name:
        raise AppError(ErrorCode.INVALID_INPUT, "Product name is required")
    if price is None or price < 0:
        raise AppError(ErrorCode.INVALID_INPUT, "Valid product price is required")

    processed_product: Dict[str, Any] = {
        "productId": f"PRODUCT#{uuid.uuid4()}",
        "productName": product_name,
        "price": Decimal(str(price)),
        "sortOrder": sort_order,
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


def _validate_admin_and_get_caller_id(event: Dict[str, Any]) -> str:
    """Validate admin access and extract caller ID."""
    if not is_admin(event):
        raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

    identity = event.get("identity", {})
    caller_id = identity.get("sub")
    if not caller_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")

    return str(caller_id)


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

    try:
        caller_id = _validate_admin_and_get_caller_id(event)

        arguments = event.get("arguments", {})
        catalog_input = arguments.get("input", {})

        catalog_name, is_public, products = _validate_catalog_input(catalog_input)

        catalog_id = f"CATALOG#{uuid.uuid4()}"
        now = datetime.now(timezone.utc).isoformat()

        processed_products = [_validate_and_process_product(product) for product in products]

        catalog_item = _build_catalog_item(catalog_id, catalog_name, is_public, caller_id, processed_products, now)

        _persist_catalog(catalog_item, logger)

        logger.info("Created managed catalog", catalog_id=catalog_id, catalog_name=catalog_name)

        return catalog_item

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in create_managed_catalog", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to create catalog")


def _delete_orders_for_campaign(campaign_id: str, logger: Any) -> int:
    """Delete all orders for a campaign. Returns count deleted."""
    orders_response = tables.orders.query(
        KeyConditionExpression="campaignId = :cid",
        ExpressionAttributeValues={":cid": campaign_id},
    )
    
    deleted_count = 0
    for order in orders_response.get("Items", []):
        tables.orders.delete_item(Key={"campaignId": campaign_id, "orderId": order["orderId"]})
        deleted_count += 1
    return deleted_count


def admin_delete_user_orders(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all orders for all campaigns of all profiles owned by a user (admin only).

    Returns the count of deleted orders.
    """
    logger = get_logger(__name__)

    try:
        account_id = _validate_admin_and_get_account_id(event)
        db_account_id = _normalize_account_id(account_id)
        deleted_count = 0

        # Get all profiles owned by this account
        profiles = _get_user_profiles(db_account_id, logger)

        for profile in profiles:
            profile_id = profile["profileId"]

            # Get all campaigns for this profile
            campaigns_response = tables.campaigns.query(
                KeyConditionExpression="profileId = :pid",
                ExpressionAttributeValues={":pid": profile_id},
            )

            for campaign in campaigns_response.get("Items", []):
                campaign_id = campaign["campaignId"]
                deleted_count += _delete_orders_for_campaign(campaign_id, logger)

        logger.info("Deleted user orders", account_id=account_id, count=deleted_count)
        return deleted_count

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_delete_user_orders", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete user orders")


def admin_delete_user_campaigns(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all campaigns for all profiles owned by a user (admin only).

    Returns the count of deleted campaigns.
    """
    logger = get_logger(__name__)

    try:
        account_id = _validate_admin_and_get_account_id(event)
        db_account_id = _normalize_account_id(account_id)
        deleted_count = 0

        # Get all profiles owned by this account
        profiles_response = tables.profiles.query(
            KeyConditionExpression="ownerAccountId = :owner",
            ExpressionAttributeValues={":owner": db_account_id},
        )

        for profile in profiles_response.get("Items", []):
            profile_id = profile["profileId"]

            # Get all campaigns for this profile
            campaigns_response = tables.campaigns.query(
                KeyConditionExpression="profileId = :pid",
                ExpressionAttributeValues={":pid": profile_id},
            )

            for campaign in campaigns_response.get("Items", []):
                tables.campaigns.delete_item(Key={"profileId": profile_id, "campaignId": campaign["campaignId"]})
                deleted_count += 1

        logger.info("Deleted user campaigns", account_id=account_id, count=deleted_count)
        return deleted_count

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_delete_user_campaigns", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete user campaigns")


def admin_delete_user_shares(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all shares for all profiles owned by a user (admin only).

    Returns the count of deleted shares.
    """
    logger = get_logger(__name__)

    try:
        account_id = _validate_admin_and_get_account_id(event)
        db_account_id = _normalize_account_id(account_id)
        deleted_count = 0

        # Get all profiles owned by this account
        profiles_response = tables.profiles.query(
            KeyConditionExpression="ownerAccountId = :owner",
            ExpressionAttributeValues={":owner": db_account_id},
        )

        for profile in profiles_response.get("Items", []):
            profile_id = profile["profileId"]

            # Get all shares for this profile
            shares_response = tables.shares.query(
                KeyConditionExpression="profileId = :pid",
                ExpressionAttributeValues={":pid": profile_id},
            )

            for share in shares_response.get("Items", []):
                tables.shares.delete_item(Key={"profileId": profile_id, "targetAccountId": share["targetAccountId"]})
                deleted_count += 1

        logger.info("Deleted user shares", account_id=account_id, count=deleted_count)
        return deleted_count

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_delete_user_shares", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete user shares")


def admin_delete_user_profiles(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all profiles owned by a user (admin only).

    Returns the count of deleted profiles.
    """
    logger = get_logger(__name__)

    try:
        account_id = _validate_admin_and_get_account_id(event)
        db_account_id = _normalize_account_id(account_id)
        deleted_count = 0

        # Get all profiles owned by this account
        profiles_response = tables.profiles.query(
            KeyConditionExpression="ownerAccountId = :owner",
            ExpressionAttributeValues={":owner": db_account_id},
        )

        for profile in profiles_response.get("Items", []):
            tables.profiles.delete_item(Key={"ownerAccountId": db_account_id, "profileId": profile["profileId"]})
            deleted_count += 1

        logger.info("Deleted user profiles", account_id=account_id, count=deleted_count)
        return deleted_count

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_delete_user_profiles", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete user profiles")


def _soft_delete_catalog(catalog_id: str) -> None:
    """Soft delete a catalog by setting isDeleted = true."""
    tables.catalogs.update_item(
        Key={"catalogId": catalog_id},
        UpdateExpression="SET isDeleted = :true",
        ExpressionAttributeValues={":true": True},
    )


def _scan_and_delete_catalogs(db_account_id: str) -> int:
    """Scan for user's catalogs and soft delete them. Returns count."""
    deleted_count = 0
    scan_kwargs: Dict[str, Any] = {
        "FilterExpression": "ownerAccountId = :owner AND (attribute_not_exists(isDeleted) OR isDeleted = :false)",
        "ExpressionAttributeValues": {":owner": db_account_id, ":false": False},
    }

    while True:
        response = tables.catalogs.scan(**scan_kwargs)

        for catalog in response.get("Items", []):
            _soft_delete_catalog(catalog["catalogId"])
            deleted_count += 1

        # Handle pagination
        if "LastEvaluatedKey" in response:
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        else:
            break

    return deleted_count


def admin_delete_user_catalogs(event: Dict[str, Any], context: Any) -> int:
    """
    Soft delete all catalogs owned by a user (admin only).

    Sets isDeleted=true on each catalog instead of removing from database.
    Returns the count of soft-deleted catalogs.
    """
    logger = get_logger(__name__)

    try:
        account_id = _validate_admin_and_get_account_id(event)
        db_account_id = _normalize_account_id(account_id)

        deleted_count = _scan_and_delete_catalogs(db_account_id)
        logger.info("Soft-deleted user catalogs", account_id=account_id, count=deleted_count)
        return deleted_count

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_delete_user_catalogs", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete user catalogs")


def admin_get_user_profiles(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all profiles owned by a user (admin only).

    Returns the list of profiles with full details.
    """
    logger = get_logger(__name__)

    try:
        account_id = _validate_admin_and_get_account_id(event)
        db_account_id = _normalize_account_id(account_id)

        # Query profiles by ownerAccountId
        response = tables.profiles.query(
            KeyConditionExpression="ownerAccountId = :owner",
            ExpressionAttributeValues={":owner": db_account_id},
        )

        profiles = response.get("Items", [])
        logger.info("Retrieved user profiles", account_id=account_id, count=len(profiles))
        return list(profiles)

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_get_user_profiles", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to get user profiles")


def admin_get_user_catalogs(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all catalogs owned by a user (admin only).

    Returns the list of catalogs with full details.
    """
    logger = get_logger(__name__)

    try:
        account_id = _validate_admin_and_get_account_id(event)
        db_account_id = _normalize_account_id(account_id)

        # Query catalogs by ownerAccountId using GSI
        response = tables.catalogs.query(
            IndexName="ownerAccountId-index",
            KeyConditionExpression="ownerAccountId = :owner",
            FilterExpression="attribute_not_exists(isDeleted) OR isDeleted = :false",
            ExpressionAttributeValues={
                ":owner": db_account_id,
                ":false": False,
            },
        )

        catalogs = response.get("Items", [])
        logger.info("Retrieved user catalogs", account_id=account_id, count=len(catalogs))
        return list(catalogs)

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_get_user_catalogs", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to get user catalogs")


def _get_user_profiles(db_account_id: str, logger: Any) -> list[Dict[str, Any]]:
    """Get all profiles owned by an account."""
    profiles_response = tables.profiles.query(
        KeyConditionExpression="ownerAccountId = :owner",
        ExpressionAttributeValues={":owner": db_account_id},
    )
    return list(profiles_response.get("Items", []))


def _get_campaigns_for_profiles(profiles: list[Dict[str, Any]], logger: Any) -> list[Dict[str, Any]]:
    """Query campaigns for each profile."""
    all_campaigns = []
    for profile in profiles:
        profile_id = profile.get("profileId")
        if profile_id:
            campaigns_response = tables.campaigns.query(
                KeyConditionExpression="profileId = :pid",
                ExpressionAttributeValues={":pid": profile_id},
            )
            campaigns = campaigns_response.get("Items", [])
            all_campaigns.extend(campaigns)
            logger.info("Retrieved campaigns for profile", profile_id=profile_id, count=len(campaigns))
    return all_campaigns


def admin_get_user_campaigns(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all campaigns for a user's profiles.

    Admin-only operation. Returns all campaigns across all profiles owned by the account.
    """
    logger = get_logger(__name__)

    try:
        account_id = _validate_admin_and_get_account_id(event)
        db_account_id = _normalize_account_id(account_id)

        # First, get all profiles owned by this account
        profiles = _get_user_profiles(db_account_id, logger)
        logger.info("Retrieved user profiles", account_id=account_id, count=len(profiles))

        # Now query campaigns for each profile
        all_campaigns = _get_campaigns_for_profiles(profiles, logger)
        logger.info("Retrieved user campaigns", account_id=account_id, count=len(all_campaigns))
        return all_campaigns

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_get_user_campaigns", error=str(e), exc_info=True)
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to get user campaigns")


def admin_get_user_shared_campaigns(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all shared campaigns created by a user.

    Admin-only operation.
    """
    logger = get_logger(__name__)

    try:
        account_id = _validate_admin_and_get_account_id(event)
        db_account_id = _normalize_account_id(account_id)

        # Query shared campaigns by createdBy using GSI1
        response = tables.shared_campaigns.query(
            IndexName="GSI1",
            KeyConditionExpression="createdBy = :creator",
            ExpressionAttributeValues={
                ":creator": db_account_id,
            },
        )

        campaigns = response.get("Items", [])
        logger.info("Retrieved user shared campaigns", account_id=account_id, count=len(campaigns))
        return list(campaigns)

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_get_user_shared_campaigns", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to get user shared campaigns")


def _convert_permissions_to_lists(shares: list[Dict[str, Any]]) -> None:
    """Convert DynamoDB permission sets to lists for JSON serialization."""
    for share in shares:
        if "permissions" in share and isinstance(share["permissions"], set):
            share["permissions"] = list(share["permissions"])


def _query_profile_shares(db_profile_id: str) -> list[Dict[str, Any]]:
    """Query all shares for a profile."""
    response = tables.shares.query(
        KeyConditionExpression="profileId = :pid",
        ExpressionAttributeValues={":pid": db_profile_id},
    )
    return list(response.get("Items", []))


def _validate_admin_and_get_profile_id(event: Dict[str, Any]) -> str:
    """Validate admin access and extract profile ID with prefix."""
    if not is_admin(event):
        raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

    arguments = event.get("arguments", {})
    profile_id = arguments.get("profileId", "").strip()

    if not profile_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Profile ID is required")

    # Add PROFILE# prefix if not present
    return profile_id if profile_id.startswith("PROFILE#") else f"PROFILE#{profile_id}"


def admin_get_profile_shares(event: Dict[str, Any], context: Any) -> list[Dict[str, Any]]:
    """
    Get all shares for a specific profile.

    Admin-only operation. Returns all users who have access to this profile.
    """
    logger = get_logger(__name__)

    try:
        db_profile_id = _validate_admin_and_get_profile_id(event)

        # Query shares and convert sets to lists
        shares = _query_profile_shares(db_profile_id)
        _convert_permissions_to_lists(shares)

        logger.info("Retrieved profile shares", profile_id=db_profile_id, count=len(shares))
        return shares

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_get_profile_shares", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to get profile shares")


def _normalize_profile_and_account_ids(profile_id: str, target_account_id: str) -> tuple[str, str]:
    """Normalize profile ID and target account ID with prefixes."""
    db_profile_id = profile_id if profile_id.startswith("PROFILE#") else f"PROFILE#{profile_id}"
    db_target_id = target_account_id if target_account_id.startswith("ACCOUNT#") else f"ACCOUNT#{target_account_id}"
    return db_profile_id, db_target_id


def _validate_and_get_share_ids(event: Dict[str, Any]) -> tuple[str, str]:
    """Validate admin and extract profile/account IDs."""
    if not is_admin(event):
        raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

    arguments = event.get("arguments", {})
    profile_id = arguments.get("profileId", "").strip()
    target_account_id = arguments.get("targetAccountId", "").strip()

    if not profile_id or not target_account_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Profile ID and target account ID are required")

    return profile_id, target_account_id


def admin_delete_share(event: Dict[str, Any], context: Any) -> bool:
    """
    Delete a specific share (revoke access).

    Admin-only operation. Allows admin to remove someone's access to a profile.
    """
    logger = get_logger(__name__)

    try:
        profile_id, target_account_id = _validate_and_get_share_ids(event)
        db_profile_id, db_target_id = _normalize_profile_and_account_ids(profile_id, target_account_id)

        tables.shares.delete_item(Key={"profileId": db_profile_id, "targetAccountId": db_target_id})

        logger.info("Deleted share", profile_id=profile_id, target_account_id=target_account_id)
        return True

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_delete_share", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete share")


def _get_campaign_profile_id(db_campaign_id: str, campaign_id: str) -> str:
    """Get profile ID for a campaign via GSI lookup."""
    response = tables.campaigns.query(
        IndexName="campaignId-index",
        KeyConditionExpression="campaignId = :cid",
        ExpressionAttributeValues={":cid": db_campaign_id},
    )

    items = response.get("Items", [])
    if not items:
        raise AppError(ErrorCode.NOT_FOUND, f"Campaign not found: {campaign_id}")

    return str(items[0]["profileId"])


def _update_campaign_shared_code(profile_id: str, db_campaign_id: str, shared_campaign_code: Optional[str]) -> None:
    """Update campaign's sharedCampaignCode field."""
    updated_at = datetime.now(timezone.utc).isoformat()
    
    if shared_campaign_code is None:
        update_expr = "REMOVE sharedCampaignCode SET updatedAt = :updated"
        expr_vals = {":updated": updated_at}
    else:
        update_expr = "SET sharedCampaignCode = :code, updatedAt = :updated"
        expr_vals = {":code": shared_campaign_code, ":updated": updated_at}

    tables.campaigns.update_item(
        Key={"profileId": profile_id, "campaignId": db_campaign_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_vals,
    )


def _validate_admin_and_get_campaign_id(event: Dict[str, Any]) -> tuple[str, Optional[str]]:
    """Validate admin access and extract campaign ID and shared code."""
    if not is_admin(event):
        raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

    arguments = event.get("arguments", {})
    campaign_id = arguments.get("campaignId", "").strip()
    shared_campaign_code = arguments.get("sharedCampaignCode")

    if not campaign_id:
        raise AppError(ErrorCode.INVALID_INPUT, "Campaign ID is required")

    return campaign_id, shared_campaign_code


def admin_update_campaign_shared_code(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Update a campaign's sharedCampaignCode field.

    Admin-only operation. Allows associating a campaign with a shared campaign.
    """
    logger = get_logger(__name__)

    try:
        campaign_id, shared_campaign_code = _validate_admin_and_get_campaign_id(event)

        # Add CAMPAIGN# prefix if not present
        db_campaign_id = campaign_id if campaign_id.startswith("CAMPAIGN#") else f"CAMPAIGN#{campaign_id}"

        # Get campaign and update shared code
        profile_id = _get_campaign_profile_id(db_campaign_id, campaign_id)
        _update_campaign_shared_code(profile_id, db_campaign_id, shared_campaign_code)

        # Return updated campaign
        updated_at = datetime.now(timezone.utc).isoformat()
        updated_campaign = {
            "campaignId": db_campaign_id,
            "profileId": profile_id,
            "sharedCampaignCode": shared_campaign_code,
            "updatedAt": updated_at,
        }

        logger.info("Updated campaign shared code", campaign_id=campaign_id, shared_campaign_code=shared_campaign_code)
        return updated_campaign

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_update_campaign_shared_code", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to update campaign shared code")


# Operation dispatcher map
_OPERATION_HANDLERS = {
    "adminListUsers": admin_list_users,
    "adminSearchUser": admin_search_user,
    "adminResetUserPassword": admin_reset_user_password,
    "adminDeleteUser": admin_delete_user,
    "adminDeleteUserOrders": admin_delete_user_orders,
    "adminDeleteUserCampaigns": admin_delete_user_campaigns,
    "adminDeleteUserShares": admin_delete_user_shares,
    "adminDeleteUserProfiles": admin_delete_user_profiles,
    "adminDeleteUserCatalogs": admin_delete_user_catalogs,
    "createManagedCatalog": create_managed_catalog,
    "adminGetUserProfiles": admin_get_user_profiles,
    "adminGetUserCatalogs": admin_get_user_catalogs,
    "adminGetUserCampaigns": admin_get_user_campaigns,
    "adminGetUserSharedCampaigns": admin_get_user_shared_campaigns,
    "adminGetProfileShares": admin_get_profile_shares,
    "adminDeleteShare": admin_delete_share,
    "adminUpdateCampaignSharedCode": admin_update_campaign_shared_code,
}


def lambda_handler(event: Dict[str, Any], context: Any) -> Any:
    """
    Main Lambda handler that dispatches to specific admin operations.

    Determines which operation to call based on the GraphQL field name.

    Args:
        event: AppSync event
        context: Lambda context

    Returns:
        Result from the specific operation handler
    """
    field_name = event.get("info", {}).get("fieldName", "")
    handler = _OPERATION_HANDLERS.get(field_name)
    
    if not handler:
        raise AppError(ErrorCode.INVALID_INPUT, f"Unknown admin operation: {field_name}")
    
    return handler(event, context)
