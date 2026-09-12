"""Tests for validation utilities."""

import pytest

from src.utils.errors import AppError, ErrorCode
from src.utils.validation import (
    MAX_SELLER_NAME_LENGTH,
    VALID_UNIT_TYPES,
    CreateCampaignInput,
    CreateSellerProfileInput,
    UpdateCampaignInput,
    UpdateSellerProfileInput,
    _extract_field,
    normalize_phone,
    parse_iso_date,
    validate_address,
    validate_date_range,
    validate_invite_code,
    validate_required_fields,
    validate_seller_name,
    validate_unit_fields,
    validate_unit_number,
    validate_unit_type,
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


class TestValidateSellerName:
    """Tests for validate_seller_name function."""

    def test_valid_seller_name(self) -> None:
        """Test that a valid seller name is returned trimmed."""
        assert validate_seller_name("  Scout Name  ") == "Scout Name"

    def test_none_seller_name_raises_error(self) -> None:
        """Test that None raises AppError."""
        with pytest.raises(AppError) as exc_info:
            validate_seller_name(None)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "sellerName is required" in exc_info.value.message

    def test_empty_seller_name_raises_error(self) -> None:
        """Test that empty or whitespace-only seller name raises AppError."""
        with pytest.raises(AppError) as exc_info:
            validate_seller_name("")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "sellerName is required" in exc_info.value.message

        with pytest.raises(AppError) as exc_info:
            validate_seller_name("   ")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "sellerName is required" in exc_info.value.message

    def test_max_length_seller_name(self) -> None:
        """Test that seller name at maximum length is accepted."""
        name = "a" * MAX_SELLER_NAME_LENGTH
        assert validate_seller_name(name) == name

    def test_seller_name_exceeding_max_length_raises_error(self) -> None:
        """Test that seller name exceeding max length raises AppError."""
        name = "a" * (MAX_SELLER_NAME_LENGTH + 1)
        with pytest.raises(AppError) as exc_info:
            validate_seller_name(name)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert f"must not exceed {MAX_SELLER_NAME_LENGTH} characters" in exc_info.value.message


class TestValidateUnitType:
    """Tests for validate_unit_type function."""

    def test_valid_unit_types(self) -> None:
        """Test all valid unit types are accepted."""
        for unit_type in sorted(VALID_UNIT_TYPES):
            assert validate_unit_type(unit_type) == unit_type

    def test_none_unit_type(self) -> None:
        """Test that None returns None."""
        assert validate_unit_type(None) is None

    def test_non_string_unit_type_raises_error(self) -> None:
        """Test that non-string unit type raises AppError."""
        with pytest.raises(AppError) as exc_info:
            validate_unit_type(123)  # type: ignore[arg-type]
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "unitType must be a string" in exc_info.value.message

    def test_invalid_unit_type_raises_error(self) -> None:
        """Test that invalid unit type raises AppError."""
        with pytest.raises(AppError) as exc_info:
            validate_unit_type("InvalidType")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "unitType must be one of:" in exc_info.value.message


class TestValidateUnitFields:
    """Tests for validate_unit_fields function."""

    def test_absent_unit_type_returns_none(self) -> None:
        """Test that absent unit type returns None."""
        assert validate_unit_fields(None, 123, "City", "ST") is None
        assert validate_unit_fields("", 123, "City", "ST") is None

    def test_missing_unit_number_raises_error(self) -> None:
        """Test that missing unit number raises error."""
        with pytest.raises(AppError) as exc_info:
            validate_unit_fields("Pack", None, "City", "ST")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_missing_city_raises_error(self) -> None:
        """Test that missing city raises error."""
        with pytest.raises(AppError) as exc_info:
            validate_unit_fields("Pack", 123, "", "ST")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "city is required" in exc_info.value.message

    def test_missing_state_raises_error(self) -> None:
        """Test that missing state raises error."""
        with pytest.raises(AppError) as exc_info:
            validate_unit_fields("Pack", 123, "City", "")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "state is required" in exc_info.value.message

    def test_valid_unit_fields(self) -> None:
        """Test valid unit fields return tuple."""
        result = validate_unit_fields("Pack", 123, "Springfield", "IL")
        assert result == ("Pack", 123, "Springfield", "IL")


class TestValidateRequiredFields:
    """Tests for validate_required_fields function."""

    def test_all_fields_present(self) -> None:
        """Test validation passes when all required fields are present and non-empty."""
        data = {"name": "Test", "id": 123, "items": ["a"]}
        validate_required_fields(data, ["name", "id", "items"])

    def test_missing_field_raises_error(self) -> None:
        """Test that missing field raises AppError."""
        with pytest.raises(AppError) as exc_info:
            validate_required_fields({"name": "Test"}, ["name", "missing"])
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "missing is required" in exc_info.value.message

    def test_empty_field_raises_error(self) -> None:
        """Test that None, empty string, or empty list raises AppError."""
        with pytest.raises(AppError) as exc_info:
            validate_required_fields({"name": None}, ["name"])
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "name is required" in exc_info.value.message

        with pytest.raises(AppError) as exc_info:
            validate_required_fields({"name": ""}, ["name"])
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

        with pytest.raises(AppError) as exc_info:
            validate_required_fields({"name": []}, ["name"])
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT


class TestParseIsoDateAndValidateDateRange:
    """Tests for parse_iso_date and validate_date_range."""

    def test_parse_iso_date_with_z(self) -> None:
        """Test parsing ISO date string ending in Z."""
        dt = parse_iso_date("2025-01-01T00:00:00Z")
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.tzinfo is not None

    def test_parse_iso_date_with_offset(self) -> None:
        """Test parsing ISO date string with explicit offset."""
        dt = parse_iso_date("2025-01-01T00:00:00+00:00")
        assert dt.year == 2025
        assert dt.month == 1

    def test_parse_iso_date_naive(self) -> None:
        """Test parsing naive ISO date string normalized to UTC."""
        dt = parse_iso_date("2025-01-01T12:00:00")
        assert dt.year == 2025
        assert dt.tzinfo is not None

    def test_parse_iso_date_non_string(self) -> None:
        """Test that non-string date raises AppError."""
        with pytest.raises(AppError) as exc_info:
            parse_iso_date(123)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Invalid date format for startDate or endDate" in exc_info.value.message

    def test_parse_iso_date_empty_string(self) -> None:
        """Test that empty or whitespace date raises AppError."""
        with pytest.raises(AppError) as exc_info:
            parse_iso_date("   ")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Invalid date format for startDate or endDate" in exc_info.value.message

    def test_parse_iso_date_invalid_format(self) -> None:
        """Test that malformed date string raises AppError."""
        with pytest.raises(AppError) as exc_info:
            parse_iso_date("not-a-date")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Invalid date format for startDate or endDate" in exc_info.value.message

    def test_validate_date_range_both_none(self) -> None:
        """Test date range with both dates None passes."""
        validate_date_range(None, None)

    def test_validate_date_range_only_start(self) -> None:
        """Test date range with only start date passes."""
        validate_date_range("2025-01-01T00:00:00Z", None)

    def test_validate_date_range_only_end(self) -> None:
        """Test date range with only end date passes."""
        validate_date_range(None, "2025-12-31T23:59:59Z")

    def test_validate_date_range_valid_order(self) -> None:
        """Test date range with endDate after startDate passes."""
        validate_date_range("2025-01-01T00:00:00Z", "2025-12-31T23:59:59Z")

    def test_validate_date_range_equal_dates_raises_error(self) -> None:
        """Test date range with endDate equal to startDate raises AppError."""
        with pytest.raises(AppError) as exc_info:
            validate_date_range("2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "endDate must be after startDate" in exc_info.value.message

    def test_validate_date_range_inverted_dates_raises_error(self) -> None:
        """Test date range with endDate before startDate raises AppError."""
        with pytest.raises(AppError) as exc_info:
            validate_date_range("2025-12-31T00:00:00Z", "2025-01-01T00:00:00Z")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "endDate must be after startDate" in exc_info.value.message


class TestExtractField:
    """Tests for _extract_field utility."""

    def test_extract_first_match(self) -> None:
        """Test extracting first present key."""
        data = {"camelCase": 1, "snake_case": 2}
        assert _extract_field(data, "camelCase", "snake_case") == 1

    def test_extract_second_match(self) -> None:
        """Test extracting second key when first is absent."""
        data = {"snake_case": 2}
        assert _extract_field(data, "camelCase", "snake_case") == 2

    def test_extract_none_match(self) -> None:
        """Test extracting when no keys match."""
        data = {"other": 3}
        assert _extract_field(data, "camelCase", "snake_case") is None


class TestCreateSellerProfileInput:
    """Tests for CreateSellerProfileInput."""

    def test_minimal_valid_initialization(self) -> None:
        """Test creating model with only required seller_name."""
        model = CreateSellerProfileInput(seller_name="  Scout Name  ")
        assert model.seller_name == "Scout Name"
        assert model.unit_type is None
        assert model.unit_number is None

    def test_full_valid_initialization(self) -> None:
        """Test creating model with all fields."""
        model = CreateSellerProfileInput(seller_name="Scout", unit_type="Pack", unit_number=42)
        assert model.seller_name == "Scout"
        assert model.unit_type == "Pack"
        assert model.unit_number == 42

    def test_invalid_seller_name_raises(self) -> None:
        """Test that invalid seller_name raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateSellerProfileInput(seller_name="")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "sellerName is required" in exc_info.value.message

    def test_invalid_unit_type_raises(self) -> None:
        """Test that invalid unit_type raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateSellerProfileInput(seller_name="Scout", unit_type="InvalidType")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "unitType must be one of:" in exc_info.value.message

    def test_invalid_unit_number_raises(self) -> None:
        """Test that invalid unit_number raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateSellerProfileInput(seller_name="Scout", unit_type="Pack", unit_number=-1)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "unitNumber must be a positive integer" in exc_info.value.message

    def test_from_dict_camel_case(self) -> None:
        """Test from_dict with camelCase keys."""
        data = {"sellerName": "Scout", "unitType": "Troop", "unitNumber": 101}
        model = CreateSellerProfileInput.from_dict(data)
        assert model.seller_name == "Scout"
        assert model.unit_type == "Troop"
        assert model.unit_number == 101

    def test_from_dict_snake_case(self) -> None:
        """Test from_dict with snake_case keys."""
        data = {"seller_name": "Scout", "unit_type": "Troop", "unit_number": 101}
        model = CreateSellerProfileInput.from_dict(data)
        assert model.seller_name == "Scout"
        assert model.unit_type == "Troop"
        assert model.unit_number == 101

    def test_from_dict_non_dict_raises(self) -> None:
        """Test from_dict with non-dict input raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateSellerProfileInput.from_dict("not-a-dict")  # type: ignore[arg-type]
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Input must be an object" in exc_info.value.message

    def test_to_dict_camel_case(self) -> None:
        """Test to_dict with camelCase formatting."""
        model = CreateSellerProfileInput(seller_name="Scout", unit_type="Pack")
        d = model.to_dict()
        assert d == {"sellerName": "Scout", "unitType": "Pack", "unitNumber": None}

    def test_to_dict_snake_case(self) -> None:
        """Test to_dict with snake_case formatting."""
        model = CreateSellerProfileInput(seller_name="Scout", unit_type="Pack")
        d = model.to_dict(camel_case=False)
        assert d == {"seller_name": "Scout", "unit_type": "Pack", "unit_number": None}

    def test_to_dict_exclude_none(self) -> None:
        """Test to_dict with exclude_none=True."""
        model = CreateSellerProfileInput(seller_name="Scout", unit_type="Pack")
        d = model.to_dict(exclude_none=True)
        assert d == {"sellerName": "Scout", "unitType": "Pack"}


class TestUpdateSellerProfileInput:
    """Tests for UpdateSellerProfileInput."""

    def test_valid_initialization(self) -> None:
        """Test valid update profile initialization."""
        model = UpdateSellerProfileInput(
            profile_id="PROFILE#123", seller_name="New Name", unit_type="Crew", unit_number=5
        )
        assert model.profile_id == "PROFILE#123"
        assert model.seller_name == "New Name"
        assert model.unit_type == "Crew"
        assert model.unit_number == 5

    def test_missing_profile_id_raises(self) -> None:
        """Test that missing profile_id raises AppError."""
        with pytest.raises(AppError) as exc_info:
            UpdateSellerProfileInput(profile_id="   ", seller_name="Name")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "profileId is required" in exc_info.value.message

    def test_invalid_seller_name_raises(self) -> None:
        """Test that empty seller_name raises AppError."""
        with pytest.raises(AppError) as exc_info:
            UpdateSellerProfileInput(profile_id="PROFILE#123", seller_name="")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "sellerName is required" in exc_info.value.message

    def test_invalid_unit_type_raises(self) -> None:
        """Test that invalid unit_type raises AppError."""
        with pytest.raises(AppError) as exc_info:
            UpdateSellerProfileInput(profile_id="PROFILE#123", seller_name="Name", unit_type="Bad")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_invalid_unit_number_raises(self) -> None:
        """Test that invalid unit_number raises AppError."""
        with pytest.raises(AppError) as exc_info:
            UpdateSellerProfileInput(profile_id="PROFILE#123", seller_name="Name", unit_number=0)
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT

    def test_from_dict_camel_and_snake(self) -> None:
        """Test from_dict with camelCase and snake_case."""
        camel = UpdateSellerProfileInput.from_dict({"profileId": "p-1", "sellerName": "Scout"})
        assert camel.profile_id == "p-1"
        assert camel.seller_name == "Scout"

        snake = UpdateSellerProfileInput.from_dict({"profile_id": "p-2", "seller_name": "Scout 2"})
        assert snake.profile_id == "p-2"
        assert snake.seller_name == "Scout 2"

    def test_from_dict_non_dict_raises(self) -> None:
        """Test from_dict with non-dict raises AppError."""
        with pytest.raises(AppError) as exc_info:
            UpdateSellerProfileInput.from_dict(123)  # type: ignore[arg-type]
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Input must be an object" in exc_info.value.message

    def test_to_dict_variants(self) -> None:
        """Test to_dict camel/snake and exclude_none variants."""
        model = UpdateSellerProfileInput(profile_id="p-1", seller_name="Name")
        assert model.to_dict()["profileId"] == "p-1"
        assert "unitType" in model.to_dict()
        assert "unitType" not in model.to_dict(exclude_none=True)
        assert model.to_dict(camel_case=False)["profile_id"] == "p-1"


class TestCreateCampaignInput:
    """Tests for CreateCampaignInput."""

    def test_standalone_valid_initialization(self) -> None:
        """Test standalone campaign creation with required fields."""
        model = CreateCampaignInput(
            profile_id="PROFILE#1",
            campaign_name="  Fall Sale  ",
            campaign_year=2025,
            catalog_id="CATALOG#1",
        )
        assert model.profile_id == "PROFILE#1"
        assert model.campaign_name == "Fall Sale"
        assert model.campaign_year == 2025
        assert model.catalog_id == "CATALOG#1"

    def test_missing_profile_id_raises(self) -> None:
        """Test missing profile_id raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateCampaignInput(
                profile_id="",
                campaign_name="Sale",
                campaign_year=2025,
                catalog_id="CATALOG#1",
            )
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "profileId is required" in exc_info.value.message

    def test_standalone_missing_name_raises(self) -> None:
        """Test standalone campaign missing campaign_name raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateCampaignInput(
                profile_id="PROFILE#1",
                campaign_name="   ",
                campaign_year=2025,
                catalog_id="CATALOG#1",
            )
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "campaign_name is required" in exc_info.value.message

    def test_standalone_missing_year_raises(self) -> None:
        """Test standalone campaign missing campaign_year raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateCampaignInput(
                profile_id="PROFILE#1",
                campaign_name="Sale",
                campaign_year=None,
                catalog_id="CATALOG#1",
            )
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "campaign_year is required" in exc_info.value.message

    def test_standalone_invalid_year_raises(self) -> None:
        """Test standalone campaign with invalid campaign_year raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateCampaignInput(
                profile_id="PROFILE#1",
                campaign_name="Sale",
                campaign_year="not-a-year",  # type: ignore[arg-type]
                catalog_id="CATALOG#1",
            )
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "campaign_year must be a valid integer" in exc_info.value.message

        with pytest.raises(AppError) as exc_info:
            CreateCampaignInput(
                profile_id="PROFILE#1",
                campaign_name="Sale",
                campaign_year=2025.5,  # type: ignore[arg-type]
                catalog_id="CATALOG#1",
            )
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "campaign_year must be a valid integer" in exc_info.value.message

    def test_standalone_missing_catalog_raises(self) -> None:
        """Test standalone campaign missing catalog_id raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateCampaignInput(
                profile_id="PROFILE#1",
                campaign_name="Sale",
                campaign_year=2025,
                catalog_id="",
            )
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "catalog_id is required" in exc_info.value.message

    def test_shared_campaign_code_allows_omitted_fields(self) -> None:
        """Test shared campaign creation allows omitting name, year, catalog."""
        model = CreateCampaignInput(
            profile_id="PROFILE#1",
            shared_campaign_code="CODE123",
        )
        assert model.profile_id == "PROFILE#1"
        assert model.shared_campaign_code == "CODE123"
        assert model.campaign_name is None
        assert model.campaign_year is None
        assert model.catalog_id is None

    def test_shared_campaign_code_with_optional_fields(self) -> None:
        """Test shared campaign creation with optional name, year, catalog."""
        model = CreateCampaignInput(
            profile_id="PROFILE#1",
            shared_campaign_code="CODE123",
            campaign_name="  My Sale  ",
            campaign_year=2025,
            catalog_id="  CATALOG#1  ",
        )
        assert model.campaign_name == "My Sale"
        assert model.campaign_year == 2025
        assert model.catalog_id == "CATALOG#1"

    def test_shared_campaign_code_invalid_year_raises(self) -> None:
        """Test shared campaign creation with invalid year raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateCampaignInput(
                profile_id="PROFILE#1",
                shared_campaign_code="CODE123",
                campaign_year="invalid",  # type: ignore[arg-type]
            )
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "campaign_year must be a valid integer" in exc_info.value.message

    def test_valid_date_range(self) -> None:
        """Test campaign creation with valid date range."""
        model = CreateCampaignInput(
            profile_id="PROFILE#1",
            campaign_name="Sale",
            campaign_year=2025,
            catalog_id="CATALOG#1",
            start_date="2025-01-01T00:00:00Z",
            end_date="2025-12-31T23:59:59Z",
        )
        assert model.start_date == "2025-01-01T00:00:00Z"
        assert model.end_date == "2025-12-31T23:59:59Z"

    def test_invalid_date_format_raises(self) -> None:
        """Test campaign creation with invalid date format raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateCampaignInput(
                profile_id="PROFILE#1",
                campaign_name="Sale",
                campaign_year=2025,
                catalog_id="CATALOG#1",
                start_date="bad-date",
            )
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Invalid date format for startDate or endDate" in exc_info.value.message

    def test_end_date_before_start_date_raises(self) -> None:
        """Test campaign creation with end date before start date raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateCampaignInput(
                profile_id="PROFILE#1",
                campaign_name="Sale",
                campaign_year=2025,
                catalog_id="CATALOG#1",
                start_date="2025-12-31T00:00:00Z",
                end_date="2025-01-01T00:00:00Z",
            )
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "endDate must be after startDate" in exc_info.value.message

    def test_valid_unit_fields(self) -> None:
        """Test campaign creation with valid unit fields."""
        model = CreateCampaignInput(
            profile_id="PROFILE#1",
            campaign_name="Sale",
            campaign_year=2025,
            catalog_id="CATALOG#1",
            unit_type="Pack",
            unit_number=42,
            city="Springfield",
            state="IL",
        )
        assert model.unit_type == "Pack"
        assert model.unit_number == 42
        assert model.city == "Springfield"
        assert model.state == "IL"
        key = model.build_unit_campaign_key()
        assert key == "Pack#42#Springfield#IL#Sale#2025"

    def test_unit_type_missing_unit_number_raises(self) -> None:
        """Test unit_type provided without unit_number raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateCampaignInput(
                profile_id="PROFILE#1",
                campaign_name="Sale",
                campaign_year=2025,
                catalog_id="CATALOG#1",
                unit_type="Pack",
                city="Springfield",
                state="IL",
            )
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "unitNumber is required when unitType is provided" in exc_info.value.message

    def test_unit_type_missing_city_raises(self) -> None:
        """Test unit_type provided without city raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateCampaignInput(
                profile_id="PROFILE#1",
                campaign_name="Sale",
                campaign_year=2025,
                catalog_id="CATALOG#1",
                unit_type="Pack",
                unit_number=42,
                city="",
                state="IL",
            )
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "city is required when unitType is provided" in exc_info.value.message

    def test_unit_type_missing_state_raises(self) -> None:
        """Test unit_type provided without state raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateCampaignInput(
                profile_id="PROFILE#1",
                campaign_name="Sale",
                campaign_year=2025,
                catalog_id="CATALOG#1",
                unit_type="Pack",
                unit_number=42,
                city="Springfield",
                state="",
            )
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "state is required when unitType is provided" in exc_info.value.message

    def test_unit_fields_present_without_unit_type_raises(self) -> None:
        """Test unit fields present without unit_type raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateCampaignInput(
                profile_id="PROFILE#1",
                campaign_name="Sale",
                campaign_year=2025,
                catalog_id="CATALOG#1",
                unit_number=42,
            )
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "unitType is required when unit fields are present" in exc_info.value.message

    def test_build_unit_campaign_key_absent(self) -> None:
        """Test build_unit_campaign_key returns None when unit fields are absent."""
        model = CreateCampaignInput(
            profile_id="PROFILE#1",
            campaign_name="Sale",
            campaign_year=2025,
            catalog_id="CATALOG#1",
        )
        assert model.build_unit_campaign_key() is None

    def test_from_dict_non_dict_raises(self) -> None:
        """Test from_dict with non-dict raises AppError."""
        with pytest.raises(AppError) as exc_info:
            CreateCampaignInput.from_dict("invalid")  # type: ignore[arg-type]
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Input must be an object" in exc_info.value.message

    def test_from_dict_and_to_dict_roundtrip(self) -> None:
        """Test roundtrip serialization between dict and model."""
        payload = {
            "profileId": "p-1",
            "campaignName": "Sale",
            "campaignYear": 2025,
            "catalogId": "c-1",
            "startDate": "2025-01-01T00:00:00Z",
            "endDate": "2025-12-31T23:59:59Z",
            "unitType": "Troop",
            "unitNumber": 10,
            "city": "Dallas",
            "state": "TX",
            "sharedCampaignCode": "S-1",
            "shareWithCreator": True,
        }
        model = CreateCampaignInput.from_dict(payload)
        out = model.to_dict()
        assert out == payload

        snake_out = model.to_dict(camel_case=False)
        assert snake_out["profile_id"] == "p-1"
        assert snake_out["campaign_name"] == "Sale"
        assert snake_out["shared_campaign_code"] == "S-1"

        sparse_model = CreateCampaignInput.from_dict({"profile_id": "p-2", "shared_campaign_code": "S-2"})
        sparse_out = sparse_model.to_dict(exclude_none=True)
        assert sparse_out == {"profileId": "p-2", "sharedCampaignCode": "S-2"}


class TestUpdateCampaignInput:
    """Tests for UpdateCampaignInput."""

    def test_minimal_valid_initialization(self) -> None:
        """Test minimal valid campaign update."""
        model = UpdateCampaignInput(campaign_id="CAMPAIGN#123")
        assert model.campaign_id == "CAMPAIGN#123"
        assert not model.has_unit_update()

    def test_missing_campaign_id_raises(self) -> None:
        """Test missing campaign_id raises AppError."""
        with pytest.raises(AppError) as exc_info:
            UpdateCampaignInput(campaign_id="   ")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "campaignId is required" in exc_info.value.message

    def test_empty_campaign_name_raises(self) -> None:
        """Test empty campaignName raises AppError."""
        with pytest.raises(AppError) as exc_info:
            UpdateCampaignInput(campaign_id="c-1", campaign_name="   ")
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "campaignName cannot be empty" in exc_info.value.message

    def test_invalid_campaign_year_raises(self) -> None:
        """Test non-integer campaignYear raises AppError."""
        with pytest.raises(AppError) as exc_info:
            UpdateCampaignInput(campaign_id="c-1", campaign_year="invalid")  # type: ignore[arg-type]
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "campaign_year must be a valid integer" in exc_info.value.message

        with pytest.raises(AppError) as exc_info:
            UpdateCampaignInput(campaign_id="c-1", campaign_year=2026.5)  # type: ignore[arg-type]
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "campaign_year must be a valid integer" in exc_info.value.message

    def test_valid_campaign_year_parsing(self) -> None:
        """Test valid campaignYear is parsed to int."""
        model = UpdateCampaignInput(campaign_id="c-1", campaign_year=2026.0)  # type: ignore[arg-type]
        assert model.campaign_year == 2026

    def test_invalid_is_active_raises(self) -> None:
        """Test non-boolean isActive raises AppError."""
        with pytest.raises(AppError) as exc_info:
            UpdateCampaignInput(campaign_id="c-1", is_active="true")  # type: ignore[arg-type]
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "isActive must be a boolean" in exc_info.value.message

    def test_valid_optional_fields(self) -> None:
        """Test updating optional catalogId, isActive, unitType, unitNumber."""
        model = UpdateCampaignInput(
            campaign_id="c-1",
            campaign_name="  Updated Sale  ",
            catalog_id="  CATALOG#2  ",
            is_active=False,
            unit_type="Troop",
            unit_number=15,
        )
        assert model.campaign_name == "Updated Sale"
        assert model.catalog_id == "CATALOG#2"
        assert model.is_active is False
        assert model.unit_type == "Troop"
        assert model.unit_number == 15
        assert model.has_unit_update()

    def test_validate_unit_update_no_unit_fields(self) -> None:
        """Test validate_unit_update no-ops when no unit update is present."""
        model = UpdateCampaignInput(campaign_id="c-1", campaign_name="Sale")
        model.validate_unit_update({"unitType": "Pack"})

    def test_validate_unit_update_shared_campaign_blocked(self) -> None:
        """Test unit updates are blocked for shared campaigns."""
        model = UpdateCampaignInput(campaign_id="c-1", unit_number=10)
        with pytest.raises(AppError) as exc_info:
            model.validate_unit_update({"sharedCampaignCode": "SHARED-1", "unitType": "Pack"})
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Unit information cannot be changed" in exc_info.value.message

    def test_validate_unit_update_effective_fields_complete(self) -> None:
        """Test unit update merged with existing campaign fields."""
        existing = {"unitType": "Pack", "unitNumber": 5, "city": "Chicago", "state": "IL"}
        model = UpdateCampaignInput(campaign_id="c-1", unit_number=10)
        model.validate_unit_update(existing)

    def test_validate_unit_update_missing_unit_number_raises(self) -> None:
        """Test unit update with unit_type but missing unit_number raises AppError."""
        model = UpdateCampaignInput(campaign_id="c-1", unit_type="Pack", city="Chicago", state="IL")
        with pytest.raises(AppError) as exc_info:
            model.validate_unit_update()
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "unitNumber is required when unitType is provided" in exc_info.value.message

    def test_validate_unit_update_missing_city_raises(self) -> None:
        """Test unit update with unit_type but missing city raises AppError."""
        model = UpdateCampaignInput(campaign_id="c-1", unit_type="Pack", unit_number=10, state="IL")
        with pytest.raises(AppError) as exc_info:
            model.validate_unit_update()
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "city is required when unitType is provided" in exc_info.value.message

    def test_validate_unit_update_missing_state_raises(self) -> None:
        """Test unit update with unit_type but missing state raises AppError."""
        model = UpdateCampaignInput(campaign_id="c-1", unit_type="Pack", unit_number=10, city="Chicago")
        with pytest.raises(AppError) as exc_info:
            model.validate_unit_update()
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "state is required when unitType is provided" in exc_info.value.message

    def test_validate_unit_update_unit_fields_without_type_raises(self) -> None:
        """Test unit fields present without unit_type raises AppError."""
        model = UpdateCampaignInput(campaign_id="c-1", city="Chicago")
        with pytest.raises(AppError) as exc_info:
            model.validate_unit_update()
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "unitType is required when unit fields are present" in exc_info.value.message

    def test_validate_effective_unit_fields_all_none_passes(self) -> None:
        """Test effective unit fields when all are None."""
        model = UpdateCampaignInput(campaign_id="c-1")
        model._validate_effective_unit_fields(None, None, None, None)

    def test_from_dict_non_dict_raises(self) -> None:
        """Test from_dict with non-dict raises AppError."""
        with pytest.raises(AppError) as exc_info:
            UpdateCampaignInput.from_dict(["not-a-dict"])  # type: ignore[arg-type]
        assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
        assert "Input must be an object" in exc_info.value.message

    def test_from_dict_and_to_dict_roundtrip(self) -> None:
        """Test roundtrip serialization for UpdateCampaignInput."""
        payload = {
            "campaignId": "c-1",
            "campaignName": "Updated",
            "campaignYear": 2026,
            "catalogId": "cat-2",
            "startDate": "2026-01-01T00:00:00Z",
            "endDate": "2026-12-31T23:59:59Z",
            "isActive": True,
            "unitType": "Ship",
            "unitNumber": 7,
            "city": "Boston",
            "state": "MA",
        }
        model = UpdateCampaignInput.from_dict(payload)
        assert model.to_dict() == payload
        assert model.to_dict(camel_case=False)["campaign_id"] == "c-1"

        sparse = UpdateCampaignInput.from_dict({"campaign_id": "c-2"})
        assert sparse.to_dict(exclude_none=True) == {"campaignId": "c-2"}
