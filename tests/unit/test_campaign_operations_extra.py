from types import SimpleNamespace

from src.handlers import campaign_operations as co


def test_dynamo_client_proxy_delegation(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.exceptions = SimpleNamespace(TransactionCanceledException=Exception)

        def transact_write_items(self, *args, **kwargs):
            return "ok"

    monkeypatch.setattr("src.handlers.campaign_operations._get_dynamodb_client", lambda: DummyClient())
    proxy = co._DynamoClientProxy()
    assert hasattr(proxy, "exceptions")
    assert proxy.transact_write_items() == "ok"
