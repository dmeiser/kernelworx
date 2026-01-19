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
from typing import Any, Dict

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

    if field_name == "adminListUsers":
        return admin_list_users(event, context)
    elif field_name == "adminSearchUser":
        return admin_search_user(event, context)
    elif field_name == "adminResetUserPassword":
        return admin_reset_user_password(event, context)
    elif field_name == "adminDeleteUser":
        return admin_delete_user(event, context)
    elif field_name == "adminDeleteUserOrders":
        return admin_delete_user_orders(event, context)
    elif field_name == "adminDeleteUserCampaigns":
        return admin_delete_user_campaigns(event, context)
    elif field_name == "adminDeleteUserShares":
        return admin_delete_user_shares(event, context)
    elif field_name == "adminDeleteUserProfiles":
        return admin_delete_user_profiles(event, context)
    elif field_name == "adminDeleteUserCatalogs":
        return admin_delete_user_catalogs(event, context)
    elif field_name == "createManagedCatalog":
        return create_managed_catalog(event, context)
    elif field_name == "adminGetUserProfiles":
        return admin_get_user_profiles(event, context)
    elif field_name == "adminGetUserCatalogs":
        return admin_get_user_catalogs(event, context)
    else:
        raise AppError(ErrorCode.INVALID_INPUT, f"Unknown admin operation: {field_name}")


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
        # Verify caller is admin
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        # Extract pagination arguments
        arguments = event.get("arguments", {})
        limit = arguments.get("limit", 20)  # Default 20 users per page
        next_token = arguments.get("nextToken")

        # Clamp limit to reasonable bounds
        limit = max(1, min(limit, 60))  # Cognito max is 60

        user_pool_id = _get_required_env("USER_POOL_ID")
        cognito = _get_cognito_client()

        # Build Cognito list_users request
        list_params: Dict[str, Any] = {
            "UserPoolId": user_pool_id,
            "Limit": limit,
        }
        if next_token:
            list_params["PaginationToken"] = next_token

        # Call Cognito list_users
        try:
            response = cognito.list_users(**list_params)
        except ClientError as e:
            logger.error("Cognito list_users failed", error=str(e))
            raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to list users")

        cognito_users = response.get("Users", [])
        pagination_token = response.get("PaginationToken")

        # Build list of AdminUser objects
        admin_users = []
        for cognito_user in cognito_users:
            # Extract Cognito attributes
            username = cognito_user.get("Username", "")
            attributes = {attr["Name"]: attr["Value"] for attr in cognito_user.get("Attributes", [])}

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
            display_name = None
            try:
                db_account_id = f"ACCOUNT#{account_id}"
                db_response = tables.accounts.get_item(Key={"accountId": db_account_id})
                if "Item" in db_response:
                    account = db_response["Item"]
                    given_name = str(account.get("givenName", ""))
                    family_name = str(account.get("familyName", ""))
                    if given_name or family_name:
                        display_name = f"{given_name} {family_name}".strip()
            except ClientError as e:
                logger.warning("Failed to get DynamoDB account", error=str(e), account_id=account_id)

            admin_user: Dict[str, Any] = {
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
            admin_users.append(admin_user)

        logger.info("Listed users", count=len(admin_users), has_more=bool(pagination_token))

        return {
            "users": admin_users,
            "nextToken": pagination_token,
        }

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_list_users", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to list users")


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
        # Verify caller is admin
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        # Extract query argument
        arguments = event.get("arguments", {})
        query = arguments.get("query", "").strip()

        if not query:
            raise AppError(ErrorCode.INVALID_INPUT, "Search query is required")

        user_pool_id = _get_required_env("USER_POOL_ID")
        cognito = _get_cognito_client()

        results_map: dict[str, Dict[str, Any]] = {}  # Use dict to deduplicate by accountId

        # Determine search strategy based on query format
        # If it looks like a UUID or ACCOUNT#UUID, search Cognito directly by sub
        if query.startswith("ACCOUNT#"):
            # Strip prefix for sub search
            sub_value = query[8:]  # Remove "ACCOUNT#"
            cognito_user = _search_user_by_sub(cognito, user_pool_id, sub_value, logger)
            if cognito_user:
                admin_user = _build_admin_user(cognito, user_pool_id, cognito_user, logger)
                results_map[admin_user["accountId"]] = admin_user
        elif _looks_like_uuid(query):
            # Search by sub directly
            cognito_user = _search_user_by_sub(cognito, user_pool_id, query, logger)
            if cognito_user:
                admin_user = _build_admin_user(cognito, user_pool_id, cognito_user, logger)
                results_map[admin_user["accountId"]] = admin_user
        else:
            # Search DynamoDB first with fuzzy matching (logged-in users)
            accounts = _search_accounts_in_dynamodb(query, logger)
            for account in accounts:
                # Extract sub from accountId (remove ACCOUNT# prefix)
                account_id = account.get("accountId", "")
                if account_id.startswith("ACCOUNT#"):
                    sub_value = account_id[8:]
                    cognito_user = _search_user_by_sub(cognito, user_pool_id, sub_value, logger)
                    if cognito_user:
                        admin_user = _build_admin_user(cognito, user_pool_id, cognito_user, logger)
                        results_map[admin_user["accountId"]] = admin_user

            # Also search Cognito directly (prefix matching on email)
            # This finds users who haven't logged in yet (no DynamoDB record)
            cognito_users = _search_users_in_cognito_by_email_prefix(cognito, user_pool_id, query, logger)
            for cognito_user in cognito_users:
                admin_user = _build_admin_user(cognito, user_pool_id, cognito_user, logger)
                # Only add if not already found via DynamoDB search (avoid duplicates)
                if admin_user["accountId"] not in results_map:
                    results_map[admin_user["accountId"]] = admin_user

        return list(results_map.values())

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_search_user", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to search user")


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
        # Use pagination to handle larger datasets
        paginator_params: Dict[str, Any] = {}
        scanned_count = 0
        max_scan = 1000  # Safety limit

        while scanned_count < max_scan and len(matches) < max_results:
            response = tables.accounts.scan(**paginator_params)
            items = response.get("Items", [])

            for item in items:
                if len(matches) >= max_results:
                    break
                # Case-insensitive partial match on email, givenName, familyName
                email = str(item.get("email", "")).lower()
                given_name = str(item.get("givenName", "")).lower()
                family_name = str(item.get("familyName", "")).lower()

                if query_lower in email or query_lower in given_name or query_lower in family_name:
                    matches.append(item)

            scanned_count += len(items)

            # Check for more pages
            if "LastEvaluatedKey" in response:
                paginator_params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
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
        return response.get("Users", [])
    except ClientError as e:
        logger.warning("Cognito email prefix search failed", error=str(e), query=query)
        return []


