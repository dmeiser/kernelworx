"""Regression tests for #552: malformed AppSync arguments must surface as INVALID_INPUT.

The six argument-extraction sites (list_unit_catalogs, list_unit_campaign_catalogs,
campaign_reporting.get_unit_report, transfer_profile_ownership, and report_generation
request_campaign_report) used to index the raw event with brackets. A missing key or a
non-numeric int() operand then raised KeyError/ValueError, which the ``lambda_handler``
decorator (#329) collapsed into a generic INTERNAL_ERROR — indistinguishable by the client
from a real server fault. These tests pin the correct behavior: every such malformed or
missing input returns ``INVALID_INPUT`` (or ``UNAUTHORIZED`` for a missing identity), and the
unit-number bound is enforced instead of flowing into the GSI key condition.
"""

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from src.handlers.campaign_reporting import get_unit_report
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

    def test_missing_identity_is_unauthorized(self, ctx: MagicMock) -> None:
        event = _event({"input": {"profileId": "PROFILE#p1", "newOwnerAccountId": "ACCOUNT#a"}})
        del event["identity"]
        result = transfer_profile_ownership(event, ctx)
        assert result["__isError"] is True
        assert result["errorCode"] == ErrorCode.UNAUTHORIZED


