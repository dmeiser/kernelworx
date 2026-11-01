"""Tests for validation utilities."""

import pytest

from src.utils.errors import AppError, ErrorCode
from src.utils.validation import validate_unit_number


class TestValidateUnitNumber:
    """Tests for validate_unit_number function."""

    def test_valid_positive_integer(self) -> None:
        """Test that a positive integer is returned."""
        result = validate_unit_number(42)
        assert result == 42

    def test_valid_positive_integer_string(self) -> None:
        """Test that a positive integer string is converted."""
        result = validate_unit_number("123")
        assert result == 123

    def test_zero_raises_error(self) -> None:
        """Test that zero is rejected."""
        with pytest.raises(AppError) as exc_info:
            validate_unit_number(0)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "positive" in exc_info.value.message

    def test_negative_raises_error(self) -> None:
        """Test that negative values are rejected."""
        with pytest.raises(AppError) as exc_info:
            validate_unit_number(-5)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "positive" in exc_info.value.message

    def test_invalid_string_raises_error(self) -> None:
        """Test that non-numeric strings are rejected."""
        with pytest.raises(AppError) as exc_info:
            validate_unit_number("abc")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_non_numeric_type_raises_error(self) -> None:
        """Test that a non-numeric, non-string type is rejected as INVALID_INPUT."""
        with pytest.raises(AppError) as exc_info:
            validate_unit_number(["1"])
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_optional_missing_returns_none(self) -> None:
        """Test that None returns None when not required."""
        result = validate_unit_number(None)
        assert result is None

    def test_optional_empty_string_returns_none(self) -> None:
        """Test that empty string returns None when not required."""
        result = validate_unit_number("")
        assert result is None

    def test_required_missing_raises_error(self) -> None:
        """Test that None raises error when required."""
        with pytest.raises(AppError) as exc_info:
            validate_unit_number(None, required=True)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
