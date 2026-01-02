from types import SimpleNamespace

from src.handlers import campaign_operations as co


def test_get_profile_returns_item(monkeypatch):
    class DummyProfilesTable:
        def query(self, **kwargs):
            return {"Items": [{"profileId": "PROFILE#p1", "ownerAccountId": "ACCOUNT#u1"}]}

    monkeypatch.setattr(co, "profiles_table", DummyProfilesTable())
    item = co._get_profile("PROFILE#p1")
    assert item is not None and item.get("profileId") == "PROFILE#p1"


def test_get_profile_not_found(monkeypatch):
    class DummyProfilesTable:
        def query(self, **kwargs):
            return {"Items": []}

    monkeypatch.setattr(co, "profiles_table", DummyProfilesTable())
    item = co._get_profile("PROFILE#missing")
    assert item is None


def test_get_shared_campaign_handles_exception(monkeypatch):
    class Dummy:
        def get_item(self, Key):
            raise Exception("boom")

    monkeypatch.setattr(co, "shared_campaigns_table", Dummy())
    assert co._get_shared_campaign("code") is None
