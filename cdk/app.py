#!/usr/bin/env python3
"""
CDK Application entry point for KernelWorx infrastructure.

This file is used by the CDK CLI to synthesize CloudFormation templates.
It should NOT perform any AWS operations like cleanup or resource modification.

All cleanup and import operations should be handled by deploy.sh BEFORE calling cdk deploy.
"""
import os
import subprocess
from pathlib import Path

import aws_cdk as cdk

from cdk.cdk_stack import REGION_ABBREVIATIONS, CdkStack

# Load environment variables from .env file if it exists
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                # Only set if not already in environment (allow override)
                if key.strip() and not os.getenv(key.strip()):
                    os.environ[key.strip()] = value.strip()

app = cdk.App()

# Get environment from context or environment variable (dev/prod)
env_name = app.node.try_get_context("environment") or os.getenv("ENVIRONMENT", "dev")

# Get region and its abbreviation for stack naming
region = os.getenv("AWS_REGION") or os.getenv("CDK_DEFAULT_REGION", "us-east-1")
region_abbrev = REGION_ABBREVIATIONS.get(region, region[:3])

# Get AWS account ID - required for context provider lookups (hosted zones, etc)
account = os.getenv("AWS_ACCOUNT_ID") or os.getenv("CDK_DEFAULT_ACCOUNT")
if not account:
    # Try to get from AWS CLI if not in environment
    import subprocess
    try:
        account = subprocess.check_output(
            ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # Will use synthesized stack without context if account lookup fails

# Configure environment
env = cdk.Environment(
    account=account,
    region=region,
)

# Environment-specific stack name with region: kernelworx-{region}-{env}
stack_name = f"kernelworx-{region_abbrev}-{env_name}"

# NOTE: Cleanup and import operations are handled by deploy.sh, NOT here.
# app.py should only synthesize CloudFormation templates without side effects.

stack = CdkStack(
    app,
    f"KernelWorxStack-{region_abbrev}-{env_name}",
    stack_name=stack_name,
    env_name=env_name,
    env=env,
    description=f"KernelWorx - Core Infrastructure ({region_abbrev}-{env_name})",
)

app.synth()
