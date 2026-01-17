#!/usr/bin/env python3
"""
Delete managed catalogs owned by test users
"""

import os
import sys
import boto3

# Get configuration
TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "kernelworx-catalogs-ue1-dev")
REGION = os.getenv("AWS_REGION", "us-east-1")
TEST_OWNER_EMAIL = os.getenv("TEST_OWNER_EMAIL")
TEST_CONTRIBUTOR_EMAIL = os.getenv("TEST_CONTRIBUTOR_EMAIL")
TEST_READONLY_EMAIL = os.getenv("TEST_READONLY_EMAIL")

if not TABLE_NAME:
    print("Error: DYNAMODB_TABLE_NAME not set")
    sys.exit(1)

# Initialize DynamoDB
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)

# Get Cognito sub values for test users
cognito = boto3.client("cognito-idp", region_name=REGION)
user_pool_id = os.getenv("TEST_USER_POOL_ID")

test_users = [
    TEST_OWNER_EMAIL,
    TEST_CONTRIBUTOR_EMAIL,
    TEST_READONLY_EMAIL,
]

test_subs = []
if user_pool_id:
    print("Getting test user IDs from Cognito...")
    for email in test_users:
        if not email:
            continue
        try:
            response = cognito.admin_get_user(
                UserPoolId=user_pool_id,
                Username=email
            )
            sub = None
            for attr in response['UserAttributes']:
                if attr['Name'] == 'sub':
                    sub = attr['Value']
                    break
            if sub:
                test_subs.append(sub)
                print(f"  ✓ {email}: {sub}")
        except Exception as e:
            print(f"  ✗ Could not get ID for {email}: {e}")

if not test_subs:
    print("No test user IDs found")
    sys.exit(1)

# Query for catalogs owned by test users
print(f"\nSearching for catalogs in DynamoDB table: {TABLE_NAME}")

deleted_count = 0
for sub in test_subs:
    print(f"\nScanning for catalogs owned by: {sub}")
    
    # Scan for catalogs with this owner (GSI1PK = MANAGED_CATALOG#{sub})
    response = table.scan(
        FilterExpression="begins_with(PK, :pk_prefix) AND GSI1PK = :gsi1pk",
        ExpressionAttributeValues={
            ":pk_prefix": "CATALOG#",
            ":gsi1pk": f"MANAGED_CATALOG#{sub}"
        }
    )
    
    catalogs = response.get("Items", [])
    print(f"  Found {len(catalogs)} catalogs")
    
    for catalog in catalogs:
        catalog_id = catalog["PK"].replace("CATALOG#", "")
        catalog_name = catalog.get("catalogName", "Unknown")
        
        try:
            # Delete METADATA item
            table.delete_item(
                Key={"PK": catalog["PK"], "SK": "METADATA"}
            )
            print(f"    ✓ Deleted: {catalog_name} ({catalog_id})")
            deleted_count += 1
        except Exception as e:
            print(f"    ✗ Failed to delete {catalog_name}: {e}")

print(f"\n✅ Deleted {deleted_count} test catalogs")
