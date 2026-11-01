"""Single source of truth for the ``ORDER#<campaignId>#<suffix>`` sort-key grammar.

The orders table is keyed ``{campaignId, orderId}``, and the sort key embeds the
campaign's bare id so a buyer-facing link can address one order with a single
strongly consistent ``GetItem`` — no GSI fallback, because a capability lookup
that reads an eventually consistent index turns a typo into a disclosure race.
The same grammar is minted by the write path and re-derived by the receipt read,
so it has exactly one owner here (DRY-11).

Grammar:

- ``ORDER#`` then the campaign id with its ``CAMPAIGN#`` prefix stripped, then
  ``#``, then the suffix the write path minted (``util.autoId()`` in
  ``create_order_fn.js``).
- Legacy rows carry only ``ORDER#<uuid>``. They have no embedded campaign id, so
  they cannot be addressed through the campaign-keyed path at all; the parser
  returns ``None`` for them rather than guessing a campaign.

Both helpers accept the prefixed and the bare spelling of a campaign id, because
both cross the AppSync payload boundary; neither spelling is ever rejected.
"""

from typing import Any, Optional, Tuple

from .ids import ensure_campaign_id, strip_prefix

#: The sort-key prefix for an order row.
ORDER_ID_PREFIX = "ORDER"

#: A campaign-keyed order id splits into exactly three ``#``-separated parts.
_ORDER_ID_PARTS = 3


def build_order_id(campaign_id: Any, suffix: Any) -> Optional[str]:
    """Return the orders sort key for one campaign + suffix, or ``None``.

    ``None`` means the segments cannot form a key: a missing/empty campaign id or
    suffix, or a segment carrying its own ``#``. The second rule is what keeps a
    caller who concatenates a whole order id into one URL segment from producing
    a plausible-looking key.
    """
    campaign_bare = strip_prefix(ensure_campaign_id(campaign_id))
    if not campaign_bare or "#" in campaign_bare:
        return None
    if not isinstance(suffix, str) or not suffix or "#" in suffix:
        return None
    return f"{ORDER_ID_PREFIX}#{campaign_bare}#{suffix}"


def parse_order_id(order_id: Any) -> Optional[Tuple[str, str]]:
    """Split a campaign-keyed order id into ``(bare campaign id, suffix)``.

    ``None`` means the value is not a campaign-keyed order id: not a string, not
    an ``ORDER#`` row, a legacy two-part id, or a segment that is empty.
    """
    if not isinstance(order_id, str) or not order_id.startswith(f"{ORDER_ID_PREFIX}#"):
        return None
    parts = order_id.split("#")
    if len(parts) != _ORDER_ID_PARTS or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]
