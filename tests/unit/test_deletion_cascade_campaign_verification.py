"""Campaign-delete verification measures the table, not the filtered key list (#765).

``delete_user_campaigns`` builds its delete keys from a query result it filters
with ``if campaign.get("campaignId")``. The verification used to iterate that
same unfiltered result inside the ``if campaign_keys:`` guard, so it audited
the view the filter had already narrowed: when the filter emptied the key set
the verification never ran at all and the function reported success with every
campaign row still in the table, and when the filter dropped only some rows the
loop dereferenced ``campaign["campaignId"]`` on rows that were never deleted.

The verification now re-queries the campaigns table with a strongly consistent
read per profile and fails while any row remains. These tests drive the real
cascade function against a patched ``tables`` module, because the malformed row
the filter skips cannot be seeded in a real (or moto) table: ``campaignId`` is
the campaigns table sort key, so DynamoDB never returns a row without it.
"""

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from src.handlers.deletion_cascade import delete_user_campaigns
from src.utils.errors import AppError, ErrorCode

PROFILE_ID = "PROFILE#owner-1"


def _campaign(campaign_id: str) -> Dict[str, Any]:
    return {"profileId": PROFILE_ID, "campaignId": campaign_id}


def _malformed_campaign() -> Dict[str, Any]:
    """A campaign row the key filter skips: no usable ``campaignId``."""
    return {"profileId": PROFILE_ID, "campaignName": "Season 1"}


def _run(query_pages: List[Dict[str, Any]], log: MagicMock) -> Any:
    """Run ``delete_user_campaigns`` for one profile over the given Query pages."""
    with patch("src.handlers.deletion_cascade.tables") as mock_tables:
        mock_tables.campaigns.query.side_effect = query_pages
        mock_tables.campaigns.meta.client.batch_write_item.return_value = {"UnprocessedItems": {}}
        result = delete_user_campaigns([{"profileId": PROFILE_ID}], log)
        return result, mock_tables


class TestCampaignDeleteVerification:
    """The verification must fail on the settled table state, never on the pre-filtered view."""

    def test_filter_empties_keys_but_rows_remain_fails_verification(self) -> None:
        """Every row skipped by the filter still fails the cascade.

        On the old code the empty ``campaign_keys`` skipped the whole
        verification block, so this returned 0 and logged success while the row
        stayed in the table.
        """
        log = MagicMock()

        with pytest.raises(AppError) as excinfo:
            _run([{"Items": [_malformed_campaign()]}, {"Items": [_malformed_campaign()]}], log)

        assert excinfo.value.error_code == ErrorCode.INTERNAL_ERROR
        assert str(excinfo.value) == "Failed to delete campaign"
        log.error.assert_called_once_with(
            "Campaign still present after delete verification",
            profile_id=PROFILE_ID,
            campaign_id=None,
        )

    def test_skipped_row_fails_verification_even_when_other_campaigns_deleted(self) -> None:
        """A row the filter skipped cannot hide behind a successful batch delete."""
        log = MagicMock()

        with pytest.raises(AppError) as excinfo:
            _run(
                [
                    {"Items": [_campaign("CAMPAIGN#owner-1"), _malformed_campaign()]},
                    {"Items": [_malformed_campaign()]},
                ],
                log,
            )

        assert excinfo.value.error_code == ErrorCode.INTERNAL_ERROR

    def test_persisted_campaign_fails_verification(self) -> None:
        """A delete that did not land surfaces as the module's existing typed error and log line."""
        log = MagicMock()

        with pytest.raises(AppError) as excinfo:
            _run([{"Items": [_campaign("CAMPAIGN#owner-1")]}, {"Items": [_campaign("CAMPAIGN#owner-1")]}], log)

        assert excinfo.value.error_code == ErrorCode.INTERNAL_ERROR
        assert str(excinfo.value) == "Failed to delete campaign"
        log.error.assert_called_once_with(
            "Campaign still present after delete verification",
            profile_id=PROFILE_ID,
            campaign_id="CAMPAIGN#owner-1",
        )

    def test_positive_case_deletes_every_campaign_and_reports_count(self) -> None:
        """The normal path: both campaigns deleted, the settled table empty, count returned."""
        log = MagicMock()

        result, mock_tables = _run(
            [
                {"Items": [_campaign("CAMPAIGN#owner-1"), _campaign("CAMPAIGN#owner-2")]},
                {"Items": []},
            ],
            log,
        )

        assert result == 2
        assert mock_tables.campaigns.meta.client.batch_write_item.call_count == 1
        sent = mock_tables.campaigns.meta.client.batch_write_item.call_args.kwargs["RequestItems"]
        requests = [request for batch in sent.values() for request in batch]
        assert [request["DeleteRequest"]["Key"]["campaignId"] for request in requests] == [
            "CAMPAIGN#owner-1",
            "CAMPAIGN#owner-2",
        ]
        log.info.assert_any_call("Deleted user campaigns", count=2)

    def test_verification_requeries_the_base_table_strongly_consistently(self) -> None:
        """The verification is a second, strongly consistent Query on the base table."""
        log = MagicMock()

        _, mock_tables = _run([{"Items": [_campaign("CAMPAIGN#owner-1")]}, {"Items": []}], log)

        assert mock_tables.campaigns.query.call_count == 2
        verification_kwargs = mock_tables.campaigns.query.call_args.kwargs
        assert verification_kwargs["ConsistentRead"] is True
        assert verification_kwargs["KeyConditionExpression"] == "profileId = :pid"
        assert verification_kwargs["ExpressionAttributeValues"] == {":pid": PROFILE_ID}
        assert "IndexName" not in verification_kwargs

    def test_profile_without_campaigns_still_verifies(self) -> None:
        """An empty first query does not skip the check: the settled read confirms it.

        The old code issued one Query and returned 0 without verifying, so a
        campaign the eventually consistent first read had not yet surfaced would
        survive the cascade unnoticed.
        """
        log = MagicMock()

        result, mock_tables = _run([{"Items": []}, {"Items": []}], log)

        assert result == 0
        assert mock_tables.campaigns.meta.client.batch_write_item.call_count == 0
        assert mock_tables.campaigns.query.call_count == 2
        assert mock_tables.campaigns.query.call_args.kwargs["ConsistentRead"] is True
