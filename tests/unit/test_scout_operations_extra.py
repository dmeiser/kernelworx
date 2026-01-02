import boto3

from src.handlers import scout_operations as so


class DummyDynamoClient:
    def transact_write_items(self, *args, **kwargs):
        return None


def test_create_seller_profile_invalid_unit_number(monkeypatch):
    # Patch boto3.client to avoid real AWS calls
    monkeypatch.setattr(boto3, "client", lambda service: DummyDynamoClient())

    event = {"arguments": {"input": {"sellerName": "Joe", "unitNumber": "not-an-int"}}, "identity": {"sub": "acct-1"}}
    result = so.create_seller_profile(event, None)
    # Invalid unitNumber should be skipped and not included in response
    assert "unitNumber" not in result