def _build_admin_user(cognito: Any, user_pool_id: str, cognito_user: Dict[str, Any], logger: Any) -> Dict[str, Any]:
    """Build an AdminUser object from Cognito user data."""
    # Extract Cognito attributes
    username = cognito_user.get("Username", "")
    attributes = {attr["Name"]: attr["Value"] for attr in cognito_user.get("Attributes", [])}

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
    display_name = None
    try:
        db_account_id = f"ACCOUNT#{account_id}"
        db_response = tables.accounts.get_item(Key={"accountId": db_account_id})
        if "Item" in db_response:
            account = db_response["Item"]
            given_name = str(account.get("givenName", ""))
            family_name = str(account.get("familyName", ""))
            if given_name or family_name:
                display_name = f"{given_name} {family_name}".strip()
    except ClientError as e:
        logger.warning("Failed to get DynamoDB account", error=str(e), account_id=account_id)

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
        # Verify caller is admin
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        # Extract arguments
        arguments = event.get("arguments", {})
        email = arguments.get("email", "").strip().lower()

        if not email:
            raise AppError(ErrorCode.INVALID_INPUT, "Email is required")

        user_pool_id = _get_required_env("USER_POOL_ID")
        cognito = _get_cognito_client()

        # Find user by email
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

        username = users[0]["Username"]

        # Initiate password reset
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

        logger.info("Password reset initiated", email=email, username=username)
        return True

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_reset_user_password", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to reset password")


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
        # Verify caller is admin
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        # Get caller ID to prevent self-deletion
        identity = event.get("identity", {})
        caller_id = identity.get("sub")

        # Extract arguments
        arguments = event.get("arguments", {})
        account_id = arguments.get("accountId", "").strip()

        if not account_id:
            raise AppError(ErrorCode.INVALID_INPUT, "Account ID is required")

        # Prevent self-deletion
        if account_id == caller_id:
            raise AppError(ErrorCode.INVALID_INPUT, "Cannot delete your own account")

        user_pool_id = _get_required_env("USER_POOL_ID")
        cognito = _get_cognito_client()

        # Try to find user in Cognito first using accountId (which is the Cognito sub)
        # The sub attribute is the unique identifier, but it's stored in user attributes
        username = None
        email = None

        # First, try to list users filtering by sub attribute
        try:
            users_response = cognito.list_users(
                UserPoolId=user_pool_id,
                Filter=f'sub = "{account_id}"',
                Limit=1,
            )
            users = users_response.get("Users", [])
            if users:
                username = users[0]["Username"]
                # Extract email from attributes
                attributes = {attr["Name"]: attr["Value"] for attr in users[0].get("Attributes", [])}
                email = attributes.get("email", "")
        except ClientError as e:
            logger.warning("Could not find Cognito user by sub", error=str(e), account_id=account_id)

        # If not found, the user doesn't exist in Cognito
        if not username:
            raise AppError(ErrorCode.NOT_FOUND, f"User '{account_id}' not found in Cognito")

        # Delete from Cognito
        try:
            cognito.admin_delete_user(
                UserPoolId=user_pool_id,
                Username=username,
            )
            logger.info("Deleted user from Cognito", username=username, email=email)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            logger.error("Cognito admin_delete_user failed", error=str(e), error_code=error_code)
            raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete user from Cognito")

        # Try to delete from DynamoDB if Account exists (users who never logged in won't have one)
        db_account_id = f"ACCOUNT#{account_id}"
        try:
            tables.accounts.delete_item(Key={"accountId": db_account_id})
            logger.info("Deleted account from DynamoDB", account_id=db_account_id)
        except ClientError as e:
            # If the account doesn't exist in DynamoDB, that's OK (user never logged in)
            logger.warning("Could not delete from DynamoDB (may not exist)", error=str(e), account_id=db_account_id)

        logger.info("User deleted successfully", account_id=account_id, email=email)
        return True

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_delete_user", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to delete user")


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
        # Verify caller is admin
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        # Extract caller identity
        identity = event.get("identity", {})
        caller_id = identity.get("sub")

        if not caller_id:
            raise AppError(ErrorCode.UNAUTHORIZED, "Authentication required")

        # Extract arguments
        arguments = event.get("arguments", {})
        catalog_input = arguments.get("input", {})

        catalog_name = catalog_input.get("catalogName", "").strip()
        is_public = catalog_input.get("isPublic", True)  # Default to public for managed catalogs
        products = catalog_input.get("products", [])

        # Validation
        if not catalog_name:
            raise AppError(ErrorCode.INVALID_INPUT, "Catalog name is required")

        if not products:
            raise AppError(ErrorCode.INVALID_INPUT, "Products array cannot be empty")

        # Generate IDs
        catalog_id = f"CATALOG#{uuid.uuid4()}"
        now = datetime.now(timezone.utc).isoformat()

        # Process products - add productId to each
        processed_products = []
        for product in products:
            product_name = product.get("productName", "").strip()
            price = product.get("price")
            sort_order = product.get("sortOrder", 0)

            if not product_name:
                raise AppError(ErrorCode.INVALID_INPUT, "Product name is required")
            if price is None or price < 0:
                raise AppError(ErrorCode.INVALID_INPUT, "Valid product price is required")

            # Convert price to Decimal for DynamoDB (floats not supported)
            price_decimal = Decimal(str(price))

            processed_product: Dict[str, Any] = {
                "productId": f"PRODUCT#{uuid.uuid4()}",
                "productName": product_name,
                "price": price_decimal,
                "sortOrder": sort_order,
            }

            description = product.get("description", "").strip()
            if description:
                processed_product["description"] = description

            processed_products.append(processed_product)

        # Create catalog item
        catalog_item = {
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

        # Write to DynamoDB
        try:
            tables.catalogs.put_item(Item=catalog_item)
        except ClientError as e:
            logger.error("Failed to create catalog", error=str(e))
            raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to create catalog")

        logger.info("Created managed catalog", catalog_id=catalog_id, catalog_name=catalog_name)

        return catalog_item

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in create_managed_catalog", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to create catalog")


