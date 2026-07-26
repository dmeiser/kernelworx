"""
KernelWorx Local Development Server.

Runs a local HTTP server on http://localhost:8000 serving the HTMX application,
Jinja2 templates, static CSS/JS, and local DynamoDB handlers backed by moto so
the full app renders without AWS credentials.
"""

import os
import threading
import time
from pathlib import Path
import sys
from wsgiref.simple_server import make_server

import boto3
from botocore.exceptions import ClientError
from moto import mock_aws

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _create_mock_tables() -> None:
    """Create DynamoDB tables + env vars for local rendering (mirrors e2e conftest)."""
    os.environ.setdefault("PROFILES_TABLE_NAME", "kernelworx-profiles-v2-ue1-dev")
    os.environ.setdefault("CAMPAIGNS_TABLE_NAME", "kernelworx-campaigns-v2-ue1-dev")
    os.environ.setdefault("ORDERS_TABLE_NAME", "kernelworx-orders-v2-ue1-dev")
    os.environ.setdefault("ACCOUNTS_TABLE_NAME", "kernelworx-accounts-ue1-dev")
    os.environ.setdefault("CATALOGS_TABLE_NAME", "kernelworx-catalogs-v2-ue1-dev")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    tables_spec = [
        ("kernelworx-profiles-v2-ue1-dev", [("PK", "HASH"), ("SK", "RANGE")]),
        ("kernelworx-campaigns-v2-ue1-dev", [("profileId", "HASH"), ("campaignId", "RANGE")]),
        ("kernelworx-orders-v2-ue1-dev", [("campaignId", "HASH"), ("orderId", "RANGE")]),
        ("kernelworx-accounts-ue1-dev", [("accountId", "HASH")]),
        ("kernelworx-catalogs-v2-ue1-dev", [("catalogId", "HASH")]),
    ]
    for tbl_name, keys in tables_spec:
        try:
            dynamodb.create_table(
                TableName=tbl_name,
                KeySchema=[{"AttributeName": k, "KeyType": t} for k, t in keys],
                AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k, _ in keys],
                BillingMode="PAY_PER_REQUEST",
            )
        except ClientError:
            pass


PORT = 8000


def main() -> None:
    from tests.e2e.test_server import wsgi_app

    with mock_aws():
        _create_mock_tables()
        print("=" * 50)
        print(f"KernelWorx HTMX Development Server Started!")
        print(f"Local URL: http://localhost:{PORT}")
        print("=" * 50)
        httpd = make_server("0.0.0.0", PORT, wsgi_app)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down dev server...")
            sys.exit(0)


if __name__ == "__main__":
    main()