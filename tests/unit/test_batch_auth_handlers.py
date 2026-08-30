"""End-to-end tests demonstrating batched profile authorization in handlers.

These tests use real moto DynamoDB tables (no mocking of `batch_check_profile_access`)
and instrument the underlying `BatchGetItem` calls to prove that listing and reporting
handlers perform a constant number of batched authorization reads instead of one
read per profile.
"""

from decimal import Decimal
from typing import Any, Dict

import boto3
import pytest

from src.handlers.campaign_reporting import get_unit_report
from src.handlers.list_unit_catalogs import list_unit_campaign_catalogs, list_unit_catalogs
from src.utils.dynamodb import get_dynamodb_resource


class TestCampaignReportingBatchAuth:
    """End-to-end batch authorization tests for campaign reporting."""

    def test_get_unit_report_batches_authorization(
        self,
        dynamodb_table: Any,
        lambda_context: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Unit report authorizes all profiles via BatchGetItem, not per-profile reads."""
        caller = "caller-account"
        other = "other-account"
        unit_campaign_key = "Pack#158#Springfield#IL#Fall#2024"
        catalog_id = "CATALOG#catalog-123"

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        profiles_table = dynamodb_table
        campaigns_table = dynamodb.Table("kernelworx-campaigns-v2-ue1-dev")
        orders_table = dynamodb.Table("kernelworx-orders-v2-ue1-dev")
        shares_table = dynamodb.Table("kernelworx-shares-ue1-dev")

        accessible_ids: list[str] = []

        # 10 profiles owned by caller
        for i in range(10):
            profile_id = f"PROFILE#owned-{i:03d}"
            profiles_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{caller}",
                    "profileId": profile_id,
                    "sellerName": f"Owned {i}",
                    "unitType": "Pack",
                    "unitNumber": 158,
                }
            )
            campaigns_table.put_item(
                Item={
                    "profileId": profile_id,
                    "campaignId": f"CAMPAIGN#owned-{i:03d}",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "catalogId": catalog_id,
                    "unitCampaignKey": unit_campaign_key,
                }
            )
            orders_table.put_item(
                Item={
                    "orderId": f"ORDER#owned-{i:03d}",
                    "campaignId": f"CAMPAIGN#owned-{i:03d}",
                    "profileId": profile_id,
                    "customerName": "Customer",
                    "orderDate": "2024-10-01T12:00:00Z",
                    "totalAmount": Decimal("10.00"),
                    "lineItems": [],
                }
            )
            accessible_ids.append(profile_id)

        # 10 profiles shared with caller
        for i in range(10):
            profile_id = f"PROFILE#shared-{i:03d}"
            profiles_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{other}",
                    "profileId": profile_id,
                    "sellerName": f"Shared {i}",
                    "unitType": "Pack",
                    "unitNumber": 158,
                }
            )
            campaigns_table.put_item(
                Item={
                    "profileId": profile_id,
                    "campaignId": f"CAMPAIGN#shared-{i:03d}",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "catalogId": catalog_id,
                    "unitCampaignKey": unit_campaign_key,
                }
            )
            shares_table.put_item(
                Item={
                    "profileId": profile_id,
                    "targetAccountId": f"ACCOUNT#{caller}",
                    "permissions": ["READ"],
                }
            )
            orders_table.put_item(
                Item={
                    "orderId": f"ORDER#shared-{i:03d}",
                    "campaignId": f"CAMPAIGN#shared-{i:03d}",
                    "profileId": profile_id,
                    "customerName": "Customer",
                    "orderDate": "2024-10-01T12:00:00Z",
                    "totalAmount": Decimal("10.00"),
                    "lineItems": [],
                }
            )
            accessible_ids.append(profile_id)

        # 10 profiles caller cannot access
        for i in range(10):
            profile_id = f"PROFILE#denied-{i:03d}"
            profiles_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{other}",
                    "profileId": profile_id,
                    "sellerName": f"Denied {i}",
                    "unitType": "Pack",
                    "unitNumber": 158,
                }
            )
            campaigns_table.put_item(
                Item={
                    "profileId": profile_id,
                    "campaignId": f"CAMPAIGN#denied-{i:03d}",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "catalogId": catalog_id,
                    "unitCampaignKey": unit_campaign_key,
                }
            )

        # Instrument BatchGetItem on the resource used by batch_check_profile_access.
        resource = get_dynamodb_resource()
        original_batch_get_item = resource.batch_get_item
        batch_get_item_calls = 0

        def counted_batch_get_item(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            nonlocal batch_get_item_calls
            batch_get_item_calls += 1
            return original_batch_get_item(*args, **kwargs)

        monkeypatch.setattr(resource, "batch_get_item", counted_batch_get_item)
        monkeypatch.setattr("src.utils.auth.get_dynamodb_resource", lambda: resource)

        event = {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "city": "Springfield",
                "state": "IL",
                "campaignName": "Fall",
                "campaignYear": 2024,
                "catalogId": catalog_id,
            },
            "identity": {"sub": caller},
        }

        result = get_unit_report(event, lambda_context)

        # 30 campaigns were found; only 20 are accessible.
        assert len(result["sellers"]) == 20
        assert result["totalOrders"] == 20
        assert result["totalSales"] == 200.0

        # Authorization should require exactly two BatchGetItem calls:
        # one for ownership checks and one for share checks.
        assert batch_get_item_calls == 2


class TestListUnitCatalogsBatchAuth:
    """End-to-end batch authorization tests for list_unit_catalogs."""

    def test_list_unit_catalogs_batches_authorization(
        self,
        dynamodb_table: Any,
        lambda_context: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """list_unit_catalogs authorizes all unit profiles via BatchGetItem."""
        caller = "caller-account"
        other = "other-account"

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        profiles_table = dynamodb_table
        campaigns_table = dynamodb.Table("kernelworx-campaigns-v2-ue1-dev")
        catalogs_table = dynamodb.Table("kernelworx-catalogs-ue1-dev")
        shares_table = dynamodb.Table("kernelworx-shares-ue1-dev")

        # Seed a catalog used by accessible profiles.
        catalogs_table.put_item(
            Item={
                "catalogId": "catalog-123",
                "catalogName": "Alpha Catalog",
                "isActive": True,
            }
        )

        # 10 owned + 10 shared = accessible; 10 denied.
        for i in range(10):
            profile_id = f"PROFILE#owned-{i:03d}"
            profiles_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{caller}",
                    "profileId": profile_id,
                    "sellerName": f"Owned {i}",
                    "unitType": "Pack",
                    "unitNumber": 158,
                }
            )
            campaigns_table.put_item(
                Item={
                    "profileId": profile_id,
                    "campaignId": f"CAMPAIGN#owned-{i:03d}",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "catalogId": "catalog-123",
                }
            )

        for i in range(10):
            profile_id = f"PROFILE#shared-{i:03d}"
            profiles_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{other}",
                    "profileId": profile_id,
                    "sellerName": f"Shared {i}",
                    "unitType": "Pack",
                    "unitNumber": 158,
                }
            )
            campaigns_table.put_item(
                Item={
                    "profileId": profile_id,
                    "campaignId": f"CAMPAIGN#shared-{i:03d}",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "catalogId": "catalog-123",
                }
            )
            shares_table.put_item(
                Item={
                    "profileId": profile_id,
                    "targetAccountId": f"ACCOUNT#{caller}",
                    "permissions": ["READ"],
                }
            )

        for i in range(10):
            profile_id = f"PROFILE#denied-{i:03d}"
            profiles_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{other}",
                    "profileId": profile_id,
                    "sellerName": f"Denied {i}",
                    "unitType": "Pack",
                    "unitNumber": 158,
                }
            )
            campaigns_table.put_item(
                Item={
                    "profileId": profile_id,
                    "campaignId": f"CAMPAIGN#denied-{i:03d}",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "catalogId": "catalog-123",
                }
            )

        resource = get_dynamodb_resource()
        original_batch_get_item = resource.batch_get_item
        batch_get_item_calls = 0

        def counted_batch_get_item(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            nonlocal batch_get_item_calls
            batch_get_item_calls += 1
            return original_batch_get_item(*args, **kwargs)

        monkeypatch.setattr(resource, "batch_get_item", counted_batch_get_item)
        monkeypatch.setattr("src.utils.auth.get_dynamodb_resource", lambda: resource)

        event = {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "campaignName": "Fall",
                "campaignYear": 2024,
            },
            "identity": {"sub": caller},
        }

        result = list_unit_catalogs(event, lambda_context)

        assert len(result) == 1
        assert result[0]["catalogId"] == "catalog-123"
        # One ownership BatchGetItem + one share BatchGetItem.
        assert batch_get_item_calls == 2


class TestListUnitCampaignCatalogsBatchAuth:
    """End-to-end batch authorization tests for list_unit_campaign_catalogs."""

    def test_list_unit_campaign_catalogs_batches_authorization(
        self,
        dynamodb_table: Any,
        lambda_context: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """list_unit_campaign_catalogs authorizes all campaign profiles via BatchGetItem."""
        caller = "caller-account"
        other = "other-account"
        unit_campaign_key = "Pack#158#Springfield#IL#Fall#2024"

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        profiles_table = dynamodb_table
        campaigns_table = dynamodb.Table("kernelworx-campaigns-v2-ue1-dev")
        catalogs_table = dynamodb.Table("kernelworx-catalogs-ue1-dev")
        shares_table = dynamodb.Table("kernelworx-shares-ue1-dev")

        catalogs_table.put_item(
            Item={
                "catalogId": "catalog-123",
                "catalogName": "Alpha Catalog",
                "isActive": True,
            }
        )

        for i in range(10):
            profile_id = f"PROFILE#owned-{i:03d}"
            profiles_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{caller}",
                    "profileId": profile_id,
                    "sellerName": f"Owned {i}",
                    "unitType": "Pack",
                    "unitNumber": 158,
                }
            )
            campaigns_table.put_item(
                Item={
                    "profileId": profile_id,
                    "campaignId": f"CAMPAIGN#owned-{i:03d}",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "catalogId": "catalog-123",
                    "unitCampaignKey": unit_campaign_key,
                }
            )

        for i in range(10):
            profile_id = f"PROFILE#shared-{i:03d}"
            profiles_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{other}",
                    "profileId": profile_id,
                    "sellerName": f"Shared {i}",
                    "unitType": "Pack",
                    "unitNumber": 158,
                }
            )
            campaigns_table.put_item(
                Item={
                    "profileId": profile_id,
                    "campaignId": f"CAMPAIGN#shared-{i:03d}",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "catalogId": "catalog-123",
                    "unitCampaignKey": unit_campaign_key,
                }
            )
            shares_table.put_item(
                Item={
                    "profileId": profile_id,
                    "targetAccountId": f"ACCOUNT#{caller}",
                    "permissions": ["READ"],
                }
            )

        for i in range(10):
            profile_id = f"PROFILE#denied-{i:03d}"
            profiles_table.put_item(
                Item={
                    "ownerAccountId": f"ACCOUNT#{other}",
                    "profileId": profile_id,
                    "sellerName": f"Denied {i}",
                    "unitType": "Pack",
                    "unitNumber": 158,
                }
            )
            campaigns_table.put_item(
                Item={
                    "profileId": profile_id,
                    "campaignId": f"CAMPAIGN#denied-{i:03d}",
                    "campaignName": "Fall",
                    "campaignYear": 2024,
                    "catalogId": "catalog-123",
                    "unitCampaignKey": unit_campaign_key,
                }
            )

        resource = get_dynamodb_resource()
        original_batch_get_item = resource.batch_get_item
        batch_get_item_calls = 0

        def counted_batch_get_item(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            nonlocal batch_get_item_calls
            batch_get_item_calls += 1
            return original_batch_get_item(*args, **kwargs)

        monkeypatch.setattr(resource, "batch_get_item", counted_batch_get_item)
        monkeypatch.setattr("src.utils.auth.get_dynamodb_resource", lambda: resource)

        event = {
            "arguments": {
                "unitType": "Pack",
                "unitNumber": 158,
                "city": "Springfield",
                "state": "IL",
                "campaignName": "Fall",
                "campaignYear": 2024,
            },
            "identity": {"sub": caller},
        }

        result = list_unit_campaign_catalogs(event, lambda_context)

        assert len(result) == 1
        assert result[0]["catalogId"] == "catalog-123"
        # One ownership BatchGetItem + one share BatchGetItem.
        assert batch_get_item_calls == 2
