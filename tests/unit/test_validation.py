"""Tests for validation utilities."""

import pytest
from src.utils.errors import AppError, ErrorCode
from src.utils.validation import (
    normalize_phone,
    validate_address,
    validate_campaign_update,
    validate_customer_input,
    validate_invite_code,
    validate_order_update,
)


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


class TestValidateAddress:
    """Tests for validate_address function."""

    def test_valid_address_passes(self) -> None:
        """Test that valid address passes validation."""
        address = {"street": "123 Main St", "city": "Springfield", "state": "IL", "zip": "62701"}

        # Should not raise
        validate_address(address)

    def test_valid_address_with_9_digit_zip(self) -> None:
        """Test that 9-digit ZIP code is valid."""
        address = {
            "street": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "zip": "62701-1234",
        }

        validate_address(address)

    def test_missing_street_raises_error(self) -> None:
        """Test that missing street raises error."""
        address = {"city": "Springfield", "state": "IL", "zip": "62701"}

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
        assert "zip" in exc_info.value.details["missingFields"]

    def test_invalid_zip_raises_error(self) -> None:
        """Test that invalid ZIP code raises error."""
        address = {"street": "123 Main St", "city": "Springfield", "state": "IL", "zip": "ABC"}

        with pytest.raises(AppError) as exc_info:
            validate_address(address)

        assert exc_info.value.error_code == ErrorCode.INVALID_ADDRESS


class TestValidateCustomerInput:
    """Tests for validate_customer_input function."""

    def test_valid_customer_with_phone(self) -> None:
        """Test valid customer with phone."""
        customer = {"name": "John Doe", "phone": "123-456-7890"}

        result = validate_customer_input(customer)

        assert result["name"] == "John Doe"
        assert result["phone"] == "+11234567890"
        assert "address" not in result

    def test_valid_customer_with_address(self) -> None:
        """Test valid customer with address."""
        customer = {
            "name": "Jane Smith",
            "address": {"street": "456 Oak Ave", "city": "Boston", "state": "MA", "zip": "02101"},
        }

        result = validate_customer_input(customer)

        assert result["name"] == "Jane Smith"
        assert result["address"] == customer["address"]
        assert "phone" not in result

    def test_valid_customer_with_both(self) -> None:
        """Test valid customer with both phone and address."""
        customer = {
            "name": "Bob Johnson",
            "phone": "(555) 123-4567",
            "address": {"street": "789 Elm St", "city": "Austin", "state": "TX", "zip": "78701"},
        }

        result = validate_customer_input(customer)

        assert result["name"] == "Bob Johnson"
        assert result["phone"] == "+15551234567"
        assert result["address"] == customer["address"]

    def test_missing_name_raises_error(self) -> None:
        """Test that missing name raises error."""
        customer = {"phone": "123-456-7890"}

        with pytest.raises(AppError) as exc_info:
            validate_customer_input(customer)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "name" in exc_info.value.message

    def test_empty_name_raises_error(self) -> None:
        """Test that empty name raises error."""
        customer = {"name": "   ", "phone": "123-456-7890"}

        with pytest.raises(AppError) as exc_info:
            validate_customer_input(customer)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_no_contact_method_raises_error(self) -> None:
        """Test that missing both phone and address raises error."""
        customer = {"name": "Test User"}

        with pytest.raises(AppError) as exc_info:
            validate_customer_input(customer)

        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "contact method" in exc_info.value.message

    def test_invalid_phone_raises_error(self) -> None:
        """Test that invalid phone raises error."""
        customer = {"name": "Test User", "phone": "invalid"}

        with pytest.raises(AppError) as exc_info:
            validate_customer_input(customer)

        assert exc_info.value.error_code == ErrorCode.INVALID_PHONE

    def test_invalid_address_raises_error(self) -> None:
        """Test that invalid address raises error."""
        customer = {"name": "Test User", "address": {"street": "123 Main"}}

        with pytest.raises(AppError) as exc_info:
            validate_customer_input(customer)

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


class TestValidateCampaigngnUpdate:
    """Tests for validate_campaign_update function."""

    def test_validate_campaign_update_valid(self) -> None:
        """Test valid campaigngn update."""
        updates = {"name": "Fall 2025"}

        result = validate_campaign_update(updates)

        assert result is None

    def test_validate_campaign_update_empty_name(self) -> None:
        """Test that empty name returns error."""
        updates = {"name": ""}

        result = validate_campaign_update(updates)

        assert result is not None
        assert result["errorCode"] == "INVALID_INPUT"

    def test_validate_campaign_update_dates(self) -> None:
        """Test valid date update."""
        updates = {"startDate": "2025-09-01", "endDate": "2025-11-30"}

        result = validate_campaign_update(updates)

        assert result is None

    def test_validate_campaign_update_invalid_date_order(self) -> None:
        """Test that endDate before startDate returns error."""
        updates = {"startDate": "2025-11-30", "endDate": "2025-09-01"}

        result = validate_campaign_update(updates)

        assert result is not None
        assert result["errorCode"] == "INVALID_INPUT"

    def test_validate_campaign_update_empty_start_date(self) -> None:
        """Test that empty startDate returns error."""
        updates = {"startDate": ""}

        result = validate_campaign_update(updates)

        assert result is not None
        assert result["errorCode"] == "INVALID_INPUT"

    def test_validate_campaign_update_empty_end_date(self) -> None:
        """Test that empty endDate is allowed (open-ended campaigngn)."""
        updates = {"startDate": "2025-09-01", "endDate": ""}

        result = validate_campaign_update(updates)

        assert result is None

    def test_validate_campaign_update_no_updates(self) -> None:
        """Test that empty updates dict returns None."""
        result = validate_campaign_update({})

        assert result is None


