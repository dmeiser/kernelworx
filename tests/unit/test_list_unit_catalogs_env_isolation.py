"""Environment-isolation tests for the listUnitCatalogs resolver (#561).

These drive the real ``list_unit_catalogs`` handler against a moto-backed
DynamoDB that holds a prod stack *and* a dev catalogs table side by side, so the
assertions describe what a signed-in end user of the AppSync query actually
receives (the resolver's return payload) and which physical table was read.

The bug under test: the handler used to resolve the catalogs table name from
``os.environ`` with a hard-coded dev table name as a "fallback", which read as a
live safety net but could never be reached (``tables.catalogs`` raises first).
The fix routes resolution through the shared ``tables`` accessor, so an
environment-variable mistake surfaces as a loud failure naming the variable
instead of a plausible-but-wrong cross-environment read.
"""

import json
from types import SimpleNamespace
from typing import Any, Dict, Generator, List
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

from src.handlers.list_unit_catalogs import _get_catalogs_table_name, list_unit_campaign_catalogs, list_unit_catalogs
from src.utils.dynamodb import get_dynamodb_resource, reset_dynamodb_resource, reset_singleton
from tests.unit.table_schemas import (
    create_campaigns_table_schema,
    create_catalogs_table_schema,
    create_profiles_table_schema,
)

CALLER = "ACCOUNT#acct-caller"
DEV_CATALOGS_TABLE = "kernelworx-catalogs-ue1-dev"
PROD_CATALOGS_TABLE = "kernelworx-catalogs-ue1-prod"
PROD_PROFILES_TABLE = "kernelworx-profiles-v2-ue1-prod"
PROD_CAMPAIGNS_TABLE = "kernelworx-campaigns-v2-ue1-prod"

# Catalog ids seeded into both environments. The dev table holds a *decoy* row
# under the same catalogId the prod campaign points at, so a silent read of the
# dev table is visible in the resolver payload the user receives.
CATALOG_1 = "catalog-0001"
CATALOG_2 = "catalog-0002"


def _event(campaign_name: str = "Fall", campaign_year: int = 2026) -> Dict[str, Any]:
    """Build the AppSync resolver event a client sends for listUnitCatalogs."""
    return {
        "arguments": {
            "unitType": "Pack",
            "unitNumber": 158,
            "campaignName": campaign_name,
            "campaignYear": campaign_year,
        },
        "identity": {"sub": "acct-caller"},
    }


def _event_unit_campaign(campaign_name: str = "Fall", campaign_year: int = 2026) -> Dict[str, Any]:
    """Build the AppSync resolver event for the unit+campaign variant."""
    return {
        "arguments": {
            "unitType": "Pack",
            "unitNumber": 158,
            "city": "Springfield",
            "state": "IL",
            "campaignName": campaign_name,
            "campaignYear": campaign_year,
        },
        "identity": {"sub": "acct-caller"},
    }


def _create_table(dynamodb: Any, schema: Dict[str, Any], table_name: str) -> Any:
    dynamodb.create_table(**{**schema, "TableName": table_name})
    return dynamodb.Table(table_name)


def _deploy_two_environment_stack(monkeypatch: pytest.MonkeyPatch) -> Generator[SimpleNamespace, None, None]:
    """Create a prod stack plus a decoy dev catalogs table and wire the env vars the Lambda module sets."""
    with mock_aws():
        reset_singleton()
        reset_dynamodb_resource()
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        _create_table(dynamodb, create_profiles_table_schema(), PROD_PROFILES_TABLE)
        _create_table(dynamodb, create_campaigns_table_schema(), PROD_CAMPAIGNS_TABLE)
        _create_table(dynamodb, create_catalogs_table_schema(), PROD_CATALOGS_TABLE)
        _create_table(dynamodb, create_catalogs_table_schema(), DEV_CATALOGS_TABLE)

        # Unit 158 Pack: two profiles owned by the caller, each with a Fall 2026 campaign.
        profiles = dynamodb.Table(PROD_PROFILES_TABLE)
        profiles.put_item(
            Item={
                "ownerAccountId": CALLER,
                "profileId": "PROFILE#alpha",
                "sellerName": "Scout Alpha",
                "unitType": "Pack",
                "unitNumber": 158,
            }
        )
        profiles.put_item(
            Item={
                "ownerAccountId": CALLER,
                "profileId": "PROFILE#bravo",
                "sellerName": "Scout Bravo",
                "unitType": "Pack",
                "unitNumber": 158,
            }
        )
        campaigns = dynamodb.Table(PROD_CAMPAIGNS_TABLE)
        campaigns.put_item(
            Item={
                "profileId": "PROFILE#alpha",
                "campaignId": "CAMPAIGN#alpha-fall",
                "campaignName": "Fall",
                "campaignYear": 2026,
                "catalogId": CATALOG_1,
                "unitCampaignKey": "Pack#158#Springfield#IL#Fall#2026",
            }
        )
        campaigns.put_item(
            Item={
                "profileId": "PROFILE#bravo",
                "campaignId": "CAMPAIGN#bravo-fall",
                "campaignName": "Fall",
                "campaignYear": 2026,
                "catalogId": CATALOG_2,
                "unitCampaignKey": "Pack#158#Springfield#IL#Fall#2026",
            }
        )

        prod_catalogs = dynamodb.Table(PROD_CATALOGS_TABLE)
        prod_catalogs.put_item(Item={"catalogId": CATALOG_1, "catalogName": "PROD Winter Gear"})
        prod_catalogs.put_item(Item={"catalogId": CATALOG_2, "catalogName": "PROD Uniforms"})

        dev_catalogs = dynamodb.Table(DEV_CATALOGS_TABLE)
        # Decoys: same catalogIds, dev content. A cross-environment read is visible in the payload.
        dev_catalogs.put_item(Item={"catalogId": CATALOG_1, "catalogName": "DEV stale copy of catalog-0001"})
        dev_catalogs.put_item(Item={"catalogId": CATALOG_2, "catalogName": "DEV stale copy of catalog-0002"})

        monkeypatch.setenv("PROFILES_TABLE_NAME", PROD_PROFILES_TABLE)
        monkeypatch.setenv("CAMPAIGNS_TABLE_NAME", PROD_CAMPAIGNS_TABLE)
        monkeypatch.setenv("CATALOGS_TABLE_NAME", PROD_CATALOGS_TABLE)

        # Record every physical table the resolver reads catalogs from. Registered on the
        # handler's own cached DynamoDB resource so the recording covers handler calls.
        batch_get_tables: List[str] = []

        def _record_batch_get(model: Any, params: Dict[str, Any], **_: Any) -> None:
            body = params.get("body")
            if body:
                batch_get_tables.extend(json.loads(body)["RequestItems"])

        get_dynamodb_resource().meta.client.meta.events.register("before-call.dynamodb.BatchGetItem", _record_batch_get)

        yield SimpleNamespace(batch_get_tables=batch_get_tables, dynamodb=dynamodb)

        reset_singleton()
        reset_dynamodb_resource()


