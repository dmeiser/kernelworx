import builtins
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.handlers.report_generation import request_campaign_report


class DummyTable:
    def __init__(self, items):
        self._items = items

    def query(self, **kwargs):
        # For _get_campaign (campaignId-index) return first item
        index = kwargs.get("IndexName")
        if index == "campaignId-index":
            return {"Items": [self._items[0]]} if self._items else {"Items": []}
        # For orders query (PK=campaignId)
        return {"Items": self._items}


class DummyS3Client:
    def __init__(self):
        self.put_calls = []

    def put_object(self, Bucket, Key, Body, ContentType):
        self.put_calls.append((Bucket, Key, Body, ContentType))

    def generate_presigned_url(self, OperationName, Params, ExpiresIn):
        return f"https://example.com/{Params['Key']}"


def make_event(campaign_id, caller_sub, format="xlsx"):
    return {
        "arguments": {"input": {"campaignId": campaign_id, "format": format}},
        "identity": {"sub": caller_sub},
        "requestId": "test-req",
    }


def test_request_campaign_report_happy_path(monkeypatch):
    # Prepare a campaign item and some orders
    campaign_id = "CAMPAIGN#c-123"
    profile_id = "PROFILE#p-1"
    campaign_item = {"campaignId": campaign_id, "profileId": profile_id, "campaignName": "FALL"}
    orders = [{"orderId": "ORDER#o1", "campaignId": campaign_id, "customerName": "Alice", "lineItems": []}]

    # Patch the tables
    monkeypatch.setattr("src.handlers.report_generation.get_campaigns_table", lambda: DummyTable([campaign_item]))
    monkeypatch.setattr("src.handlers.report_generation.get_orders_table", lambda: DummyTable(orders))

    # Patch s3 client used in module
    dummy_s3 = DummyS3Client()
    monkeypatch.setattr("src.handlers.report_generation.s3_client", dummy_s3)

    # Patch check_profile_access to allow
    monkeypatch.setattr("src.handlers.report_generation.check_profile_access", lambda caller, pid, action: True)

    event = make_event(campaign_id, "acct-1")

    res = request_campaign_report(event, SimpleNamespace())

    assert res["campaignId"] == campaign_id
    assert res["profileId"] == profile_id
    assert res["status"] == "COMPLETED"
    assert res["reportId"].startswith("REPORT#")
    assert res["reportUrl"].startswith("https://example.com/")


def test_request_campaign_report_csv_format(monkeypatch):
    campaign_id = "CAMPAIGN#c-234"
    profile_id = "PROFILE#p-2"
    campaign_item = {"campaignId": campaign_id, "profileId": profile_id, "campaignName": "SPRING"}

    monkeypatch.setattr("src.handlers.report_generation.get_campaigns_table", lambda: DummyTable([campaign_item]))
    monkeypatch.setattr("src.handlers.report_generation.get_orders_table", lambda: DummyTable([]))

    dummy_s3 = DummyS3Client()
    monkeypatch.setattr("src.handlers.report_generation.s3_client", dummy_s3)

    monkeypatch.setattr("src.handlers.report_generation.check_profile_access", lambda caller, pid, action: True)

    event = make_event(campaign_id, "acct-2", format="csv")
    res = request_campaign_report(event, SimpleNamespace())

    assert res["reportId"].startswith("REPORT#")
    assert res["reportUrl"].endswith(".csv") or ".csv" in res["reportUrl"]
