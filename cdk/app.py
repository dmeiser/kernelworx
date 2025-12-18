#!/usr/bin/env python3
import os
from pathlib import Path

import aws_cdk as cdk

from cdk.cdk_stack import CdkStack

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

# Configure environment
env = cdk.Environment(
    account=os.getenv("AWS_ACCOUNT_ID") or os.getenv("CDK_DEFAULT_ACCOUNT"),
    region=os.getenv("AWS_REGION") or os.getenv("CDK_DEFAULT_REGION", "us-east-1"),
)

# Environment-specific stack name with deterministic naming
stack_name = f"kernelworx-{env_name}"

CdkStack(
    app,
    f"KernelWorxStack-{env_name}",
    stack_name=stack_name,
    env_name=env_name,
    env=env,
    description=f"KernelWorx - Core Infrastructure ({env_name})",
)

app.synth()
