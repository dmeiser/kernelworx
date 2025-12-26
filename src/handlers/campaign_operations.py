"""Lambda resolver for campaign operations with shared campaign and share support."""

import os
import uuid
from typing import Any, Dict, List, Optional

import boto3

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
campaigns_table_name = os.environ.get("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-v2-ue1-dev")
shared_campaigns_table_name = os.environ.get("SHARED_CAMPAIGNS_TABLE_NAME", "kernelworx-shared-campaigns-ue1-dev")
shares_table_name = os.environ.get("SHARES_TABLE_NAME", "kernelworx-shares-v2-ue1-dev")
profiles_table_name = os.environ.get("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")

campaigns_table = dynamodb.Table(campaigns_table_name)
shared_campaigns_table = dynamodb.Table(shared_campaigns_table_name)
shares_table = dynamodb.Table(shares_table_name)
profiles_table = dynamodb.Table(profiles_table_name)


def _build_unit_campaign_key(
    unit_type: str, unit_number: int, city: str, state: str, campaign_name: str, campaign_year: int
) -> str:
    """Build the GSI3 partition key for unit+campaign queries."""
    return f"{unit_type}#{unit_number}#{city}#{state}#{campaign_name}#{campaign_year}"


def _get_shared_campaign(shared_campaign_code: str) -> Optional[Dict[str, Any]]:
    """Retrieve a shared campaign by code."""
    try:
        response = shared_campaigns_table.get_item(Key={"shared_campaignCode": shared_campaign_code, "SK": "METADATA"})
        return response.get("Item")
    except Exception as e:
        logger.error(f"Error fetching shared campaign {shared_campaign_code}: {str(e)}")
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


