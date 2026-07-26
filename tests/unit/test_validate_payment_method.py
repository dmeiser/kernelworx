"""Unit tests for validate_payment_method handler."""

import json
import os
from typing import Any, Dict
from unittest.mock import patch

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from src.handlers.validate_payment_method import handler, lambda_handler
from src.utils.errors import AppError, ErrorCode


def _event(caller: str = "user-abc", body: Any = None) -> Dict[str, Any]:
    return {
        "httpMethod": "POST",
        "path": "/api/payment-methods/validate",
        "requestContext": {"authorizer": {"sub": caller}},
        "body": json.dumps(body) if body else "{}",
    }


def test_missing_payment_method_returns_400() -> None:
    res = lambda_handler(_event(body={}), None)
    assert res["statusCode"] == 400
    assert "required" in json.loads(res["body"])["error"]


def test_caller_id_mismatch_returns_403() -> None:
    body = {"paymentMethod": "Cash", "ownerAccountId": "user-other"}
    res = lambda_handler(_event(caller="user-abc", body=body), None)
    assert res["statusCode"] == 403


def test_valid_payment_no_owner_returns_200() -> None:
    res = lambda_handler(_event(body={"paymentMethod": "Cash"}), None)
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body["valid"] is True
    assert body["paymentMethod"] == "Cash"


def test_valid_payment_with_matching_owner() -> None:
    body = {"paymentMethod": "Venmo", "ownerAccountId": "user-abc"}
    with patch("src.handlers.validate_payment_method.validate_payment_method_exists"):
        res = lambda_handler(_event(caller="user-abc", body=body), None)
    assert res["statusCode"] == 200


def test_valid_payment_with_account_prefix_owner() -> None:
    """ACCOUNT# prefix is stripped before calling validate_payment_method_exists."""
    body = {"paymentMethod": "PayPal", "ownerAccountId": "ACCOUNT#user-abc"}
    with patch("src.handlers.validate_payment_method.validate_payment_method_exists") as mock_v:
        res = lambda_handler(_event(caller="ACCOUNT#user-abc", body=body), None)
    assert res["statusCode"] == 200
    mock_v.assert_called_once_with("user-abc", "PayPal")


def test_app_error_invalid_input_returns_400() -> None:
    body = {"paymentMethod": "Bad", "ownerAccountId": "user-abc"}
    with patch(
        "src.handlers.validate_payment_method.validate_payment_method_exists",
        side_effect=AppError(ErrorCode.INVALID_INPUT, "invalid"),
    ):
        res = lambda_handler(_event(caller="user-abc", body=body), None)
    assert res["statusCode"] == 400
    assert json.loads(res["body"])["valid"] is False


def test_app_error_forbidden_returns_403() -> None:
    body = {"paymentMethod": "X", "ownerAccountId": "user-abc"}
    with patch(
        "src.handlers.validate_payment_method.validate_payment_method_exists",
        side_effect=AppError(ErrorCode.FORBIDDEN, "forbidden"),
    ):
        res = lambda_handler(_event(caller="user-abc", body=body), None)
    assert res["statusCode"] == 403


def test_app_error_unauthorized_returns_401() -> None:
    body = {"paymentMethod": "X", "ownerAccountId": "user-abc"}
    with patch(
        "src.handlers.validate_payment_method.validate_payment_method_exists",
        side_effect=AppError(ErrorCode.UNAUTHORIZED, "unauth"),
    ):
        res = lambda_handler(_event(caller="user-abc", body=body), None)
    assert res["statusCode"] == 401


def test_unexpected_exception_returns_500() -> None:
    body = {"paymentMethod": "Cash", "ownerAccountId": "user-abc"}
    with patch(
        "src.handlers.validate_payment_method.validate_payment_method_exists",
        side_effect=RuntimeError("boom"),
    ):
        res = lambda_handler(_event(caller="user-abc", body=body), None)
    assert res["statusCode"] == 500


def test_name_field_used_as_payment_method() -> None:
    """body.name is accepted as payment method."""
    res = lambda_handler(_event(body={"name": "Stripe"}), None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"])["paymentMethod"] == "Stripe"


# ---------------------------------------------------------------------------
# handler routing
# ---------------------------------------------------------------------------


def test_handler_routes_to_validate() -> None:
    res = handler(_event(body={"paymentMethod": "Cash"}), None)
    assert res["statusCode"] == 200


def test_handler_unknown_route_returns_404() -> None:
    event: Dict[str, Any] = {"httpMethod": "GET", "path": "/unknown", "body": None}
    res = handler(event, None)
    assert res["statusCode"] == 404
