"""Shared materialisation ceiling for the report handlers.

Both report paths materialise one in-memory record per order, with its line
items: the unit report returns every order and every line item for the whole
unit in a single resolver response (#577), and the campaign report holds every
order of one campaign and builds the whole CSV/Excel output from them in memory
(#533). Neither path is bounded, so the largest units and campaigns - exactly
the case the reports exist for - run out of the Lambda's memory and time budget
and surface as a generic internal error.

The ceiling is measured in the bytes an order graph serialises to, not in order
count: what drives the size of a report is the graph (orders *and* line items
per order), and a plain count cannot express that - a few hundred wide orders
and a few thousand narrow ones occupy the same budget and are very different
amounts of work. Both handlers charge the same measurement, through the same
budget, against the record they are about to accumulate, so the two report paths
cannot drift apart and neither ever holds more than its ceiling allows.

One measurement, one budget and one error shape, but not one number: the two
paths are bounded by different resources and no single value serves both. The
unit report's whole order graph *is* its resolver response, so its ceiling comes
out of the AppSync response quota. The campaign export is not a resolver
response at all - it returns a report URL and puts the file in S3 - so its
ceiling comes out of the memory of the Lambda it materialises in. Each ceiling
below is derived from the resource that actually bounds its own path, and each
is sized so the order count #577 approved for a report still passes on both.
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

# The external anchor: the AWS AppSync service quotas list "Resolvers, functions,
# and handlers response size - 5 Megabytes". It is a service limit, not a
# product decision, and nothing here may exceed it.
APPSYNC_RESPONSE_LIMIT_BYTES = 5_000_000

# Both report handlers run at 512 MB / 60 s, per the ``request-report`` and
# ``unit-reporting`` entries in tofu/application/modules/lambda/main.tf.
REPORT_LAMBDA_MEMORY_BYTES = 512 * 1024 * 1024

# Unit report: ``get_unit_report`` returns the whole order graph of the unit in
# one resolver response, so the response quota is the ceiling. The graph gets two
# fifths of it, because the response is not only the order details - it also
# carries a wrapper per seller and the GraphQL envelope, and those have to fit in
# what is left. Two fifths is also the order contract: the 5,000 orders #577
# called "a few thousand", generous for a scout unit, at the 381 B a realistic
# one-line-item order detail measures (the shape
# tests/unit/test_report_limits.py pins) is 1.9 MB, so 5,000 orders report and
# the order after them is refused.
MAX_UNIT_REPORT_GRAPH_BYTES = (2 * APPSYNC_RESPONSE_LIMIT_BYTES) // 5

# Campaign report: ``request_campaign_report`` returns only reportId, reportUrl,
# status and expiresAt, and writes the CSV/XLSX to S3, so no part of that order
# graph is ever a resolver response and the quota above does not apply. What
# bounds it is the memory of the function it runs in, which holds every order of
# the campaign at once and, for XLSX, the whole openpyxl workbook beside them.
# Measured on the order shapes tests/unit/test_report_limits.py pins, a
# materialised order costs 4.0x its serialised size at one line item, 3.4x at
# five and 2.9x at twenty (recursive sys.getsizeof), and the workbook adds about
# 1.3 kB per order row at five columns or 2.9 kB at twelve (tracemalloc; a row
# is three fixed columns plus one per distinct product in the campaign, plus the
# total), beside a ~40 MB interpreter baseline.
#
# That arithmetic is what the approved contract is sized against: 5,000 orders,
# "a few thousand", are 4 MB serialised at one line item and 22 MB at twenty, so
# ~20-67 MB of live orders plus a ~6 MB workbook - comfortably inside the
# function, and comfortably inside the ceiling this is derived from.
#
# It is not a bound on the widest thing the ceiling admits, and that difference
# matters: at the narrow end it admits ~80,000 orders, which is ~271 MB of live
# orders plus ~100 MB of workbook, and a campaign that size spanning a dozen
# products does not fit in 512 MB. So this is a contract on report volume, not a
# promise that the export always completes. The 60 s timeout is a separate bound
# this ceiling does not measure either.
MAX_CAMPAIGN_REPORT_GRAPH_BYTES = REPORT_LAMBDA_MEMORY_BYTES // 8


def order_graph_bytes(record: Mapping[str, Any]) -> int:
    """Return the serialised size in bytes of one order graph.

    Measured, not estimated: what a report costs is the bytes its order graph
    serialises to, and a per-field estimate of that would silently undercharge
    the moment the graph gained a field, which is how a ceiling quietly becomes
    fiction. Measuring the record itself cannot drift from the shape of the data
    the handlers actually hold.

    Callers charge the record they are about to materialise, which differs by
    path and is what makes one measurement correct for both: the campaign export
    materialises the stored order, and the unit report materialises the detail
    ``_build_order_detail`` projects from it - a subset of the stored fields,
    which is why charging the stored order there would overcharge by ~2.2x.
    Values DynamoDB returns that JSON cannot represent natively (``Decimal``,
    sets) serialise as their string form, which is never shorter than the number
    the response carries, and non-ASCII is escaped, so neither can make the
    charge read low.
    """
    return len(json.dumps(record, default=str).encode("utf-8"))


def report_too_large_error(subject: str, max_bytes: int) -> AppError:
    """Return the typed error raised when a report exceeds its order-graph ceiling.

    Args:
        subject: Human-readable owner of the report, e.g. ``"This unit's"``.
        max_bytes: The ceiling that was crossed, reported in the message so it
            matches the budget actually enforced.

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
    """Byte ceiling for the order graph a single report may materialise.

    Callers charge each record *before* accumulating it, so a report that is
    going to be refused never pays for keeping what it cannot return.
    """

    def __init__(self, subject: str, max_bytes: int) -> None:
        self._subject = subject
        self._max_bytes = max_bytes
        self._spent = 0

    def admit(self, record: Mapping[str, Any]) -> None:
        """Charge one record, refusing the record that would cross the ceiling."""
        self._spent += order_graph_bytes(record)
        if self._spent > self._max_bytes:
            logger.warning(
                "Report order-graph ceiling reached",
                subject=self._subject,
                spentBytes=self._spent,
                maxBytes=self._max_bytes,
            )
            raise report_too_large_error(self._subject, self._max_bytes)
