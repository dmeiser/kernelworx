from src.handlers.show_and_sell_operations import handler


def test_handler_returns_ok() -> None:
    assert handler({}, None) == {"ok": True}
