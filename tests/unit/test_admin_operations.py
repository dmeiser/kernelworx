"""Unit tests for admin operations Lambda handler.

Tests for:
- adminListUsers
- adminResetUserPassword
- adminDeleteUser
- adminDeleteUserOrders
- adminDeleteUserCampaigns
- adminDeleteUserShares
- adminDeleteUserProfiles
- adminDeleteUserCatalogs
- createManagedCatalog
"""

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, call, patch

import boto3
import pytest
from botocore.exceptions import ClientError

from src.handlers.admin_operations import (
    admin_delete_user,
    admin_list_users,
    admin_reset_user_password,
    admin_search_user,
    create_managed_catalog,
    lambda_handler,
)
from src.utils.errors import AppError, ErrorCode


def get_accounts_table() -> Any:
    """Get the accounts table for testing."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-accounts-ue1-dev")


def get_catalogs_table() -> Any:
    """Get the catalogs table for testing."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-catalogs-ue1-dev")


@pytest.fixture
def admin_appsync_event(sample_account_id: str) -> Dict[str, Any]:
    """Base AppSync event structure for admin user."""
    return {
        "arguments": {},
        "identity": {
            "sub": sample_account_id,
            "username": "adminuser",
            "claims": {
                "cognito:groups": ["ADMIN"],
            },
        },
        "requestContext": {
            "requestId": "test-correlation-id",
        },
        "info": {
            "fieldName": "testField",
            "parentTypeName": "Mutation",
        },
    }


@pytest.fixture
def non_admin_appsync_event(sample_account_id: str) -> Dict[str, Any]:
    """Base AppSync event structure for non-admin user."""
    return {
        "arguments": {},
        "identity": {
            "sub": sample_account_id,
            "username": "regularuser",
            "claims": {},
        },
        "requestContext": {
            "requestId": "test-correlation-id",
        },
        "info": {
            "fieldName": "testField",
            "parentTypeName": "Mutation",
        },
    }


