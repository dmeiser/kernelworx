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
    return boto3.resource("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"))


def get_dynamodb_resource() -> "DynamoDBServiceResource":
    """Get DynamoDB resource for direct resource-level operations like batch_get_item.

    Use this for operations that require the resource directly rather than a table.
    For table-level operations, prefer using the `tables` singleton.
    """
    return _get_dynamodb()


class TableAccessor:
    """Centralized access to DynamoDB tables with environment-based naming."""

    _instance: Optional["TableAccessor"] = None

    def __new__(cls) -> "TableAccessor":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def accounts(self) -> "Table":
        """Get accounts table instance."""
        if override := _table_overrides.get("accounts"):
            return override
        table_name = get_required_env("ACCOUNTS_TABLE_NAME")
        return _get_dynamodb().Table(table_name)

    @property
    def profiles(self) -> "Table":
        """Get profiles table instance (V2 multi-table design)."""
        if override := _table_overrides.get("profiles"):
            return override
        table_name = get_required_env("PROFILES_TABLE_NAME")
        return _get_dynamodb().Table(table_name)

    @property
    def campaigns(self) -> "Table":
        """Get campaigns table instance (V2 multi-table design)."""
        if override := _table_overrides.get("campaigns"):
            return override
        table_name = get_required_env("CAMPAIGNS_TABLE_NAME")
        return _get_dynamodb().Table(table_name)

    @property
    def orders(self) -> "Table":
        """Get orders table instance (V2 multi-table design)."""
        if override := _table_overrides.get("orders"):
            return override
        table_name = get_required_env("ORDERS_TABLE_NAME")
        return _get_dynamodb().Table(table_name)

    @property
    def shares(self) -> "Table":
        """Get shares table instance."""
        if override := _table_overrides.get("shares"):
            return override
        table_name = get_required_env("SHARES_TABLE_NAME")
        return _get_dynamodb().Table(table_name)

    @property
    def catalogs(self) -> "Table":
        """Get catalogs table instance."""
        if override := _table_overrides.get("catalogs"):
            return override
        table_name = get_required_env("CATALOGS_TABLE_NAME")
        return _get_dynamodb().Table(table_name)

    @property
    def invites(self) -> "Table":
        """Get invites table instance."""
        if override := _table_overrides.get("invites"):
            return override
        table_name = get_required_env("INVITES_TABLE_NAME")
        return _get_dynamodb().Table(table_name)

    @property
    def shared_campaigns(self) -> "Table":
        """Get shared campaigns table instance."""
        if override := _table_overrides.get("shared_campaigns"):
            return override
        table_name = get_required_env("SHARED_CAMPAIGNS_TABLE_NAME")
        return _get_dynamodb().Table(table_name)


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
    TableAccessor._instance = None
