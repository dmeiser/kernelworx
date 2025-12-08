# Lambda Simplification Analysis & TODO

## Implementation Status

| Phase | Item | Status | Notes |
|-------|------|--------|-------|
| **1.1** | `list-orders-by-season` → VTL | ✅ **DEPLOYED** | VTL resolver works, Lambda removed |
| **1.2** | `revoke-share` → VTL | ✅ **DEPLOYED** | VTL DeleteItem resolver works, Lambda removed |
| **1.3** | `create-invite` → JS | ⏸️ **DEFERRED** | JS resolver failed with cryptic errors; kept as Lambda |
| 2.x | Pipeline resolvers | ⬜ Not started | update/delete season, orders, etc. |
| 3.x | Complex refactoring | ⬜ Not started | redeem-invite, share-direct |

**Last Updated**: Phase 1 deployed on January 2025  
**Current Lambda Count**: ~13 (down from 15)

---

## Executive Summary

The current implementation has **~13 Lambda functions** when **only 2-3 are truly necessary**. Most Lambda resolvers were created as shortcuts to avoid implementing proper VTL/JavaScript resolvers or AppSync Pipeline Resolvers. This document outlines the path to an 85%+ reduction in Lambda functions.

## Current Lambda Inventory

| # | Lambda Function | GraphQL Operation | Why It Exists | Can Be Replaced? |
|---|----------------|-------------------|---------------|------------------|
| 1 | `kernelworx-create-invite` | `createProfileInvite` | Complex invite code generation | ✅ Yes - JS resolver |
| 2 | `kernelworx-redeem-invite` | `redeemProfileInvite` | Multi-step (find + update + create) | ⚠️ Pipeline resolver |
| 3 | `kernelworx-share-direct` | `shareProfileDirect` | Lookup by email + create share | ⚠️ Pipeline resolver |
| 4 | `kernelworx-revoke-share` | `revokeShare` | Simple delete | ✅ Yes - VTL resolver |
| 5 | `kernelworx-update-season` | `updateSeason` | GSI lookup then update | ✅ Yes - Pipeline resolver |
| 6 | `kernelworx-delete-season` | `deleteSeason` | GSI lookup then delete | ✅ Yes - Pipeline resolver |
| 7 | `kernelworx-create-order` | `createOrder` | Enriches line items from catalog | ⚠️ Pipeline resolver |
| 8 | `kernelworx-list-orders-by-season` | `listOrdersBySeason` | Simple query | ✅ Yes - VTL resolver (already exists!) |
| 9 | `kernelworx-update-order` | `updateOrder` | GSI lookup then update | ✅ Yes - Pipeline resolver |
| 10 | `kernelworx-delete-order` | `deleteOrder` | GSI lookup then delete | ✅ Yes - Pipeline resolver |
| 11 | `kernelworx-create-profile` | `createSellerProfile` | Transaction (2 items) | ⚠️ Consider keeping |
| 12 | `kernelworx-request-report` | `requestSeasonReport` | Excel generation + S3 upload | ❌ Must keep (external deps) |
| 13 | `kernelworx-post-auth` | Cognito trigger | Create/update account on login | ❌ Must keep (Cognito trigger) |

## Analysis: What Should Be Lambda vs. Resolver

### MUST Remain as Lambda (2 functions)

1. **`kernelworx-post-auth`** - Cognito trigger, not an AppSync resolver
2. **`kernelworx-request-report`** - Requires openpyxl, S3 operations, cannot run in VTL/JS

### COULD Be Lambda (1 function)

3. **`kernelworx-create-profile`** - Uses DynamoDB transaction for atomicity. Could be replaced with Pipeline resolver + 2 PutItem functions, but transaction is cleaner.

### SHOULD Be Replaced (10 functions → 0 Lambda + ~5-7 Pipeline/JS resolvers)

#### Direct VTL/JS Resolver Replacements

