#!/bin/bash
set -e

# Helper script to deploy CDK with automatic resource import
# This detects existing AWS resources and either imports or deploys them

ENV="dev"
STACK_NAME="kernelworx-${ENV}"

echo "===================================================================="
echo "CDK Deployment with Auto-Import for environment: $ENV"
echo "===================================================================="
echo ""

# Check if stack exists
STACK_EXISTS=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" 2>/dev/null || echo "")

if [ -z "$STACK_EXISTS" ]; then
    echo "Stack does not exist. Checking for orphaned resources to import..."
    echo ""
    
    # Create resource mapping file for import
    IMPORT_FILE=$(mktemp)
    cat > "$IMPORT_FILE" << 'EOF'
[]
EOF
    
    RESOURCES_TO_IMPORT=()
    
    # Check for existing DynamoDB table
    TABLE_NAME="psm-app-${ENV}"
    if aws dynamodb describe-table --table-name "$TABLE_NAME" &>/dev/null; then
        echo "✓ Found existing DynamoDB table: $TABLE_NAME"
        RESOURCES_TO_IMPORT+=("PsmApp|$TABLE_NAME")
    fi
    
    # Check for existing S3 buckets
    STATIC_BUCKET=$(aws s3 ls | grep -E "kernelworx-static-${ENV}" | awk '{print $3}' | head -1)
    if [ -n "$STATIC_BUCKET" ]; then
        echo "✓ Found existing static assets bucket: $STATIC_BUCKET"
        RESOURCES_TO_IMPORT+=("StaticAssets|$STATIC_BUCKET")
    fi
    
    EXPORTS_BUCKET=$(aws s3 ls | grep -E "kernelworx-exports-${ENV}" | awk '{print $3}' | head -1)
    if [ -n "$EXPORTS_BUCKET" ]; then
        echo "✓ Found existing exports bucket: $EXPORTS_BUCKET"
        RESOURCES_TO_IMPORT+=("Exports|$EXPORTS_BUCKET")
    fi
    
    # Check for existing Cognito User Pool
    USER_POOL_NAME="kernelworx-users-${ENV}"
    USER_POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 | \
        jq -r ".UserPools[] | select(.Name==\"$USER_POOL_NAME\") | .Id" 2>/dev/null | head -1)
    if [ -n "$USER_POOL_ID" ]; then
        echo "✓ Found existing Cognito User Pool: $USER_POOL_ID"
        RESOURCES_TO_IMPORT+=("UserPool|$USER_POOL_ID")
    fi
    
    # Check for existing AppSync API
    API_NAME="kernelworx-api-${ENV}"
    API_ID=$(aws appsync list-graphql-apis | \
        jq -r ".graphqlApis[] | select(.name==\"$API_NAME\") | .apiId" 2>/dev/null | head -1)
    if [ -n "$API_ID" ]; then
        echo "✓ Found existing AppSync API: $API_ID"
        RESOURCES_TO_IMPORT+=("Api|$API_ID")
    fi
    
    echo ""
    
    if [ ${#RESOURCES_TO_IMPORT[@]} -gt 0 ]; then
        echo "Building resource import mapping..."
        
        # Build JSON for import
        JSON_ARRAY="["
        FIRST=true
        for RESOURCE in "${RESOURCES_TO_IMPORT[@]}"; do
            LOGICAL_ID="${RESOURCE%%|*}"
            PHYSICAL_ID="${RESOURCE##*|}"
            
            if [ "$FIRST" = true ]; then
                FIRST=false
            else
                JSON_ARRAY+=","
            fi
            
            JSON_ARRAY+="{\"logicalResourceId\":\"$LOGICAL_ID\",\"physicalResourceId\":\"$PHYSICAL_ID\"}"
        done
        JSON_ARRAY+="]"
        
        echo "$JSON_ARRAY" > "$IMPORT_FILE"
        
        echo "Import mapping file:"
        cat "$IMPORT_FILE"
        echo ""
        echo "Importing existing resources into CloudFormation..."
        
        # Use CDK context to tell stack to use imported resources
        CONTEXT_ARGS=""
        for RESOURCE in "${RESOURCES_TO_IMPORT[@]}"; do
            LOGICAL_ID="${RESOURCE%%|*}"
            PHYSICAL_ID="${RESOURCE##*|}"
            
            case "$LOGICAL_ID" in
                "PsmApp")
                    CONTEXT_ARGS="$CONTEXT_ARGS -c table_name=$PHYSICAL_ID"
                    ;;
                "StaticAssets")
                    CONTEXT_ARGS="$CONTEXT_ARGS -c static_bucket_name=$PHYSICAL_ID"
                    ;;
                "Exports")
                    CONTEXT_ARGS="$CONTEXT_ARGS -c exports_bucket_name=$PHYSICAL_ID"
                    ;;
                "UserPool")
                    CONTEXT_ARGS="$CONTEXT_ARGS -c user_pool_id=$PHYSICAL_ID"
                    ;;
                "Api")
                    CONTEXT_ARGS="$CONTEXT_ARGS -c appsync_api_id=$PHYSICAL_ID"
                    ;;
            esac
        done
        
        echo "Deploying with imported resources..."
        npx cdk deploy $CONTEXT_ARGS -c environment="$ENV" "${@:2}"
        
        rm -f "$IMPORT_FILE"
    else
        echo "No existing resources found. Deploying fresh stack..."
        npx cdk deploy -c environment="$ENV" "${@:2}"
    fi
else
    echo "Stack already exists. Performing update..."
    npx cdk deploy -c environment="$ENV" "${@:2}"
fi

echo ""
echo "===================================================================="
echo "Deployment complete!"
echo "===================================================================="
