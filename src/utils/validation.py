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


def validate_campaign_update(updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Validate campaigngn update parameters.

    Args:
        updates: Dictionary of fields to update

    Returns:
        Error response if validation fails, None if valid
    """
    from .errors import create_error_response

    # Validate name if provided
    if "name" in updates:
        if not updates["name"] or not updates["name"].strip():
            return create_error_response("INVALID_INPUT", "Campaign name cannot be empty")

    # Validate dates if provided
    if "startDate" in updates:
        if not updates["startDate"]:
            return create_error_response("INVALID_INPUT", "Start date cannot be empty")

    # Validate endDate is after startDate if both provided
    if "startDate" in updates and "endDate" in updates and updates["endDate"]:
        if updates["endDate"] < updates["startDate"]:
            return create_error_response("INVALID_INPUT", "End date must be after start date")

    return None


def validate_order_update(updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Validate order update parameters.

    Args:
        updates: Dictionary of fields to update

    Returns:
        Error response if validation fails, None if valid
    """
    from .errors import create_error_response

    # Validate customer name if provided
    if "customerName" in updates:
        if not updates["customerName"] or not updates["customerName"].strip():
            return create_error_response("INVALID_INPUT", "Customer name cannot be empty")

    # Validate phone format if provided
    if "customerPhone" in updates and updates["customerPhone"]:
        try:
            normalize_phone(updates["customerPhone"])
        except AppError as e:
            return create_error_response("INVALID_INPUT", str(e))

    # Validate address if provided
    if "customerAddress" in updates and updates["customerAddress"]:
        try:
            validate_address(updates["customerAddress"])
        except AppError as e:
            return create_error_response("INVALID_INPUT", str(e))

    # Validate lineItems if provided
    if "lineItems" in updates:
        if not isinstance(updates["lineItems"], list):
            return create_error_response("INVALID_INPUT", "Line items must be an array")

        if not updates["lineItems"]:
            return create_error_response("INVALID_INPUT", "Order must have at least one line item")

        for item in updates["lineItems"]:
            if not isinstance(item, dict):
                return create_error_response("INVALID_INPUT", "Each line item must be an object")

            if "productId" not in item or not item["productId"]:
                return create_error_response("INVALID_INPUT", "Each line item must have a productId")

            if "quantity" not in item or not isinstance(item["quantity"], (int, float)) or item["quantity"] <= 0:
                return create_error_response("INVALID_INPUT", "Each line item must have a positive quantity")

            if "pricePerUnit" in item and not isinstance(item["pricePerUnit"], (int, float)):
                return create_error_response("INVALID_INPUT", "Price per unit must be a number")

    # Validate payment method if provided
    if "paymentMethod" in updates:
        valid_methods = ["CASH", "CHECK", "CREDIT_CARD", "ONLINE"]
        if updates["paymentMethod"] not in valid_methods:
            return create_error_response("INVALID_INPUT", f"Payment method must be one of: {', '.join(valid_methods)}")

    return None
