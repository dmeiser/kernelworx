"""Tests for src/utils/appsync_types.py - AppSync event type utilities."""

from typing import Any, Dict

import pytest

from src.utils.appsync_types import (
    get_caller_id,
    require_int,
    require_str,
    require_unit_number,
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

    def test_returns_none_when_identity_is_not_dict(self) -> None:
        """Test returns None when identity is a non-dict type."""
        event: Dict[str, Any] = {"identity": "not-a-dict"}
        assert get_caller_id(event) is None


class TestRequireStr:
    """Tests for require_str argument validator."""

    def test_returns_valid_string(self) -> None:
        """Valid non-empty string is returned."""
        assert require_str({"key": "value"}, "key") == "value"

    def test_missing_argument_raises(self) -> None:
        """Missing key raises INVALID_INPUT."""
        with pytest.raises(AppError) as exc_info:
            require_str({}, "key")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "required" in exc_info.value.message

    def test_null_argument_raises(self) -> None:
        """Explicitly null key raises INVALID_INPUT."""
        with pytest.raises(AppError) as exc_info:
            require_str({"key": None}, "key")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "required" in exc_info.value.message

    def test_empty_string_raises(self) -> None:
        """Empty string raises INVALID_INPUT."""
        with pytest.raises(AppError) as exc_info:
            require_str({"key": ""}, "key")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "non-empty string" in exc_info.value.message

    def test_non_string_type_raises(self) -> None:
        """Non-string value raises INVALID_INPUT."""
        with pytest.raises(AppError) as exc_info:
            require_str({"key": 123}, "key")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "non-empty string" in exc_info.value.message


class TestRequireInt:
    """Tests for require_int argument validator."""

    def test_returns_valid_int(self) -> None:
        """Integer value is returned as int."""
        assert require_int({"year": 2026}, "year") == 2026

    def test_converts_numeric_string(self) -> None:
        """Numeric string is converted to int."""
        assert require_int({"year": "2026"}, "year") == 2026

    def test_missing_argument_raises(self) -> None:
        """Missing argument raises INVALID_INPUT."""
        with pytest.raises(AppError) as exc_info:
            require_int({}, "year")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "required" in exc_info.value.message

    def test_non_integer_string_raises(self) -> None:
        """Non-numeric string raises INVALID_INPUT."""
        with pytest.raises(AppError) as exc_info:
            require_int({"year": "abc"}, "year")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "must be an integer" in exc_info.value.message

    def test_invalid_type_raises(self) -> None:
        """Non-scalar type raises INVALID_INPUT."""
        with pytest.raises(AppError) as exc_info:
            require_int({"year": [2026]}, "year")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "must be an integer" in exc_info.value.message


class TestRequireUnitNumber:
    """Tests for require_unit_number argument validator."""

    def test_returns_valid_unit_number(self) -> None:
        """Valid positive unit number is returned."""
        assert require_unit_number({"unitNumber": 42}, "unitNumber") == 42
        assert require_unit_number({"unitNumber": "100"}, "unitNumber") == 100

    def test_missing_unit_number_raises(self) -> None:
        """Missing unitNumber raises INVALID_INPUT."""
        with pytest.raises(AppError) as exc_info:
            require_unit_number({}, "unitNumber")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_invalid_unit_number_raises(self) -> None:
        """Non-positive or non-numeric unit number raises INVALID_INPUT."""
        with pytest.raises(AppError) as exc_info:
            require_unit_number({"unitNumber": 0}, "unitNumber")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

        with pytest.raises(AppError) as exc_info:
            require_unit_number({"unitNumber": -5}, "unitNumber")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

        with pytest.raises(AppError) as exc_info:
            require_unit_number({"unitNumber": "abc"}, "unitNumber")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
