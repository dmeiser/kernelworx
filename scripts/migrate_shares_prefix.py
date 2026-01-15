"""One-off migration: add ACCOUNT# prefix to createdByAccountId in shares table.

Usage (dev only):
    uv run python scripts/migrate_shares_prefix.py

Prereqs:
- AWS credentials for the dev account
- Environment variable SHARES_TABLE_NAME set (or provided via .env already used by Lambdas)

This script scans the shares table and updates any item whose createdByAccountId
is missing the ACCOUNT# prefix. Updates are conditional to avoid double-prefixing.
"""

from __future__ import annotations

import os
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

PREFIX = "ACCOUNT#"


def needs_prefix(value: Any) -> bool:
    return isinstance(value, str) and not value.startswith(PREFIX)


def migrate(table_name: str) -> None:
    table = boto3.resource("dynamodb").Table(table_name)

    updated = 0
    scanned = 0
    last_key: Dict[str, Any] | None = None

    while True:
        params: Dict[str, Any] = {
            "ProjectionExpression": "profileId, targetAccountId, createdByAccountId",
        }
        if last_key:
            params["ExclusiveStartKey"] = last_key

        response = table.scan(**params)
        items = response.get("Items", [])
        scanned += len(items)

        for item in items:
            created_by = item.get("createdByAccountId")
            if not created_by or not needs_prefix(created_by):
                continue

            prefixed = f"{PREFIX}{created_by}"
            key = {
                "profileId": item["profileId"],
                "targetAccountId": item["targetAccountId"],
            }

            try:
                table.update_item(
                    Key=key,
                    UpdateExpression="SET createdByAccountId = :new",
                    ConditionExpression=
                    "attribute_exists(profileId) AND attribute_exists(targetAccountId) AND createdByAccountId = :current",
                    ExpressionAttributeValues={
                        ":new": prefixed,
                        ":current": created_by,
                    },
                )
                updated += 1
            except ClientError as e:
                print(f"Failed to update {key['profileId']}::{key['targetAccountId']}: {e}")

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break

    print(f"Scanned {scanned} items; updated {updated} records missing prefix")


def main() -> None:
    table_name = os.getenv("SHARES_TABLE_NAME")
    if not table_name:
        raise RuntimeError("SHARES_TABLE_NAME is not set; aborting migration")

    migrate(table_name)


if __name__ == "__main__":
    main()
