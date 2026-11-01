"""Cross-language contract: the email operation discriminator must stay pinned."""

from src.handlers.public_order_emails import SEND_ORDER_EMAILS_OPERATION

CANONICAL = "send_order_emails"


def test_python_discriminator_matches_canonical():
    assert SEND_ORDER_EMAILS_OPERATION == CANONICAL