def admin_delete_user_orders(event: Dict[str, Any], context: Any) -> int:
    """
    Delete all orders for all campaigns of all profiles owned by a user (admin only).

    Returns the count of deleted orders.
    """
    logger = get_logger(__name__)

    try:
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        arguments = event.get("arguments", {})
        account_id = arguments.get("accountId", "").strip()

        if not account_id:
            raise AppError(ErrorCode.INVALID_INPUT, "Account ID is required")

        db_account_id = f"ACCOUNT#{account_id}"
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
                campaign_id = campaign["campaignId"]

                # Delete all orders for this campaign
                orders_response = tables.orders.query(
                    KeyConditionExpression="campaignId = :cid",
                    ExpressionAttributeValues={":cid": campaign_id},
                )

                for order in orders_response.get("Items", []):
                    tables.orders.delete_item(Key={"campaignId": campaign_id, "orderId": order["orderId"]})
                    deleted_count += 1

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
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        arguments = event.get("arguments", {})
        account_id = arguments.get("accountId", "").strip()

        if not account_id:
            raise AppError(ErrorCode.INVALID_INPUT, "Account ID is required")

        db_account_id = f"ACCOUNT#{account_id}"
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
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        arguments = event.get("arguments", {})
        account_id = arguments.get("accountId", "").strip()

        if not account_id:
            raise AppError(ErrorCode.INVALID_INPUT, "Account ID is required")

        db_account_id = f"ACCOUNT#{account_id}"
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
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        arguments = event.get("arguments", {})
        account_id = arguments.get("accountId", "").strip()

        if not account_id:
            raise AppError(ErrorCode.INVALID_INPUT, "Account ID is required")

        db_account_id = f"ACCOUNT#{account_id}"
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


