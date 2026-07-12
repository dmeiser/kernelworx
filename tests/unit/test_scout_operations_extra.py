import boto3
import pytest

from src.handlers import scout_operations as so
from src.utils.errors import AppError, ErrorCode


class DummyDynamoClient:
    def transact_write_items(self, *args, **kwargs):
        return None


def test_create_seller_profile_invalid_unit_number(monkeypatch):
    # Patch boto3.client to avoid real AWS calls
    monkeypatch.setattr(boto3, "client", lambda service: DummyDynamoClient())

    event = {"arguments": {"input": {"sellerName": "Joe", "unitNumber": "not-an-int"}}, "identity": {"sub": "acct-1"}}
    with pytest.raises(AppError) as exc_info:
        so.create_seller_profile(event, None)

    assert exc_info.value.error_code == ErrorCode.INVALID_INPUT
