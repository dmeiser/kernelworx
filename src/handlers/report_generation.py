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
try:
    from utils.auth import check_profile_access
    from utils.errors import AppError, ErrorCode, handle_error
    from utils.logging import get_logger
except ModuleNotFoundError:
    from ..utils.auth import check_profile_access  # type: ignore
    from ..utils.errors import AppError, ErrorCode, handle_error  # type: ignore
    from ..utils.logging import get_logger  # type: ignore

# Initialize AWS clients
dynamodb = boto3.resource("dynamodb", endpoint_url=os.getenv("DYNAMODB_ENDPOINT"))
s3_client = boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT"))


def get_table() -> Any:
    """Get DynamoDB table instance."""
    table_name = os.getenv("TABLE_NAME", "PsmApp")
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

        # Get season and verify authorization
        table = get_table()
        season = _get_season(table, season_id)

        if not season:
            raise AppError(ErrorCode.NOT_FOUND, f"Season {season_id} not found")

        profile_id = season["profileId"]

        # Check authorization (must have read access to profile)
        if not check_profile_access(caller_account_id, profile_id, "read"):
            raise AppError(ErrorCode.FORBIDDEN, "You don't have access to this season")

        # Get all orders for the season
        orders = _get_season_orders(table, profile_id, season_id)

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

    except AppError:
        raise
    except Exception as e:
        logger.error("Unexpected error generating report", error=str(e))
        raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to generate report: {str(e)}")


def _get_season(table: Any, season_id: str) -> Dict[str, Any] | None:
    """Get season by ID using GSI5 (seasonId index)."""
    # Season ID format: SEASON#uuid
    # Seasons are stored with PK=profileId, SK=seasonId
    # They also have a seasonId attribute for GSI5 queries
    # Note: GSI5 may return both the season AND orders for that season,
    # so we filter by SK to get only the season row
    response = table.query(
        IndexName="GSI5",
        KeyConditionExpression="seasonId = :season_id",
        FilterExpression="begins_with(SK, :sk_prefix)",
        ExpressionAttributeValues={
            ":season_id": season_id,
            ":sk_prefix": "SEASON#",
        },
    )

    items = response.get("Items", [])
    return items[0] if items else None


def _get_season_orders(table: Any, profile_id: str, season_id: str) -> list[Dict[str, Any]]:
    """Get all orders for a season by querying profile and filtering by seasonId."""
    response = table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
        FilterExpression="seasonId = :season_id",
        ExpressionAttributeValues={
            ":pk": profile_id,
            ":sk": "ORDER#",
            ":season_id": season_id,
        },
    )

    items = response.get("Items", [])
    return list(items) if items else []


def _generate_csv_report(season: Dict[str, Any], orders: list[Dict[str, Any]]) -> bytes:
    """Generate CSV report."""
    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([f"Season Report: {season.get('name', season.get('seasonName', 'Unknown'))}"])
    writer.writerow([f"Start Date: {season['startDate']}"])
    writer.writerow([f"End Date: {season.get('endDate', 'Ongoing')}"])
    writer.writerow([])

    # Orders header
    writer.writerow(
        [
            "Order Date",
            "Customer Name",
            "Customer Phone",
            "Payment Method",
            "Total Amount",
            "Notes",
        ]
    )

    # Orders
    for order in orders:
        writer.writerow(
            [
                order.get("orderDate", ""),
                order.get("customerName", ""),
                order.get("customerPhone", ""),
                order.get("paymentMethod", ""),
                order.get("totalAmount", 0),
                order.get("notes", ""),
            ]
        )

    # Summary
    total_orders = len(orders)
    total_revenue = sum(float(order.get("totalAmount", 0)) for order in orders)
    writer.writerow([])
    writer.writerow(["Summary"])
    writer.writerow(["Total Orders", total_orders])
    writer.writerow(["Total Revenue", f"${total_revenue:.2f}"])

    return output.getvalue().encode("utf-8")


def _generate_excel_report(season: Dict[str, Any], orders: list[Dict[str, Any]]) -> bytes:
    """Generate Excel report."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None, "Workbook must have an active worksheet"
    ws.title = "Season Report"

    # Header styling
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    # Title
    ws["A1"] = f"Season Report: {season.get('name', season.get('seasonName', 'Unknown'))}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Start Date: {season['startDate']}"
    ws["A3"] = f"End Date: {season.get('endDate', 'Ongoing')}"

    # Orders header (row 5)
    headers = [
        "Order Date",
        "Customer Name",
        "Customer Phone",
        "Payment Method",
        "Total Amount",
        "Notes",
    ]
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=5, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font

    # Orders data
    for row_idx, order in enumerate(orders, start=6):
        ws.cell(row=row_idx, column=1, value=order.get("orderDate", ""))
        ws.cell(row=row_idx, column=2, value=order.get("customerName", ""))
        ws.cell(row=row_idx, column=3, value=order.get("customerPhone", ""))
        ws.cell(row=row_idx, column=4, value=order.get("paymentMethod", ""))
        ws.cell(row=row_idx, column=5, value=float(order.get("totalAmount", 0)))
        ws.cell(row=row_idx, column=6, value=order.get("notes", ""))

    # Summary
    summary_row = len(orders) + 7
    ws.cell(row=summary_row, column=1, value="Summary").font = Font(bold=True)
    ws.cell(row=summary_row + 1, column=1, value="Total Orders:")
    ws.cell(row=summary_row + 1, column=2, value=len(orders))
    ws.cell(row=summary_row + 2, column=1, value="Total Revenue:")

    total_revenue = sum(float(order.get("totalAmount", 0)) for order in orders)
    ws.cell(row=summary_row + 2, column=2, value=total_revenue)

    # Auto-size columns
    for column in ws.columns:
        max_length = 0
        first_cell = column[0]
        # Get column letter safely (MergedCell doesn't have column_letter)
        column_letter = getattr(first_cell, "column_letter", None)
        if column_letter is None:
            continue
        for cell in column:  # type: ignore[assignment]
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except Exception:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[column_letter].width = adjusted_width

    # Save to BytesIO
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
