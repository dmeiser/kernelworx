"""Unit tests for list_catalogs_in_use Lambda handler."""

import asyncio
from typing import Any, Dict, List, Set
from unittest.mock import AsyncMock, MagicMock, patch

import boto3
import pytest
from moto import mock_aws


class TestAsyncGetOwnedProfileIds:
    """Tests for _async_get_owned_profile_ids helper."""

    @pytest.mark.asyncio
    async def test_returns_profile_ids_from_owned_profiles(self) -> None:
        """Should return profile IDs from profiles owned by the account."""
        from src.handlers.list_catalogs_in_use import _async_get_owned_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"profileId": "PROFILE#prof1"},
                {"profileId": "PROFILE#prof2"},
            ]
        }

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_owned_profile_ids(mock_dynamodb, "profiles-table", "ACCOUNT#test-user")

        assert result == ["PROFILE#prof1", "PROFILE#prof2"]
        mock_table.query.assert_called_once_with(
            KeyConditionExpression="ownerAccountId = :ownerAccountId",
            ExpressionAttributeValues={":ownerAccountId": "ACCOUNT#test-user"},
            ProjectionExpression="profileId",
        )

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_profiles(self) -> None:
        """Should return empty list when account has no profiles."""
        from src.handlers.list_catalogs_in_use import _async_get_owned_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {"Items": []}

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_owned_profile_ids(mock_dynamodb, "profiles-table", "ACCOUNT#test-user")

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_pagination(self) -> None:
        """Should handle paginated results."""
        from src.handlers.list_catalogs_in_use import _async_get_owned_profile_ids

        mock_table = AsyncMock()
        mock_table.query.side_effect = [
            {
                "Items": [{"profileId": "PROFILE#prof1"}],
                "LastEvaluatedKey": {"pk": "key1"},
            },
            {
                "Items": [{"profileId": "PROFILE#prof2"}],
            },
        ]

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_owned_profile_ids(mock_dynamodb, "profiles-table", "ACCOUNT#test-user")

        assert result == ["PROFILE#prof1", "PROFILE#prof2"]
        assert mock_table.query.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_pagination_with_items_in_continuation(self) -> None:
        """Should collect items from paginated continuation that includes items without profileId."""
        from src.handlers.list_catalogs_in_use import _async_get_owned_profile_ids

        mock_table = AsyncMock()
        mock_table.query.side_effect = [
            {
                "Items": [{"profileId": "PROFILE#prof1"}],
                "LastEvaluatedKey": {"pk": "key1"},
            },
            {
                "Items": [{"profileId": "PROFILE#prof2"}, {}],  # Include item without profileId
            },
        ]

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_owned_profile_ids(mock_dynamodb, "profiles-table", "ACCOUNT#test-user")

        assert result == ["PROFILE#prof1", "PROFILE#prof2"]

    @pytest.mark.asyncio
    async def test_skips_items_without_profile_id(self) -> None:
        """Should skip items that don't have profileId."""
        from src.handlers.list_catalogs_in_use import _async_get_owned_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"profileId": "PROFILE#prof1"},
                {},  # Missing profileId
                {"profileId": None},  # None profileId
            ]
        }

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_owned_profile_ids(mock_dynamodb, "profiles-table", "ACCOUNT#test-user")

        assert result == ["PROFILE#prof1"]


