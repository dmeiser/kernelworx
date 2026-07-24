"""
Centralized DynamoDB table access utilities.

Provides singleton-pattern table accessors with lazy initialization
and test monkeypatch support.
"""

import os
from typing import TYPE_CHECKING, Optional

import boto3

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBServiceResource
    from mypy_boto3_dynamodb.service_resource import Table


# Module-level cache for test overrides
_table_overrides: dict[str, Optional["Table"]] = {}

# Module-level cache for the DynamoDB service resource
_dynamodb_resource: Optional["DynamoDBServiceResource"] = None


def get_required_env(name: str, default: Optional[str] = None) -> str:
    """Get a required environment variable.

    In Lambda/production, the env var must be set. For tests, a default can be
    provided to allow the code to run in mocked environments.

    Args:
        name: Environment variable name
        default: Optional default for test environments (should not be dev resource)

    Returns:
        The environment variable value

    Raises:
        ValueError: If the env var is not set and no default is provided
    """
    value = os.getenv(name, default)
    if value is None:
        raise ValueError(f"Required environment variable '{name}' is not set")
    return value


def _get_dynamodb() -> "DynamoDBServiceResource":
    """Get DynamoDB resource with optional endpoint override for LocalStack."""
    global _dynamodb_resource
    if _dynamodb_resource is None:
        _dynamodb_resource = boto3.resource("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"))
    return _dynamodb_resource


def get_dynamodb_resource() -> "DynamoDBServiceResource":
    """Get DynamoDB resource for direct resource-level operations like batch_get_item.

    Use this for operations that require the resource directly rather than a table.
    For table-level operations, prefer using the `tables` singleton.
    """
    return _get_dynamodb()


class TableAccessor:
    """Centralized access to DynamoDB tables with environment-based naming."""

    _instance: Optional["TableAccessor"] = None
    _tables: dict[str, "Table"]

    def __new__(cls) -> "TableAccessor":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tables = {}
        return cls._instance

    def _get_table(self, table_name_key: str) -> "Table":
        """Return a cached table, or create and cache it."""
        if override := _table_overrides.get(table_name_key):
            return override
        if table_name_key not in self._tables:
            table_name = get_required_env(f"{table_name_key.upper()}_TABLE_NAME")
            self._tables[table_name_key] = _get_dynamodb().Table(table_name)
        return self._tables[table_name_key]

    @property
    def accounts(self) -> "Table":
        """Get accounts table instance."""
        return self._get_table("accounts")

    @property
    def profiles(self) -> "Table":
        """Get profiles table instance (V2 multi-table design)."""
        return self._get_table("profiles")

    @property
    def campaigns(self) -> "Table":
        """Get campaigns table instance (V2 multi-table design)."""
        return self._get_table("campaigns")

    @property
    def orders(self) -> "Table":
        """Get orders table instance (V2 multi-table design)."""
        return self._get_table("orders")

    @property
    def shares(self) -> "Table":
        """Get shares table instance."""
        return self._get_table("shares")

    @property
    def catalogs(self) -> "Table":
        """Get catalogs table instance."""
        return self._get_table("catalogs")

    @property
    def invites(self) -> "Table":
        """Get invites table instance."""
        return self._get_table("invites")

    @property
    def shared_campaigns(self) -> "Table":
        """Get shared campaigns table instance."""
        return self._get_table("shared_campaigns")


# Singleton instance for import
tables = TableAccessor()


# Test utilities
def override_table(table_name: str, table: Optional["Table"]) -> None:
    """Override a table for testing. Set to None to clear override."""
    _table_overrides[table_name] = table


def clear_all_overrides() -> None:
    """Clear all table overrides (call in test teardown)."""
    _table_overrides.clear()


def reset_singleton() -> None:
    """Reset the singleton instance (for testing isolation)."""
    if TableAccessor._instance is not None:
        TableAccessor._instance._tables = {}
    # Also clear the module-level singleton's cache so external imports that
    # hold a reference to the old instance do not reuse stale tables.
    tables._tables = {}
    TableAccessor._instance = None


def reset_dynamodb_resource() -> None:
    """Reset the cached DynamoDB resource (for testing isolation)."""
    global _dynamodb_resource
    _dynamodb_resource = None
