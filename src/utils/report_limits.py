"""Shared materialisation ceiling for the report handlers.

Both report paths materialise one in-memory record per order, with its line
items: the unit report returns every order and every line item for the whole
unit in a single response (#577), and the campaign report builds the entire
CSV/Excel output in memory (#533). Neither path is bounded, so the largest
units and campaigns - exactly the case the reports exist for - run out of the
Lambda's memory and time budget and surface as a generic internal error.

The ceiling is therefore measured in the bytes an order graph serialises to,
not in order count: what drives the size of a report is the graph (orders *and*
line items per order), and a plain count cannot express that - a few hundred
wide orders and a few thousand narrow ones occupy the same budget and are very
different amounts of work. Both handlers charge the same measurement against the
same budget and refuse the order that would cross it, so the two report paths
cannot drift apart and neither ever materialises more than the budget allows.
"""

import json
from typing import Any, Mapping

try:  # pragma: no cover
    from utils.errors import AppError, ErrorCode
    from utils.logging import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.errors import AppError, ErrorCode
    from ..utils.logging import get_logger

logger = get_logger(__name__)

# AppSync truncates a single Lambda resolver response at 5 MB, and the unit
# report returns the whole order graph in that one response. A fifth of the
# limit is the ceiling: the measurement below already charges the full stored
# order rather than only the fields a report returns, so it is an upper bound
# on the response, and the rest of the limit covers the response envelope and
# GraphQL transport overhead.
APPSYNC_RESPONSE_LIMIT_BYTES = 5_000_000
MAX_REPORT_GRAPH_BYTES = APPSYNC_RESPONSE_LIMIT_BYTES // 5


def order_graph_bytes(order: Mapping[str, Any]) -> int:
    """Return the serialised size in bytes of one stored order and its line items.

    Measured, not estimated: what a report costs is the bytes its order graph
    serialises to, and a per-field estimate of that would silently undercharge
    the moment the order gained a field, which is how a ceiling quietly becomes
    fiction. Measuring the order itself cannot drift from the shape of the data
    the handlers actually read.

    The measurement is taken over the stored order rather than over the shape a
    particular report projects from it, so it bounds both report paths: the
    campaign report materialises the stored order itself, and the unit report
    materialises a subset of these fields. Values DynamoDB returns that JSON
    cannot represent natively (``Decimal``, sets) serialise as their string
    form, which is never shorter than the number the response carries, and
    non-ASCII is escaped, so neither can make the charge read low.
    """
    return len(json.dumps(order, default=str).encode("utf-8"))


def report_too_large_error(subject: str, max_bytes: int = MAX_REPORT_GRAPH_BYTES) -> AppError:
    """Return the typed error raised when a report exceeds its order-graph budget.

    Args:
        subject: Human-readable owner of the report, e.g. ``"This unit's"``.
        max_bytes: The budget that was crossed, reported in the message so it
            matches the ceiling actually enforced.

    Returns:
        An ``AppError`` carrying the ``RESOURCE_BUSY`` code the issue specifies
        (#577); the AppSync Lambda resolver surfaces it in the GraphQL
        ``extensions.errorCode`` and the frontend renders the message as-is.
    """
    return AppError(
        ErrorCode.RESOURCE_BUSY,
        f"{subject} report is too large to generate: its order details exceed {max_bytes / 1_000_000:.1f} MB.",
    )


class OrderGraphBudget:
    """Byte budget for the order graph a single report may materialise.

    Callers charge each order *before* expanding it, so a report that is going
    to be refused never pays for the work it cannot return.
    """

    def __init__(self, subject: str, max_bytes: int = MAX_REPORT_GRAPH_BYTES) -> None:
        self._subject = subject
        self._max_bytes = max_bytes
        self._spent = 0

    def admit(self, order: Mapping[str, Any]) -> None:
        """Charge one order, refusing the order that would cross the budget."""
        self._spent += order_graph_bytes(order)
        if self._spent > self._max_bytes:
            logger.warning(
                "Report order-graph budget exhausted",
                subject=self._subject,
                spentBytes=self._spent,
                maxBytes=self._max_bytes,
            )
            raise report_too_large_error(self._subject, self._max_bytes)
