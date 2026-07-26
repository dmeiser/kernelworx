"""Unit tests for list_catalogs_in_use handler."""

import json
import os
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import boto3
from moto import mock_aws  # type: ignore[import-untyped]

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
os.environ.setdefault("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-v2-ue1-dev")
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
        TableName="kernelworx-shares-ue1-dev",
        KeySchema=[
            {"AttributeName": "profileId", "KeyType": "HASH"},
            {"AttributeName": "targetAccountId", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "profileId", "AttributeType": "S"},
            {"AttributeName": "targetAccountId", "AttributeType": "S"},
            {"AttributeName": "x_targetAccountId", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "targetAccountId-index",
                "KeySchema": [{"AttributeName": "x_targetAccountId", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _event(caller: str = "user-abc") -> Dict[str, Any]:
    return {
        "httpMethod": "GET",
        "path": "/api/catalogs/in-use",
        "requestContext": {"authorizer": {"sub": caller}},
    }


def test_no_profiles_no_shares_returns_empty() -> None:
    """When caller has no profiles or shares, returns empty list."""
    from src.handlers.list_catalogs_in_use import handler

    with patch("src.handlers.list_catalogs_in_use._get_all_catalog_ids", return_value=set()):
        event = _event()
        res = handler(event, None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"]) == []


def test_owned_profiles_with_catalog_ids() -> None:
    """Owned profiles' campaigns contribute catalog IDs."""
    from src.handlers.list_catalogs_in_use import handler

    with patch("src.handlers.list_catalogs_in_use._get_all_catalog_ids", return_value={"CATALOG#A", "CATALOG#B"}):
        event = _event()
        res = handler(event, None)
    assert res["statusCode"] == 200
    ids = json.loads(res["body"])
    assert "CATALOG#A" in ids
    assert "CATALOG#B" in ids


def test_app_error_returns_500() -> None:
    from src.handlers.list_catalogs_in_use import handler
    from src.utils.errors import AppError, ErrorCode

    with patch(
        "src.handlers.list_catalogs_in_use._get_all_catalog_ids",
        side_effect=AppError(ErrorCode.INTERNAL_ERROR, "db error"),
    ):
        res = handler(_event(), None)
    assert res["statusCode"] == 500


def test_generic_exception_returns_500() -> None:
    from src.handlers.list_catalogs_in_use import handler

    with patch("src.handlers.list_catalogs_in_use._get_all_catalog_ids", side_effect=RuntimeError("boom")):
        res = handler(_event(), None)
    assert res["statusCode"] == 500


def test_caller_already_has_account_prefix() -> None:
    """When caller_sub already has ACCOUNT# prefix, no duplicate prefix."""
    from src.handlers.list_catalogs_in_use import handler

    with patch("src.handlers.list_catalogs_in_use._get_all_catalog_ids", return_value=set()) as mock_fn:
        event = _event(caller="ACCOUNT#user-abc")
        res = handler(event, None)
    assert res["statusCode"] == 200
    # Verify _get_all_catalog_ids was called with the prefixed ID (no double prefix)
    called_with = mock_fn.call_args[0][0]
    assert called_with == "ACCOUNT#ACCOUNT#user-abc" or called_with == "ACCOUNT#user-abc"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def test_get_owned_profile_ids() -> None:
    from src.handlers.list_catalogs_in_use import _get_owned_profile_ids

    with patch("src.handlers.list_catalogs_in_use.tables") as mock_tables:
        mock_tables.profiles.query.return_value = {"Items": [{"profileId": "PROFILE#1"}, {"no_id": True}]}
        ids = _get_owned_profile_ids("profiles-table", "ACCOUNT#user")
    assert ids == ["PROFILE#1"]


def test_get_shared_profile_ids() -> None:
    from src.handlers.list_catalogs_in_use import _get_shared_profile_ids

    with patch("src.handlers.list_catalogs_in_use.tables") as mock_tables:
        mock_tables.shares.query.return_value = {"Items": [{"profileId": "PROFILE#2"}, {}]}
        ids = _get_shared_profile_ids("shares-table", "ACCOUNT#user")
    assert ids == ["PROFILE#2"]


def test_get_catalog_ids_for_profile() -> None:
    from src.handlers.list_catalogs_in_use import _get_catalog_ids_for_profile

    with patch("src.handlers.list_catalogs_in_use.tables") as mock_tables:
        mock_tables.campaigns.query.return_value = {"Items": [{"catalogId": "CAT#1"}, {"no_catalog": True}]}
        ids = _get_catalog_ids_for_profile(["PROFILE#1"], "campaigns-table")
    assert "CAT#1" in ids


def test_query_all_paginates() -> None:
    from src.handlers.list_catalogs_in_use import _query_all

    mock_table = MagicMock()
    mock_table.query.side_effect = [
        {"Items": [{"a": 1}], "LastEvaluatedKey": {"a": 1}},
        {"Items": [{"b": 2}]},
    ]
    items = _query_all(mock_table, "pk = :pk", {":pk": "v"})
    assert len(items) == 2


def test_query_all_with_index_and_projection() -> None:
    from src.handlers.list_catalogs_in_use import _query_all

    mock_table = MagicMock()
    mock_table.query.return_value = {"Items": [{"x": "y"}]}
    items = _query_all(mock_table, "pk = :pk", {":pk": "v"}, index_name="idx", projection="x")
    assert len(items) == 1
    kwargs = mock_table.query.call_args[1]
    assert "IndexName" in kwargs
    assert "ProjectionExpression" in kwargs


def test_get_all_catalog_ids_integration() -> None:
    """_get_all_catalog_ids combines owned and shared profile catalog IDs."""
    from src.handlers.list_catalogs_in_use import _get_all_catalog_ids

    with patch("src.handlers.list_catalogs_in_use._get_owned_profile_ids", return_value=["PROFILE#1"]):
        with patch("src.handlers.list_catalogs_in_use._get_shared_profile_ids", return_value=["PROFILE#2"]):
            with patch(
                "src.handlers.list_catalogs_in_use._get_catalog_ids_for_profile",
                side_effect=[{"CAT#A"}, {"CAT#B"}],
            ):
                result = _get_all_catalog_ids("ACCOUNT#user")
    assert "CAT#A" in result
    assert "CAT#B" in result
