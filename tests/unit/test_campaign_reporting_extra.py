from types import SimpleNamespace

from src.handlers import campaign_reporting as cr


def test_build_unit_campaign_key():
    key = cr._build_unit_campaign_key("Pack", 158, "Springfield", "IL", "Fall", 2024)
    assert key == "Pack#158#Springfield#IL#Fall#2024"


class DummyCampaignsTable:
    def __init__(self, items):
        self._items = items

    def query(self, **kwargs):
        return {"Items": self._items}


def test_get_unit_report_no_campaigns(lambda_context):
    # Monkeypatch campaigns_table to return no items
    cr.campaigns_table = DummyCampaignsTable([])

    event = {
        "arguments": {
            "unitType": "Pack",
            "unitNumber": 158,
            "city": "Springfield",
            "state": "IL",
            "campaignName": "Fall",
            "campaignYear": 2024,
            "catalogId": "catalog-1",
        },
        "identity": {"sub": "user-123"},
    }

    result = cr.get_unit_report(event, lambda_context)
    assert result["sellers"] == []
    assert result["totalSales"] == 0.0
    assert result["totalOrders"] == 0
