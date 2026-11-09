"""Tests for src/utils/appsync_types.py - AppSync event type utilities."""

from typing import Any, Dict

from src.utils.appsync_types import (
    get_caller_id,
    require_bounded_str,
    require_cents,
    require_idempotency_key,
    require_int,
    require_str_enum,
    require_strict_int,
    require_timestamp,
    require_timezone,
    require_version,
)
from src.utils.errors import AppError, ErrorCode


class TestGetCallerId:
    """Tests for get_caller_id function."""

    def test_returns_sub_from_identity(self) -> None:
        """Test extracting sub from identity."""
        event: Dict[str, Any] = {"identity": {"sub": "user-123"}}
        assert get_caller_id(event) == "user-123"

    def test_returns_none_when_no_identity(self) -> None:
        """Test returns None when identity is missing."""
        event: Dict[str, Any] = {}
        assert get_caller_id(event) is None

    def test_returns_none_when_no_sub(self) -> None:
        """Test returns None when sub is missing."""
        event: Dict[str, Any] = {"identity": {}}
        assert get_caller_id(event) is None

    def test_returns_none_when_identity_is_null(self) -> None:
        """Test returns None instead of raising when identity is explicitly null.

        AppSync omits `identity` for an unauthenticated invocation, and the
        hand-inlined `event["identity"]["sub"]` dialect raised `KeyError` on
        exactly this shape.
        """
        event: Dict[str, Any] = {"identity": None}
        assert get_caller_id(event) is None


class TestRequireInt:
    def test_missing_raises(self) -> None:
        try:
            require_int({}, "x")
        except AppError as exc:
            assert exc.error_code == ErrorCode.INVALID_INPUT
        else:
            raise AssertionError("expected AppError")

    def test_invalid_raises(self) -> None:
        try:
            require_int({"x": "abc"}, "x")
        except AppError as exc:
            assert exc.error_code == ErrorCode.INVALID_INPUT
        else:
            raise AssertionError("expected AppError")

    def test_valid_returns_int(self) -> None:
        assert require_int({"x": "42"}, "x") == 42


class _StrictValidatorContract:
    """Shared shape: missing -> required; wrong type -> type message."""

    def assert_invalid(self, arguments: Dict[str, Any], name: str) -> None:
        try:
            self.call(arguments, name)
        except AppError as exc:
            assert exc.error_code == ErrorCode.INVALID_INPUT
        else:
            raise AssertionError("expected AppError")

    def call(self, arguments: Dict[str, Any], name: str) -> Any:  # pragma: no cover
        raise NotImplementedError


class TestRequireStrictInt(_StrictValidatorContract):
    def call(self, arguments: Dict[str, Any], name: str) -> Any:
        return require_strict_int(arguments, name)

    def test_accepts_int(self) -> None:
        assert require_strict_int({"x": 7}, "x") == 7

    def test_rejects_numeric_string(self) -> None:
        self.assert_invalid({"x": "42"}, "x")

    def test_rejects_float(self) -> None:
        self.assert_invalid({"x": 4.2}, "x")

    def test_rejects_bool(self) -> None:
        self.assert_invalid({"x": True}, "x")

    def test_missing(self) -> None:
        self.assert_invalid({}, "x")


class TestRequireBoundedStr(_StrictValidatorContract):
    def call(self, arguments: Dict[str, Any], name: str) -> Any:
        return require_bounded_str(arguments, name, 10)

    def test_accepts_within_bound(self) -> None:
        assert require_bounded_str({"x": "hello"}, "x", 10) == "hello"

    def test_rejects_over_bound(self) -> None:
        self.assert_invalid({"x": "x" * 11}, "x")

    def test_missing(self) -> None:
        self.assert_invalid({}, "x")

    def test_rejects_empty_by_default(self) -> None:
        self.assert_invalid({"x": ""}, "x")

    def test_allows_empty_when_flagged(self) -> None:
        assert require_bounded_str({"x": ""}, "x", 10, allow_empty=True) == ""

    def test_rejects_non_string(self) -> None:
        self.assert_invalid({"x": 5}, "x")


