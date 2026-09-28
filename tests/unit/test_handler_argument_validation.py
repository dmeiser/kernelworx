"""Regression tests for #552: malformed AppSync arguments must surface as INVALID_INPUT.

The six argument-extraction sites (list_unit_catalogs, list_unit_campaign_catalogs,
campaign_reporting.get_unit_report, transfer_profile_ownership, and report_generation
request_campaign_report) used to index the raw event with brackets. A missing key or a
non-numeric int() operand then raised KeyError/ValueError, which the ``lambda_handler``
decorator (#329) collapsed into a generic INTERNAL_ERROR — indistinguishable by the client
from a real server fault. These tests pin the correct behaviour: every such malformed or
missing input returns ``INVALID_INPUT`` (or ``UNAUTHORIZED`` for a missing identity), and the
unit-number bound is enforced instead of flowing into the GSI key condition.
"""

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from src.handlers.campaign_reporting import get_unit_report
from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs, list_unit_catalogs
from src.handlers.report_generation import request_campaign_report
from src.handlers.transfer_profile_ownership import lambda_handler as transfer_profile_ownership
from src.utils.errors import ErrorCode

_VALID_UNIT_CATALOGS = {"unitType": "Pack", "unitNumber": 158, "campaignName": "Fall", "campaignYear": 2024}
_VALID_UNIT_CAMPAIGN = {
    "unitType": "Pack",
    "unitNumber": 158,
    "city": "Springfield",
    "state": "IL",
    "campaignName": "Fall",
    "campaignYear": 2024,
}
_VALID_UNIT_REPORT = {
    "unitType": "Pack",
    "unitNumber": 158,
    "city": "Springfield",
    "state": "IL",
    "campaignName": "Fall",
    "campaignYear": 2024,
    "catalogId": "CATALOG#catalog-123",
}


@pytest.fixture
def ctx() -> MagicMock:
    return MagicMock()


def _event(arguments: Dict[str, Any], *, sub: str = "test-account-123") -> Dict[str, Any]:
    return {"arguments": arguments, "identity": {"sub": sub}}