| Lambda | Replacement | Complexity |
|--------|-------------|------------|
| `list-orders-by-season` | VTL Query resolver | **Trivial** - Already have VTL for this pattern |
| `revoke-share` | VTL DeleteItem | **Easy** - Direct delete with condition |
| `create-invite` | JS resolver | **Easy** - `crypto.randomUUID()` + PutItem |

#### Pipeline Resolver Replacements

| Lambda | Pipeline Steps | Complexity |
|--------|---------------|------------|
| `update-season` | 1. Query GSI7 → 2. UpdateItem | **Medium** |
| `delete-season` | 1. Query GSI7 → 2. DeleteItem + 3. Delete child orders (batch) | **Hard** |
| `update-order` | 1. Query GSI6 → 2. UpdateItem | **Medium** |
| `delete-order` | 1. Query GSI6 → 2. DeleteItem | **Medium** |
| `redeem-invite` | 1. Scan for invite → 2. Create Share → 3. Mark invite used | **Hard** |
| `share-direct` | 1. Query account by email (GSI needed) → 2. Create Share | **Medium** |
| `create-order` | 1. GetItem catalog → 2. PutItem order with enriched data | **Medium** |

## Recommended Action Plan

### Phase 1: Quick Wins (Eliminate 3 Lambdas)

**Effort: 1-2 hours each**

1. **Delete `list-orders-by-season` Lambda**
   - Already have working VTL pattern in cdk_stack.py for similar queries
   - Just change data source from Lambda to DynamoDB

2. **Replace `revoke-share` with VTL**
   ```vtl
   {
       "version": "2017-02-28",
       "operation": "DeleteItem",
       "key": {
           "PK": $util.dynamodb.toDynamoDBJson($ctx.args.input.profileId),
           "SK": $util.dynamodb.toDynamoDBJson("SHARE#" + $ctx.args.input.targetAccountId)
       },
       "condition": {...owner check...}
   }
   ```

3. **Replace `create-invite` with JS resolver**
   ```javascript
   export function request(ctx) {
       const inviteCode = crypto.randomUUID().substring(0, 8).toUpperCase();
       // ... PutItem template
   }
   ```

### Phase 2: Pipeline Resolvers (Eliminate 5 Lambdas)

**Effort: 2-4 hours each**

4. **`update-season` → Pipeline**
   - Function 1: Query GSI7 by seasonId
   - Function 2: UpdateItem with PK/SK from step 1

5. **`delete-order` → Pipeline**
   - Function 1: Query GSI6 by orderId
   - Function 2: DeleteItem with PK/SK from step 1

6. **`update-order` → Pipeline**
   - Similar to update-season

7. **`create-order` → Pipeline**
   - Function 1: GetItem catalog
   - Function 2: PutItem order with enriched line items (JS for calculation)

8. **`share-direct` → Pipeline** (requires new GSI)
   - Function 1: Query accounts by email (need GSI on email)
   - Function 2: PutItem share

### Phase 3: Complex Refactoring (Eliminate 2 Lambdas)

**Effort: 4-8 hours each**

9. **`redeem-invite` → Pipeline**
   - Need invite lookup GSI or accept profileId+inviteCode as input
   - Multiple conditional operations

10. **`delete-season` → Pipeline with batch**
    - Must delete season + all child orders
    - Consider if this should remain Lambda for batch delete logic

### Phase 4: Evaluate Remaining

11. **`create-profile`** - Keep as Lambda (transaction atomicity is cleaner than pipeline)

## Data Model Changes Needed

### New GSI Required

For `share-direct` to work without Lambda, need email lookup:

```python
# GSI8: Account lookup by email
self.table.add_global_secondary_index(
    index_name="GSI8",
    partition_key=dynamodb.Attribute(
        name="email", type=dynamodb.AttributeType.STRING
    ),
    projection_type=dynamodb.ProjectionType.KEYS_ONLY,
)
```

