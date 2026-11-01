"""Unit tests for the public-orders Lambda dispatcher (PRIN-5).

The dispatcher lives in ``src/handlers/public_orders_router.py`` and is wrapped
into the deployed entry point by ``public_orders_offer`` (Terraform registers
``handlers.public_orders_offer.handler``). Three surfaces share one Lambda and
arrive with different discriminators: the pipeline's email invoke carries an
``operation`` field and no ``info``, while the two API-key reads arrive through
``lambda_unit_resolver.js`` with the whole AppSync context, so ``info.fieldName``
routes them.

The routing itself is exercised here against stubs; the end-to-end behavior of
each surface stays in that surface's own test module.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from src.handlers import public_orders_offer as offer
from src.handlers import public_orders_router as router
from src.utils.errors import AppError, ErrorCode

ROUTER_SOURCE = Path(router.__file__)


def _event(**overrides: Any) -> Dict[str, Any]:
    event: Dict[str, Any] = {
        "arguments": {"campaignId": "c1", "token": "tok"},
        "info": {"fieldName": "publicGetOrderOffer"},
    }
    event.update(overrides)
    return event


def _module_scope_imports(source: str) -> list[str]:
    """Module names imported at module scope, including try/except import blocks."""
    names: list[str] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.Try):
            statements = node.body + [statement for handler in node.handlers for statement in handler.body]
            for statement in statements:
                if isinstance(statement, ast.ImportFrom):
                    names.append(statement.module or "")
                elif isinstance(statement, ast.Import):
                    names.extend(alias.name for alias in statement.names)
    return names


class TestRouting:
    def test_the_email_operation_discriminator_routes_the_pipeline_invoke(self) -> None:
        event = {"operation": "send_order_emails", "order": {"orderId": "ORDER#c1#s1"}}
        with patch.object(router, "handle_send_order_emails", return_value={"configured": False}) as mailer:
            assert router.route(event, None) == {"configured": False}
        mailer.assert_called_once_with(event, None)

    def test_the_email_operation_routes_ahead_of_the_field_name(self) -> None:
        """An Invoke payload has no field name; the discriminator wins regardless."""
        event = _event(operation="send_order_emails")
        with (
            patch.object(router, "handle_send_order_emails", return_value="mailer"),
            patch.object(router, "handle_receipt") as receipt,
            patch.object(offer, "_run_guarded") as build,
        ):
            assert router.route(event, None) == "mailer"
        assert receipt.call_args_list == []
        assert build.call_args_list == []

    def test_the_receipt_field_routes_to_the_receipt_handler(self) -> None:
        event = _event(info={"fieldName": "publicGetOrderReceipt"})
        with patch.object(router, "handle_receipt", return_value={"orderId": "ORDER#c1#s1"}) as receipt:
            assert router.route(event, None) == {"orderId": "ORDER#c1#s1"}
        receipt.assert_called_once_with(event, None)

    def test_the_offer_field_routes_to_the_guarded_offer_read(self) -> None:
        with patch.object(offer, "_run_guarded", return_value={"campaignId": "c1"}) as build:
            assert router.route(_event(), None) == {"campaignId": "c1"}
        build.assert_called_once()

    @pytest.mark.parametrize("info", [{"fieldName": "publicSomethingElse"}, {}, None])
    def test_an_unknown_or_missing_field_is_a_structured_internal_error(self, info: Any) -> None:
        """``route`` is undecorated, so the caller's decorator maps this payload."""
        with pytest.raises(AppError) as exc:
            router.route({"arguments": {}, "info": info}, None)
        assert exc.value.error_code is ErrorCode.INTERNAL_ERROR


class TestEntryPointWiring:
    def test_the_offer_module_still_exposes_the_deployed_entry_point(self) -> None:
        """Terraform resolves ``handlers.public_orders_offer.handler``."""
        assert callable(offer.handler)
        assert offer.handler is not router.route  # the decorator wraps the dispatcher

    def test_the_entry_point_maps_an_unsupported_field_to_the_error_payload(self) -> None:
        result = offer.handler({"arguments": {}, "info": {"fieldName": "publicNope"}}, None)
        assert result["__isError"] is True
        assert result["errorCode"] is ErrorCode.INTERNAL_ERROR

    def test_the_router_does_not_import_the_offer_module_at_module_scope(self) -> None:
        """The pair is cyclic by construction; only a deferred import keeps it loadable.

        ``public_orders_offer`` imports the router to build the entry point, so a
        module-scope import of the offer module back would fail depending on which
        module the Lambda runtime loads first.
        """
        imported = _module_scope_imports(ROUTER_SOURCE.read_text())
        assert not any("public_orders_offer" in name for name in imported), imported
