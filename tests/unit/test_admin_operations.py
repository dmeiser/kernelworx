"""Unit tests for admin operations Lambda handler.

Tests for:
- adminListUsers
- adminResetUserPassword
- adminPurgeUserAccount
- adminDeleteUserOrders
- adminDeleteUserCampaigns
- adminDeleteUserShares
- adminDeleteUserProfiles
- createManagedCatalog
"""

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import MagicMock, call, patch

import boto3
import pytest
from botocore.exceptions import ClientError

from src.handlers.admin_operations import (
    _batch_get_campaign_catalogs,
    _batch_get_display_names,
    _batch_get_user_groups,
    _extract_unique_catalog_ids,
    _search_user_by_sub,
    _search_users_in_cognito_by_email_prefix,
    admin_list_users,
    admin_purge_user_account,
    admin_reset_user_password,
    admin_search_user,
    create_managed_catalog,
    lambda_handler,
)
from src.utils.errors import AppError, ErrorCode
from tests.unit.fixtures import accept_batch_deletes


def _assert_delete_requests(table: Any, expected_count: int) -> None:
    """Assert the DeleteRequests sent to this table total ``expected_count`` items."""
    requests: List[Dict[str, Any]] = []
    for call_obj in table.meta.client.batch_write_item.call_args_list:
        sent = call_obj.kwargs["RequestItems"]
        requests.extend(request for batch in sent.values() for request in batch)
    assert all("DeleteRequest" in request for request in requests)
    assert len(requests) == expected_count


def get_accounts_table() -> Any:
    """Get the accounts table for testing."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-accounts-ue1-dev")


def get_catalogs_table() -> Any:
    """Get the catalogs table for testing."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    return dynamodb.Table("kernelworx-catalogs-ue1-dev")


@pytest.fixture(autouse=True)
def _stub_s3_client_slots(monkeypatch: Any) -> None:
    """Stub the S3 client slots used by the purge's S3 sweeps for every test in this module.

    The sweeps page through this stub, so they are no-ops unless a test
    replaces the slot with a configured client (see TestAdminPurgeUserAccount).
    """
    monkeypatch.setattr("src.handlers.delete_profile_cascade.s3_client", MagicMock())
    monkeypatch.setattr("src.utils.payment_methods.s3_client", MagicMock())


