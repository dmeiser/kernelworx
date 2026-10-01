"""Caller-ID extraction goes through ``utils.appsync_types.get_caller_id`` (#527).

``get_caller_id`` exists to centralize the caller-ID read, but thirteen handler
sites had inlined it in three dialects. Only one of them was total:
``event["identity"]["sub"]`` raises ``KeyError`` on a malformed or
unauthenticated event, where ``get_caller_id`` returns ``None``.

The tests below verify that missing or malformed identity returns ``None``
without raising exceptions and that handlers consuming it return the typed
``UNAUTHORIZED`` error code rather than failing with an unhandled exception.
"""

from src.handlers import list_catalogs_in_use
from src.utils.appsync_types import get_caller_id
from src.utils.errors import ErrorCode


def test_list_catalogs_in_use_reports_unauthenticated_instead_of_key_error() -> None:
    """A missing or null identity is UNAUTHORIZED, not the KeyError's generic INTERNAL_ERROR."""
    result = list_catalogs_in_use.handler({"identity": None}, None)

    assert result["__isError"] is True
    assert result["errorCode"] == ErrorCode.UNAUTHORIZED

    result_empty = list_catalogs_in_use.handler({}, None)

    assert result_empty["__isError"] is True
    assert result_empty["errorCode"] == ErrorCode.UNAUTHORIZED


def test_get_caller_id_is_the_total_dialect() -> None:
    """The helper returns None for every shape the inlined dialects disagreed on."""
    assert get_caller_id({"identity": {"sub": "user-1"}}) == "user-1"
    assert get_caller_id({"identity": None}) is None
    assert get_caller_id({"identity": {}}) is None
    assert get_caller_id({}) is None
    assert get_caller_id({"identity": "not-a-dict"}) is None