def admin_delete_user_catalogs(event: Dict[str, Any], context: Any) -> int:
    """
    Soft delete all catalogs owned by a user (admin only).

    Sets isDeleted=true on each catalog instead of removing from database.
    Returns the count of soft-deleted catalogs.
    """
    logger = get_logger(__name__)

    try:
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        arguments = event.get("arguments", {})
        account_id = arguments.get("accountId", "").strip()

        if not account_id:
            raise AppError(ErrorCode.INVALID_INPUT, "Account ID is required")

        db_account_id = f"ACCOUNT#{account_id}"
        deleted_count = 0

        # Scan catalogs table for catalogs owned by this account
        # Note: Catalogs don't have a GSI on ownerAccountId, so we need to scan
        scan_kwargs: Dict[str, Any] = {
            "FilterExpression": "ownerAccountId = :owner AND (attribute_not_exists(isDeleted) OR isDeleted = :false)",
            "ExpressionAttributeValues": {
                ":owner": db_account_id,
                ":false": False,
            },
        }

        while True:
            response = tables.catalogs.scan(**scan_kwargs)

            for catalog in response.get("Items", []):
                # Soft delete: set isDeleted = true
                tables.catalogs.update_item(
                    Key={"catalogId": catalog["catalogId"]},
                    UpdateExpression="SET isDeleted = :true",
                    ExpressionAttributeValues={":true": True},
                )
                deleted_count += 1

            # Handle pagination
            if "LastEvaluatedKey" in response:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            else:
                break

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
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        arguments = event.get("arguments", {})
        account_id = arguments.get("accountId", "").strip()

        if not account_id:
            raise AppError(ErrorCode.INVALID_INPUT, "Account ID is required")

        # Add ACCOUNT# prefix if not present
        db_account_id = account_id if account_id.startswith("ACCOUNT#") else f"ACCOUNT#{account_id}"

        # Query profiles by ownerAccountId
        response = tables.profiles.query(
            KeyConditionExpression="ownerAccountId = :owner",
            ExpressionAttributeValues={":owner": db_account_id},
        )

        profiles = response.get("Items", [])
        logger.info("Retrieved user profiles", account_id=account_id, count=len(profiles))
        return profiles

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
        if not is_admin(event):
            raise AppError(ErrorCode.FORBIDDEN, "Admin access required")

        arguments = event.get("arguments", {})
        account_id = arguments.get("accountId", "").strip()

        if not account_id:
            raise AppError(ErrorCode.INVALID_INPUT, "Account ID is required")

        # Add ACCOUNT# prefix if not present
        db_account_id = account_id if account_id.startswith("ACCOUNT#") else f"ACCOUNT#{account_id}"

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
        return catalogs

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error in admin_get_user_catalogs", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to get user catalogs")
