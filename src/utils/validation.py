"""
Input validation utilities.

Validates customer information, phone numbers, addresses, etc.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from .errors import AppError, ErrorCode

# US phone number pattern: 10 digits with optional formatting
PHONE_PATTERN = re.compile(r"^(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})$")

# Scout unit types supported by the application
VALID_UNIT_TYPES = {"Pack", "Troop", "Crew", "Ship", "Post"}

# Maximum allowed length for a seller profile name
MAX_SELLER_NAME_LENGTH = 100


def validate_unit_number(value: Any, required: bool = False) -> Optional[int]:
    """
    Validate and convert unit number to integer.

    Args:
        value: Value to validate (may be string, int, or None)
        required: Whether value is required

    Returns:
        Validated integer or None if not required and not provided

    Raises:
        AppError: If validation fails
    """
    if value is None or value == "":
        if required:
            raise AppError(ErrorCode.INVALID_INPUT, "unitNumber is required when unitType is provided")
        return None

    try:
        number = int(value)
        if number < 1:
            raise AppError(ErrorCode.INVALID_INPUT, "unitNumber must be a positive integer")
        return number
    except ValueError, TypeError:
        raise AppError(ErrorCode.INVALID_INPUT, "unitNumber must be a valid integer")


def validate_seller_name(name: Any) -> str:
    """
    Validate seller name length and non-emptiness.

    Args:
        name: Seller name value

    Returns:
        Trimmed seller name

    Raises:
        AppError: If name is missing, empty, or too long
    """
    if name is None:
        raise AppError(ErrorCode.INVALID_INPUT, "sellerName is required")

    cleaned = str(name).strip()
    if not cleaned:
        raise AppError(ErrorCode.INVALID_INPUT, "sellerName is required")
    if len(cleaned) > MAX_SELLER_NAME_LENGTH:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            f"sellerName must not exceed {MAX_SELLER_NAME_LENGTH} characters",
        )

    return cleaned


def validate_unit_type(unit_type: Optional[str]) -> Optional[str]:
    """
    Validate unit type against the supported enum.

    Args:
        unit_type: Unit type value (e.g., Pack, Troop)

    Returns:
        The unit type unchanged if valid, or None if not provided

    Raises:
        AppError: If unitType is not a supported value
    """
    if unit_type is None:
        return None

    if not isinstance(unit_type, str):
        raise AppError(ErrorCode.INVALID_INPUT, "unitType must be a string")

    if unit_type not in VALID_UNIT_TYPES:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            f"unitType must be one of: {', '.join(sorted(VALID_UNIT_TYPES))}",
        )

    return unit_type


def validate_unit_fields(
    unit_type: Optional[str],
    unit_number: Optional[int],
    city: Optional[str],
    state: Optional[str],
) -> Optional[Tuple[str, int, str, str]]:
    """
    Validate that all unit fields are present if any are provided.

    Args:
        unit_type: Scout unit type (Pack, Troop, Crew, Ship, Post)
        unit_number: Unit number
        city: City name
        state: State abbreviation

    Returns:
        Tuple of validated fields if all present, None if unitType is absent

    Raises:
        AppError: If unit_type is provided but other fields are missing
    """
    if not unit_type:
        return None

    validated_number = validate_unit_number(unit_number, required=True)
    assert validated_number is not None  # For type checker

    if not city:
        raise AppError(ErrorCode.INVALID_INPUT, "city is required when unitType is provided")
    if not state:
        raise AppError(ErrorCode.INVALID_INPUT, "state is required when unitType is provided")

    return (unit_type, validated_number, city, state)


def validate_required_fields(data: Dict[str, Any], required_fields: List[str]) -> None:
    """
    Validate that all required fields are present and non-empty.

    Args:
        data: Dictionary to validate
        required_fields: List of field names that must be present

    Raises:
        AppError: If any required field is missing or empty
    """
    for field in required_fields:
        if field not in data or data[field] in (None, "", []):
            raise AppError(ErrorCode.INVALID_INPUT, f"{field} is required")


def normalize_phone(phone: str) -> str:
    """
    Normalize US phone number to E.164 format (+1XXXXXXXXXX).

    Args:
        phone: Phone number with various formatting (string or coercible value).

    Returns:
        Normalized phone number

    Raises:
        AppError: If phone number is invalid
    """
    if not isinstance(phone, str):
        phone = str(phone)

    match = PHONE_PATTERN.match(phone.strip())

    if not match:
        raise AppError(
            ErrorCode.INVALID_PHONE,
            "Phone number must be a valid 10-digit US number",
            {"phone": phone},
        )

    # Extract digits and format as E.164
    area_code, prefix, line = match.groups()
    return f"+1{area_code}{prefix}{line}"


def validate_address(address: Dict[str, Any]) -> None:
    """
    Validate address has all required fields.

    Args:
        address: Address dictionary with street, city, state, zipCode

    Raises:
        AppError: If address is missing required fields
    """
    required_fields = ["street", "city", "state", "zipCode"]
    missing_fields = [field for field in required_fields if not address.get(field)]

    if missing_fields:
        raise AppError(
            ErrorCode.INVALID_ADDRESS,
            "Address is missing required fields",
            {"missingFields": missing_fields},
        )

    # Validate zip code (5 or 9 digits)
    zip_code = str(address.get("zipCode", "")).strip()
    if not re.match(r"^\d{5}(-\d{4})?$", zip_code):
        raise AppError(ErrorCode.INVALID_ADDRESS, "ZIP code must be 5 or 9 digits", {"zipCode": zip_code})


def validate_invite_code(invite_code: str) -> str:
    """
    Validate invite code format.

    Args:
        invite_code: Invite code to validate

    Returns:
        Uppercase invite code

    Raises:
        AppError: If invite code is invalid
    """
    code = invite_code.strip().upper()

    # Invite codes should be 8-12 alphanumeric characters
    if not re.match(r"^[A-Z0-9]{8,12}$", code):
        raise AppError(
            ErrorCode.INVALID_INPUT,
            "Invite code must be 8-12 alphanumeric characters",
            {"inviteCode": invite_code},
        )

    return code