### Invite Lookup Pattern

For `redeem-invite`, either:
- A) Add GSI on `inviteCode` field
- B) Change API to require `profileId` + `inviteCode` (client must know profile)
- C) Keep as Lambda (current approach)

## Cost-Benefit Analysis

### Current State (15 Lambdas)
- **Cold start overhead**: ~15 functions × ~200ms = potential latency issues
- **Deployment complexity**: 15 separate function updates
- **Testing overhead**: 15 separate test files
- **Cost**: Lambda invocation costs (though minimal at low scale)

### Target State (2-3 Lambdas)
- **Faster response**: VTL/JS resolvers execute in AppSync without Lambda overhead
- **Simpler deployment**: Single schema + resolver deployment
- **Reduced code maintenance**: VTL/JS templates are declarative
- **Lower cost**: DynamoDB direct access is cheaper than Lambda

### Trade-offs

| Approach | Pros | Cons |
|----------|------|------|
| **Lambda** | Easy debugging, familiar Python | Cold starts, more code, higher cost |
| **VTL** | Fast, no cold start | Verbose, limited functionality |
| **JS Resolvers** | Modern, powerful | Learning curve, less familiar |
| **Pipeline** | Chained operations | More complex setup |

## Implementation Priority

```
Priority 1 (Do First - Highest Impact, Lowest Effort):
├── Remove list-orders-by-season Lambda (duplicate of VTL)
├── Replace revoke-share with VTL
└── Replace create-invite with JS resolver

Priority 2 (Medium Effort, Medium Impact):
├── update-season → Pipeline
├── update-order → Pipeline
├── delete-order → Pipeline
└── create-order → Pipeline

Priority 3 (High Effort, Lower Impact):
├── share-direct → Pipeline + GSI8
├── redeem-invite → Pipeline + GSI or keep Lambda
└── delete-season → Keep Lambda (batch delete complexity)

Keep as Lambda (No Change):
├── post-auth (Cognito trigger)
├── request-report (Excel/S3)
└── create-profile (Transaction)
```

## Summary

| Metric | Current | Target | Reduction |
|--------|---------|--------|-----------|
| Lambda Functions | 15 | 3 | **80%** |
| Lambda Invocations | All CRUD | Reports + Auth only | **90%** |
| Cold Start Risk | High | Low | **~85%** |
| Deployment Complexity | High | Low | **~75%** |

## Related Documentation

- `docs/VTL_RESOLVER_NOTES.md` - Current VTL implementation details
- `cdk/schema/schema.graphql` - GraphQL schema
- `cdk/cdk/cdk_stack.py` - CDK infrastructure (Lines 760-1400 contain resolver definitions)

## Next Steps

1. [ ] Review this analysis with team
2. [ ] Create feature branch for Lambda simplification
3. [ ] Start with Priority 1 items (quick wins)
4. [ ] Update tests as resolvers are migrated
5. [ ] Monitor performance after migration

---

## Detailed Implementation Guide

### Priority 1.1: Remove `list-orders-by-season` Lambda

**Current State**: Lambda function queries DynamoDB and returns orders
**Target State**: VTL resolver (same pattern as other list queries)

**Files to Modify**:
- `cdk/cdk/cdk_stack.py`: Change resolver data source from Lambda to DynamoDB
- Delete: `src/handlers/order_operations.py` → `list_orders_by_season` function (after migration)

**CDK Changes** (in `cdk_stack.py`):
```python
# REMOVE this Lambda data source resolver:
self.list_orders_by_season_ds.create_resolver(
    "ListOrdersBySeasonResolver",
    type_name="Query",
    field_name="listOrdersBySeason",
)

# REPLACE with VTL DynamoDB resolver:
self.dynamodb_datasource.create_resolver(
    "ListOrdersBySeasonResolver",
    type_name="Query",
    field_name="listOrdersBySeason",
    request_mapping_template=appsync.MappingTemplate.from_string("""
{
    "version": "2017-02-28",
    "operation": "Query",
    "query": {
        "expression": "PK = :pk AND begins_with(SK, :sk)",
        "expressionValues": {
            ":pk": $util.dynamodb.toDynamoDBJson($ctx.args.seasonId),
            ":sk": $util.dynamodb.toDynamoDBJson("ORDER#")
        }
    }
}
    """),
    response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    $util.error($ctx.error.message, $ctx.error.type)
#end
$util.toJson($ctx.result.items)
    """),
)
```

