"""Every Cognito ``ListUsers`` filter call site, asserted end to end (#560).

These are the six places in ``src/`` that build a Cognito user filter. Each row
invokes the real function with a stubbed Cognito client and asserts the exact
``Filter=`` string that reaches ``list_users`` -- so the value that was validated
and the value that was sent cannot drift apart. The second half asserts the
converse: a value carrying a filter metacharacter never reaches ``list_users`` at
all, from any of the six.
"""

import inspect
from typing import Any, Callable, Dict, List, Optional, Tuple, cast
from unittest.mock import MagicMock, patch

import pytest

from src.handlers import account_operations, admin_operations, pre_signup
from src.utils.errors import AppError, ErrorCode

POOL = "us-east-1_TEST123"
# Values that must never reach ``list_users``. The benign-prefixed rows matter as much
# as the leading-metacharacter one: they fail a guard that only inspects part of the
# value, which is the shape a validate/interpolate drift takes.
UNSAFE = [
    'x" OR 1=1 --',
    'aaaaaaaaaaaa" OR 1=1 --',
    "safe-prefix-then-backslash" + "\\",
    "safe-prefix-then space",
]
UUID = "2b0e7f1a-9c3d-4f5e-8a7b-1d2c3b4a5e6f"

# (label, call site, name of the parameter carrying the filtered value,
#  a safe value, the exact Filter expression it must produce)
FILTER_SITES: List[Tuple[str, Callable[..., Any], str, str, str]] = [
    (
        "admin _search_user_by_sub",
        admin_operations._search_user_by_sub,
        "sub",
        UUID,
        f'sub = "{UUID}"',
    ),
    (
        "admin _search_users_in_cognito_by_email_prefix",
        admin_operations._search_users_in_cognito_by_email_prefix,
        "query",
        "user@exa",
        'email ^= "user@exa"',
    ),
    (
        "admin _find_cognito_user_by_sub",
        admin_operations._find_cognito_user_by_sub,
        "account_id",
        f"ACCOUNT#{UUID}",
        f'sub = "{UUID}"',
    ),
    (
        "admin _find_user_by_email",
        admin_operations._find_user_by_email,
        "email",
        "user@example.com",
        'email = "user@example.com"',
    ),
    (
        "account _lookup_cognito_user_with_retry",
        account_operations._lookup_cognito_user_with_retry,
        "account_id",
        UUID,
        f'sub = "{UUID}"',
    ),
]

IDS = [case[0] for case in FILTER_SITES]


def _cognito_stub() -> MagicMock:
    cognito = MagicMock()
    cognito.list_users.return_value = {
        "Users": [{"Username": "someone", "Attributes": [{"Name": "email", "Value": "user@example.com"}]}]
    }
    return cognito


def _kwargs(site: Callable[..., Any], value_param: str, value: str) -> Dict[str, Any]:
    """Build the call kwargs for a filter call site, honouring its actual signature.

    Not every call site still takes a logger: #580 dropped the parameter as dead,
    so passing one unconditionally is a TypeError on the ones that shed it.
    """
    params = inspect.signature(site).parameters
    assert value_param in params, f"{site.__name__} has no {value_param!r} parameter"
    kwargs: Dict[str, Any] = {"cognito": _cognito_stub(), "user_pool_id": POOL, value_param: value}
    if "logger" in params:
        kwargs["logger"] = MagicMock()
    return kwargs


def _call(site: Callable[..., Any], value_param: str, value: str) -> MagicMock:
    """Invoke a filter call site with a stubbed Cognito client, returning the stub."""
    kwargs = _kwargs(site, value_param, value)
    site(**kwargs)
    return cast(MagicMock, kwargs["cognito"])


@pytest.mark.parametrize(("_label", "site", "value_param", "safe_value", "expected"), FILTER_SITES, ids=IDS)
def test_call_site_sends_the_exact_expected_filter(
    _label: str, site: Callable[..., Any], value_param: str, safe_value: str, expected: str
) -> None:
    cognito = _call(site, value_param, safe_value)

    assert cognito.list_users.call_count == 1
    assert cognito.list_users.call_args.kwargs["Filter"] == expected


@pytest.mark.parametrize(("_label", "site", "value_param", "safe_value", "expected"), FILTER_SITES, ids=IDS)
@pytest.mark.parametrize("unsafe", UNSAFE, ids=[f"unsafe{i}" for i in range(len(UNSAFE))])
def test_call_site_rejects_a_metacharacter_before_querying(
    _label: str, site: Callable[..., Any], value_param: str, safe_value: str, expected: str, unsafe: str
) -> None:
    kwargs = _kwargs(site, value_param, unsafe)
    cognito = cast(MagicMock, kwargs["cognito"])

    with pytest.raises(AppError) as exc_info:
        site(**kwargs)

    assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
    cognito.list_users.assert_not_called()


@pytest.mark.parametrize(("_label", "site", "value_param", "safe_value", "expected"), FILTER_SITES, ids=IDS)
def test_call_site_rejects_whitespace_before_querying(
    _label: str, site: Callable[..., Any], value_param: str, safe_value: str, expected: str
) -> None:
    kwargs = _kwargs(site, value_param, "a b")
    cognito = cast(MagicMock, kwargs["cognito"])

    with pytest.raises(AppError):
        site(**kwargs)

    cognito.list_users.assert_not_called()


def _federated_event(email: Any) -> Dict[str, Any]:
    return {
        "triggerSource": "PreSignUp_ExternalProvider",
        "userPoolId": POOL,
        "userName": "Google_123456789",
        "request": {"userAttributes": {"email": email, "email_verified": "true"}},
        "response": {"autoConfirmUser": False, "autoVerifyEmail": False, "autoVerifyPhone": False},
    }


def test_pre_signup_sends_the_exact_expected_filter() -> None:
    with patch("boto3.client") as mock_client:
        mock_cognito = _cognito_stub()
        # No existing user: the trigger must still have queried with the exact filter.
        mock_cognito.list_users.return_value = {"Users": []}
        mock_client.return_value = mock_cognito
        pre_signup.lambda_handler(_federated_event("user@example.com"), MagicMock())

    assert mock_cognito.list_users.call_args.kwargs["Filter"] == 'email = "user@example.com"'


@pytest.mark.parametrize(
    "email",
    [
        'user@example.com" OR 1=1',  # filter metacharacter
        "user example@example.com",  # whitespace
        "user@example.1",  # non-alphabetic TLD: rejected by the strict provider shape
        "user@sub_domain.example",  # underscore: rejected by the strict provider shape
        12345,  # non-string attribute
    ],
)
def test_pre_signup_rejects_an_unsafe_provider_email_before_querying(email: Any) -> None:
    with patch("boto3.client") as mock_client:
        result = pre_signup.lambda_handler(_federated_event(email), MagicMock())

    mock_client.assert_not_called()
    assert result["response"]["autoConfirmUser"] is True


def test_find_cognito_user_by_sub_resolves_not_found_for_a_safe_non_uuid() -> None:
    """A safe non-UUID account ID must reach Cognito, not be rejected as INVALID_INPUT."""
    cognito = MagicMock()
    cognito.list_users.return_value = {"Users": []}

    result: Optional[Tuple[None, None]] = admin_operations._find_cognito_user_by_sub(
        cognito, POOL, "ACCOUNT#definitely-not-a-uuid", MagicMock()
    )

    assert result == (None, None)
    assert cognito.list_users.call_args.kwargs["Filter"] == 'sub = "definitely-not-a-uuid"'
