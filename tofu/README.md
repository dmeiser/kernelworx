# OpenTofu Infrastructure

This directory contains OpenTofu configurations for the Popcorn Sales Manager infrastructure.

## Directory Structure

```
tofu/
├── bootstrap/              # CloudFormation for state bucket (one-time setup)
├── environments/
│   ├── dev/               # Dev environment configuration
│   └── prod/              # Production environment configuration  
├── modules/
│   ├── dynamodb/          # DynamoDB tables
│   ├── s3/                # S3 buckets
│   ├── iam/               # IAM roles
│   ├── cognito/           # Cognito User Pool
│   ├── lambda/            # Lambda functions
│   ├── appsync/           # AppSync API
│   ├── cloudfront/        # CloudFront distribution
│   └── certificates/      # ACM certificates
└── scripts/               # Deployment and import scripts
```

## Prerequisites

1. **OpenTofu 1.7+** installed
2. **AWS CLI** configured with appropriate credentials
3. **jq** installed for JSON processing
4. **ENCRYPTION_PASSPHRASE** set in root `.env` file

## Quick Start

```bash
# 1. Initialize (first time only)
cd environments/dev
./../../scripts/deploy.sh dev init

# 2. Import existing resources (first time only)
./../../scripts/import-resources.sh dev

# 3. Plan changes
./../../scripts/deploy.sh dev plan

# 4. Apply changes
./../../scripts/deploy.sh dev apply
```

## State Encryption

State files are encrypted using PBKDF2+AES-GCM with the passphrase from `ENCRYPTION_PASSPHRASE` environment variable.

**⚠️ IMPORTANT**: If you lose the passphrase, you cannot decrypt the state file!

## Migrated Resources

All resources previously managed by CDK have been imported:
- 8 DynamoDB tables
- 2 S3 buckets
- 20 Lambda functions
- 1 Cognito User Pool + Client + Domain
- 1 AppSync API
- 1 CloudFront distribution
- 3 ACM certificates
- IAM roles (Lambda, AppSync, Cognito SMS)