class TestListUnitCatalogsArgumentValidation:
    """list_unit_catalogs must reject malformed arguments with INVALID_INPUT."""

    @pytest.mark.parametrize("bad_arg", ["unitType", "campaignName"])
    def test_missing_required_string_is_invalid_input(self, bad_arg: str, ctx: MagicMock) -> None:
        args = {k: v for k, v in _VALID_UNIT_CATALOGS.items() if k != bad_arg}
        result = list_unit_catalogs(_event(args), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_missing_unit_number_is_invalid_input(self, ctx: MagicMock) -> None:
        args = {k: v for k, v in _VALID_UNIT_CATALOGS.items() if k != "unitNumber"}
        result = list_unit_catalogs(_event(args), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    @pytest.mark.parametrize("bad_year", ["campaignName", "campaignYear"])
    def test_missing_string_or_year_is_invalid_input(self, bad_year: str, ctx: MagicMock) -> None:
        args = {k: v for k, v in _VALID_UNIT_CATALOGS.items() if k != bad_year}
        result = list_unit_catalogs(_event(args), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    @pytest.mark.parametrize("bad_unit_number", ["abc", 0, -3])
    def test_non_numeric_or_out_of_bounds_unit_number_is_invalid_input(
        self, bad_unit_number: Any, ctx: MagicMock
    ) -> None:
        result = list_unit_catalogs(_event({**_VALID_UNIT_CATALOGS, "unitNumber": bad_unit_number}), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_missing_identity_is_unauthorized(self, ctx: MagicMock) -> None:
        event = _event(_VALID_UNIT_CATALOGS)
        del event["identity"]
        result = list_unit_catalogs(event, ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.UNAUTHORIZED


class TestListUnitCampaignCatalogsArgumentValidation:
    """list_unit_campaign_catalogs must reject malformed arguments with INVALID_INPUT."""

    @pytest.mark.parametrize("bad_arg", ["unitType", "city", "state", "campaignName"])
    def test_missing_required_string_is_invalid_input(self, bad_arg: str, ctx: MagicMock) -> None:
        args = {k: v for k, v in _VALID_UNIT_CAMPAIGN.items() if k != bad_arg}
        result = list_unit_campaign_catalogs(_event(args), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_missing_unit_number_is_invalid_input(self, ctx: MagicMock) -> None:
        args = {k: v for k, v in _VALID_UNIT_CAMPAIGN.items() if k != "unitNumber"}
        result = list_unit_campaign_catalogs(_event(args), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_non_numeric_unit_number_is_invalid_input(self, ctx: MagicMock) -> None:
        result = list_unit_campaign_catalogs(_event({**_VALID_UNIT_CAMPAIGN, "unitNumber": "abc"}), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_zero_unit_number_is_invalid_input(self, ctx: MagicMock) -> None:
        result = list_unit_campaign_catalogs(_event({**_VALID_UNIT_CAMPAIGN, "unitNumber": 0}), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_missing_campaign_year_is_invalid_input(self, ctx: MagicMock) -> None:
        args = {k: v for k, v in _VALID_UNIT_CAMPAIGN.items() if k != "campaignYear"}
        result = list_unit_campaign_catalogs(_event(args), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_missing_identity_is_unauthorized(self, ctx: MagicMock) -> None:
        event = _event(_VALID_UNIT_CAMPAIGN)
        del event["identity"]
        result = list_unit_campaign_catalogs(event, ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.UNAUTHORIZED


class TestGetUnitReportArgumentValidation:
    """get_unit_report must reject malformed arguments with INVALID_INPUT."""

    @pytest.mark.parametrize("bad_arg", ["unitType", "campaignName"])
    def test_missing_required_string_is_invalid_input(self, bad_arg: str, ctx: MagicMock) -> None:
        args = {k: v for k, v in _VALID_UNIT_REPORT.items() if k != bad_arg}
        result = get_unit_report(_event(args), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_missing_catalog_id_is_invalid_input(self, ctx: MagicMock) -> None:
        args = {k: v for k, v in _VALID_UNIT_REPORT.items() if k != "catalogId"}
        result = get_unit_report(_event(args), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_non_numeric_unit_number_is_invalid_input(self, ctx: MagicMock) -> None:
        result = get_unit_report(_event({**_VALID_UNIT_REPORT, "unitNumber": "abc"}), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_negative_unit_number_is_invalid_input(self, ctx: MagicMock) -> None:
        result = get_unit_report(_event({**_VALID_UNIT_REPORT, "unitNumber": -1}), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_missing_identity_is_unauthorized(self, ctx: MagicMock) -> None:
        event = _event(_VALID_UNIT_REPORT)
        del event["identity"]
        result = get_unit_report(event, ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.UNAUTHORIZED


class TestTransferProfileOwnershipArgumentValidation:
    """transferProfileOwnership must reject missing input with INVALID_INPUT, not a spurious NOT_FOUND."""

    def test_missing_profile_id_is_invalid_input(self, ctx: MagicMock) -> None:
        result = transfer_profile_ownership(_event({"input": {}}), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_missing_new_owner_account_id_is_invalid_input(self, ctx: MagicMock) -> None:
        result = transfer_profile_ownership(_event({"input": {"profileId": "PROFILE#p1"}}), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_empty_profile_id_is_invalid_input(self, ctx: MagicMock) -> None:
        result = transfer_profile_ownership(_event({"input": {"profileId": "", "newOwnerAccountId": "ACCOUNT#a"}}), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_missing_input_object_is_invalid_input(self, ctx: MagicMock) -> None:
        result = transfer_profile_ownership(_event({}), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT


class TestRequestCampaignReportArgumentValidation:
    """requestCampaignReport must reject malformed arguments with INVALID_INPUT."""

    def test_missing_campaign_id_is_invalid_input(self, ctx: MagicMock) -> None:
        result = request_campaign_report(_event({"input": {}}), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_missing_input_object_is_invalid_input(self, ctx: MagicMock) -> None:
        result = request_campaign_report(_event({}), ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.INVALID_INPUT

    def test_missing_identity_is_unauthorized(self, ctx: MagicMock) -> None:
        event = _event({"input": {"campaignId": "CAMPAIGN#c1"}})
        del event["identity"]
        result = request_campaign_report(event, ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.UNAUTHORIZED