class TestAsyncGetSharedProfileIds:
    """Tests for _async_get_shared_profile_ids helper."""

    @pytest.mark.asyncio
    async def test_returns_profile_ids_from_shares(self) -> None:
        """Should return profile IDs shared with the account."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"profileId": "PROFILE#prof1", "permissions": ["READ"]},
                {"profileId": "PROFILE#prof2", "permissions": ["WRITE"]},
            ]
        }

        # Legacy shares without ownerAccountId are accepted when the profile
        # still exists via the GSI; the existence check returns the profiles.
        mock_profiles_table = AsyncMock()
        mock_profiles_table.query.return_value = {"Items": [{"profileId": "PROFILE#prof1"}]}

        mock_dynamodb = AsyncMock()

        async def mock_table_by_name(table_name: str) -> AsyncMock:
            if "profiles" in table_name:
                return mock_profiles_table
            return mock_table

        mock_dynamodb.Table = mock_table_by_name

        result = await _async_get_shared_profile_ids(
            mock_dynamodb, "shares-table", "ACCOUNT#test-user", "profiles-table"
        )

        assert result == ["PROFILE#prof1", "PROFILE#prof2"]
        # No ProjectionExpression: the whole item (including ownerAccountId)
        # is returned from the ALL-projected GSI.
        assert mock_table.query.await_args_list[0].kwargs == {
            "IndexName": "targetAccountId-index",
            "KeyConditionExpression": "targetAccountId = :targetAccountId",
            "ExpressionAttributeValues": {":targetAccountId": "ACCOUNT#test-user"},
        }

    @pytest.mark.asyncio
    async def test_returns_profile_ids_from_shares_with_valid_owner(self) -> None:
        """Shares whose recorded owner still owns the profile keep working."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"profileId": "PROFILE#prof1", "permissions": ["READ"], "ownerAccountId": "ACCOUNT#owner1"},
                {"profileId": "PROFILE#prof2", "permissions": ["WRITE"], "ownerAccountId": "ACCOUNT#owner2"},
            ]
        }

        mock_profiles_table = AsyncMock()
        mock_profiles_table.get_item.return_value = {"Item": {}}

        mock_dynamodb = AsyncMock()

        async def mock_table_by_name(table_name: str) -> AsyncMock:
            if "profiles" in table_name:
                return mock_profiles_table
            return mock_table

        mock_dynamodb.Table = mock_table_by_name

        result = await _async_get_shared_profile_ids(
            mock_dynamodb, "shares-table", "ACCOUNT#test-user", "profiles-table"
        )

        assert result == ["PROFILE#prof1", "PROFILE#prof2"]
        # Strongly consistent re-read under each share's recorded owner (#432).
        assert mock_profiles_table.get_item.await_count == 2
        mock_profiles_table.get_item.assert_any_call(
            Key={"ownerAccountId": "ACCOUNT#owner1", "profileId": "PROFILE#prof1"}, ConsistentRead=True
        )
        mock_profiles_table.get_item.assert_any_call(
            Key={"ownerAccountId": "ACCOUNT#owner2", "profileId": "PROFILE#prof2"}, ConsistentRead=True
        )

    @pytest.mark.asyncio
    async def test_excludes_stale_shares_after_ownership_transfer(self) -> None:
        """A share stamped by a previous owner must not grant access (#432, #530).

        After ``transfer_profile_ownership`` the old owner's base-table record is
        deleted and the share repair is best-effort, so a stale share keeps its
        old ``ownerAccountId``. The strongly consistent read under that recorded
        owner comes back empty and the share is dropped instead of surfacing the
        profile's catalog IDs to the ex-collaborator.
        """
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"profileId": "PROFILE#stale", "permissions": ["READ"], "ownerAccountId": "ACCOUNT#old-owner"},
                {"profileId": "PROFILE#valid", "permissions": ["WRITE"], "ownerAccountId": "ACCOUNT#current-owner"},
            ]
        }

        mock_profiles_table = AsyncMock()

        async def mock_get_item(Key: Dict[str, str], ConsistentRead: bool = False) -> Dict[str, Any]:
            # The stale share's recorded owner no longer owns the profile.
            if Key["ownerAccountId"] == "ACCOUNT#old-owner":
                return {}
            return {"Item": {"profileId": Key["profileId"]}}

        mock_profiles_table.get_item.side_effect = mock_get_item

        mock_dynamodb = AsyncMock()

        async def mock_table_by_name(table_name: str) -> AsyncMock:
            if "profiles" in table_name:
                return mock_profiles_table
            return mock_table

        mock_dynamodb.Table = mock_table_by_name

        result = await _async_get_shared_profile_ids(
            mock_dynamodb, "shares-table", "ACCOUNT#test-user", "profiles-table"
        )

        assert result == ["PROFILE#valid"]

    @pytest.mark.asyncio
    async def test_accepts_legacy_share_without_owner_when_profile_exists(self) -> None:
        """Shares missing ownerAccountId are accepted only if the profile still exists."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {"Items": [{"profileId": "PROFILE#legacy", "permissions": ["READ"]}]}

        mock_profiles_table = AsyncMock()
        mock_profiles_table.query.return_value = {"Items": [{"profileId": "PROFILE#legacy"}]}

        mock_dynamodb = AsyncMock()

        async def mock_table_by_name(table_name: str) -> AsyncMock:
            if "profiles" in table_name:
                return mock_profiles_table
            return mock_table

        mock_dynamodb.Table = mock_table_by_name

        result = await _async_get_shared_profile_ids(
            mock_dynamodb, "shares-table", "ACCOUNT#test-user", "profiles-table"
        )

        assert result == ["PROFILE#legacy"]

    @pytest.mark.asyncio
    async def test_drops_legacy_share_without_owner_when_profile_gone(self) -> None:
        """A share without ownerAccountId whose profile no longer exists is dropped."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {"Items": [{"profileId": "PROFILE#legacy", "permissions": ["READ"]}]}

        mock_profiles_table = AsyncMock()
        mock_profiles_table.query.return_value = {"Items": []}

        mock_dynamodb = AsyncMock()

        async def mock_table_by_name(table_name: str) -> AsyncMock:
            if "profiles" in table_name:
                return mock_profiles_table
            return mock_table

        mock_dynamodb.Table = mock_table_by_name

        result = await _async_get_shared_profile_ids(
            mock_dynamodb, "shares-table", "ACCOUNT#test-user", "profiles-table"
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_query_is_accepted_by_dynamodb_expression_validation(self) -> None:
        """The emitted query must pass DynamoDB's reserved-keyword validation.

        Regression test for the ephemeral integration failure where every
        listCatalogsInUse call returned INTERNAL_ERROR ("Failed to list
        catalogs in use"): "permissions" is a DynamoDB reserved word, so a
        ProjectionExpression containing it bare is rejected with a
        ValidationException. moto enforces the same expression validation
        as the real service; before the fix this test fails with
        "reserved keyword: permissions" and passes after it.
        """
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {"Items": []}
        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        await _async_get_shared_profile_ids(mock_dynamodb, "shares-table", "ACCOUNT#test-user", "profiles-table")
        query_kwargs = mock_table.query.call_args.kwargs

        with mock_aws():
            dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
            dynamodb.create_table(
                TableName="shares-table",
                KeySchema=[
                    {"AttributeName": "profileId", "KeyType": "HASH"},
                    {"AttributeName": "targetAccountId", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "profileId", "AttributeType": "S"},
                    {"AttributeName": "targetAccountId", "AttributeType": "S"},
                ],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": "targetAccountId-index",
                        "KeySchema": [{"AttributeName": "targetAccountId", "KeyType": "HASH"}],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            real_table = dynamodb.Table("shares-table")
            real_table.put_item(
                Item={"profileId": "PROFILE#prof1", "targetAccountId": "ACCOUNT#test-user", "permissions": ["READ"]}
            )
            response = real_table.query(**query_kwargs)

        # No projection: the query returns the whole item, including the base
        # table's range key (targetAccountId) alongside the attributes read.
        assert response["Items"] == [
            {
                "profileId": "PROFILE#prof1",
                "targetAccountId": "ACCOUNT#test-user",
                "permissions": ["READ"],
            }
        ]

    @pytest.mark.asyncio
    async def test_query_returns_owner_account_id_the_stale_share_check_needs(self) -> None:
        """The emitted query must return ownerAccountId, which the stale-share check reads."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {"Items": []}
        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        await _async_get_shared_profile_ids(mock_dynamodb, "shares-table", "ACCOUNT#test-user", "profiles-table")
        query_kwargs = mock_table.query.call_args.kwargs

        with mock_aws():
            dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
            dynamodb.create_table(
                TableName="shares-table",
                KeySchema=[
                    {"AttributeName": "profileId", "KeyType": "HASH"},
                    {"AttributeName": "targetAccountId", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "profileId", "AttributeType": "S"},
                    {"AttributeName": "targetAccountId", "AttributeType": "S"},
                ],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": "targetAccountId-index",
                        "KeySchema": [{"AttributeName": "targetAccountId", "KeyType": "HASH"}],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            real_table = dynamodb.Table("shares-table")
            real_table.put_item(
                Item={
                    "profileId": "PROFILE#prof1",
                    "targetAccountId": "ACCOUNT#test-user",
                    "permissions": ["READ"],
                    "ownerAccountId": "ACCOUNT#owner1",
                }
            )
            response = real_table.query(**query_kwargs)

        # No projection: the query returns the whole item, including the base
        # table's range key (targetAccountId) alongside the attributes read.
        assert response["Items"] == [
            {
                "profileId": "PROFILE#prof1",
                "targetAccountId": "ACCOUNT#test-user",
                "permissions": ["READ"],
                "ownerAccountId": "ACCOUNT#owner1",
            }
        ]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_shares(self) -> None:
        """Should return empty list when account has no shares."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {"Items": []}

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_shared_profile_ids(
            mock_dynamodb, "shares-table", "ACCOUNT#test-user", "profiles-table"
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_pagination(self) -> None:
        """Should handle paginated results."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.side_effect = [
            {
                "Items": [{"profileId": "PROFILE#prof1", "permissions": ["READ"], "ownerAccountId": "ACCOUNT#owner1"}],
                "LastEvaluatedKey": {"pk": "key1"},
            },
            {
                "Items": [{"profileId": "PROFILE#prof2", "permissions": ["WRITE"], "ownerAccountId": "ACCOUNT#owner2"}],
            },
        ]

        mock_profiles_table = AsyncMock()
        mock_profiles_table.get_item.return_value = {"Item": {}}

        mock_dynamodb = AsyncMock()

        async def mock_table_by_name(table_name: str) -> AsyncMock:
            if "profiles" in table_name:
                return mock_profiles_table
            return mock_table

        mock_dynamodb.Table = mock_table_by_name

        result = await _async_get_shared_profile_ids(
            mock_dynamodb, "shares-table", "ACCOUNT#test-user", "profiles-table"
        )

        assert result == ["PROFILE#prof1", "PROFILE#prof2"]
        assert mock_table.query.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_pagination_with_items_in_continuation(self) -> None:
        """Should collect items from paginated continuation including missing profileId."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.side_effect = [
            {
                "Items": [{"profileId": "PROFILE#prof1", "permissions": ["READ"], "ownerAccountId": "ACCOUNT#owner1"}],
                "LastEvaluatedKey": {"pk": "key1"},
            },
            {
                "Items": [
                    {"profileId": "PROFILE#prof2", "permissions": ["WRITE"], "ownerAccountId": "ACCOUNT#owner2"},
                    {},  # Item without profileId
                ],
            },
        ]

        mock_profiles_table = AsyncMock()
        mock_profiles_table.get_item.return_value = {"Item": {}}

        mock_dynamodb = AsyncMock()

        async def mock_table_by_name(table_name: str) -> AsyncMock:
            if "profiles" in table_name:
                return mock_profiles_table
            return mock_table

        mock_dynamodb.Table = mock_table_by_name

        result = await _async_get_shared_profile_ids(
            mock_dynamodb, "shares-table", "ACCOUNT#test-user", "profiles-table"
        )

        assert result == ["PROFILE#prof1", "PROFILE#prof2"]

    @pytest.mark.asyncio
    async def test_skips_items_without_profile_id(self) -> None:
        """Should skip items that don't have profileId."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"profileId": "PROFILE#prof1", "permissions": ["READ"], "ownerAccountId": "ACCOUNT#owner1"},
                {},  # Missing profileId
            ]
        }

        mock_profiles_table = AsyncMock()
        mock_profiles_table.get_item.return_value = {"Item": {}}

        mock_dynamodb = AsyncMock()

        async def mock_table_by_name(table_name: str) -> AsyncMock:
            if "profiles" in table_name:
                return mock_profiles_table
            return mock_table

        mock_dynamodb.Table = mock_table_by_name

        result = await _async_get_shared_profile_ids(
            mock_dynamodb, "shares-table", "ACCOUNT#test-user", "profiles-table"
        )

        assert result == ["PROFILE#prof1"]

    @pytest.mark.asyncio
    async def test_filters_shares_with_empty_permissions(self) -> None:
        """Should skip shares with empty permissions array (#242)."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"profileId": "PROFILE#prof1", "permissions": ["READ"], "ownerAccountId": "ACCOUNT#owner1"},
                {"profileId": "PROFILE#prof2", "permissions": [], "ownerAccountId": "ACCOUNT#owner2"},
            ]
        }

        mock_profiles_table = AsyncMock()
        mock_profiles_table.get_item.return_value = {"Item": {}}

        mock_dynamodb = AsyncMock()

        async def mock_table_by_name(table_name: str) -> AsyncMock:
            if "profiles" in table_name:
                return mock_profiles_table
            return mock_table

        mock_dynamodb.Table = mock_table_by_name

        result = await _async_get_shared_profile_ids(
            mock_dynamodb, "shares-table", "ACCOUNT#test-user", "profiles-table"
        )

        assert result == ["PROFILE#prof1"]
        # Only the candidate with READ/WRITE reaches the owner re-read.
        mock_profiles_table.get_item.assert_awaited_once_with(
            Key={"ownerAccountId": "ACCOUNT#owner1", "profileId": "PROFILE#prof1"}, ConsistentRead=True
        )

    @pytest.mark.asyncio
    async def test_filters_shares_with_invalid_permissions(self) -> None:
        """Should skip shares with unsupported permissions (#242)."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"profileId": "PROFILE#prof1", "permissions": ["WRITE"], "ownerAccountId": "ACCOUNT#owner1"},
                {"profileId": "PROFILE#prof2", "permissions": ["ADMIN"], "ownerAccountId": "ACCOUNT#owner2"},
            ]
        }

        mock_profiles_table = AsyncMock()
        mock_profiles_table.get_item.return_value = {"Item": {}}

        mock_dynamodb = AsyncMock()

        async def mock_table_by_name(table_name: str) -> AsyncMock:
            if "profiles" in table_name:
                return mock_profiles_table
            return mock_table

        mock_dynamodb.Table = mock_table_by_name

        result = await _async_get_shared_profile_ids(
            mock_dynamodb, "shares-table", "ACCOUNT#test-user", "profiles-table"
        )

        assert result == ["PROFILE#prof1"]

    @pytest.mark.asyncio
    async def test_filters_shares_with_missing_permissions(self) -> None:
        """Should skip shares missing permissions attribute (#242)."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"profileId": "PROFILE#prof1", "permissions": ["READ"], "ownerAccountId": "ACCOUNT#owner1"},
                {"profileId": "PROFILE#prof2"},
            ]
        }

        mock_profiles_table = AsyncMock()
        mock_profiles_table.get_item.return_value = {"Item": {}}

        mock_dynamodb = AsyncMock()

        async def mock_table_by_name(table_name: str) -> AsyncMock:
            if "profiles" in table_name:
                return mock_profiles_table
            return mock_table

        mock_dynamodb.Table = mock_table_by_name

        result = await _async_get_shared_profile_ids(
            mock_dynamodb, "shares-table", "ACCOUNT#test-user", "profiles-table"
        )

        assert result == ["PROFILE#prof1"]
        # The share without permissions is filtered before the owner re-read.
        mock_profiles_table.get_item.assert_awaited_once_with(
            Key={"ownerAccountId": "ACCOUNT#owner1", "profileId": "PROFILE#prof1"}, ConsistentRead=True
        )


