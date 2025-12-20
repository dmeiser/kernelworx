"""Lambda handler for createCampaignPrefill operation only.

Other operations (get, list, find, update, delete) use VTL/Pipeline resolvers.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict

import boto3
from boto3.dynamodb.conditions import Key

# Handle both Lambda (absolute) and unit test (relative) imports
try:
    from utils.errors import ValidationError  # type: ignore[import-not-found]
    from utils.logging import get_logger  # type: ignore[import-not-found]
except ModuleNotFoundError:
    from ..utils.errors import ValidationError
    from ..utils.logging import get_logger

logger = get_logger(__name__)

# Initialize DynamoDB client
dynamodb = boto3.resource("dynamodb")

# Campaign Prefills table
prefills_table_name = os.environ.get(
    "CAMPAIGN_PREFILLS_TABLE_NAME", "kernelworx-campaign-prefills-ue1-dev"
)
prefills_table = dynamodb.Table(prefills_table_name)


def _generate_prefill_code(
    unit_type: str, unit_number: int, season_name: str, state: str, season_year: int
) -> str:
    """
    Generate a prefill code in format: {unitType}{unitNumber}-{season4chars}-{state}-{year2digits}

    Examples:
    - Pack 123, Spring, IL, 2025 -> PACK123-SPRI-IL-25
    - Troop 456, Fall, CA, 2025 -> TROO456-FALL-CA-25

    Args:
        unit_type: "Pack", "Troop", "Crew", "Ship"
        unit_number: Unit number (e.g., 123)
        season_name: Season name (e.g., "Spring", "Fall")
        state: 2-letter state code (e.g., "IL")
        season_year: 4-digit year (e.g., 2025)

    Returns:
        Generated prefill code (uppercase)
    """
    # First 4 letters of unit type (uppercase)
    unit_prefix = unit_type[:4].upper()

    # First 4 letters of season name (uppercase)
    season_prefix = season_name[:4].upper()

    # Last 2 digits of year
    year_suffix = str(season_year)[-2:]

    # Format: PACK123-SPRI-IL-25
    code = f"{unit_prefix}{unit_number}-{season_prefix}-{state.upper()}-{year_suffix}"

    return code


def create_campaign_prefill(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create a new campaign prefill.

    Authorization: Any authenticated user
    Rate limit: Not enforced in Lambda (left for future enhancement)

    Args:
        event: AppSync resolver event with arguments and identity
        context: Lambda context (unused)

    Returns:
        Created prefill dict

    Raises:
        ValidationError: If validation fails
    """
    try:
        # Extract parameters from input wrapper
        args = event["arguments"]["input"]
        catalog_id = args["catalogId"]
        season_name = args["seasonName"]
        season_year = args["seasonYear"]
        unit_type = args["unitType"]
        unit_number = args["unitNumber"]
        city = args["city"]
        state = args["state"]
        creator_message = args.get("creatorMessage", "")
        description = args.get("description", "")
        start_date = args.get("startDate")
        end_date = args.get("endDate")

        caller_account_id = event["identity"]["sub"]
        caller_name = event["identity"].get("username", "Unknown")

        logger.info(
            "Creating campaign prefill",
            extra={
                "callerAccountId": caller_account_id,
                "unitType": unit_type,
                "unitNumber": unit_number,
                "seasonName": season_name,
                "seasonYear": season_year,
            },
        )

        # Validate creator message length (max 300 chars)
        if len(creator_message) > 300:
            raise ValidationError(
                f"Creator message exceeds maximum length of 300 characters "
                f"(current: {len(creator_message)})"
            )

        # Generate prefill code
        prefill_code = _generate_prefill_code(
            unit_type, unit_number, season_name, state, season_year
        )

        # Check for code collision using conditional write
        now = datetime.now(timezone.utc).isoformat()

        unit_season_key = (
            f"UNIT#{unit_type}#{unit_number}#{city}#{state}#SEASON#{season_name}#{season_year}"
        )

        # Prepare item
        item = {
            "prefillCode": prefill_code,  # PK
            "SK": "METADATA",  # SK
            "createdBy": caller_account_id,  # GSI1 PK
            "createdAt": now,  # GSI1 SK
            "unitSeasonKey": unit_season_key,  # GSI2 PK
            "catalogId": catalog_id,
            "seasonName": season_name,
            "seasonYear": season_year,
            "unitType": unit_type,
            "unitNumber": unit_number,
            "city": city,
            "state": state,
            "createdByName": caller_name,
            "creatorMessage": creator_message,
            "description": description,
            "isActive": True,
        }

        # Add optional dates
        if start_date:
            item["startDate"] = start_date
        if end_date:
            item["endDate"] = end_date

        # Conditional write - fail if code already exists
        try:
            prefills_table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(prefillCode)",
            )
        except prefills_table.meta.client.exceptions.ConditionalCheckFailedException:
            # Code collision - try alternative strategy
            # For now, raise error - in production, could add random suffix
            raise ValidationError(
                f"Campaign prefill code '{prefill_code}' already exists. "
                f"Please try again with different parameters or contact support."
            )

        logger.info(
            "Campaign prefill created successfully",
            extra={"prefillCode": prefill_code},
        )

        return item

    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating campaign prefill: {str(e)}")
        raise
