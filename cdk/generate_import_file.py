#!/usr/bin/env python3
"""
Generate CloudFormation resource import file before deployment.

This script is called by deploy.sh to dynamically generate a resource import file
for resources that exist in AWS but are not yet managed by CloudFormation.

Outputs the path to the import file on stdout (or nothing if no imports needed).
"""
import os
import sys
from pathlib import Path

# Add cdk module to path
sys.path.insert(0, str(Path(__file__).parent))

from cdk.cdk_stack import REGION_ABBREVIATIONS
from cdk.cleanup_hook import generate_import_file


def main() -> None:
    """Generate import file and print its path to stdout."""
    # Get environment configuration (same logic as app.py)
    env_name = os.getenv("ENVIRONMENT", "dev")
    region = os.getenv("AWS_REGION") or os.getenv("CDK_DEFAULT_REGION", "us-east-1")
    region_abbrev = REGION_ABBREVIATIONS.get(region, region[:3])
    stack_name = f"kernelworx-{region_abbrev}-{env_name}"
    
    # Generate import file
    import_file_path = generate_import_file(
        stack_name=stack_name,
        environment_name=env_name,
        region_abbrev=region_abbrev,
    )
    
    # Print path to stdout (or nothing if no imports needed)
    if import_file_path:
        print(import_file_path)


if __name__ == "__main__":
    main()