class TestAsyncGetCampaignsForProfile:
    """Tests for _async_get_campaigns_for_profile helper."""

    @pytest.mark.asyncio
    async def test_returns_catalog_ids_from_profile_campaigns(self) -> None:
        """Should return catalog IDs from campaigns for a profile."""
        from src.handlers.list_catalogs_in_use import _async_get_campaigns_for_profile

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"catalogId": "CATALOG#cat1"},
                {"catalogId": "CATALOG#cat2"},
            ]
        }

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_campaigns_for_profile(mock_dynamodb, "campaigns-table", "PROFILE#prof1")

        assert result == {"CATALOG#cat1", "CATALOG#cat2"}
        mock_table.query.assert_called_once_with(
            KeyConditionExpression="profileId = :profileId",
            ExpressionAttributeValues={":profileId": "PROFILE#prof1"},
            ProjectionExpression="catalogId",
        )

    @pytest.mark.asyncio
    async def test_skips_items_without_catalog_id_in_first_page(self) -> None:
        """Should skip items without catalogId in the first page."""
        from src.handlers.list_catalogs_in_use import _async_get_campaigns_for_profile

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"catalogId": "CATALOG#cat1"},
                {},  # Missing catalogId
                {"catalogId": "CATALOG#cat2"},
            ]
        }

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_campaigns_for_profile(mock_dynamodb, "campaigns-table", "PROFILE#prof1")

        assert result == {"CATALOG#cat1", "CATALOG#cat2"}

    @pytest.mark.asyncio
    async def test_handles_pagination(self) -> None:
        """Should handle paginated results."""
        from src.handlers.list_catalogs_in_use import _async_get_campaigns_for_profile

        mock_table = AsyncMock()
        mock_table.query.side_effect = [
            {
                "Items": [{"catalogId": "CATALOG#cat1"}],
                "LastEvaluatedKey": {"pk": "key1"},
            },
            {
                "Items": [{"catalogId": "CATALOG#cat2"}],
            },
        ]

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_campaigns_for_profile(mock_dynamodb, "campaigns-table", "PROFILE#prof1")

        assert result == {"CATALOG#cat1", "CATALOG#cat2"}
        assert mock_table.query.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_pagination_with_items_in_continuation(self) -> None:
        """Should collect items from paginated continuation including missing catalogId."""
        from src.handlers.list_catalogs_in_use import _async_get_campaigns_for_profile

        mock_table = AsyncMock()
        mock_table.query.side_effect = [
            {
                "Items": [{"catalogId": "CATALOG#cat1"}],
                "LastEvaluatedKey": {"pk": "key1"},
            },
            {
                "Items": [{"catalogId": "CATALOG#cat2"}, {}],  # Include item without catalogId
            },
        ]

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_campaigns_for_profile(mock_dynamodb, "campaigns-table", "PROFILE#prof1")

        assert result == {"CATALOG#cat1", "CATALOG#cat2"}

    @pytest.mark.asyncio
    async def test_skips_items_without_catalog_id_in_pagination(self) -> None:
        """Should skip items without catalogId in paginated continuation."""
        from src.handlers.list_catalogs_in_use import _async_get_campaigns_for_profile

        mock_table = AsyncMock()
        mock_table.query.side_effect = [
            {
                "Items": [{"catalogId": "CATALOG#cat1"}],
                "LastEvaluatedKey": {"pk": "key1"},
            },
            {
                "Items": [{"other": "value"}, {"catalogId": None}],  # All items missing/null catalogId
            },
        ]

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_campaigns_for_profile(mock_dynamodb, "campaigns-table", "PROFILE#prof1")

        # Should only have cat1 from first page
        assert result == {"CATALOG#cat1"}


