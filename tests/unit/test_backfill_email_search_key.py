"""Tests for scripts/backfill_email_search_key.py (accounts prefix-search backfill).

The backfill exists because the accounts table's ``emailSearchIndex`` GSI is
sparse: an account written before the index existed carries no ``emailSearchKey``
and would be invisible to admin email search (#586). These tests run the script
against the real moto table and assert on the resulting index membership.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List

import pytest

from src.utils.dynamodb import EMAIL_SEARCH_KEY, tables

SCRIPT_REL = Path("scripts") / "backfill_email_search_key.py"
EMAIL_SEARCH_INDEX = "emailSearchIndex"
ACCOUNTS_TABLE_NAME = "kernelworx-accounts-ue1-dev"


@pytest.fixture
def script(repo_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("backfill_email_search_key", repo_root / SCRIPT_REL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def accounts(dynamodb_table: Any) -> Any:
    """The moto accounts table, seeded with a mix of pre- and post-index rows."""
    for account_id, email in (
        ("ACCOUNT#legacy-anna", "anna@example.com"),
        ("ACCOUNT#legacy-bob", "bob@example.com"),
        ("ACCOUNT#indexed-cara", "cara@example.com"),
    ):
        item: Dict[str, Any] = {"accountId": account_id, "email": email}
        if account_id == "ACCOUNT#indexed-cara":
            item["emailSearchKey"] = EMAIL_SEARCH_KEY
        tables.accounts.put_item(Item=item)
    return tables.accounts


def _searchable_accounts(prefix: str) -> List[str]:
    response = tables.accounts.query(
        IndexName=EMAIL_SEARCH_INDEX,
        KeyConditionExpression="emailSearchKey = :searchKey AND begins_with(email, :prefix)",
        ExpressionAttributeValues={":searchKey": EMAIL_SEARCH_KEY, ":prefix": prefix},
    )
    return sorted(item["accountId"] for item in response["Items"])


def _emails_resolvable_through_the_index() -> List[str]:
    """Every stored email must be findable by its own value through the index."""
    stored = sorted(item["email"] for item in tables.accounts.scan(ProjectionExpression="email")["Items"])
    return sorted(email for email in stored if _searchable_accounts(email) != [])


def test_unindexed_account_is_invisible_to_search_before_the_backfill(accounts: Any) -> None:
    """The sparse index cannot see a row that predates it."""
    assert _searchable_accounts("anna@") == []


def test_backfill_indexes_every_account_missing_the_search_key(script: ModuleType, accounts: Any) -> None:
    scanned, updated = script.backfill(accounts)

    assert (scanned, updated) == (3, 2)
    assert _searchable_accounts("anna@") == ["ACCOUNT#legacy-anna"]
    assert _searchable_accounts("bob@") == ["ACCOUNT#legacy-bob"]


def test_backfill_is_idempotent(script: ModuleType, accounts: Any) -> None:
    script.backfill(accounts)
    scanned, updated = script.backfill(accounts)

    assert (scanned, updated) == (3, 0)
    assert _emails_resolvable_through_the_index() == ["anna@example.com", "bob@example.com", "cara@example.com"]


def test_verify_reports_unindexed_accounts_until_the_backfill_has_run(script: ModuleType, accounts: Any) -> None:
    assert script.verify(accounts) == 2
    script.backfill(accounts)
    assert script.verify(accounts) == 0


def test_main_verify_exits_non_zero_while_accounts_are_unindexed(
    script: ModuleType,
    accounts: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verify mode gates the index rollout on every row being indexed."""
    monkeypatch.setenv("ACCOUNTS_TABLE_NAME", ACCOUNTS_TABLE_NAME)

    assert script.main(["--verify"]) == 1
    assert script.main([]) == 0
    assert script.main(["--verify"]) == 0


def test_main_aborts_without_a_table_name(script: ModuleType, accounts: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACCOUNTS_TABLE_NAME", raising=False)

    with pytest.raises(RuntimeError, match="ACCOUNTS_TABLE_NAME"):
        script.main([])


def test_backfill_survives_an_account_indexed_by_a_concurrent_sign_in(script: ModuleType, accounts: Any) -> None:
    """A sign-in that indexes the account mid-run must not fail or stop the backfill."""
    original_update = accounts.update_item
    raced: List[str] = []

    def racing_update(**kwargs: Any) -> Dict[str, Any]:
        account_id = kwargs["Key"]["accountId"]
        if account_id == "ACCOUNT#legacy-anna":
            # Simulate the account bootstrap trigger indexing this account first.
            original_update(
                Key=kwargs["Key"],
                UpdateExpression="SET emailSearchKey = :searchKey",
                ExpressionAttributeValues={":searchKey": EMAIL_SEARCH_KEY},
            )
            raced.append(account_id)
        return original_update(**kwargs)

    accounts.update_item = racing_update  # type: ignore[method-assign]
    try:
        scanned, updated = script.backfill(accounts)
    finally:
        del accounts.update_item

    assert scanned == 3
    # The raced account is skipped, the other unindexed one is written.
    assert raced == ["ACCOUNT#legacy-anna"]
    assert updated == 1
    assert _emails_resolvable_through_the_index() == ["anna@example.com", "bob@example.com", "cara@example.com"]
