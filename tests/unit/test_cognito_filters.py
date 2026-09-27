"""Unit tests for the shared Cognito filter formatter (#560)."""

import pytest

from src.utils.cognito_filters import cognito_user_filter
from src.utils.errors import AppError, ErrorCode

SUBS = [
    "2b0e7f1a-9c3d-4f5e-8a7b-1d2c3b4a5e6f",
    # A sub that is not a UUID must still be filterable: a deletion for a
    # non-existent user must resolve to NOT_FOUND, not INVALID_INPUT.
    "not-a-uuid-but-perfectly-safe",
    "user.name+tag",
]


class TestSubFilter:
    @pytest.mark.parametrize("sub", SUBS)
    def test_returns_exact_sub_expression(self, sub: str) -> None:
        assert cognito_user_filter("sub", sub) == f'sub = "{sub}"'

    def test_rejects_empty(self) -> None:
        with pytest.raises(AppError) as exc_info:
            cognito_user_filter("sub", "")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert exc_info.value.message == "Account ID is required"

    def test_rejects_over_256_chars(self) -> None:
        with pytest.raises(AppError) as exc_info:
            cognito_user_filter("sub", "a" * 257)
        assert exc_info.value.message == "Account ID is required"

    def test_accepts_256_chars(self) -> None:
        sub = "a" * 256
        assert cognito_user_filter("sub", sub) == f'sub = "{sub}"'

    @pytest.mark.parametrize("sub", ['a"b', "a\\b", 'a" OR 1=1 --', "a b", "a\tb", "a\nb"])
    def test_rejects_metachars_and_whitespace(self, sub: str) -> None:
        with pytest.raises(AppError) as exc_info:
            cognito_user_filter("sub", sub)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert exc_info.value.message == "Invalid account ID"

    def test_rejects_non_string(self) -> None:
        with pytest.raises(AppError) as exc_info:
            cognito_user_filter("sub", 12345)  # type: ignore[arg-type]
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT


class TestEmailFilter:
    def test_returns_exact_email_expression(self) -> None:
        assert cognito_user_filter("email", "user@example.com") == 'email = "user@example.com"'

    def test_loose_shape_requires_a_dotted_domain(self) -> None:
        with pytest.raises(AppError) as exc_info:
            cognito_user_filter("email", "user@example")
        assert exc_info.value.message == "Invalid email"

    def test_loose_shape_is_the_default(self) -> None:
        email = "user@sub_domain.example"
        assert cognito_user_filter("email", email) == cognito_user_filter("email", email, email_shape="loose")

    def test_strict_shape_requires_an_alphabetic_tld(self) -> None:
        with pytest.raises(AppError) as exc_info:
            cognito_user_filter("email", "user@example.1", email_shape="strict")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert exc_info.value.message == "Invalid email"

    def test_strict_shape_is_tighter_than_loose(self) -> None:
        """The pre-signup shape must reject at least everything the loose one does."""
        for email in ('user@example.com" OR 1=1', "user example@example.com", "not-an-email"):
            with pytest.raises(AppError):
                cognito_user_filter("email", email, email_shape="strict")
            with pytest.raises(AppError):
                cognito_user_filter("email", email, email_shape="loose")

    def test_rejects_empty(self) -> None:
        with pytest.raises(AppError) as exc_info:
            cognito_user_filter("email", "")
        assert exc_info.value.message == "Email is required"

    def test_rejects_over_254_chars(self) -> None:
        with pytest.raises(AppError) as exc_info:
            cognito_user_filter("email", "a" * 250 + "@b.co")
        assert exc_info.value.message == "Email is required"

    @pytest.mark.parametrize("email", ['a"b@c.com', "a\\b@c.com", "a b@c.com"])
    def test_rejects_metachars_and_whitespace(self, email: str) -> None:
        with pytest.raises(AppError) as exc_info:
            cognito_user_filter("email", email)
        assert exc_info.value.message == "Invalid email"


class TestEmailPrefixFilter:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("user", 'email ^= "user"'),
            ("user@", 'email ^= "user@"'),
            ("user@exa", 'email ^= "user@exa"'),
            ("first.last+tag@sub.example.co", 'email ^= "first.last+tag@sub.example.co"'),
        ],
    )
    def test_returns_starts_with_expression(self, query: str, expected: str) -> None:
        assert cognito_user_filter("email_prefix", query) == expected

    @pytest.mark.parametrize("query", ["user name", "user\tname", 'user" OR 1=1', "user\\", ""])
    def test_rejects_unsafe_prefixes(self, query: str) -> None:
        with pytest.raises(AppError) as exc_info:
            cognito_user_filter("email_prefix", query)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_rejects_over_254_chars(self) -> None:
        with pytest.raises(AppError) as exc_info:
            cognito_user_filter("email_prefix", "a" * 255)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