class TestAsyncGetSharedCampaignCatalogIds:
    """Tests for _async_get_shared_campaign_catalog_ids helper."""

    @pytest.mark.asyncio
    async def test_returns_empty_set_for_empty_profile_list(self) -> None:
        """Should return empty set when no profile IDs provided."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_campaign_catalog_ids

        mock_dynamodb = AsyncMock()
        result = await _async_get_shared_campaign_catalog_ids(mock_dynamodb, "campaigns-table", [])

        assert result == set()

    @pytest.mark.asyncio
    async def test_aggregates_catalog_ids_from_multiple_profiles(self) -> None:
        """Should aggregate catalog IDs from all profiles."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_campaign_catalog_ids

        mock_table = AsyncMock()
        # First call returns cat1, cat2; second call returns cat2, cat3
        mock_table.query.side_effect = [
            {"Items": [{"catalogId": "CATALOG#cat1"}, {"catalogId": "CATALOG#cat2"}]},
            {"Items": [{"catalogId": "CATALOG#cat2"}, {"catalogId": "CATALOG#cat3"}]},
        ]

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_shared_campaign_catalog_ids(
            mock_dynamodb, "campaigns-table", ["PROFILE#prof1", "PROFILE#prof2"]
        )

        # Should deduplicate cat2
        assert result == {"CATALOG#cat1", "CATALOG#cat2", "CATALOG#cat3"}

    @pytest.mark.asyncio
    async def test_raises_resource_busy_when_a_profile_query_fails(self) -> None:
        """A single failed per-profile query must not be swallowed (#556).

        Regression test for #556: previously a per-profile DynamoDB failure was
        logged and discarded, so the caller returned the surviving catalogs as
        the authoritative "in use" answer. Now any failure raises a retryable
        RESOURCE_BUSY so the request is retried instead of answered incompletely.
        """
        import botocore.exceptions

        from src.handlers.list_catalogs_in_use import _async_get_shared_campaign_catalog_ids
        from src.utils.errors import AppError, ErrorCode

        call_count = 0

        async def mock_query(**kwargs: object) -> Dict[str, List[Dict[str, str]]]:
            nonlocal call_count
            call_count += 1
            # First profile's query succeeds, second profile's query is throttled
            if call_count == 1:
                return {"Items": [{"catalogId": "CATALOG#cat1"}]}
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "throttled"}},
                "Query",
            )

        mock_table = AsyncMock()
        mock_table.query.side_effect = mock_query

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        with pytest.raises(AppError) as exc_info:
            await _async_get_shared_campaign_catalog_ids(
                mock_dynamodb, "campaigns-table", ["PROFILE#prof1", "PROFILE#prof2"]
            )

        # Refuses the partial answer with the retryable code, preserving the cause
        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY
        assert "retry" in exc_info.value.message.lower()
        assert isinstance(exc_info.value.__cause__, botocore.exceptions.ClientError)

    @pytest.mark.asyncio
    async def test_raises_internal_error_for_unexpected_failure(self) -> None:
        """A non-ClientError failure is permanent, so it is not reported as retryable."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_campaign_catalog_ids
        from src.utils.errors import AppError, ErrorCode

        async def mock_query(**kwargs: object) -> Dict[str, List[Dict[str, str]]]:
            raise RuntimeError("network blip")

        mock_table = AsyncMock()
        mock_table.query.side_effect = mock_query

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        with pytest.raises(AppError) as exc_info:
            await _async_get_shared_campaign_catalog_ids(
                mock_dynamodb, "campaigns-table", ["PROFILE#prof1", "PROFILE#prof2", "PROFILE#prof3"]
            )

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert isinstance(exc_info.value.__cause__, RuntimeError)

    @pytest.mark.asyncio
    async def test_raises_internal_error_for_non_throttling_client_error(self) -> None:
        """A permanent ClientError is not retryable, so it maps to INTERNAL_ERROR."""
        from botocore.exceptions import ClientError

        from src.handlers.list_catalogs_in_use import _async_get_shared_campaign_catalog_ids
        from src.utils.errors import AppError, ErrorCode

        async def mock_query(**kwargs: object) -> Dict[str, List[Dict[str, str]]]:
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
                "Query",
            )

        mock_table = AsyncMock()
        mock_table.query.side_effect = mock_query

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        with pytest.raises(AppError) as exc_info:
            await _async_get_shared_campaign_catalog_ids(
                mock_dynamodb, "campaigns-table", ["PROFILE#prof1", "PROFILE#prof2"]
            )

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert isinstance(exc_info.value.__cause__, ClientError)

    @pytest.mark.asyncio
    async def test_throttling_failure_wins_over_permanent_failure(self) -> None:
        """A throttled profile keeps the whole request retryable."""
        from botocore.exceptions import ClientError

        from src.handlers.list_catalogs_in_use import _async_get_shared_campaign_catalog_ids
        from src.utils.errors import AppError, ErrorCode

        outcomes = [
            ClientError({"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}}, "Query"),
            ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "throttled"}},
                "Query",
            ),
        ]

        async def mock_query(**kwargs: object) -> Dict[str, List[Dict[str, str]]]:
            raise outcomes.pop(0)

        mock_table = AsyncMock()
        mock_table.query.side_effect = mock_query

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        with pytest.raises(AppError) as exc_info:
            await _async_get_shared_campaign_catalog_ids(
                mock_dynamodb, "campaigns-table", ["PROFILE#prof1", "PROFILE#prof2"]
            )

        assert exc_info.value.error_code == ErrorCode.RESOURCE_BUSY
        assert isinstance(exc_info.value.__cause__, ClientError)

    @pytest.mark.asyncio
    async def test_concurrency_is_capped_and_every_profile_is_processed(self) -> None:
        """Peak concurrent queries stay within the cap even past the chunk limit (#541).

        Regression test for #541: the per-profile fan-out used to gather one
        unbounded task per profile, so a caller with more profiles than the
        cap issued that many concurrent DynamoDB queries (multiplied by each
        profile's pagination loop). With more profiles than the chunk cap,
        the peak in-flight query count must never exceed the concurrency cap
        and every profile must still be processed and aggregated.
        """
        from src.handlers import list_catalogs_in_use as module
        from src.handlers.campaign_reporting import _ORDER_QUERY_CONCURRENCY, _PROFILE_BATCH_LIMIT

        profile_count = _PROFILE_BATCH_LIMIT + 25
        cap = _ORDER_QUERY_CONCURRENCY

        in_flight = 0
        peak = 0
        queried_profile_ids: List[str] = []

        async def tracking_query(**kwargs: Any) -> Dict[str, Any]:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            profile_id = kwargs["ExpressionAttributeValues"][":profileId"]
            queried_profile_ids.append(profile_id)
            # Yield long enough that an unbounded fan-out would overlap fully.
            await asyncio.sleep(0.01)
            in_flight -= 1
            return {"Items": [{"catalogId": f"CATALOG#{profile_id}"}]}

        mock_table = AsyncMock()
        mock_table.query.side_effect = tracking_query

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        profile_ids = [f"PROFILE#prof{i}" for i in range(profile_count)]
        result = await module._async_get_shared_campaign_catalog_ids(mock_dynamodb, "campaigns-table", profile_ids)

        # The cap holds even though the profile count exceeds both caps...
        assert peak <= cap
        # ...and no profile was dropped: every one was queried exactly once
        # and its catalog id made it into the aggregated answer.
        assert sorted(queried_profile_ids) == sorted(profile_ids)
        assert mock_table.query.call_count == profile_count
        assert result == {f"CATALOG#{pid}" for pid in profile_ids}


class TestAsyncGetAllCatalogIds:
    """Tests for _async_get_all_catalog_ids orchestrator."""

    @pytest.mark.asyncio
    async def test_runs_owned_and_shared_profiles_in_parallel(self) -> None:
        """Should run owned profiles and shared profiles queries concurrently."""
        import importlib

        import src.handlers.list_catalogs_in_use as module

        # Reload to ensure clean state
        importlib.reload(module)

        mock_profiles_table = AsyncMock()
        mock_profiles_table.query.return_value = {"Items": [{"profileId": "PROFILE#owned1"}]}
        mock_profiles_table.get_item.return_value = {"Item": {}}

        mock_campaigns_table = AsyncMock()
        mock_campaigns_table.query.return_value = {"Items": [{"catalogId": "CATALOG#cat1"}]}

        mock_shares_table = AsyncMock()
        mock_shares_table.query.return_value = {
            "Items": [{"profileId": "PROFILE#shared1", "permissions": ["READ"], "ownerAccountId": "ACCOUNT#owner1"}]
        }

        async def mock_table(table_name: str) -> AsyncMock:
            """Return the appropriate mock table based on name."""
            if "profiles" in table_name:
                return mock_profiles_table
            if "campaigns" in table_name:
                return mock_campaigns_table
            return mock_shares_table

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table = mock_table

        mock_session = MagicMock()
        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__.return_value = mock_dynamodb
        mock_context_manager.__aexit__.return_value = None
        mock_session.resource.return_value = mock_context_manager

        # Patch directly on the module after reload
        original_session = module.aioboto3.Session
        module.aioboto3.Session = MagicMock(return_value=mock_session)
        try:
            owned, shared_profiles, shared_catalogs = await module._async_get_all_catalog_ids("ACCOUNT#test-user")
        finally:
            module.aioboto3.Session = original_session

        assert owned == {"CATALOG#cat1"}
        assert shared_profiles == ["PROFILE#shared1"]
        assert shared_catalogs == {"CATALOG#cat1"}

    @pytest.mark.asyncio
    async def test_excludes_stale_shared_profile_catalogs_after_transfer(self) -> None:
        """Catalogs of a profile left behind by a stale share are not returned (#530).

        The share still exists on the targetAccountId-index GSI with READ and a
        pre-transfer ownerAccountId; the strongly consistent read under that old
        owner is empty, so the profile (and its catalogs) must not be surfaced.
        """
        import importlib

        import src.handlers.list_catalogs_in_use as module

        importlib.reload(module)

        mock_profiles_table = AsyncMock()
        mock_profiles_table.query.return_value = {"Items": []}

        async def mock_get_item(Key: Dict[str, str], ConsistentRead: bool = False) -> Dict[str, Any]:
            return {}

        mock_profiles_table.get_item.side_effect = mock_get_item

        mock_campaigns_table = AsyncMock()
        mock_campaigns_table.query.return_value = {"Items": [{"catalogId": "CATALOG#stale"}]}

        mock_shares_table = AsyncMock()
        mock_shares_table.query.return_value = {
            "Items": [
                {
                    "profileId": "PROFILE#stale",
                    "permissions": ["READ"],
                    "ownerAccountId": "ACCOUNT#old-owner",
                }
            ]
        }

        async def mock_table(table_name: str) -> AsyncMock:
            if "profiles" in table_name:
                return mock_profiles_table
            if "campaigns" in table_name:
                return mock_campaigns_table
            return mock_shares_table

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table = mock_table

        mock_session = MagicMock()
        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__.return_value = mock_dynamodb
        mock_context_manager.__aexit__.return_value = None
        mock_session.resource.return_value = mock_context_manager

        original_session = module.aioboto3.Session
        module.aioboto3.Session = MagicMock(return_value=mock_session)
        try:
            owned, shared_profiles, shared_catalogs = await module._async_get_all_catalog_ids("ACCOUNT#test-user")
        finally:
            module.aioboto3.Session = original_session

        assert owned == set()
        assert shared_profiles == []
        assert shared_catalogs == set()
        # The stale share never reached the campaigns table.
        mock_campaigns_table.query.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_empty_shared_catalogs_when_no_shared_profiles(self) -> None:
        """Should return empty shared catalogs when user has no shared profiles."""
        import importlib
        import os

        import src.handlers.list_catalogs_in_use as module

        # Set environment variables to ensure correct table names
        os.environ["PROFILES_TABLE_NAME"] = "test-profiles"
        os.environ["CAMPAIGNS_TABLE_NAME"] = "test-campaigns"
        os.environ["SHARES_TABLE_NAME"] = "test-shares"

        # Reload to ensure clean state
        importlib.reload(module)

        # Create separate mock tables for each query
        mock_profiles_table = AsyncMock()
        mock_profiles_table.query.return_value = {"Items": [{"profileId": "PROFILE#owned1"}]}

        mock_campaigns_table = AsyncMock()
        mock_campaigns_table.query.return_value = {"Items": [{"catalogId": "CATALOG#cat1"}]}

        mock_shares_table = AsyncMock()
        mock_shares_table.query.return_value = {"Items": []}  # No shares

        async def mock_table(table_name: str) -> AsyncMock:
            """Return the appropriate mock table based on name."""
            if "profiles" in table_name:
                return mock_profiles_table
            if "campaigns" in table_name:
                return mock_campaigns_table
            return mock_shares_table

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table = mock_table

        mock_session = MagicMock()
        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__.return_value = mock_dynamodb
        mock_context_manager.__aexit__.return_value = None
        mock_session.resource.return_value = mock_context_manager

        # Patch directly on the module after reload
        original_session = module.aioboto3.Session
        module.aioboto3.Session = MagicMock(return_value=mock_session)
        try:
            owned, shared_profiles, shared_catalogs = await module._async_get_all_catalog_ids("ACCOUNT#test-user")
        finally:
            module.aioboto3.Session = original_session

        assert owned == {"CATALOG#cat1"}
        assert shared_profiles == []
        assert shared_catalogs == set()


class TestHandler:
    """Tests for the main handler function."""

    def test_returns_all_catalog_ids_sorted(self) -> None:
        """Should return all catalog IDs sorted."""
        from src.handlers.list_catalogs_in_use import handler

        event = {"identity": {"sub": "test-user-id"}}

        async def mock_get_all(account_id: str, request_logger: Any = None) -> tuple[Set[str], List[str], Set[str]]:
            return (
                {"CATALOG#cat2", "CATALOG#cat1"},
                ["PROFILE#prof1"],
                {"CATALOG#cat3", "CATALOG#cat1"},
            )

        with patch(
            "src.handlers.list_catalogs_in_use._async_get_all_catalog_ids",
            side_effect=mock_get_all,
        ):
            result = handler(event, None)

        assert result == ["CATALOG#cat1", "CATALOG#cat2", "CATALOG#cat3"]

    def test_handles_account_id_with_prefix(self) -> None:
        """Should handle account ID that already has ACCOUNT# prefix."""
        from src.handlers.list_catalogs_in_use import handler

        event = {"identity": {"sub": "ACCOUNT#test-user-id"}}

        captured_account_id: List[str] = []

        async def mock_get_all(account_id: str, request_logger: Any = None) -> tuple[Set[str], List[str], Set[str]]:
            captured_account_id.append(account_id)
            return (set(), [], set())

        with patch(
            "src.handlers.list_catalogs_in_use._async_get_all_catalog_ids",
            side_effect=mock_get_all,
        ):
            handler(event, None)

        # Should not double-prefix
        assert captured_account_id[0] == "ACCOUNT#test-user-id"

    def test_returns_empty_list_when_no_catalogs(self) -> None:
        """Should return empty list when user has no campaigns."""
        from src.handlers.list_catalogs_in_use import handler

        event = {"identity": {"sub": "test-user-id"}}

        async def mock_get_all(account_id: str, request_logger: Any = None) -> tuple[Set[str], List[str], Set[str]]:
            return (set(), [], set())

        with patch(
            "src.handlers.list_catalogs_in_use._async_get_all_catalog_ids",
            side_effect=mock_get_all,
        ):
            result = handler(event, None)

        assert result == []

    def test_returns_resource_busy_payload_when_a_profile_query_is_throttled(self) -> None:
        """A throttled per-profile query must reach the caller as a typed RESOURCE_BUSY, not a short list."""
        import os

        from botocore.exceptions import ClientError

        import src.handlers.list_catalogs_in_use as module
        from src.handlers.list_catalogs_in_use import handler
        from src.utils.errors import ErrorCode

        os.environ["PROFILES_TABLE_NAME"] = "test-profiles"
        os.environ["CAMPAIGNS_TABLE_NAME"] = "test-campaigns"
        os.environ["SHARES_TABLE_NAME"] = "test-shares"

        mock_profiles_table = AsyncMock()
        mock_profiles_table.query.return_value = {"Items": [{"profileId": "PROFILE#owned1"}]}
        mock_shares_table = AsyncMock()
        mock_shares_table.query.return_value = {"Items": []}

        async def failing_query(**kwargs: object) -> Dict[str, List[Dict[str, str]]]:
            raise ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "throttled"}},
                "Query",
            )

        mock_campaigns_table = AsyncMock()
        mock_campaigns_table.query.side_effect = failing_query

        async def mock_table(table_name: str) -> AsyncMock:
            if "profiles" in table_name:
                return mock_profiles_table
            if "campaigns" in table_name:
                return mock_campaigns_table
            return mock_shares_table

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table = mock_table

        mock_session = MagicMock()
        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__.return_value = mock_dynamodb
        mock_context_manager.__aexit__.return_value = None
        mock_session.resource.return_value = mock_context_manager

        original_session = module.aioboto3.Session
        module.aioboto3.Session = MagicMock(return_value=mock_session)
        try:
            result = handler({"identity": {"sub": "test-user-id"}}, None)
        finally:
            module.aioboto3.Session = original_session

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.RESOURCE_BUSY
        assert "retry" in result["message"].lower()

    def test_returns_internal_error_payload_when_a_profile_query_is_denied(self) -> None:
        """A permanent per-profile query failure must reach the caller as INTERNAL_ERROR."""
        import os

        from botocore.exceptions import ClientError

        import src.handlers.list_catalogs_in_use as module
        from src.handlers.list_catalogs_in_use import handler
        from src.utils.errors import ErrorCode

        os.environ["PROFILES_TABLE_NAME"] = "test-profiles"
        os.environ["CAMPAIGNS_TABLE_NAME"] = "test-campaigns"
        os.environ["SHARES_TABLE_NAME"] = "test-shares"

        mock_profiles_table = AsyncMock()
        mock_profiles_table.query.return_value = {"Items": [{"profileId": "PROFILE#owned1"}]}
        mock_shares_table = AsyncMock()
        mock_shares_table.query.return_value = {"Items": []}

        async def failing_query(**kwargs: object) -> Dict[str, List[Dict[str, str]]]:
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
                "Query",
            )

        mock_campaigns_table = AsyncMock()
        mock_campaigns_table.query.side_effect = failing_query

        async def mock_table(table_name: str) -> AsyncMock:
            if "profiles" in table_name:
                return mock_profiles_table
            if "campaigns" in table_name:
                return mock_campaigns_table
            return mock_shares_table

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table = mock_table

        mock_session = MagicMock()
        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__.return_value = mock_dynamodb
        mock_context_manager.__aexit__.return_value = None
        mock_session.resource.return_value = mock_context_manager

        original_session = module.aioboto3.Session
        module.aioboto3.Session = MagicMock(return_value=mock_session)
        try:
            result = handler({"identity": {"sub": "test-user-id"}}, None)
        finally:
            module.aioboto3.Session = original_session

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR

    def test_returns_error_payload_on_exception(self) -> None:
        """Should convert unexpected exceptions into an INTERNAL_ERROR payload."""
        from src.handlers.list_catalogs_in_use import handler
        from src.utils.errors import ErrorCode

        event = {"identity": {"sub": "test-user-id"}}

        async def mock_get_all(account_id: str, request_logger: Any = None) -> tuple[Set[str], List[str], Set[str]]:
            raise RuntimeError("Unexpected error")

        with patch(
            "src.handlers.list_catalogs_in_use._async_get_all_catalog_ids",
            side_effect=mock_get_all,
        ):
            result = handler(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INTERNAL_ERROR
        assert "Failed to list catalogs in use" in result["message"]

    def test_converts_app_error_to_payload(self) -> None:
        """Should convert an AppError into an error payload with its code intact."""
        from src.handlers.list_catalogs_in_use import handler
        from src.utils.errors import AppError, ErrorCode

        event = {"identity": {"sub": "test-user-id"}}

        async def mock_get_all(account_id: str, request_logger: Any = None) -> tuple[Set[str], List[str], Set[str]]:
            raise AppError(ErrorCode.NOT_FOUND, "Not found")

        with patch(
            "src.handlers.list_catalogs_in_use._async_get_all_catalog_ids",
            side_effect=mock_get_all,
        ):
            result = handler(event, None)

        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.NOT_FOUND
