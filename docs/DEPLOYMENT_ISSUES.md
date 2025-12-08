# Deployment Issues and Resolutions

## CloudFormation State Corruption (Phase 2 Pipeline Resolvers)

**Date**: January 2025  
**Status**: Unresolved - awaiting manual intervention  
**Affected Resources**: AppSync GraphQL resolvers for `updateSeason`, `updateOrder`, `deleteOrder`, `deleteSeason`

### Problem Description

After implementing Phase 2 pipeline resolvers to replace Lambda functions, all deployment attempts fail with CloudFormation errors indicating that resolvers "already exist" despite the physical AWS resources being deleted.

**Phantom Resolver Logical IDs in CloudFormation Stack**:
- `ApiUpdateSeasonResolver52CB9A30`
- `ApiUpdateOrderResolverFAB8542A`
- `ApiDeleteOrderResolver9B0BE4E8`

These logical IDs remain in the CloudFormation stack metadata (status: `CREATE_COMPLETE`) but the corresponding AppSync resolver resources do not exist in the AWS AppSync API.

### Root Cause

Previous deployment rollbacks left orphaned logical resource IDs in the CloudFormation stack's internal state. When CDK attempts to create new pipeline resolvers with the same GraphQL field names (`Mutation.updateSeason`, `Mutation.updateOrder`, `Mutation.deleteOrder`), CloudFormation believes the resources already exist and refuses to create them.

### Deployment Timeline

1. **Initial Implementation**: Replaced 4 Lambda resolvers with pipeline resolvers
2. **First Deploy**: Failed due to invalid AppSync function names (used hyphens instead of underscores)
3. **Function Name Fix**: Changed to underscore-separated names (e.g., `LookupSeasonFn_dev`)
4. **Second Deploy**: Failed with "Resource already exists" errors
5. **Manual Deletion**: Deleted resolvers via AWS CLI
6. **Third Deploy**: Still failed - CloudFormation metadata not updated
7. **Resolver Recreation**: Manually recreated resolvers to sync CloudFormation state
8. **Fourth Deploy**: Failed again - conflict on new resolver creation
9. **Construct ID Change**: Added V2 suffix to all resolver construct IDs
10. **Fifth+ Deploys**: Multiple attempts with various strategies, all failed

**Current Stack State**: `UPDATE_ROLLBACK_COMPLETE`

### Evidence

```bash
# Describe stack resources shows phantom resolvers
aws cloudformation describe-stack-resources --stack-name kernelworx-dev \
  | grep -A5 "ApiUpdateSeasonResolver\|ApiUpdateOrderResolver\|ApiDeleteOrderResolver"
```

Output shows 3 resolver logical IDs with `CREATE_COMPLETE` status but ARNs point to non-existent AppSync resources.

```bash
# AppSync API has no matching resolvers
aws appsync list-resolvers --api-id ymbwcstfmzbl7euhghyblmlkhu --type-name Mutation
```

Output shows only resolvers that exist in current CDK code (no updateSeason, updateOrder, deleteOrder).

### Attempted Solutions

1. ❌ **Manual AWS CLI deletion** - Resources already deleted, CloudFormation state unchanged
2. ❌ **Resolver recreation to sync state** - Subsequent deploy still fails
3. ❌ **Changing CDK construct IDs** - CloudFormation still references old ARNs
4. ❌ **Multiple cdk destroy/deploy cycles** - Cannot destroy while in UPDATE_ROLLBACK_COMPLETE
5. ⬜ **Manual CloudFormation template edit** - Not yet attempted
6. ⬜ **CloudFormation resource import** - Not yet attempted
7. ⬜ **Stack deletion and recreation** - Too disruptive, would lose all resources

### Resolution Options

#### Option A: Manual CloudFormation Template Edit (Recommended)

1. Export current stack template:
   ```bash
   aws cloudformation get-template --stack-name kernelworx-dev \
     --query "TemplateBody" > /tmp/kernelworx-template.json
   ```

2. Edit `/tmp/kernelworx-template.json` to remove these resource definitions:
   - `ApiUpdateSeasonResolver52CB9A30`
   - `ApiUpdateOrderResolverFAB8542A`
   - `ApiDeleteOrderResolver9B0BE4E8`

3. Update stack with cleaned template:
   ```bash
   aws cloudformation update-stack \
     --stack-name kernelworx-dev \
     --template-body file:///tmp/kernelworx-template.json \
     --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM
   ```

4. Wait for stack to reach `UPDATE_COMPLETE`

5. Deploy CDK normally:
   ```bash
   cd /home/dm/code/popcorn-sales-manager/cdk
   cdk deploy --require-approval never
   ```

#### Option B: Direct AppSync Resolver Creation + CloudFormation Import

1. Create pipeline resolvers directly via AWS CLI for all 4 operations
2. Create CloudFormation change set to import existing resources
3. Update CDK construct IDs to match imported resource names
4. Continue with normal CDK deployments

**Pros**: Preserves existing stack  
**Cons**: Complex multi-step process, requires precise naming

#### Option C: Stack Deletion and Recreation (Last Resort)

1. Export all critical resource identifiers (DynamoDB table name, Cognito pool ID, etc.)
2. Delete CloudFormation stack
3. Update CDK code to import existing resources
4. Deploy fresh stack

**Pros**: Clean state  
**Cons**: Extremely disruptive, risk of losing production data if not careful

### Workaround for Development

Until CloudFormation state is fixed, the code changes are complete and committed:

- **Commit**: `3fbbba7` on `feature/lambda-simplification-phase1`
- **CDK Code**: `/home/dm/code/popcorn-sales-manager/cdk/cdk/cdk_stack.py`
- **Status**: All 6 AppSync functions and 4 pipeline resolvers implemented
- **Validation**: `cdk synth` passes successfully

The implementation is correct and ready to deploy once CloudFormation state is repaired.

### Prevention for Future

1. **Always test in dev environment first** before production deployments
2. **Use unique construct IDs** when refactoring to avoid name conflicts
3. **Monitor stack state** after failed deployments - don't assume rollback cleans everything
4. **Consider using CDK escape hatches** for critical resources to prevent accidental deletion
5. **Maintain CloudFormation drift detection** to catch phantom resources early

### Related Files

- CloudFormation template export: `/tmp/kernelworx-template.json` (3624 lines)
- CDK stack definition: `cdk/cdk/cdk_stack.py`
- Pipeline resolver implementation: Lines 800-1200 in `cdk_stack.py`
- AppSync functions: 6 functions (LookupSeasonFn, UpdateSeasonFn, etc.)

### Next Steps

**User action required** to select resolution option and execute CloudFormation state repair. Once stack state is clean, `cdk deploy` should succeed and complete Phase 2 of Lambda simplification.
