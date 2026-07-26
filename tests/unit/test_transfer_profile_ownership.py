"""Unit tests for transfer_profile_ownership handler."""

import json
import os
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws  # type: ignore[import-untyped]

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
os.environ.setdefault("SHARES_TABLE_NAME", "kernelworx-shares-ue1-dev")


def _create_tables(dynamodb: Any) -> None:
    dynamodb.create_table(
        TableName="kernelworx-profiles-v2-ue1-dev",
        KeySchema=[
            {"AttributeName": "ownerAccountId", "KeyType": "HASH"},
            {"AttributeName": "profileId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "ownerAccountId", "AttributeType": "S"},
            {"AttributeName": "profileId", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "profileId-index",
                "KeySchema": [{"AttributeName": "profileId", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    dynamodb.create_table(
        TableName="kernelworx-shares-ue1-dev",
        KeySchema=[
            {"AttributeName": "profileId", "KeyType": "HASH"},
            {"AttributeName": "targetAccountId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "profileId", "AttributeType": "S"},
            {"AttributeName": "targetAccountId", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _event(
    profile_id: str = "PROFILE#1",
    new_owner: str = "ACCOUNT#new-owner",
    caller: str = "user-abc",
    is_admin: bool = False,
) -> Dict[str, Any]:
    groups = ["ADMIN"] if is_admin else []
    return {
        "httpMethod": "POST",
        "path": f"/api/profiles/{profile_id}/transfer",
        "requestContext": {
            "authorizer": {
                "sub": caller,
                "cognito:groups": groups,
            }
        },
        "body": json.dumps({"profileId": profile_id, "newOwnerAccountId": new_owner}),
    }


# ---------------------------------------------------------------------------
# lambda_handler
# ---------------------------------------------------------------------------


def test_missing_profile_id_returns_400() -> None:
    from src.handlers.transfer_profile_ownership import lambda_handler

    event: Dict[str, Any] = {
        "requestContext": {"authorizer": {"sub": "u"}},
        "body": json.dumps({"newOwnerAccountId": "ACCOUNT#x"}),
    }
    res = lambda_handler(event, None)
    assert res["statusCode"] == 400


def test_missing_new_owner_returns_400() -> None:
    from src.handlers.transfer_profile_ownership import lambda_handler

    event: Dict[str, Any] = {
        "requestContext": {"authorizer": {"sub": "u"}},
        "body": json.dumps({"profileId": "PROFILE#1"}),
    }
    res = lambda_handler(event, None)
    assert res["statusCode"] == 400


def test_profile_not_found_returns_404() -> None:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)

        from src.handlers.transfer_profile_ownership import lambda_handler

        res = lambda_handler(_event(), None)
        assert res["statusCode"] == 404


def test_caller_not_owner_not_admin_returns_403() -> None:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        profiles_table = dynamodb.Table("kernelworx-profiles-v2-ue1-dev")
        # Profile owned by someone else
        profiles_table.put_item(Item={"ownerAccountId": "ACCOUNT#other", "profileId": "PROFILE#1"})

        from src.handlers.transfer_profile_ownership import lambda_handler

        res = lambda_handler(_event(caller="user-abc", is_admin=False), None)
        assert res["statusCode"] == 403


def test_new_owner_no_share_non_admin_returns_400() -> None:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        profiles_table = dynamodb.Table("kernelworx-profiles-v2-ue1-dev")
        profiles_table.put_item(Item={"ownerAccountId": "ACCOUNT#user-abc", "profileId": "PROFILE#1"})
        # No share for new owner

        from src.handlers.transfer_profile_ownership import lambda_handler

        res = lambda_handler(_event(caller="user-abc", new_owner="ACCOUNT#new-owner"), None)
        assert res["statusCode"] == 400


def test_successful_transfer_non_admin_with_share() -> None:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        profiles_table = dynamodb.Table("kernelworx-profiles-v2-ue1-dev")
        profiles_table.put_item(
            Item={"ownerAccountId": "ACCOUNT#user-abc", "profileId": "PROFILE#1", "sellerName": "Scout"}
        )
        shares_table = dynamodb.Table("kernelworx-shares-ue1-dev")
        shares_table.put_item(Item={"profileId": "PROFILE#1", "targetAccountId": "ACCOUNT#new-owner"})

        from src.handlers.transfer_profile_ownership import lambda_handler

        with patch("src.handlers.transfer_profile_ownership.boto3.client") as mock_client:
            mock_ddb = MagicMock()
            mock_client.return_value = mock_ddb
            res = lambda_handler(_event(caller="user-abc", new_owner="ACCOUNT#new-owner"), None)

        assert res["statusCode"] == 200


def test_successful_transfer_admin_no_share_needed() -> None:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        profiles_table = dynamodb.Table("kernelworx-profiles-v2-ue1-dev")
        profiles_table.put_item(
            Item={"ownerAccountId": "ACCOUNT#user-abc", "profileId": "PROFILE#1", "sellerName": "Scout"}
        )
        # No share needed for admin

        from src.handlers.transfer_profile_ownership import lambda_handler

        with patch("src.handlers.transfer_profile_ownership.boto3.client") as mock_client:
            mock_ddb = MagicMock()
            mock_client.return_value = mock_ddb
            res = lambda_handler(_event(caller="user-abc", new_owner="ACCOUNT#new-owner", is_admin=True), None)

        assert res["statusCode"] == 200


def test_transfer_ownership_client_error_returns_500() -> None:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        profiles_table = dynamodb.Table("kernelworx-profiles-v2-ue1-dev")
        profiles_table.put_item(Item={"ownerAccountId": "ACCOUNT#user-abc", "profileId": "PROFILE#1"})

        from src.handlers.transfer_profile_ownership import lambda_handler

        with patch("src.handlers.transfer_profile_ownership.boto3.client") as mock_client:
            mock_ddb = MagicMock()
            mock_ddb.transact_write_items.side_effect = ClientError(
                {"Error": {"Code": "TransactionCanceledException", "Message": "conflict"}},
                "TransactWriteItems",
            )
            mock_client.return_value = mock_ddb
            res = lambda_handler(_event(caller="user-abc", new_owner="ACCOUNT#new-owner", is_admin=True), None)
        assert res["statusCode"] == 500


def test_generic_exception_returns_500() -> None:
    from src.handlers.transfer_profile_ownership import lambda_handler

    with patch("src.handlers.transfer_profile_ownership.get_caller_id", return_value="user-abc"):
        with patch(
            "src.handlers.transfer_profile_ownership._get_and_verify_profile",
            side_effect=RuntimeError("boom"),
        ):
            event: Dict[str, Any] = {
                "requestContext": {"authorizer": {"sub": "u"}},
                "body": json.dumps({"profileId": "PROFILE#1", "newOwnerAccountId": "ACCOUNT#x"}),
            }
            res = lambda_handler(event, None)
    assert res["statusCode"] == 500


# ---------------------------------------------------------------------------
# handler routing
# ---------------------------------------------------------------------------


def test_handler_transfer_route() -> None:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        profiles_table = dynamodb.Table("kernelworx-profiles-v2-ue1-dev")
        profiles_table.put_item(Item={"ownerAccountId": "ACCOUNT#user-abc", "profileId": "PROFILE#1"})

        from src.handlers.transfer_profile_ownership import handler

        with patch("src.handlers.transfer_profile_ownership.boto3.client") as mock_client:
            mock_ddb = MagicMock()
            mock_client.return_value = mock_ddb
            event: Dict[str, Any] = {
                "httpMethod": "POST",
                "path": "/api/profiles/PROFILE%231/transfer",
                "requestContext": {"authorizer": {"sub": "user-abc", "cognito:groups": ["ADMIN"]}},
                "body": json.dumps({"newOwnerAccountId": "ACCOUNT#new-owner"}),
            }
            res = handler(event, None)
        assert res["statusCode"] == 200


def test_handler_unknown_route_returns_404() -> None:
    from src.handlers.transfer_profile_ownership import handler

    event: Dict[str, Any] = {"httpMethod": "GET", "path": "/unknown", "body": None}
    res = handler(event, None)
    assert res["statusCode"] == 404


# ---------------------------------------------------------------------------
# _delete_share_if_exists
# ---------------------------------------------------------------------------


def test_delete_share_if_exists_swallows_exception() -> None:
    from src.handlers.transfer_profile_ownership import _delete_share_if_exists

    with patch("src.handlers.transfer_profile_ownership.tables") as mock_tables:
        mock_tables.shares.delete_item.side_effect = RuntimeError("fail")
        # Should not raise
        _delete_share_if_exists("PROFILE#1", "ACCOUNT#new")