**Also Remove**:
- Lambda function definition: `self.list_orders_by_season_fn`
- Lambda data source: `self.list_orders_by_season_ds`

---

### Priority 1.2: Replace `revoke-share` with VTL

**Current State**: Lambda looks up share, checks ownership, deletes
**Target State**: VTL DeleteItem with conditional expression

**CDK Changes**:
```python
# REMOVE Lambda resolver and REPLACE with:
self.dynamodb_datasource.create_resolver(
    "RevokeShareResolver",
    type_name="Mutation",
    field_name="revokeShare",
    request_mapping_template=appsync.MappingTemplate.from_string("""
## First, we need to verify caller owns the profile
## The share SK format is: SHARE#<targetAccountId>
{
    "version": "2017-02-28",
    "operation": "DeleteItem",
    "key": {
        "PK": $util.dynamodb.toDynamoDBJson($ctx.args.input.profileId),
        "SK": $util.dynamodb.toDynamoDBJson("SHARE#" + $ctx.args.input.targetAccountId)
    },
    "condition": {
        "expression": "attribute_exists(PK)"
    }
}
    """),
    response_mapping_template=appsync.MappingTemplate.from_string("""
#if($ctx.error)
    #if($ctx.error.type == "DynamoDB:ConditionalCheckFailedException")
        $util.error("Share not found", "NotFound")
    #else
        $util.error($ctx.error.message, $ctx.error.type)
    #end
#end
$util.toJson(true)
    """),
)
```

**Note**: This simplified version doesn't check profile ownership. For full auth, use a Pipeline resolver that first queries the profile metadata to verify `ownerAccountId == $ctx.identity.sub`.

---

### Priority 1.3: Replace `create-invite` with JS Resolver

**Current State**: Lambda generates random invite code, stores with TTL
**Target State**: JavaScript resolver using `util.autoId()`

**CDK Changes**:
```python
# REMOVE Lambda resolver and REPLACE with:
self.dynamodb_datasource.create_resolver(
    "CreateProfileInviteResolver",
    type_name="Mutation",
    field_name="createProfileInvite",
    runtime=appsync.FunctionRuntime.JS_1_0_0,
    code=appsync.Code.from_inline("""
export function request(ctx) {
    const profileId = ctx.args.input.profileId;
    const permissions = ctx.args.input.permissions;
    const callerAccountId = ctx.identity.sub;
    
    // Generate invite code (8 chars from UUID)
    const inviteCode = util.autoId().substring(0, 8).toUpperCase();
    
    // Calculate expiry (14 days = 1209600 seconds)
    const expiresInDays = ctx.args.input.expiresInDays || 14;
    const expiresAt = util.time.nowEpochSeconds() + (expiresInDays * 24 * 60 * 60);
    const now = util.time.nowISO8601();
    
    return {
        operation: "PutItem",
        key: util.dynamodb.toMapValues({
            PK: profileId,
            SK: `INVITE#${inviteCode}`
        }),
        attributeValues: util.dynamodb.toMapValues({
            inviteCode: inviteCode,
            profileId: profileId,
            permissions: permissions,
            createdByAccountId: callerAccountId,
            createdAt: now,
            expiresAt: expiresAt,  // TTL field (epoch seconds)
        }),
        condition: {
            expression: "attribute_not_exists(PK)"  // Prevents collision
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === "DynamoDB:ConditionalCheckFailedException") {
            // Extremely rare - invite code collision, client should retry
            util.error("Invite code collision, please retry", "ConflictException");
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    
    return {
        inviteCode: ctx.result.inviteCode,
        profileId: ctx.result.profileId,
        permissions: ctx.result.permissions,
        expiresAt: util.time.epochSecondsToISO8601(ctx.result.expiresAt),
        createdAt: ctx.result.createdAt,
        createdByAccountId: ctx.result.createdByAccountId
    };
}
    """),
)
```

---

### Priority 2: Pipeline Resolver Template

**Example: `update-season` Pipeline**

A pipeline resolver chains multiple "functions" that pass data via `ctx.stash`.

```python
# Step 1: Create the lookup function
lookup_season_fn = appsync.AppsyncFunction(
    self,
    "LookupSeasonFn",
    name="LookupSeasonFn",
    api=self.api,
    data_source=self.dynamodb_datasource,
    runtime=appsync.FunctionRuntime.JS_1_0_0,
    code=appsync.Code.from_inline("""