class TestValidateOrderUpdate:
    """Tests for validate_order_update function."""

    def test_validate_order_update_valid(self) -> None:
        """Test valid order update."""
        updates = {"customerName": "John Doe"}

        result = validate_order_update(updates)

        assert result is None

    def test_validate_order_update_empty_name(self) -> None:
        """Test that empty customer name returns error."""
        updates = {"customerName": ""}

        result = validate_order_update(updates)

        assert result is not None
        assert result["errorCode"] == "INVALID_INPUT"

    def test_validate_order_update_invalid_phone(self) -> None:
        """Test that invalid phone returns error."""
        updates = {"customerPhone": "123"}

        result = validate_order_update(updates)

        assert result is not None
        assert result["errorCode"] == "INVALID_INPUT"

    def test_validate_order_update_valid_phone(self) -> None:
        """Test valid phone in order update."""
        updates = {"customerPhone": "5551234567"}

        result = validate_order_update(updates)

        assert result is None

    def test_validate_order_update_valid_line_items(self) -> None:
        """Test valid line items."""
        updates = {
            "lineItems": [
                {"productId": "PROD1", "quantity": 2, "pricePerUnit": 10.0},
                {"productId": "PROD2", "quantity": 1, "pricePerUnit": 15.0},
            ]
        }

        result = validate_order_update(updates)

        assert result is None

    def test_validate_order_update_empty_line_items(self) -> None:
        """Test that empty line items returns error."""
        updates = {"lineItems": []}

        result = validate_order_update(updates)

        assert result is not None
        assert result["errorCode"] == "INVALID_INPUT"

    def test_validate_order_update_invalid_line_item_quantity(self) -> None:
        """Test that invalid quantity returns error."""
        updates = {"lineItems": [{"productId": "PROD1", "quantity": 0}]}

        result = validate_order_update(updates)

        assert result is not None
        assert result["errorCode"] == "INVALID_INPUT"

    def test_validate_order_update_invalid_line_item_missing_product_id(self) -> None:
        """Test that missing productId returns error."""
        updates = {"lineItems": [{"quantity": 1}]}

        result = validate_order_update(updates)

        assert result is not None
        assert result["errorCode"] == "INVALID_INPUT"

    def test_validate_order_update_invalid_line_item_not_array(self) -> None:
        """Test that non-array line items returns error."""
        updates = {"lineItems": "not an array"}

        result = validate_order_update(updates)

        assert result is not None
        assert result["errorCode"] == "INVALID_INPUT"

    def test_validate_order_update_invalid_line_item_not_dict(self) -> None:
        """Test that line item not being dict returns error."""
        updates = {"lineItems": ["not a dict"]}

        result = validate_order_update(updates)

        assert result is not None
        assert result["errorCode"] == "INVALID_INPUT"

    def test_validate_order_update_invalid_price_per_unit(self) -> None:
        """Test that non-numeric pricePerUnit returns error."""
        updates = {"lineItems": [{"productId": "PROD1", "quantity": 1, "pricePerUnit": "abc"}]}

        result = validate_order_update(updates)

        assert result is not None
        assert result["errorCode"] == "INVALID_INPUT"

    def test_validate_order_update_invalid_payment_method(self) -> None:
        """Test that invalid payment method returns error."""
        updates = {"paymentMethod": "BITCOIN"}

        result = validate_order_update(updates)

        assert result is not None
        assert result["errorCode"] == "INVALID_INPUT"

    def test_validate_order_update_valid_payment_methods(self) -> None:
        """Test all valid payment methods."""
        for method in ["CASH", "CHECK", "CREDIT_CARD", "ONLINE"]:
            updates = {"paymentMethod": method}
            result = validate_order_update(updates)
            assert result is None, f"Payment method {method} should be valid"

    def test_validate_order_update_invalid_address(self) -> None:
        """Test that invalid address returns error."""
        updates = {
            "customerAddress": {
                "street": "123 Main St",
                # Missing city, state, zip
            }
        }

        result = validate_order_update(updates)

        assert result is not None
        assert result["errorCode"] == "INVALID_INPUT"

    def test_validate_order_update_no_updates(self) -> None:
        """Test that empty updates dict returns None."""
        result = validate_order_update({})

        assert result is None
