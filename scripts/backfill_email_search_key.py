"""One-off backfill: add the ``emailSearchKey`` prefix-segment attribute to accounts.

Why this exists
---------------
The accounts table's ``emailSearchIndex`` GSI is sparse: it is a constant HASH
key (``emailSearchKey``) plus ``email`` as the RANGE key, which is what makes
``begins_with(email, :prefix)`` a legal Query key condition for admin search
(#586). An account item only becomes searchable once it carries the constant, so
every account written before the index existed has to be given the attribute or
it silently disappears from email search.

Deployment order (see also tofu/application/modules/dynamodb/main.tf):
1. deploy the account write path (the Cognito bootstrap trigger now sets
   ``emailSearchKey``, so new and updated accounts are indexed);
2. run this script, then ``--verify`` to prove no row is left unindexed;
3. apply the table change that creates the index.

The write is conditional on the attribute being absent, so the script is
idempotent and safe to re-run while sign-ins keep writing the table.

Usage (dev first, then prod):
    uv run python scripts/backfill_email_search_key.py
    uv run python scripts/backfill_email_search_key.py --verify

``--verify`` writes nothing and exits non-zero while any account is still
missing the attribute, so it can gate the index rollout.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, Iterator, List, Tuple

import boto3
from botocore.exceptions import ClientError

EMAIL_SEARCH_KEY = "EMAIL"

ScanResult = Tuple[int, int]


def scan_accounts(table: Any) -> Iterator[Dict[str, Any]]:
    """Yield every account item, following pagination."""
    last_key: Dict[str, Any] | None = None
    while True:
        params: Dict[str, Any] = {"ProjectionExpression": "accountId, email, emailSearchKey"}
        if last_key:
            params["ExclusiveStartKey"] = last_key
        response = table.scan(**params)
        yield from response.get("Items", [])
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return


def needs_search_key(item: Dict[str, Any]) -> bool:
    """An item needs the attribute when it is absent or not the expected constant."""
    return item.get("emailSearchKey") != EMAIL_SEARCH_KEY


def backfill(table: Any) -> ScanResult:
    """Set the search key on every account that is missing it. Returns (scanned, updated)."""
    scanned = 0
    updated = 0
    for item in scan_accounts(table):
        scanned += 1
        if not needs_search_key(item):
            continue
        try:
            table.update_item(
                Key={"accountId": item["accountId"]},
                UpdateExpression="SET emailSearchKey = :searchKey",
                ConditionExpression="attribute_not_exists(emailSearchKey)",
                ExpressionAttributeValues={":searchKey": EMAIL_SEARCH_KEY},
            )
            updated += 1
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                # A concurrent sign-in already indexed this account.
                continue
            print(f"Failed to update {item['accountId']}: {e}")
    return scanned, updated


def verify(table: Any) -> int:
    """Return the number of accounts still missing the search key."""
    remaining = sum(1 for item in scan_accounts(table) if needs_search_key(item))
    print(f"Accounts still missing {EMAIL_SEARCH_KEY}: {remaining}")
    return remaining


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--verify",
        action="store_true",
        help="report accounts still missing the search key without writing anything",
    )
    args = parser.parse_args(argv)

    table_name = os.getenv("ACCOUNTS_TABLE_NAME")
    if not table_name:
        raise RuntimeError("ACCOUNTS_TABLE_NAME is not set; aborting backfill")

    table = boto3.resource("dynamodb").Table(table_name)

    if args.verify:
        return 1 if verify(table) else 0

    scanned, updated = backfill(table)
    print(f"Scanned {scanned} accounts; indexed {updated} missing {EMAIL_SEARCH_KEY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
