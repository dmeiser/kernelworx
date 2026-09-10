"""
Handler utilities for standardizing Lambda exception handling (#294, #329).

The ``lambda_handler`` decorator replaces the repetitive
``except AppError: raise`` / ``except Exception`` boilerplate in resolver
handlers. Instead of re-raising (which AWS Lambda serializes as
``{"errorType": "AppError", "errorMessage": "..."}``, stripping the
structured ``error_code``), both paths return a structured error payload
(``__isError`` + ``errorCode`` + ``message``) that AppSync JS resolvers
surface via ``util.error`` with ``extensions.errorCode`` intact (#329).
"""

from functools import wraps
from typing import Any, Callable, Dict, Optional, Union, overload

from .errors import AppError, ErrorCode
from .logging import get_logger

# AppSync Lambda resolver signature: (event, context) -> result.
HandlerFunc = Callable[[Dict[str, Any], Any], Any]


def _structured_error(error_code: str, message: str) -> Dict[str, Any]:
    """Build the #329 structured error payload returned instead of raising.

    ``__isError`` marks the payload for AppSync JS resolvers (e.g.
    ``lambda_passthrough_resolver.js``), which call
    ``util.error(message, errorCode, null, { errorCode })`` so the code also
    lands in GraphQL ``extensions.errorCode``.
    """
    code = getattr(error_code, "value", error_code)
    return {"__isError": True, "errorCode": code, "message": message}


@overload
def lambda_handler(func: HandlerFunc, *, error_message: Optional[str] = None) -> HandlerFunc: ...  # pragma: no cover


@overload
def lambda_handler(  # pragma: no cover
    func: None = None, *, error_message: Optional[str] = None
) -> Callable[[HandlerFunc], HandlerFunc]: ...


def lambda_handler(
    func: Optional[HandlerFunc] = None, *, error_message: Optional[str] = None
) -> Union[HandlerFunc, Callable[[HandlerFunc], HandlerFunc]]:
    """Standardize exception handling for an AppSync Lambda resolver handler.

    - ``AppError`` raised by the handler is converted to a structured error
      payload ``{"__isError": True, "errorCode": ..., "message": ...}`` so
      the error code survives Lambda serialization and reaches AppSync
      extensions (see #329).
    - Any other exception is logged at error level naming the function, then
      converted to the same structured payload with
      ``ErrorCode.INTERNAL_ERROR`` instead of an unhandled exception.

    Usable bare (``@lambda_handler``) or with a client-facing message for the
    generic failure path (``@lambda_handler(error_message="Failed to list users")``).
    Handler-specific typed errors (e.g. retryable ``RESOURCE_BUSY``) must still
    be raised/handled inside the handler or its helpers; the decorator only
    covers the generic unexpected-exception path.

    Args:
        func: The handler function when used as a bare decorator.
        error_message: Client-facing message for the INTERNAL_ERROR AppError;
            defaults to ``f"Failed to execute {func.__name__}"``.

    Returns:
        The wrapped handler, or a decorator when called with arguments.
    """

    def decorator(target: HandlerFunc) -> HandlerFunc:
        @wraps(target)
        def wrapper(event: Dict[str, Any], context: Any) -> Any:
            try:
                return target(event, context)
            except AppError as e:
                return _structured_error(e.error_code, e.message)
            except Exception as e:
                logger = get_logger(target.__module__)
                logger.error(f"Unexpected error in {target.__name__}", error=str(e))
                return _structured_error(
                    ErrorCode.INTERNAL_ERROR,
                    error_message or f"Failed to execute {target.__name__}",
                )

        return wrapper

    if func is None:
        return decorator
    return decorator(func)
