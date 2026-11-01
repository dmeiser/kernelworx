"""Unit tests for the single ``ORDER#<campaignId>#<suffix>`` key grammar (DRY-11).

The orders table sort key embeds the campaign's bare id so the public receipt
link can address one order with a single strongly consistent ``GetItem``. The
write path mints it and the receipt read re-derives it, so both halves live in
``src/utils/order_keys.py`` and are tested here directly: the builder must accept
either campaign-id spelling and refuse any segment that carries its own ``#``,
and the parser must refuse legacy two-part ``ORDER#<uuid>`` ids rather than
guessing a campaign for them.
"""

import pytest

from src.handlers import public_orders_receipt as receipt
from src.utils.errors import AppError, ErrorCode
from src.utils.order_keys import ORDER_ID_PREFIX, build_order_id, parse_order_id


class TestBuildOrderId:
    def test_accepts_both_campaign_id_spellings(self) -> None:
        assert build_order_id("CAMPAIGN#c1", "s1") == "ORDER#c1#s1"
        assert build_order_id("c1", "s1") == "ORDER#c1#s1"

    def test_refuses_an_empty_or_missing_campaign_id(self) -> None:
        assert build_order_id("", "s1") is None
        assert build_order_id(None, "s1") is None
        assert build_order_id("CAMPAIGN#", "s1") is None

    def test_refuses_a_campaign_id_that_is_not_a_single_segment(self) -> None:
        # A caller that concatenates a whole order id into the campaign segment
        # must not get a plausible-looking key back.
        assert build_order_id("CAMPAIGN#a#b", "s1") is None

    def test_refuses_an_empty_or_non_string_suffix(self) -> None:
        assert build_order_id("CAMPAIGN#c1", "") is None
        assert build_order_id("CAMPAIGN#c1", None) is None
        assert build_order_id("CAMPAIGN#c1", 7) is None

    def test_refuses_a_suffix_carrying_its_own_separator(self) -> None:
        assert build_order_id("CAMPAIGN#c1", "s1#extra") is None

    def test_the_prefix_constant_matches_the_minted_key(self) -> None:
        assert build_order_id("c1", "s1") == f"{ORDER_ID_PREFIX}#c1#s1"


class TestParseOrderId:
    def test_splits_a_campaign_keyed_id(self) -> None:
        assert parse_order_id("ORDER#c1#s1") == ("c1", "s1")

    def test_refuses_a_legacy_two_part_id(self) -> None:
        """Legacy ``ORDER#<uuid>`` rows have no embedded campaign to resolve."""
        assert parse_order_id("ORDER#550e8400-e29b-41d4-a716-446655440000") is None

    def test_refuses_a_non_order_or_non_string_value(self) -> None:
        assert parse_order_id("CAMPAIGN#c1#s1") is None
        assert parse_order_id("c1#s1") is None
        assert parse_order_id(None) is None
        assert parse_order_id(7) is None

    def test_refuses_empty_or_extra_segments(self) -> None:
        assert parse_order_id("ORDER##s1") is None
        assert parse_order_id("ORDER#c1#") is None
        assert parse_order_id("ORDER#c1#s1#extra") is None

    @pytest.mark.parametrize("order_id", ["ORDER#c1#s1", "ORDER#uuid-like-suffix#a-b-c"])
    def test_round_trips_through_the_builder(self, order_id: str) -> None:
        campaign, suffix = parse_order_id(order_id) or ("", "")
        assert build_order_id(campaign, suffix) == order_id


class TestGrammarIsShared:
    def test_the_receipt_read_uses_this_module(self) -> None:
        """The receipt handler must not re-implement the grammar (DRY-11)."""
        assert receipt.build_order_id is build_order_id
        assert receipt.parse_order_id is parse_order_id

    def test_the_receipt_key_builder_rebuilds_the_split_url_segments(self) -> None:
        """The URL carries the id split at ``#``; re-joining must be exact."""
        campaign_id, order_id = receipt._order_key({"campaignId": "CAMPAIGN#c1", "orderSuffix": "s1"})
        assert campaign_id == "CAMPAIGN#c1"
        assert order_id == "ORDER#c1#s1"
        assert parse_order_id(order_id) == ("c1", "s1")

    def test_the_receipt_read_refuses_a_legacy_id_before_any_datastore_call(self) -> None:
        with pytest.raises(AppError) as exc:
            receipt._order_key({"campaignId": "CAMPAIGN#c1", "orderSuffix": "ORDER#c1#s1"})
        assert exc.value.error_code is ErrorCode.NOT_FOUND
