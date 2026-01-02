"""
Input validation utilities.

Validates customer information, phone numbers, addresses, etc.
"""

import re
from typing import Any, Dict, Optional

from .errors import AppError, ErrorCode

# US phone number pattern: 10 digits with optional formatting
PHONE_PATTERN = re.compile(r"^(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})$")


def normalize_phone(phone: str) -> str:
    """
    Normalize US phone number to E.164 format (+1XXXXXXXXXX).

    Args:
        phone: Phone number with various formatting

    Returns:
        Normalized phone number

    Raises:
        AppError: If phone number is invalid
    """
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
        address: Address dictionary with street, city, state, zip

    Raises:
        AppError: If address is missing required fields
    """
    required_fields = ["street", "city", "state", "zip"]
    missing_fields = [field for field in required_fields if not address.get(field)]

    if missing_fields:
        raise AppError(
            ErrorCode.INVALID_ADDRESS,
            "Address is missing required fields",
            {"missingFields": missing_fields},
        )

    # Validate zip code (5 or 9 digits)
    zip_code = str(address.get("zip", "")).strip()
    if not re.match(r"^\d{5}(-\d{4})?$", zip_code):
        raise AppError(ErrorCode.INVALID_ADDRESS, "ZIP code must be 5 or 9 digits", {"zip": zip_code})


def validate_customer_input(customer: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate customer information for orders.

    Requirements:
    - Name is required
    - At least one of phone or address is required
    - If address provided, all fields must be present
    - Phone must be valid US format

    Args:
        customer: Customer dictionary

    Returns:
        Validated and normalized customer data

    Raises:
        AppError: If validation fails
    """
    # Name is required
    if not customer.get("name", "").strip():
        raise AppError(ErrorCode.INVALID_INPUT, "Customer name is required")

    # At least one contact method required
    has_phone = bool(customer.get("phone"))
    has_address = bool(customer.get("address"))

    if not has_phone and not has_address:
        raise AppError(
            ErrorCode.INVALID_INPUT,
            "Customer must have at least one contact method (phone or address)",
        )

    # Normalize and validate phone if provided
    validated_customer = {"name": customer["name"].strip()}

    if has_phone:
        validated_customer["phone"] = normalize_phone(customer["phone"])

    # Validate address if provided
    if has_address:
        validate_address(customer["address"])
        validated_customer["address"] = customer["address"]

    return validated_customer


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


def _validate_campaign_name(updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate campaign name if provided."""
    from .errors import create_error_response

    if "name" not in updates:
        return None
    if not updates["name"] or not updates["name"].strip():
        return create_error_response("INVALID_INPUT", "Campaign name cannot be empty")
    return None


def _validate_campaign_start_date(updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate start date if provided."""
    from .errors import create_error_response

    if "startDate" not in updates:
        return None
    if not updates["startDate"]:
        return create_error_response("INVALID_INPUT", "Start date cannot be empty")
    return None


def _validate_campaign_date_order(updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate endDate is after startDate if both provided."""
    from .errors import create_error_response

    if "startDate" not in updates or "endDate" not in updates:
        return None
    if not updates["endDate"]:
        return None
    if updates["endDate"] < updates["startDate"]:
        return create_error_response("INVALID_INPUT", "End date must be after start date")
    return None


def validate_campaign_update(updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Validate campaign update parameters.

    Args:
        updates: Dictionary of fields to update

    Returns:
        Error response if validation fails, None if valid
    """
    validators = [
        _validate_campaign_name,
        _validate_campaign_start_date,
        _validate_campaign_date_order,
    ]
    for validator in validators:
        error = validator(updates)
        if error:
            return error
    return None


def _validate_order_customer_name(updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate customer name if provided."""
    from .errors import create_error_response

    if "customerName" not in updates:
        return None
    if not updates["customerName"] or not updates["customerName"].strip():
        return create_error_response("INVALID_INPUT", "Customer name cannot be empty")
    return None


def _validate_order_customer_phone(updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate phone format if provided."""
    from .errors import create_error_response

    if "customerPhone" not in updates or not updates["customerPhone"]:
        return None
    try:
        normalize_phone(updates["customerPhone"])
    except AppError as e:
        return create_error_response("INVALID_INPUT", str(e))
    return None


def _validate_order_customer_address(updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate address if provided."""
    from .errors import create_error_response

    if "customerAddress" not in updates or not updates["customerAddress"]:
        return None
    try:
        validate_address(updates["customerAddress"])
    except AppError as e:
        return create_error_response("INVALID_INPUT", str(e))
    return None


def _is_valid_quantity(item: Dict[str, Any]) -> bool:
    """Check if line item has a valid positive quantity."""
    if "quantity" not in item:
        return False
    quantity = item["quantity"]
    if not isinstance(quantity, (int, float)):
        return False
    return quantity > 0


def _validate_single_line_item(item: Any) -> Optional[Dict[str, Any]]:
    """Validate a single line item."""
    from .errors import create_error_response

    if not isinstance(item, dict):
        return create_error_response("INVALID_INPUT", "Each line item must be an object")
    if "productId" not in item or not item["productId"]:
        return create_error_response("INVALID_INPUT", "Each line item must have a productId")
    if not _is_valid_quantity(item):
        return create_error_response("INVALID_INPUT", "Each line item must have a positive quantity")
    if "pricePerUnit" in item and not isinstance(item["pricePerUnit"], (int, float)):
        return create_error_response("INVALID_INPUT", "Price per unit must be a number")
    return None


def _validate_order_line_items(updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate lineItems if provided."""
    from .errors import create_error_response

    if "lineItems" not in updates:
        return None
    if not isinstance(updates["lineItems"], list):
        return create_error_response("INVALID_INPUT", "Line items must be an array")
    if not updates["lineItems"]:
        return create_error_response("INVALID_INPUT", "Order must have at least one line item")
    for item in updates["lineItems"]:
        error = _validate_single_line_item(item)
        if error:
            return error
    return None


def _validate_order_payment_method(updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate payment method if provided."""
    from .errors import create_error_response

    if "paymentMethod" not in updates:
        return None
    valid_methods = ["CASH", "CHECK", "CREDIT_CARD", "ONLINE"]
    if updates["paymentMethod"] not in valid_methods:
        return create_error_response("INVALID_INPUT", f"Payment method must be one of: {', '.join(valid_methods)}")
    return None


def validate_order_update(updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Validate order update parameters.

    Args:
        updates: Dictionary of fields to update

    Returns:
        Error response if validation fails, None if valid
    """
    validators = [
        _validate_order_customer_name,
        _validate_order_customer_phone,
        _validate_order_customer_address,
        _validate_order_line_items,
        _validate_order_payment_method,
    ]
    for validator in validators:
        error = validator(updates)
        if error:
            return error
    return None
