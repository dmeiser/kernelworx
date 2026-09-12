"""
Input validation utilities.

Validates customer information, phone numbers, addresses, etc.

The typed input models in this module (CreateSellerProfileInput,
UpdateSellerProfileInput, CreateCampaignInput, UpdateCampaignInput) are
additive: they mirror the AppSync resolver validation semantics but are not
yet wired into request handling. That wiring is tracked as follow-up task
KW-VALIDATION-WIRING-1.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Self, Tuple

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


def parse_iso_date(date_str: Any) -> datetime:
    """
    Parse an ISO 8601 date string to a datetime object, normalized to UTC.

    Args:
        date_str: Date string to validate and parse

    Returns:
        datetime object in UTC

    Raises:
        AppError: If date_str is not a string or has an invalid ISO format
    """
    if not isinstance(date_str, str):
        raise AppError(ErrorCode.INVALID_INPUT, "Invalid date format for startDate or endDate")

    cleaned = date_str.strip()
    if not cleaned:
        raise AppError(ErrorCode.INVALID_INPUT, "Invalid date format for startDate or endDate")

    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError, TypeError:
        raise AppError(ErrorCode.INVALID_INPUT, "Invalid date format for startDate or endDate")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def validate_date_range(start_date: Optional[str], end_date: Optional[str]) -> None:
    """
    Validate startDate and endDate format and relative ordering.

    Args:
        start_date: Optional ISO start date string
        end_date: Optional ISO end date string

    Raises:
        AppError: If date format is invalid or endDate is not after startDate
    """
    start_dt = parse_iso_date(start_date) if start_date is not None else None
    end_dt = parse_iso_date(end_date) if end_date is not None else None

    if start_dt is not None and end_dt is not None:
        if end_dt <= start_dt:
            raise AppError(ErrorCode.INVALID_INPUT, "endDate must be after startDate")


def _extract_field(data: Dict[str, Any], *keys: str) -> Any:
    """Extract first matching key from dictionary."""
    for key in keys:
        if key in data:
            return data[key]
    return None


@dataclass
class CreateSellerProfileInput:
    """Input model for creating a seller profile."""

    seller_name: str
    unit_type: Optional[str] = None
    unit_number: Optional[int] = None

    def __post_init__(self) -> None:
        """Validate fields upon initialization."""
        self.seller_name = validate_seller_name(self.seller_name)
        if self.unit_type is not None:
            self.unit_type = validate_unit_type(self.unit_type)
        if self.unit_number is not None:
            self.unit_number = validate_unit_number(self.unit_number)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
        """Create model instance from dictionary with camelCase or snake_case keys."""
        if not isinstance(data, dict):
            raise AppError(ErrorCode.INVALID_INPUT, "Input must be an object")
        seller_name = _extract_field(data, "sellerName", "seller_name")
        unit_type = _extract_field(data, "unitType", "unit_type")
        unit_number = _extract_field(data, "unitNumber", "unit_number")
        return cls(
            seller_name=seller_name,
            unit_type=unit_type,
            unit_number=unit_number,
        )

    def to_dict(self, exclude_none: bool = False, camel_case: bool = True) -> Dict[str, Any]:
        """Convert model instance to dictionary."""
        if camel_case:
            res: Dict[str, Any] = {
                "sellerName": self.seller_name,
                "unitType": self.unit_type,
                "unitNumber": self.unit_number,
            }
        else:
            res = {
                "seller_name": self.seller_name,
                "unit_type": self.unit_type,
                "unit_number": self.unit_number,
            }
        if exclude_none:
            return {k: v for k, v in res.items() if v is not None}
        return res


@dataclass
class UpdateSellerProfileInput:
    """Input model for updating a seller profile."""

    profile_id: str
    seller_name: str
    unit_type: Optional[str] = None
    unit_number: Optional[int] = None

    def __post_init__(self) -> None:
        """Validate fields upon initialization."""
        if not self.profile_id or not str(self.profile_id).strip():
            raise AppError(ErrorCode.INVALID_INPUT, "profileId is required")
        self.profile_id = str(self.profile_id).strip()
        self.seller_name = validate_seller_name(self.seller_name)
        if self.unit_type is not None:
            self.unit_type = validate_unit_type(self.unit_type)
        if self.unit_number is not None:
            self.unit_number = validate_unit_number(self.unit_number)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
        """Create model instance from dictionary with camelCase or snake_case keys."""
        if not isinstance(data, dict):
            raise AppError(ErrorCode.INVALID_INPUT, "Input must be an object")
        profile_id = _extract_field(data, "profileId", "profile_id")
        seller_name = _extract_field(data, "sellerName", "seller_name")
        unit_type = _extract_field(data, "unitType", "unit_type")
        unit_number = _extract_field(data, "unitNumber", "unit_number")
        return cls(
            profile_id=profile_id,
            seller_name=seller_name,
            unit_type=unit_type,
            unit_number=unit_number,
        )

    def to_dict(self, exclude_none: bool = False, camel_case: bool = True) -> Dict[str, Any]:
        """Convert model instance to dictionary."""
        if camel_case:
            res: Dict[str, Any] = {
                "profileId": self.profile_id,
                "sellerName": self.seller_name,
                "unitType": self.unit_type,
                "unitNumber": self.unit_number,
            }
        else:
            res = {
                "profile_id": self.profile_id,
                "seller_name": self.seller_name,
                "unit_type": self.unit_type,
                "unit_number": self.unit_number,
            }
        if exclude_none:
            return {k: v for k, v in res.items() if v is not None}
        return res


@dataclass
class CreateCampaignInput:
    """Input model for creating a campaign."""

    profile_id: str
    campaign_name: Optional[str] = None
    campaign_year: Optional[int] = None
    catalog_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    unit_type: Optional[str] = None
    unit_number: Optional[int] = None
    city: Optional[str] = None
    state: Optional[str] = None
    shared_campaign_code: Optional[str] = None
    share_with_creator: Optional[bool] = None

    def __post_init__(self) -> None:
        """Validate fields upon initialization."""
        self._validate_profile_id()
        self._validate_campaign_identity()
        self._validate_dates()
        self._validate_unit_fields()

    def _validate_profile_id(self) -> None:
        if not self.profile_id or not str(self.profile_id).strip():
            raise AppError(ErrorCode.INVALID_INPUT, "profileId is required")
        self.profile_id = str(self.profile_id).strip()

    def _validate_campaign_identity(self) -> None:
        if self.shared_campaign_code:
            self._validate_shared_identity()
        else:
            self._validate_standalone_identity()

    def _validate_shared_identity(self) -> None:
        if self.campaign_name is not None:
            self.campaign_name = str(self.campaign_name).strip()
        if self.catalog_id is not None:
            self.catalog_id = str(self.catalog_id).strip()
        if self.campaign_year is not None and str(self.campaign_year).strip() != "":
            self.campaign_year = self._parse_year(self.campaign_year)

    def _validate_standalone_identity(self) -> None:
        if not self.campaign_name or not str(self.campaign_name).strip():
            raise AppError(ErrorCode.INVALID_INPUT, "campaign_name is required")
        self.campaign_name = str(self.campaign_name).strip()

        if self.campaign_year is None or str(self.campaign_year).strip() == "":
            raise AppError(ErrorCode.INVALID_INPUT, "campaign_year is required")
        self.campaign_year = self._parse_year(self.campaign_year)

        if not self.catalog_id or not str(self.catalog_id).strip():
            raise AppError(ErrorCode.INVALID_INPUT, "catalog_id is required")
        self.catalog_id = str(self.catalog_id).strip()

    def _parse_year(self, year_val: Any) -> int:
        try:
            val = float(year_val)
            if not val.is_integer():
                raise ValueError
            return int(val)
        except ValueError, TypeError:
            raise AppError(ErrorCode.INVALID_INPUT, "campaign_year must be a valid integer")

    def _validate_dates(self) -> None:
        validate_date_range(self.start_date, self.end_date)

    def _validate_unit_fields(self) -> None:
        if self.unit_type:
            self.unit_type = validate_unit_type(self.unit_type)
            if self.unit_number is None or str(self.unit_number).strip() == "":
                raise AppError(ErrorCode.INVALID_INPUT, "unitNumber is required when unitType is provided")
            self.unit_number = validate_unit_number(self.unit_number)
            if not self.city or not str(self.city).strip():
                raise AppError(ErrorCode.INVALID_INPUT, "city is required when unitType is provided")
            self.city = str(self.city).strip()
            if not self.state or not str(self.state).strip():
                raise AppError(ErrorCode.INVALID_INPUT, "state is required when unitType is provided")
            self.state = str(self.state).strip()
        elif any(x not in (None, "") for x in (self.unit_number, self.city, self.state)):
            raise AppError(ErrorCode.INVALID_INPUT, "unitType is required when unit fields are present")

    def build_unit_campaign_key(self) -> Optional[str]:
        """Build DynamoDB unitCampaignKey index value if unit fields are present."""
        if not self.unit_type or self.unit_number is None or not self.city or not self.state:
            return None
        name = self.campaign_name or ""
        year = str(self.campaign_year) if self.campaign_year is not None else ""
        return f"{self.unit_type}#{self.unit_number}#{self.city}#{self.state}#{name}#{year}"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
        """Create model instance from dictionary with camelCase or snake_case keys."""
        if not isinstance(data, dict):
            raise AppError(ErrorCode.INVALID_INPUT, "Input must be an object")
        return cls(
            profile_id=_extract_field(data, "profileId", "profile_id"),
            campaign_name=_extract_field(data, "campaignName", "campaign_name"),
            campaign_year=_extract_field(data, "campaignYear", "campaign_year"),
            catalog_id=_extract_field(data, "catalogId", "catalog_id"),
            start_date=_extract_field(data, "startDate", "start_date"),
            end_date=_extract_field(data, "endDate", "end_date"),
            unit_type=_extract_field(data, "unitType", "unit_type"),
            unit_number=_extract_field(data, "unitNumber", "unit_number"),
            city=_extract_field(data, "city"),
            state=_extract_field(data, "state"),
            shared_campaign_code=_extract_field(data, "sharedCampaignCode", "shared_campaign_code"),
            share_with_creator=_extract_field(data, "shareWithCreator", "share_with_creator"),
        )

    def to_dict(self, exclude_none: bool = False, camel_case: bool = True) -> Dict[str, Any]:
        """Convert model instance to dictionary."""
        if camel_case:
            res: Dict[str, Any] = {
                "profileId": self.profile_id,
                "campaignName": self.campaign_name,
                "campaignYear": self.campaign_year,
                "catalogId": self.catalog_id,
                "startDate": self.start_date,
                "endDate": self.end_date,
                "unitType": self.unit_type,
                "unitNumber": self.unit_number,
                "city": self.city,
                "state": self.state,
                "sharedCampaignCode": self.shared_campaign_code,
                "shareWithCreator": self.share_with_creator,
            }
        else:
            res = {
                "profile_id": self.profile_id,
                "campaign_name": self.campaign_name,
                "campaign_year": self.campaign_year,
                "catalog_id": self.catalog_id,
                "start_date": self.start_date,
                "end_date": self.end_date,
                "unit_type": self.unit_type,
                "unit_number": self.unit_number,
                "city": self.city,
                "state": self.state,
                "shared_campaign_code": self.shared_campaign_code,
                "share_with_creator": self.share_with_creator,
            }
        if exclude_none:
            return {k: v for k, v in res.items() if v is not None}
        return res


@dataclass
class UpdateCampaignInput:
    """Input model for updating a campaign."""

    campaign_id: str
    campaign_name: Optional[str] = None
    campaign_year: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    catalog_id: Optional[str] = None
    is_active: Optional[bool] = None
    unit_type: Optional[str] = None
    unit_number: Optional[int] = None
    city: Optional[str] = None
    state: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate fields upon initialization."""
        self._validate_campaign_id()
        self._validate_general_optional_fields()
        self._validate_unit_optional_fields()
        self._validate_dates()

    def _validate_campaign_id(self) -> None:
        if not self.campaign_id or not str(self.campaign_id).strip():
            raise AppError(ErrorCode.INVALID_INPUT, "campaignId is required")
        self.campaign_id = str(self.campaign_id).strip()

    def _validate_general_optional_fields(self) -> None:
        if self.campaign_name is not None:
            cleaned_name = str(self.campaign_name).strip()
            if not cleaned_name:
                raise AppError(ErrorCode.INVALID_INPUT, "campaignName cannot be empty")
            self.campaign_name = cleaned_name

        if self.campaign_year is not None and str(self.campaign_year).strip() != "":
            try:
                val = float(self.campaign_year)
                if not val.is_integer():
                    raise ValueError
                self.campaign_year = int(val)
            except ValueError, TypeError:
                raise AppError(ErrorCode.INVALID_INPUT, "campaign_year must be a valid integer")

        if self.catalog_id is not None:
            self.catalog_id = str(self.catalog_id).strip()

        if self.is_active is not None and not isinstance(self.is_active, bool):
            raise AppError(ErrorCode.INVALID_INPUT, "isActive must be a boolean")

    def _validate_unit_optional_fields(self) -> None:
        if self.unit_type is not None:
            self.unit_type = validate_unit_type(self.unit_type)

        if self.unit_number is not None:
            self.unit_number = validate_unit_number(self.unit_number)

    def _validate_dates(self) -> None:
        validate_date_range(self.start_date, self.end_date)

    def has_unit_update(self) -> bool:
        """Check whether any unit field is present in the update."""
        return any(x is not None for x in (self.unit_type, self.unit_number, self.city, self.state))

    def validate_unit_update(self, existing_campaign: Optional[Dict[str, Any]] = None) -> None:
        """
        Validate unit update against an existing campaign record.

        Raises:
            AppError: If unit update is invalid or campaign was created from a shared link
        """
        if not self.has_unit_update():
            return

        campaign = existing_campaign or {}
        if campaign.get("sharedCampaignCode"):
            raise AppError(
                ErrorCode.INVALID_INPUT,
                "Unit information cannot be changed for campaigns created from a shared campaign link.",
            )

        eff_type = self.unit_type if self.unit_type is not None else campaign.get("unitType")
        eff_num = self.unit_number if self.unit_number is not None else campaign.get("unitNumber")
        eff_city = self.city if self.city is not None else campaign.get("city")
        eff_state = self.state if self.state is not None else campaign.get("state")

        self._validate_effective_unit_fields(eff_type, eff_num, eff_city, eff_state)

    def _validate_effective_unit_fields(
        self,
        eff_type: Optional[str],
        eff_num: Any,
        eff_city: Optional[str],
        eff_state: Optional[str],
    ) -> None:
        if eff_type:
            validate_unit_type(eff_type)
            if eff_num is None or eff_num == "":
                raise AppError(ErrorCode.INVALID_INPUT, "unitNumber is required when unitType is provided")
            validate_unit_number(eff_num)
            if not eff_city or not str(eff_city).strip():
                raise AppError(ErrorCode.INVALID_INPUT, "city is required when unitType is provided")
            if not eff_state or not str(eff_state).strip():
                raise AppError(ErrorCode.INVALID_INPUT, "state is required when unitType is provided")
        elif any(x not in (None, "") for x in (eff_num, eff_city, eff_state)):
            raise AppError(ErrorCode.INVALID_INPUT, "unitType is required when unit fields are present")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Self:
        """Create model instance from dictionary with camelCase or snake_case keys."""
        if not isinstance(data, dict):
            raise AppError(ErrorCode.INVALID_INPUT, "Input must be an object")
        return cls(
            campaign_id=_extract_field(data, "campaignId", "campaign_id"),
            campaign_name=_extract_field(data, "campaignName", "campaign_name"),
            campaign_year=_extract_field(data, "campaignYear", "campaign_year"),
            catalog_id=_extract_field(data, "catalogId", "catalog_id"),
            start_date=_extract_field(data, "startDate", "start_date"),
            end_date=_extract_field(data, "endDate", "end_date"),
            is_active=_extract_field(data, "isActive", "is_active"),
            unit_type=_extract_field(data, "unitType", "unit_type"),
            unit_number=_extract_field(data, "unitNumber", "unit_number"),
            city=_extract_field(data, "city"),
            state=_extract_field(data, "state"),
        )

    def to_dict(self, exclude_none: bool = False, camel_case: bool = True) -> Dict[str, Any]:
        """Convert model instance to dictionary."""
        if camel_case:
            res: Dict[str, Any] = {
                "campaignId": self.campaign_id,
                "campaignName": self.campaign_name,
                "campaignYear": self.campaign_year,
                "catalogId": self.catalog_id,
                "startDate": self.start_date,
                "endDate": self.end_date,
                "isActive": self.is_active,
                "unitType": self.unit_type,
                "unitNumber": self.unit_number,
                "city": self.city,
                "state": self.state,
            }
        else:
            res = {
                "campaign_id": self.campaign_id,
                "campaign_name": self.campaign_name,
                "campaign_year": self.campaign_year,
                "catalog_id": self.catalog_id,
                "start_date": self.start_date,
                "end_date": self.end_date,
                "is_active": self.is_active,
                "unit_type": self.unit_type,
                "unit_number": self.unit_number,
                "city": self.city,
                "state": self.state,
            }
        if exclude_none:
            return {k: v for k, v in res.items() if v is not None}
        return res
