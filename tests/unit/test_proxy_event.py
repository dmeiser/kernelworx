"""Unit tests for proxy_event utilities."""

import json

from src.utils.errors import AppError, ErrorCode
from src.utils.proxy_event import (
    error_response,
    get_authorizer_claims,
    get_caller_id,
    get_path_param,
    get_query_param,
    html_response,
    is_admin,
    json_response,
    parse_body,
    redirect_response,
)

# ---------------------------------------------------------------------------
# get_caller_id
# ---------------------------------------------------------------------------


def test_get_caller_id_from_claims_sub() -> None:
    event = {"requestContext": {"authorizer": {"claims": {"sub": "claims-sub-id"}}}}
    assert get_caller_id(event) == "claims-sub-id"


def test_get_caller_id_from_flat_authorizer_sub() -> None:
    event = {"requestContext": {"authorizer": {"sub": "flat-sub-id"}}}
    assert get_caller_id(event) == "flat-sub-id"


def test_get_caller_id_from_mock_user_id_header() -> None:
    event = {"requestContext": {}, "headers": {"x-mock-user-id": "mock-user"}}
    assert get_caller_id(event) == "mock-user"


def test_get_caller_id_from_test_sub_header() -> None:
    event = {"requestContext": {}, "headers": {"x-test-sub": "test-sub-user"}}
    assert get_caller_id(event) == "test-sub-user"


def test_get_caller_id_fallback_to_test_user_id() -> None:
    assert get_caller_id({}) == "test-user-id"


def test_get_caller_id_claims_not_dict() -> None:
    # When claims is not a dict, falls back to auth_ctx.get("sub")
    event = {"requestContext": {"authorizer": {"claims": "not-a-dict", "sub": "direct-sub"}}}
    assert get_caller_id(event) == "direct-sub"


# ---------------------------------------------------------------------------
# get_path_param
# ---------------------------------------------------------------------------


def test_get_path_param_found() -> None:
    event = {"pathParameters": {"profileId": "PROFILE#123"}}
    assert get_path_param(event, "profileId") == "PROFILE#123"


def test_get_path_param_missing_returns_default() -> None:
    event = {"pathParameters": {"other": "val"}}
    assert get_path_param(event, "profileId") == ""


def test_get_path_param_no_path_parameters() -> None:
    assert get_path_param({}, "profileId") == ""


def test_get_path_param_custom_default() -> None:
    event = {"pathParameters": {}}
    assert get_path_param(event, "x", "fallback") == "fallback"


# ---------------------------------------------------------------------------
# get_query_param
# ---------------------------------------------------------------------------


def test_get_query_param_found() -> None:
    event = {"queryStringParameters": {"page": "2"}}
    assert get_query_param(event, "page") == "2"


def test_get_query_param_missing_returns_none() -> None:
    event = {"queryStringParameters": {}}
    assert get_query_param(event, "page") is None


def test_get_query_param_no_qs() -> None:
    assert get_query_param({}, "page") is None


def test_get_query_param_with_default() -> None:
    assert get_query_param({}, "page", "1") == "1"


# ---------------------------------------------------------------------------
# parse_body
# ---------------------------------------------------------------------------


def test_parse_body_json() -> None:
    event = {"body": '{"name": "Alice", "age": 30}'}
    assert parse_body(event) == {"name": "Alice", "age": 30}


def test_parse_body_json_array_no_brace_returns_empty() -> None:
    # JSON array doesn't start with '{', falls through to return {}
    event = {"body": "[1, 2, 3]"}
    result = parse_body(event)
    assert result == {}


def test_parse_body_json_non_dict_via_mock() -> None:
    # Cover the {"_raw": parsed} branch by mocking json.loads to return a non-dict
    # for a body that starts with '{'
    from unittest.mock import patch

    with patch("src.utils.proxy_event.json") as mock_json:
        mock_json.loads.return_value = [1, 2, 3]
        mock_json.JSONDecodeError = __import__("json").JSONDecodeError
        event = {"body": "{not-real}"}
        result = parse_body(event)
    assert result == {"_raw": [1, 2, 3]}


def test_parse_body_invalid_json_returns_empty() -> None:
    event = {"body": "{not valid json"}
    assert parse_body(event) == {}


def test_parse_body_url_encoded() -> None:
    event = {"body": "name=Alice&city=NYC"}
    result = parse_body(event)
    assert result["name"] == "Alice"
    assert result["city"] == "NYC"


def test_parse_body_empty_string() -> None:
    assert parse_body({"body": ""}) == {}


def test_parse_body_none_body() -> None:
    assert parse_body({"body": None}) == {}


def test_parse_body_no_body_key() -> None:
    assert parse_body({}) == {}


# ---------------------------------------------------------------------------
# get_authorizer_claims
# ---------------------------------------------------------------------------


def test_get_authorizer_claims_with_claims_dict() -> None:
    event = {"requestContext": {"authorizer": {"claims": {"sub": "abc", "email": "x@y.com"}}}}
    claims = get_authorizer_claims(event)
    assert claims["sub"] == "abc"


