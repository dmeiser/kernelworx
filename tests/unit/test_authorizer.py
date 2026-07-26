"""Unit tests for API Gateway custom request authorizer."""

import os
from typing import Any, Dict
from unittest.mock import MagicMock, patch

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from src.handlers.authorizer import _allow_policy, _case_insensitive_get, _deny_policy, _extract_token, handler


def _make_event(headers: Dict[str, Any] | None = None, method_arn: str = "") -> Dict[str, Any]:
    event: Dict[str, Any] = {}
    if headers is not None:
        event["headers"] = headers
    if method_arn:
        event["methodArn"] = method_arn
    return event


def test_case_insensitive_get_found() -> None:
    assert _case_insensitive_get({"Authorization": "token"}, "authorization") == "token"


def test_case_insensitive_get_uppercase_key() -> None:
    assert _case_insensitive_get({"AUTHORIZATION": "tok"}, "Authorization") == "tok"


def test_case_insensitive_get_not_found() -> None:
    assert _case_insensitive_get({"Content-Type": "json"}, "Authorization") is None


def test_case_insensitive_get_empty_headers() -> None:
    assert _case_insensitive_get({}, "Authorization") is None


def test_case_insensitive_get_none_headers() -> None:
    assert _case_insensitive_get(None, "Authorization") is None  # type: ignore[arg-type]


def test_extract_token_bearer_header() -> None:
    event = _make_event({"Authorization": "Bearer mytoken123"})
    assert _extract_token(event) == "mytoken123"


def test_extract_token_bearer_case_insensitive() -> None:
    event = _make_event({"authorization": "Bearer tok"})
    assert _extract_token(event) == "tok"


def test_extract_token_no_bearer_prefix() -> None:
    event = _make_event({"Authorization": "rawtoken"})
    assert _extract_token(event) == "rawtoken"


def test_extract_token_cookie_only() -> None:
    event = _make_event({"Cookie": "kw_access_token=cookietoken"})
    assert _extract_token(event) == "cookietoken"


def test_extract_token_cookie_multiple_cookies() -> None:
    event = _make_event({"Cookie": "session=abc; kw_access_token=mytoken; foo=bar"})
    assert _extract_token(event) == "mytoken"


def test_extract_token_cookie_not_present() -> None:
    event = _make_event({"Cookie": "session=abc; other=val"})
    assert _extract_token(event) == ""


def test_extract_token_auth_header_takes_precedence_over_cookie() -> None:
    event = _make_event({"Authorization": "Bearer headertoken", "Cookie": "kw_access_token=cookietoken"})
    assert _extract_token(event) == "headertoken"


def test_extract_token_no_headers_key() -> None:
    assert _extract_token({}) == ""


def test_extract_token_headers_none() -> None:
    assert _extract_token({"headers": None}) == ""


def test_deny_policy_with_arn() -> None:
    policy = _deny_policy("arn:aws:execute-api:us-east-1:123:abc/dev/GET/scouts")
    assert policy["principalId"] == "anonymous"
    stmt = policy["policyDocument"]["Statement"][0]
    assert stmt["Effect"] == "Deny"
    assert stmt["Resource"] == "arn:aws:execute-api:us-east-1:123:abc/dev/GET/scouts"


def test_deny_policy_empty_arn_uses_wildcard() -> None:
    policy = _deny_policy("")
    assert policy["policyDocument"]["Statement"][0]["Resource"] == "*"


def test_allow_policy() -> None:
    policy = _allow_policy("arn:test", "user-sub-123")
    assert policy["principalId"] == "user-sub-123"
    assert policy["context"] == {"sub": "user-sub-123"}
    stmt = policy["policyDocument"]["Statement"][0]
    assert stmt["Effect"] == "Allow"
    assert stmt["Resource"] == "arn:test"


def test_allow_policy_empty_arn_uses_wildcard() -> None:
    policy = _allow_policy("", "sub")
    assert policy["policyDocument"]["Statement"][0]["Resource"] == "*"


@patch("src.handlers.authorizer.cognito_client")
def test_handler_bearer_token_success(mock_cognito: MagicMock) -> None:
    mock_cognito.get_user.return_value = {"Username": "user-uuid-123"}
    event = _make_event({"Authorization": "Bearer validtoken"}, method_arn="arn:test")
    result = handler(event, None)
    assert result["principalId"] == "user-uuid-123"
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    mock_cognito.get_user.assert_called_once_with(AccessToken="validtoken")


@patch("src.handlers.authorizer.cognito_client")
def test_handler_cookie_token_success(mock_cognito: MagicMock) -> None:
    mock_cognito.get_user.return_value = {"Username": "cookie-user"}
    event = _make_event({"Cookie": "kw_access_token=cookietok"}, method_arn="arn:test")
    result = handler(event, None)
    assert result["principalId"] == "cookie-user"
    assert result["context"]["sub"] == "cookie-user"


def test_handler_no_token_denies() -> None:
    event = _make_event({}, method_arn="arn:test")
    result = handler(event, None)
    assert result["principalId"] == "anonymous"
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"


@patch("src.handlers.authorizer.cognito_client")
def test_handler_cognito_exception_denies(mock_cognito: MagicMock) -> None:
    mock_cognito.get_user.side_effect = Exception("NotAuthorizedException")
    event = _make_event({"Authorization": "Bearer badtoken"}, method_arn="arn:test")
    result = handler(event, None)
    assert result["principalId"] == "anonymous"
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"


@patch("src.handlers.authorizer.cognito_client")
def test_handler_empty_username_denies(mock_cognito: MagicMock) -> None:
    mock_cognito.get_user.return_value = {"Username": ""}
    event = _make_event({"Authorization": "Bearer tok"}, method_arn="arn:test")
    result = handler(event, None)
    assert result["principalId"] == "anonymous"
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"


@patch("src.handlers.authorizer.cognito_client")
def test_handler_no_method_arn(mock_cognito: MagicMock) -> None:
    mock_cognito.get_user.return_value = {"Username": "u"}
    event = _make_event({"Authorization": "Bearer t"})
    result = handler(event, None)
    assert result["principalId"] == "u"
    assert result["policyDocument"]["Statement"][0]["Resource"] == "*"


def test_handler_no_headers_at_all_denies() -> None:
    result = handler({}, None)
    assert result["principalId"] == "anonymous"
