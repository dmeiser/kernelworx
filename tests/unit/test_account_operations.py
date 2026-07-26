"""Unit tests for account_operations handler."""

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
os.environ.setdefault("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
os.environ.setdefault("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
os.environ.setdefault("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-v2-ue1-dev")
os.environ.setdefault("ORDERS_TABLE_NAME", "kernelworx-orders-v2-ue1-dev")
os.environ.setdefault("SHARES_TABLE_NAME", "kernelworx-shares-ue1-dev")
os.environ.setdefault("INVITES_TABLE_NAME", "kernelworx-invites-ue1-dev")
os.environ.setdefault("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev")
os.environ.setdefault("EXPORTS_BUCKET", "kernelworx-exports-ue1-dev")


def _make_event(
    path: str = "/api/account", method: str = "POST", caller: str = "user-abc", body: Any = None
) -> Dict[str, Any]:
    return {
        "httpMethod": method,
        "path": path,
        "requestContext": {"authorizer": {"sub": caller}},
        "body": json.dumps(body) if isinstance(body, dict) else (body or "{}"),
    }


def _create_tables(dynamodb: Any) -> Dict[str, Any]:
    """Create all needed tables and return them."""
    tables: Dict[str, Any] = {}

    tables["accounts"] = dynamodb.create_table(
        TableName="kernelworx-accounts-ue1-dev",
        KeySchema=[{"AttributeName": "accountId", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "accountId", "AttributeType": "S"},
            {"AttributeName": "email", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "email-index",
                "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    tables["profiles"] = dynamodb.create_table(
        TableName=os.environ.get("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev"),
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

    tables["campaigns"] = dynamodb.create_table(
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

    tables["orders"] = dynamodb.create_table(
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

    tables["shares"] = dynamodb.create_table(
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

    tables["catalogs"] = dynamodb.create_table(
        TableName=os.environ.get("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev"),
        KeySchema=[{"AttributeName": "catalogId", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "catalogId", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    return tables


# ---------------------------------------------------------------------------
# update_my_account
# ---------------------------------------------------------------------------


def test_update_my_account_success() -> None:
    """Successful account update returns 200 with updated fields."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")
        accounts_table.put_item(Item={"accountId": "ACCOUNT#user-abc", "email": "user@example.com"})

        from src.handlers.account_operations import update_my_account

        event = _make_event(body={"givenName": "John", "familyName": "Doe"})
        res = update_my_account(event, None)
        assert res["statusCode"] == 200
        body = json.loads(res["body"])
        assert body["accountId"] == "ACCOUNT#user-abc"


def test_update_my_account_no_fields_returns_400() -> None:
    """When no updateable fields provided, returns 400."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)

        from src.handlers.account_operations import update_my_account

        event = _make_event(body={})
        res = update_my_account(event, None)
        assert res["statusCode"] == 400


def test_update_my_account_not_found_returns_404() -> None:
    """When account does not exist, returns 404."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)

        from src.handlers.account_operations import update_my_account

        event = _make_event(body={"givenName": "Jane"})
        res = update_my_account(event, None)
        assert res["statusCode"] == 404


def test_update_my_account_with_unit_number() -> None:
    """Account update with valid unitNumber succeeds."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")
        accounts_table.put_item(Item={"accountId": "ACCOUNT#user-abc", "email": "u@e.com"})

        from src.handlers.account_operations import update_my_account

        event = _make_event(body={"unitNumber": "42"})
        res = update_my_account(event, None)
        # unitNumber alone still only gives updatedAt + unitNumber = 2 expressions → ok
        assert res["statusCode"] == 200


def test_update_my_account_unit_number_invalid() -> None:
    """When unitNumber is invalid (non-integer), it is skipped."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")
        accounts_table.put_item(Item={"accountId": "ACCOUNT#user-abc", "email": "u@e.com"})

        from src.handlers.account_operations import update_my_account

        # unitNumber="" → validate_unit_number returns None (falsy, not required) → skipped → only updatedAt → 400
        event = _make_event(body={"unitNumber": ""})
        res = update_my_account(event, None)
        assert res["statusCode"] == 400


def test_update_my_account_dynamodb_error_returns_500() -> None:
    """Non-ConditionalCheck DynamoDB error returns 500."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")
        accounts_table.put_item(Item={"accountId": "ACCOUNT#user-abc"})

        from src.handlers.account_operations import update_my_account

        error_response = {"Error": {"Code": "InternalServerError", "Message": "boom"}}
        with patch("src.handlers.account_operations.tables") as mock_tables:
            mock_tables.accounts.update_item.side_effect = ClientError(error_response, "UpdateItem")
            event = _make_event(body={"givenName": "X"})
            res = update_my_account(event, None)
        assert res["statusCode"] == 500


# ---------------------------------------------------------------------------
# _get_user_profiles fallback (scan when GSI query fails)
# ---------------------------------------------------------------------------


def test_get_user_profiles_fallback_to_scan() -> None:
    """_get_user_profiles falls back to scan when GSI query raises."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        tbls = _create_tables(dynamodb)
        tbls["profiles"].put_item(Item={"ownerAccountId": "ACCOUNT#u", "profileId": "PROFILE#1"})

        from src.handlers.account_operations import _get_user_profiles

        with patch("src.handlers.account_operations.tables") as mock_tables:
            # GSI query raises, fallback scan succeeds
            mock_tables.profiles.query.side_effect = Exception("no GSI")
            mock_tables.profiles.scan.return_value = {
                "Items": [{"ownerAccountId": "ACCOUNT#u", "profileId": "PROFILE#1"}]
            }
            items = _get_user_profiles("ACCOUNT#u")
        assert len(items) == 1


def test_get_user_profiles_gsi_success() -> None:
    """_get_user_profiles returns items directly when GSI query succeeds."""
    from src.handlers.account_operations import _get_user_profiles

    with patch("src.handlers.account_operations.tables") as mock_tables:
        mock_tables.profiles.query.return_value = {"Items": [{"ownerAccountId": "ACCOUNT#u", "profileId": "PROFILE#1"}]}
        items = _get_user_profiles("ACCOUNT#u")
    assert len(items) == 1


# ---------------------------------------------------------------------------
# _query_all pagination
# ---------------------------------------------------------------------------


def test_query_all_with_pagination() -> None:
    """_query_all follows LastEvaluatedKey across pages."""
    from src.handlers.account_operations import _query_all

    mock_table = MagicMock()
    mock_table.query.side_effect = [
        {"Items": [{"id": "a"}], "LastEvaluatedKey": {"id": "a"}},
        {"Items": [{"id": "b"}]},
    ]
    items = _query_all(mock_table, "pk = :pk", {":pk": "val"})
    assert len(items) == 2


def test_query_all_with_index() -> None:
    """_query_all passes IndexName when provided."""
    from src.handlers.account_operations import _query_all

    mock_table = MagicMock()
    mock_table.query.return_value = {"Items": [{"id": "x"}]}
    items = _query_all(mock_table, "pk = :pk", {":pk": "v"}, index_name="my-index")
    assert len(items) == 1
    call_kwargs = mock_table.query.call_args[1]
    assert call_kwargs["IndexName"] == "my-index"


# ---------------------------------------------------------------------------
# delete_my_account
# ---------------------------------------------------------------------------


def test_delete_my_account_missing_user_pool_id() -> None:
    """When USER_POOL_ID is not set, returns 500."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)

        from src.handlers.account_operations import delete_my_account

        env = os.environ.copy()
        env.pop("USER_POOL_ID", None)
        with patch.dict(os.environ, env, clear=True):
            os.environ.pop("USER_POOL_ID", None)
            event = _make_event(path="/api/account/delete")
            res = delete_my_account(event, None)
        assert res["statusCode"] == 500
        assert "USER_POOL_ID" in res["body"]


def test_delete_my_account_success() -> None:
    """Successful account deletion returns 200."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)

        # Insert account record so deletion can proceed
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")
        accounts_table.put_item(Item={"accountId": "ACCOUNT#user-abc"})

        from src.handlers.account_operations import delete_my_account

        mock_cognito = MagicMock()
        mock_cognito.list_users.return_value = {"Users": [{"Username": "cognito-user-abc"}]}

        with patch.dict(os.environ, {"USER_POOL_ID": "us-east-1_TEST"}):
            with patch("src.handlers.account_operations.boto3.client", return_value=mock_cognito):
                event = _make_event(path="/api/account/delete")
                res = delete_my_account(event, None)

        assert res["statusCode"] == 200
        mock_cognito.admin_delete_user.assert_called_once()


def test_delete_my_account_user_not_found_in_cognito() -> None:
    """When Cognito user not found, deletion still succeeds (just logs warning)."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)

        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")
        accounts_table.put_item(Item={"accountId": "ACCOUNT#user-abc"})

        from src.handlers.account_operations import delete_my_account

        mock_cognito = MagicMock()
        mock_cognito.list_users.return_value = {"Users": []}

        with patch.dict(os.environ, {"USER_POOL_ID": "us-east-1_TEST"}):
            with patch("src.handlers.account_operations.boto3.client", return_value=mock_cognito):
                event = _make_event(path="/api/account/delete")
                res = delete_my_account(event, None)

        assert res["statusCode"] == 200
        mock_cognito.admin_delete_user.assert_not_called()


def test_delete_my_account_cognito_client_error_returns_500() -> None:
    """When Cognito raises unexpected ClientError, returns 500."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)

        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")
        accounts_table.put_item(Item={"accountId": "ACCOUNT#user-abc"})

        from src.handlers.account_operations import delete_my_account

        error = ClientError({"Error": {"Code": "ServiceError", "Message": "boom"}}, "AdminDeleteUser")
        mock_cognito = MagicMock()
        mock_cognito.list_users.return_value = {"Users": [{"Username": "u"}]}
        mock_cognito.admin_delete_user.side_effect = error

        with patch.dict(os.environ, {"USER_POOL_ID": "us-east-1_TEST"}):
            with patch("src.handlers.account_operations.boto3.client", return_value=mock_cognito):
                event = _make_event(path="/api/account/delete")
                res = delete_my_account(event, None)

        assert res["statusCode"] == 500


def test_delete_my_account_generic_exception_returns_500() -> None:
    """When unexpected exception occurs, returns 500."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)

        from src.handlers.account_operations import delete_my_account

        with patch.dict(os.environ, {"USER_POOL_ID": "us-east-1_TEST"}):
            with patch("src.handlers.account_operations._delete_all_user_data", side_effect=RuntimeError("fail")):
                event = _make_event(path="/api/account/delete")
                res = delete_my_account(event, None)

        assert res["statusCode"] == 500


def test_delete_my_account_with_data() -> None:
    """Deletion cascades through profiles, campaigns, orders, shares, catalogs."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        tbls = _create_tables(dynamodb)

        tbls["profiles"].put_item(Item={"ownerAccountId": "ACCOUNT#user-abc", "profileId": "PROFILE#1"})
        tbls["campaigns"].put_item(Item={"profileId": "PROFILE#1", "campaignId": "CAMPAIGN#1"})
        tbls["orders"].put_item(Item={"campaignId": "CAMPAIGN#1", "orderId": "ORDER#1"})
        tbls["shares"].put_item(Item={"profileId": "PROFILE#1", "targetAccountId": "ACCOUNT#other"})
        tbls["accounts"].put_item(Item={"accountId": "ACCOUNT#user-abc"})
        tbls["catalogs"].put_item(
            Item={"catalogId": "CATALOG#1", "ownerAccountId": "ACCOUNT#user-abc", "isDeleted": False}
        )

        from src.handlers.account_operations import delete_my_account

        mock_cognito = MagicMock()
        mock_cognito.list_users.return_value = {"Users": [{"Username": "u"}]}

        with patch.dict(os.environ, {"USER_POOL_ID": "us-east-1_TEST"}):
            with patch("src.handlers.account_operations.boto3.client", return_value=mock_cognito):
                event = _make_event(path="/api/account/delete")
                res = delete_my_account(event, None)

        assert res["statusCode"] == 200


def test_delete_cognito_user_not_found_exception() -> None:
    """When Cognito raises UserNotFoundException, it is swallowed."""
    from src.handlers.account_operations import _delete_user_from_cognito

    error = ClientError({"Error": {"Code": "UserNotFoundException", "Message": "not found"}}, "AdminDeleteUser")
    mock_cognito = MagicMock()
    mock_cognito.list_users.return_value = {"Users": [{"Username": "u"}]}
    mock_cognito.admin_delete_user.side_effect = error
    # Should not raise
    _delete_user_from_cognito(mock_cognito, "pool-id", "sub-123")


def test_delete_cognito_user_non_user_not_found_raises() -> None:
    """When Cognito raises other ClientError, it propagates."""
    from src.handlers.account_operations import _delete_user_from_cognito

    error = ClientError({"Error": {"Code": "InternalError", "Message": "boom"}}, "AdminDeleteUser")
    mock_cognito = MagicMock()
    mock_cognito.list_users.return_value = {"Users": [{"Username": "u"}]}
    mock_cognito.admin_delete_user.side_effect = error
    with pytest.raises(ClientError):
        _delete_user_from_cognito(mock_cognito, "pool-id", "sub-123")


# ---------------------------------------------------------------------------
# handler routing
# ---------------------------------------------------------------------------


def test_handler_update_route() -> None:
    """handler routes /api/account POST to update_my_account."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)

        from src.handlers.account_operations import handler

        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")
        accounts_table.put_item(Item={"accountId": "ACCOUNT#user-abc"})
        event = _make_event(path="/api/account", body={"givenName": "J"})
        res = handler(event, None)
        assert res["statusCode"] == 200


def test_handler_delete_route() -> None:
    """handler routes /api/account/delete POST to delete_my_account."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)

        from src.handlers.account_operations import handler

        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")
        accounts_table.put_item(Item={"accountId": "ACCOUNT#user-abc"})

        mock_cognito = MagicMock()
        mock_cognito.list_users.return_value = {"Users": []}

        with patch.dict(os.environ, {"USER_POOL_ID": "us-east-1_TEST"}):
            with patch("src.handlers.account_operations.boto3.client", return_value=mock_cognito):
                event = _make_event(path="/api/account/delete")
                res = handler(event, None)
        assert res["statusCode"] == 200


def test_handler_unknown_route_returns_404() -> None:
    """handler returns 404 for unknown routes."""
    from src.handlers.account_operations import handler

    event = {"httpMethod": "GET", "path": "/unknown", "body": None}
    res = handler(event, None)
    assert res["statusCode"] == 404


# ---------------------------------------------------------------------------
# all simple update fields
# ---------------------------------------------------------------------------


def test_update_all_simple_fields() -> None:
    """All SIMPLE_UPDATE_FIELDS are updated together."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        accounts_table = dynamodb.Table("kernelworx-accounts-ue1-dev")
        accounts_table.put_item(Item={"accountId": "ACCOUNT#user-abc"})

        from src.handlers.account_operations import update_my_account

        event = _make_event(
            body={
                "givenName": "John",
                "familyName": "Doe",
                "city": "Springfield",
                "state": "IL",
                "unitType": "Troop",
            }
        )
        res = update_my_account(event, None)
        assert res["statusCode"] == 200


def test_delete_user_catalogs_with_pagination() -> None:
    """_delete_user_catalogs handles paginated scan."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(dynamodb)
        catalogs_table = dynamodb.Table("kernelworx-catalogs-ue1-dev")
        catalogs_table.put_item(Item={"catalogId": "C1", "ownerAccountId": "ACCOUNT#u", "isDeleted": False})

        from src.handlers.account_operations import _delete_user_catalogs

        with patch("src.handlers.account_operations.tables") as mock_tables:
            mock_tables.catalogs.scan.side_effect = [
                {
                    "Items": [{"catalogId": "C1", "ownerAccountId": "ACCOUNT#u"}],
                    "LastEvaluatedKey": {"catalogId": "C1"},
                },
                {"Items": []},
            ]
            count = _delete_user_catalogs("u")
        assert count == 1
