"""Tests for the lambda_handler exception-handling decorator (#294, #329)."""

from typing import Any, Dict

from src.utils.errors import AppError, ErrorCode
from src.utils.handlers import lambda_handler


class TestLambdaHandlerDecorator:
    """Tests for the lambda_handler decorator's exception-handling contract.

    Per #329 the decorator returns structured error payloads
    (``__isError`` + ``errorCode`` + ``message``) instead of re-raising, so
    the error code survives AWS Lambda serialization and reaches AppSync
    (and the frontend's typed matchers) intact.
    """

    def test_app_error_returns_structured_payload(self) -> None:
        """AppError raised by the handler becomes a structured error payload."""
        original = AppError(ErrorCode.NOT_FOUND, "User not found", {"userId": "u1"})

        @lambda_handler
        def handler(event: Dict[str, Any], context: Any) -> Any:
            raise original

        result = handler({}, None)

        assert result == {
            "__isError": True,
            "errorCode": ErrorCode.NOT_FOUND,
            "message": "User not found",
        }

    def test_generic_exception_returns_internal_error_payload(self) -> None:
        """Any other unexpected Exception becomes an INTERNAL_ERROR payload."""

        @lambda_handler
        def handler(event: Dict[str, Any], context: Any) -> Any:
            raise ValueError("boom")

        result = handler({}, None)

        assert result == {
            "__isError": True,
            "errorCode": ErrorCode.INTERNAL_ERROR,
            "message": "Failed to execute handler",
        }

    def test_custom_error_message_used(self) -> None:
        """An explicit error_message overrides the default INTERNAL_ERROR message."""

        @lambda_handler(error_message="Failed to list users")
        def handler(event: Dict[str, Any], context: Any) -> Any:
            raise RuntimeError("db down")

        result = handler({}, None)

        assert result == {
            "__isError": True,
            "errorCode": ErrorCode.INTERNAL_ERROR,
            "message": "Failed to list users",
        }

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

        result = my_failing_handler({}, None)

        assert result["__isError"] is True
        log_line = capsys.readouterr().out.strip()
        entry = json.loads(log_line)
        assert entry["level"] == "ERROR"
        assert entry["message"] == "Unexpected error in my_failing_handler"
        assert entry["error"] == "kaput"
