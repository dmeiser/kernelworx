"""Unit tests for list_unit_catalogs handler."""

import json
import os
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
os.environ.setdefault("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-v2-ue1-dev")
os.environ.setdefault("CATALOGS_TABLE_NAME", "kernelworx-catalogs-ue1-dev")


def _unit_event(
    path: str = "/api/unit-catalogs",
    unit_type: str = "Troop",
    unit_number: str = "42",
    campaign_name: str = "Fall",
    campaign_year: str = "2025",
    caller: str = "user-abc",
    city: str = "",
    state: str = "",
) -> Dict[str, Any]:
    params: Dict[str, str] = {
        "unitType": unit_type,
        "unitNumber": unit_number,
        "campaignName": campaign_name,
        "campaignYear": campaign_year,
    }
    if city:
        params["city"] = city
    if state:
        params["state"] = state
    return {
        "httpMethod": "GET",
        "path": path,
        "requestContext": {"authorizer": {"sub": caller}},
        "queryStringParameters": params,
    }


def _campaign_event(
    unit_type: str = "Troop",
    unit_number: str = "42",
    city: str = "Springfield",
    state: str = "IL",
    campaign_name: str = "Fall",
    campaign_year: str = "2025",
    caller: str = "user-abc",
) -> Dict[str, Any]:
    return {
        "httpMethod": "GET",
        "path": "/api/unit-campaign-catalogs",
        "requestContext": {"authorizer": {"sub": caller}},
        "queryStringParameters": {
            "unitType": unit_type,
            "unitNumber": unit_number,
            "city": city,
            "state": state,
            "campaignName": campaign_name,
            "campaignYear": campaign_year,
        },
    }


# ---------------------------------------------------------------------------
# list_unit_catalogs
# ---------------------------------------------------------------------------


def test_list_unit_catalogs_missing_params_returns_400() -> None:
    from src.handlers.list_unit_catalogs import list_unit_catalogs

    event: Dict[str, Any] = {
        "queryStringParameters": {"unitType": "Troop"},
        "requestContext": {"authorizer": {"sub": "u"}},
    }
    res = list_unit_catalogs(event, None)
    assert res["statusCode"] == 400


