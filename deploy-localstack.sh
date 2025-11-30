#!/bin/bash
#
# Deploy CDK stack to LocalStack
#
# Usage:
#   ./deploy-localstack.sh
#

set -e

echo "============================================================"
echo "Deploying Popcorn Sales Manager to LocalStack"
echo "============================================================"
echo ""

# Check if LocalStack is running
if ! localstack status | grep -q "running"; then
    echo "LocalStack is not running. Starting it..."
    
    # Create localstack-data directory with proper permissions
    mkdir -p localstack-data
    
    # Start LocalStack with CLI (no docker-compose)
    localstack start -d
    
    echo ""
    echo "Waiting for LocalStack to be ready..."
    sleep 10
    
    # Wait for health check
    echo "Checking LocalStack health..."
    timeout=30
    counter=0
    until curl -s http://localhost:4566/_localstack/health > /dev/null 2>&1; do
        counter=$((counter + 1))
        if [ $counter -gt $timeout ]; then
            echo "❌ LocalStack failed to start within ${timeout}s"
            exit 1
        fi
        echo "  Waiting... ($counter/$timeout)"
        sleep 1
    done
    
    echo "✅ LocalStack is ready"
else
    echo "✅ LocalStack is already running"
fi

echo ""

# Set environment variables for LocalStack
export AWS_DEFAULT_REGION=us-east-1
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export USE_LOCALSTACK=true
export CDK_DEFAULT_ACCOUNT=000000000000
export CDK_DEFAULT_REGION=us-east-1

# Navigate to cdk directory
cd cdk

echo "Bootstrapping CDK (if needed)..."
npx cdk bootstrap --require-approval never

echo ""
echo "Synthesizing stack..."
npx cdk synth

echo ""
echo "Deploying stack..."
npx cdk deploy --require-approval never

echo ""
echo "============================================================"
echo "✅ Deployment complete!"
echo "============================================================"
echo ""
echo "LocalStack endpoint: http://localhost:4566"
echo ""
echo "To interact with resources:"
echo "  awslocal dynamodb list-tables"
echo "  awslocal s3 ls"
echo "  awslocal iam list-roles"
echo ""
echo "To stop LocalStack:"
echo "  localstack stop"
echo ""