@pytest.fixture
def two_environment_stack(monkeypatch: pytest.MonkeyPatch) -> Generator[SimpleNamespace, None, None]:
    yield from _deploy_two_environment_stack(monkeypatch)


@pytest.fixture
def lambda_context() -> MagicMock:
    """Mock Lambda context as AppSync supplies it."""
    context = MagicMock()
    context.aws_request_id = "test-request-id"
    context.function_name = "list_unit_catalogs"
    return context


class TestListUnitCatalogsEnvironmentIsolation:
    """The catalogs table the resolver reads must be the one the deployed environment names."""

    def test_resolver_returns_catalogs_from_the_deployed_environment_table(
        self, two_environment_stack: SimpleNamespace, lambda_context: MagicMock
    ) -> None:
        """A prod deployment returns prod catalog data, not the dev table's rows."""
        result = list_unit_catalogs(_event(), lambda_context)

        assert [c["catalogName"] for c in result] == ["PROD Uniforms", "PROD Winter Gear"]
        assert PROD_CATALOGS_TABLE in two_environment_stack.batch_get_tables
        assert DEV_CATALOGS_TABLE not in two_environment_stack.batch_get_tables

    def test_unit_campaign_resolver_returns_catalogs_from_the_deployed_environment_table(
        self, two_environment_stack: SimpleNamespace, lambda_context: MagicMock
    ) -> None:
        """The unit+campaign resolver resolves the same table through the same path."""
        result = list_unit_campaign_catalogs(_event_unit_campaign(), lambda_context)

        assert [c["catalogName"] for c in result] == ["PROD Uniforms", "PROD Winter Gear"]
        assert PROD_CATALOGS_TABLE in two_environment_stack.batch_get_tables
        assert DEV_CATALOGS_TABLE not in two_environment_stack.batch_get_tables

    def test_missing_env_var_fails_loud_instead_of_reading_dev_table(
        self,
        two_environment_stack: SimpleNamespace,
        lambda_context: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A missing CATALOGS_TABLE_NAME surfaces as an error naming the variable, reading no table at all."""
        monkeypatch.delenv("CATALOGS_TABLE_NAME", raising=False)
        reset_singleton()  # drop the accessor cache so resolution re-reads the (now absent) env var

        result = list_unit_catalogs(_event(), lambda_context)

        assert result == {
            "__isError": True,
            "errorCode": "INTERNAL_ERROR",
            "message": "Failed to list unit catalogs",
        }
        # The Lambda log line names the missing variable (this is what a deploy mistake surfaces as).
        logged = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
        assert any(
            entry.get("level") == "ERROR"
            and "Required environment variable 'CATALOGS_TABLE_NAME' is not set" == entry.get("error")
            for entry in logged
        )
        # No catalogs were read from any environment (neither the deployed one nor the dev table).
        catalogs_reads = [t for t in two_environment_stack.batch_get_tables if "catalogs" in t]
        assert catalogs_reads == []

    def test_table_name_resolution_matches_the_shared_accessor(
        self, two_environment_stack: SimpleNamespace
    ) -> None:
        """The name used for BatchGetItem is exactly the shared accessor's resolved table name."""
        from src.utils.dynamodb import tables

        assert _get_catalogs_table_name() == PROD_CATALOGS_TABLE
        assert _get_catalogs_table_name() == tables.catalogs.table_name
