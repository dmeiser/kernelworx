from typing import Any

import boto3
from moto import mock_aws

from src.handlers import list_unit_catalogs as lul


def test_get_profiles_table_uses_monkeypatch(monkeypatch: Any) -> None:
    dummy = object()
    monkeypatch.setattr(lul, "profiles_table", dummy)
    assert lul._get_profiles_table() is dummy


def test_get_profiles_table_fallback_uses_moto(aws_credentials: None, dynamodb_table: Any) -> None:
    # Ensure module-level override is None
    lul.profiles_table = None

    # When moto fixture created tables, fallback should return a real Table object
    table = lul._get_profiles_table()
    assert getattr(table, "table_name", "") == "kernelworx-profiles-v2-ue1-dev"