def create_campaign(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Create a new campaign with optional shared campaign support and share creation.

    This handler supports:
    1. Creating a campaign with explicitly provided unit fields
    2. Creating a campaign from a shared campaign (shared_campaignCode)
    3. Optionally creating a READ share with the shared campaign creator (shareWithCreator)

    When unit fields (unitType, unitNumber, city, state) are provided,
    the campaign is indexed in GSI3 for unit-based queries.

    Args:
        event: AppSync resolver event with arguments:
            - profileId: ID! - The profile to create the campaign for
            - campaignName: String - Campaign name (from input or shared_campaign)
            - campaignYear: Int - Campaign year (from input or shared_campaign)
            - startDate: AWSDateTime - Campaign start date
            - endDate: AWSDateTime - Optional campaign end date
            - catalogId: ID - Catalog to use (from input or shared_campaign)
            - unitType: String - Optional unit type
            - unitNumber: Int - Optional unit number
            - city: String - Required if unitType provided
            - state: String - Required if unitType provided
            - shared_campaignCode: String - Optional shared campaign code to use
            - shareWithCreator: Boolean - If true, create READ share with shared campaign creator
        context: Lambda context (unused)

    Returns:
        Created Campaign object
    """
    try:
        # Extract input
        inp = event["arguments"]["input"]
        caller_account_id = event["identity"]["sub"]
        profile_id = inp["profileId"]

        logger.info(f"Creating campaign for profile {profile_id}, caller {caller_account_id}")

        # Step 1: Verify caller has write access to the profile
        if not check_profile_access(
            caller_account_id=caller_account_id,
            profile_id=profile_id,
            required_permission="WRITE",
        ):
            logger.warning(f"Access denied for {caller_account_id} to profile {profile_id}")
            raise PermissionError("You do not have permission to create a campaign for this profile")

        # Step 2: Get the profile to verify it exists
        profile = _get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        # Step 3: If sharedCampaignCode provided, load Shared Campaign data
        shared_campaign: Optional[Dict[str, Any]] = None
        shared_campaign_code = inp.get("sharedCampaignCode")
        share_with_creator = inp.get("shareWithCreator", False)

        if shared_campaign_code:
            shared_campaign = _get_shared_campaign(shared_campaign_code)
            if not shared_campaign:
                raise ValueError(f"Shared Campaign {shared_campaign_code} not found")
            if not shared_campaign.get("isActive", True):
                raise ValueError(f"Shared Campaign {shared_campaign_code} is no longer active")
            logger.info(f"Using shared campaign {shared_campaign_code} from creator {shared_campaign.get('createdBy')}")

        # Step 4: Determine campaign values (prefer Shared Campaign over input, but input can override dates)
        if shared_campaign:
            campaign_name = shared_campaign["campaignName"]
            campaign_year = shared_campaign["campaignYear"]
            catalog_id = shared_campaign["catalogId"]
            unit_type = shared_campaign["unitType"]
            unit_number = shared_campaign["unitNumber"]
            city = shared_campaign["city"]
            state = shared_campaign["state"]
            # Dates can come from input or fall back to Shared Campaign
            start_date = inp.get("startDate") or shared_campaign.get("startDate")
            end_date = inp.get("endDate") or shared_campaign.get("endDate")
        else:
            campaign_name = inp.get("campaignName")
            campaign_year = inp.get("campaignYear")
            catalog_id = inp.get("catalogId")
            unit_type = inp.get("unitType")
            unit_number = inp.get("unitNumber")
            city = inp.get("city")
            state = inp.get("state")
            start_date = inp.get("startDate")
            end_date = inp.get("endDate")

        # Step 5: Validate required fields
        if not campaign_name:
            raise ValueError("campaignName is required")
        if not campaign_year:
            raise ValueError("campaignYear is required")
        if not catalog_id:
            raise ValueError("catalogId is required")

        # Validate unit fields consistency
        if unit_type:
            if not unit_number:
                raise ValueError("unitNumber is required when unitType is provided")
            # Convert unitNumber to int
            try:
                unit_number = int(unit_number)
            except (ValueError, TypeError):
                raise ValueError("unitNumber must be a valid integer")
            if not city:
                raise ValueError("city is required when unitType is provided")
            if not state:
                raise ValueError("state is required when unitType is provided")

        # Step 6: Generate IDs and timestamps
        from datetime import datetime, timezone

        campaign_id = f"CAMPAIGN#{uuid.uuid4()}"
        now = datetime.now(timezone.utc).isoformat()

        # Step 7: Build campaign item
        campaign_item: Dict[str, Any] = {
            "profileId": profile_id,  # DynamoDB partition key (named "profileId" in table)
            "campaignId": campaign_id,  # DynamoDB sort key (named "campaignId" in table, contains campaign data)
            "campaignName": campaign_name,
            "campaignYear": campaign_year,
            "startDate": start_date,
            "catalogId": catalog_id,
            "createdAt": now,
            "updatedAt": now,
        }

        if end_date:
            campaign_item["endDate"] = end_date

        # Add unit fields if present
        if unit_type:
            campaign_item["unitType"] = unit_type
            campaign_item["unitNumber"] = unit_number
            campaign_item["city"] = city
            campaign_item["state"] = state
            # Build GSI3 key for unit-based queries
            campaign_item["unitCampaignKey"] = _build_unit_campaign_key(
                unit_type, unit_number, city, state, campaign_name, campaign_year
            )

        # Store sharedCampaignCode reference if used
        if shared_campaign_code:
            campaign_item["sharedCampaignCode"] = shared_campaign_code

        # Step 8: Build transaction items
        transact_items: List[Dict[str, Any]] = []

        # Convert campaign item to DynamoDB format
        campaign_dynamo = {k: _to_dynamo_value(v) for k, v in campaign_item.items()}
        transact_items.append(
            {
                "Put": {
                    "TableName": campaigns_table_name,
                    "Item": campaign_dynamo,
                }
            }
        )

        # If shareWithCreator is true and we have a shared_campaign, create the share
        share_item: Optional[Dict[str, Any]] = None
        if share_with_creator and shared_campaign:
            creator_account_id = shared_campaign.get("createdBy")
            # Get the profile owner's account ID (stored with ACCOUNT# prefix, but compare without it)
            owner_account_id = profile.get("ownerAccountId", "")
            # Normalize: remove ACCOUNT# prefix if present for comparison
            owner_account_id_normalized = owner_account_id.replace("ACCOUNT#", "") if owner_account_id else ""
            if creator_account_id and creator_account_id != owner_account_id_normalized:
                # Don't create share if creator is the profile owner
                share_id = f"SHARE#{uuid.uuid4()}"
                share_item = {
                    "profileId": profile_id,
                    "shareId": share_id,
                    "targetAccountId": creator_account_id,
                    "permissions": ["READ"],
                    "ownerAccountId": owner_account_id,  # Store owner account ID for BatchGetItem lookup
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
            logger.info(f"Created campaign {campaign_id} for profile {profile_id}")
            if share_item:
                logger.info(
                    f"Created share with creator {shared_campaign.get('createdBy')}"  # type: ignore[union-attr]
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

        # Return the created campaign
        return campaign_item

    except PermissionError as e:
        logger.warning(f"Permission error: {str(e)}")
        raise
    except ValueError as e:
        logger.warning(f"Validation error: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error creating campaign: {str(e)}", exc_info=True)
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
    elif isinstance(value, (list, set)):
        value_list = list(value) if isinstance(value, set) else value
        if all(isinstance(item, str) for item in value_list):
            return {"SS": set(value_list)}  # boto3 expects a set for SS type
        else:
            return {"L": [_to_dynamo_value(item) for item in value_list]}
    elif isinstance(value, dict):
        return {"M": {k: _to_dynamo_value(v) for k, v in value.items()}}
    else:
        return {"S": str(value)}
