# LocalStack Development

This project supports deploying to LocalStack for local development and testing.

## Prerequisites

1. **Docker** must be running
2. **LocalStack CLI** installed (`pip install localstack`)
3. **awslocal CLI** installed (`pip install awscli-local`) - optional but recommended

## Installation

If you don't have LocalStack CLI installed:

```bash
pip install localstack
pip install awscli-local  # Optional: awslocal wrapper for AWS CLI
```

## Quick Start

### 1. Start LocalStack

```bash
# Start LocalStack in detached mode
localstack start -d

# Check status
localstack status
```

### 2. Deploy Infrastructure

```bash
./deploy-localstack.sh
```

This script:
- Checks if LocalStack is running (starts it if not)
- Sets environment variables
- Bootstraps CDK
- Synthesizes the stack
- Deploys to LocalStack

### 3. Verify Deployment

```bash
# List DynamoDB tables
awslocal dynamodb list-tables

# List S3 buckets
awslocal s3 ls

# List IAM roles
awslocal iam list-roles

# Scan DynamoDB table
awslocal dynamodb scan --table-name PsmApp
```

## Manual Deployment

If you prefer manual control:

```bash
# Start LocalStack
localstack start -d

# Set environment variables
export USE_LOCALSTACK=true
export AWS_DEFAULT_REGION=us-east-1
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test

# Navigate to cdk directory
cd cdk

# Bootstrap CDK
npx cdk bootstrap --require-approval never

# Synth stack
npx cdk synth

# Deploy
npx cdk deploy --require-approval never
```

## LocalStack Management

### Start LocalStack
```bash
localstack start -d
```

### Stop LocalStack
```bash
localstack stop
```

### Check Status
```bash
localstack status
```

### View Logs
```bash
localstack logs
```

### Restart LocalStack
```bash
localstack restart
```

## LocalStack Pro Features

LocalStack Community (free) supports:
- DynamoDB
- S3
- IAM
- Lambda
- SNS/SES
- CloudWatch
- EventBridge

LocalStack Pro (requires license) adds:
- **Cognito**: User Pools and social login
- **AppSync**: GraphQL API
- **CloudFront**: CDN distribution

### Free OSS License

LocalStack offers free Pro licenses for open-source projects!

**To apply:**
1. Email: info@localstack.cloud
2. Provide: GitHub repo URL, project description, MIT license
3. Include: "Volunteer-run Scouting America popcorn sales management app"
4. See [Step 4 in TODO.md](TODO.md#step-4-apply-for-localstack-pro-oss-license)

**If approved:**
```bash
# Set your license key
export LOCALSTACK_API_KEY=your-key-here

# Restart LocalStack
localstack restart
```

## Troubleshooting

### Permission Issues

If you see "Permission denied" errors for `/var/lib/localstack/logs`:

```bash
# LocalStack CLI handles this automatically, but if using docker-compose:
mkdir -p localstack-data
sudo chown -R $USER:$USER localstack-data
```

### LocalStack not starting
```bash
# Check logs
localstack logs

# Try restarting
localstack stop
localstack start -d
```

### Reset LocalStack state
```bash
# Stop LocalStack
localstack stop

# Remove data directory
rm -rf ~/.cache/localstack

# Start fresh
localstack start -d
```

### Check LocalStack health
```bash
curl http://localhost:4566/_localstack/health | jq
```

## Differences from AWS

### Account ID
LocalStack uses account ID `000000000000`

### Endpoint
All services use `http://localhost:4566`

### Credentials
Use any credentials (e.g., `test` / `test`)

### Region
Default: `us-east-1` (configurable)

## Data Persistence

LocalStack data persists in `~/.cache/localstack/` directory.

To start fresh:
```bash
localstack stop
rm -rf ~/.cache/localstack
localstack start -d
```

## Integration with uv

All CDK commands use the virtualenv:

```bash
cd cdk
npx cdk synth
npx cdk deploy
npx cdk diff
```

## Using docker-compose (Alternative)

If you prefer docker-compose, use:

```bash
docker-compose up -d
```

But the **recommended approach is `localstack start -d`** as it:
- Handles permissions automatically
- Easier to manage (start/stop/restart)
- Better log access
- Integrated health checks

## Common Commands

```bash
# Start LocalStack
localstack start -d

# Deploy infrastructure
./deploy-localstack.sh

# List resources
awslocal dynamodb list-tables
awslocal s3 ls
awslocal iam list-roles

# Stop LocalStack
localstack stop

# View logs
localstack logs --follow
```

## Next Steps

After deploying to LocalStack:
1. Test DynamoDB operations
2. Test S3 uploads
3. Test IAM permissions
4. Prepare for Step 7 (Auth & API layer)

