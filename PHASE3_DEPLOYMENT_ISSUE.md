# Phase 3 Lambda Simplification - CloudFormation Deployment Issue

## Status: IN PROGRESS - Blocked by CloudFormation phantom resources

### What's Complete

1. ✅ **GSI8 Added** - `email` field index for share-direct pipeline resolver (DEPLOYED to DynamoDB)
2. ✅ **GSI9 Code Ready** - `inviteCode` field index (commented out - can only add 1 GSI per deployment)
3. ✅ **All 3 Pipeline Resolvers Implemented**:
   - `createOrder`: GetCatalogFn → CreateOrderFn (complex loop logic tested with AWS CLI)
   - `shareProfileDirect`: LookupAccountByEmailFn → CreateShareFn
   - `redeemProfileInvite`: LookupInviteFn → CreateShareFn → MarkInviteUsedFn (commented out, needs GSI9)
4. ✅ **3 Lambda Functions Removed from CDK Code**:
   - `create_order_fn` → Pipeline resolver
   - `share_profile_direct_fn` → Pipeline resolver
   - `redeem_profile_invite_fn` → Pipeline resolver
5. ✅ **Lambda Count**: Code is ready for 15 → 3 Lambdas (80% reduction)

### The Problem

**CloudFormation State Corruption**: CloudFormation stack has phantom resolver resources that don't exist in AppSync:
- `ApiCreateOrderResolverCEF70549`
- `ApiShareProfileDirectResolver4580883B`
- `ApiRedeemProfileInviteResolver620EB666`

**What We Tried**:
1. ❌ Manual deletion from AppSync → CloudFormation still thinks they exist
2. ❌ Manual deletion of data sources from AppSync → Same issue
3. ❌ CDK deployment → Fails with "Resource already exists in stack"
4. ❌ Stack rollback → Stuck in UPDATE_ROLLBACK_COMPLETE state

**Root Cause**: When we removed Lambda resolvers from CDK code, CloudFormation retained metadata about them even after manual deletion from AppSync.

### Solution Options

#### Option 1: Manual CloudFormation Template Edit (RECOMMENDED)

```bash
# 1. Export current template
aws cloudformation get-template --stack-name kernelworx-dev --query 'TemplateBody' > /tmp/cfn-template.json

# 2. Edit /tmp/cfn-template.json and remove these 3 resources:
#    - ApiCreateOrderResolverCEF70549
#    - ApiShareProfileDirectResolver4580883B  
#    - ApiRedeemProfileInviteResolver620EB666
#    Also remove associated data sources:
#    - ApiCreateOrderDSXXXXXXXX
#    - ApiShareProfileDirectDSXXXXXXXX
#    - ApiRedeemProfileInviteDSXXXXXXXX

# 3. Upload edited template to S3
aws s3 cp /tmp/cfn-template-edited.json s3://YOUR-BUCKET/cfn-template-fixed.json

# 4. Update stack with edited template
aws cloudformation update-stack \
  --stack-name kernelworx-dev \
  --template-url https://s3.amazonaws.com/YOUR-BUCKET/cfn-template-fixed.json \
  --capabilities CAPABILITY_IAM

# 5. Wait for update to complete
aws cloudformation wait stack-update-complete --stack-name kernelworx-dev

# 6. Deploy Phase 3 changes with CDK
cd cdk && npx cdk deploy --app "uv run python app.py" --require-approval never
```

#### Option 2: Delete and Recreate Stack (NOT RECOMMENDED - LOSES DATA)

**DO NOT DO THIS** - DynamoDB table has `RETAIN` policy but still risky.

#### Option 3: Import Existing Resources

```bash
# Create import template
aws cloudformation create-change-set \
  --stack-name kernelworx-dev \
  --change-set-name import-resolvers \
  --change-set-type IMPORT \
  --resources-to-import file://resources-to-import.json \
  --template-body file://template.json
```

### Next Steps (After CloudFormation Fix)

1. **Deploy GSI8 + Phase 3 (Part 1)**:
   ```bash
   # GSI8 already deployed
   # createOrder and shareProfileDirect pipeline resolvers ready
   cd cdk && npx cdk deploy --app "uv run python app.py" --require-approval never
   ```

2. **Deploy GSI9 + Phase 3 (Part 2)**:
   ```bash
   # Uncomment GSI9 in cdk_stack.py (lines ~165-172)
   # Uncomment redeemProfileInvite pipeline resolver (lines ~1460-1580)
   cd cdk && npx cdk deploy --app "uv run python app.py" --require-approval never
   ```

3. **Verify Lambda Count**:
   ```bash
   aws lambda list-functions --query 'Functions[?starts_with(FunctionName, `kernelworx`)].FunctionName'
   # Should show only 3:
   # - kernelworx-create-profile-dev (DynamoDB transaction)
   # - kernelworx-request-report-dev (Excel/S3 file generation)
   # - kernelworx-post-auth-dev (Cognito trigger)
   ```

4. **Clean Up Code**:
   - Remove Lambda handler functions from `src/handlers/`
   - Update `TODO_SIMPLIFY_LAMBDA.md` with final stats
   - Commit and push

### Files Modified (Not Yet Deployed)

- `cdk/cdk/cdk_stack.py`:
  - Added GSI8 (DEPLOYED) and GSI9 (commented out)
  - Added 3 pipeline resolvers (createOrder, shareProfileDirect, redeemProfileInvite commented out)
  - Removed 3 Lambda functions and data sources

### Manual Changes Made to AWS

- ✅ Deleted 3 Lambda resolvers from AppSync manually
- ✅ Deleted 3 Lambda data sources from AppSync manually
- ⏸️ Need to clean up CloudFormation phantom resources

### Contact

If deployment is still failing, the issue is CloudFormation state. Follow Option 1 above to manually fix the template.

---

**Created**: December 8, 2025  
**Status**: Awaiting CloudFormation template cleanup  
**Branch**: `feature/lambda-simplification-phase1`