@pytest.fixture
def sample_account_id() -> str:
    """Sample account ID (Cognito sub) as a valid UUID."""
    return "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def admin_appsync_event(sample_account_id: str) -> Dict[str, Any]:
    """Base AppSync event structure for admin user (MFA-verified, per #336)."""
    return {
        "arguments": {},
        "identity": {
            "sub": sample_account_id,
            "username": "adminuser",
            "claims": {
                "cognito:groups": ["ADMIN"],
                "mfa": True,
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
        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": "test-user-123"}]}
            mock_cognito.admin_reset_user_password.return_value = {}
            mock_get_client.return_value = mock_cognito

            result = lambda_handler(event, lambda_context)

            assert result is True

    def test_dispatch_admin_purge_user_account(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test dispatch to admin_purge_user_account."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "11111111-1111-1111-1111-111111111111"

        get_accounts_table().put_item(
            Item={
                "accountId": f"ACCOUNT#{target_account_id}",
                "email": "target@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminPurgeUserAccount"},
            "arguments": {"accountId": target_account_id, "profileIds": []},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": target_account_id}]}
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
        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
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

        with patch("src.handlers.deletion_cascade.tables") as mock_tables:
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

        with patch("src.handlers.deletion_cascade.tables") as mock_tables:
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

        with patch("src.handlers.deletion_cascade.tables") as mock_tables:
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

        with patch("src.handlers.deletion_cascade.tables") as mock_tables:
            mock_tables.profiles.query.return_value = {"Items": []}

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

        result = lambda_handler(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT
        assert "Unknown admin operation" in result["message"]


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

        user_id = "user-123"
        user_created = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        user_modified = datetime(2024, 6, 15, 9, 30, 0, tzinfo=timezone.utc)

        event = {
            **admin_appsync_event,
            "arguments": {"limit": 20},
        }

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
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
            mock_batch_names.return_value = {user_id: "John Doe"}
            mock_batch_groups.return_value = {user_id: ["ADMIN"]}
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

            # Verify handler plumbs extracted subs/usernames into the batch helpers.
            assert mock_batch_names.call_args.args[0] == [user_id]
            assert mock_batch_groups.call_args.args[0] is mock_cognito
            assert mock_batch_groups.call_args.args[1] == "test-pool-id"
            assert mock_batch_groups.call_args.args[2] == [user_id]

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

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
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
            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {}
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

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
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
            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {}
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

        user_id = "user-no-name"

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
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
            # Account exists but has no name, so displayName should be None
            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {}
            mock_get_client.return_value = mock_cognito

            result = admin_list_users(event, lambda_context)

            assert len(result["users"]) == 1
            user = result["users"][0]
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

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
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

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
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

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": []}
            mock_get_client.return_value = mock_cognito

            admin_list_users(event, lambda_context)

            mock_cognito.list_users.assert_called_once_with(
                UserPoolId="test-pool-id",
                Limit=1,  # Clamped to min
            )

    def test_limit_explicit_none_defaults(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that explicit null limit defaults to 20 without raising TypeError."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"limit": None},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": []}
            mock_get_client.return_value = mock_cognito

            admin_list_users(event, lambda_context)

            mock_cognito.list_users.assert_called_once_with(
                UserPoolId="test-pool-id",
                Limit=20,
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

        result = admin_list_users(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN
        assert "Admin access required" in result["message"]

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

        result = admin_list_users(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
        # #575: USER_POOL_ID is read through the canonical
        # utils.dynamodb.get_required_env, which raises ValueError; the
        # decorator maps that to the generic admin-operation message, and the
        # variable name reaches the Lambda log rather than the client.
        assert "USER_POOL_ID" not in result["message"]

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

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.side_effect = ClientError(
                {"Error": {"Code": "InternalErrorException", "Message": "Internal error"}},
                "ListUsers",
            )
            mock_get_client.return_value = mock_cognito

            result = admin_list_users(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
            assert "Failed to list users" in result["message"]

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

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
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
            mock_batch_names.return_value = {}
            # Group lookup fails; batch helper swallows the error and returns empty map
            mock_batch_groups.return_value = {}
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

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
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
            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {
                "admin-user": ["ADMIN"],
                "regular-user": [],
            }
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

        When the batched display-name lookup fails, the helper logs a warning
        and returns an empty map so we continue with displayName=None.
        """
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {},
        }

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
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
            # Simulate batched display-name lookup failing gracefully
            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {}
            mock_get_client.return_value = mock_cognito

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

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            # Raise a generic exception
            mock_cognito.list_users.side_effect = RuntimeError("Unexpected error")
            mock_get_client.return_value = mock_cognito

            result = admin_list_users(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
            assert "Failed to list users" in result["message"]


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

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
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

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
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

        result = admin_reset_user_password(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN
        assert "Admin access required" in result["message"]

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

        result = admin_reset_user_password(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT
        assert "Email is required" in result["message"]

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

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": []}
            mock_get_client.return_value = mock_cognito

            result = admin_reset_user_password(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.NOT_FOUND

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

        result = admin_reset_user_password(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

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

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.side_effect = ClientError(
                {"Error": {"Code": "InternalErrorException", "Message": "Test error"}},
                "ListUsers",
            )
            mock_get_client.return_value = mock_cognito

            result = admin_reset_user_password(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

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

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": "test-user-123"}]}
            mock_cognito.admin_reset_user_password.side_effect = ClientError(
                {"Error": {"Code": "UserNotFoundException", "Message": "User not found"}},
                "AdminResetUserPassword",
            )
            mock_get_client.return_value = mock_cognito

            result = admin_reset_user_password(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.NOT_FOUND

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

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": "test-user-123"}]}
            mock_cognito.admin_reset_user_password.side_effect = ClientError(
                {"Error": {"Code": "InvalidParameterException", "Message": "Invalid param"}},
                "AdminResetUserPassword",
            )
            mock_get_client.return_value = mock_cognito

            result = admin_reset_user_password(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INVALID_INPUT

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

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": "test-user-123"}]}
            mock_cognito.admin_reset_user_password.side_effect = ClientError(
                {"Error": {"Code": "LimitExceededException", "Message": "Rate limited"}},
                "AdminResetUserPassword",
            )
            mock_get_client.return_value = mock_cognito

            result = admin_reset_user_password(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

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

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.side_effect = RuntimeError("Unexpected error")
            mock_get_client.return_value = mock_cognito

            result = admin_reset_user_password(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

    def test_email_with_quote_rejected_before_filter(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """An email containing a double quote must be rejected before reaching Cognito (#124)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"email": 'evil"@example.com'},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_get_client.return_value = mock_cognito

            result = admin_reset_user_password(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INVALID_INPUT
            mock_cognito.list_users.assert_not_called()

    def test_email_with_backslash_rejected_before_filter(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """An email containing a backslash must be rejected before reaching Cognito (#124)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"email": "evil\\@example.com\\"},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_get_client.return_value = mock_cognito

            result = admin_reset_user_password(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INVALID_INPUT
            mock_cognito.list_users.assert_not_called()

    def test_malformed_email_rejected_before_filter(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """An email without a valid local@domain shape is rejected (#124)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"email": "not-an-email"},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_get_client.return_value = mock_cognito

            result = admin_reset_user_password(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INVALID_INPUT
            mock_cognito.list_users.assert_not_called()

    def test_oversize_email_rejected_before_filter(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """An email longer than 254 chars is rejected by the filter formatter (#124)."""
        from src.utils.cognito_filters import cognito_user_filter

        long_email = "a" * 250 + "@b.co"
        with pytest.raises(AppError) as exc_info:
            cognito_user_filter("email", long_email)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT


class TestAdminMfaRequired:
    """Tests that admin operations require MFA (#336).

    The gate is ``require_admin_mfa``: a non-admin is denied with "Admin
    access required" (unchanged), and an admin whose token lacks the
    injected "mfa" claim is denied with exactly "MFA required" (#336).
    """

    def _admin_event_without_mfa(self, sample_account_id: str) -> Dict[str, Any]:
        """Admin event with the ADMIN group but no mfa claim."""
        return {
            "arguments": {},
            "identity": {
                "sub": sample_account_id,
                "username": "adminuser",
                "claims": {
                    "cognito:groups": ["ADMIN"],
                },
            },
            "requestContext": {"requestId": "test-correlation-id"},
            "info": {"fieldName": "testField", "parentTypeName": "Mutation"},
        }

    def test_admin_with_mfa_passes(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """An admin whose token has injected mfa:true is allowed to proceed."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"email": "test@example.com"},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": [{"Username": "test-user-123"}]}
            mock_cognito.admin_reset_user_password.return_value = {}
            mock_get_client.return_value = mock_cognito

            result = admin_reset_user_password(event, lambda_context)

        assert result is True

    def test_admin_without_mfa_forbidden(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """An admin whose token lacks mfa:true gets exactly 'MFA required'."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **self._admin_event_without_mfa(sample_account_id),
            "arguments": {"email": "test@example.com"},
        }

        result = admin_reset_user_password(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.MFA_REQUIRED
        assert result["message"] == "MFA required"

    def test_admin_with_amr_pwd_only_forbidden(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """An admin with bare amr=['pwd'] is rejected with 'MFA required'."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            "arguments": {"email": "test@example.com"},
            "identity": {
                "sub": sample_account_id,
                "username": "adminuser",
                "claims": {
                    "cognito:groups": ["ADMIN"],
                    "amr": ["pwd"],
                },
            },
            "requestContext": {"requestId": "test-correlation-id"},
            "info": {"fieldName": "testField", "parentTypeName": "Mutation"},
        }

        result = admin_reset_user_password(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.MFA_REQUIRED
        assert result["message"] == "MFA required"

    def test_admin_with_mfa_false_and_amr_mfa_forbidden(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """An admin with mfa:False is rejected even with amr=['mfa'] (#336)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            "arguments": {"email": "test@example.com"},
            "identity": {
                "sub": sample_account_id,
                "username": "adminuser",
                "claims": {
                    "cognito:groups": ["ADMIN"],
                    "mfa": False,
                    "amr": ["mfa"],
                },
            },
            "requestContext": {"requestId": "test-correlation-id"},
            "info": {"fieldName": "testField", "parentTypeName": "Mutation"},
        }

        result = admin_reset_user_password(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.MFA_REQUIRED
        assert result["message"] == "MFA required"

    def test_admin_with_federated_amr_and_mfa_false_forbidden(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """An admin with federated amr and mfa:False is rejected with 'MFA required'."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            "arguments": {"email": "test@example.com"},
            "identity": {
                "sub": sample_account_id,
                "username": "adminuser",
                "claims": {
                    "cognito:groups": ["ADMIN"],
                    "mfa": False,
                    "amr": ["accounts.google.com"],
                },
            },
            "requestContext": {"requestId": "test-correlation-id"},
            "info": {"fieldName": "testField", "parentTypeName": "Mutation"},
        }

        result = admin_reset_user_password(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.MFA_REQUIRED
        assert result["message"] == "MFA required"

    def test_admin_with_webauthn_amr_and_no_mfa_forbidden(
        self,
        dynamodb_table: Any,
        sample_account_id: str,
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """An admin with passkey/webauthn amr without mfa:true gets 'MFA required'."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            "arguments": {"email": "test@example.com"},
            "identity": {
                "sub": sample_account_id,
                "username": "adminuser",
                "claims": {
                    "cognito:groups": ["ADMIN"],
                    "amr": ["webauthn"],
                },
            },
            "requestContext": {"requestId": "test-correlation-id"},
            "info": {"fieldName": "testField", "parentTypeName": "Mutation"},
        }

        result = admin_reset_user_password(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.MFA_REQUIRED
        assert result["message"] == "MFA required"

    def test_non_admin_without_mfa_gets_admin_access_required(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """A non-admin without MFA is denied by the admin gate, not the MFA gate."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **non_admin_appsync_event,
            "arguments": {"email": "test@example.com"},
        }

        result = admin_reset_user_password(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN
        assert result["message"] == "Admin access required"


class TestAdminPurgeUserAccount:
    """Tests for admin_purge_user_account handler (#521).

    Deletion is client-side by decision: the client issues the per-entity
    adminDeleteUser* mutations and calls this operation for the four classes
    it cannot reach (invites for owned profiles, inbound shares, S3 reports,
    payment-QR codes) plus the two things no browser can do itself, the
    accounts record and the Cognito user. Catalogs are never deleted.
    """

    def _seed_account(self, account_id: str) -> None:
        get_accounts_table().put_item(
            Item={
                "accountId": f"ACCOUNT#{account_id}",
                "email": "target@example.com",
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

    def _mock_cognito(self, target_account_id: str) -> MagicMock:
        mock_cognito = MagicMock()
        mock_cognito.list_users.return_value = {"Users": [{"Username": target_account_id}]}
        mock_cognito.admin_delete_user.return_value = {}
        return mock_cognito

    def test_deletes_account_record_and_cognito_user(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Both client-unreachable entities are removed."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "11111111-1111-1111-1111-111111111111"
        self._seed_account(target_account_id)

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": []}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = self._mock_cognito(target_account_id)
            mock_get_client.return_value = mock_cognito

            result = admin_purge_user_account(event, lambda_context)

        assert result is True
        mock_cognito.admin_delete_user.assert_called_once_with(UserPoolId="test-pool-id", Username=target_account_id)
        assert "Item" not in get_accounts_table().get_item(Key={"accountId": f"ACCOUNT#{target_account_id}"})

    def test_does_not_touch_profiles_campaigns_or_catalogs(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """The purge writes only the accounts row; the client owns the per-entity deletes (#521)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-123"
        self._seed_account(target_account_id)

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": []}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = self._mock_cognito(target_account_id)
            mock_get_client.return_value = mock_cognito

            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_tables.accounts.get_item.return_value = {"Item": {"accountId": "ACCOUNT#target-user-123"}}
                mock_tables.profiles.get_item.return_value = {}
                result = admin_purge_user_account(event, lambda_context)

                assert result is True
                writes = [
                    name
                    for name, _args, _kwargs in mock_tables.mock_calls
                    if name.split(".")[-1] in {"delete_item", "put_item", "update_item", "batch_write_item"}
                ]
                assert writes == ["accounts.delete_item"]
                profile_ops = [name for name, _a, _k in mock_tables.mock_calls if name.startswith("profiles.")]
                assert set(profile_ops) <= {"profiles.get_item"}

    def test_catalog_survives_a_purge(
        self,
        dynamodb_table: Any,
        profiles_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """A custom catalog is still present after the account is purged (#521)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
        monkeypatch.setenv("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev")

        target_account_id = "target-user-123"
        db_account_id = f"ACCOUNT#{target_account_id}"
        self._seed_account(target_account_id)

        catalogs_table = boto3.resource("dynamodb", region_name="us-east-1").Table(os.environ["CATALOGS_TABLE_NAME"])
        catalogs_table.put_item(
            Item={
                "catalogId": "CATALOG#owned-catalog",
                "catalogName": "Keep Me",
                "ownerAccountId": db_account_id,
                "isPublic": False,
                "products": [],
            }
        )

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": []}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = self._mock_cognito(target_account_id)
            mock_get_client.return_value = mock_cognito

            assert admin_purge_user_account(event, lambda_context) is True

        catalog = catalogs_table.get_item(Key={"catalogId": "CATALOG#owned-catalog"}).get("Item")
        assert catalog is not None
        assert catalog.get("isDeleted") is not True

    def test_refuses_while_a_profile_remains(
        self,
        dynamodb_table: Any,
        profiles_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """A surviving profile means the client cascade never finished: refuse with CONFLICT (#521)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-123"
        self._seed_account(target_account_id)
        profiles_table.put_item(
            Item={
                "ownerAccountId": f"ACCOUNT#{target_account_id}",
                "profileId": "PROFILE#p1",
                "sellerName": "Still There",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": ["PROFILE#p1"]}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = self._mock_cognito(target_account_id)
            mock_get_client.return_value = mock_cognito

            result = admin_purge_user_account(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.CONFLICT
        # Nothing was deleted: the Cognito user and the accounts row survive.
        mock_cognito.admin_delete_user.assert_not_called()
        assert "Item" in get_accounts_table().get_item(Key={"accountId": f"ACCOUNT#{target_account_id}"})

    def test_succeeds_once_the_profiles_are_gone(
        self,
        dynamodb_table: Any,
        profiles_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """After the client deleted every profile, the verification read finds none and the purge completes."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-123"
        self._seed_account(target_account_id)

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": ["PROFILE#p1"]}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = self._mock_cognito(target_account_id)
            mock_get_client.return_value = mock_cognito

            result = admin_purge_user_account(event, lambda_context)

        assert result is True
        mock_cognito.admin_delete_user.assert_called_once()
        assert "Item" not in get_accounts_table().get_item(Key={"accountId": f"ACCOUNT#{target_account_id}"})

    def test_cognito_user_already_gone_is_idempotent(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Cognito reporting the user already deleted still completes the purge."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-123"
        self._seed_account(target_account_id)

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": []}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = self._mock_cognito(target_account_id)
            mock_cognito.admin_delete_user.side_effect = ClientError(
                {"Error": {"Code": "UserNotFoundException", "Message": "User does not exist."}},
                "AdminDeleteUser",
            )
            mock_get_client.return_value = mock_cognito

            result = admin_purge_user_account(event, lambda_context)

        assert result is True
        assert "Item" not in get_accounts_table().get_item(Key={"accountId": f"ACCOUNT#{target_account_id}"})

    def test_cognito_delete_failure_aborts_the_purge(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """A real Cognito delete failure surfaces as INTERNAL_ERROR and keeps the account record."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-123"
        self._seed_account(target_account_id)

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": []}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = self._mock_cognito(target_account_id)
            mock_cognito.admin_delete_user.side_effect = ClientError(
                {"Error": {"Code": "NotAuthorizedException", "Message": "Access denied."}},
                "AdminDeleteUser",
            )
            mock_get_client.return_value = mock_cognito

            result = admin_purge_user_account(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
        # The accounts row is deleted after Cognito, so the failure leaves the account retryable.
        assert "Item" in get_accounts_table().get_item(Key={"accountId": f"ACCOUNT#{target_account_id}"})

    def test_cognito_delete_failure_leaves_swept_data_intact(
        self,
        dynamodb_table: Any,
        invites_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """A Cognito failure must run before any sweep, so the data phase leaves everything in place (#551)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-123"
        self._seed_account(target_account_id)
        invites_table.put_item(Item={"inviteCode": "INV-OWNED", "profileId": "PROFILE#p1", "status": "PENDING"})

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": ["PROFILE#p1"]}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = self._mock_cognito(target_account_id)
            mock_cognito.admin_delete_user.side_effect = ClientError(
                {"Error": {"Code": "NotAuthorizedException", "Message": "Access denied."}},
                "AdminDeleteUser",
            )
            mock_get_client.return_value = mock_cognito

            result = admin_purge_user_account(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
        # Nothing was swept: the invite and the account record both survive, so a
        # retry after the Cognito outage converges on the same well-defined state.
        assert invites_table.get_item(Key={"inviteCode": "INV-OWNED"}).get("Item") is not None
        assert "Item" in get_accounts_table().get_item(Key={"accountId": f"ACCOUNT#{target_account_id}"})

    def test_sweep_failure_after_cognito_delete_is_logged_loudly(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
        capsys: Any,
    ) -> None:
        """A data-phase failure after the Cognito commit point surfaces in the logs with an errorCode (#551)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-123"
        self._seed_account(target_account_id)

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": []}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = self._mock_cognito(target_account_id)
            mock_get_client.return_value = mock_cognito
            with patch(
                "src.handlers.admin_operations.delete_inbound_shares",
                side_effect=ClientError(
                    {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "throttled"}},
                    "Query",
                ),
            ):
                result = admin_purge_user_account(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
        # The Cognito commit point already fired; the leftover records are inert because
        # the user cannot sign in again, and the account record stays for a convergent re-run.
        mock_cognito.admin_delete_user.assert_called_once_with(UserPoolId="test-pool-id", Username=target_account_id)
        assert "Item" in get_accounts_table().get_item(Key={"accountId": f"ACCOUNT#{target_account_id}"})

        captured = capsys.readouterr().out
        assert "Purge data sweep failed after Cognito user was deleted" in captured
        assert ErrorCode.INTERNAL_ERROR in captured

    def test_sweep_app_error_after_cognito_delete_is_logged_with_its_code(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
        capsys: Any,
    ) -> None:
        """An AppError from a sweep helper keeps its own errorCode in the loud post-commit log (#551)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-123"
        self._seed_account(target_account_id)

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": []}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = self._mock_cognito(target_account_id)
            mock_get_client.return_value = mock_cognito
            with patch(
                "src.handlers.admin_operations.delete_all_user_qr_codes",
                side_effect=AppError(ErrorCode.INTERNAL_ERROR, "Failed to purge payment QR codes from S3"),
            ):
                result = admin_purge_user_account(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
        mock_cognito.admin_delete_user.assert_called_once_with(UserPoolId="test-pool-id", Username=target_account_id)
        assert "Item" in get_accounts_table().get_item(Key={"accountId": f"ACCOUNT#{target_account_id}"})

        captured = capsys.readouterr().out
        assert "Purge data sweep failed after Cognito user was deleted" in captured
        assert ErrorCode.INTERNAL_ERROR in captured

    def test_purge_sweeps_invites_for_the_supplied_profiles(
        self,
        dynamodb_table: Any,
        invites_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Invites on the account's profiles are swept; invites on other profiles survive."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-123"
        self._seed_account(target_account_id)

        invites_table.put_item(Item={"inviteCode": "INV-OWNED", "profileId": "PROFILE#p1", "status": "PENDING"})
        invites_table.put_item(Item={"inviteCode": "INV-OTHER", "profileId": "PROFILE#other", "status": "PENDING"})

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": ["PROFILE#p1"]}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_get_client.return_value = self._mock_cognito(target_account_id)
            assert admin_purge_user_account(event, lambda_context) is True

        assert invites_table.get_item(Key={"inviteCode": "INV-OWNED"}).get("Item") is None
        assert invites_table.get_item(Key={"inviteCode": "INV-OTHER"}).get("Item") is not None

    def test_purge_sweeps_inbound_shares(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Shares granting the deleted account access to other owners' profiles are swept."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-123"
        self._seed_account(target_account_id)

        shares_table.put_item(
            Item={"profileId": "PROFILE#other-owner", "targetAccountId": f"ACCOUNT#{target_account_id}"}
        )
        shares_table.put_item(Item={"profileId": "PROFILE#other-owner", "targetAccountId": "ACCOUNT#someone-else"})

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": []}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_get_client.return_value = self._mock_cognito(target_account_id)
            assert admin_purge_user_account(event, lambda_context) is True

        assert (
            shares_table.get_item(
                Key={"profileId": "PROFILE#other-owner", "targetAccountId": "ACCOUNT#target-user-123"}
            ).get("Item")
            is None
        )
        assert (
            shares_table.get_item(
                Key={"profileId": "PROFILE#other-owner", "targetAccountId": "ACCOUNT#someone-else"}
            ).get("Item")
            is not None
        )

    def test_purge_deletes_s3_reports_for_the_supplied_profiles(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """The report objects under each supplied profile's prefix are deleted."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
        monkeypatch.setenv("EXPORTS_BUCKET", "test-reports-bucket")

        target_account_id = "target-user-123"
        self._seed_account(target_account_id)

        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"Versions": [{"Key": "reports/PROFILE#p1/report.xlsx", "VersionId": "v1"}], "DeleteMarkers": []}
        ]
        mock_s3.get_paginator.return_value = mock_paginator
        monkeypatch.setattr("src.handlers.delete_profile_cascade.s3_client", mock_s3)

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": ["PROFILE#p1"]}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_get_client.return_value = self._mock_cognito(target_account_id)
            assert admin_purge_user_account(event, lambda_context) is True

        deleted = mock_s3.delete_objects.call_args.kwargs["Delete"]["Objects"]
        assert deleted == [{"Key": "reports/PROFILE#p1/report.xlsx", "VersionId": "v1"}]

    def test_purge_deletes_payment_qr_codes(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """The payment-QR S3 objects for the account are deleted."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
        monkeypatch.setenv("EXPORTS_BUCKET", "test-qr-bucket")

        target_account_id = "target-user-123"
        self._seed_account(target_account_id)

        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Versions": [
                    {"Key": "payment-qr-codes/target-user-123/visa.png", "VersionId": "v1"},
                ],
                "DeleteMarkers": [],
            }
        ]
        mock_s3.get_paginator.return_value = mock_paginator
        monkeypatch.setattr("src.utils.payment_methods.s3_client", mock_s3)

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": []}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_get_client.return_value = self._mock_cognito(target_account_id)
            assert admin_purge_user_account(event, lambda_context) is True

        assert mock_s3.delete_objects.call_count >= 1
        deleted_keys = {
            obj["Key"]
            for call_obj in mock_s3.delete_objects.call_args_list
            for obj in call_obj.kwargs["Delete"]["Objects"]
        }
        assert "payment-qr-codes/target-user-123/visa.png" in deleted_keys

    @pytest.mark.parametrize(
        "bad_profile_ids",
        [None, "PROFILE#p1", ["PROFILE#p1", ""], [123]],
    )
    def test_rejects_malformed_profile_ids(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        bad_profile_ids: Any,
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """A non-list or empty-member profileIds argument fails validation before any lookup."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {**admin_appsync_event, "arguments": {"accountId": "target-user-123", "profileIds": bad_profile_ids}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_get_client.return_value = mock_cognito

            result = admin_purge_user_account(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT
        mock_cognito.list_users.assert_not_called()

    def test_profile_verification_throttling_returns_resource_busy(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """A throttled verification read is retryable and deletes nothing (#291)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-123"
        self._seed_account(target_account_id)

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": ["PROFILE#p1"]}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = self._mock_cognito(target_account_id)
            mock_get_client.return_value = mock_cognito

            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_tables.accounts.get_item.return_value = {"Item": {"accountId": "ACCOUNT#target-user-123"}}
                mock_tables.profiles.get_item.side_effect = ClientError(
                    {"Error": {"Code": "ProvisionedThroughputExceededException"}}, "GetItem"
                )
                result = admin_purge_user_account(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.RESOURCE_BUSY
        mock_cognito.admin_delete_user.assert_not_called()

    def test_absent_account_record_still_deletes_cognito_user(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """A partially-migrated account (Cognito only) is still purged."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "cognito-only-user-1"

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": []}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = self._mock_cognito(target_account_id)
            mock_get_client.return_value = mock_cognito

            result = admin_purge_user_account(event, lambda_context)

        assert result is True
        mock_cognito.admin_delete_user.assert_called_once_with(UserPoolId="test-pool-id", Username=target_account_id)
        assert "Item" not in get_accounts_table().get_item(Key={"accountId": f"ACCOUNT#{target_account_id}"})

    def test_self_purge_rejected(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """An admin cannot purge their own account (#125)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": admin_appsync_event["identity"]["sub"], "profileIds": []},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_get_client.return_value = MagicMock()
            result = admin_purge_user_account(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT
        assert "Cannot delete your own account" in result["message"]

    def test_not_found_when_no_cognito_user_and_no_account(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        event = {**admin_appsync_event, "arguments": {"accountId": "ghost-user", "profileIds": []}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": []}
            mock_get_client.return_value = mock_cognito

            result = admin_purge_user_account(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND
        mock_cognito.admin_delete_user.assert_not_called()

    def test_absent_cognito_user_still_deletes_account_record(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """A partially-migrated account (DynamoDB only) is still purged."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "partial-user-1"
        self._seed_account(target_account_id)

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": []}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_cognito.list_users.return_value = {"Users": []}
            mock_get_client.return_value = mock_cognito

            result = admin_purge_user_account(event, lambda_context)

        assert result is True
        assert "Item" not in get_accounts_table().get_item(Key={"accountId": f"ACCOUNT#{target_account_id}"})

    def test_account_delete_failure_returns_internal_error(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")

        target_account_id = "target-user-123"
        self._seed_account(target_account_id)

        event = {**admin_appsync_event, "arguments": {"accountId": target_account_id, "profileIds": []}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = self._mock_cognito(target_account_id)
            mock_get_client.return_value = mock_cognito

            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_tables.accounts.get_item.return_value = {"Item": {"accountId": "ACCOUNT#target-user-123"}}
                mock_tables.profiles.get_item.return_value = {}
                mock_tables.accounts.delete_item.side_effect = ClientError(
                    {"Error": {"Code": "ResourceNotFoundException"}}, "DeleteItem"
                )
                result = admin_purge_user_account(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

    @pytest.mark.parametrize("bad_account_id", ['other"user', "other\\user\\"])
    def test_unsafe_account_id_rejected_before_cognito(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        bad_account_id: str,
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Metacharacter accountIds are rejected before the Cognito sub filter (#124)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {**admin_appsync_event, "arguments": {"accountId": bad_account_id, "profileIds": []}}

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_cognito = MagicMock()
            mock_get_client.return_value = mock_cognito

            result = admin_purge_user_account(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT
        mock_cognito.list_users.assert_not_called()


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

        result = create_managed_catalog(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

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

        result = create_managed_catalog(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT
        assert "Catalog name is required" in result["message"]

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

        result = create_managed_catalog(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT
        assert "Products array cannot be empty" in result["message"]

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

        result = create_managed_catalog(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT
        assert "Product name is required" in result["message"]

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

        result = create_managed_catalog(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT
        assert "Valid product price is required" in result["message"]

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

        result = create_managed_catalog(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT
        assert "Valid product price is required" in result["message"]

    def test_product_string_price_is_accepted(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that a numeric string price is accepted and converted."""
        monkeypatch.setenv("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev")

        event = {
            **admin_appsync_event,
            "arguments": {
                "input": {
                    "catalogName": "Test Catalog",
                    "products": [{"productName": "Test", "price": "5.50"}],
                }
            },
        }

        result = create_managed_catalog(event, lambda_context)

        assert result["products"][0]["price"] == Decimal("5.50")

    def test_product_non_numeric_string_price_raises_error(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that a non-numeric string price returns INVALID_INPUT."""
        event = {
            **admin_appsync_event,
            "arguments": {
                "input": {
                    "catalogName": "Test Catalog",
                    "products": [{"productName": "Test", "price": "not-a-number"}],
                }
            },
        }

        result = create_managed_catalog(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT
        assert "Product price must be a valid number" in result["message"]

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
                "claims": {"cognito:groups": ["ADMIN"], "mfa": True},
            },
            "arguments": {
                "input": {
                    "catalogName": "Test Catalog",
                    "products": [{"productName": "Test", "price": 5.00}],
                }
            },
        }

        result = create_managed_catalog(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.UNAUTHORIZED

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

            result = create_managed_catalog(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

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

            result = create_managed_catalog(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR


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

        with (
            patch("src.handlers.deletion_cascade.tables") as mock_tables,
            patch("src.handlers.campaign_operations.tables") as mock_campaign_tables,
        ):
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

            # Mock orders query in campaign_operations (where delete_orders_for_campaign lives)
            orders_side_effect = [
                {"Items": [{"orderId": "order-1", "campaignId": "campaign-1"}]},
                {
                    "Items": [
                        {"orderId": "order-2", "campaignId": "campaign-2"},
                        {"orderId": "order-3", "campaignId": "campaign-2"},
                    ]
                },
            ]
            mock_campaign_tables.orders.query.side_effect = orders_side_effect
            mock_tables.orders.query.side_effect = orders_side_effect

            # BatchWriteItem on campaign_operations.tables.orders
            accept_batch_deletes(mock_campaign_tables.orders)

            # Delete verification helpers use campaign_operations.tables
            mock_campaign_tables.orders.get_item.return_value = {}
            mock_campaign_tables.campaigns.get_item.return_value = {}

            result = admin_delete_user_orders(event, lambda_context)

            assert result == 3  # 3 orders deleted
            assert mock_campaign_tables.orders.meta.client.batch_write_item.call_count == 2
            _assert_delete_requests(mock_campaign_tables.orders, 3)

    def test_success_with_campaign_having_no_orders(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that a campaign without orders is handled and skipped correctly."""
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

        with (
            patch("src.handlers.deletion_cascade.tables") as mock_tables,
            patch("src.handlers.campaign_operations.tables") as mock_campaign_tables,
        ):
            # Mock profiles query
            mock_tables.profiles.query.return_value = {
                "Items": [
                    {"profileId": "profile-1", "ownerAccountId": db_account_id},
                ]
            }

            # Mock campaigns query - two campaigns for the same profile
            mock_tables.campaigns.query.return_value = {
                "Items": [
                    {"campaignId": "campaign-1", "profileId": "profile-1"},
                    {"campaignId": "campaign-2", "profileId": "profile-1"},
                ]
            }

            # Mock orders query - first campaign has one order, second has none
            orders_side_effect = [
                {"Items": [{"orderId": "order-1", "campaignId": "campaign-1"}]},
                {"Items": []},
            ]
            mock_campaign_tables.orders.query.side_effect = orders_side_effect
            mock_tables.orders.query.side_effect = orders_side_effect

            accept_batch_deletes(mock_campaign_tables.orders)

            # Delete verification helpers use campaign_operations.tables
            mock_campaign_tables.orders.get_item.return_value = {}
            mock_campaign_tables.campaigns.get_item.return_value = {}

            result = admin_delete_user_orders(event, lambda_context)

            assert result == 1  # Only 1 order deleted
            assert mock_campaign_tables.orders.meta.client.batch_write_item.call_count == 1
            _assert_delete_requests(mock_campaign_tables.orders, 1)

    def test_throttled_returns_resource_busy(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that throttling during order deletion surfaces as RESOURCE_BUSY."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")
        monkeypatch.setenv("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-ue1-dev")
        monkeypatch.setenv("ORDERS_TABLE_NAME", "kernelworx-orders-ue1-dev")

        from botocore.exceptions import ClientError

        from src.handlers.admin_operations import admin_delete_user_orders

        target_account_id = "target-user-123"
        db_account_id = f"ACCOUNT#{target_account_id}"

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with (
            patch("src.handlers.deletion_cascade.tables") as mock_tables,
            patch("src.handlers.campaign_operations.tables") as mock_campaign_tables,
        ):
            mock_tables.profiles.query.return_value = {
                "Items": [{"profileId": "profile-1", "ownerAccountId": db_account_id}]
            }
            mock_tables.campaigns.query.return_value = {
                "Items": [{"campaignId": "campaign-1", "profileId": "profile-1"}]
            }
            mock_campaign_tables.orders.query.return_value = {
                "Items": [{"orderId": "order-1", "campaignId": "campaign-1"}]
            }
            error_response = {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "Throttled"}}
            mock_campaign_tables.orders.meta.client.batch_write_item.side_effect = ClientError(
                error_response, "BatchWriteItem"
            )

            result = admin_delete_user_orders(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.RESOURCE_BUSY

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

        result = admin_delete_user_orders(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

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

        result = admin_delete_user_orders(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

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

            result = admin_delete_user_orders(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR


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

        with (
            patch("src.handlers.deletion_cascade.tables") as mock_tables,
            patch("src.handlers.campaign_operations.tables") as mock_campaign_tables,
        ):
            # Mock profiles query
            mock_tables.profiles.query.return_value = {
                "Items": [
                    {"profileId": "profile-1", "ownerAccountId": db_account_id},
                ]
            }

            # Mock campaigns query - campaigns for the profile
            mock_tables.campaigns.query.return_value = {
                "Items": [
                    {"campaignId": "campaign-1", "profileId": "profile-1"},
                    {"campaignId": "campaign-2", "profileId": "profile-1"},
                ]
            }

            # Delete verification helpers use campaign_operations.tables
            mock_campaign_tables.campaigns.get_item.return_value = {}

            accept_batch_deletes(mock_tables.campaigns)

            result = admin_delete_user_campaigns(event, lambda_context)

            assert result == 2  # 2 campaigns deleted
            assert mock_tables.campaigns.meta.client.batch_write_item.call_count == 1
            _assert_delete_requests(mock_tables.campaigns, 2)

    def test_throttled_returns_resource_busy(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that throttling during campaign deletion surfaces as RESOURCE_BUSY."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")
        monkeypatch.setenv("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-ue1-dev")

        from botocore.exceptions import ClientError

        from src.handlers.admin_operations import admin_delete_user_campaigns

        target_account_id = "target-user-123"
        db_account_id = f"ACCOUNT#{target_account_id}"

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": target_account_id},
        }

        with patch("src.handlers.deletion_cascade.tables") as mock_tables:
            mock_tables.profiles.query.return_value = {
                "Items": [{"profileId": "profile-1", "ownerAccountId": db_account_id}]
            }
            mock_tables.campaigns.query.return_value = {
                "Items": [{"campaignId": "campaign-1", "profileId": "profile-1"}]
            }
            error_response = {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "Throttled"}}
            mock_tables.campaigns.meta.client.batch_write_item.side_effect = ClientError(
                error_response, "BatchWriteItem"
            )

            result = admin_delete_user_campaigns(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.RESOURCE_BUSY

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

        result = admin_delete_user_campaigns(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

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

        result = admin_delete_user_campaigns(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_profile_with_no_campaigns_deletes_nothing(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that a profile with no campaigns skips the delete and reports zero.

        Covers the empty ``campaign_keys`` guard: the behavior tests always
        return items, so without this the False branch is never exercised and a
        profile that simply has no campaigns is untested.
        """
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")

        from src.handlers.admin_operations import admin_delete_user_campaigns

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": "target-user-123"},
        }

        with (
            patch("src.handlers.deletion_cascade.tables") as mock_tables,
            patch("src.handlers.campaign_operations.tables") as mock_campaign_tables,
        ):
            mock_tables.profiles.query.return_value = {
                "Items": [{"profileId": "profile-1", "ownerAccountId": "ACCOUNT#target-user-123"}]
            }
            mock_tables.campaigns.query.return_value = {"Items": []}
            accept_batch_deletes(mock_tables.campaigns, mock_campaign_tables.campaigns)

            result = admin_delete_user_campaigns(event, lambda_context)

            assert result == 0
            mock_tables.campaigns.meta.client.batch_write_item.assert_not_called()

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

        with patch("src.handlers.deletion_cascade.tables") as mock_tables:
            mock_tables.profiles.query.side_effect = RuntimeError("Unexpected")

            result = admin_delete_user_campaigns(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR


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

        with patch("src.handlers.deletion_cascade.tables") as mock_tables:
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

            accept_batch_deletes(mock_tables.shares)

            result = admin_delete_user_shares(event, lambda_context)

            assert result == 2  # 2 shares deleted
            assert mock_tables.shares.meta.client.batch_write_item.call_count == 1
            _assert_delete_requests(mock_tables.shares, 2)

    def test_profile_with_no_shares_deletes_nothing(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test that a profile with no shares skips the delete and reports zero.

        Covers the empty ``share_keys`` guard: the behavior tests always return
        items, so without this the False branch is never exercised and a profile
        that simply has no shares is untested.
        """
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-ue1-dev")

        from src.handlers.admin_operations import admin_delete_user_shares

        event = {
            **admin_appsync_event,
            "arguments": {"accountId": "target-user-123"},
        }

        with patch("src.handlers.deletion_cascade.tables") as mock_tables:
            mock_tables.profiles.query.return_value = {
                "Items": [{"profileId": "profile-1", "ownerAccountId": "ACCOUNT#target-user-123"}]
            }
            mock_tables.shares.query.return_value = {"Items": []}
            accept_batch_deletes(mock_tables.shares)

            result = admin_delete_user_shares(event, lambda_context)

            assert result == 0
            mock_tables.shares.meta.client.batch_write_item.assert_not_called()

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

        result = admin_delete_user_shares(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

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

        result = admin_delete_user_shares(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

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

        with patch("src.handlers.deletion_cascade.tables") as mock_tables:
            mock_tables.profiles.query.side_effect = RuntimeError("Unexpected")

            result = admin_delete_user_shares(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR


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

        with patch("src.handlers.deletion_cascade.tables") as mock_tables:
            # Mock profiles query (no pagination in this handler)
            mock_tables.profiles.query.return_value = {
                "Items": [
                    {"profileId": "profile-1", "ownerAccountId": db_account_id},
                    {"profileId": "profile-2", "ownerAccountId": db_account_id},
                    {"profileId": "profile-3", "ownerAccountId": db_account_id},
                ]
            }

            accept_batch_deletes(mock_tables.profiles)

            result = admin_delete_user_profiles(event, lambda_context)

            assert result == 3  # 3 profiles deleted
            assert mock_tables.profiles.meta.client.batch_write_item.call_count == 1
            _assert_delete_requests(mock_tables.profiles, 3)

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

        result = admin_delete_user_profiles(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

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

        result = admin_delete_user_profiles(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

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

        with patch("src.handlers.deletion_cascade.tables") as mock_tables:
            mock_tables.profiles.query.side_effect = RuntimeError("Unexpected")

            result = admin_delete_user_profiles(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR


class TestAccountDeletionHelpers:
    """Tests for cascade-deletion helpers used during account deletion."""

    def test_delete_invites_for_owned_profiles(
        self,
        dynamodb_table: Any,
        profiles_table: Any,
        invites_table: Any,
        monkeypatch: Any,
    ) -> None:
        """Invites for profiles owned by the account are deleted."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
        monkeypatch.setenv("INVITES_TABLE_NAME", "kernelworx-invites-ue1-dev")

        from src.handlers.deletion_cascade import (
            delete_invites_for_owned_profiles,
            get_user_profiles,
        )

        account_id = "owner-account"
        account_id_key = f"ACCOUNT#{account_id}"
        profile_id = "PROFILE#owned"
        invite_code = "INVITE#abc123"

        profiles_table.put_item(
            Item={
                "ownerAccountId": account_id_key,
                "profileId": profile_id,
                "sellerName": "Test Scout",
            }
        )
        invites_table.put_item(
            Item={
                "inviteCode": invite_code,
                "profileId": profile_id,
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        count = delete_invites_for_owned_profiles(get_user_profiles(account_id_key), MagicMock())

        assert count == 1
        assert invites_table.get_item(Key={"inviteCode": invite_code}).get("Item") is None

    def test_delete_invites_for_owned_profiles_with_no_invites(
        self,
        dynamodb_table: Any,
        profiles_table: Any,
        invites_table: Any,
        monkeypatch: Any,
    ) -> None:
        """No invites are deleted when the profile has zero invites."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
        monkeypatch.setenv("INVITES_TABLE_NAME", "kernelworx-invites-ue1-dev")

        from src.handlers.deletion_cascade import delete_invites_for_owned_profiles, get_user_profiles

        account_id = "owner-account-no-invites"
        account_id_key = f"ACCOUNT#{account_id}"
        profile_id = "PROFILE#no-invites"

        profiles_table.put_item(
            Item={
                "ownerAccountId": account_id_key,
                "profileId": profile_id,
                "sellerName": "Test Scout",
            }
        )

        count = delete_invites_for_owned_profiles(get_user_profiles(account_id_key), MagicMock())
        assert count == 0

    def test_delete_invites_for_owned_profiles_no_profiles(
        self,
        dynamodb_table: Any,
        monkeypatch: Any,
    ) -> None:
        """No invites are deleted when the account owns no profiles."""
        monkeypatch.setenv("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
        monkeypatch.setenv("INVITES_TABLE_NAME", "kernelworx-invites-ue1-dev")

        from src.handlers.deletion_cascade import delete_invites_for_owned_profiles, get_user_profiles

        count = delete_invites_for_owned_profiles(get_user_profiles("ACCOUNT#no-profiles"), MagicMock())
        assert count == 0

    def test_delete_inbound_shares(
        self,
        dynamodb_table: Any,
        shares_table: Any,
        monkeypatch: Any,
    ) -> None:
        """Inbound shares where the account is the target are deleted."""
        monkeypatch.setenv("SHARES_TABLE_NAME", "kernelworx-shares-ue1-dev")

        from src.handlers.deletion_cascade import delete_inbound_shares

        account_id = "target-account"
        account_id_key = f"ACCOUNT#{account_id}"

        shares_table.put_item(
            Item={
                "profileId": "PROFILE#shared-with-me",
                "targetAccountId": account_id_key,
                "permissions": ["READ"],
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

        count = delete_inbound_shares(account_id, MagicMock())

        assert count == 1
        response = shares_table.query(
            IndexName="targetAccountId-index",
            KeyConditionExpression="targetAccountId = :tid",
            ExpressionAttributeValues={":tid": account_id_key},
        )
        assert len(response.get("Items", [])) == 0

    def test_delete_inbound_shares_no_shares(
        self,
        dynamodb_table: Any,
        monkeypatch: Any,
    ) -> None:
        """No shares are deleted when the account has no inbound shares."""
        monkeypatch.setenv("SHARES_TABLE_NAME", "kernelworx-shares-ue1-dev")

        from src.handlers.deletion_cascade import delete_inbound_shares

        count = delete_inbound_shares("no-shares", MagicMock())
        assert count == 0

    def test_find_cognito_user_by_sub_unprefixed(self) -> None:
        """_find_cognito_user_by_sub queries Cognito with raw sub."""
        from src.handlers.admin_operations import _find_cognito_user_by_sub

        mock_cognito = MagicMock()
        mock_cognito.list_users.return_value = {
            "Users": [
                {
                    "Username": "user-123",
                    "Attributes": [
                        {"Name": "sub", "Value": "11111111-1111-1111-1111-111111111111"},
                        {"Name": "email", "Value": "user@example.com"},
                    ],
                }
            ]
        }

        username, email = _find_cognito_user_by_sub(
            mock_cognito, "pool-id", "11111111-1111-1111-1111-111111111111", MagicMock()
        )

        assert username == "user-123"
        assert email == "user@example.com"
        mock_cognito.list_users.assert_called_once_with(
            UserPoolId="pool-id",
            Filter='sub = "11111111-1111-1111-1111-111111111111"',
            Limit=1,
        )

    def test_find_cognito_user_by_sub_prefixed(self) -> None:
        """_find_cognito_user_by_sub strips ACCOUNT# prefix before querying Cognito."""
        from src.handlers.admin_operations import _find_cognito_user_by_sub

        mock_cognito = MagicMock()
        mock_cognito.list_users.return_value = {
            "Users": [
                {
                    "Username": "user-123",
                    "Attributes": [
                        {"Name": "sub", "Value": "11111111-1111-1111-1111-111111111111"},
                        {"Name": "email", "Value": "user@example.com"},
                    ],
                }
            ]
        }

        username, email = _find_cognito_user_by_sub(
            mock_cognito, "pool-id", "ACCOUNT#11111111-1111-1111-1111-111111111111", MagicMock()
        )

        assert username == "user-123"
        assert email == "user@example.com"
        mock_cognito.list_users.assert_called_once_with(
            UserPoolId="pool-id",
            Filter='sub = "11111111-1111-1111-1111-111111111111"',
            Limit=1,
        )

    def test_find_cognito_user_by_sub_not_found(self) -> None:
        """_find_cognito_user_by_sub returns (None, None) when user not found."""
        from src.handlers.admin_operations import _find_cognito_user_by_sub

        mock_cognito = MagicMock()
        mock_cognito.list_users.return_value = {"Users": []}

        username, email = _find_cognito_user_by_sub(
            mock_cognito, "pool-id", "ACCOUNT#11111111-1111-1111-1111-111111111111", MagicMock()
        )

        assert username is None
        assert email is None

    def test_find_cognito_user_by_sub_client_error(self) -> None:
        """_find_cognito_user_by_sub raises AppError when Cognito call fails."""
        from src.handlers.admin_operations import _find_cognito_user_by_sub

        mock_cognito = MagicMock()
        mock_cognito.list_users.side_effect = ClientError(
            {"Error": {"Code": "InternalErrorException", "Message": "Cognito failure"}},
            "ListUsers",
        )

        with pytest.raises(AppError) as exc_info:
            _find_cognito_user_by_sub(
                mock_cognito, "pool-id", "ACCOUNT#11111111-1111-1111-1111-111111111111", MagicMock()
            )

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_account_exists_in_dynamodb_unprefixed(self, dynamodb_table: Any) -> None:
        """_account_exists_in_dynamodb normalizes unprefixed account ID."""
        from src.handlers.admin_operations import _account_exists_in_dynamodb

        accounts_table = get_accounts_table()
        target_account_id = "11111111-1111-1111-1111-111111111111"
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{target_account_id}",
                "email": "target@example.com",
            }
        )

        assert _account_exists_in_dynamodb(target_account_id, MagicMock()) is True

    def test_account_exists_in_dynamodb_prefixed(self, dynamodb_table: Any) -> None:
        """_account_exists_in_dynamodb normalizes ACCOUNT#-prefixed account ID."""
        from src.handlers.admin_operations import _account_exists_in_dynamodb

        accounts_table = get_accounts_table()
        target_account_id = "11111111-1111-1111-1111-111111111111"
        accounts_table.put_item(
            Item={
                "accountId": f"ACCOUNT#{target_account_id}",
                "email": "target@example.com",
            }
        )

        assert _account_exists_in_dynamodb(f"ACCOUNT#{target_account_id}", MagicMock()) is True

    def test_account_exists_in_dynamodb_not_found(self, dynamodb_table: Any) -> None:
        """_account_exists_in_dynamodb returns False when account not in DynamoDB."""
        from src.handlers.admin_operations import _account_exists_in_dynamodb

        assert _account_exists_in_dynamodb("non-existent-user", MagicMock()) is False

    def test_account_exists_in_dynamodb_client_error(self) -> None:
        """_account_exists_in_dynamodb propagates ClientError."""
        from src.handlers.admin_operations import _account_exists_in_dynamodb

        with patch("src.handlers.admin_operations.tables.accounts.get_item") as mock_get:
            mock_get.side_effect = ClientError(
                {"Error": {"Code": "ResourceNotFoundException", "Message": "Table not found"}},
                "GetItem",
            )
            with pytest.raises(ClientError):
                _account_exists_in_dynamodb("test-user", MagicMock())


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

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # DynamoDB prefix-index query returns matching account
            mock_tables.accounts.query.return_value = {
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

            mock_batch_names.return_value = {"user-sub-123": "Test User"}
            mock_batch_groups.return_value = {"user@example.com": []}

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

            # Verify handler plumbs extracted sub and username into the batch helpers.
            assert mock_batch_names.call_args.args[0] == ["user-sub-123"]
            assert mock_batch_groups.call_args.args[0] is mock_client
            assert mock_batch_groups.call_args.args[1] == "test-pool-id"
            assert mock_batch_groups.call_args.args[2] == ["user@example.com"]

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

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
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

            mock_batch_names.return_value = {
                "dave-sub-123": "Dave Meiser",
                "jon-sub-456": "Jon Dupont",
            }
            mock_batch_groups.return_value = {
                "dave@daveandjonee.com": [],
                "jondupont@gmail.com": [],
            }

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

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
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

            mock_batch_names.return_value = {"john-sub-456": "John Smith"}
            mock_batch_groups.return_value = {"john@example.com": []}

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

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables"),
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_client.list_users.return_value = {"Users": [mock_cognito_user]}

            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {"user@example.com": []}

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

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables"),
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_client.list_users.return_value = {"Users": [mock_cognito_user]}

            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {"user@example.com": []}

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

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
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

        result = admin_search_user(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_search_user_invalid_query_raises_error(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test search with unsafe query raises INVALID_INPUT error."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": 'test"injection'},
        }

        result = admin_search_user(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT
        assert "valid UUID" in result["message"]

    def test_search_user_malformed_account_prefix_raises_error(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test search with ACCOUNT# prefix that is not a UUID is rejected."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "ACCOUNT#not-a-uuid"},
        }

        result = admin_search_user(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

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

        result = admin_search_user(event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

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

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
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

            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {"admin@example.com": ["ADMIN"]}

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

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
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

            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {"user@example.com": []}

            result = lambda_handler(event, lambda_context)

            # Returns list now
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["accountId"] == "user-sub-123"

    def test_search_user_by_account_prefix_not_found(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test search with ACCOUNT# prefix when user not found in Cognito."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "ACCOUNT#123e4567-e89b-12d3-a456-426614174000"},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables"):
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                # Cognito lookup returns no users
                mock_client.list_users.return_value = {"Users": []}

                result = admin_search_user(event, lambda_context)

                # Returns empty list when no user found
                assert result == []

    def test_search_user_by_uuid_not_found(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test search with UUID when user not found in Cognito."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"},  # Valid UUID
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables"):
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                # Cognito lookup returns no users
                mock_client.list_users.return_value = {"Users": []}

                result = admin_search_user(event, lambda_context)

                # Returns empty list when no user found
                assert result == []

    def test_search_user_dynamodb_account_no_cognito_user(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test when DynamoDB has account but Cognito user doesn't exist."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "orphan"},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                # DynamoDB has orphaned account (Cognito user deleted)
                mock_tables.accounts.scan.return_value = {
                    "Items": [
                        {
                            "accountId": "ACCOUNT#orphan-user",
                            "email": "orphan@example.com",
                        }
                    ]
                }

                # Cognito lookup returns no user for sub, no email match either
                mock_client.list_users.return_value = {"Users": []}

                result = admin_search_user(event, lambda_context)

                # Empty because Cognito user doesn't exist
                assert result == []

    def test_search_user_duplicate_deduplicated(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test duplicate users from DynamoDB and Cognito are deduplicated."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "test"},
        }

        mock_cognito_user = {
            "Username": "test@example.com",
            "Attributes": [
                {"Name": "sub", "Value": "test-sub-123"},
                {"Name": "email", "Value": "test@example.com"},
            ],
            "Enabled": True,
            "UserStatus": "CONFIRMED",
            "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # DynamoDB has the account
            mock_tables.accounts.scan.return_value = {
                "Items": [
                    {
                        "accountId": "ACCOUNT#test-sub-123",
                        "email": "test@example.com",
                    }
                ]
            }

            # Both DynamoDB sub lookup and email prefix return same user
            mock_client.list_users.return_value = {"Users": [mock_cognito_user]}

            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {"test@example.com": []}

            result = admin_search_user(event, lambda_context)

            # Should only return one result (deduplicated)
            assert len(result) == 1
            assert result[0]["accountId"] == "test-sub-123"

    def test_search_user_cognito_only_user_added(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test user found only via Cognito email search is added (branch 307)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "cognitoonly"},
        }

        # User only exists in Cognito (never logged in, no DynamoDB record)
        mock_cognito_only_user = {
            "Username": "cognitoonly@example.com",
            "Attributes": [
                {"Name": "sub", "Value": "cognito-only-sub"},
                {"Name": "email", "Value": "cognitoonly@example.com"},
            ],
            "Enabled": True,
            "UserStatus": "CONFIRMED",
            "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # DynamoDB has NO matching accounts
            mock_tables.accounts.scan.return_value = {"Items": []}

            # Cognito email prefix search returns user (not found in DynamoDB)
            mock_client.list_users.return_value = {"Users": [mock_cognito_only_user]}

            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {"cognitoonly@example.com": []}

            result = admin_search_user(event, lambda_context)

            # Should return one result from Cognito only search
            assert len(result) == 1
            assert result[0]["accountId"] == "cognito-only-sub"
            assert result[0]["email"] == "cognitoonly@example.com"

    def test_search_user_malformed_account_id_skipped(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test DynamoDB account without ACCOUNT# prefix is skipped (branch 293->290)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "malformed"},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                # DynamoDB returns account without ACCOUNT# prefix (malformed data)
                mock_tables.accounts.scan.return_value = {
                    "Items": [
                        {
                            "accountId": "malformed-no-prefix",  # Missing ACCOUNT# prefix
                            "email": "malformed@example.com",
                        }
                    ]
                }

                # Cognito returns nothing
                mock_client.list_users.return_value = {"Users": []}

                result = admin_search_user(event, lambda_context)

                # Should return empty since malformed account is skipped
                assert result == []

    def test_search_user_dynamodb_pagination(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test DynamoDB scan pagination in search."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "multi"},
        }

        mock_cognito_user = {
            "Username": "multi@example.com",
            "Attributes": [
                {"Name": "sub", "Value": "multi-sub"},
                {"Name": "email", "Value": "multi@example.com"},
            ],
            "Enabled": True,
            "UserStatus": "CONFIRMED",
            "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # DynamoDB scan returns with pagination (LastEvaluatedKey)
            mock_tables.accounts.scan.side_effect = [
                {
                    "Items": [{"accountId": "ACCOUNT#multi-sub", "email": "multi@example.com"}],
                    "LastEvaluatedKey": {"accountId": "ACCOUNT#multi-sub"},
                },
                {"Items": []},  # Second page is empty
            ]

            mock_client.list_users.return_value = {"Users": [mock_cognito_user]}

            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {"multi@example.com": []}

            result = admin_search_user(event, lambda_context)

            assert len(result) == 1
            # Verify pagination was used
            assert mock_tables.accounts.scan.call_count == 2

    def test_search_user_unexpected_exception(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test exception handler for unexpected errors."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "test"},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables"):
                mock_get_client.side_effect = RuntimeError("Unexpected error")

                result = admin_search_user(event, lambda_context)

                assert result["__isError"] is True
                assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
                assert "Failed to search user" in result["message"]

    def test_search_user_by_uuid_throttled_returns_resource_busy(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """UUID search throttled by Cognito returns structured RESOURCE_BUSY error (#456)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        uuid_str = "12345678-1234-1234-1234-123456789abc"
        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": uuid_str},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.list_users.side_effect = ClientError(
                {"Error": {"Code": "TooManyRequestsException", "Message": "Throttled"}},
                "ListUsers",
            )

            result = admin_search_user(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.RESOURCE_BUSY
            assert result["message"] == "Temporarily unable to load data. Please retry."

    def test_search_user_by_account_id_throttled_returns_resource_busy(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """ACCOUNT#UUID search throttled by Cognito returns structured RESOURCE_BUSY error (#456)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "ACCOUNT#12345678-1234-1234-1234-123456789abc"},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.list_users.side_effect = ClientError(
                {"Error": {"Code": "TooManyRequestsException", "Message": "Throttled"}},
                "ListUsers",
            )

            result = admin_search_user(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.RESOURCE_BUSY
            assert result["message"] == "Temporarily unable to load data. Please retry."

    def test_search_user_general_query_sub_lookup_throttled_returns_resource_busy(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """DynamoDB-matched user sub lookup throttled by Cognito returns structured RESOURCE_BUSY error (#456)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "test"},
        }

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_tables.accounts.scan.return_value = {
                "Items": [{"accountId": "ACCOUNT#test-sub-123", "email": "test@example.com"}]
            }

            mock_client.list_users.side_effect = ClientError(
                {"Error": {"Code": "TooManyRequestsException", "Message": "Throttled"}},
                "ListUsers",
            )

            result = admin_search_user(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.RESOURCE_BUSY
            assert result["message"] == "Temporarily unable to load data. Please retry."

    def test_search_user_general_query_email_prefix_throttled_returns_resource_busy(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Cognito email prefix search throttled returns structured RESOURCE_BUSY error (#456)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "test"},
        }

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_tables.accounts.scan.return_value = {"Items": []}

            mock_client.list_users.side_effect = ClientError(
                {"Error": {"Code": "TooManyRequestsException", "Message": "Throttled"}},
                "ListUsers",
            )

            result = admin_search_user(event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.RESOURCE_BUSY
            assert result["message"] == "Temporarily unable to load data. Please retry."


class TestAdminSearchUserThrottling:
    """Tests for throttling error handling in Cognito search helpers (#456)."""

    @pytest.mark.parametrize(
        "error_code",
        ["TooManyRequestsException", "ThrottlingException", "ProvisionedThroughputExceededException"],
    )
    def test_search_user_by_sub_throttling_raises_resource_busy(self, error_code: str) -> None:
        """Throttling in _search_user_by_sub raises retryable RESOURCE_BUSY."""
        mock_cognito = MagicMock()
        mock_cognito.list_users.side_effect = ClientError(
            {"Error": {"Code": error_code, "Message": "Throttled"}},
            "ListUsers",
        )
        mock_logger = MagicMock()

        with pytest.raises(AppError) as exc_info:
            _search_user_by_sub(mock_cognito, "pool-id", "sub-123", mock_logger)

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY
        assert exc_info.value.message == "Temporarily unable to load data. Please retry."
        mock_logger.warning.assert_called_once()
        log_kwargs = mock_logger.warning.call_args[1]
        assert log_kwargs["error_code"] == error_code
        assert log_kwargs["sub"] == "sub-123"

    def test_search_user_by_sub_non_throttling_client_error_returns_none(self) -> None:
        """Non-throttling ClientError in _search_user_by_sub logs warning and returns None."""
        mock_cognito = MagicMock()
        mock_cognito.list_users.side_effect = ClientError(
            {"Error": {"Code": "InternalErrorException", "Message": "Service error"}},
            "ListUsers",
        )
        mock_logger = MagicMock()

        result = _search_user_by_sub(mock_cognito, "pool-id", "sub-123", mock_logger)
        assert result is None
        mock_logger.warning.assert_called_once()
        assert "Cognito search by sub failed" in mock_logger.warning.call_args[0][0]

    def test_search_user_by_sub_genuine_not_found_returns_none(self) -> None:
        """Empty Cognito Users list in _search_user_by_sub returns None."""
        mock_cognito = MagicMock()
        mock_cognito.list_users.return_value = {"Users": []}
        mock_logger = MagicMock()

        result = _search_user_by_sub(mock_cognito, "pool-id", "sub-123", mock_logger)
        assert result is None
        mock_logger.warning.assert_not_called()

    def test_search_user_by_sub_success_returns_user(self) -> None:
        """Successful search in _search_user_by_sub returns the first user dict."""
        mock_cognito = MagicMock()
        user = {"Username": "user-1", "Attributes": [{"Name": "sub", "Value": "sub-123"}]}
        mock_cognito.list_users.return_value = {"Users": [user]}
        mock_logger = MagicMock()

        result = _search_user_by_sub(mock_cognito, "pool-id", "sub-123", mock_logger)
        assert result == user
        mock_logger.warning.assert_not_called()

    @pytest.mark.parametrize(
        "error_code",
        ["TooManyRequestsException", "ThrottlingException", "ProvisionedThroughputExceededException"],
    )
    def test_search_users_in_cognito_by_email_prefix_throttling_raises_resource_busy(self, error_code: str) -> None:
        """Throttling in _search_users_in_cognito_by_email_prefix raises retryable RESOURCE_BUSY."""
        mock_cognito = MagicMock()
        mock_cognito.list_users.side_effect = ClientError(
            {"Error": {"Code": error_code, "Message": "Throttled"}},
            "ListUsers",
        )
        mock_logger = MagicMock()

        with pytest.raises(AppError) as exc_info:
            _search_users_in_cognito_by_email_prefix(mock_cognito, "pool-id", "alice@exa", mock_logger)

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY
        assert exc_info.value.message == "Temporarily unable to load data. Please retry."
        mock_logger.warning.assert_called_once()
        log_kwargs = mock_logger.warning.call_args[1]
        assert log_kwargs["error_code"] == error_code
        assert log_kwargs["query"] == "a***@exa"

    def test_search_users_in_cognito_by_email_prefix_non_throttling_client_error_returns_empty(self) -> None:
        """Non-throttling ClientError in _search_users_in_cognito_by_email_prefix logs warning and returns []."""
        mock_cognito = MagicMock()
        mock_cognito.list_users.side_effect = ClientError(
            {"Error": {"Code": "InternalErrorException", "Message": "Service error"}},
            "ListUsers",
        )
        mock_logger = MagicMock()

        result = _search_users_in_cognito_by_email_prefix(mock_cognito, "pool-id", "alice@exa", mock_logger)
        assert result == []
        mock_logger.warning.assert_called_once()
        assert "Cognito email prefix search failed" in mock_logger.warning.call_args[0][0]
        log_kwargs = mock_logger.warning.call_args[1]
        assert log_kwargs["query"] == "a***@exa"

    def test_search_users_in_cognito_by_email_prefix_genuine_not_found_returns_empty(self) -> None:
        """Empty Cognito Users list in _search_users_in_cognito_by_email_prefix returns []."""
        mock_cognito = MagicMock()
        mock_cognito.list_users.return_value = {"Users": []}
        mock_logger = MagicMock()

        result = _search_users_in_cognito_by_email_prefix(mock_cognito, "pool-id", "user@", mock_logger)
        assert result == []
        mock_logger.warning.assert_not_called()

    def test_search_users_in_cognito_by_email_prefix_success_returns_users(self) -> None:
        """Successful search in _search_users_in_cognito_by_email_prefix returns users list."""
        mock_cognito = MagicMock()
        users = [{"Username": "user-1"}, {"Username": "user-2"}]
        mock_cognito.list_users.return_value = {"Users": users}
        mock_logger = MagicMock()

        result = _search_users_in_cognito_by_email_prefix(mock_cognito, "pool-id", "user@", mock_logger)
        assert result == users
        mock_logger.warning.assert_not_called()


class TestBatchHelpers:
    """Tests for the batched DynamoDB display-name and Cognito group helpers."""

    def test_batch_get_display_names_empty(
        self,
        monkeypatch: Any,
    ) -> None:
        """Empty account-id list returns an empty map."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "test-accounts")

        result = _batch_get_display_names([], MagicMock())
        assert result == {}

    def test_batch_get_display_names_single(
        self,
        monkeypatch: Any,
    ) -> None:
        """A single account id is looked up and its display name returned."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "test-accounts")

        with patch("src.utils.dynamodb.get_dynamodb_resource") as mock_get_resource:
            mock_resource = MagicMock()
            mock_get_resource.return_value = mock_resource
            mock_resource.batch_get_item.return_value = {
                "Responses": {
                    "test-accounts": [{"accountId": "ACCOUNT#user-1", "givenName": "John", "familyName": "Doe"}]
                }
            }

            result = _batch_get_display_names(["user-1"], MagicMock())

            assert result == {"user-1": "John Doe"}
            mock_resource.batch_get_item.assert_called_once_with(
                RequestItems={"test-accounts": {"Keys": [{"accountId": "ACCOUNT#user-1"}]}}
            )

    def test_batch_get_display_names_prefix_normalized(
        self,
        monkeypatch: Any,
    ) -> None:
        """ACCOUNT# prefixed ids are normalized and stripped when building the map."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "test-accounts")

        with patch("src.utils.dynamodb.get_dynamodb_resource") as mock_get_resource:
            mock_resource = MagicMock()
            mock_get_resource.return_value = mock_resource
            mock_resource.batch_get_item.return_value = {
                "Responses": {
                    "test-accounts": [{"accountId": "ACCOUNT#user-1", "givenName": "Jane", "familyName": "Doe"}]
                }
            }

            result = _batch_get_display_names(["ACCOUNT#user-1"], MagicMock())

            assert result == {"user-1": "Jane Doe"}

    def test_batch_get_display_names_chunks_at_100(
        self,
        monkeypatch: Any,
    ) -> None:
        """BatchGetItem is chunked at DynamoDB's 100-key limit."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "test-accounts")

        ids = [f"user-{i}" for i in range(150)]

        with patch("src.utils.dynamodb.get_dynamodb_resource") as mock_get_resource:
            mock_resource = MagicMock()
            mock_get_resource.return_value = mock_resource
            mock_resource.batch_get_item.side_effect = [
                {"Responses": {"test-accounts": []}},
                {"Responses": {"test-accounts": []}},
            ]

            _batch_get_display_names(ids, MagicMock())

            assert mock_resource.batch_get_item.call_count == 2
            first_keys = mock_resource.batch_get_item.call_args_list[0].kwargs["RequestItems"]["test-accounts"]["Keys"]
            second_keys = mock_resource.batch_get_item.call_args_list[1].kwargs["RequestItems"]["test-accounts"]["Keys"]
            assert len(first_keys) == 100
            assert len(second_keys) == 50

    def test_batch_get_display_names_duplicate_ids_deduped(
        self,
        monkeypatch: Any,
    ) -> None:
        """Duplicate account ids are deduplicated before calling BatchGetItem."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "test-accounts")

        with patch("src.utils.dynamodb.get_dynamodb_resource") as mock_get_resource:
            mock_resource = MagicMock()
            mock_get_resource.return_value = mock_resource
            mock_resource.batch_get_item.return_value = {
                "Responses": {
                    "test-accounts": [{"accountId": "ACCOUNT#user-1", "givenName": "John", "familyName": "Doe"}]
                }
            }

            result = _batch_get_display_names(["user-1", "ACCOUNT#user-1", "user-1"], MagicMock())

            assert result == {"user-1": "John Doe"}
            keys = mock_resource.batch_get_item.call_args.kwargs["RequestItems"]["test-accounts"]["Keys"]
            assert len(keys) == 1

    def test_batch_get_display_names_empty_name_fields_skipped(
        self,
        monkeypatch: Any,
    ) -> None:
        """Items with neither givenName nor familyName do not populate displayName."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "test-accounts")

        with patch("src.utils.dynamodb.get_dynamodb_resource") as mock_get_resource:
            mock_resource = MagicMock()
            mock_get_resource.return_value = mock_resource
            mock_resource.batch_get_item.return_value = {
                "Responses": {"test-accounts": [{"accountId": "ACCOUNT#user-1", "givenName": "", "familyName": ""}]}
            }

            result = _batch_get_display_names(["user-1"], MagicMock())

            assert result == {}

    def test_batch_get_display_names_client_error_handled(
        self,
        monkeypatch: Any,
    ) -> None:
        """A non-throttling ClientError during BatchGetItem raises INTERNAL_ERROR."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "test-accounts")

        with patch("src.utils.dynamodb.get_dynamodb_resource") as mock_get_resource:
            mock_resource = MagicMock()
            mock_get_resource.return_value = mock_resource
            mock_resource.batch_get_item.side_effect = ClientError(
                {"Error": {"Code": "InternalServerError", "Message": "boom"}},
                "BatchGetItem",
            )

            with pytest.raises(AppError) as exc_info:
                _batch_get_display_names(["user-1"], MagicMock())

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
            assert "Failed to load data" in exc_info.value.message

    def test_batch_get_display_names_throttling_raises_retryable(
        self,
        monkeypatch: Any,
    ) -> None:
        """A throttling ClientError during BatchGetItem raises retryable RESOURCE_BUSY."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "test-accounts")

        with patch("src.utils.dynamodb.get_dynamodb_resource") as mock_get_resource:
            mock_resource = MagicMock()
            mock_get_resource.return_value = mock_resource
            mock_resource.batch_get_item.side_effect = ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "throttled"}},
                "BatchGetItem",
            )

            with pytest.raises(AppError) as exc_info:
                _batch_get_display_names(["user-1"], MagicMock())

            assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY
            assert exc_info.value.message == "Temporarily unable to load data. Please retry."

    def test_batch_get_display_names_unexpected_exception_raises_internal(
        self,
        monkeypatch: Any,
    ) -> None:
        """A non-ClientError exception during BatchGetItem raises INTERNAL_ERROR."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "test-accounts")

        with patch("src.utils.dynamodb.get_dynamodb_resource") as mock_get_resource:
            mock_resource = MagicMock()
            mock_get_resource.return_value = mock_resource
            mock_resource.batch_get_item.side_effect = RuntimeError("network blip")

            with pytest.raises(AppError) as exc_info:
                _batch_get_display_names(["user-1"], MagicMock())

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
            assert "Failed to load data" in exc_info.value.message

    def test_batch_get_display_names_unprocessed_keys_retried(
        self,
        monkeypatch: Any,
    ) -> None:
        """UnprocessedKeys from BatchGetItem are retried before returning results."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "test-accounts")

        with patch("src.utils.dynamodb.get_dynamodb_resource") as mock_get_resource:
            mock_resource = MagicMock()
            mock_get_resource.return_value = mock_resource
            mock_resource.batch_get_item.side_effect = [
                {
                    "Responses": {"test-accounts": []},
                    "UnprocessedKeys": {"test-accounts": {"Keys": [{"accountId": "ACCOUNT#user-1"}]}},
                },
                {
                    "Responses": {
                        "test-accounts": [{"accountId": "ACCOUNT#user-1", "givenName": "John", "familyName": "Doe"}]
                    }
                },
            ]

            result = _batch_get_display_names(["user-1"], MagicMock())

            assert result == {"user-1": "John Doe"}
            assert mock_resource.batch_get_item.call_count == 2

    def test_batch_get_display_names_unprocessed_keys_across_batches(
        self,
        monkeypatch: Any,
    ) -> None:
        """UnprocessedKeys are retried and the outer batch loop continues."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "test-accounts")

        ids = [f"user-{i}" for i in range(101)]
        retry_keys = [{"accountId": "ACCOUNT#user-0"}]

        with patch("src.utils.dynamodb.get_dynamodb_resource") as mock_get_resource:
            mock_resource = MagicMock()
            mock_get_resource.return_value = mock_resource
            mock_resource.batch_get_item.side_effect = [
                {
                    "Responses": {"test-accounts": []},
                    "UnprocessedKeys": {"test-accounts": {"Keys": retry_keys}},
                },
                {
                    "Responses": {
                        "test-accounts": [{"accountId": "ACCOUNT#user-0", "givenName": "A", "familyName": "B"}]
                    },
                },
                {
                    "Responses": {
                        "test-accounts": [{"accountId": "ACCOUNT#user-100", "givenName": "C", "familyName": "D"}]
                    },
                },
            ]

            result = _batch_get_display_names(ids, MagicMock())

            assert result == {
                "user-0": "A B",
                "user-100": "C D",
            }
            assert mock_resource.batch_get_item.call_count == 3

    def test_batch_get_display_names_unprocessed_keys_exhaust_attempts(
        self,
        monkeypatch: Any,
    ) -> None:
        """UnprocessedKeys that survive every attempt now raise retryable RESOURCE_BUSY (#557)."""
        monkeypatch.setenv("ACCOUNTS_TABLE_NAME", "test-accounts")

        ids = [f"user-{i}" for i in range(101)]
        first_key = {"accountId": "ACCOUNT#user-0"}

        with patch("src.utils.dynamodb.get_dynamodb_resource") as mock_get_resource:
            mock_resource = MagicMock()
            mock_get_resource.return_value = mock_resource
            mock_resource.batch_get_item.side_effect = [
                {
                    "Responses": {"test-accounts": []},
                    "UnprocessedKeys": {"test-accounts": {"Keys": [first_key]}},
                },
                {
                    "Responses": {"test-accounts": []},
                    "UnprocessedKeys": {"test-accounts": {"Keys": [first_key]}},
                },
                {
                    "Responses": {"test-accounts": []},
                    "UnprocessedKeys": {"test-accounts": {"Keys": [first_key]}},
                },
                {
                    "Responses": {
                        "test-accounts": [{"accountId": "ACCOUNT#user-100", "givenName": "C", "familyName": "D"}]
                    },
                },
            ]

            with pytest.raises(AppError) as exc_info:
                _batch_get_display_names(ids, MagicMock())

            assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY
            # The stuck chunk is abandoned after its retries; the second chunk is never fetched,
            # so no silently incomplete display-name map can reach the admin UI.
            assert mock_resource.batch_get_item.call_count == 3

    def test_batch_get_user_groups_empty(
        self,
    ) -> None:
        """Empty username list returns an empty map without calling Cognito."""
        mock_cognito = MagicMock()

        result = _batch_get_user_groups(mock_cognito, "pool-id", [], MagicMock())

        assert result == {}
        mock_cognito.admin_list_groups_for_user.assert_not_called()

    def test_batch_get_user_groups_filters_falsy_usernames(
        self,
    ) -> None:
        """Falsy usernames are filtered out before invoking Cognito."""
        mock_cognito = MagicMock()
        mock_cognito.admin_list_groups_for_user.return_value = {"Groups": []}

        result = _batch_get_user_groups(mock_cognito, "pool-id", ["", "user-1", None, "user-1"], MagicMock())

        assert result == {"user-1": []}
        mock_cognito.admin_list_groups_for_user.assert_called_once_with(UserPoolId="pool-id", Username="user-1")

    def test_batch_get_user_groups_parallel(
        self,
    ) -> None:
        """Groups are fetched in parallel and mapped by username."""
        mock_cognito = MagicMock()

        def side_effect(UserPoolId: str, Username: str) -> Dict[str, Any]:
            if Username == "user-1":
                return {"Groups": [{"GroupName": "ADMIN"}]}
            return {"Groups": []}

        mock_cognito.admin_list_groups_for_user.side_effect = side_effect

        result = _batch_get_user_groups(mock_cognito, "pool-id", ["user-1", "user-2"], MagicMock())

        assert result == {"user-1": ["ADMIN"], "user-2": []}

    def test_batch_get_user_groups_per_user_error_handled(
        self,
    ) -> None:
        """A per-user group lookup failure raises a typed AppError (#291)."""
        mock_cognito = MagicMock()
        mock_cognito.admin_list_groups_for_user.side_effect = ClientError(
            {"Error": {"Code": "InternalErrorException", "Message": "boom"}},
            "AdminListGroupsForUser",
        )

        with pytest.raises(AppError) as exc_info:
            _batch_get_user_groups(mock_cognito, "pool-id", ["user-1"], MagicMock())

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert "Failed to load user groups" in exc_info.value.message

    def test_batch_get_user_groups_per_user_throttling_raises_retryable(
        self,
    ) -> None:
        """A throttled per-user group lookup raises retryable RESOURCE_BUSY (#291)."""
        mock_cognito = MagicMock()
        mock_cognito.admin_list_groups_for_user.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "throttled"}},
            "AdminListGroupsForUser",
        )

        with pytest.raises(AppError) as exc_info:
            _batch_get_user_groups(mock_cognito, "pool-id", ["user-1"], MagicMock())

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY
        assert exc_info.value.message == "Temporarily unable to load data. Please retry."

    def test_batch_get_user_groups_per_user_too_many_requests_raises_retryable(
        self,
    ) -> None:
        """A per-user group lookup throttled with TooManyRequestsException raises RESOURCE_BUSY (#456)."""
        mock_cognito = MagicMock()
        mock_cognito.admin_list_groups_for_user.side_effect = ClientError(
            {"Error": {"Code": "TooManyRequestsException", "Message": "throttled"}},
            "AdminListGroupsForUser",
        )

        with pytest.raises(AppError) as exc_info:
            _batch_get_user_groups(mock_cognito, "pool-id", ["user-1"], MagicMock())

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY
        assert exc_info.value.message == "Temporarily unable to load data. Please retry."

    def test_batch_get_user_groups_executor_error_handled(
        self,
    ) -> None:
        """A failure inside the parallel executor raises INTERNAL_ERROR."""
        mock_cognito = MagicMock()

        with patch("src.handlers.admin_operations.ThreadPoolExecutor") as mock_executor_cls:
            mock_executor = MagicMock()
            mock_executor_cls.return_value = mock_executor
            mock_executor.__enter__ = MagicMock(return_value=mock_executor)
            mock_executor.__exit__ = MagicMock(return_value=False)
            mock_executor.map.side_effect = RuntimeError("executor failed")

            with pytest.raises(AppError) as exc_info:
                _batch_get_user_groups(mock_cognito, "pool-id", ["user-1"], MagicMock())

            assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
            assert "Failed to load user groups" in exc_info.value.message


class TestAdminGetUserProfiles:
    """Tests for admin_get_user_profiles function."""

    def test_get_user_profiles_success(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        profiles_table: Any,
        sample_account_id: str,
    ) -> None:
        """Test successful profile retrieval for a user."""
        # Create a profile for the target user
        target_account_id = "ACCOUNT#target-user-123"
        profiles_table.put_item(
            Item={
                "ownerAccountId": target_account_id,
                "profileId": "PROFILE#profile-1",
                "sellerName": "Test Scout",
                "createdAt": "2024-01-01T00:00:00Z",
            }
        )

        admin_appsync_event["info"]["fieldName"] = "adminGetUserProfiles"
        admin_appsync_event["arguments"] = {"accountId": "target-user-123"}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["profileId"] == "PROFILE#profile-1"
        assert result[0]["sellerName"] == "Test Scout"

    def test_get_user_profiles_with_prefix(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        profiles_table: Any,
    ) -> None:
        """Test profile retrieval with ACCOUNT# prefix."""
        target_account_id = "ACCOUNT#target-user-456"
        profiles_table.put_item(
            Item={
                "ownerAccountId": target_account_id,
                "profileId": "PROFILE#profile-2",
                "sellerName": "Another Scout",
            }
        )

        admin_appsync_event["info"]["fieldName"] = "adminGetUserProfiles"
        admin_appsync_event["arguments"] = {"accountId": target_account_id}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert len(result) == 1
        assert result[0]["profileId"] == "PROFILE#profile-2"

    def test_get_user_profiles_empty(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test empty profile list for user with no profiles."""
        admin_appsync_event["info"]["fieldName"] = "adminGetUserProfiles"
        admin_appsync_event["arguments"] = {"accountId": "nonexistent-user"}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result == []

    def test_get_user_profiles_missing_account_id(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test error when accountId is missing."""
        admin_appsync_event["info"]["fieldName"] = "adminGetUserProfiles"
        admin_appsync_event["arguments"] = {}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_get_user_profiles_non_admin(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test forbidden for non-admin user."""
        non_admin_appsync_event["info"]["fieldName"] = "adminGetUserProfiles"
        non_admin_appsync_event["arguments"] = {"accountId": "some-user"}

        result = lambda_handler(non_admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

    def test_get_user_profiles_paginates(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that profile retrieval follows DynamoDB pagination."""
        with patch("src.handlers.admin_operations.query_all_items") as mock_query_all:
            mock_query_all.return_value = [{"profileId": f"PROFILE#{i}", "sellerName": f"Scout {i}"} for i in range(3)]

            admin_appsync_event["info"]["fieldName"] = "adminGetUserProfiles"
            admin_appsync_event["arguments"] = {"accountId": "paginated-user"}

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert len(result) == 3
            mock_query_all.assert_called_once()


class TestAdminGetUserCatalogs:
    """Tests for admin_get_user_catalogs function."""

    def test_get_user_catalogs_success(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        catalogs_table: Any,
    ) -> None:
        """Test successful catalog retrieval for a user."""
        target_account_id = "ACCOUNT#target-user-789"
        catalogs_table.put_item(
            Item={
                "ownerAccountId": target_account_id,
                "catalogId": "CATALOG#cat-1",
                "catalogName": "Test Catalog",
                "catalogType": "USER",
            }
        )

        admin_appsync_event["info"]["fieldName"] = "adminGetUserCatalogs"
        admin_appsync_event["arguments"] = {"accountId": "target-user-789"}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["catalogId"] == "CATALOG#cat-1"
        assert result[0]["catalogName"] == "Test Catalog"

    def test_get_user_catalogs_excludes_deleted(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        catalogs_table: Any,
    ) -> None:
        """Test that deleted catalogs are excluded."""
        target_account_id = "ACCOUNT#target-user-del"
        # Active catalog
        catalogs_table.put_item(
            Item={
                "ownerAccountId": target_account_id,
                "catalogId": "CATALOG#active",
                "catalogName": "Active",
            }
        )
        # Deleted catalog
        catalogs_table.put_item(
            Item={
                "ownerAccountId": target_account_id,
                "catalogId": "CATALOG#deleted",
                "catalogName": "Deleted",
                "isDeleted": True,
            }
        )

        admin_appsync_event["info"]["fieldName"] = "adminGetUserCatalogs"
        admin_appsync_event["arguments"] = {"accountId": "target-user-del"}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert len(result) == 1
        assert result[0]["catalogId"] == "CATALOG#active"

    def test_get_user_catalogs_missing_account_id(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test error when accountId is missing."""
        admin_appsync_event["info"]["fieldName"] = "adminGetUserCatalogs"
        admin_appsync_event["arguments"] = {"accountId": ""}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_get_user_catalogs_non_admin(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test forbidden for non-admin user."""
        non_admin_appsync_event["info"]["fieldName"] = "adminGetUserCatalogs"
        non_admin_appsync_event["arguments"] = {"accountId": "some-user"}

        result = lambda_handler(non_admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

    def test_get_user_catalogs_paginates(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that catalog retrieval follows DynamoDB pagination."""
        with patch("src.handlers.admin_operations.query_all_items") as mock_query_all:
            mock_query_all.return_value = [
                {"catalogId": f"CATALOG#{i}", "catalogName": f"Catalog {i}"} for i in range(3)
            ]

            admin_appsync_event["info"]["fieldName"] = "adminGetUserCatalogs"
            admin_appsync_event["arguments"] = {"accountId": "paginated-user"}

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert len(result) == 3
            mock_query_all.assert_called_once()
            call_kwargs = mock_query_all.call_args[0][1]
            assert call_kwargs["IndexName"] == "ownerAccountId-index"


class TestAdminGetUserCampaigns:
    """Tests for admin_get_user_campaigns function."""

    def test_get_user_campaigns_success(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        profiles_table: Any,
        campaigns_table: Any,
    ) -> None:
        """Test successful campaign retrieval across profiles."""
        target_account_id = "ACCOUNT#target-campaign-user"
        profile_id = "PROFILE#profile-camp"

        # Create profile
        profiles_table.put_item(
            Item={
                "ownerAccountId": target_account_id,
                "profileId": profile_id,
                "sellerName": "Scout",
            }
        )
        # Create campaign
        campaigns_table.put_item(
            Item={
                "profileId": profile_id,
                "campaignId": "CAMPAIGN#camp-1",
                "campaignName": "Spring Sale",
            }
        )

        admin_appsync_event["info"]["fieldName"] = "adminGetUserCampaigns"
        admin_appsync_event["arguments"] = {"accountId": "target-campaign-user"}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["campaignId"] == "CAMPAIGN#camp-1"
        assert result[0]["campaignName"] == "Spring Sale"

    def test_get_user_campaigns_multiple_profiles(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        profiles_table: Any,
        campaigns_table: Any,
    ) -> None:
        """Test campaign retrieval from multiple profiles."""
        target_account_id = "ACCOUNT#multi-profile-user"

        # Create two profiles
        profiles_table.put_item(
            Item={
                "ownerAccountId": target_account_id,
                "profileId": "PROFILE#p1",
                "sellerName": "Scout 1",
            }
        )
        profiles_table.put_item(
            Item={
                "ownerAccountId": target_account_id,
                "profileId": "PROFILE#p2",
                "sellerName": "Scout 2",
            }
        )
        # Create campaigns for each profile
        campaigns_table.put_item(
            Item={
                "profileId": "PROFILE#p1",
                "campaignId": "CAMPAIGN#c1",
                "campaignName": "Campaign 1",
            }
        )
        campaigns_table.put_item(
            Item={
                "profileId": "PROFILE#p2",
                "campaignId": "CAMPAIGN#c2",
                "campaignName": "Campaign 2",
            }
        )

        admin_appsync_event["info"]["fieldName"] = "adminGetUserCampaigns"
        admin_appsync_event["arguments"] = {"accountId": "multi-profile-user"}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert len(result) == 2
        campaign_ids = {c["campaignId"] for c in result}
        assert "CAMPAIGN#c1" in campaign_ids
        assert "CAMPAIGN#c2" in campaign_ids

    def test_get_user_campaigns_profile_without_profile_id(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test campaign retrieval skips profiles without profileId (coverage for line 1126->1124)."""
        admin_appsync_event["info"]["fieldName"] = "adminGetUserCampaigns"
        admin_appsync_event["arguments"] = {"accountId": "profile-no-id-user"}

        with (
            patch("src.handlers.deletion_cascade.tables") as mock_cascade_tables,
            patch("src.handlers.admin_operations.tables") as mock_tables,
        ):
            # Mock profiles query returning a malformed profile without profileId
            mock_cascade_tables.profiles.query.return_value = {
                "Items": [
                    {
                        "ownerAccountId": "ACCOUNT#profile-no-id-user",
                        "profileId": "PROFILE#valid",
                        "sellerName": "Valid Scout",
                    },
                    {
                        "ownerAccountId": "ACCOUNT#profile-no-id-user",
                        # No profileId field - should be skipped
                        "sellerName": "Malformed Scout",
                    },
                ]
            }

            # Mock campaigns query for valid profile
            mock_tables.campaigns.query.return_value = {
                "Items": [
                    {
                        "profileId": "PROFILE#valid",
                        "campaignId": "CAMPAIGN#valid-c",
                        "campaignName": "Valid Campaign",
                    }
                ]
            }

            result = lambda_handler(admin_appsync_event, lambda_context)

            # Should only have 1 campaign from the valid profile
            assert len(result) == 1
            assert result[0]["campaignId"] == "CAMPAIGN#valid-c"
            # Should have only queried campaigns once (for valid profile)
            assert mock_tables.campaigns.query.call_count == 1

    def test_get_user_campaigns_empty(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test empty campaign list for user with no profiles."""
        admin_appsync_event["info"]["fieldName"] = "adminGetUserCampaigns"
        admin_appsync_event["arguments"] = {"accountId": "user-no-campaigns"}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result == []

    def test_get_user_campaigns_missing_account_id(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test error when accountId is missing."""
        admin_appsync_event["info"]["fieldName"] = "adminGetUserCampaigns"
        admin_appsync_event["arguments"] = {}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_get_user_campaigns_non_admin(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test forbidden for non-admin user."""
        non_admin_appsync_event["info"]["fieldName"] = "adminGetUserCampaigns"
        non_admin_appsync_event["arguments"] = {"accountId": "some-user"}

        result = lambda_handler(non_admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN


class TestAdminGetUserSharedCampaigns:
    """Tests for admin_get_user_shared_campaigns function."""

    def test_get_user_shared_campaigns_success(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        shared_campaigns_table: Any,
    ) -> None:
        """Test successful shared campaign retrieval."""
        creator_id = "ACCOUNT#creator-123"
        shared_campaigns_table.put_item(
            Item={
                "sharedCampaignCode": "ABC123",
                "SK": "METADATA",
                "createdBy": creator_id,
                "createdAt": "2024-01-01T00:00:00Z",
                "catalogId": "CATALOG#cat-1",
                "campaignName": "Shared Campaign",
            }
        )

        admin_appsync_event["info"]["fieldName"] = "adminGetUserSharedCampaigns"
        admin_appsync_event["arguments"] = {"accountId": "creator-123"}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["sharedCampaignCode"] == "ABC123"

    def test_get_user_shared_campaigns_empty(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test empty list when user has no shared campaigns."""
        admin_appsync_event["info"]["fieldName"] = "adminGetUserSharedCampaigns"
        admin_appsync_event["arguments"] = {"accountId": "no-shared-user"}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result == []

    def test_get_user_shared_campaigns_missing_account_id(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test error when accountId is missing."""
        admin_appsync_event["info"]["fieldName"] = "adminGetUserSharedCampaigns"
        admin_appsync_event["arguments"] = {}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_get_user_shared_campaigns_non_admin(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test forbidden for non-admin user."""
        non_admin_appsync_event["info"]["fieldName"] = "adminGetUserSharedCampaigns"
        non_admin_appsync_event["arguments"] = {"accountId": "some-user"}

        result = lambda_handler(non_admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

    def test_get_user_shared_campaigns_paginates(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that shared campaign retrieval follows DynamoDB pagination."""
        with patch("src.handlers.admin_operations.query_all_items") as mock_query_all:
            mock_query_all.return_value = [
                {"sharedCampaignCode": f"CODE{i}", "campaignName": f"Campaign {i}"} for i in range(3)
            ]

            admin_appsync_event["info"]["fieldName"] = "adminGetUserSharedCampaigns"
            admin_appsync_event["arguments"] = {"accountId": "paginated-user"}

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert len(result) == 3
            mock_query_all.assert_called_once()
            call_kwargs = mock_query_all.call_args[0][1]
            assert call_kwargs["IndexName"] == "GSI1"

    def test_get_user_shared_campaigns_batch_resolves_catalogs(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Catalogs are pre-resolved via BatchGetItem, not per-item GetItem (#332)."""
        catalog = {"catalogId": "CATALOG#cat-1", "catalogName": "Fall Sale"}
        campaigns = [
            {"sharedCampaignCode": "ABC123", "catalogId": "CATALOG#cat-1"},
            {"sharedCampaignCode": "DEF456", "catalogId": "CATALOG#missing"},
        ]

        with (
            patch("src.handlers.admin_operations.query_all_items", return_value=campaigns),
            patch("src.utils.dynamodb.get_dynamodb_resource") as mock_resource,
            patch("src.handlers.admin_operations.tables") as mock_tables,
        ):
            mock_resource.return_value.batch_get_item.return_value = {
                "Responses": {"kernelworx-catalogs-ue1-dev": [catalog]},
                "UnprocessedKeys": {},
            }

            admin_appsync_event["info"]["fieldName"] = "adminGetUserSharedCampaigns"
            admin_appsync_event["arguments"] = {"accountId": "batch-catalog-user"}

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert result[0]["catalog"] == catalog
            assert result[1]["catalog"] is None
            mock_resource.return_value.batch_get_item.assert_called_once()
            # The per-item field-resolver read must not run for the catalog.
            mock_tables.catalogs.get_item.assert_not_called()

    def test_get_user_shared_campaigns_chunks_batch_get_item(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """A page with >100 distinct catalogs is chunked into 100-key BatchGetItem requests."""
        campaigns = [{"sharedCampaignCode": f"CODE{i}", "catalogId": f"CATALOG#{i}"} for i in range(150)]

        with (
            patch("src.handlers.admin_operations.query_all_items", return_value=campaigns),
            patch("src.utils.dynamodb.get_dynamodb_resource") as mock_resource,
        ):
            mock_resource.return_value.batch_get_item.return_value = {
                "Responses": {"kernelworx-catalogs-ue1-dev": []},
                "UnprocessedKeys": {},
            }

            admin_appsync_event["info"]["fieldName"] = "adminGetUserSharedCampaigns"
            admin_appsync_event["arguments"] = {"accountId": "big-batch-user"}

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert len(result) == 150
            assert mock_resource.return_value.batch_get_item.call_count == 2
            first_keys = mock_resource.return_value.batch_get_item.call_args_list[0][1]["RequestItems"][
                "kernelworx-catalogs-ue1-dev"
            ]["Keys"]
            second_keys = mock_resource.return_value.batch_get_item.call_args_list[1][1]["RequestItems"][
                "kernelworx-catalogs-ue1-dev"
            ]["Keys"]
            assert len(first_keys) == 100
            assert len(second_keys) == 50


class TestBatchGetCampaignCatalogs:
    """Tests for the #332 admin-side catalog batching helpers."""

    def test_extract_unique_catalog_ids_preserves_first_seen_order(self) -> None:
        campaigns = [
            {"campaignId": "C1", "catalogId": "CATALOG#a"},
            {"campaignId": "C2", "catalogId": "CATALOG#b"},
            {"campaignId": "C3", "catalogId": "CATALOG#a"},
            {"campaignId": "C4"},
            {"campaignId": "C5", "catalogId": "CATALOG#c"},
        ]
        assert _extract_unique_catalog_ids(campaigns) == ["CATALOG#a", "CATALOG#b", "CATALOG#c"]

    def test_attaches_catalogs_and_maps_missing_to_none(self, dynamodb_table: Any, catalogs_table: Any) -> None:
        catalogs_table.put_item(Item={"catalogId": "CATALOG#a", "catalogName": "Catalog A"})
        campaigns = [
            {"campaignId": "C1", "catalogId": "CATALOG#a"},
            {"campaignId": "C2", "catalogId": "CATALOG#missing"},
            {"campaignId": "C3", "catalogId": ""},
            {"campaignId": "C4"},
        ]

        _batch_get_campaign_catalogs(campaigns, treat_deleted_as_null=False, logger=MagicMock())

        assert campaigns[0]["catalog"] == {"catalogId": "CATALOG#a", "catalogName": "Catalog A"}
        assert campaigns[1]["catalog"] is None
        assert "catalog" not in campaigns[2]
        assert "catalog" not in campaigns[3]

    def test_campaign_without_catalog_id_left_untouched(self, dynamodb_table: Any) -> None:
        campaigns = [{"campaignId": "C1"}]

        _batch_get_campaign_catalogs(campaigns, treat_deleted_as_null=False, logger=MagicMock())

        assert "catalog" not in campaigns[0]

    def test_soft_deleted_contract_matches_field_resolvers(self, dynamodb_table: Any, catalogs_table: Any) -> None:
        """Campaign keeps the raw soft-deleted item; SharedCampaign maps it to None."""
        catalogs_table.put_item(Item={"catalogId": "CATALOG#deleted", "catalogName": "Old", "isDeleted": True})
        campaign = [{"campaignId": "C1", "catalogId": "CATALOG#deleted"}]
        shared = [{"sharedCampaignCode": "S1", "catalogId": "CATALOG#deleted"}]

        _batch_get_campaign_catalogs(campaign, treat_deleted_as_null=False, logger=MagicMock())
        _batch_get_campaign_catalogs(shared, treat_deleted_as_null=True, logger=MagicMock())

        assert campaign[0]["catalog"]["isDeleted"] is True
        assert shared[0]["catalog"] is None

    def test_no_catalog_ids_skips_dynamodb_call(self, dynamodb_table: Any) -> None:
        with patch("src.utils.dynamodb.get_dynamodb_resource") as mock_resource:
            _batch_get_campaign_catalogs([{"campaignId": "C1"}], treat_deleted_as_null=False, logger=MagicMock())
            mock_resource.return_value.batch_get_item.assert_not_called()

    def test_unprocessed_keys_are_retried(self, dynamodb_table: Any, catalogs_table: Any) -> None:
        catalogs_table.put_item(Item={"catalogId": "CATALOG#a", "catalogName": "Catalog A"})
        campaigns = [{"campaignId": "C1", "catalogId": "CATALOG#a"}]

        with patch("src.utils.dynamodb.get_dynamodb_resource") as mock_resource:
            mock_resource.return_value.batch_get_item.side_effect = [
                {
                    "Responses": {},
                    "UnprocessedKeys": {"kernelworx-catalogs-ue1-dev": {"Keys": [{"catalogId": "CATALOG#a"}]}},
                },
                {
                    "Responses": {
                        "kernelworx-catalogs-ue1-dev": [{"catalogId": "CATALOG#a", "catalogName": "Catalog A"}]
                    },
                    "UnprocessedKeys": {},
                },
            ]

            _batch_get_campaign_catalogs(campaigns, treat_deleted_as_null=False, logger=MagicMock())

            assert mock_resource.return_value.batch_get_item.call_count == 2
            assert campaigns[0]["catalog"]["catalogName"] == "Catalog A"

    def test_unprocessed_after_retries_raises(self, dynamodb_table: Any) -> None:
        """A persistent throttle is retryable: the shared helper raises RESOURCE_BUSY (#557)."""
        campaigns = [{"campaignId": "C1", "catalogId": "CATALOG#stuck"}]

        with (
            patch("src.utils.dynamodb.get_dynamodb_resource") as mock_resource,
            patch("time.sleep"),
        ):
            mock_resource.return_value.batch_get_item.return_value = {
                "Responses": {},
                "UnprocessedKeys": {"kernelworx-catalogs-ue1-dev": {"Keys": [{"catalogId": "CATALOG#stuck"}]}},
            }

            with pytest.raises(AppError) as exc_info:
                _batch_get_campaign_catalogs(campaigns, treat_deleted_as_null=False, logger=MagicMock())

            assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY

    def test_throttling_raises_retryable_resource_busy(self, dynamodb_table: Any) -> None:
        campaigns = [{"campaignId": "C1", "catalogId": "CATALOG#a"}]
        throttling = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "throttled"}},
            "BatchGetItem",
        )

        with patch("src.utils.dynamodb.get_dynamodb_resource") as mock_resource:
            mock_resource.return_value.batch_get_item.side_effect = throttling

            with pytest.raises(AppError) as exc_info:
                _batch_get_campaign_catalogs(campaigns, treat_deleted_as_null=False, logger=MagicMock())

            assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY


class TestAdminGetProfileShares:
    """Tests for admin_get_profile_shares function."""

    def test_get_profile_shares_success(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        shares_table: Any,
    ) -> None:
        """Test successful share retrieval."""
        profile_id = "PROFILE#shared-profile"
        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": "ACCOUNT#user-1",
                "permissions": {"READ"},
            }
        )
        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": "ACCOUNT#user-2",
                "permissions": {"READ", "WRITE"},
            }
        )

        admin_appsync_event["info"]["fieldName"] = "adminGetProfileShares"
        admin_appsync_event["arguments"] = {"profileId": "shared-profile"}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert isinstance(result, list)
        assert len(result) == 2

    def test_get_profile_shares_with_prefix(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        shares_table: Any,
    ) -> None:
        """Test with PROFILE# prefix."""
        profile_id = "PROFILE#prefixed"
        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": "ACCOUNT#user-1",
                "permissions": {"READ"},
            }
        )

        admin_appsync_event["info"]["fieldName"] = "adminGetProfileShares"
        admin_appsync_event["arguments"] = {"profileId": profile_id}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert len(result) == 1

    def test_get_profile_shares_empty(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test empty list for profile with no shares."""
        admin_appsync_event["info"]["fieldName"] = "adminGetProfileShares"
        admin_appsync_event["arguments"] = {"profileId": "no-shares-profile"}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result == []

    def test_get_profile_shares_missing_profile_id(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test error when profileId is missing."""
        admin_appsync_event["info"]["fieldName"] = "adminGetProfileShares"
        admin_appsync_event["arguments"] = {}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_get_profile_shares_permissions_set_conversion(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that permissions set is converted to list for JSON serialization."""
        admin_appsync_event["info"]["fieldName"] = "adminGetProfileShares"
        admin_appsync_event["arguments"] = {"profileId": "test-profile"}

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            # Return shares where permissions is a Python set
            mock_tables.shares.query.return_value = {
                "Items": [
                    {
                        "profileId": "PROFILE#test-profile",
                        "targetAccountId": "ACCOUNT#user-1",
                        "permissions": {"READ", "WRITE"},  # Python set, not list
                    }
                ]
            }

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert len(result) == 1
            # Permissions should be converted to a list
            assert isinstance(result[0]["permissions"], list)
            assert set(result[0]["permissions"]) == {"READ", "WRITE"}

    def test_get_profile_shares_permissions_already_list(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that permissions already as list is not modified (branch coverage)."""
        admin_appsync_event["info"]["fieldName"] = "adminGetProfileShares"
        admin_appsync_event["arguments"] = {"profileId": "test-profile"}

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            # Return shares where permissions is already a list (not a set)
            mock_tables.shares.query.return_value = {
                "Items": [
                    {
                        "profileId": "PROFILE#test-profile",
                        "targetAccountId": "ACCOUNT#user-1",
                        "permissions": ["READ", "WRITE"],  # Already a list
                    }
                ]
            }

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert len(result) == 1
            # Permissions should still be a list
            assert isinstance(result[0]["permissions"], list)
            assert result[0]["permissions"] == ["READ", "WRITE"]

    def test_get_profile_shares_non_admin(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test forbidden for non-admin user."""
        non_admin_appsync_event["info"]["fieldName"] = "adminGetProfileShares"
        non_admin_appsync_event["arguments"] = {"profileId": "some-profile"}

        result = lambda_handler(non_admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN

    def test_get_profile_shares_paginates(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test that share retrieval follows DynamoDB pagination."""
        with patch("src.handlers.admin_operations.query_all_items") as mock_query_all:
            mock_query_all.return_value = [
                {
                    "profileId": "PROFILE#test",
                    "targetAccountId": f"ACCOUNT#user-{i}",
                    "permissions": ["READ"],
                }
                for i in range(3)
            ]

            admin_appsync_event["info"]["fieldName"] = "adminGetProfileShares"
            admin_appsync_event["arguments"] = {"profileId": "test"}

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert len(result) == 3
            mock_query_all.assert_called_once()


class TestAdminDeleteShare:
    """Tests for admin_delete_share function."""

    def test_delete_share_success(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        shares_table: Any,
    ) -> None:
        """Test successful share deletion."""
        profile_id = "PROFILE#del-share"
        target_id = "ACCOUNT#target"
        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": target_id,
                "permissions": {"READ"},
            }
        )

        admin_appsync_event["info"]["fieldName"] = "adminDeleteShare"
        admin_appsync_event["arguments"] = {
            "profileId": "del-share",
            "targetAccountId": "target",
        }

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result is True

        # Verify deletion
        response = shares_table.get_item(Key={"profileId": profile_id, "targetAccountId": target_id})
        assert "Item" not in response

    def test_delete_share_with_prefixes(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        shares_table: Any,
    ) -> None:
        """Test deletion with prefixes already included."""
        profile_id = "PROFILE#del-share-2"
        target_id = "ACCOUNT#target-2"
        shares_table.put_item(
            Item={
                "profileId": profile_id,
                "targetAccountId": target_id,
                "permissions": {"WRITE"},
            }
        )

        admin_appsync_event["info"]["fieldName"] = "adminDeleteShare"
        admin_appsync_event["arguments"] = {
            "profileId": profile_id,
            "targetAccountId": target_id,
        }

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result is True

    def test_delete_share_missing_params(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test error when required params are missing."""
        admin_appsync_event["info"]["fieldName"] = "adminDeleteShare"
        admin_appsync_event["arguments"] = {"profileId": "some-id"}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_delete_share_non_admin(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test forbidden for non-admin user."""
        non_admin_appsync_event["info"]["fieldName"] = "adminDeleteShare"
        non_admin_appsync_event["arguments"] = {
            "profileId": "some",
            "targetAccountId": "user",
        }

        result = lambda_handler(non_admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN


class TestAdminUpdateCampaignSharedCode:
    """Tests for admin_update_campaign_shared_code function."""

    def test_update_campaign_shared_code_success(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        campaigns_table: Any,
    ) -> None:
        """Test successful shared code update."""
        campaigns_table.put_item(
            Item={
                "profileId": "PROFILE#p1",
                "campaignId": "CAMPAIGN#c1",
                "campaignName": "Test Campaign",
            }
        )

        admin_appsync_event["info"]["fieldName"] = "adminUpdateCampaignSharedCode"
        admin_appsync_event["arguments"] = {
            "campaignId": "c1",
            "sharedCampaignCode": "NEWCODE",
        }

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result["sharedCampaignCode"] == "NEWCODE"
        assert "updatedAt" in result
        # The returned object must be the actual stored item, not fabricated.
        assert result["campaignName"] == "Test Campaign"
        assert result["campaignId"] == "CAMPAIGN#c1"
        assert result["profileId"] == "PROFILE#p1"

    def test_update_campaign_shared_code_remove(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        campaigns_table: Any,
    ) -> None:
        """Test removing shared code (set to None)."""
        campaigns_table.put_item(
            Item={
                "profileId": "PROFILE#p2",
                "campaignId": "CAMPAIGN#c2",
                "campaignName": "Test Campaign 2",
                "sharedCampaignCode": "OLDCODE",
            }
        )

        admin_appsync_event["info"]["fieldName"] = "adminUpdateCampaignSharedCode"
        admin_appsync_event["arguments"] = {
            "campaignId": "c2",
            "sharedCampaignCode": None,
        }

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result.get("sharedCampaignCode") is None
        assert "updatedAt" in result
        # The returned object must be the actual stored item, not fabricated.
        assert result["campaignName"] == "Test Campaign 2"
        assert result["campaignId"] == "CAMPAIGN#c2"

    def test_update_campaign_shared_code_with_prefix(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        campaigns_table: Any,
    ) -> None:
        """Test with CAMPAIGN# prefix."""
        campaigns_table.put_item(
            Item={
                "profileId": "PROFILE#p3",
                "campaignId": "CAMPAIGN#c3",
                "campaignName": "Test Campaign 3",
            }
        )

        admin_appsync_event["info"]["fieldName"] = "adminUpdateCampaignSharedCode"
        admin_appsync_event["arguments"] = {
            "campaignId": "CAMPAIGN#c3",
            "sharedCampaignCode": "CODE123",
        }

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result["sharedCampaignCode"] == "CODE123"

    def test_update_campaign_shared_code_not_found(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test error when campaign not found."""
        admin_appsync_event["info"]["fieldName"] = "adminUpdateCampaignSharedCode"
        admin_appsync_event["arguments"] = {
            "campaignId": "nonexistent",
            "sharedCampaignCode": "CODE",
        }

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND

    def test_update_campaign_shared_code_missing_campaign_id(
        self,
        dynamodb_table: Any,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test error when campaignId is missing."""
        admin_appsync_event["info"]["fieldName"] = "adminUpdateCampaignSharedCode"
        admin_appsync_event["arguments"] = {"sharedCampaignCode": "CODE"}

        result = lambda_handler(admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_update_campaign_shared_code_non_admin(
        self,
        dynamodb_table: Any,
        non_admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test forbidden for non-admin user."""
        non_admin_appsync_event["info"]["fieldName"] = "adminUpdateCampaignSharedCode"
        non_admin_appsync_event["arguments"] = {
            "campaignId": "c1",
            "sharedCampaignCode": "CODE",
        }

        result = lambda_handler(non_admin_appsync_event, lambda_context)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.FORBIDDEN


class TestAdminOperationExceptionHandlers:
    """Tests for exception handler paths in admin operations."""

    def test_get_user_profiles_unexpected_error(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test exception handler in admin_get_user_profiles."""
        admin_appsync_event["info"]["fieldName"] = "adminGetUserProfiles"
        admin_appsync_event["arguments"] = {"accountId": "test-user"}

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.profiles.query.side_effect = RuntimeError("Unexpected failure")

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
            assert "Failed to get user profiles" in result["message"]

    def test_get_user_catalogs_unexpected_error(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test exception handler in admin_get_user_catalogs."""
        admin_appsync_event["info"]["fieldName"] = "adminGetUserCatalogs"
        admin_appsync_event["arguments"] = {"accountId": "test-user"}

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.catalogs.query.side_effect = RuntimeError("Unexpected failure")

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
            assert "Failed to get user catalogs" in result["message"]

    def test_get_user_campaigns_unexpected_error(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test exception handler in admin_get_user_campaigns."""
        admin_appsync_event["info"]["fieldName"] = "adminGetUserCampaigns"
        admin_appsync_event["arguments"] = {"accountId": "test-user"}

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.profiles.query.side_effect = RuntimeError("Unexpected failure")

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
            assert "Failed to get user campaigns" in result["message"]

    def test_get_user_shared_campaigns_unexpected_error(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test exception handler in admin_get_user_shared_campaigns."""
        admin_appsync_event["info"]["fieldName"] = "adminGetUserSharedCampaigns"
        admin_appsync_event["arguments"] = {"accountId": "test-user"}

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.shared_campaigns.query.side_effect = RuntimeError("Unexpected failure")

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
            assert "Failed to get user shared campaigns" in result["message"]

    def test_get_profile_shares_unexpected_error(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test exception handler in admin_get_profile_shares."""
        admin_appsync_event["info"]["fieldName"] = "adminGetProfileShares"
        admin_appsync_event["arguments"] = {"profileId": "test-profile"}

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.shares.query.side_effect = RuntimeError("Unexpected failure")

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
            assert "Failed to get profile shares" in result["message"]

    def test_delete_share_unexpected_error(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test exception handler in admin_delete_share."""
        admin_appsync_event["info"]["fieldName"] = "adminDeleteShare"
        admin_appsync_event["arguments"] = {
            "profileId": "test-profile",
            "targetAccountId": "target-user",
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.shares.delete_item.side_effect = RuntimeError("Unexpected failure")

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
            assert "Failed to delete share" in result["message"]

    def test_update_campaign_shared_code_unexpected_error(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
    ) -> None:
        """Test exception handler in admin_update_campaign_shared_code."""
        admin_appsync_event["info"]["fieldName"] = "adminUpdateCampaignSharedCode"
        admin_appsync_event["arguments"] = {
            "campaignId": "test-campaign",
            "sharedCampaignCode": "CODE123",
        }

        with patch("src.handlers.admin_operations.tables") as mock_tables:
            mock_tables.campaigns.query.side_effect = RuntimeError("Unexpected failure")

            result = lambda_handler(admin_appsync_event, lambda_context)

            assert result["__isError"] is True
            assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
            assert "Failed to update campaign shared code" in result["message"]

    def test_search_user_account_without_name(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test admin_search_user when DynamoDB account has no name fields (branch coverage)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "noname"},
        }

        mock_cognito_user = {
            "Username": "noname@example.com",
            "Attributes": [
                {"Name": "sub", "Value": "noname-sub"},
                {"Name": "email", "Value": "noname@example.com"},
            ],
            "Enabled": True,
            "UserStatus": "CONFIRMED",
            "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # DynamoDB scan returns account
            mock_tables.accounts.scan.return_value = {
                "Items": [{"accountId": "ACCOUNT#noname-sub", "email": "noname@example.com"}]
            }

            # Cognito finds user
            mock_client.list_users.return_value = {"Users": [mock_cognito_user]}

            # Account exists but has no name, so displayName should be None
            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {"noname@example.com": []}

            result = admin_search_user(event, lambda_context)

            assert len(result) == 1
            # displayName should be None when no name fields exist
            assert result[0]["displayName"] is None

    def test_search_user_build_admin_user_get_item_fails(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test admin_search_user handles ClientError from DynamoDB get_item (branch coverage 450-451)."""

        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "getfail"},
        }

        mock_cognito_user = {
            "Username": "getfail@example.com",
            "Attributes": [
                {"Name": "sub", "Value": "getfail-sub"},
                {"Name": "email", "Value": "getfail@example.com"},
            ],
            "Enabled": True,
            "UserStatus": "CONFIRMED",
            "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # DynamoDB scan returns account
            mock_tables.accounts.scan.return_value = {
                "Items": [{"accountId": "ACCOUNT#getfail-sub", "email": "getfail@example.com"}]
            }

            # Cognito finds user
            mock_client.list_users.return_value = {"Users": [mock_cognito_user]}

            # Batched display-name lookup fails gracefully and returns empty map
            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {"getfail@example.com": []}

            result = admin_search_user(event, lambda_context)

            # Should still return user, but without displayName
            assert len(result) == 1
            assert result[0]["displayName"] is None
            assert result[0]["email"] == "getfail@example.com"

    def test_search_user_cognito_sub_search_fails(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test _search_user_by_sub handles ClientError gracefully."""
        from botocore.exceptions import ClientError

        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "test"},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                # DynamoDB returns account with sub
                mock_tables.accounts.scan.return_value = {
                    "Items": [{"accountId": "ACCOUNT#test-sub-123", "email": "test@example.com"}]
                }

                # Cognito sub search fails with ClientError
                mock_client.list_users.side_effect = ClientError(
                    {"Error": {"Code": "InternalErrorException", "Message": "Service error"}},
                    "ListUsers",
                )

                # Should return empty list since sub search fails
                result = admin_search_user(event, lambda_context)
                assert result == []

    def test_search_user_cognito_email_prefix_search_fails(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test _search_users_in_cognito_by_email_prefix handles ClientError gracefully."""
        from botocore.exceptions import ClientError

        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "test"},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                # DynamoDB returns no accounts
                mock_tables.accounts.scan.return_value = {"Items": []}

                # Cognito email prefix search fails with ClientError
                mock_client.list_users.side_effect = ClientError(
                    {"Error": {"Code": "InternalErrorException", "Message": "Service error"}},
                    "ListUsers",
                )

                # Should return empty list since cognito search fails
                result = admin_search_user(event, lambda_context)
                assert result == []

    def test_search_user_dynamodb_items_not_matching(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test DynamoDB scan filters out non-matching items (branch 351->343)."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "findme"},
        }

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # DynamoDB returns items where only some match
            mock_tables.accounts.scan.return_value = {
                "Items": [
                    {"accountId": "ACCOUNT#no-match-1", "email": "other@example.com"},  # No match
                    {"accountId": "ACCOUNT#match", "email": "findme@example.com"},  # Match
                    {"accountId": "ACCOUNT#no-match-2", "email": "different@example.com"},  # No match
                ]
            }

            mock_cognito_user = {
                "Username": "findme@example.com",
                "Attributes": [
                    {"Name": "sub", "Value": "match"},
                    {"Name": "email", "Value": "findme@example.com"},
                ],
                "Enabled": True,
                "UserStatus": "CONFIRMED",
                "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
            }

            # Cognito finds only the matching user
            mock_client.list_users.return_value = {"Users": [mock_cognito_user]}

            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {"findme@example.com": []}

            result = admin_search_user(event, lambda_context)

            # Should only have 1 result (the one that matches)
            assert len(result) == 1
            assert result[0]["email"] == "findme@example.com"

    def test_search_user_dynamodb_scan_client_error(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test _search_accounts_in_dynamodb handles ClientError gracefully."""
        from botocore.exceptions import ClientError

        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "test"},
        }

        with patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client:
            with patch("src.handlers.admin_operations.tables") as mock_tables:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                # DynamoDB scan fails with ClientError
                mock_tables.accounts.scan.side_effect = ClientError(
                    {"Error": {"Code": "InternalErrorException", "Message": "Service error"}},
                    "Scan",
                )

                # Cognito returns empty
                mock_client.list_users.return_value = {"Users": []}

                # Should return empty list since DynamoDB search fails but cognito still works
                result = admin_search_user(event, lambda_context)
                assert result == []

    def test_search_user_max_scan_limit_reached(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test DynamoDB scan stops at max_scan limit."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "test"},
        }

        # Create 1001 items to exceed max_scan of 1000
        large_items_batch = [{"accountId": f"ACCOUNT#sub-{i}", "email": f"test{i}@example.com"} for i in range(1001)]

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # DynamoDB returns all items in one batch (simulating reaching limit)
            mock_tables.accounts.scan.return_value = {
                "Items": large_items_batch,
                "LastEvaluatedKey": {"accountId": "ACCOUNT#sub-1000"},  # More pages exist
            }

            # Return cognito user for each DynamoDB account
            mock_cognito_user = {
                "Username": "test@example.com",
                "Attributes": [
                    {"Name": "sub", "Value": "test-sub"},
                    {"Name": "email", "Value": "test@example.com"},
                ],
                "Enabled": True,
                "UserStatus": "CONFIRMED",
                "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
            }
            mock_client.list_users.return_value = {"Users": [mock_cognito_user]}

            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {"test@example.com": []}

            admin_search_user(event, lambda_context)

            # Should stop after first batch since scanned_count (1001) >= max_scan (1000)
            assert mock_tables.accounts.scan.call_count == 1

    def test_search_user_max_results_reached_early(
        self,
        admin_appsync_event: Dict[str, Any],
        lambda_context: Any,
        monkeypatch: Any,
    ) -> None:
        """Test DynamoDB scan stops when max_results (50) is reached."""
        monkeypatch.setenv("USER_POOL_ID", "test-pool-id")

        event = {
            **admin_appsync_event,
            "info": {"fieldName": "adminSearchUser"},
            "arguments": {"query": "match"},
        }

        # Create items that all match the query
        matching_items = [
            {"accountId": f"ACCOUNT#sub-{i}", "email": f"match{i}@example.com"}
            for i in range(60)  # More than max_results of 50
        ]

        with (
            patch("src.handlers.admin_operations.get_cognito_client") as mock_get_client,
            patch("src.handlers.admin_operations.tables") as mock_tables,
            patch("src.handlers.admin_operations._batch_get_display_names") as mock_batch_names,
            patch("src.handlers.admin_operations._batch_get_user_groups") as mock_batch_groups,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # DynamoDB returns all items
            mock_tables.accounts.scan.return_value = {
                "Items": matching_items,
                "LastEvaluatedKey": {"accountId": "ACCOUNT#sub-59"},
            }

            def mock_list_users(*args: Any, **kwargs: Any) -> Dict[str, Any]:
                filter_str = kwargs.get("Filter", "")
                if "sub" in filter_str:
                    # Extract sub value from filter
                    import re

                    match = re.search(r'sub = "([^"]+)"', filter_str)
                    if match:
                        sub_val = match.group(1)
                        return {
                            "Users": [
                                {
                                    "Username": f"{sub_val}@example.com",
                                    "Attributes": [
                                        {"Name": "sub", "Value": sub_val},
                                        {"Name": "email", "Value": f"{sub_val}@example.com"},
                                    ],
                                    "Enabled": True,
                                    "UserStatus": "CONFIRMED",
                                    "UserCreateDate": datetime(2024, 1, 1, tzinfo=timezone.utc),
                                }
                            ]
                        }
                return {"Users": []}

            mock_client.list_users.side_effect = mock_list_users

            mock_batch_names.return_value = {}
            mock_batch_groups.return_value = {}

            result = admin_search_user(event, lambda_context)

            # Should have 50 results (max_results limit)
            assert len(result) == 50