class TestLambdaHandler:
    """Tests for the main lambda_handler dispatcher."""

    def test_dispatch_admin_reset_user_password(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test dispatch to admin_reset_user_password."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminResetUserPassword"},
            "arguments": {"email": "test@example.com"},
        }

        # Mock Cognito
        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": "test-user-123"}]}
            mock_cognito.admin_reset_user_password.return_value = {}
            mock_get_client.return_value = mock_cognito

            result = lambda_handler(event, lambda_context)

            assert result is True

    def test_dispatch_admin_delete_user(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test dispatch to admin_delete_user."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-456"

        # Create target account
        accounts_table = get_accounts_table()
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{target_account_id}",
                "email": "target@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminDeleteUser"},
            "arguments": {"accountId": target_account_id},
        }

        # Mock Cognito
        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": "target-user-456"}]}
            mock_cognito.admin_delete_user.return_value = {}
            mock_get_client.return_value = mock_cognito

            result = lambda_handler(event, lambda_context)

            assert result is True

    def test_dispatch_create_managed_catalog(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test dispatch to create_managed_catalog."""
        monkeypatch.setenv("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "createManagedCatalog"},
            "arguments": {
                "input": {
                    "catalogName": "Test Catalog",
                    "products": [
                        {"productName": "Popcorn", "price": 10.00},
                    ],
                }
            },
        }

        result = lambda_handler(event, lambda_context)

        assert result["catalogName"] == "Test Catalog"
        assert result["catalogType"] == "ADMIN_MANAGED"

    def test_dispatch_admin_list_users(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test dispatch to admin_list_users."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminListUsers"},
            "arguments": {"limit": 10},
        }

        # Mock Cognito
        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": []}
            mock_cognito.admin_list_groups_for_user.return_value = {"Groups": []}
            mock_get_client.return_value = mock_cognito

            result = lambda_handler(event, lambda_context)

            assert "users" in result
            assert isinstance(result["users"], list)

    def test_dispatch_admin_delete_user_orders(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test dispatch to adminDeleteUserOrders."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")
        monkeypatch.setenv("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-ue1-dev")
        monkeypatch.setenv("ORDERS_TABLE_NAME", "kernelworx-orders-ue1-dev")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminDeleteUserOrders"},
            "arguments": {"accountId": "target-user-123"},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.profiles.query.return_value = {"Items": []}

            result = lambda_handler(event, lambda_context)

            assert result == 0

    def test_dispatch_admin_delete_user_campaigns(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test dispatch to adminDeleteUserCampaigns."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")
        monkeypatch.setenv("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-ue1-dev")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminDeleteUserCampaigns"},
            "arguments": {"accountId": "target-user-123"},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.profiles.query.return_value = {"Items": []}

            result = lambda_handler(event, lambda_context)

            assert result == 0

    def test_dispatch_admin_delete_user_shares(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test dispatch to adminDeleteUserShares."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")
        monkeypatch.setenv("SHARES_TABLE_NAME", "kernelworx-shares-ue1-dev")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminDeleteUserShares"},
            "arguments": {"accountId": "target-user-123"},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.profiles.query.return_value = {"Items": []}

            result = lambda_handler(event, lambda_context)

            assert result == 0

    def test_dispatch_admin_delete_user_profiles(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test dispatch to adminDeleteUserProfiles."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminDeleteUserProfiles"},
            "arguments": {"accountId": "target-user-123"},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.profiles.query.return_value = {"Items": []}

            result = lambda_handler(event, lambda_context)

            assert result == 0

    def test_dispatch_admin_delete_user_catalogs(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test dispatch to adminDeleteUserCatalogs."""
        monkeypatch.setenv("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminDeleteUserCatalogs"},
            "arguments": {"accountId": "target-user-123"},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.catalogs.scan.return_value = {"Items": []}

            result = lambda_handler(event, lambda_context)

            assert result == 0

    def test_dispatch_unknown_operation_raises_error(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that unknown operation raises error."""
        event = {
            **admin_appsync_event,
            "info": {"fieldName": "unknownOperation"},
        }

        with pytest.raises(AppError) as exc_info:
            lambda_handler(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Unknown admin operation" in exc_info.value.message


class TestAdminListUsers:
    """Tests for admin_list_users handler."""

    def test_success_returns_users(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test successful listing of users with all fields."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        user_id = "user-123"
        user_created = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        user_modified = datetime(2024, 6, 15, 9, 30, 0, tzinfo=timezone.utc)

        # Create account in DynamoDB for display name
        accounts_table = get_accounts_table()
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{user_id}",
                "email": "user@example.com",
                "givenName": "John",
                "familyName": "Doe",
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **admin_appsync_event,
            "arguments": {"limit": 20},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": user_id,
                        "Attributes": [
                            {"Name": "sub", "Value": user_id},
                            {"Name": "email", "Value": "user@example.com"},
                            {"Name": "email_verified", "Value": "true"},
                        ],
                        "UserStatus": "CONFIRMED",
                        "Enabled": True,
                        "UserCreateDate": user_created,
                        "UserLastModifiedDate": user_modified,
                    }
                ],
            }
            mock_cognito.admin_list_groups_for_user.return_value = {"Groups": [{"GroupName": "ADMIN"}]}
            mock_get_client.return_value = mock_cognito

            result = admin_list_users(event, lambda_context)

            assert "users" in result
            assert len(result["users"]) == 1

            user = result["users"][0]
            assert user["accountId"] == user_id
            assert user["email"] == "user@example.com"
            assert user["displayName"] == "John Doe"
            assert user["status"] == "CONFIRMED"
            assert user["enabled"] is True
            assert user["emailVerified"] is True
            assert user["isAdmin"] is True
            assert user["createdAt"] == user_created.isoformat()
            assert user["lastModifiedAt"] == user_modified.isoformat()

    def test_success_with_pagination(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test pagination with nextToken."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"limit": 5, "nextToken": "page1token"},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "user-1",
                        "Attributes": [
                            {"Name": "sub", "Value": "user-1"},
                            {"Name": "email", "Value": "user1@example.com"},
                        ],
                        "UserStatus": "CONFIRMED",
                        "Enabled": True,
                        "UserCreateDate": datetime.now(timezone.utc),
                    }
                ],
                "PaginationToken": "page2token",
            }
            mock_cognito.admin_list_groups_for_user.return_value = {"Groups": []}
            mock_get_client.return_value = mock_cognito

            result = admin_list_users(event, lambda_context)

            assert result["nextToken"] == "page2token"
            mock_cognito.list_users.assert_called_once_with(
                UserPoolId="test-pool-id",
                Limit=5,
                PaginationToken="page1token",
            )

    def test_success_no_dynamodb_account(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test user listing when no DynamoDB account exists (new user)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "new-user-456",
                        "Attributes": [
                            {"Name": "sub", "Value": "new-user-456"},
                            {"Name": "email", "Value": "newuser@example.com"},
                        ],
                        "UserStatus": "FORCE_CHANGE_PASSWORD",
                        "Enabled": True,
                        "UserCreateDate": datetime.now(timezone.utc),
                    }
                ],
            }
            mock_cognito.admin_list_groups_for_user.return_value = {"Groups": []}
            mock_get_client.return_value = mock_cognito

            result = admin_list_users(event, lambda_context)

            assert len(result["users"]) == 1
            user = result["users"][0]
            assert user["displayName"] is None  # No DynamoDB account
            assert user["status"] == "FORCE_CHANGE_PASSWORD"
            assert user["isAdmin"] is False

    def test_success_dynamodb_account_without_name(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test user listing when DynamoDB account exists but has no given/family name."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        user_id = "user-no-name"

        # Create account in DynamoDB WITHOUT givenName or familyName
        accounts_table = get_accounts_table()
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{user_id}",
                "email": "noname@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                # Note: no givenName or familyName
            }
        )

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": user_id,
                        "Attributes": [
                            {"Name": "sub", "Value": user_id},
                            {"Name": "email", "Value": "noname@example.com"},
                        ],
                        "UserStatus": "CONFIRMED",
                        "Enabled": True,
                        "UserCreateDate": datetime.now(timezone.utc),
                    }
                ],
            }
            mock_cognito.admin_list_groups_for_user.return_value = {"Groups": []}
            mock_get_client.return_value = mock_cognito

            result = admin_list_users(event, lambda_context)

            assert len(result["users"]) == 1
            user = result["users"][0]
            # Account exists but has no name, so displayName should be None
            assert user["displayName"] is None
            assert user["email"] == "noname@example.com"

    def test_success_empty_user_list(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test empty user list."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": []}
            mock_get_client.return_value = mock_cognito

            result = admin_list_users(event, lambda_context)

            assert result["users"] == []
            assert result["nextToken"] is None

    def test_limit_clamped_to_max(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that limit is clamped to max 60."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"limit": 100},  # Over max
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": []}
            mock_get_client.return_value = mock_cognito

            admin_list_users(event, lambda_context)

            mock_cognito.list_users.assert_called_once_with(
                UserPoolId="test-pool-id",
                Limit=60,  # Clamped to max
            )

    def test_limit_clamped_to_min(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that limit is clamped to min 1."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"limit": -5},  # Below min
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": []}
            mock_get_client.return_value = mock_cognito

            admin_list_users(event, lambda_context)

            mock_cognito.list_users.assert_called_once_with(
                UserPoolId="test-pool-id",
                Limit=1,  # Clamped to min
            )

    def test_non_admin_forbidden(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that non-admin user gets forbidden error."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **non_admin_appsync_event,
            "arguments": {},
        }

        with pytest.raises(AppError) as exc_info:
            admin_list_users(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN
        assert "Admin access required" in exc_info.value.message

    def test_missing_user_pool_id_env(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test error when USER_POOL_ID is missing."""
        monkeypatch.delenv("USER_POOL_ID", raising=False)

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with pytest.raises(AppError) as exc_info:
            admin_list_users(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert "USER_POOL_ID" in exc_info.value.message

    def test_cognito_list_users_error(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test handling of Cognito list_users error."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.side_effect = ClientError(
                {"Error": {"Code": "InternalErrorException", "Message": "Internal error"}},
                "ListUsers",
            )
            mock_get_client.return_value = mock_cognito

            with pytest.raises(AppError) as exc_info:
                admin_list_users(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
            assert "Failed to list users" in exc_info.value.message

    def test_group_lookup_error_handled_gracefully(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that group lookup errors are handled gracefully (user still returned)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "user-1",
                        "Attributes": [
                            {"Name": "sub", "Value": "user-1"},
                            {"Name": "email", "Value": "user@example.com"},
                        ],
                        "UserStatus": "CONFIRMED",
                        "Enabled": True,
                        "UserCreateDate": datetime.now(timezone.utc),
                    }
                ],
            }
            # Group lookup fails
            mock_cognito.admin_list_groups_for_user.side_effect = ClientError(
                {"Error": {"Code": "InternalErrorException", "Message": "Error"}},
                "AdminListGroupsForUser",
            )
            mock_get_client.return_value = mock_cognito

            result = admin_list_users(event, lambda_context)

            # User should still be returned, but isAdmin should be False
            assert len(result["users"]) == 1
            assert result["users"][0]["isAdmin"] is False

    def test_multiple_users_with_mixed_admin_status(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test listing multiple users with different admin statuses."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        def mock_groups(UserPoolId: str, Username: str) -> Dict[str, Any]:
            if Username == "admin-user":
                return {"Groups": [{"GroupName": "ADMIN"}]}
            return {"Groups": []}

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "admin-user",
                        "Attributes": [
                            {"Name": "sub", "Value": "admin-user"},
                            {"Name": "email", "Value": "admin@example.com"},
                        ],
                        "UserStatus": "CONFIRMED",
                        "Enabled": True,
                        "UserCreateDate": datetime.now(timezone.utc),
                    },
                    {
                        "Username": "regular-user",
                        "Attributes": [
                            {"Name": "sub", "Value": "regular-user"},
                            {"Name": "email", "Value": "regular@example.com"},
                        ],
                        "UserStatus": "CONFIRMED",
                        "Enabled": True,
                        "UserCreateDate": datetime.now(timezone.utc),
                    },
                ],
            }
            mock_cognito.admin_list_groups_for_user.side_effect = mock_groups
            mock_get_client.return_value = mock_cognito

            result = admin_list_users(event, lambda_context)

            assert len(result["users"]) == 2

            admin_user = next(u for u in result["users"] if u["accountId"] == "admin-user")
            regular_user = next(u for u in result["users"] if u["accountId"] == "regular-user")

            assert admin_user["isAdmin"] is True
            assert regular_user["isAdmin"] is False

    def test_dynamodb_lookup_error_handled_gracefully(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that DynamoDB lookup errors are handled gracefully.

        When DynamoDB get_item fails with a ClientError, the code logs a warning
        and continues with displayName=None.
        """
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "user-123",
                        "Attributes": [
                            {"Name": "sub", "Value": "user-123"},
                            {"Name": "email", "Value": "user@example.com"},
                        ],
                        "UserStatus": "CONFIRMED",
                        "Enabled": True,
                        "UserCreateDate": datetime.now(timezone.utc),
                    }
                ],
            }
            mock_cognito.admin_list_groups_for_user.return_value = {"Groups": []}
            mock_get_client.return_value = mock_cognito

            with patch("src.handlers.admin_operations.tables") as mock_tables:
                # Simulate DynamoDB ClientError
                mock_tables.accounts.get_item.side_effect = ClientError(
                    {"Error": {"Code": "InternalServerError", "Message": "DB error"}},
                    "GetItem",
                )

                result = admin_list_users(event, lambda_context)

                # User should still be returned, but displayName should be None
                assert len(result["users"]) == 1
                assert result["users"][0]["displayName"] is None
                assert result["users"][0]["email"] == "user@example.com"

    def test_unexpected_exception_handled(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test handling of unexpected exceptions."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            # Raise a generic exception
            mock_cognito.list_users.side_effect = RuntimeError("Unexpected error")
            mock_get_client.return_value = mock_cognito

            with pytest.raises(AppError) as exc_info:
                admin_list_users(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
            assert "Failed to list users" in exc_info.value.message


class TestAdminResetUserPassword:
    """Tests for admin_reset_user_password handler."""

    def test_success(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test successful password reset."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"email": "test@example.com"},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": "test-user-123"}]}
            mock_cognito.admin_reset_user_password.return_value = {}
            mock_get_client.return_value = mock_cognito

            result = admin_reset_user_password(event, lambda_context)

            assert result is True
            mock_cognito.admin_reset_user_password.assert_called_once_with(
                UserPoolId="test-pool-id",
                Username="test-user-123",
            )

    def test_email_trimmed_and_lowercased(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that email is trimmed and lowercased."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"email": "  TEST@EXAMPLE.COM  "},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": "test-user-123"}]}
            mock_cognito.admin_reset_user_password.return_value = {}
            mock_get_client.return_value = mock_cognito

            result = admin_reset_user_password(event, lambda_context)

            assert result is True
            mock_cognito.list_users.assert_called_once_with(
                UserPoolId="test-pool-id",
                Filter='email = "test@example.com"',
                Limit=1,
            )

    def test_non_admin_forbidden(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that non-admin gets forbidden error."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **non_admin_appsync_event,
            "arguments": {"email": "test@example.com"},
        }

        with pytest.raises(AppError) as exc_info:
            admin_reset_user_password(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN
        assert "Admin access required" in exc_info.value.message

    def test_empty_email_raises_error(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that empty email raises error."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"email": "   "},
        }

        with pytest.raises(AppError) as exc_info:
            admin_reset_user_password(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Email is required" in exc_info.value.message

    def test_user_not_found(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that user not found raises error."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"email": "notfound@example.com"},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": []}
            mock_get_client.return_value = mock_cognito

            with pytest.raises(AppError) as exc_info:
                admin_reset_user_password(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_missing_user_pool_id_raises_error(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that missing USER_POOL_ID raises error."""
        monkeypatch.delenv("USER_POOL_ID", raising=False)

        event = {
            **admin_appsync_event,
            "arguments": {"email": "test@example.com"},
        }

        with pytest.raises(AppError) as exc_info:
            admin_reset_user_password(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert "USER_POOL_ID" in exc_info.value.message

    def test_cognito_list_users_error(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that Cognito list_users error is handled."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"email": "test@example.com"},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.side_effect = ClientError(
                {"Error": {"Code": "InternalErrorException", "Message": "Test error"}},
                "ListUsers",
            )
            mock_get_client.return_value = mock_cognito

            with pytest.raises(AppError) as exc_info:
                admin_reset_user_password(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_cognito_reset_user_not_found(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that UserNotFoundException from reset is handled."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"email": "test@example.com"},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": "test-user-123"}]}
            mock_cognito.admin_reset_user_password.side_effect = ClientError(
                {"Error": {"Code": "UserNotFoundException", "Message": "User not found"}},
                "AdminResetUserPassword",
            )
            mock_get_client.return_value = mock_cognito

            with pytest.raises(AppError) as exc_info:
                admin_reset_user_password(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_cognito_invalid_parameter_exception(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that InvalidParameterException from reset is handled."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"email": "test@example.com"},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": "test-user-123"}]}
            mock_cognito.admin_reset_user_password.side_effect = ClientError(
                {"Error": {"Code": "InvalidParameterException", "Message": "Invalid param"}},
                "AdminResetUserPassword",
            )
            mock_get_client.return_value = mock_cognito

            with pytest.raises(AppError) as exc_info:
                admin_reset_user_password(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_cognito_other_error_during_reset(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that other Cognito errors during reset are handled."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"email": "test@example.com"},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": "test-user-123"}]}
            mock_cognito.admin_reset_user_password.side_effect = ClientError(
                {"Error": {"Code": "LimitExceededException", "Message": "Rate limited"}},
                "AdminResetUserPassword",
            )
            mock_get_client.return_value = mock_cognito

            with pytest.raises(AppError) as exc_info:
                admin_reset_user_password(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_unexpected_exception_handled(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that unexpected exceptions are handled."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"email": "test@example.com"},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.side_effect = RuntimeError("Unexpected error")
            mock_get_client.return_value = mock_cognito

            with pytest.raises(AppError) as exc_info:
                admin_reset_user_password(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR


class TestAdminDeleteUser:
    """Tests for admin_delete_user handler."""

    def test_success(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test successful user deletion."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-456"

        # Create target account
        accounts_table = get_accounts_table()
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{target_account_id}",
                "email": "target@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            # Mock Cognito list_users to find user by sub
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "cognito-username-123",
                        "Attributes": [
                            {"Name": "sub", "Value": target_account_id},
                            {"Name": "email", "Value": "target@example.com"},
                        ],
                    }
                ]
            }
            mock_cognito.admin_delete_user.return_value = {}
            mock_get_client.return_value = mock_cognito

            result = admin_delete_user(event, lambda_context)

            assert result is True

            # Verify Cognito user was deleted
            mock_cognito.admin_delete_user.assert_called_once_with(
                UserPoolId="test-pool-id", Username="cognito-username-123"
            )

            # Verify account was deleted from DynamoDB
            response = accounts_table.get_item(Key={"accountId": f"ACCOUNT#{target_account_id}"})
            assert "Item" not in response

    def test_success_with_account_prefix(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test successful user deletion when user hasn't logged in yet (no DynamoDB Account)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        # accountId in GraphQL is the UUID (without ACCOUNT# prefix)
        target_account_id = "target-user-789"

        # Don't create Account in DynamoDB (user never logged in)

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            # Mock Cognito list_users to find user by sub
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "cognito-username-789",
                        "Attributes": [
                            {"Name": "sub", "Value": target_account_id},
                            {"Name": "email", "Value": "neverloggedin@example.com"},
                        ],
                    }
                ]
            }
            mock_cognito.admin_delete_user.return_value = {}
            mock_get_client.return_value = mock_cognito

            result = admin_delete_user(event, lambda_context)

            assert result is True

            # Verify Cognito user was deleted
            mock_cognito.admin_delete_user.assert_called_once_with(
                UserPoolId="test-pool-id", Username="cognito-username-789"
            )

    def test_non_admin_forbidden(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that non-admin gets forbidden error."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **non_admin_appsync_event,
            "arguments": {"accountId": "target-user-456"},
        }

        with pytest.raises(AppError) as exc_info:
            admin_delete_user(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN

    def test_empty_account_id_raises_error(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that empty account ID raises error."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": "   "},
        }

        with pytest.raises(AppError) as exc_info:
            admin_delete_user(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Account ID is required" in exc_info.value.message

    def test_self_deletion_prevented(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        sample_account_id: str,
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that admin cannot delete their own account."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": sample_account_id},
        }

        with pytest.raises(AppError) as exc_info:
            admin_delete_user(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Cannot delete your own account" in exc_info.value.message

    def test_account_not_found(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that non-existent user (not in Cognito) raises error."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": "nonexistent-user"},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            # User not found in Cognito
            mock_cognito.list_users.return_value = {"Users": []}
            mock_get_client.return_value = mock_cognito

            with pytest.raises(AppError) as exc_info:
                admin_delete_user(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_cognito_user_not_found_continues(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that if Cognito delete fails with UserNotFoundException, it raises an error."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-456"

        # Create target account
        accounts_table = get_accounts_table()
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{target_account_id}",
                "email": "target@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            # Mock list_users to return a valid user with attributes
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "target-user-456",
                        "Attributes": [
                            {"Name": "sub", "Value": target_account_id},
                            {"Name": "email", "Value": "target@example.com"},
                        ],
                    }
                ]
            }
            mock_cognito.admin_delete_user.side_effect = ClientError(
                {"Error": {"Code": "UserNotFoundException", "Message": "User not found"}},
                "AdminDeleteUser",
            )
            mock_get_client.return_value = mock_cognito

            # Now expect an INTERNAL_ERROR because Cognito delete failed
            with pytest.raises(AppError) as exc_info:
                admin_delete_user(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_cognito_delete_error_raises(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that Cognito delete errors raise exception."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-456"

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            # Mock Cognito list_users to find user
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "cognito-username-456",
                        "Attributes": [
                            {"Name": "sub", "Value": target_account_id},
                            {"Name": "email", "Value": "target@example.com"},
                        ],
                    }
                ]
            }
            # Mock delete to fail with non-UserNotFound error
            mock_cognito.admin_delete_user.side_effect = ClientError(
                {"Error": {"Code": "InternalError", "Message": "Internal error"}},
                "AdminDeleteUser",
            )
            mock_get_client.return_value = mock_cognito

            with pytest.raises(AppError) as exc_info:
                admin_delete_user(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_self_deletion_prevented(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that admin cannot delete their own account."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        # Try to delete own account (caller ID matches target)
        event = {
            **admin_appsync_event,
            "arguments": {"accountId": "user-123-456"},  # Same as caller in fixture
        }

        with pytest.raises(AppError) as exc_info:
            admin_delete_user(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_dynamodb_delete_error_logged_but_continues(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that DynamoDB delete errors are logged but deletion succeeds.

        The implementation logs a warning when DynamoDB deletion fails but still
        returns True because the Cognito user was deleted successfully.
        """
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-456"

        # Create target account
        accounts_table = get_accounts_table()
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{target_account_id}",
                "email": "target@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {
                "Users": [
                    {
                        "Username": "target-user-456",
                        "Attributes": [
                            {"Name": "sub", "Value": target_account_id},
                            {"Name": "email", "Value": "target@example.com"},
                        ],
                    }
                ]
            }
            mock_cognito.admin_delete_user.return_value = {}
            mock_get_client.return_value = mock_cognito

            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_accounts = MagicMock()
                mock_accounts.delete_item.side_effect = ClientError(
                    {"Error": {"Code": "InternalServerError", "Message": "DB error"}},
                    "DeleteItem",
                )
                mock_tables.accounts = mock_accounts

                # DynamoDB error is logged but doesn't fail the operation
                result = admin_delete_user(event, lambda_context)
                assert result is True

    def test_cognito_lookup_error_raises_not_found(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that Cognito lookup error raises NOT_FOUND.

        When Cognito list_users fails, the user cannot be found so we raise NOT_FOUND.
        """
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-456"

        # Create target account (but Cognito lookup will fail)
        accounts_table = get_accounts_table()
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{target_account_id}",
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.side_effect = ClientError(
                {"Error": {"Code": "InternalErrorException", "Message": "Error"}},
                "ListUsers",
            )
            mock_get_client.return_value = mock_cognito

            with pytest.raises(AppError) as exc_info:
                admin_delete_user(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_sub_lookup_error_logs_warning_and_raises_not_found(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that sub lookup error logs warning and raises NOT_FOUND."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-456"

        # Create target account
        accounts_table = get_accounts_table()
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{target_account_id}",
                "email": "target@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.side_effect = ClientError(
                {"Error": {"Code": "InternalErrorException", "Message": "Error"}},
                "ListUsers",
            )
            mock_cognito.admin_delete_user.return_value = {}
            mock_get_client.return_value = mock_cognito

            with pytest.raises(AppError) as exc_info:
                admin_delete_user(event, lambda_context)

            # User not found because Cognito lookup failed
            assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_empty_cognito_users_raises_not_found(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that empty user list from Cognito raises NOT_FOUND."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-456"

        # Create target account with email
        accounts_table = get_accounts_table()
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{target_account_id}",
                "email": "target@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            # Cognito lookup succeeds but returns empty user list
            mock_cognito.list_users.return_value = {"Users": []}
            mock_cognito.admin_delete_user.return_value = {}
            mock_get_client.return_value = mock_cognito

            with pytest.raises(AppError) as exc_info:
                admin_delete_user(event, lambda_context)

            # User not found because Cognito returned empty list
            assert exc_info.value.error_code == ErrorCode.NOT_FOUND

    def test_unexpected_exception_handled(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that unexpected exceptions are handled."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": "target-user-456"},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.accounts.get_item.side_effect = RuntimeError("Unexpected")

            with pytest.raises(AppError) as exc_info:
                admin_delete_user(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR


class TestCreateManagedCatalog:
    """Tests for create_managed_catalog handler."""

    def test_success(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test successful managed catalog creation."""
        monkeypatch.setenv("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev")

        event = {
            **admin_appsync_event,
            "arguments": {
                "input": {
                    "catalogName": "Official 2025 Catalog",
                    "isPublic": True,
                    "products": [
                        {"productName": "Popcorn", "price": 10.00, "sortOrder": 1},
                        {"productName": "Chocolate", "price": 5.00, "description": "Yummy", "sortOrder": 2},
                    ],
                }
            },
        }

        result = create_managed_catalog(event, lambda_context)

        assert result["catalogName"] == "Official 2025 Catalog"
        assert result["catalogType"] == "ADMIN_MANAGED"
        assert result["isPublic"] is True
        assert result["isPublicStr"] == "true"
        assert len(result["products"]) == 2
        assert result["products"][0]["productName"] == "Popcorn"
        assert result["products"][0]["price"] == 10.00
        assert "productId" in result["products"][0]
        assert result["products"][1]["description"] == "Yummy"
        assert "catalogId" in result
        assert result["catalogId"].startswith("CATALOG#")

    def test_default_is_public(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that isPublic defaults to True for managed catalogs."""
        monkeypatch.setenv("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev")

        event = {
            **admin_appsync_event,
            "arguments": {
                "input": {
                    "catalogName": "Test Catalog",
                    "products": [
                        {"productName": "Product A", "price": 5.00},
                    ],
                }
            },
        }

        result = create_managed_catalog(event, lambda_context)

        assert result["isPublic"] is True

    def test_non_public_catalog(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test creating non-public managed catalog."""
        monkeypatch.setenv("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev")

        event = {
            **admin_appsync_event,
            "arguments": {
                "input": {
                    "catalogName": "Private Catalog",
                    "isPublic": False,
                    "products": [
                        {"productName": "Product A", "price": 5.00},
                    ],
                }
            },
        }

        result = create_managed_catalog(event, lambda_context)

        assert result["isPublic"] is False
        assert result["isPublicStr"] == "false"

    def test_non_admin_forbidden(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that non-admin gets forbidden error."""
        event = {
            **non_admin_appsync_event,
            "arguments": {
                "input": {
                    "catalogName": "Test Catalog",
                    "products": [{"productName": "Test", "price": 5.00}],
                }
            },
        }

        with pytest.raises(AppError) as exc_info:
            create_managed_catalog(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN

    def test_missing_catalog_name_raises_error(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that missing catalog name raises error."""
        event = {
            **admin_appsync_event,
            "arguments": {
                "input": {
                    "catalogName": "   ",
                    "products": [{"productName": "Test", "price": 5.00}],
                }
            },
        }

        with pytest.raises(AppError) as exc_info:
            create_managed_catalog(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Catalog name is required" in exc_info.value.message

    def test_empty_products_raises_error(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that empty products raises error."""
        event = {
            **admin_appsync_event,
            "arguments": {
                "input": {
                    "catalogName": "Test Catalog",
                    "products": [],
                }
            },
        }

        with pytest.raises(AppError) as exc_info:
            create_managed_catalog(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Products array cannot be empty" in exc_info.value.message

    def test_product_missing_name_raises_error(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that product without name raises error."""
        event = {
            **admin_appsync_event,
            "arguments": {
                "input": {
                    "catalogName": "Test Catalog",
                    "products": [{"productName": "   ", "price": 5.00}],
                }
            },
        }

        with pytest.raises(AppError) as exc_info:
            create_managed_catalog(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Product name is required" in exc_info.value.message

    def test_product_invalid_price_raises_error(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that product with invalid price raises error."""
        event = {
            **admin_appsync_event,
            "arguments": {
                "input": {
                    "catalogName": "Test Catalog",
                    "products": [{"productName": "Test", "price": -5.00}],
                }
            },
        }

        with pytest.raises(AppError) as exc_info:
            create_managed_catalog(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Valid product price is required" in exc_info.value.message

    def test_product_missing_price_raises_error(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that product without price raises error."""
        event = {
            **admin_appsync_event,
            "arguments": {
                "input": {
                    "catalogName": "Test Catalog",
                    "products": [{"productName": "Test"}],
                }
            },
        }

        with pytest.raises(AppError) as exc_info:
            create_managed_catalog(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Valid product price is required" in exc_info.value.message

    def test_missing_caller_id_raises_error(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that missing caller ID raises error."""
        event = {
            **admin_appsync_event,
            "identity": {
                "username": "adminuser",
                "claims": {"cognito:groups": ["ADMIN"]},
            },
            "arguments": {
                "input": {
                    "catalogName": "Test Catalog",
                    "products": [{"productName": "Test", "price": 5.00}],
                }
            },
        }

        with pytest.raises(AppError) as exc_info:
            create_managed_catalog(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.UNAUTHORIZED

    def test_dynamodb_error_raises(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that DynamoDB errors are handled."""
        monkeypatch.setenv("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev")

        event = {
            **admin_appsync_event,
            "arguments": {
                "input": {
                    "catalogName": "Test Catalog",
                    "products": [{"productName": "Test", "price": 5.00}],
                }
            },
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_catalogs = MagicMock()
            mock_catalogs.put_item.side_effect = ClientError(
                {"Error": {"Code": "InternalServerError", "Message": "DB error"}},
                "PutItem",
            )
            mock_tables.catalogs = mock_catalogs

            with pytest.raises(AppError) as exc_info:
                create_managed_catalog(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_unexpected_exception_handled(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that unexpected exceptions are handled."""
        event = {
            **admin_appsync_event,
            "arguments": {
                "input": {
                    "catalogName": "Test Catalog",
                    "products": [{"productName": "Test", "price": 5.00}],
                }
            },
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.catalogs.put_item.side_effect = RuntimeError("Unexpected")

            with pytest.raises(AppError) as exc_info:
                create_managed_catalog(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR


class TestAdminDeleteUserOrders:
    """Tests for admin_delete_user_orders handler."""

    def test_success_deletes_all_orders(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test successful deletion of all orders for a user's campaigns."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")
        monkeypatch.setenv("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-ue1-dev")
        monkeypatch.setenv("ORDERS_TABLE_NAME", "kernelworx-orders-ue1-dev")

        from src.handlers.admin_operations import admin_delete_user_orders

        target_account_id = "target-user-123"
        db_account_id = f"ACCOUNT#{target_account_id}"

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            # Mock profiles query
            mock_tables.profiles.query.return_value = {
                "Items": [
                    {"profileId": "profile-1", "ownerAccountId": db_account_id},
                    {"profileId": "profile-2", "ownerAccountId": db_account_id},
                ]
            }

            # Mock campaigns query - different results for each profile
            mock_tables.campaigns.query.side_effect = [
                {"Items": [{"campaignId": "campaign-1", "profileId": "profile-1"}]},
                {"Items": [{"campaignId": "campaign-2", "profileId": "profile-2"}]},
            ]

            # Mock orders query - orders for each campaign
            mock_tables.orders.query.side_effect = [
                {"Items": [{"orderId": "order-1", "campaignId": "campaign-1"}]},
                {
                    "Items": [
                        {"orderId": "order-2", "campaignId": "campaign-2"},
                        {"orderId": "order-3", "campaignId": "campaign-2"},
                    ]
                },
            ]

            result = admin_delete_user_orders(event, lambda_context)

            assert result == 3  # 3 orders deleted
            assert mock_tables.orders.delete_item.call_count == 3

    def test_non_admin_forbidden(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that non-admin users cannot delete user orders."""
        from src.handlers.admin_operations import admin_delete_user_orders

        event = {
            **non_admin_appsync_event,
            "arguments": {"accountId": "target-user-123"},
        }

        with pytest.raises(AppError) as exc_info:
            admin_delete_user_orders(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN

    def test_missing_account_id(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that missing account ID raises error."""
        from src.handlers.admin_operations import admin_delete_user_orders

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with pytest.raises(AppError) as exc_info:
            admin_delete_user_orders(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_unexpected_error_handled(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that unexpected exceptions are handled."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")

        from src.handlers.admin_operations import admin_delete_user_orders

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": "target-user-123"},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.profiles.query.side_effect = RuntimeError("Unexpected")

            with pytest.raises(AppError) as exc_info:
                admin_delete_user_orders(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR


class TestAdminDeleteUserCampaigns:
    """Tests for admin_delete_user_campaigns handler."""

    def test_success_deletes_all_campaigns(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test successful deletion of all campaigns for a user's profiles."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")
        monkeypatch.setenv("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-ue1-dev")

        from src.handlers.admin_operations import admin_delete_user_campaigns

        target_account_id = "target-user-123"
        db_account_id = f"ACCOUNT#{target_account_id}"

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            # Mock profiles query
            mock_tables.profiles.query.return_value = {
                "Items": [
                    {"profileId": "profile-1", "ownerAccountId": db_account_id},
                ]
            }

            # Mock campaigns query
            mock_tables.campaigns.query.return_value = {
                "Items": [
                    {"campaignId": "campaign-1", "profileId": "profile-1"},
                    {"campaignId": "campaign-2", "profileId": "profile-1"},
                ]
            }

            result = admin_delete_user_campaigns(event, lambda_context)

            assert result == 2  # 2 campaigns deleted
            assert mock_tables.campaigns.delete_item.call_count == 2

    def test_non_admin_forbidden(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that non-admin users cannot delete user campaigns."""
        from src.handlers.admin_operations import admin_delete_user_campaigns

        event = {
            **non_admin_appsync_event,
            "arguments": {"accountId": "target-user-123"},
        }

        with pytest.raises(AppError) as exc_info:
            admin_delete_user_campaigns(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN

    def test_missing_account_id(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that missing account ID raises error."""
        from src.handlers.admin_operations import admin_delete_user_campaigns

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with pytest.raises(AppError) as exc_info:
            admin_delete_user_campaigns(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_unexpected_error_handled(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that unexpected exceptions are handled."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")

        from src.handlers.admin_operations import admin_delete_user_campaigns

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": "target-user-123"},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.profiles.query.side_effect = RuntimeError("Unexpected")

            with pytest.raises(AppError) as exc_info:
                admin_delete_user_campaigns(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR


class TestAdminDeleteUserShares:
    """Tests for admin_delete_user_shares handler."""

    def test_success_deletes_all_shares(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test successful deletion of all shares for a user's profiles."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")
        monkeypatch.setenv("SHARES_TABLE_NAME", "kernelworx-shares-ue1-dev")

        from src.handlers.admin_operations import admin_delete_user_shares

        target_account_id = "target-user-123"
        db_account_id = f"ACCOUNT#{target_account_id}"

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            # Mock profiles query
            mock_tables.profiles.query.return_value = {
                "Items": [
                    {"profileId": "profile-1", "ownerAccountId": db_account_id},
                ]
            }

            # Mock shares query
            mock_tables.shares.query.return_value = {
                "Items": [
                    {"profileId": "profile-1", "targetAccountId": "shared-user-1"},
                    {"profileId": "profile-1", "targetAccountId": "shared-user-2"},
                ]
            }

            result = admin_delete_user_shares(event, lambda_context)

            assert result == 2  # 2 shares deleted
            assert mock_tables.shares.delete_item.call_count == 2

    def test_non_admin_forbidden(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that non-admin users cannot delete user shares."""
        from src.handlers.admin_operations import admin_delete_user_shares

        event = {
            **non_admin_appsync_event,
            "arguments": {"accountId": "target-user-123"},
        }

        with pytest.raises(AppError) as exc_info:
            admin_delete_user_shares(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN

    def test_missing_account_id(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that missing account ID raises error."""
        from src.handlers.admin_operations import admin_delete_user_shares

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with pytest.raises(AppError) as exc_info:
            admin_delete_user_shares(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_unexpected_error_handled(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that unexpected exceptions are handled."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")

        from src.handlers.admin_operations import admin_delete_user_shares

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": "target-user-123"},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.profiles.query.side_effect = RuntimeError("Unexpected")

            with pytest.raises(AppError) as exc_info:
                admin_delete_user_shares(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR


class TestAdminDeleteUserProfiles:
    """Tests for admin_delete_user_profiles handler."""

    def test_success_deletes_all_profiles(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test successful deletion of all profiles for a user."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")

        from src.handlers.admin_operations import admin_delete_user_profiles

        target_account_id = "target-user-123"
        db_account_id = f"ACCOUNT#{target_account_id}"

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            # Mock profiles query (no pagination in this handler)
            mock_tables.profiles.query.return_value = {
                "Items": [
                    {"profileId": "profile-1", "ownerAccountId": db_account_id},
                    {"profileId": "profile-2", "ownerAccountId": db_account_id},
                    {"profileId": "profile-3", "ownerAccountId": db_account_id},
                ]
            }

            result = admin_delete_user_profiles(event, lambda_context)

            assert result == 3  # 3 profiles deleted
            assert mock_tables.profiles.delete_item.call_count == 3

    def test_non_admin_forbidden(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that non-admin users cannot delete user profiles."""
        from src.handlers.admin_operations import admin_delete_user_profiles

        event = {
            **non_admin_appsync_event,
            "arguments": {"accountId": "target-user-123"},
        }

        with pytest.raises(AppError) as exc_info:
            admin_delete_user_profiles(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN

    def test_missing_account_id(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that missing account ID raises error."""
        from src.handlers.admin_operations import admin_delete_user_profiles

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with pytest.raises(AppError) as exc_info:
            admin_delete_user_profiles(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_unexpected_error_handled(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that unexpected exceptions are handled."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")

        from src.handlers.admin_operations import admin_delete_user_profiles

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": "target-user-123"},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.profiles.query.side_effect = RuntimeError("Unexpected")

            with pytest.raises(AppError) as exc_info:
                admin_delete_user_profiles(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR


class TestAdminDeleteUserCatalogs:
    """Tests for admin_delete_user_catalogs handler (soft delete)."""

    def test_success_soft_deletes_all_catalogs(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test successful soft deletion of all catalogs for a user."""
        monkeypatch.setenv("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev")

        from src.handlers.admin_operations import admin_delete_user_catalogs

        target_account_id = "target-user-123"
        db_account_id = f"ACCOUNT#{target_account_id}"

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            # Mock catalogs scan - simulate pagination
            mock_tables.catalogs.scan.side_effect = [
                {
                    "Items": [
                        {"catalogId": "catalog-1", "ownerAccountId": db_account_id},
                        {"catalogId": "catalog-2", "ownerAccountId": db_account_id},
                    ],
                    "LastEvaluatedKey": {"catalogId": "catalog-2"},
                },
                {
                    "Items": [
                        {"catalogId": "catalog-3", "ownerAccountId": db_account_id},
                    ]
                },
            ]

            result = admin_delete_user_catalogs(event, lambda_context)

            assert result == 3  # 3 catalogs soft-deleted
            # Verify soft delete via update_item (not delete_item)
            assert mock_tables.catalogs.update_item.call_count == 3
            # Verify delete_item was NOT called
            assert mock_tables.catalogs.delete_item.call_count == 0

    def test_non_admin_forbidden(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that non-admin users cannot delete user catalogs."""
        from src.handlers.admin_operations import admin_delete_user_catalogs

        event = {
            **non_admin_appsync_event,
            "arguments": {"accountId": "target-user-123"},
        }

        with pytest.raises(AppError) as exc_info:
            admin_delete_user_catalogs(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN

    def test_missing_account_id(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that missing account ID raises error."""
        from src.handlers.admin_operations import admin_delete_user_catalogs

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with pytest.raises(AppError) as exc_info:
            admin_delete_user_catalogs(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_unexpected_error_handled(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that unexpected exceptions are handled."""
        monkeypatch.setenv("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev")

        from src.handlers.admin_operations import admin_delete_user_catalogs

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": "target-user-123"},
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.catalogs.scan.side_effect = RuntimeError("Unexpected")

            with pytest.raises(AppError) as exc_info:
                admin_delete_user_catalogs(event, lambda_context)

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR


class TestGetCognitoClient:
    """Tests for _get_cognito_client helper."""

    def test_default_client(self, monkeypatch: Any) -> None:
        """Test default Cognito client without custom endpoint."""
        monkeypatch.delenv("COGNITO_ENDPOINT", raising=False)

        from src.handlers.admin_operations import _get_cognito_client

        with patch("src.handlers.admin_operations.boto3.client") as mock_client:
            mock_client.return_value = MagicMock()

            _get_cognito_client()

            mock_client.assert_called_once_with("cognito-idp")

    def test_custom_endpoint_client(self, monkeypatch: Any) -> None:
        """Test Cognito client with custom endpoint (e.g., localstack)."""
        monkeypatch.setenv("COGNITO_ENDPOINT", "http://localhost:4566")

        from src.handlers.admin_operations import _get_cognito_client

        with patch("src.handlers.admin_operations.boto3.client") as mock_client:
            mock_client.return_value = MagicMock()

            _get_cognito_client()

            mock_client.assert_called_once_with("cognito-idp", endpoint_url="http://localhost:4566")


class TestAdminSearchUser:
    """Tests for admin_search_user function."""

    def test_search_user_by_email_partial_match(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test successful search by partial email address (fuzzy, case-insensitive)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "user@example"},  # Partial email
        }

        mock_cognito_user = {
            "Username": "user@example.com",
            "Attributes": [
                {"Name": "sub", "Value": "user-sub-123"},
                {"Name": "email", "Value": "user@example.com"},
                {"Name": "email_verified", "Value": "true"},
            ],
            "Enabled": True,
            "UserStatus": "CONFIRMED",
            "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                # DynamoDB scan returns matching account
                mock_tables.accounts.scan.return_value = {
                    "Items": [
                        {
                            "accountId": "ACCOUNT#user-sub-123",
                            "email": "user@example.com",
                            "givenName": "Test",
                            "familyName": "User",
                        }
                    ]
                }

                # Cognito lookup by sub + email prefix search
                mock_client.list_users.side_effect = [
                    {"Users": [mock_cognito_user]},  # DynamoDB sub lookup
                    {"Users": []},  # Cognito email prefix search (returns empty, already found)
                ]
                mock_client.admin_list_groups_for_user.return_value = {"Groups": []}

                # For _build_admin_user
                mock_tables.accounts.get_item.return_value = {
                    "Item": {
                        "accountId": "ACCOUNT#user-sub-123",
                        "givenName": "Test",
                        "familyName": "User",
                    }
                }

                result = admin_search_user(event, lambda_context)

                # Now returns a list
                assert isinstance(result, list)
                assert len(result) == 1
                assert result[0]["accountId"] == "user-sub-123"
                assert result[0]["email"] == "user@example.com"
                assert result[0]["displayName"] == "Test User"

            # Verify it searched by sub (from DynamoDB result) and email prefix (Cognito)
            assert mock_client.list_users.call_count == 2
            # First call: DynamoDB sub lookup
            assert mock_client.list_users.call_args_list[0] == call(
                UserPoolId="test-pool-id",
                Filter='sub = "user-sub-123"',
                Limit=1,
            )
            # Second call: Cognito email prefix search
            assert mock_client.list_users.call_args_list[1] == call(
                UserPoolId="test-pool-id",
                Filter='email ^= "user@example"',
                Limit=50,
            )

    def test_search_user_multiple_matches(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test search returns multiple matches when multiple users match."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "test-table")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "jon"},  # Should match both "jon" accounts
        }

        mock_cognito_users = [
            {
                "Username": "dave@daveandjonee.com",
                "Attributes": [
                    {"Name": "sub", "Value": "dave-sub-123"},
                    {"Name": "email", "Value": "dave@daveandjonee.com"},
                ],
                "Enabled": True,
                "UserStatus": "CONFIRMED",
                "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
            },
            {
                "Username": "jondupont@gmail.com",
                "Attributes": [
                    {"Name": "sub", "Value": "jon-sub-456"},
                    {"Name": "email", "Value": "jondupont@gmail.com"},
                ],
                "Enabled": True,
                "UserStatus": "CONFIRMED",
                "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
            },
        ]

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                # DynamoDB scan returns multiple matching accounts
                mock_tables.accounts.scan.return_value = {
                    "Items": [
                        {
                            "accountId": "ACCOUNT#dave-sub-123",
                            "email": "dave@daveandjonee.com",
                            "givenName": "Dave",
                            "familyName": "Meiser",
                        },
                        {
                            "accountId": "ACCOUNT#jon-sub-456",
                            "email": "jondupont@gmail.com",
                            "givenName": "Jon",
                            "familyName": "Dupont",
                        },
                    ]
                }

                # Cognito lookup returns the matching user each time
                mock_client.list_users.side_effect = [
                    {"Users": [mock_cognito_users[0]]},  # First DynamoDB account lookup
                    {"Users": [mock_cognito_users[1]]},  # Second DynamoDB account lookup
                    {"Users": []},  # Cognito email prefix search (returns empty, all users already found)
                ]
                mock_client.admin_list_groups_for_user.return_value = {"Groups": []}
                mock_tables.accounts.get_item.side_effect = [
                    {"Item": {"accountId": "ACCOUNT#dave-sub-123", "givenName": "Dave", "familyName": "Meiser"}},
                    {"Item": {"accountId": "ACCOUNT#jon-sub-456", "givenName": "Jon", "familyName": "Dupont"}},
                ]

                result = admin_search_user(event, lambda_context)

                # Should return both matches
                assert isinstance(result, list)
                assert len(result) == 2
                emails = [r["email"] for r in result]
                assert "dave@daveandjonee.com" in emails
                assert "jondupont@gmail.com" in emails

    def test_search_user_by_name_case_insensitive(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test search by name is case-insensitive."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "JOHN"},  # Uppercase search
        }

        mock_cognito_user = {
            "Username": "john@example.com",
            "Attributes": [
                {"Name": "sub", "Value": "john-sub-456"},
                {"Name": "email", "Value": "john@example.com"},
            ],
            "Enabled": True,
            "UserStatus": "CONFIRMED",
            "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                # DynamoDB scan returns matching account (lowercase name matches uppercase query)
                mock_tables.accounts.scan.return_value = {
                    "Items": [
                        {
                            "accountId": "ACCOUNT#john-sub-456",
                            "email": "john@example.com",
                            "givenName": "John",  # Mixed case
                            "familyName": "Smith",
                        }
                    ]
                }

                mock_client.list_users.return_value = {"Users": [mock_cognito_user]}
                mock_client.admin_list_groups_for_user.return_value = {"Groups": []}
                mock_tables.accounts.get_item.return_value = {
                    "Item": {
                        "accountId": "ACCOUNT#john-sub-456",
                        "givenName": "John",
                        "familyName": "Smith",
                    }
                }

                result = admin_search_user(event, lambda_context)

                assert isinstance(result, list)
                assert len(result) == 1
                assert result[0]["accountId"] == "john-sub-456"

    def test_search_user_by_uuid_success(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test successful search by raw UUID."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "123e4567-e89b-12d3-a456-426614174000"},
        }

        mock_cognito_user = {
            "Username": "user@example.com",
            "Attributes": [
                {"Name": "sub", "Value": "123e4567-e89b-12d3-a456-426614174000"},
                {"Name": "email", "Value": "user@example.com"},
            ],
            "Enabled": True,
            "UserStatus": "CONFIRMED",
            "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                mock_client.list_users.return_value = {"Users": [mock_cognito_user]}
                mock_client.admin_list_groups_for_user.return_value = {"Groups": []}
                mock_tables.accounts.get_item.return_value = {}

                result = admin_search_user(event, lambda_context)

                assert isinstance(result, list)
                assert len(result) == 1
                assert result[0]["accountId"] == "123e4567-e89b-12d3-a456-426614174000"

                mock_client.list_users.assert_called_once_with(
                    UserPoolId="test-pool-id",
                    Filter='sub = "123e4567-e89b-12d3-a456-426614174000"',
                    Limit=1,
                )

    def test_search_user_by_account_prefixed_uuid(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test successful search by ACCOUNT#UUID format."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "ACCOUNT#123e4567-e89b-12d3-a456-426614174000"},
        }

        mock_cognito_user = {
            "Username": "user@example.com",
            "Attributes": [
                {"Name": "sub", "Value": "123e4567-e89b-12d3-a456-426614174000"},
                {"Name": "email", "Value": "user@example.com"},
            ],
            "Enabled": True,
            "UserStatus": "CONFIRMED",
            "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                mock_client.list_users.return_value = {"Users": [mock_cognito_user]}
                mock_client.admin_list_groups_for_user.return_value = {"Groups": []}
                mock_tables.accounts.get_item.return_value = {}

                result = admin_search_user(event, lambda_context)

                assert isinstance(result, list)
                assert len(result) == 1
                assert result[0]["accountId"] == "123e4567-e89b-12d3-a456-426614174000"

                # Should search by sub with ACCOUNT# prefix stripped
                mock_client.list_users.assert_called_once_with(
                    UserPoolId="test-pool-id",
                    Filter='sub = "123e4567-e89b-12d3-a456-426614174000"',
                    Limit=1,
                )

    def test_search_user_not_found(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test search returns empty list when user not found in DynamoDB."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "nonexistent"},
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                # DynamoDB scan returns no matches
                mock_tables.accounts.scan.return_value = {"Items": []}

                result = admin_search_user(event, lambda_context)

                assert result == []

    def test_search_user_empty_query_raises_error(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test search with empty query raises INVALID_INPUT error."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "   "},  # whitespace only
        }

        with pytest.raises(AppError) as exc_info:
            admin_search_user(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_search_user_non_admin_raises_error(
        self,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test non-admin user gets FORBIDDEN error."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **non_admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "user@example.com"},
        }

        with pytest.raises(AppError) as exc_info:
            admin_search_user(event, lambda_context)

        assert exc_info.value.error_code == ErrorCode.FORBIDDEN

    def test_search_user_admin_found(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test search finds admin user correctly."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "admin"},  # Partial match
        }

        mock_cognito_user = {
            "Username": "admin@example.com",
            "Attributes": [
                {"Name": "sub", "Value": "admin-sub-123"},
                {"Name": "email", "Value": "admin@example.com"},
            ],
            "Enabled": True,
            "UserStatus": "CONFIRMED",
            "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                # DynamoDB scan returns the account
                mock_tables.accounts.scan.return_value = {
                    "Items": [
                        {
                            "accountId": "ACCOUNT#admin-sub-123",
                            "email": "admin@example.com",
                            "givenName": "Admin",
                            "familyName": "User",
                        }
                    ]
                }

                mock_client.list_users.return_value = {"Users": [mock_cognito_user]}
                mock_client.admin_list_groups_for_user.return_value = {"Groups": [{"GroupName": "ADMIN"}]}
                mock_tables.accounts.get_item.return_value = {}

                result = admin_search_user(event, lambda_context)

                # Should return list with admin user
                assert isinstance(result, list)
                assert len(result) == 1
                assert result[0]["isAdmin"] is True

    def test_search_user_via_lambda_handler(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test admin_search_user is routed correctly via lambda_handler."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "user"},  # Partial match
        }

        mock_cognito_user = {
            "Username": "user@example.com",
            "Attributes": [
                {"Name": "sub", "Value": "user-sub-123"},
                {"Name": "email", "Value": "user@example.com"},
            ],
            "Enabled": True,
            "UserStatus": "CONFIRMED",
            "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

        with patch("src.handlers.admin_operations._get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                # DynamoDB scan returns the account
                mock_tables.accounts.scan.return_value = {
                    "Items": [
                        {
                            "accountId": "ACCOUNT#user-sub-123",
                            "email": "user@example.com",
                            "givenName": "Test",
                            "familyName": "User",
                        }
                    ]
                }

                mock_client.list_users.return_value = {"Users": [mock_cognito_user]}
                mock_client.admin_list_groups_for_user.return_value = {"Groups": []}
                mock_tables.accounts.get_item.return_value = {}

                result = lambda_handler(event, lambda_context)

                # Returns list now
                assert isinstance(result, list)
                assert len(result) == 1
                assert result[0]["accountId"] == "user-sub-123"