def test_get_authorizer_claims_flat_ctx() -> None:
    event = {"requestContext": {"authorizer": {"sub": "flat-sub"}}}
    claims = get_authorizer_claims(event)
    assert claims["sub"] == "flat-sub"


def test_get_authorizer_claims_empty() -> None:
    assert get_authorizer_claims({}) == {}


def test_get_authorizer_claims_flat_ctx_returned() -> None:
    # When 'claims' is absent, auth_ctx is returned directly as a dict
    event = {"requestContext": {"authorizer": {"sub": "flat-sub", "other": "val"}}}
    claims = get_authorizer_claims(event)
    assert claims["sub"] == "flat-sub"
    assert claims["other"] == "val"


# ---------------------------------------------------------------------------
# is_admin
# ---------------------------------------------------------------------------


def test_is_admin_with_list_containing_admin() -> None:
    event = {"requestContext": {"authorizer": {"claims": {"cognito:groups": ["ADMIN", "USER"]}}}}
    assert is_admin(event) is True


def test_is_admin_with_string_admin() -> None:
    event = {"requestContext": {"authorizer": {"claims": {"cognito:groups": "ADMIN"}}}}
    assert is_admin(event) is True


def test_is_admin_not_in_groups() -> None:
    event = {"requestContext": {"authorizer": {"claims": {"cognito:groups": ["USER"]}}}}
    assert is_admin(event) is False


def test_is_admin_no_groups() -> None:
    event = {"requestContext": {"authorizer": {"claims": {}}}}
    assert is_admin(event) is False


def test_is_admin_exception_returns_false() -> None:
    # Pass something that will cause an exception during access
    assert is_admin(None) is False  # type: ignore[arg-type]


def test_is_admin_flat_authorizer_with_groups() -> None:
    event = {"requestContext": {"authorizer": {"cognito:groups": ["ADMIN"]}}}
    assert is_admin(event) is True


# ---------------------------------------------------------------------------
# html_response
# ---------------------------------------------------------------------------


def test_html_response_default_status() -> None:
    r = html_response("<h1>Hello</h1>")
    assert r["statusCode"] == 200
    assert r["headers"]["Content-Type"] == "text/html"
    assert r["body"] == "<h1>Hello</h1>"


def test_html_response_custom_status_and_headers() -> None:
    r = html_response("body", status_code=404, extra_headers={"X-Custom": "val"})
    assert r["statusCode"] == 404
    assert r["headers"]["X-Custom"] == "val"


# ---------------------------------------------------------------------------
# json_response
# ---------------------------------------------------------------------------


def test_json_response_default() -> None:
    r = json_response({"key": "val"})
    assert r["statusCode"] == 200
    assert json.loads(r["body"]) == {"key": "val"}
    assert r["headers"]["Content-Type"] == "application/json"


def test_json_response_custom_status() -> None:
    r = json_response({"err": "bad"}, status_code=400)
    assert r["statusCode"] == 400


def test_json_response_extra_headers() -> None:
    r = json_response({}, extra_headers={"X-Req-Id": "123"})
    assert r["headers"]["X-Req-Id"] == "123"


def test_json_response_non_serializable_uses_str() -> None:
    from datetime import datetime

    dt = datetime(2025, 1, 1)
    r = json_response({"ts": dt})
    assert "2025" in r["body"]


# ---------------------------------------------------------------------------
# error_response
# ---------------------------------------------------------------------------


def test_error_response_unauthorized() -> None:
    e = AppError(ErrorCode.UNAUTHORIZED, "not auth")
    r = error_response(e)
    assert r["statusCode"] == 401


def test_error_response_forbidden() -> None:
    e = AppError(ErrorCode.FORBIDDEN, "forbidden")
    r = error_response(e)
    assert r["statusCode"] == 403


def test_error_response_not_found() -> None:
    e = AppError(ErrorCode.NOT_FOUND, "not found")
    r = error_response(e)
    assert r["statusCode"] == 404


def test_error_response_invalid_input() -> None:
    e = AppError(ErrorCode.INVALID_INPUT, "bad input")
    r = error_response(e)
    assert r["statusCode"] == 400


def test_error_response_already_exists() -> None:
    e = AppError(ErrorCode.ALREADY_EXISTS, "exists")
    r = error_response(e)
    assert r["statusCode"] == 409


def test_error_response_unknown_error_code_uses_500() -> None:
    e = AppError("UNKNOWN_CODE", "oops")
    r = error_response(e)
    assert r["statusCode"] == 500


def test_error_response_generic_exception() -> None:
    e = ValueError("unexpected")
    r = error_response(e)
    assert r["statusCode"] == 500
    assert "unexpected" in r["body"]


def test_error_response_custom_status_code() -> None:
    e = AppError(ErrorCode.FORBIDDEN, "nope")
    r = error_response(e, status_code=418)
    # AppError overrides the default status_code
    assert r["statusCode"] == 403


# ---------------------------------------------------------------------------
# redirect_response
# ---------------------------------------------------------------------------


def test_redirect_response() -> None:
    r = redirect_response("/login")
    assert r["statusCode"] == 302
    assert r["headers"]["Location"] == "/login"
    assert r["body"] == ""