class TestRequireCents(_StrictValidatorContract):
    def call(self, arguments: Dict[str, Any], name: str) -> Any:
        return require_cents(arguments, name)

    def test_accepts_zero(self) -> None:
        assert require_cents({"x": 0}, "x") == 0

    def test_accepts_positive(self) -> None:
        assert require_cents({"x": 1999}, "x") == 1999

    def test_rejects_negative(self) -> None:
        self.assert_invalid({"x": -5}, "x")

    def test_rejects_float(self) -> None:
        self.assert_invalid({"x": 19.99}, "x")

    def test_rejects_over_maximum(self) -> None:
        try:
            require_cents({"x": 101}, "x", maximum=100)
        except AppError as exc:
            assert exc.error_code == ErrorCode.INVALID_INPUT
        else:
            raise AssertionError("expected AppError")

    def test_missing(self) -> None:
        self.assert_invalid({}, "x")


class TestRequireVersion(_StrictValidatorContract):
    def call(self, arguments: Dict[str, Any], name: str) -> Any:
        return require_version(arguments, name)

    def test_default_name(self) -> None:
        assert require_version({"expectedVersion": 3}) == 3

    def test_rejects_zero(self) -> None:
        self.assert_invalid({"expectedVersion": 0}, "expectedVersion")

    def test_rejects_negative(self) -> None:
        self.assert_invalid({"expectedVersion": -2}, "expectedVersion")


class TestRequireTimestamp(_StrictValidatorContract):
    def call(self, arguments: Dict[str, Any], name: str) -> Any:
        return require_timestamp(arguments, name)

    def test_accepts_z_suffix(self) -> None:
        assert require_timestamp({"x": "2026-11-09T12:00:00Z"}, "x") == "2026-11-09T12:00:00Z"

    def test_accepts_explicit_offset(self) -> None:
        value = "2026-11-09T12:00:00-07:00"
        assert require_timestamp({"x": value}, "x") == value

    def test_rejects_naive_timestamp(self) -> None:
        self.assert_invalid({"x": "2026-11-09T12:00:00"}, "x")

    def test_rejects_garbage(self) -> None:
        self.assert_invalid({"x": "not-a-time"}, "x")


class TestRequireTimezone(_StrictValidatorContract):
    def call(self, arguments: Dict[str, Any], name: str) -> Any:
        return require_timezone(arguments, name)

    def test_accepts_iana_name(self) -> None:
        assert require_timezone({"x": "America/Denver"}, "x") == "America/Denver"

    def test_rejects_abbreviation(self) -> None:
        self.assert_invalid({"x": "MST"}, "x")

    def test_rejects_unknown_zone(self) -> None:
        self.assert_invalid({"x": "Nowhere/Special"}, "x")


class TestRequireIdempotencyKey(_StrictValidatorContract):
    def call(self, arguments: Dict[str, Any], name: str) -> Any:
        return require_idempotency_key(arguments, name)

    def test_accepts_alphanumeric_key(self) -> None:
        assert require_idempotency_key({"x": "ABC123xy"}, "x") == "ABC123xy"

    def test_rejects_short_key(self) -> None:
        self.assert_invalid({"x": "SHORT"}, "x")

    def test_rejects_long_key(self) -> None:
        self.assert_invalid({"x": "K" * 129}, "x")

    def test_rejects_whitespace(self) -> None:
        self.assert_invalid({"x": "HAS SPACE 1"}, "x")

    def test_rejects_control_characters(self) -> None:
        self.assert_invalid({"x": "BAD\tKEY!!"}, "x")


class TestRequireStrEnum(_StrictValidatorContract):
    def call(self, arguments: Dict[str, Any], name: str) -> Any:
        return require_str_enum(arguments, name, ("SCHEDULED", "ACTIVE"))

    def test_accepts_allowed_value(self) -> None:
        assert require_str_enum({"x": "ACTIVE"}, "x", ("SCHEDULED", "ACTIVE")) == "ACTIVE"

    def test_rejects_value_outside_enum(self) -> None:
        self.assert_invalid({"x": "ENDED"}, "x")

    def test_rejects_wrong_case(self) -> None:
        self.assert_invalid({"x": "active"}, "x")