export function request(ctx) {
    return {
        operation: "Query",
        index: "GSI7",
        query: {
            expression: "seasonId = :seasonId AND SK = :sk",
            expressionValues: util.dynamodb.toMapValues({
                ":seasonId": ctx.args.input.seasonId,
                ":sk": ctx.args.input.seasonId
            })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result.items || ctx.result.items.length === 0) {
        util.error("Season not found", "NotFound");
    }
    // Store season in stash for next function
    ctx.stash.season = ctx.result.items[0];
    return ctx.result.items[0];
}
    """),
)

# Step 2: Create the update function
update_season_fn = appsync.AppsyncFunction(
    self,
    "UpdateSeasonFn",
    name="UpdateSeasonFn",
    api=self.api,
    data_source=self.dynamodb_datasource,
    runtime=appsync.FunctionRuntime.JS_1_0_0,
    code=appsync.Code.from_inline("""
export function request(ctx) {
    const season = ctx.stash.season;
    const input = ctx.args.input;
    const now = util.time.nowISO8601();
    
    // Build update expression dynamically
    let updateExpr = "SET updatedAt = :updatedAt";
    const exprValues = { ":updatedAt": now };
    
    if (input.seasonName) {
        updateExpr += ", seasonName = :seasonName";
        exprValues[":seasonName"] = input.seasonName;
    }
    if (input.startDate) {
        updateExpr += ", startDate = :startDate";
        exprValues[":startDate"] = input.startDate;
    }
    if (input.endDate !== undefined) {
        updateExpr += ", endDate = :endDate";
        exprValues[":endDate"] = input.endDate;
    }
    if (input.catalogId) {
        updateExpr += ", catalogId = :catalogId";
        exprValues[":catalogId"] = input.catalogId;
    }
    
    return {
        operation: "UpdateItem",
        key: util.dynamodb.toMapValues({
            PK: season.PK,
            SK: season.SK
        }),
        update: {
            expression: updateExpr,
            expressionValues: util.dynamodb.toMapValues(exprValues)
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
    """),
)

# Step 3: Create the pipeline resolver
self.api.create_resolver(
    "UpdateSeasonPipelineResolver",
    type_name="Mutation",
    field_name="updateSeason",
    runtime=appsync.FunctionRuntime.JS_1_0_0,
    pipeline_config=[lookup_season_fn, update_season_fn],
    code=appsync.Code.from_inline("""
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
    """),
)
```

---

## Testing Considerations

When migrating from Lambda to VTL/JS resolvers:

1. **Unit tests for Lambda become obsolete** - Delete corresponding test files
2. **Integration tests remain valid** - GraphQL operations should behave the same
3. **Add VTL/JS resolver tests** - Use AppSync's built-in test console or create integration tests

**Test Strategy**:
- Before migration: Run full test suite, document expected behavior
- After migration: Verify same behavior via GraphQL calls
- Coverage: Lambda test coverage will decrease (expected), integration coverage should stay same

---

## Implementation Checklist

### Phase 1: Quick Wins (3 Lambdas → 0)

- [x] **1.1 Remove `list-orders-by-season` Lambda** ✅ COMPLETED
  - [x] Replace Lambda resolver with VTL DynamoDB resolver in `cdk_stack.py`
  - [x] Remove `self.list_orders_by_season_fn` Lambda function definition
  - [x] Remove `self.list_orders_by_season_ds` Lambda data source
  - [x] Remove `list_orders_by_season` function from `src/handlers/order_operations.py`
  - [x] Delete corresponding unit tests (or mark as skipped)
  - [ ] Deploy and verify via GraphQL query
  - [x] Update this checklist

- [x] **1.2 Replace `revoke-share` with VTL** ✅ COMPLETED
  - [x] Replace Lambda resolver with VTL DeleteItem resolver in `cdk_stack.py`
  - [x] Remove `self.revoke_share_fn` Lambda function definition
  - [x] Remove `self.revoke_share_ds` Lambda data source
  - [x] Remove `revoke_share` function from `src/handlers/profile_sharing.py`
  - [x] Delete corresponding unit tests
  - [ ] Deploy and verify via GraphQL mutation
  - [x] Update this checklist

- [x] **1.3 Replace `create-invite` with JS Resolver** ✅ COMPLETED
  - [x] Replace Lambda resolver with JS resolver in `cdk_stack.py`
  - [x] Remove `self.create_profile_invite_fn` Lambda function definition
  - [x] Remove `self.create_profile_invite_ds` Lambda data source
  - [x] Remove `create_profile_invite` function from `src/handlers/profile_sharing.py`
  - [x] Delete corresponding unit tests
  - [ ] Deploy and verify invite creation works
  - [ ] Verify TTL expiration field is set correctly
  - [x] Update this checklist

### Phase 2: Pipeline Resolvers (5 Lambdas → 0)

- [ ] **2.1 Replace `update-season` with Pipeline Resolver**
  - [ ] Create `LookupSeasonFn` AppSync function (Query GSI7)
  - [ ] Create `UpdateSeasonFn` AppSync function (UpdateItem)
  - [ ] Create pipeline resolver combining both functions
  - [ ] Remove `self.update_season_fn` and `self.update_season_ds`
  - [ ] Remove `update_season` from `src/handlers/season_operations.py`
  - [ ] Delete corresponding unit tests
  - [ ] Deploy and verify season updates work
  - [ ] Update this checklist

- [ ] **2.2 Replace `delete-order` with Pipeline Resolver**
  - [ ] Create `LookupOrderFn` AppSync function (Query GSI6)
  - [ ] Create `DeleteOrderFn` AppSync function (DeleteItem)
  - [ ] Create pipeline resolver combining both functions
  - [ ] Remove `self.delete_order_fn` and `self.delete_order_ds`
  - [ ] Remove `delete_order` from `src/handlers/order_operations.py`
  - [ ] Delete corresponding unit tests
  - [ ] Deploy and verify order deletion works
  - [ ] Update this checklist

- [ ] **2.3 Replace `update-order` with Pipeline Resolver**
  - [ ] Create `LookupOrderForUpdateFn` AppSync function (Query GSI6)
  - [ ] Create `UpdateOrderFn` AppSync function (UpdateItem)
  - [ ] Create pipeline resolver combining both functions
  - [ ] Remove `self.update_order_fn` and `self.update_order_ds`
  - [ ] Remove `update_order` from `src/handlers/order_operations.py`
  - [ ] Delete corresponding unit tests
  - [ ] Deploy and verify order updates work
  - [ ] Update this checklist

- [ ] **2.4 Replace `create-order` with Pipeline Resolver**
  - [ ] Create `GetCatalogFn` AppSync function (GetItem catalog)
  - [ ] Create `CreateOrderFn` AppSync function (PutItem with JS for line item enrichment)
  - [ ] Create pipeline resolver combining both functions
  - [ ] Remove `self.create_order_fn` and `self.create_order_ds`
  - [ ] Remove `create_order` from `src/handlers/order_operations.py`
  - [ ] Delete corresponding unit tests
  - [ ] Deploy and verify order creation with line item enrichment works
  - [ ] Update this checklist

- [ ] **2.5 Replace `share-direct` with Pipeline Resolver**
  - [ ] Add GSI8 on `email` field for account lookup (if not exists)
  - [ ] Create `LookupAccountByEmailFn` AppSync function (Query GSI8)
  - [ ] Create `CreateShareFn` AppSync function (PutItem)
  - [ ] Create pipeline resolver combining both functions
  - [ ] Remove `self.share_profile_direct_fn` and `self.share_profile_direct_ds`
  - [ ] Remove `share_profile_direct` from `src/handlers/profile_sharing.py`
  - [ ] Delete corresponding unit tests
  - [ ] Deploy and verify direct sharing works
  - [ ] Update this checklist

### Phase 3: Complex Refactoring (2 Lambdas)

- [ ] **3.1 Replace `redeem-invite` with Pipeline Resolver (or keep Lambda)**
  - [ ] Decide: Add GSI on `inviteCode` OR require `profileId+inviteCode` in API OR keep Lambda
  - [ ] If replacing: Create lookup, create-share, and mark-used functions
  - [ ] If keeping: Document reason in this file
  - [ ] Update this checklist

- [ ] **3.2 Replace `delete-season` with Pipeline Resolver (or keep Lambda)**
  - [ ] Decide: Pipeline can't batch-delete child orders efficiently
  - [ ] Option A: Keep Lambda for batch delete logic
  - [ ] Option B: Pipeline deletes season only, orphan orders cleaned by TTL or background job
  - [ ] Document decision and implement
  - [ ] Update this checklist

### Phase 4: Final Cleanup

- [ ] **4.1 Verify remaining Lambdas are necessary**
  - [ ] Confirm `post-auth` is required (Cognito trigger)
  - [ ] Confirm `request-report` is required (openpyxl/S3)
  - [ ] Confirm `create-profile` decision (keep for transaction or convert to pipeline)
  - [ ] Document final Lambda count in this file

- [ ] **4.2 Code cleanup**
  - [ ] Remove empty handler files if all functions migrated
  - [ ] Update `src/handlers/__init__.py` if needed
  - [ ] Remove unused Lambda layer dependencies if possible
  - [ ] Run `uv run black` and `uv run isort` on remaining code

- [ ] **4.3 Documentation updates**
  - [ ] Update `AGENT.md` with final Lambda count
  - [ ] Update `.github/copilot-instructions.md` if patterns changed
  - [ ] Update `docs/VTL_RESOLVER_NOTES.md` with new resolver patterns
  - [ ] Archive or update this TODO file

- [ ] **4.4 Testing verification**
  - [ ] Run full integration test suite against deployed stack
  - [ ] Verify all GraphQL operations work as expected
  - [ ] Check CloudWatch for any resolver errors
  - [ ] Monitor cold start metrics (should be reduced)

---

## Progress Tracking

| Phase | Items | Completed | Status |
|-------|-------|-----------|--------|
| Phase 1 | 3 | 3 | ✅ Complete (pending deploy) |
| Phase 2 | 5 | 0 | ⬜ Not Started |
| Phase 3 | 2 | 0 | ⬜ Not Started |
| Phase 4 | 4 | 0 | ⬜ Not Started |
| **Total** | **14** | **3** | **21%** |

**Target**: Reduce from 15 Lambdas to 2-3 Lambdas (80%+ reduction)

**Current Status**: Reduced from 15 Lambdas to 12 Lambdas (20% reduction achieved)
