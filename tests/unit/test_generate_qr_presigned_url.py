"""Unit tests for generate_qr_code_presigned_url handler."""

import json
import os
from typing import Any, Dict
from unittest.mock import patch

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from src.handlers.generate_qr_code_presigned_url import (
    _is_already_presigned,
    _validate_and_extract_params,
    generate_qr_code_presigned_url,
    handler,
)
from src.utils.errors import AppError, ErrorCode


def _event(caller: str = "user-abc", body: Any = None, path_id: str = "") -> Dict[str, Any]:
    return {
        "httpMethod": "POST",
        "path": f"/api/payment-methods/{path_id}/qr-presigned-url" if path_id else "/api/payment-methods/qr",
        "requestContext": {"authorizer": {"sub": caller}},
        "body": json.dumps(body) if body else None,
        "pathParameters": {"id": path_id} if path_id else {},
    }


# ---------------------------------------------------------------------------
# _is_already_presigned
# ---------------------------------------------------------------------------


def test_is_already_presigned_with_algorithm() -> None:
    assert _is_already_presigned("https://s3.amazonaws.com/b/k?X-Amz-Algorithm=AWS4") is True


def test_is_already_presigned_with_signature() -> None:
    assert _is_already_presigned("https://s3.amazonaws.com/b/k?X-Amz-Signature=abc") is True


def test_is_not_presigned() -> None:
    assert _is_already_presigned("https://s3.amazonaws.com/bucket/key.png") is False


# ---------------------------------------------------------------------------
# _validate_and_extract_params
# ---------------------------------------------------------------------------


def test_validate_missing_owner_raises_unauthorized() -> None:
    event = _event(caller="user-abc", body={})
    with pytest.raises(AppError) as exc:
        _validate_and_extract_params(event)
    assert exc.value.error_code == ErrorCode.UNAUTHORIZED


def test_validate_caller_mismatch_raises_forbidden() -> None:
    event = _event(caller="user-abc", body={"ownerAccountId": "user-xyz"})
    with pytest.raises(AppError) as exc:
        _validate_and_extract_params(event)
    assert exc.value.error_code == ErrorCode.FORBIDDEN


def test_validate_caller_matches_plain_owner() -> None:
    event = _event(caller="user-abc", body={"ownerAccountId": "user-abc", "methodName": "Cash"})
    owner, method, s3_key = _validate_and_extract_params(event)
    assert owner == "user-abc"
    assert method == "Cash"
    assert s3_key is None


def test_validate_caller_matches_account_prefix_owner() -> None:
    """owner with ACCOUNT# prefix should match caller without prefix."""
    event = _event(caller="user-abc", body={"ownerAccountId": "ACCOUNT#user-abc", "name": "Venmo"})
    owner, method, s3_key = _validate_and_extract_params(event)
    assert owner == "ACCOUNT#user-abc"
    assert method == "Venmo"


def test_validate_owner_from_path_parameter() -> None:
    event = _event(caller="user-abc", path_id="user-abc")
    event["body"] = json.dumps({"methodName": "PayPal"})
    owner, method, s3_key = _validate_and_extract_params(event)
    assert owner == "user-abc"


# ---------------------------------------------------------------------------
# generate_qr_code_presigned_url
# ---------------------------------------------------------------------------


def test_already_presigned_url_returned_as_is() -> None:
    url = "https://s3.amazonaws.com/bucket/key?X-Amz-Algorithm=AWS4"
    event = _event(caller="user-abc", body={"qrCodeUrl": url, "ownerAccountId": "user-abc"})
    res = generate_qr_code_presigned_url(event, None)
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body["url"] == url


def test_qr_code_url_not_presigned_falls_through_to_generate() -> None:
    """qrCodeUrl present but not presigned → fall through to generate new presigned URL."""
    url = "https://s3.amazonaws.com/bucket/key.png"  # not presigned
    event = _event(
        caller="user-abc",
        body={"qrCodeUrl": url, "ownerAccountId": "user-abc", "methodName": "Cash"},
    )
    with patch(
        "src.handlers.generate_qr_code_presigned_url.generate_presigned_get_url",
        return_value="https://new-signed",
    ):
        res = generate_qr_code_presigned_url(event, None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"])["url"] == "https://new-signed"


def test_non_presigned_url_generates_new() -> None:
    event = _event(caller="user-abc", body={"ownerAccountId": "user-abc", "methodName": "Cash"})
    with patch(
        "src.handlers.generate_qr_code_presigned_url.generate_presigned_get_url", return_value="https://new-url"
    ):
        res = generate_qr_code_presigned_url(event, None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"])["url"] == "https://new-url"


def test_no_qr_code_url_generates_presigned() -> None:
    event = _event(caller="user-abc", body={"ownerAccountId": "user-abc", "methodName": "Venmo", "s3Key": "k"})
    with patch("src.handlers.generate_qr_code_presigned_url.generate_presigned_get_url", return_value="https://signed"):
        res = generate_qr_code_presigned_url(event, None)
    assert res["statusCode"] == 200


def test_unauthorized_returns_401() -> None:
    event = _event(caller="user-abc", body={})
    res = generate_qr_code_presigned_url(event, None)
    assert res["statusCode"] == 401


def test_forbidden_returns_403() -> None:
    event = _event(caller="user-abc", body={"ownerAccountId": "user-other"})
    res = generate_qr_code_presigned_url(event, None)
    assert res["statusCode"] == 403


def test_unexpected_exception_returns_500() -> None:
    event = _event(caller="user-abc", body={"ownerAccountId": "user-abc", "methodName": "Cash"})
    with patch(
        "src.handlers.generate_qr_code_presigned_url.generate_presigned_get_url",
        side_effect=RuntimeError("boom"),
    ):
        res = generate_qr_code_presigned_url(event, None)
    assert res["statusCode"] == 500


# ---------------------------------------------------------------------------
# handler routing
# ---------------------------------------------------------------------------


def test_handler_routes_correctly() -> None:
    event: Dict[str, Any] = {
        "httpMethod": "POST",
        "path": "/api/payment-methods/user-abc/qr-presigned-url",
        "requestContext": {"authorizer": {"sub": "user-abc"}},
        "body": json.dumps({"methodName": "Cash"}),
        "pathParameters": {"id": "user-abc"},
    }
    with patch("src.handlers.generate_qr_code_presigned_url.generate_presigned_get_url", return_value="https://u"):
        res = handler(event, None)
    assert res["statusCode"] == 200


def test_handler_unknown_route_returns_404() -> None:
    event: Dict[str, Any] = {"httpMethod": "GET", "path": "/unknown", "body": None}
    res = handler(event, None)
    assert res["statusCode"] == 404


import pytest
