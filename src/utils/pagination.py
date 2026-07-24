"""DynamoDB pagination helpers for Lambda handlers.

Provides synchronous query/scan wrappers that follow LastEvaluatedKey so callers
do not silently truncate results at DynamoDB's 1 MB page limit.
"""

from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_dynamodb.service_resource import Table


def query_all_items(table: "Table", query_kwargs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute a DynamoDB query and follow pagination to return all items.

    Args:
        table: DynamoDB table resource to query.
        query_kwargs: Keyword arguments passed to ``Table.query``. Must include
            ``KeyConditionExpression`` and any ``ExpressionAttributeValues``.

    Returns:
        All items matching the query, aggregated across pages.
    """
    items: List[Dict[str, Any]] = []
    kwargs = dict(query_kwargs)

    while True:
        response = table.query(**kwargs)
        items.extend(response.get("Items", []))

        last_evaluated_key = response.get("LastEvaluatedKey")
        if last_evaluated_key is None:
            break
        kwargs["ExclusiveStartKey"] = last_evaluated_key

    return items


def scan_all_items(table: "Table", scan_kwargs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Execute a DynamoDB scan and follow pagination to return all items.

    Args:
        table: DynamoDB table resource to scan.
        scan_kwargs: Keyword arguments passed to ``Table.scan``.

    Returns:
        All items matching the scan, aggregated across pages.
    """
    items: List[Dict[str, Any]] = []
    kwargs = dict(scan_kwargs)

    while True:
        response = table.scan(**kwargs)
        items.extend(response.get("Items", []))

        last_evaluated_key = response.get("LastEvaluatedKey")
        if last_evaluated_key is None:
            break
        kwargs["ExclusiveStartKey"] = last_evaluated_key

    return items
