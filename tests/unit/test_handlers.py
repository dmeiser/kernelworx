"""Tests for the lambda_handler exception-handling decorator (#294)."""

from typing import Any, Dict

import pytest

from src.utils.errors import AppError, ErrorCode
from src.utils.handlers import lambda_handler


class TestLambdaHandlerDecorator:
    """Tests for the lambda_handler decorator's exception-handling contract."""

    def test_app_error_propagates_unchanged(self) -> None:
        """AppError raised by the handler propagates unchanged."""
        original = AppError(ErrorCode.NOT_FOUND, "User not found", {"userId": "u1"})

        @lambda_handler
        def handler(event: Dict[str, Any], context: Any) -> Any:
            raise original

        with pytest.raises(AppError) as exc_info:
            handler({}, None)

        assert exc_info.value is original
        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
        assert exc_info.value.message == "User not found"
        assert exc_info.value.details == {"userId": "u1"}

    def test_generic_exception_converts_to_internal_error(self) -> None:
        """Any other unexpected Exception becomes an INTERNAL_ERROR AppError."""

        @lambda_handler
        def handler(event: Dict[str, Any], context: Any) -> Any:
            raise ValueError("boom")

        with pytest.raises(AppError) as exc_info:
            handler({}, None)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert exc_info.value.message == "Failed to execute handler"
        assert isinstance(exc_info.value.__cause__, ValueError)

    def test_custom_error_message_used(self) -> None:
        """An explicit error_message overrides the default INTERNAL_ERROR message."""

        @lambda_handler(error_message="Failed to list users")
        def handler(event: Dict[str, Any], context: Any) -> Any:
            raise RuntimeError("db down")

        with pytest.raises(AppError) as exc_info:
            handler({}, None)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert exc_info.value.message == "Failed to list users"

    def test_normal_return_value_unchanged(self) -> None:
        """A successful handler return value passes through unchanged."""

        @lambda_handler
        def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
            return {"result": event["value"]}

        result = handler({"value": 42}, None)

        assert result == {"result": 42}

    def test_error_log_names_the_function(self, capsys: Any) -> None:
        """The generic path logs at error level naming the failed function."""
        import json

        @lambda_handler(error_message="Failed to do the thing")
        def my_failing_handler(event: Dict[str, Any], context: Any) -> Any:
            raise RuntimeError("kaput")

        with pytest.raises(AppError):
            my_failing_handler({}, None)

        log_line = capsys.readouterr().out.strip()
        entry = json.loads(log_line)
        assert entry["level"] == "ERROR"
        assert entry["message"] == "Unexpected error in my_failing_handler"
        assert entry["error"] == "kaput"
