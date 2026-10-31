"""Tests for the centralized dual-layout import helper (#774).

The Lambda payload zip lays ``src/`` out as top-level ``utils``/``handlers``
packages (absolute ``utils.<module>`` imports), while unit tests import
through the ``src`` package (relative ``..utils.<module>`` imports).
`import_from_utils` must resolve the SAME module objects in both layouts —
a second, shadow module identity would silently break test monkeypatching.
"""

import sys
from types import ModuleType

import pytest

from src.utils import dynamodb, errors
from src.utils.import_fallback import import_from_utils


class TestImportFromUtils:
    def test_single_name_returns_bare_attribute(self) -> None:
        assert import_from_utils("errors", "AppError") is errors.AppError

    def test_multiple_names_return_tuple_in_order(self) -> None:
        assert import_from_utils("errors", "AppError", "ErrorCode") == (
            errors.AppError,
            errors.ErrorCode,
        )

    def test_falls_back_to_src_utils_layout(self) -> None:
        """Without a top-level ``utils`` package, resolves ``src.utils.<name>``."""
        assert "utils" not in sys.modules
        assert import_from_utils("dynamodb", "tables") is dynamodb.tables

    def test_lambda_layout_wins_when_top_level_utils_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With a resolvable top-level ``utils`` package (the Lambda zip layout), it is used as-is."""
        stub_utils = ModuleType("utils")
        stub_errors = ModuleType("utils.errors")
        marker = object()
        stub_errors.MARKER = marker
        monkeypatch.setitem(sys.modules, "utils", stub_utils)
        monkeypatch.setitem(sys.modules, "utils.errors", stub_errors)

        assert import_from_utils("errors", "MARKER") is marker

    def test_missing_attribute_raises_attribute_error(self) -> None:
        with pytest.raises(AttributeError):
            import_from_utils("errors", "no_such_name")


class TestMigratedCallSites:
    """The migrated modules must bind the same objects relative imports would.

    This is the no-dual-identity guard: if the helper ever resolved a
    shadow ``utils.*`` module instead of ``src.utils.*``, these identities
    would diverge and test monkeypatching of ``src.utils.*`` would stop
    affecting the handlers under test.
    """

    def test_utils_payment_methods(self) -> None:
        from src.utils import boto, logging, payment_methods, s3

        assert payment_methods.get_s3_client is boto.get_s3_client
        assert payment_methods.get_required_env is dynamodb.get_required_env
        assert payment_methods.tables is dynamodb.tables
        assert payment_methods.AppError is errors.AppError
        assert payment_methods.ErrorCode is errors.ErrorCode
        assert payment_methods.get_logger is logging.get_logger
        assert payment_methods.purge_s3_prefix is s3.purge_s3_prefix

    def test_payment_methods_handlers(self) -> None:
        from src.handlers import payment_methods_handlers
        from src.utils import appsync_types, handlers, payment_methods

        assert payment_methods_handlers.get_caller_id is appsync_types.get_caller_id
        assert payment_methods_handlers.AppError is errors.AppError
        assert payment_methods_handlers.with_error_handling is handlers.lambda_handler
        assert payment_methods_handlers._mutate_payment_methods is payment_methods._mutate_payment_methods
        assert payment_methods_handlers.tables is dynamodb.tables

    def test_admin_operations(self) -> None:
        from src.handlers import admin_operations
        from src.utils import appsync_types, auth, handlers

        assert admin_operations.get_caller_id is appsync_types.get_caller_id
        assert admin_operations.require_admin_mfa is auth.require_admin_mfa
        assert admin_operations.TRANSIENT_ERROR_CODES is dynamodb.TRANSIENT_ERROR_CODES
        assert admin_operations.AppError is errors.AppError
        assert admin_operations.ErrorCode is errors.ErrorCode
        assert admin_operations.with_error_handling is handlers.lambda_handler
