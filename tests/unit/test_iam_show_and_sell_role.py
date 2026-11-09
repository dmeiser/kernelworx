"""
Acceptance pin for the one Show & Sell domain role (review ruling r2 C-2):
every table named in an ACTUAL TransactWriteItems call the feature submits
must be in the role's allow-list.

The pin runs real handler flows under moto while recording DynamoDB API
calls through botocore's event system, then asserts the captured
TransactItems table set against the IAM module's show-and-sell table lists
(read from the terraform source — a drift here fails the test, not the deploy).
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Set

import boto3
import pytest

from src.handlers.unit_campaign_operations import handler as campaign_handler
from src.handlers.unit_operations import handler as unit_handler

REPO_ROOT = Path(__file__).resolve().parents[2]
IAM_MODULE = REPO_ROOT / "tofu" / "application" / "modules" / "iam" / "main.tf"

ACCOUNT_A = "ACCOUNT#user-123-456"
PROFILE_A = "PROFILE#profile-1"
CAMPAIGN_A = "CAMPAIGN#campaign-1"
CATALOG_A = "CATALOG#catalog-1"

EXPECTED_TRANSACT_TABLES = {"units", "unit_campaigns", "campaigns"}


def _role_transact_tables() -> Set[str]:
    """Parse the show-and-sell TransactWriteItems allow-list from the IAM module."""
    source = IAM_MODULE.read_text()
    match = re.search(
        r"show_and_sell_transact_keys = \[(.*?)\]",
        source,
        re.DOTALL,
    )
    assert match, "show_and_sell_transact_keys not found in iam module"
    return set(re.findall(r'"(\w+)"', match.group(1)))


class _TransactRecorder:
    """Record the table names inside actual TransactWriteItems submissions."""

    def __init__(self, original: Any) -> None:
        self._original = original
        self.tables: Set[str] = set()

    def __call__(self, TransactItems: List[Dict[str, Any]], **kwargs: Any) -> Any:
        for entry in TransactItems:
            self.tables.add(next(iter(entry.values()))["TableName"])
        return self._original(TransactItems=TransactItems, **kwargs)


def _seed_world(t: Dict[str, Any]) -> Dict[str, Any]:
    t["units"].put_item(
        Item={
            "unitId": "unit-1",
            "itemKey": "METADATA",
            "accountId": ACCOUNT_A,
            "unitType": "Pack",
            "unitNumber": "9999",
            "city": "Denver",
            "state": "CO",
            "displayName": "Pack 9999 (Denver)",
            "timezone": "America/Denver",
            "splitDefault": "EQUAL",
            "councilNeedBasis": "PHYSICAL_STOCK",
            "metadataKey": "pack|9999|denver|co",
            "adminCount": 1,
            "activeInviteCount": 0,
            "version": 1,
            "createdAt": "2026-11-01T00:00:00Z",
            "updatedAt": "2026-11-01T00:00:00Z",
            "createdByAccountId": ACCOUNT_A,
        }
    )
    t["units"].put_item(
        Item={
            "unitId": "unit-1",
            "itemKey": f"GRANT#{ACCOUNT_A}",
            "accountId": ACCOUNT_A,
            "role": "UNIT_ADMIN",
            "createdByAccountId": ACCOUNT_A,
            "createdAt": "2026-11-01T00:00:00Z",
        }
    )
    t["profiles"].put_item(
        Item={
            "ownerAccountId": ACCOUNT_A,
            "profileId": PROFILE_A,
            "displayName": "Scout Sam",
            "createdAt": "2026-11-01T00:00:00Z",
            "version": 1,
        }
    )
    t["campaigns"].put_item(
        Item={
            "profileId": PROFILE_A,
            "campaignId": CAMPAIGN_A,
            "campaignName": "Fall Sale",
            "campaignYear": 2026,
            "catalogId": CATALOG_A,
            "isActive": True,
            "version": 1,
            "createdAt": "2026-11-01T00:00:00Z",
        }
    )
    t["catalogs"].put_item(
        Item={
            "catalogId": CATALOG_A,
            "catalogName": "Council Catalog",
            "products": [],
            "version": 1,
            "createdAt": "2026-11-01T00:00:00Z",
        }
    )


def _event(field: str, arguments: Dict[str, Any], sub: str = "user-123-456") -> Dict[str, Any]:
    return {
        "arguments": arguments,
        "identity": {"sub": sub, "username": sub},
        "info": {"fieldName": field},
    }


@pytest.mark.parametrize("expected_table", sorted(EXPECTED_TRANSACT_TABLES))
def test_allow_list_covers_wave2_tables(expected_table: str) -> None:
    """The IAM transact allow-list names every table wave-2 transactions use."""
    assert expected_table in _role_transact_tables()


def test_wave2_transact_calls_stay_in_allow_list(dynamodb_table: Any, monkeypatch: Any) -> None:
    """Run the wave-2 mutation flows; every TransactWriteItems table captured
    at the wire must be inside the IAM role's transact allow-list."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    tables = {
        "units": dynamodb.Table("kernelworx-units-ue1-dev"),
        "unit_campaigns": dynamodb.Table("kernelworx-unit-campaigns-ue1-dev"),
        "campaigns": dynamodb.Table("kernelworx-campaigns-v2-ue1-dev"),
        "profiles": dynamodb.Table("kernelworx-profiles-v2-ue1-dev"),
        "catalogs": dynamodb.Table("kernelworx-catalogs-ue1-dev"),
    }
    _seed_world(tables)

    # Spy on the handlers' actual client: utils.dynamodb's singleton resource
    # (reset first so the registry rebuilds inside this mock scope), then wrap
    # transact_write_items to record the submitted plans (the actual botocore
    # call, including table names nested inside TransactItems — r2 C-2).
    from src.utils import dynamodb as dynamodb_module

    dynamodb_module.reset_singleton()
    dynamodb_module.reset_dynamodb_resource()
    client = dynamodb_module._get_dynamodb().meta.client
    recorder = _TransactRecorder(client.transact_write_items)
    monkeypatch.setattr(client, "transact_write_items", recorder)

    created = unit_handler(
        _event(
            "createUnit",
            {
                "input": {
                    "unitType": "Troop",
                    "unitNumber": "77",
                    "city": "Aurora",
                    "state": "CO",
                    "idempotencyKey": "cap-create-1",
                }
            },
        ),
        None,
    )
    assert "unit" in created
    unit_handler(_event("createUnitInvite", {"unitId": "unit-1", "idempotencyKey": "cap-invite-1"}), None)
    invite = tables["units"].query(
        KeyConditionExpression="unitId = :u",
        ExpressionAttributeValues={":u": "unit-1"},
    )["Items"]
    code = next(i["inviteCode"] for i in invite if i["itemKey"].startswith("INVITE#"))
    unit_handler(
        _event("redeemUnitInvite", {"inviteCode": code, "idempotencyKey": "cap-redeem-1"}, sub="user-789"),
        None,
    )
    uc = campaign_handler(
        _event(
            "createUnitCampaign",
            {
                "input": {
                    "unitId": "unit-1",
                    "campaignName": "S&S 2026",
                    "campaignYear": 2026,
                    "catalogId": CATALOG_A,
                    "idempotencyKey": "cap-uc-0001",
                }
            },
        ),
        None,
    )
    campaign_handler(
        _event(
            "joinUnitCampaign",
            {"joinCode": uc["joinCode"], "campaignId": CAMPAIGN_A, "idempotencyKey": "cap-join-001"},
        ),
        None,
    )

    assert recorder.tables, "no TransactWriteItems calls were captured"
    allow_list = _role_transact_tables()
    captured_slugs = set()
    for table_name in recorder.tables:
        match = re.match(r"kernelworx-([a-z0-9-]+?)(?:-v2)?-ue1-dev", table_name)
        assert match, f"unexpected table name shape: {table_name}"
        captured_slugs.add(match.group(1).replace("-", "_"))
    assert captured_slugs <= allow_list, (
        f"tables used in transactions but absent from the IAM transact allow-list: {captured_slugs - allow_list}"
    )
