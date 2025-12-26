#!/usr/bin/env python3
"""
Generate import file for SMS role ONLY (separate from other resources).
This allows importing the SMS role first, then other resources in a second pass.
"""
import json
import os
import sys

import boto3


def main():
    environment = os.getenv("ENVIRONMENT", "dev")
    region = os.getenv("AWS_REGION", "us-east-1")
    
    # Map regions to abbreviations
    region_abbrevs = {
        "us-east-1": "ue1",
        "us-east-2": "ue2",
        "us-west-1": "uw1",
        "us-west-2": "uw2",
    }
    region_abbrev = region_abbrevs.get(region, region[:3])
    
    stack_name = f"kernelworx-{region_abbrev}-{environment}"
    
    # Check if SMS role exists outside CloudFormation
    iam_client = boto3.client("iam", region_name=region)
    cfn_client = boto3.client("cloudformation", region_name=region)
    cognito_client = boto3.client("cognito-idp", region_name=region)
    
    # Get existing stack resources
    try:
        stack_resources = cfn_client.list_stack_resources(StackName=stack_name)
        managed_resources = {r["PhysicalResourceId"] for r in stack_resources["StackResourceSummaries"]}
    except cfn_client.exceptions.ClientError:
        managed_resources = set()
    
    # Find the UserPool and get its SMS role
    user_pool_id = None
    try:
        pools = cognito_client.list_user_pools(MaxResults=60)
        for pool in pools.get("UserPools", []):
            if pool["Name"] == f"kernelworx-users-{region_abbrev}-{environment}":
                user_pool_id = pool["Id"]
                break
    except Exception:
        pass
    
    sms_role_arn = None
    if user_pool_id:
        try:
            pool_details = cognito_client.describe_user_pool(UserPoolId=user_pool_id)
            sms_config = pool_details.get("UserPool", {}).get("SmsConfiguration", {})
            sms_role_arn = sms_config.get("SnsCallerArn")
        except Exception:
            pass
    
    # Extract role name from ARN
    sms_role_name = None
    if sms_role_arn:
        # ARN format: arn:aws:iam::ACCOUNT:role/ROLE_NAME
        sms_role_name = sms_role_arn.split("/")[-1]
        print(f"DEBUG: Found UserPool SMS role: {sms_role_name}", file=sys.stderr)
    else:
        print(f"DEBUG: No SMS role ARN found for UserPool {user_pool_id}", file=sys.stderr)
    
    # Check if SMS role exists but not in CloudFormation
    role_exists = False
    if sms_role_name:
        try:
            iam_client.get_role(RoleName=sms_role_name)
            role_exists = True
        except iam_client.exceptions.NoSuchEntityException:
            pass
    
    if role_exists and sms_role_name not in managed_resources:
        print("DEBUG: Role exists and not in CFN, generating import file", file=sys.stderr)
        # Generate import file for SMS role only
        import_file_path = os.path.join(os.path.dirname(__file__), ".cdk-import-sms-role.json")
        import_data = {
            "UserPoolsmsRole1998E37F": {
                "RoleName": sms_role_name
            }
        }
        
        with open(import_file_path, "w") as f:
            json.dump(import_data, f, indent=2)
        
        print(import_file_path)
        sys.exit(0)
    else:
        # No import needed
        print(f"DEBUG: No import needed - role_exists={role_exists}, sms_role_name={sms_role_name}, in_cfn={sms_role_name in managed_resources if sms_role_name else 'N/A'}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