def test_list_unit_catalogs_no_profiles_returns_empty() -> None:
    from src.handlers.list_unit_catalogs import list_unit_catalogs

    with patch("src.handlers.list_unit_catalogs.query_all_items", return_value=[]):
        res = list_unit_catalogs(_unit_event(), None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"]) == []


def test_list_unit_catalogs_no_accessible_profiles_returns_empty() -> None:
    from src.handlers.list_unit_catalogs import list_unit_catalogs

    profiles = [{"profileId": "PROFILE#1"}]
    with patch("src.handlers.list_unit_catalogs.query_all_items", return_value=profiles):
        with patch("src.handlers.list_unit_catalogs.check_profile_access", return_value=False):
            res = list_unit_catalogs(_unit_event(), None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"]) == []


def test_list_unit_catalogs_no_catalog_ids_returns_empty() -> None:
    from src.handlers.list_unit_catalogs import list_unit_catalogs

    profiles = [{"profileId": "PROFILE#1"}]
    with patch("src.handlers.list_unit_catalogs.query_all_items", return_value=profiles):
        with patch("src.handlers.list_unit_catalogs.check_profile_access", return_value=True):
            with patch("src.handlers.list_unit_catalogs._collect_catalog_ids", return_value=set()):
                res = list_unit_catalogs(_unit_event(), None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"]) == []


def test_list_unit_catalogs_full_happy_path() -> None:
    from src.handlers.list_unit_catalogs import list_unit_catalogs

    profiles = [{"profileId": "PROFILE#1"}]
    catalog = {"catalogId": "CAT#1", "catalogName": "Fall Catalog"}

    with patch("src.handlers.list_unit_catalogs.query_all_items", return_value=profiles):
        with patch("src.handlers.list_unit_catalogs.check_profile_access", return_value=True):
            with patch("src.handlers.list_unit_catalogs._collect_catalog_ids", return_value={"CAT#1"}):
                with patch("src.handlers.list_unit_catalogs._fetch_catalogs", return_value=[catalog]):
                    res = list_unit_catalogs(_unit_event(), None)
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert len(body) == 1
    assert body[0]["catalogId"] == "CAT#1"


def test_list_unit_catalogs_exception_returns_500() -> None:
    from src.handlers.list_unit_catalogs import list_unit_catalogs

    with patch("src.handlers.list_unit_catalogs.query_all_items", side_effect=RuntimeError("boom")):
        res = list_unit_catalogs(_unit_event(), None)
    assert res["statusCode"] == 500


# ---------------------------------------------------------------------------
# list_unit_campaign_catalogs
# ---------------------------------------------------------------------------


def test_list_unit_campaign_catalogs_missing_params_returns_400() -> None:
    from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

    event: Dict[str, Any] = {
        "queryStringParameters": {"unitType": "Troop"},
        "requestContext": {"authorizer": {"sub": "u"}},
    }
    res = list_unit_campaign_catalogs(event, None)
    assert res["statusCode"] == 400


def test_list_unit_campaign_catalogs_no_campaigns_returns_empty() -> None:
    from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

    with patch("src.handlers.list_unit_catalogs.query_all_items", return_value=[]):
        res = list_unit_campaign_catalogs(_campaign_event(), None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"]) == []


def test_list_unit_campaign_catalogs_no_accessible_catalog_ids_returns_empty() -> None:
    from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

    campaigns = [{"profileId": "PROFILE#1", "catalogId": "CAT#1"}]
    with patch("src.handlers.list_unit_catalogs.query_all_items", return_value=campaigns):
        with patch("src.handlers.list_unit_catalogs.check_profile_access", return_value=False):
            res = list_unit_campaign_catalogs(_campaign_event(), None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"]) == []


def test_list_unit_campaign_catalogs_happy_path() -> None:
    from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

    campaigns = [{"profileId": "PROFILE#1", "catalogId": "CAT#1"}]
    catalog = {"catalogId": "CAT#1", "catalogName": "Fall"}

    with patch("src.handlers.list_unit_catalogs.query_all_items", return_value=campaigns):
        with patch("src.handlers.list_unit_catalogs.check_profile_access", return_value=True):
            with patch("src.handlers.list_unit_catalogs._fetch_catalogs", return_value=[catalog]):
                res = list_unit_campaign_catalogs(_campaign_event(), None)
    assert res["statusCode"] == 200
    assert len(json.loads(res["body"])) == 1


def test_list_unit_campaign_catalogs_exception_returns_500() -> None:
    from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs

    with patch("src.handlers.list_unit_catalogs.query_all_items", side_effect=RuntimeError("boom")):
        res = list_unit_campaign_catalogs(_campaign_event(), None)
    assert res["statusCode"] == 500


# ---------------------------------------------------------------------------
# handler routing
# ---------------------------------------------------------------------------


def test_handler_routes_unit_catalogs() -> None:
    from src.handlers.list_unit_catalogs import handler

    with patch("src.handlers.list_unit_catalogs.query_all_items", return_value=[]):
        res = handler(_unit_event(), None)
    assert res["statusCode"] == 200


def test_handler_routes_unit_campaign_catalogs() -> None:
    from src.handlers.list_unit_catalogs import handler

    with patch("src.handlers.list_unit_catalogs.query_all_items", return_value=[]):
        res = handler(_campaign_event(), None)
    assert res["statusCode"] == 200


def test_handler_unknown_route_returns_404() -> None:
    from src.handlers.list_unit_catalogs import handler

    event: Dict[str, Any] = {"httpMethod": "GET", "path": "/unknown", "queryStringParameters": {}}
    res = handler(event, None)
    assert res["statusCode"] == 404


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def test_collect_catalog_ids_filters_non_string() -> None:
    """_collect_catalog_ids skips non-string catalogId values."""
    from src.handlers.list_unit_catalogs import _collect_catalog_ids

    profiles = [{"profileId": "PROFILE#1"}]
    with patch("src.handlers.list_unit_catalogs.query_all_items") as mock_q:
        mock_q.return_value = [
            {"catalogId": "CAT#1"},
            {"catalogId": None},
            {"catalogId": 123},
            {},
        ]
        result = _collect_catalog_ids(profiles, "Fall", 2025)
    assert result == {"CAT#1"}


def test_fetch_catalogs_skips_missing() -> None:
    """_fetch_catalogs skips catalog IDs that don't return an Item."""
    from src.handlers.list_unit_catalogs import _fetch_catalogs

    with patch("src.handlers.list_unit_catalogs.tables") as mock_tables:
        mock_tables.catalogs.get_item.side_effect = [
            {"Item": {"catalogId": "CAT#1", "catalogName": "B"}},
            {},
            Exception("fail"),
        ]
        catalogs = _fetch_catalogs({"CAT#1", "CAT#2", "CAT#3"})
    assert len(catalogs) == 1
    assert catalogs[0]["catalogId"] == "CAT#1"


def test_filter_accessible_profiles_returns_matching() -> None:
    from src.handlers.list_unit_catalogs import _filter_accessible_profiles

    profiles = [{"profileId": "P#1"}, {"profileId": "P#2"}]
    with patch("src.handlers.list_unit_catalogs.check_profile_access") as mock_access:
        mock_access.side_effect = [True, False]
        result = _filter_accessible_profiles(profiles, "ACCOUNT#u")
    assert len(result) == 1
    assert result[0]["profileId"] == "P#1"


def test_collect_catalog_ids_from_campaigns_filters_access() -> None:
    from src.handlers.list_unit_catalogs import _collect_catalog_ids_from_campaigns

    campaigns = [
        {"profileId": "P#1", "catalogId": "CAT#A"},
        {"profileId": "P#2", "catalogId": "CAT#B"},
        {"profileId": "P#3", "catalogId": None},
        {"profileId": "P#4", "catalogId": 99},
    ]
    with patch("src.handlers.list_unit_catalogs.check_profile_access", side_effect=[True, False, True, True]):
        result = _collect_catalog_ids_from_campaigns(campaigns, "ACCOUNT#u")
    assert result == {"CAT#A"}


def test_build_unit_campaign_key() -> None:
    from src.handlers.list_unit_catalogs import _build_unit_campaign_key

    key = _build_unit_campaign_key("Troop", 42, "Springfield", "IL", "Fall", 2025)
    assert key == "Troop#42#Springfield#IL#Fall#2025"
