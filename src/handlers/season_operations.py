"""Lambda resolver for season operations with prefill and share support."""

import os
import uuid
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import check_profile_access  # type: ignore[import-not-found]
    from utils.logging import get_logger  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import check_profile_access
    from ..utils.logging import get_logger

logger = get_logger(__name__)

# Initialize DynamoDB client
dynamodb = boto3.resource("dynamodb")
dynamodb_client = boto3.client("dynamodb")

# Multi-table design V2
seasons_table_name = os.environ.get("SEASONS_TABLE_NAME", "kernelworx-seasons-v2-ue1-dev")
prefills_table_name = os.environ.get("PREFILLS_TABLE_NAME", "kernelworx-campaign-prefills-ue1-dev")
shares_table_name = os.environ.get("SHARES_TABLE_NAME", "kernelworx-shares-v2-ue1-dev")
profiles_table_name = os.environ.get("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")

seasons_table = dynamodb.Table(seasons_table_name)
prefills_table = dynamodb.Table(prefills_table_name)
shares_table = dynamodb.Table(shares_table_name)
profiles_table = dynamodb.Table(profiles_table_name)


def _build_unit_season_key(
    unit_type: str, unit_number: int, city: str, state: str, season_name: str, season_year: int
) -> str:
    """Build the GSI3 partition key for unit+season queries."""
    return f"{unit_type}#{unit_number}#{city}#{state}#{season_name}#{season_year}"


def _get_prefill(prefill_code: str) -> Optional[Dict[str, Any]]:
    """Retrieve a campaign prefill by code."""
    try:
        response = prefills_table.get_item(Key={"prefillCode": prefill_code, "SK": "METADATA"})
        return response.get("Item")
    except Exception as e:
        logger.error(f"Error fetching prefill {prefill_code}: {str(e)}")
        return None


