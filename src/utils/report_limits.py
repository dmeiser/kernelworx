"""Shared order ceiling for the report handlers.

Both report paths materialise one in-memory record per order: the unit report
returns every order and every line item for the whole unit (#577), and the
campaign report builds the entire CSV/Excel output in memory (#533). Neither
path has a bound, so the largest units and campaigns - exactly the case the
reports exist for - run out of the Lambda's memory and time budget and surface
as a generic internal error. Both handlers share the ceiling below so the two
report paths cannot drift apart, and both raise the same typed error when it is
reached instead of returning a partial report.
"""

try:  # pragma: no cover
    from utils.errors import AppError, ErrorCode
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.errors import AppError, ErrorCode

# Maximum number of orders a single report may materialise. A few thousand is
# generous for a scout unit or a single campaign; past it the report is refused
# rather than allowed to exhaust the Lambda.
MAX_REPORT_ORDERS = 5000


def report_too_large_error(subject: str) -> AppError:
    """Return the typed error raised when a report exceeds ``MAX_REPORT_ORDERS``.

    Args:
        subject: Human-readable owner of the report, e.g. ``"This unit's"``.

    Returns:
        An ``AppError`` carrying the ``RESOURCE_BUSY`` code the issue specifies
        (#577); the AppSync Lambda resolver surfaces it in the GraphQL
        ``extensions.errorCode`` and the frontend renders the message as-is.
    """
    return AppError(
        ErrorCode.RESOURCE_BUSY,
        f"{subject} report is too large to generate: it has more than {MAX_REPORT_ORDERS} orders.",
    )
