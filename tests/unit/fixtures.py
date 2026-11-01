"""
Test data builders for Lambda function tests.

Provides factory functions for creating test data with sensible defaults
and customization options. Use these to create test entities without
repeating boilerplate across test files.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import MagicMock
from uuid import uuid4


def make_account_id(suffix: Optional[str] = None) -> str:
    """Generate a unique account ID.

    Args:
        suffix: Optional suffix for predictable IDs in tests

    Returns:
        Account ID in format 'ACCOUNT#...'
    """
    if suffix:
        return f"ACCOUNT#{suffix}"
    return f"ACCOUNT#{uuid4().hex[:12]}"


def make_profile_id(suffix: Optional[str] = None) -> str:
    """Generate a unique profile ID.

    Args:
        suffix: Optional suffix for predictable IDs in tests

    Returns:
        Profile ID in format 'PROFILE#...'
    """
    if suffix:
        return f"PROFILE#{suffix}"
    return f"PROFILE#{uuid4().hex[:12]}"


def make_campaign_id(suffix: Optional[str] = None) -> str:
    """Generate a unique campaign ID.

    Args:
        suffix: Optional suffix for predictable IDs in tests

    Returns:
        Campaign ID in format 'CAMPAIGN#...'
    """
    if suffix:
        return f"CAMPAIGN#{suffix}"
    return f"CAMPAIGN#{uuid4().hex[:12]}"


def make_order_id(suffix: Optional[str] = None) -> str:
    """Generate a unique order ID.

    Args:
        suffix: Optional suffix for predictable IDs in tests

    Returns:
        Order ID in format 'ORDER#...'
    """
    if suffix:
        return f"ORDER#{suffix}"
    return f"ORDER#{uuid4().hex[:12]}"


def make_catalog_id(suffix: Optional[str] = None) -> str:
    """Generate a unique catalog ID.

    Args:
        suffix: Optional suffix for predictable IDs in tests

    Returns:
        Catalog ID in format 'CATALOG#...'
    """
    if suffix:
        return f"CATALOG#{suffix}"
    return f"CATALOG#{uuid4().hex[:12]}"


def make_invite_code() -> str:
    """Generate a random invite code.

    Returns:
        8-character uppercase invite code
    """
    return uuid4().hex[:8].upper()


def now_iso() -> str:
    """Get current UTC time as ISO string.

    Returns:
        ISO 8601 formatted UTC timestamp
    """
    return datetime.now(timezone.utc).isoformat()


def make_account(
    account_id: Optional[str] = None,
    email: Optional[str] = None,
    given_name: str = "Test",
    family_name: str = "User",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Create a test account dictionary.

    Args:
        account_id: Account ID (auto-generated if not provided)
        email: Email address (auto-generated if not provided)
        given_name: First name
        family_name: Last name
        **kwargs: Additional fields to include

    Returns:
        Account dictionary suitable for DynamoDB
    """
    if account_id is None:
        account_id = make_account_id()
    if email is None:
        email = f"test-{uuid4().hex[:8]}@example.com"

    account = {
        "accountId": account_id,
        "email": email,
        "givenName": given_name,
        "familyName": family_name,
        "isAdmin": False,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    account.update(kwargs)
    return account


def make_profile(
    profile_id: Optional[str] = None,
    owner_account_id: Optional[str] = None,
    seller_name: str = "Test Scout",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Create a test profile dictionary.

    Args:
        profile_id: Profile ID (auto-generated if not provided)
        owner_account_id: Owner account ID (auto-generated if not provided)
        seller_name: Name of the seller/scout
        **kwargs: Additional fields to include

    Returns:
        Profile dictionary suitable for DynamoDB
    """
    if profile_id is None:
        profile_id = make_profile_id()
    if owner_account_id is None:
        owner_account_id = make_account_id()

    profile = {
        "profileId": profile_id,
        "ownerAccountId": owner_account_id,
        "sellerName": seller_name,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    profile.update(kwargs)
    return profile


def make_campaign(
    campaign_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    campaign_name: str = "Fall Campaign",
    campaign_year: int = 2025,
    catalog_id: str = "CATALOG#default",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Create a test campaign dictionary.

    Args:
        campaign_id: Campaign ID (auto-generated if not provided)
        profile_id: Profile ID (auto-generated if not provided)
        campaign_name: Name of the campaign
        campaign_year: Year of the campaign
        catalog_id: Catalog ID for products
        **kwargs: Additional fields to include

    Returns:
        Campaign dictionary suitable for DynamoDB
    """
    if campaign_id is None:
        campaign_id = make_campaign_id()
    if profile_id is None:
        profile_id = make_profile_id()

    campaign = {
        "campaignId": campaign_id,
        "profileId": profile_id,
        "campaignName": campaign_name,
        "campaignYear": campaign_year,
        "catalogId": catalog_id,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    campaign.update(kwargs)
    return campaign


def make_order(
    order_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    customer_name: str = "Test Customer",
    customer_phone: str = "+15551234567",
    payment_method: str = "CASH",
    line_items: Optional[List[Dict[str, Any]]] = None,
    total_amount: float = 0.0,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Create a test order dictionary.

    Args:
        order_id: Order ID (auto-generated if not provided)
        campaign_id: Campaign ID (auto-generated if not provided)
        profile_id: Profile ID (auto-generated if not provided)
        customer_name: Name of the customer
        customer_phone: Customer phone number
        payment_method: Payment method (CASH, CHECK, etc.)
        line_items: List of order line items
        total_amount: Total order amount
        **kwargs: Additional fields to include

    Returns:
        Order dictionary suitable for DynamoDB
    """
    if order_id is None:
        order_id = make_order_id()
    if campaign_id is None:
        campaign_id = make_campaign_id()
    if profile_id is None:
        profile_id = make_profile_id()
    if line_items is None:
        line_items = []

    order = {
        "orderId": order_id,
        "campaignId": campaign_id,
        "profileId": profile_id,
        "customerName": customer_name,
        "customerPhone": customer_phone,
        "paymentMethod": payment_method,
        "lineItems": line_items,
        "totalAmount": total_amount,
        "orderDate": now_iso(),
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    order.update(kwargs)
    return order


def make_line_item(
    product_id: str = "PRODUCT#001",
    product_name: str = "Test Product",
    quantity: int = 1,
    unit_price: float = 10.0,
) -> Dict[str, Any]:
    """Create a test line item dictionary.

    Args:
        product_id: Product ID
        product_name: Product display name
        quantity: Number of items
        unit_price: Price per item

    Returns:
        Line item dictionary
    """
    return {
        "productId": product_id,
        "productName": product_name,
        "quantity": quantity,
        "unitPrice": unit_price,
        "totalPrice": quantity * unit_price,
    }


def make_share(
    profile_id: Optional[str] = None,
    target_account_id: Optional[str] = None,
    permissions: Optional[List[str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Create a test share dictionary.

    Args:
        profile_id: Profile ID being shared (auto-generated if not provided)
        target_account_id: Account ID receiving the share (auto-generated if not provided)
        permissions: List of permissions ['READ', 'WRITE']
        **kwargs: Additional fields to include

    Returns:
        Share dictionary suitable for DynamoDB
    """
    if profile_id is None:
        profile_id = make_profile_id()
    if target_account_id is None:
        target_account_id = make_account_id()
    if permissions is None:
        permissions = ["READ"]

    share = {
        "profileId": profile_id,
        "targetAccountId": target_account_id,
        "permissions": permissions,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    share.update(kwargs)
    return share


def make_invite(
    invite_code: Optional[str] = None,
    profile_id: Optional[str] = None,
    permissions: Optional[List[str]] = None,
    expires_at: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Create a test invite dictionary.

    Args:
        invite_code: Invite code (auto-generated if not provided)
        profile_id: Profile ID for the invite (auto-generated if not provided)
        permissions: List of permissions ['READ', 'WRITE']
        expires_at: Expiration timestamp (defaults to 14 days from now)
        **kwargs: Additional fields to include

    Returns:
        Invite dictionary suitable for DynamoDB
    """
    if invite_code is None:
        invite_code = make_invite_code()
    if profile_id is None:
        profile_id = make_profile_id()
    if permissions is None:
        permissions = ["READ"]
    if expires_at is None:
        # Default to 14 days from now
        expires_at = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + (14 * 24 * 60 * 60),
            tz=timezone.utc,
        ).isoformat()

    invite = {
        "inviteCode": invite_code,
        "profileId": profile_id,
        "permissions": permissions,
        "expiresAt": expires_at,
        "createdAt": now_iso(),
    }
    invite.update(kwargs)
    return invite


def make_catalog(
    catalog_id: Optional[str] = None,
    catalog_name: str = "Test Catalog",
    owner_account_id: Optional[str] = None,
    is_public: bool = False,
    products: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Create a test catalog dictionary.

    Args:
        catalog_id: Catalog ID (auto-generated if not provided)
        catalog_name: Name of the catalog
        owner_account_id: Owner account ID (auto-generated if not provided)
        is_public: Whether the catalog is public
        products: List of products in the catalog
        **kwargs: Additional fields to include

    Returns:
        Catalog dictionary suitable for DynamoDB
    """
    if catalog_id is None:
        catalog_id = make_catalog_id()
    if owner_account_id is None:
        owner_account_id = make_account_id()
    if products is None:
        products = []

    catalog = {
        "catalogId": catalog_id,
        "catalogName": catalog_name,
        "ownerAccountId": owner_account_id,
        "isPublic": is_public,
        "products": products,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    catalog.update(kwargs)
    return catalog


def make_product(
    product_id: Optional[str] = None,
    product_name: str = "Popcorn",
    price: float = 20.0,
    category: str = "Snacks",
    sku: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a test product dictionary.

    Args:
        product_id: Product ID (auto-generated if not provided)
        product_name: Product name
        price: Product price
        category: Product category
        sku: Stock keeping unit

    Returns:
        Product dictionary
    """
    if product_id is None:
        product_id = f"PRODUCT#{uuid4().hex[:8]}"
    if sku is None:
        sku = uuid4().hex[:6].upper()

    return {
        "productId": product_id,
        "productName": product_name,
        "price": price,
        "category": category,
        "sku": sku,
    }


def make_appsync_event(
    account_id: Optional[str] = None,
    arguments: Optional[Dict[str, Any]] = None,
    field_name: str = "testField",
    parent_type: str = "Query",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Create a test AppSync event dictionary.

    Args:
        account_id: Caller's account ID (Cognito sub, without ACCOUNT# prefix)
        arguments: GraphQL arguments
        field_name: Name of the GraphQL field being resolved
        parent_type: Type name (Query, Mutation, etc.)
        **kwargs: Additional fields to include

    Returns:
        AppSync event dictionary suitable for Lambda handlers
    """
    if account_id is None:
        account_id = uuid4().hex[:12]
    if arguments is None:
        arguments = {}

    event = {
        "arguments": arguments,
        "identity": {
            "sub": account_id,
            "username": f"user-{account_id[:8]}",
        },
        "requestContext": {
            "requestId": f"test-{uuid4().hex[:8]}",
        },
        "info": {
            "fieldName": field_name,
            "parentTypeName": parent_type,
        },
    }
    event.update(kwargs)
    return event


class MockLambdaContext:
    """Mock AWS Lambda context for testing.

    Provides the same interface as the actual Lambda context object.
    """

    def __init__(
        self,
        function_name: str = "test-function",
        memory_limit_in_mb: int = 128,
        aws_request_id: Optional[str] = None,
    ):
        self.function_name = function_name
        self.memory_limit_in_mb = memory_limit_in_mb
        self.aws_request_id = aws_request_id or f"test-{uuid4().hex[:8]}"
        self.invoked_function_arn = f"arn:aws:lambda:us-east-1:123456789012:function:{function_name}"

    def get_remaining_time_in_millis(self) -> int:
        """Return remaining execution time (mock returns 30 seconds)."""
        return 30000


def batch_delete_table(table_name: str = "test-table") -> MagicMock:
    """Build a mock DynamoDB Table whose client accepts BatchWriteItem deletes.

    ``batch_delete_keys`` drives BatchWriteItem through ``table.meta.client``
    rather than boto3's ``batch_writer`` so the UnprocessedItems retry is
    bounded; this scaffold gives a table that answers with no unprocessed items.
    Override ``table.meta.client.batch_write_item`` to simulate throttling.
    """
    table = MagicMock()
    table.name = table_name
    table.meta.client.batch_write_item.return_value = {"UnprocessedItems": {}}
    return table


def accept_batch_deletes(*tables: MagicMock) -> None:
    """Make each mock table's client answer BatchWriteItem with nothing unprocessed.

    Use on a patched ``tables`` module whose tables are plain MagicMocks; without
    this, ``batch_write_item`` returns a MagicMock whose ``UnprocessedItems`` is
    truthy and every delete looks throttled.
    """
    for table in tables:
        table.meta.client.batch_write_item.return_value = {"UnprocessedItems": {}}


def unprocessed_batches(table: MagicMock, requests: Sequence[Dict[str, Any]], attempts: int) -> None:
    """Make the next ``attempts`` BatchWriteItem calls report every item unprocessed.

    The call after that reports success, so a test can assert the retry both
    happens and eventually clears. Pass ``attempts`` at or above the production
    cap to exercise the "still unprocessed at the cap" path.
    """
    pending = list(requests)
    calls = {"count": 0}

    def _batch_write_item(RequestItems: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:  # noqa: N803
        calls["count"] += 1
        if calls["count"] <= attempts:
            return {"UnprocessedItems": {table.name: pending}}
        return {"UnprocessedItems": {}}

    table.meta.client.batch_write_item.side_effect = _batch_write_item
