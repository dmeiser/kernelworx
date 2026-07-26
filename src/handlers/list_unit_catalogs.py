"""
List catalogs used in a unit (API Gateway proxy event shape).

Restored from the AppSync-shaped ``main`` version. Reads unit/campaign
arguments from query string parameters and the caller id from
``requestContext.authorizer.claims.sub``. Exposes two endpoints:
- GET /api/unit-catalogs -> list_unit_catalogs
- GET /api/unit-campaign-catalogs -> list_unit_campaign_catalogs
Both return a JSON list of Catalog objects.
"""

import json
from typing import Any, Dict, List, Set

from boto3.dynamodb.conditions import Key

try:  # pragma: no cover
    from utils.auth import check_profile_access
    from utils.dynamodb import tables
    from utils.logging import get_logger
    from utils.pagination import query_all_items
    from utils.proxy_event import get_caller_id, get_query_param
except ModuleNotFoundError:  # pragma: no cover
    from src.utils.auth import check_profile_access
    from src.utils.dynamodb import tables
    from src.utils.logging import get_logger
    from src.utils.pagination import query_all_items
    from src.utils.proxy_event import get_caller_id, get_query_param

logger = get_logger(__name__)


def _filter_accessible_profiles(profiles: List[Dict[str, Any]], caller_account_id: str) -> List[Dict[str, Any]]:
    accessible = []
    for profile in profiles:
        profile_id = profile["profileId"]
        if check_profile_access(caller_account_id=caller_account_id, profile_id=profile_id, required_permission="READ"):
            accessible.append(profile)
    return accessible


def _collect_catalog_ids(profiles: List[Dict[str, Any]], campaign_name: str, campaign_year: int) -> Set[str]:
    catalog_ids: Set[str] = set()
    for profile in profiles:
        profile_id = profile["profileId"]
        campaigns = query_all_items(
            tables.campaigns,
            {
                "KeyConditionExpression": Key("profileId").eq(profile_id),
                "FilterExpression": "campaignName = :name AND campaignYear = :year",
                "ExpressionAttributeValues": {":name": campaign_name, ":year": campaign_year},
            },
        )
        for campaign in campaigns:
            catalog_id = campaign.get("catalogId")
            if catalog_id is not None and isinstance(catalog_id, str):
                catalog_ids.add(catalog_id)
    return catalog_ids


def _fetch_catalogs(catalog_ids: Set[str]) -> List[Dict[str, Any]]:
    catalogs: List[Dict[str, Any]] = []
    for catalog_id in catalog_ids:
        try:
            catalog_response = tables.catalogs.get_item(Key={"catalogId": catalog_id})
            if "Item" in catalog_response:
                catalogs.append(catalog_response["Item"])
        except Exception as e:
            logger.warning("Failed to fetch catalog", catalog_id=catalog_id, error=str(e))
    catalogs.sort(key=lambda c: c.get("catalogName", ""))
    return catalogs


def _collect_catalog_ids_from_campaigns(campaigns: List[Dict[str, Any]], caller_account_id: str) -> Set[str]:
    catalog_ids: Set[str] = set()
    for campaign in campaigns:
        profile_id = campaign["profileId"]
        if check_profile_access(caller_account_id=caller_account_id, profile_id=profile_id, required_permission="READ"):
            catalog_id = campaign.get("catalogId")
            if catalog_id is not None and isinstance(catalog_id, str):
                catalog_ids.add(catalog_id)
    return catalog_ids


def list_unit_catalogs(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """List all catalogs used by scouts in a unit (that the caller has access to)."""
    logger.info("list_unit_catalogs invoked")
    try:
        unit_type = get_query_param(event, "unitType") or ""
        unit_number_raw = get_query_param(event, "unitNumber") or ""
        campaign_name = get_query_param(event, "campaignName") or ""
        campaign_year_raw = get_query_param(event, "campaignYear") or ""
        caller_account_id = get_caller_id(event)

        if not unit_type or not unit_number_raw or not campaign_name or not campaign_year_raw:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "unitType, unitNumber, campaignName, and campaignYear are required"}),
            }
        unit_number = int(unit_number_raw)
        campaign_year = int(campaign_year_raw)

        unit_profiles = query_all_items(
            tables.profiles,
            {
                "IndexName": "unitType-unitNumber-index",
                "KeyConditionExpression": Key("unitType").eq(unit_type) & Key("unitNumber").eq(unit_number),
            },
        )
        if not unit_profiles:
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps([]),
            }
        accessible = _filter_accessible_profiles(unit_profiles, caller_account_id)
        if not accessible:
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps([]),
            }
        catalog_ids = _collect_catalog_ids(accessible, campaign_name, campaign_year)
        if not catalog_ids:
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps([]),
            }
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(_fetch_catalogs(catalog_ids), default=str),
        }
    except Exception as e:
        logger.error("Error listing unit catalogs", error=str(e))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }


def _build_unit_campaign_key(unit_type, unit_number, city, state, campaign_name, campaign_year) -> str:
    return f"{unit_type}#{unit_number}#{city}#{state}#{campaign_name}#{campaign_year}"


def list_unit_campaign_catalogs(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """List all catalogs used by scouts in a unit+campaign using unitCampaignKey-index."""
    logger.info("list_unit_campaign_catalogs invoked")
    try:
        unit_type = get_query_param(event, "unitType") or ""
        unit_number_raw = get_query_param(event, "unitNumber") or ""
        city = get_query_param(event, "city") or ""
        state = get_query_param(event, "state") or ""
        campaign_name = get_query_param(event, "campaignName") or ""
        campaign_year_raw = get_query_param(event, "campaignYear") or ""
        caller_account_id = get_caller_id(event)

        if not all([unit_type, unit_number_raw, city, state, campaign_name, campaign_year_raw]):
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(
                    {"error": "unitType, unitNumber, city, state, campaignName, and campaignYear are required"}
                ),
            }
        unit_number = int(unit_number_raw)
        campaign_year = int(campaign_year_raw)

        unit_campaign_key = _build_unit_campaign_key(unit_type, unit_number, city, state, campaign_name, campaign_year)
        unit_campaigns = query_all_items(
            tables.campaigns,
            {
                "IndexName": "unitCampaignKey-index",
                "KeyConditionExpression": Key("unitCampaignKey").eq(unit_campaign_key),
            },
        )
        if not unit_campaigns:
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps([]),
            }
        catalog_ids = _collect_catalog_ids_from_campaigns(unit_campaigns, caller_account_id)
        if not catalog_ids:
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps([]),
            }
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(_fetch_catalogs(catalog_ids), default=str),
        }
    except Exception as e:
        logger.error("Error listing unit campaign catalogs", error=str(e))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway proxy entrypoint for unit catalog listing endpoints."""
    method = event.get("httpMethod", "GET")
    path = event.get("path") or "/"
    if path == "/api/unit-catalogs" and method == "GET":
        return list_unit_catalogs(event, context)
    if path == "/api/unit-campaign-catalogs" and method == "GET":
        return list_unit_campaign_catalogs(event, context)
    return {"statusCode": 404, "headers": {"Content-Type": "text/plain"}, "body": "Not Found"}
