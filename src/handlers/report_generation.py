"""
Report generation Lambda handler.

Implements:
- requestSeasonReport: Generate Excel/CSV report for season data
"""

import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Dict

import boto3
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

# Handle both Lambda (absolute) and unit test (relative) imports
try:  # pragma: no cover
    from utils.auth import check_profile_access  # type: ignore[import-not-found]
    from utils.errors import AppError, ErrorCode, handle_error  # type: ignore[import-not-found]
    from utils.logging import get_logger  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    from ..utils.auth import check_profile_access
    from ..utils.errors import AppError, ErrorCode, handle_error
    from ..utils.logging import get_logger

# Initialize AWS clients
dynamodb = boto3.resource("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"))
s3_client = boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT"))


def get_seasons_table() -> Any:
    """Get DynamoDB seasons table instance (multi-table design)."""
    table_name = os.getenv("SEASONS_TABLE_NAME", "kernelworx-seasons-ue1-dev")
    return dynamodb.Table(table_name)


def get_orders_table() -> Any:
    """Get DynamoDB orders table instance (multi-table design)."""
    table_name = os.getenv("ORDERS_TABLE_NAME", "kernelworx-orders-ue1-dev")
    return dynamodb.Table(table_name)


def request_season_report(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Generate a season report and upload to S3.

    GraphQL mutation: requestSeasonReport(seasonId: ID!, format: String)

    Returns:
        {
          reportId: String!
          seasonId: String!
          profileId: String!
          reportUrl: String
          status: String!
          createdAt: String!
          expiresAt: String
        }
    """
    logger = get_logger(__name__, event.get("requestId", "unknown"))

    try:
        # Extract arguments
        args = event["arguments"]["input"]
        season_id = args["seasonId"]
        report_format = args.get("format", "xlsx")  # xlsx or csv
        caller_account_id = event["identity"]["sub"]

        logger.info(
            "Generating season report",
            season_id=season_id,
            format=report_format,
            caller_account_id=caller_account_id,
        )

        # Get season and verify authorization (multi-table design)
        seasons_table = get_seasons_table()
        season = _get_season(seasons_table, season_id)

        if not season:
            raise AppError(ErrorCode.NOT_FOUND, f"Season {season_id} not found")

        profile_id = season["profileId"]

        # Check authorization (must have read access to profile)
        if not check_profile_access(caller_account_id, profile_id, "read"):
            raise AppError(ErrorCode.FORBIDDEN, "You don't have access to this season")

        # Get all orders for the season (multi-table design)
        orders_table = get_orders_table()
        orders = _get_season_orders(orders_table, season_id)

        # Generate report
        if report_format.lower() == "csv":
            report_content = _generate_csv_report(season, orders)
            content_type = "text/csv"
            file_extension = "csv"
        else:
            report_content = _generate_excel_report(season, orders)
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            file_extension = "xlsx"

        # Upload to S3
        report_id = f"REPORT#{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        exports_bucket = os.getenv("EXPORTS_BUCKET", "kernelworx-exports-dev")
        s3_key = f"reports/{profile_id}/{season_id}/{report_id}.{file_extension}"

        s3_client.put_object(
            Bucket=exports_bucket,
            Key=s3_key,
            Body=report_content,
            ContentType=content_type,
        )

        # Generate pre-signed URL (valid for 7 days)
        expiration = 7 * 24 * 60 * 60  # 7 days in seconds
        report_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": exports_bucket, "Key": s3_key},
            ExpiresIn=expiration,
        )

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=7)

        result = {
            "reportId": report_id,
            "seasonId": season_id,
            "profileId": profile_id,
            "reportUrl": report_url,
            "status": "COMPLETED",
            "createdAt": now.isoformat(),
            "expiresAt": expires_at.isoformat(),
        }

        logger.info("Report generated successfully", report_id=report_id, s3_key=s3_key)
        return result

    except AppError as e:
        return e.to_dict()  # type: ignore[no-any-return]
    except Exception as e:
        logger.error("Unexpected error generating report", error=str(e))
        error = AppError(ErrorCode.INTERNAL_ERROR, f"Failed to generate report: {str(e)}")
        return error.to_dict()  # type: ignore[no-any-return]


def _get_season(table: Any, season_id: str) -> Dict[str, Any] | None:
    """Get season by ID (multi-table design: direct get by primary key)."""
    # Season ID format: SEASON#uuid
    # Seasons are stored with seasonId as primary key
    response = table.get_item(Key={"seasonId": season_id})
    item: Dict[str, Any] | None = response.get("Item")
    return item


def _get_season_orders(table: Any, season_id: str) -> list[Dict[str, Any]]:
    """Get all orders for a season using seasonId GSI (multi-table design)."""
    response = table.query(
        IndexName="seasonId-index",
        KeyConditionExpression="seasonId = :season_id",
        ExpressionAttributeValues={
            ":season_id": season_id,
        },
    )

    items = response.get("Items", [])
    return list(items) if items else []


def _format_address(address: Dict[str, Any] | None) -> str:
    """Format address object as string."""
    if not address:
        return ""
    parts = []
    if address.get("street"):
        parts.append(address["street"])
    if address.get("city") or address.get("state") or address.get("zipCode"):
        city_state_zip = " ".join(
            filter(
                None,
                [address.get("city"), address.get("state"), address.get("zipCode")],
            )
        )
        if city_state_zip:  # pragma: no branch - always true if we entered outer if
            parts.append(city_state_zip)
    return ", ".join(parts)


def _generate_csv_report(season: Dict[str, Any], orders: list[Dict[str, Any]]) -> bytes:
    """Generate CSV report with product columns."""
    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)

    # Get all unique products
    all_products = sorted(
        set(
            item.get("productName", "")
            for order in orders
            for item in order.get("lineItems", [])
            if item.get("productName")
        )
    )

    # Headers: Name, Phone, Address, Product 1, Product 2, ..., Total
    headers = ["Name", "Phone", "Address"] + all_products + ["Total"]
    writer.writerow(headers)

    # Orders
    for order in orders:
        row = [
            order.get("customerName", ""),
            order.get("customerPhone", ""),
            _format_address(order.get("customerAddress", {})),
        ]

        # Add product quantities (sum duplicates)
        line_items_by_product: dict[str, int] = {}
        for item in order.get("lineItems", []):
            product_name = item.get("productName", "")
            quantity = item.get("quantity", 0)
            line_items_by_product[product_name] = (
                line_items_by_product.get(product_name, 0) + quantity
            )

        for product in all_products:
            row.append(line_items_by_product.get(product, ""))

        # Add total
        row.append(order.get("totalAmount", 0))
        writer.writerow(row)

    return output.getvalue().encode("utf-8")


def _generate_excel_report(season: Dict[str, Any], orders: list[Dict[str, Any]]) -> bytes:
    """Generate Excel report with product columns."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None, "Workbook must have an active worksheet"
    ws.title = "Orders"

    # Header styling
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    # Get all unique products
    all_products = sorted(
        set(
            item.get("productName", "")
            for order in orders
            for item in order.get("lineItems", [])
            if item.get("productName")
        )
    )

    # Headers: Name, Phone, Address, Product 1, Product 2, ..., Total
    headers = ["Name", "Phone", "Address"] + all_products + ["Total"]
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font

    # Orders data
    for row_idx, order in enumerate(orders, start=2):
        ws.cell(row=row_idx, column=1, value=order.get("customerName", ""))
        ws.cell(row=row_idx, column=2, value=order.get("customerPhone", ""))
        ws.cell(row=row_idx, column=3, value=_format_address(order.get("customerAddress", {})))

        # Add product quantities (sum duplicates)
        line_items_by_product: dict[str, int] = {}
        for item in order.get("lineItems", []):
            product_name = item.get("productName", "")
            quantity = item.get("quantity", 0)
            line_items_by_product[product_name] = (
                line_items_by_product.get(product_name, 0) + quantity
            )

        for col_idx, product in enumerate(all_products, start=4):
            ws.cell(row=row_idx, column=col_idx, value=line_items_by_product.get(product, ""))

        # Add total
        ws.cell(row=row_idx, column=len(headers), value=float(order.get("totalAmount", 0)))

    # Auto-size columns
    for column in ws.columns:
        max_length = 0
        first_cell = column[0]
        # Get column letter safely (MergedCell doesn't have column_letter)
        column_letter = getattr(first_cell, "column_letter", None)
        if column_letter is None:  # pragma: no cover
            continue  # pragma: no cover
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except Exception:  # pragma: no cover
                pass
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[column_letter].width = adjusted_width

    # Save to BytesIO
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
