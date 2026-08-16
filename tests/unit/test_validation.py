"""Tests for validation utilities."""

import pytest

from src.utils.errors import AppError, ErrorCode
from src.utils.validation import (
    normalize_phone,
    validate_address,
    validate_invite_code,
    validate_unit_number,
)


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


class TestNormalizePhone:
    """Tests for normalize_phone function."""

    def test_normalize_plain_10_digits(self) -> None:
        """Test normalizing plain 10-digit phone."""
        result = normalize_phone("1234567890")
        assert result == "+11234567890"

    def test_normalize_with_dashes(self) -> None:
        """Test normalizing phone with dashes."""
        result = normalize_phone("123-456-7890")
        assert result == "+11234567890"

    def test_normalize_with_dots(self) -> None:
        """Test normalizing phone with dots."""
        result = normalize_phone("123.456.7890")
        assert result == "+11234567890"

    def test_normalize_with_spaces(self) -> None:
        """Test normalizing phone with spaces."""
        result = normalize_phone("123 456 7890")
        assert result == "+11234567890"

    def test_normalize_with_parens(self) -> None:
        """Test normalizing phone with parentheses."""
        result = normalize_phone("(123) 456-7890")
        assert result == "+11234567890"

    def test_normalize_with_plus_one(self) -> None:
        """Test normalizing phone with +1 prefix."""
        result = normalize_phone("+1-123-456-7890")
        assert result == "+11234567890"

    def test_invalid_phone_too_short(self) -> None:
        """Test that too-short phone raises error."""
        with pytest.raises(AppError) as exc_info:
            normalize_phone("12345")
        assert exc_info.value.error_code == ErrorCode.INVALID_PHONE

    def test_invalid_phone_with_letters(self) -> None:
        """Test that phone with letters raises error."""
        with pytest.raises(AppError) as exc_info:
            normalize_phone("123-456-ABCD")
        assert exc_info.value.error_code == ErrorCode.INVALID_PHONE

    def test_non_string_phone_coerced(self) -> None:
        """Test that non-string phone is coerced to string."""
        result = normalize_phone(1234567890)
        assert result == "+11234567890"

    def test_non_string_phone_invalid_raises_error(self) -> None:
        """Test that invalid non-string phone raises error."""
        with pytest.raises(AppError) as exc_info:
            normalize_phone(None)
        assert exc_info.value.error_code == ErrorCode.INVALID_PHONE


class TestValidateAddress:
    """Tests for validate_address function."""

    def test_valid_address_passes(self) -> None:
        """Test that valid address passes validation."""
        address = {"street": "123 Main St", "city": "Springfield", "state": "IL", "zipCode": "62701"}

        # Should not raise
        validate_address(address)

    def test_valid_address_with_9_digit_zip(self) -> None:
        """Test that 9-digit ZIP code is valid."""
        address = {
            "street": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "zipCode": "62701-1234",
        }

        validate_address(address)

    def test_missing_street_raises_error(self) -> None:
        """Test that missing street raises error."""
        address = {"city": "Springfield", "state": "IL", "zipCode": "62701"}

        with pytest.raises(AppError) as exc_info:
            validate_address(address)

        assert exc_info.value.error_code == ErrorCode.INVALID_ADDRESS
        assert "street" in exc_info.value.details["missingFields"]

    def test_missing_multiple_fields_raises_error(self) -> None:
        """Test that missing multiple fields raises error."""
        address = {"street": "123 Main St"}

        with pytest.raises(AppError) as exc_info:
            validate_address(address)

        assert exc_info.value.error_code == ErrorCode.INVALID_ADDRESS
        assert "city" in exc_info.value.details["missingFields"]
        assert "state" in exc_info.value.details["missingFields"]
        assert "zipCode" in exc_info.value.details["missingFields"]

    def test_invalid_zip_raises_error(self) -> None:
        """Test that invalid ZIP code raises error."""
        address = {"street": "123 Main St", "city": "Springfield", "state": "IL", "zipCode": "ABC"}

        with pytest.raises(AppError) as exc_info:
            validate_address(address)

        assert exc_info.value.error_code == ErrorCode.INVALID_ADDRESS


class TestValidateInviteCode:
    """Tests for validate_invite_code function."""

    def test_valid_8_char_code(self) -> None:
        """Test valid 8-character code."""
        result = validate_invite_code("ABC12345")
        assert result == "ABC12345"

    def test_valid_12_char_code(self) -> None:
        """Test valid 12-character code."""
        result = validate_invite_code("ABCD1234EFGH")
        assert result == "ABCD1234EFGH"

    def test_lowercase_converted_to_uppercase(self) -> None:
        """Test that lowercase is converted to uppercase."""
        result = validate_invite_code("abc12345")
        assert result == "ABC12345"

    def test_code_with_whitespace_trimmed(self) -> None:
        """Test that whitespace is trimmed."""
        result = validate_invite_code("  ABC12345  ")
        assert result == "ABC12345"

    def test_too_short_raises_error(self) -> None:
        """Test that code too short raises error."""
        with pytest.raises(AppError) as exc_info:
            validate_invite_code("ABC123")

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_too_long_raises_error(self) -> None:
        """Test that code too long raises error."""
        with pytest.raises(AppError) as exc_info:
            validate_invite_code("ABCD1234EFGH5")

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_special_chars_raise_error(self) -> None:
        """Test that special characters raise error."""
        with pytest.raises(AppError) as exc_info:
            validate_invite_code("ABC-12345")

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
