"""Tests for src/utils/appsync_types.py - AppSync event type utilities."""

from typing import Any, Dict

from src.utils.appsync_types import get_caller_id, require_int
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
