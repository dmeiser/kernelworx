"""The public-orders Lambda's multi-surface dispatcher.

One Lambda serves three surfaces, and each arrives with a different
discriminator:

- the ``publicCreateOrder`` pipeline's best-effort email invoke carries an
  explicit ``operation`` field and no ``info`` at all (an Invoke payload has no
  field name), so it routes first;
- the two API-key public reads arrive through ``lambda_unit_resolver.js``, which
  forwards the whole AppSync context, so ``info.fieldName`` is the discriminator
  (identity is null on that auth mode and is never read).

Each surface carries its own decorated entry point so a generic failure names
its own surface ("Offer not available" vs "Receipt not available"); the inner
handler has already turned an ``AppError`` into the ``__isError`` payload the
unit resolver maps to a GraphQL error code, so this dispatcher passes that
payload straight through. The decoration itself happens in
``public_orders_offer``, which is the module Terraform wires as
``handlers.public_orders_offer.handler`` (see
``tofu/application/modules/lambda/main.tf``); keeping the entry point there is
what lets this module stay free of a top-level import of the offer module.

The offer module is imported INSIDE ``route`` rather than at module scope:
``public_orders_offer`` imports this module to build that entry point, so a
top-level import of the offer module here would be circular — the same deferred
resolution ``campaign_operations._raise_delete_error`` uses.
"""

from typing import Any, Dict

try:  # pragma: no cover
    from handlers.public_order_emails import SEND_ORDER_EMAILS_OPERATION, handle_send_order_emails
    from handlers.public_orders_receipt import RECEIPT_FIELD, handle_receipt
    from utils.errors import AppError, ErrorCode
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.errors import AppError, ErrorCode
    from .public_order_emails import SEND_ORDER_EMAILS_OPERATION, handle_send_order_emails
    from .public_orders_receipt import RECEIPT_FIELD, handle_receipt


def route(event: Dict[str, Any], context: Any) -> Any:
    """Route one public-orders Lambda event to the surface that owns it.

    Undecorated on purpose: the caller that owns a surface's client-facing
    generic-failure message applies ``@lambda_handler`` around it.
    """
    if event.get("operation") == SEND_ORDER_EMAILS_OPERATION:
        return handle_send_order_emails(event, context)

    # Deferred import (see the module docstring); resolved from the module cache
    # on every call, so the cost is one dict lookup.
    from .public_orders_offer import OFFER_FIELD, _run_guarded

    field_name = (event.get("info") or {}).get("fieldName", "")
    if field_name == RECEIPT_FIELD:
        return handle_receipt(event, context)
    if field_name != OFFER_FIELD:
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Unsupported operation: {field_name}")
    return _run_guarded(event)