def _get_profile(profile_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a profile by ID using the profileId-index GSI."""
    try:
        response = profiles_table.query(
            IndexName="profileId-index",
            KeyConditionExpression="profileId = :profileId",
            ExpressionAttributeValues={":profileId": profile_id},
            Limit=1,
        )
        items = response.get("Items", [])
        return items[0] if items else None
    except Exception as e:
        logger.error(f"Error fetching profile {profile_id}: {str(e)}")
        return None


def create_season(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create a new season with optional prefill support and share creation.

    This handler supports:
    1. Creating a season with explicitly provided unit fields
    2. Creating a season from a campaign prefill (prefillCode)
    3. Optionally creating a READ share with the prefill creator (shareWithCreator)

    When unit fields (unitType, unitNumber, city, state) are provided,
    the season is indexed in GSI3 for unit-based queries.

    Args:
        event: AppSync resolver event with arguments:
            - profileId: ID! - The profile to create the season for
            - seasonName: String - Season name (from input or prefill)
            - seasonYear: Int - Season year (from input or prefill)
            - startDate: AWSDateTime - Season start date
            - endDate: AWSDateTime - Optional season end date
            - catalogId: ID - Catalog to use (from input or prefill)
            - unitType: String - Optional unit type
            - unitNumber: Int - Optional unit number
            - city: String - Required if unitType provided
            - state: String - Required if unitType provided
            - prefillCode: String - Optional prefill code to use
            - shareWithCreator: Boolean - If true, create READ share with prefill creator
        context: Lambda context (unused)

    Returns:
        Created Season object
    """
    try:
        # Extract input
        inp = event["arguments"]["input"]
        caller_account_id = event["identity"]["sub"]
        profile_id = inp["profileId"]

        logger.info(f"Creating season for profile {profile_id}, caller {caller_account_id}")

        # Step 1: Verify caller has write access to the profile
        if not check_profile_access(
            caller_account_id=caller_account_id,
            profile_id=profile_id,
            required_permission="WRITE",
        ):
            logger.warning(f"Access denied for {caller_account_id} to profile {profile_id}")
            raise PermissionError("You do not have permission to create a season for this profile")

        # Step 2: Get the profile to verify it exists
        profile = _get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        # Step 3: If prefillCode provided, load prefill data
        prefill: Optional[Dict[str, Any]] = None
        prefill_code = inp.get("prefillCode")
        share_with_creator = inp.get("shareWithCreator", False)

        if prefill_code:
            prefill = _get_prefill(prefill_code)
            if not prefill:
                raise ValueError(f"Campaign prefill {prefill_code} not found")
            if not prefill.get("isActive", True):
                raise ValueError(f"Campaign prefill {prefill_code} is no longer active")
            logger.info(f"Using prefill {prefill_code} from creator {prefill.get('createdBy')}")

        # Step 4: Determine season values (prefer prefill over input, but input can override dates)
        if prefill:
            season_name = prefill["seasonName"]
            season_year = prefill["seasonYear"]
            catalog_id = prefill["catalogId"]
            unit_type = prefill["unitType"]
            unit_number = prefill["unitNumber"]
            city = prefill["city"]
            state = prefill["state"]
            # Dates can come from input or fall back to prefill
            start_date = inp.get("startDate") or prefill.get("startDate")
            end_date = inp.get("endDate") or prefill.get("endDate")
        else:
            season_name = inp.get("seasonName")
            season_year = inp.get("seasonYear")
            catalog_id = inp.get("catalogId")
            unit_type = inp.get("unitType")
            unit_number = inp.get("unitNumber")
            city = inp.get("city")
            state = inp.get("state")
            start_date = inp.get("startDate")
            end_date = inp.get("endDate")

        # Step 5: Validate required fields
        if not season_name:
            raise ValueError("seasonName is required")
        if not season_year:
            raise ValueError("seasonYear is required")
        if not catalog_id:
            raise ValueError("catalogId is required")

        # Validate unit fields consistency
        if unit_type:
            if not unit_number:
                raise ValueError("unitNumber is required when unitType is provided")
            if not city:
                raise ValueError("city is required when unitType is provided")
            if not state:
                raise ValueError("state is required when unitType is provided")

        # Step 6: Generate IDs and timestamps
        from datetime import datetime, timezone

        season_id = f"SEASON#{uuid.uuid4()}"
        now = datetime.now(timezone.utc).isoformat()

        # Step 7: Build season item
        season_item: Dict[str, Any] = {
            "profileId": profile_id,
            "seasonId": season_id,
            "seasonName": season_name,
            "seasonYear": season_year,
            "startDate": start_date,
            "catalogId": catalog_id,
            "createdAt": now,
            "updatedAt": now,
        }

        if end_date:
            season_item["endDate"] = end_date

        # Add unit fields if present
        if unit_type:
            season_item["unitType"] = unit_type
            season_item["unitNumber"] = unit_number
            season_item["city"] = city
            season_item["state"] = state
            # Build GSI3 key for unit-based queries
            season_item["unitSeasonKey"] = _build_unit_season_key(
                unit_type, unit_number, city, state, season_name, season_year
            )

        # Store prefillCode reference if used
        if prefill_code:
            season_item["prefillCode"] = prefill_code

        # Step 8: Build transaction items
        transact_items: List[Dict[str, Any]] = []

        # Convert season item to DynamoDB format
        season_dynamo = {k: _to_dynamo_value(v) for k, v in season_item.items()}
        transact_items.append(
            {
                "Put": {
                    "TableName": seasons_table_name,
                    "Item": season_dynamo,
                }
            }
        )

        # If shareWithCreator is true and we have a prefill, create the share
        share_item: Optional[Dict[str, Any]] = None
        if share_with_creator and prefill:
            creator_account_id = prefill.get("createdBy")
            if creator_account_id and creator_account_id != profile.get("ownerAccountId"):
                # Don't create share if creator is the profile owner
                share_id = f"SHARE#{uuid.uuid4()}"
                share_item = {
                    "profileId": profile_id,
                    "shareId": share_id,
                    "targetAccountId": creator_account_id,
                    "permissions": ["READ"],
                    "createdAt": now,
                    "createdByAccountId": caller_account_id,
                    # GSI1 key for listing shares by target account
                    "GSI1PK": f"ACCOUNT#{creator_account_id}",
                    "GSI1SK": share_id,
                }

                share_dynamo = {k: _to_dynamo_value(v) for k, v in share_item.items()}
                transact_items.append(
                    {
                        "Put": {
                            "TableName": shares_table_name,
                            "Item": share_dynamo,
                            # Prevent duplicate shares
                            "ConditionExpression": "attribute_not_exists(profileId)",
                        }
                    }
                )

        # Step 9: Execute transaction
        try:
            dynamodb_client.transact_write_items(
                TransactItems=transact_items  # type: ignore[arg-type]
            )
            logger.info(f"Created season {season_id} for profile {profile_id}")
            if share_item:
                logger.info(
                    f"Created share with creator {prefill.get('createdBy')}"  # type: ignore[union-attr]
                )
        except dynamodb_client.exceptions.TransactionCanceledException as e:
            # Check for conditional check failures
            cancellation_reasons = e.response.get("CancellationReasons", [])
            for reason in cancellation_reasons:
                if reason.get("Code") == "ConditionalCheckFailed":
                    logger.warning("Share already exists, skipping share creation")
                    # Retry without the share
                    dynamodb_client.transact_write_items(
                        TransactItems=transact_items[:1]  # type: ignore[arg-type]
                    )
                    break
            else:
                raise

        # Return the created season
        return season_item

    except PermissionError as e:
        logger.warning(f"Permission error: {str(e)}")
        raise
    except ValueError as e:
        logger.warning(f"Validation error: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error creating season: {str(e)}", exc_info=True)
        raise


def _to_dynamo_value(value: Any) -> Dict[str, Any]:
    """Convert a Python value to DynamoDB attribute value format."""
    if value is None:
        return {"NULL": True}
    elif isinstance(value, bool):
        return {"BOOL": value}
    elif isinstance(value, str):
        return {"S": value}
    elif isinstance(value, int):
        return {"N": str(value)}
    elif isinstance(value, float):
        return {"N": str(value)}
    elif isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return {"SS": value}
        else:
            return {"L": [_to_dynamo_value(item) for item in value]}
    elif isinstance(value, dict):
        return {"M": {k: _to_dynamo_value(v) for k, v in value.items()}}
    else:
        return {"S": str(value)}
