"""Unit tests for delete_profile_cascade handler."""

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
os.environ.setdefault("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-v2-ue1-dev")
os.environ.setdefault("ORDERS_TABLE_NAME", "kernelworx-orders-v2-ue1-dev")
os.environ.setdefault("SHARES_TABLE_NAME", "kernelworx-shares-ue1-dev")
os.environ.setdefault("INVITES_TABLE_NAME", "kernelworx-invites-ue1-dev")


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
        TableName="kernelworx-campaigns-v2-ue1-dev",
        KeySchema=[
            {"AttributeName": "profileId", "KeyType": "HASH"},
            {"AttributeName": "campaignId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "profileId", "AttributeType": "S"},
            {"AttributeName": "campaignId", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    dynamodb.create_table(
        TableName="kernelworx-orders-v2-ue1-dev",
        KeySchema=[
            {"AttributeName": "campaignId", "KeyType": "HASH"},
            {"AttributeName": "orderId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "campaignId", "AttributeType": "S"},
            {"AttributeName": "orderId", "AttributeType": "S"},
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
    dynamodb.create_table(
        TableName="kernelworx-invites-ue1-dev",
        KeySchema=[{"AttributeName": "inviteCode", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "inviteCode", "AttributeType": "S"},
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


def _event(profile_path_id: str = "PROFILE%231", caller: str = "ACCOUNT#user-abc") -> Dict[str, Any]:
    return {
        "httpMethod": "POST",
        "path": f"/api/profiles/{profile_path_id}/cascade-delete",
        "requestContext": {"authorizer": {"sub": caller[8:] if caller.startswith("ACCOUNT#") else caller}},
        "body": None,
    }


# ---------------------------------------------------------------------------
# lambda_handler
# ---------------------------------------------------------------------------


def test_missing_profile_id_returns_400() -> None:
    from src.handlers.delete_profile_cascade import lambda_handler

    event: Dict[str, Any] = {"pathParameters": {}, "body": None, "requestContext": {"authorizer": {"sub": "u"}}}
    res = lambda_handler(event, None)
    assert res["statusCode"] == 400


def test_missing_caller_id_returns_401() -> None:
    """When get_caller_id returns empty string, returns 401."""
    from src.handlers.delete_profile_cascade import lambda_handler

    event: Dict[str, Any] = {
        "pathParameters": {"id": "PROFILE#1"},
        "body": None,
        "requestContext": {},
    }
    with patch("src.handlers.delete_profile_cascade.get_caller_id", return_value=""):
        res = lambda_handler(event, None)
    assert res["statusCode"] == 401


def test_profile_not_found_returns_404() -> None:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)

        from src.handlers.delete_profile_cascade import lambda_handler

        event: Dict[str, Any] = {
            "pathParameters": {"id": "PROFILE#missing"},
            "body": None,
            "requestContext": {"authorizer": {"sub": "user-abc"}},
        }
        res = lambda_handler(event, None)
        assert res["statusCode"] == 404


def test_caller_not_owner_returns_403() -> None:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        profiles_table = dynamodb.Table("kernelworx-profiles-v2-ue1-dev")
        profiles_table.put_item(Item={"ownerAccountId": "ACCOUNT#other", "profileId": "PROFILE#1"})

        from src.handlers.delete_profile_cascade import lambda_handler

        event: Dict[str, Any] = {
            "pathParameters": {"id": "PROFILE#1"},
            "body": None,
            "requestContext": {"authorizer": {"sub": "user-abc"}},
        }
        res = lambda_handler(event, None)
        assert res["statusCode"] == 403


def test_successful_cascade_delete() -> None:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        profiles_table = dynamodb.Table("kernelworx-profiles-v2-ue1-dev")
        profiles_table.put_item(Item={"ownerAccountId": "ACCOUNT#user-abc", "profileId": "PROFILE#1"})
        campaigns_table = dynamodb.Table("kernelworx-campaigns-v2-ue1-dev")
        campaigns_table.put_item(Item={"profileId": "PROFILE#1", "campaignId": "CAMPAIGN#1"})
        orders_table = dynamodb.Table("kernelworx-orders-v2-ue1-dev")
        orders_table.put_item(Item={"campaignId": "CAMPAIGN#1", "orderId": "ORDER#1"})
        shares_table = dynamodb.Table("kernelworx-shares-ue1-dev")
        shares_table.put_item(Item={"profileId": "PROFILE#1", "targetAccountId": "ACCOUNT#other"})
        invites_table = dynamodb.Table("kernelworx-invites-ue1-dev")
        invites_table.put_item(Item={"inviteCode": "INVITE#1", "profileId": "PROFILE#1"})

        from src.handlers.delete_profile_cascade import lambda_handler

        event: Dict[str, Any] = {
            "pathParameters": {"id": "PROFILE#1"},
            "body": None,
            "requestContext": {"authorizer": {"sub": "user-abc"}},
        }
        res = lambda_handler(event, None)
        assert res["statusCode"] == 200
        body = json.loads(res["body"])
        assert body["success"] is True


def test_cascade_delete_app_error_response() -> None:
    """AppError with FORBIDDEN returns correct status."""
    from src.handlers.delete_profile_cascade import lambda_handler
    from src.utils.errors import AppError, ErrorCode

    with patch("src.handlers.delete_profile_cascade.get_caller_id", return_value="user-abc"):
        with patch(
            "src.handlers.delete_profile_cascade._get_profile_owner_id",
            side_effect=AppError(ErrorCode.FORBIDDEN, "forbidden"),
        ):
            event: Dict[str, Any] = {
                "pathParameters": {"id": "PROFILE#1"},
                "body": None,
                "requestContext": {},
            }
            res = lambda_handler(event, None)
    assert res["statusCode"] == 403


def test_cascade_delete_generic_exception_returns_500() -> None:
    from src.handlers.delete_profile_cascade import lambda_handler

    with patch("src.handlers.delete_profile_cascade.get_caller_id", return_value="user-abc"):
        with patch(
            "src.handlers.delete_profile_cascade._get_profile_owner_id",
            side_effect=RuntimeError("boom"),
        ):
            event: Dict[str, Any] = {
                "pathParameters": {"id": "PROFILE#1"},
                "body": None,
                "requestContext": {},
            }
            res = lambda_handler(event, None)
    assert res["statusCode"] == 500


def test_lambda_handler_profile_id_from_body() -> None:
    """lambda_handler can read profileId from request body."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        profiles_table = dynamodb.Table("kernelworx-profiles-v2-ue1-dev")
        profiles_table.put_item(Item={"ownerAccountId": "ACCOUNT#user-abc", "profileId": "PROFILE#1"})

        from src.handlers.delete_profile_cascade import lambda_handler

        event: Dict[str, Any] = {
            "pathParameters": {},
            "body": json.dumps({"profileId": "PROFILE#1"}),
            "requestContext": {"authorizer": {"sub": "user-abc"}},
        }
        res = lambda_handler(event, None)
        assert res["statusCode"] == 200


# ---------------------------------------------------------------------------
# handler routing
# ---------------------------------------------------------------------------


def test_handler_cascade_delete_route() -> None:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        profiles_table = dynamodb.Table("kernelworx-profiles-v2-ue1-dev")
        profiles_table.put_item(Item={"ownerAccountId": "ACCOUNT#user-abc", "profileId": "PROFILE#1"})

        from src.handlers.delete_profile_cascade import handler

        event: Dict[str, Any] = {
            "httpMethod": "POST",
            "path": "/api/profiles/PROFILE%231/cascade-delete",
            "requestContext": {"authorizer": {"sub": "user-abc"}},
            "body": None,
        }
        res = handler(event, None)
        assert res["statusCode"] == 200


def test_handler_unknown_route_returns_404() -> None:
    from src.handlers.delete_profile_cascade import handler

    event: Dict[str, Any] = {"httpMethod": "GET", "path": "/unknown", "body": None}
    res = handler(event, None)
    assert res["statusCode"] == 404


# ---------------------------------------------------------------------------
# _batch_delete_keys
# ---------------------------------------------------------------------------


def test_batch_delete_keys_empty() -> None:
    from src.handlers.delete_profile_cascade import _batch_delete_keys

    mock_table = MagicMock()
    result = _batch_delete_keys(mock_table, [], ["pk", "sk"])
    assert result == 0


def test_batch_delete_keys_client_error() -> None:
    from src.handlers.delete_profile_cascade import _batch_delete_keys
    from src.utils.errors import AppError

    mock_table = MagicMock()
    mock_writer = MagicMock()
    mock_writer.__enter__ = MagicMock(return_value=mock_writer)
    mock_writer.__exit__ = MagicMock(return_value=False)
    mock_writer.delete_item.side_effect = ClientError({"Error": {"Code": "E", "Message": "m"}}, "Delete")
    mock_table.batch_writer.return_value = mock_writer

    with pytest.raises(AppError):
        _batch_delete_keys(mock_table, [{"pk": "a"}], ["pk"])


# ---------------------------------------------------------------------------
# _query_all_items with pagination
# ---------------------------------------------------------------------------


def test_query_all_items_paginates() -> None:
    from src.handlers.delete_profile_cascade import _query_all_items

    mock_table = MagicMock()
    mock_table.query.side_effect = [
        {"Items": [{"id": "1"}], "LastEvaluatedKey": {"id": "1"}},
        {"Items": [{"id": "2"}]},
    ]
    items = _query_all_items(mock_table, "pk = :pk", {":pk": "v"})
    assert len(items) == 2


def test_query_all_items_with_index_and_projection() -> None:
    from src.handlers.delete_profile_cascade import _query_all_items

    mock_table = MagicMock()
    mock_table.query.return_value = {"Items": [{"x": "y"}]}
    items = _query_all_items(mock_table, "pk = :pk", {":pk": "v"}, index_name="idx", projection="x")
    assert len(items) == 1
    kwargs = mock_table.query.call_args[1]
    assert kwargs["IndexName"] == "idx"
    assert kwargs["ProjectionExpression"] == "x"


# ---------------------------------------------------------------------------
# _collect_order_keys
# ---------------------------------------------------------------------------


def test_collect_order_keys_with_orders() -> None:
    from src.handlers.delete_profile_cascade import _collect_order_keys

    campaigns = [{"campaignId": "CAMPAIGN#1"}, {"campaignId": "CAMPAIGN#2"}]

    with patch("src.handlers.delete_profile_cascade._query_all_items") as mock_q:
        mock_q.side_effect = [
            [{"campaignId": "CAMPAIGN#1", "orderId": "ORDER#1"}],
            [],
        ]
        keys = _collect_order_keys(campaigns)
    assert len(keys) == 1
    assert keys[0]["orderId"] == "ORDER#1"


def test_collect_order_keys_campaign_without_campaign_id() -> None:
    """Campaigns without campaignId are skipped."""
    from src.handlers.delete_profile_cascade import _collect_order_keys

    campaigns = [{"no_id": True}]
    keys = _collect_order_keys(campaigns)
    assert keys == []


# ---------------------------------------------------------------------------
# _delete_profile error handling
# ---------------------------------------------------------------------------


def test_delete_profile_raises_app_error_on_exception() -> None:
    from src.handlers.delete_profile_cascade import _delete_profile
    from src.utils.errors import AppError

    with patch("src.handlers.delete_profile_cascade.tables") as mock_tables:
        mock_tables.profiles.delete_item.side_effect = RuntimeError("fail")
        with pytest.raises(AppError):
            _delete_profile("ACCOUNT#u", "PROFILE#1")
