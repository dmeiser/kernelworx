"""Unit tests for account operations Lambda handler.

Updated for multi-table design (accounts table).
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import boto3
import pytest

from src.handlers.account_operations import update_my_account
from src.utils.errors import AppError, ErrorCode


def get_accounts_table() -> Any:
    """Get the accounts table for testing."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-accounts-ue1-dev")


class TestUpdateMyAccount:
    """Tests for update_my_account handler."""

    def test_update_given_name(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test updating givenName."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        # Create existing account
        accounts_table = get_accounts_table()
        account_id_key = f"ACCOUNT#{sample_account_id}"
        accounts_table.put_item(
            Item={
                "accountId": account_id_key,
                "email": "test@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "arguments": {"input": {"givenName": "John"}},
        }

        result = update_my_account(event, lambda_context)

        assert result["givenName"] == "John"
        assert result["accountId"] == account_id_key

    def test_update_multiple_fields(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test updating multiple fields at once."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        # Create existing account
        accounts_table = get_accounts_table()
        account_id_key = f"ACCOUNT#{sample_account_id}"
        accounts_table.put_item(
            Item={
                "accountId": account_id_key,
                "email": "test@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "arguments": {
                "input": {
                    "givenName": "John",
                    "familyName": "Doe",
                    "city": "Seattle",
                    "state": "WA",
                    "unitNumber": "123",
                }
            },
        }

        result = update_my_account(event, lambda_context)

        assert result["givenName"] == "John"
        assert result["accountId"] == account_id_key

    def test_update_no_fields_raises_error(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that empty input raises error."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        event = {
            **appsync_event,
            "arguments": {"input": {}},
        }

        with pytest.raises(AppError) as exc_info:
            update_my_account(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_update_nonexistent_account(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test updating non-existent account raises error."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        event = {
            **appsync_event,
            "arguments": {"input": {"givenName": "John"}},
        }

        with pytest.raises(AppError) as exc_info:
            update_my_account(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_database_error_propagates(
        self,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that database errors propagate."""

        mock_table = MagicMock()
        mock_table.update_item.side_effect = Exception("Database error")

        event = {
            **appsync_event,
            "arguments": {"input": {"givenName": "John"}},
        }

        with patch("src.handlers.account_operations.tables") as mock_tables:
            mock_tables.accounts = mock_table
            with pytest.raises(Exception, match="Database error"):
                update_my_account(event, lambda_context)

    def test_client_error_not_found(
        self,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that ClientError with other code propagates."""

        from botocore.exceptions import ClientError

        mock_table = MagicMock()
        error_response = {"Error": {"Code": "SomeOtherError", "Message": "Access Denied"}}
        mock_table.update_item.side_effect = ClientError(error_response, "UpdateItem")

        event = {
            **appsync_event,
            "arguments": {"input": {"givenName": "John"}},
        }

        with patch("src.handlers.account_operations.tables") as mock_tables:
            mock_tables.accounts = mock_table
            with pytest.raises(ClientError):
                update_my_account(event, lambda_context)

    def test_update_with_unit_type(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test updating account with unit type field."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        # Create existing account
        accounts_table = get_accounts_table()
        account_id_key = f"ACCOUNT#{sample_account_id}"
        accounts_table.put_item(
            Item={
                "accountId": account_id_key,
                "email": "test@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "arguments": {
                "input": {
                    "givenName": "Scout",
                    "unitType": "PACK",
                }
            },
        }

        result = update_my_account(event, lambda_context)

        assert result["givenName"] == "Scout"

        # Verify unitType was stored in DynamoDB even though it's not returned
        stored_item = accounts_table.get_item(Key={"accountId": account_id_key})
        assert stored_item["Item"]["unitType"] == "PACK"

    def test_update_with_invalid_unit_number(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test update with invalid unitNumber raises error."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        # Create existing account
        accounts_table = get_accounts_table()
        account_id_key = f"ACCOUNT#{sample_account_id}"
        accounts_table.put_item(
            Item={
                "accountId": account_id_key,
                "email": "test@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "arguments": {
                "input": {
                    "unitNumber": "not-a-number",
                }
            },
        }

        with pytest.raises(AppError) as exc_info:
            update_my_account(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "unitNumber must be a valid integer" in str(exc_info.value)

    def test_update_with_empty_unit_number(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test update with empty unitNumber (skips update)."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        # Create existing account
        accounts_table = get_accounts_table()
        account_id_key = f"ACCOUNT#{sample_account_id}"
        accounts_table.put_item(
            Item={
                "accountId": account_id_key,
                "email": "test@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **appsync_event,
            "arguments": {
                "input": {
                    "givenName": "Scout",
                    "unitNumber": "",  # Empty string should be skipped
                }
            },
        }

        result = update_my_account(event, lambda_context)

        assert result["givenName"] == "Scout"
        # Verify unitNumber was not set
        stored_item = accounts_table.get_item(Key={"accountId": account_id_key})
        assert "unitNumber" not in stored_item["Item"]

class TestDeleteMyAccount:
    """Tests for delete_my_account handler - comprehensive cascade deletion tests."""

    def test_delete_account_deletes_everything(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that deleting account deletes EVERYTHING - profiles, campaigns, orders, catalogs, shares."""
        from src.handlers.account_operations import delete_my_account

        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
        monkeypatch.setenv("USER_POOL_ID", "us-east-1_test123")

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")
        profiles_table = dynamodb.Table("kernelworx-profiles-v2-ue1-dev")
        campaigns_table = dynamodb.Table("kernelworx-campaigns-v2-ue1-dev")
        catalogs_table = dynamodb.Table("kernelworx-catalogs-ue1-dev")
        orders_table = dynamodb.Table("kernelworx-orders-v2-ue1-dev")
        shares_table = dynamodb.Table("kernelworx-shares-ue1-dev")

        account_id_key = f"ACCOUNT#{sample_account_id}"
        profile_id = "PROFILE#test-profile-123"
        campaign_id = "CAMPAIGN#test-campaign-123"
        catalog_id = "CATALOG#test-catalog-123"
        order_id = "ORDER#test-order-123"
        share_id = f"SHARE#{sample_account_id}#other-user"

        # 1. Create account
        accounts_table.put_item(
            Item={
                "accountId": account_id_key,
                "email": "test@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        # 2. Create profile (owned by test account)
        profiles_table.put_item(
            Item={
                "ownerAccountId": account_id_key,
                "profileId": profile_id,
                "sellerName": "Test Scout",
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        # 3. Create campaign (linked to profile)
        campaigns_table.put_item(
            Item={
                "profileId": profile_id,
                "campaignId": campaign_id,
                "campaignName": "Fall 2025",
                "catalogId": catalog_id,
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        # 4. Create CATALOG (owned by test account) - THIS IS CRITICAL
        catalogs_table.put_item(
            Item={
                "catalogId": catalog_id,
                "ownerAccountId": account_id_key,
                "catalogName": "Test Catalog",
                "products": [{"productId": "PROD1", "name": "Popcorn", "price": Decimal("10.0")}],
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "isDeleted": False,
            }
        )

        # 5. Create order (linked to campaign)
        orders_table.put_item(
            Item={
                "campaignId": campaign_id,
                "orderId": order_id,
                "profileId": profile_id,
                "customerName": "John Doe",
                "totalAmount": Decimal("10.0"),
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        # 6. Create share (profile shared with another user)
        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": f"ACCOUNT#other-user",
                "permissions": ["READ", "WRITE"],
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Verify all data exists before deletion
        assert accounts_table.get_item(Key={"accountId": account_id_key}).get("Item") is not None
        assert profiles_table.get_item(Key={"ownerAccountId": account_id_key, "profileId": profile_id}).get("Item") is not None
        assert campaigns_table.get_item(Key={"profileId": profile_id, "campaignId": campaign_id}).get("Item") is not None
        assert catalogs_table.get_item(Key={"catalogId": catalog_id}).get("Item") is not None
        assert orders_table.get_item(Key={"campaignId": campaign_id, "orderId": order_id}).get("Item") is not None
        assert shares_table.get_item(Key={"profileId": profile_id, "targetAccountId": f"ACCOUNT#other-user"}).get("Item") is not None

        # Mock Cognito client
        with patch("boto3.client") as mock_boto_client:
            mock_cognito = MagicMock()
            mock_boto_client.return_value = mock_cognito
            mock_cognito.list_users.return_value = {
                "Users": [{"Username": "testuser@example.com"}]
            }

            # Execute delete
            event = {
                **appsync_event,
                "identity": {
                    "sub": sample_account_id,
                    "claims": {"cognito:groups": ["ADMIN"]}  # Add admin claim for the pseudo event
                },
            }

            result = delete_my_account(event, lambda_context)
            assert result is True

        # Verify EVERYTHING is deleted
        # 1. Account record should be gone
        assert accounts_table.get_item(Key={"accountId": account_id_key}).get("Item") is None

        # 2. Profile should be gone
        assert profiles_table.get_item(Key={"ownerAccountId": account_id_key, "profileId": profile_id}).get("Item") is None

        # 3. Campaign should be gone
        assert campaigns_table.get_item(Key={"profileId": profile_id, "campaignId": campaign_id}).get("Item") is None

        # 4. CATALOG should be soft-deleted (isDeleted=true) - THIS IS CRITICAL
        catalog_item = catalogs_table.get_item(Key={"catalogId": catalog_id}).get("Item")
        assert catalog_item is not None, "Catalog should still exist but be marked as deleted"
        assert catalog_item.get("isDeleted") is True, "Catalog must have isDeleted=true"

        # 5. Order should be gone
        assert orders_table.get_item(Key={"campaignId": campaign_id, "orderId": order_id}).get("Item") is None

        # 6. Share should be gone (check all shares for the profile - should be empty)
        shares_response = shares_table.query(
            KeyConditionExpression="profileId = :pid",
            ExpressionAttributeValues={":pid": profile_id},
        )
        assert len(shares_response.get("Items", [])) == 0, "All shares should be deleted"

        # 7. Verify Cognito deletion was called
        mock_cognito.admin_delete_user.assert_called_once_with(
            UserPoolId="us-east-1_test123",
            Username="testuser@example.com"
        )

    def test_cannot_delete_another_users_account(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        another_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that a user cannot delete another user's account by impersonation."""
        from src.handlers.account_operations import delete_my_account

        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
        monkeypatch.setenv("USER_POOL_ID", "us-east-1_test123")

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")

        account_id_key_1 = f"ACCOUNT#{sample_account_id}"
        account_id_key_2 = f"ACCOUNT#{another_account_id}"

        # Create both accounts
        accounts_table.put_item(
            Item={
                "accountId": account_id_key_1,
                "email": "user1@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        accounts_table.put_item(
            Item={
                "accountId": account_id_key_2,
                "email": "user2@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Mock Cognito
        with patch("boto3.client") as mock_boto_client:
            mock_cognito = MagicMock()
            mock_boto_client.return_value = mock_cognito
            mock_cognito.list_users.return_value = {
                "Users": [{"Username": "user1@example.com"}]
            }

            # Try to delete as user1 (should succeed for their own account)
            event = {
                **appsync_event,
                "identity": {"sub": sample_account_id},
            }

            result = delete_my_account(event, lambda_context)
            assert result is True

            # Verify user1's account is deleted
            assert accounts_table.get_item(Key={"accountId": account_id_key_1}).get("Item") is None

            # Verify user2's account still exists (was not deleted)
            user2_item = accounts_table.get_item(Key={"accountId": account_id_key_2}).get("Item")
            assert user2_item is not None
            assert user2_item["email"] == "user2@example.com"

    def test_delete_account_with_multiple_profiles(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test deleting account with multiple profiles/campaigns/orders."""
        from src.handlers.account_operations import delete_my_account

        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
        monkeypatch.setenv("USER_POOL_ID", "us-east-1_test123")

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")
        profiles_table = dynamodb.Table("kernelworx-profiles-v2-ue1-dev")
        campaigns_table = dynamodb.Table("kernelworx-campaigns-v2-ue1-dev")
        orders_table = dynamodb.Table("kernelworx-orders-v2-ue1-dev")
        catalogs_table = dynamodb.Table("kernelworx-catalogs-ue1-dev")

        account_id_key = f"ACCOUNT#{sample_account_id}"

        # Create account
        accounts_table.put_item(
            Item={
                "accountId": account_id_key,
                "email": "test@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Create 3 profiles with campaigns and orders
        for i in range(3):
            profile_id = f"PROFILE#profile-{i}"
            campaign_id = f"CAMPAIGN#campaign-{i}"
            catalog_id = f"CATALOG#catalog-{i}"
            order_id = f"ORDER#order-{i}"

            # Profile
            profiles_table.put_item(
                Item={
                    "ownerAccountId": account_id_key,
                    "profileId": profile_id,
                    "sellerName": f"Scout {i}",
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                }
            )

            # Campaign
            campaigns_table.put_item(
                Item={
                    "profileId": profile_id,
                    "campaignId": campaign_id,
                    "campaignName": f"Campaign {i}",
                    "catalogId": catalog_id,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                }
            )

            # Catalog
            catalogs_table.put_item(
                Item={
                    "catalogId": catalog_id,
                    "ownerAccountId": account_id_key,
                    "catalogName": f"Catalog {i}",
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "isDeleted": False,
                }
            )

            # Order
            orders_table.put_item(
                Item={
                    "campaignId": campaign_id,
                    "orderId": order_id,
                    "profileId": profile_id,
                    "customerName": f"Customer {i}",
                    "totalAmount": Decimal("10.0") * (i + 1),
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                }
            )

        # Verify all items exist
        profiles_response = profiles_table.scan(
            FilterExpression="ownerAccountId = :owner",
            ExpressionAttributeValues={":owner": account_id_key}
        )
        assert len(profiles_response["Items"]) == 3

        campaigns_response = campaigns_table.scan()
        assert len(campaigns_response["Items"]) == 3

        orders_response = orders_table.scan()
        assert len(orders_response["Items"]) == 3

        catalogs_response = catalogs_table.scan(
            FilterExpression="ownerAccountId = :owner",
            ExpressionAttributeValues={":owner": account_id_key}
        )
        assert len(catalogs_response["Items"]) == 3

        # Mock Cognito and delete
        with patch("boto3.client") as mock_boto_client:
            mock_cognito = MagicMock()
            mock_boto_client.return_value = mock_cognito
            mock_cognito.list_users.return_value = {
                "Users": [{"Username": "testuser@example.com"}]
            }

            event = {
                **appsync_event,
                "identity": {"sub": sample_account_id},
            }

            result = delete_my_account(event, lambda_context)
            assert result is True

        # Verify everything is gone
        profiles_response = profiles_table.scan()
        assert len(profiles_response["Items"]) == 0

        campaigns_response = campaigns_table.scan()
        assert len(campaigns_response["Items"]) == 0

        orders_response = orders_table.scan()
        assert len(orders_response["Items"]) == 0

        # All catalogs should be soft-deleted
        catalogs_response = catalogs_table.scan()
        for catalog in catalogs_response["Items"]:
            assert catalog.get("isDeleted") is True

    def test_delete_account_with_no_data(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test deleting account with no associated data (clean account)."""
        from src.handlers.account_operations import delete_my_account

        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
        monkeypatch.setenv("USER_POOL_ID", "us-east-1_test123")

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")

        account_id_key = f"ACCOUNT#{sample_account_id}"

        # Create account only
        accounts_table.put_item(
            Item={
                "accountId": account_id_key,
                "email": "test@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Mock Cognito
        with patch("boto3.client") as mock_boto_client:
            mock_cognito = MagicMock()
            mock_boto_client.return_value = mock_cognito
            mock_cognito.list_users.return_value = {
                "Users": [{"Username": "testuser@example.com"}]
            }

            event = {
                **appsync_event,
                "identity": {"sub": sample_account_id},
            }

            result = delete_my_account(event, lambda_context)
            assert result is True

        # Verify account is deleted
        assert accounts_table.get_item(Key={"accountId": account_id_key}).get("Item") is None

        # Verify Cognito deletion was called
        mock_cognito.admin_delete_user.assert_called_once()

    def test_delete_account_cognito_user_not_found(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test deletion succeeds even if user not found in Cognito."""
        from src.handlers.account_operations import delete_my_account
        from botocore.exceptions import ClientError

        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
        monkeypatch.setenv("USER_POOL_ID", "us-east-1_test123")

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")

        account_id_key = f"ACCOUNT#{sample_account_id}"

        accounts_table.put_item(
            Item={
                "accountId": account_id_key,
                "email": "test@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Mock Cognito - user not found
        with patch("boto3.client") as mock_boto_client:
            mock_cognito = MagicMock()
            mock_boto_client.return_value = mock_cognito

            # Simulate user not found in list_users
            mock_cognito.list_users.return_value = {"Users": []}

            event = {
                **appsync_event,
                "identity": {"sub": sample_account_id},
            }

            # Should not raise error - just log warning
            result = delete_my_account(event, lambda_context)
            assert result is True

        # Account should still be deleted from DynamoDB
        assert accounts_table.get_item(Key={"accountId": account_id_key}).get("Item") is None

    def test_delete_account_missing_user_pool_id(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test deletion fails if USER_POOL_ID is not configured."""
        from src.handlers.account_operations import delete_my_account

        # Don't set USER_POOL_ID
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
        monkeypatch.delenv("USER_POOL_ID", raising=False)

        event = {
            **appsync_event,
            "identity": {"sub": sample_account_id},
        }

        with pytest.raises(AppError) as exc_info:
            delete_my_account(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert "USER_POOL_ID not configured" in str(exc_info.value)

    def test_delete_account_cognito_client_error(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test deletion handles Cognito client errors."""
        from src.handlers.account_operations import delete_my_account
        from botocore.exceptions import ClientError

        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
        monkeypatch.setenv("USER_POOL_ID", "us-east-1_test123")

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")

        account_id_key = f"ACCOUNT#{sample_account_id}"

        accounts_table.put_item(
            Item={
                "accountId": account_id_key,
                "email": "test@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Mock Cognito - raise error
        with patch("boto3.client") as mock_boto_client:
            mock_cognito = MagicMock()
            mock_boto_client.return_value = mock_cognito

            # Simulate Cognito error (not UserNotFoundException)
            error_response = {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}
            mock_cognito.list_users.side_effect = ClientError(error_response, "ListUsers")

            event = {
                **appsync_event,
                "identity": {"sub": sample_account_id},
            }

            with pytest.raises(AppError) as exc_info:
                delete_my_account(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
            assert "Failed to delete account from Cognito" in str(exc_info.value)
        # Account should still be deleted from DynamoDB
        assert accounts_table.get_item(Key={"accountId": account_id_key}).get("Item") is None

    def test_delete_account_cognito_admin_delete_error(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test deletion handles Cognito admin_delete_user errors (covers line 171)."""
        from src.handlers.account_operations import delete_my_account
        from botocore.exceptions import ClientError

        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
        monkeypatch.setenv("USER_POOL_ID", "us-east-1_test123")

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")

        account_id_key = f"ACCOUNT#{sample_account_id}"

        accounts_table.put_item(
            Item={
                "accountId": account_id_key,
                "email": "test@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Mock Cognito - list_users succeeds, admin_delete_user fails
        with patch("boto3.client") as mock_boto_client:
            mock_cognito = MagicMock()
            mock_boto_client.return_value = mock_cognito

            # list_users returns a user
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "test-user",
                        "Attributes": [{"Name": "sub", "Value": sample_account_id}],
                    }
                ]
            }

            # admin_delete_user raises non-UserNotFoundException error
            error_response = {"Error": {"Code": "InternalError", "Message": "Internal error"}}
            mock_cognito.admin_delete_user.side_effect = ClientError(error_response, "AdminDeleteUser")

            event = {
                **appsync_event,
                "identity": {"sub": sample_account_id},
            }

            # Should raise the error (line 171 re-raises), which is then caught and wrapped at line 211
            with pytest.raises(AppError) as exc_info:
                delete_my_account(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
            assert "Failed to delete account from Cognito" in str(exc_info.value)

    def test_delete_account_unexpected_exception(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test deletion handles unexpected exceptions (covers lines 213-215)."""
        from src.handlers.account_operations import delete_my_account

        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
        monkeypatch.setenv("USER_POOL_ID", "us-east-1_test123")

        # Mock Cognito
        with patch("boto3.client") as mock_boto_client:
            mock_cognito = MagicMock()
            mock_boto_client.return_value = mock_cognito

            # Mock an unexpected exception type (not ClientError)
            mock_cognito.list_users.side_effect = RuntimeError("Unexpected error")

            event = {
                **appsync_event,
                "identity": {"sub": sample_account_id},
            }

            # Should catch and wrap as AppError (lines 213-215)
            with pytest.raises(AppError) as exc_info:
                delete_my_account(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
            assert "Failed to delete account" in str(exc_info.value)

    def test_delete_account_cognito_user_not_found_exception(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test deletion handles UserNotFoundException gracefully (covers line 171 inverse branch)."""
        from src.handlers.account_operations import delete_my_account
        from botocore.exceptions import ClientError

        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
        monkeypatch.setenv("USER_POOL_ID", "us-east-1_test123")

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")

        account_id_key = f"ACCOUNT#{sample_account_id}"

        accounts_table.put_item(
            Item={
                "accountId": account_id_key,
                "email": "test@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Mock Cognito - list_users succeeds, admin_delete_user fails with UserNotFoundException
        with patch("boto3.client") as mock_boto_client:
            mock_cognito = MagicMock()
            mock_boto_client.return_value = mock_cognito

            # list_users returns a user
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "test-user",
                        "Attributes": [{"Name": "sub", "Value": sample_account_id}],
                    }
                ]
            }

            # admin_delete_user raises UserNotFoundException - should be swallowed (NOT re-raised)
            error_response = {"Error": {"Code": "UserNotFoundException", "Message": "User not found"}}
            mock_cognito.admin_delete_user.side_effect = ClientError(error_response, "AdminDeleteUser")

            event = {
                **appsync_event,
                "identity": {"sub": sample_account_id},
            }

            # Should succeed even though Cognito user wasn't found (already deleted)
            result = delete_my_account(event, lambda_context)
            
            assert result is True