"""Lambda resolvers for Scout operations."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.dynamodb import tables
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
    from utils.validation import validate_seller_name, validate_unit_number, validate_unit_type
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.dynamodb import tables
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger
    from ..utils.validation import validate_seller_name, validate_unit_number, validate_unit_type

logger = get_logger(__name__)


def _build_profile_data(
    profile_id: str, owner_account_id_stored: str, seller_name: str, now: str, unit_type: str | None, unit_number: Any
) -> Dict[str, Any]:
    """Build profile data dict with optional unit fields."""
    profile_data: Dict[str, Any] = {
        "profileId": profile_id,
        "ownerAccountId": owner_account_id_stored,
        "sellerName": seller_name,
        "createdAt": now,
        "updatedAt": now,
    }

    if unit_type:
        profile_data["unitType"] = unit_type
    if unit_number is not None:
        profile_data["unitNumber"] = int(unit_number)

    return profile_data


def create_seller_profile(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create a new seller profile.

    In the multi-table design (V2), profiles are stored in the profiles table with:
    - PK: ownerAccountId (e.g., "ACCOUNT#abc123")
    - SK: profileId (e.g., "PROFILE#abc123")

    This allows efficient listing of all profiles owned by an account via PK query.
    GSI (profileId-index) enables lookup by profileId.

    Args:
        event: AppSync resolver event with arguments and identity
        context: Lambda context (unused)

    Returns:
        Created profile dict

    Raises:
        AppError: If input validation fails or an unexpected error occurs
    """
    try:
        input_data = event["arguments"]["input"]
        seller_name = validate_seller_name(input_data.get("sellerName"))
        unit_type = validate_unit_type(input_data.get("unitType"))
        unit_number = input_data.get("unitNumber")
        caller_account_id = event["identity"]["sub"]

        if unit_number is not None:
            validate_unit_number(unit_number, required=True)

        logger.info("Creating seller profile", extra={"sellerName": seller_name, "callerAccountId": caller_account_id})

        profile_id = f"PROFILE#{uuid.uuid4()}"
        owner_account_id_stored = f"ACCOUNT#{caller_account_id}"
        now = datetime.now(timezone.utc).isoformat()

        profile_data = _build_profile_data(
            profile_id, owner_account_id_stored, seller_name, now, unit_type, unit_number
        )

        # In multi-table design V2, profiles table uses:
        # - PK: ownerAccountId (ACCOUNT#sub) - enables listMyProfiles via PK query
        # - SK: profileId (PROFILE#uuid) - unique profile identifier
        # - GSI: profileId-index - enables getProfile and authorization lookups
        tables.profiles.put_item(Item=profile_data)

        logger.info(
            "Seller profile created successfully",
            extra={"profileId": profile_id, "sellerName": seller_name},
        )

        return profile_data

    except AppError:
        raise
    except Exception as e:
        logger.error("Error creating seller profile", extra={"error": str(e)}, exc_info=True)
        raise AppError(ErrorCode.INTERNAL_ERROR, "Failed to create seller profile") from e
