# DynamoDB Table Analysis & Restructuring Recommendations

## Executive Summary

**Problem:** GSI propagation delays with only 3000 records are causing test timeouts and will worsen at scale.

**Solution:** Full restructuring (Alternative C) to make primary access patterns use table PKs instead of GSIs.

**Result:** 40% fewer GSIs (10 → 6), primary queries become strongly consistent.

---

## Current vs. Proposed Table Structure

### Current Tables (5 tables, 10 GSIs)

| Table | PK | SK | GSIs |
|-------|-----|-----|------|
| Accounts | accountId | - | email-index |
| Profiles | profileId | recordType | ownerAccountId-index, targetAccountId-index, inviteCode-index |
| Seasons | seasonId | - | profileId-index, catalogId-index |
| Orders | orderId | - | seasonId-index, profileId-index |
| Catalogs | catalogId | - | ownerAccountId-index, isPublic-createdAt-index |

### Proposed Tables (7 tables, 6 GSIs)

| Table | PK | SK | GSIs | Notes |
|-------|-----|-----|------|-------|
| **Accounts** | accountId | - | email-index | No change |
| **Profiles** | ownerAccountId | profileId | profileId-index (sparse) | Simplified |
| **Shares** (NEW) | profileId | targetAccountId | targetAccountId-index | Separated |
| **Invites** (NEW) | inviteCode | - | profileId-index, TTL | Separated |
| **Seasons** | profileId | seasonId | seasonId-index (sparse), catalogId-index | Refactored |
| **Orders** | seasonId | orderId | orderId-index (sparse), profileId-index | Refactored |
| **Catalogs** | catalogId | - | ownerAccountId-index, isPublic-createdAt-index | No change |

### GSI Reduction Summary

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Total Tables | 5 | 7 | +2 |
| Total GSIs | 10 | 6 | **-4 (40%)** |
| Queries hitting GSIs | ~80% | ~30% | **-50%** |

---

## Summary of 7 Tables (Post-Restructure)

1. **Accounts Table** - PK: accountId (no change)
2. **Profiles Table** - PK: ownerAccountId, SK: profileId
3. **Shares Table** (NEW) - PK: profileId, SK: targetAccountId
4. **Invites Table** (NEW) - PK: inviteCode, TTL: expiresAt
5. **Seasons Table** - PK: profileId, SK: seasonId
6. **Orders Table** - PK: seasonId, SK: orderId
7. **Catalogs Table** - PK: catalogId (no change)

---

## TABLE 1: ACCOUNTS TABLE

### Current Design
- **PK:** accountId (e.g., `ACCOUNT#{uuid}`)
- **SK:** None
- **GSI:** email-index (email as PK)

### Query Patterns
1. `getMyAccount` → Direct lookup by accountId
2. Implicit: email lookup during signup/login

### Analysis
- Only 2 query patterns, both specific to identity
- Single-key lookups don't benefit from SK
- GSI for email is necessary for auth flow

### Recommendation
**✅ KEEP CURRENT DESIGN**

**Reasoning:**
- Simple, identity-scoped table
- No multi-entity relationships
- Email GSI handles auth use case
- No complex filtering needed

---

## TABLE 2: PROFILES TABLE

### Current Design
- **PK:** profileId (e.g., `PROFILE#{uuid}`)
- **SK:** recordType (literal values: `METADATA`, `SHARE#...`, `INVITE#...`)
- **GSIs:**
  - ownerAccountId-index (list my profiles)
  - targetAccountId-index (list shared profiles)
  - inviteCode-index (lookup invite by code)

### Query Patterns
1. `getProfile(profileId)` → GetItem on PK
2. `listMyProfiles` → Query ownerAccountId-index, filter recordType=METADATA
3. `listSharedProfiles` → Query targetAccountId-index, batch get METADATA records
4. Profile invite redemption → Query inviteCode-index

### Analysis

**Primary access pattern is by OWNER, not by profile ID.**
- ListMyProfiles queries ownerAccountId (GSI) with filter on recordType
- Owner is fundamental to profile identity
- Direct getProfile happens but infrequently
- Multi-record-type design adds complexity
- Shares and Invites should be separate tables (different lifecycles)

### Recommendation
**🔄 REFACTOR: Change PK/SK + Separate Shares/Invites**

**Proposed Design:**
```
PK: ownerAccountId (clean UUID, no prefix)
SK: profileId (e.g., "PROFILE#{uuid}")

Attributes:
- sellerName, createdAt, updatedAt

GSIs:
- profileId-index (sparse, for direct getProfile lookups)
```

**Benefits:**
- ✅ Eliminates recordType complexity
- ✅ Direct query for listMyProfiles (PK query, no GSI)
- ✅ Shares/Invites in dedicated tables with proper keys
- ✅ Reduces 2 GSIs (ownerAccountId-index, targetAccountId-index, inviteCode-index → profileId-index only)
- ✅ Strongly consistent listMyProfiles queries

---

## TABLE 2A: SHARES TABLE (NEW)

### Proposed Design
```
PK: profileId (e.g., "PROFILE#{uuid}")
SK: targetAccountId (clean UUID)

Attributes:
- permissions (list: READ, WRITE)
- createdAt
- createdByAccountId

GSIs:
- targetAccountId-index (for listSharedProfiles - "profiles shared with me")
```

### Query Patterns
1. `listSharesByProfile(profileId)` → Query by PK (direct, no GSI)
2. `listSharedProfiles(accountId)` → Query targetAccountId-index
3. `getShare(profileId, targetAccountId)` → GetItem by PK+SK (direct)
4. `revokeShare(profileId, targetAccountId)` → DeleteItem by PK+SK (direct)

### Benefits
- ✅ Direct PK query for listSharesByProfile
- ✅ Composite key prevents duplicate shares
- ✅ Simple delete (no need to find shareId first)
- ✅ Only 1 GSI needed

---

## TABLE 2B: INVITES TABLE (NEW)

### Proposed Design
```
PK: inviteCode (e.g., "5CB7297E-C")
SK: None

Attributes:
- profileId
- permissions (list: READ, WRITE)
- createdByAccountId
- expiresAt (epoch seconds)
- usedAt (null until redeemed)
- usedByAccountId (null until redeemed)

TTL: expiresAt (automatic cleanup of expired invites)

GSIs:
- profileId-index (for listInvitesByProfile)
```

### Query Patterns
1. `getInvite(inviteCode)` → GetItem by PK (direct, no GSI)
2. `redeemInvite(inviteCode)` → GetItem + conditional update
3. `listInvitesByProfile(profileId)` → Query profileId-index
4. Expired invites → Auto-deleted by DynamoDB TTL

### Benefits
- ✅ Direct PK lookup for invite redemption (most common)
- ✅ Automatic TTL cleanup (no manual expiration logic)
- ✅ Global uniqueness of invite codes (PK constraint)
- ✅ Only 1 GSI needed

---

## TABLE 3: SEASONS TABLE

### Current Design
- **PK:** seasonId (e.g., `SEASON#{uuid}`)
- **SK:** None
- **GSIs:**
  - profileId-index + SK: createdAt (list by profile)
  - catalogId-index (check catalog in-use)

### Query Patterns
1. `getSeason(seasonId)` → Direct GetItem on PK
2. `listSeasonsByProfile(profileId)` → Query profileId-index, sorted by createdAt
3. `listCatalogUsage(catalogId)` → Query catalogId-index (read-only, verify deletion)

### Analysis

**Primary access pattern is by PROFILE, not by season ID.**
- Users work within a profile context
- List seasons for a profile is the main operation
- Direct getSeason is secondary
- Catalog lookup is mostly for validation

### Recommendation
**🔄 REFACTOR: Change PK and SK**

**Proposed Design:**
```
PK: profileId (clean UUID, no prefix)
SK: seasonId (e.g., "SEASON#{uuid}")

Attributes:
- seasonName, catalogId, startDate, endDate, createdAt, updatedAt

GSIs:
- seasonId-index (sparse, for direct getSeason lookups)
- catalogId-index (for catalog in-use verification)
```

**Benefits:**
- ✅ Direct query for listSeasonsByProfile (PK query, no GSI)
- ✅ Natural clustering: "all seasons for a profile"
- ✅ Reduces 1 GSI (profileId-index becomes PK)
- ✅ Strongly consistent listSeasonsByProfile queries

**Note:** Using seasonId as SK (not createdAt) to avoid collision issues and enable direct GetItem when both profileId and seasonId are known.

---

## TABLE 4: ORDERS TABLE

### Current Design
- **PK:** orderId (e.g., `ORDER#{uuid}`)
- **SK:** None
- **GSIs:**
  - seasonId-index + SK: createdAt (list by season)
  - profileId-index + SK: createdAt (cross-season profile orders)

### Query Patterns
1. `getOrder(orderId)` → Direct GetItem on PK
2. `listOrdersBySeason(seasonId)` → Query seasonId-index, sorted by createdAt
3. `listOrdersByProfile(profileId)` → Query profileId-index, sorted by createdAt
4. Analytics/reporting → Cross-season queries by profile

### Analysis

**Two primary access patterns with similar weight:**
- By season (within a season context)
- By profile (cross-season operations)
- Direct lookup is less common

### Recommendation
**🔄 REFACTOR: Prioritize SEASON pattern**

**Proposed Design:**
```
PK: seasonId (clean UUID, no prefix)
SK: orderId (e.g., "ORDER#{uuid}")

Attributes:
- profileId, customerName, customerPhone, totalAmount, paymentMethod, notes, lineItems, orderDate, createdAt, updatedAt

GSIs:
- orderId-index (sparse, for direct getOrder lookups)
- profileId-index + SK: createdAt (for cross-season queries and reporting)
```

**Rationale for SEASON as PK:**
- Most orders accessed in season context (active workflows)
- Natural partition: "orders for this season"
- Cross-season queries are analytics/reporting (less frequent)
- Simpler query model

**Benefits:**
- ✅ Direct query for listOrdersBySeason (PK query, no GSI)
- ✅ Reduces 1 GSI (seasonId-index becomes PK)
- ✅ Strongly consistent listOrdersBySeason queries

**Note:** Using orderId as SK (not createdAt) to avoid collision issues and enable direct GetItem when both seasonId and orderId are known.

---

## TABLE 5: CATALOGS TABLE

### Current Design
- **PK:** catalogId (e.g., `CATALOG#{uuid}`)
- **SK:** None
- **GSIs:**
  - ownerAccountId-index (list my catalogs)
  - isPublicStr + SK: createdAt (public catalog listing)

### Query Patterns
1. `getCatalog(catalogId)` → Direct GetItem on PK
2. Implicit: list my catalogs (for season creation)
3. `listPublicCatalogs` → Query isPublicStr-index, sorted by createdAt
4. Catalog admin → Query by owner

### Analysis

**Two distinct user groups with different patterns:**
- **Users:** Mostly getCatalog (lookup by ID, used during order entry)
- **Admins/Owners:** List by owner/public (rare operations)

**Direct lookup is dominant** (most queries are getCatalog).

### Recommendation
**✅ KEEP CURRENT DESIGN (with minor optimization)**

**Rationale:**
- getCatalog dominance justifies catalogId as PK
- Public listing is infrequent (marketing/discovery)
- Owner lookup is admin-only (rare)

**Minor Optimization:**
Consider consolidating isPublicStr + createdAt GSI:

**Optional Proposed Design:**
```
PK: catalogId (e.g., "CATALOG#{uuid}")
SK: None

Retain GSIs:
- GSI1: ownerAccountId-index (list my catalogs - optional, rarely used)
- GSI2: isPublicStr + SK: createdAt (public catalog listing)
```

**Alternative (if listing own catalogs is frequent):**
Create a second attribute `createdAt` on all catalogs for sorting in owner queries.

**Conclusion for Catalogs:**
- Keep PK as catalogId
- Keep GSIs as-is (no restructuring needed)
- Public listing is acceptable as GSI use case

---

## SUMMARY TABLE

| Table | Current PK/SK | Proposed PK/SK | GSIs Before | GSIs After |
|-------|---------------|----------------|-------------|------------|
| Accounts | accountId / - | No change | 1 | 1 |
| Profiles | profileId / recordType | ownerAccountId / profileId | 3 | 1 |
| Shares | (in Profiles) | profileId / targetAccountId | - | 1 |
| Invites | (in Profiles) | inviteCode / - | - | 1 |
| Seasons | seasonId / - | profileId / seasonId | 2 | 2 |
| Orders | orderId / - | seasonId / orderId | 2 | 2 |
| Catalogs | catalogId / - | No change | 2 | 2 |
| **TOTAL** | | | **10** | **6** |

---

## Implementation Checklist

### Pre-Work: Create Feature Branch
- [ ] Create branch `feature/dynamodb-restructure` from `fix/share-resolver-improvements`
- [ ] Ensure all 369 current tests pass before starting

---

### Phase 1: Profiles Table + Shares Table + Invites Table
**Estimated: 3-4 hours**

#### 1.1 CDK Changes
- [ ] Create new `shares` table with PK=profileId, SK=targetAccountId
- [ ] Create new `invites` table with PK=inviteCode, TTL=expiresAt
- [ ] Modify `profiles` table: PK=ownerAccountId, SK=profileId
- [ ] Add profileId-index GSI to profiles table (sparse)
- [ ] Add targetAccountId-index GSI to shares table
- [ ] Add profileId-index GSI to invites table
- [ ] Remove old GSIs from profiles table (ownerAccountId-index, targetAccountId-index, inviteCode-index)
- [ ] Add datasources for shares and invites tables

#### 1.2 Resolver Updates - Profiles
- [ ] Update `createSellerProfile` resolver (Lambda) - use new key structure
- [ ] Update `getSellerProfile` resolver - query profileId-index GSI
- [ ] Update `listMyProfiles` resolver - direct PK query on ownerAccountId
- [ ] Update `updateSellerProfile` resolver - use new key structure
- [ ] Update `deleteSellerProfile` resolver - use new key structure, cleanup shares/invites

#### 1.3 Resolver Updates - Shares
- [ ] Update `shareProfileDirect` resolver - write to shares table
- [ ] Update `revokeShare` resolver - delete from shares table
- [ ] Update `listSharesByProfile` resolver - query shares table by PK
- [ ] Update `listSharedProfiles` resolver - query targetAccountId-index
- [ ] Update `SellerProfile.permissions` field resolver - query shares table
- [ ] Update `SellerProfile.isOwner` field resolver - compare ownerAccountId

#### 1.4 Resolver Updates - Invites
- [ ] Update `createProfileInvite` resolver - write to invites table
- [ ] Update `redeemProfileInvite` resolver - read/update invites table, write to shares table
- [ ] Update `revokeProfileInvite` resolver - delete from invites table
- [ ] Update `listInvitesByProfile` resolver - query profileId-index
- [ ] Update `getInviteDetails` resolver - direct GetItem by inviteCode

#### 1.5 Lambda Updates
- [ ] Update `profile_operations.py` for new key structure
- [ ] Update `profile_sharing.py` for shares/invites tables

#### 1.6 Data Migration - Profiles/Shares/Invites
- [ ] Export existing profiles (METADATA records only)
- [ ] Export existing shares (SHARE# records)
- [ ] Export existing invites (INVITE# records)
- [ ] Transform and import to new profiles table
- [ ] Transform and import to new shares table
- [ ] Transform and import to new invites table

#### 1.7 Integration Tests - Phase 1
- [ ] Update `profileQueries.integration.test.ts` for new structure
- [ ] Update `profileOperations.integration.test.ts` for new structure
- [ ] Update `profileSharing.integration.test.ts` for shares table
- [ ] Update `shareQueries.integration.test.ts` for shares/invites tables
- [ ] Run profile/share tests: `npx vitest run --testPathPattern="profile|share"`
- [ ] All profile/share tests pass before proceeding

---

### Phase 2: Seasons Table
**Estimated: 2-3 hours**

#### 2.1 CDK Changes
- [ ] Modify `seasons` table: PK=profileId, SK=seasonId
- [ ] Add seasonId-index GSI (sparse, for direct getSeason)
- [ ] Keep catalogId-index GSI (for catalog in-use check)
- [ ] Remove profileId-index GSI (now PK)

#### 2.2 Resolver Updates
- [ ] Update `createSeason` resolver - use new key structure
- [ ] Update `getSeason` resolver - query seasonId-index GSI
- [ ] Update `listSeasonsByProfile` resolver - direct PK query
- [ ] Update `updateSeason` resolver - use new key structure
- [ ] Update `deleteSeason` resolver - use new key structure
- [ ] Update `CheckCatalogUsageFn` - still uses catalogId-index

#### 2.3 Lambda Updates
- [ ] Update `season_operations.py` if applicable

#### 2.4 Data Migration - Seasons
- [ ] Export existing seasons
- [ ] Transform: seasonId→SK, profileId→PK
- [ ] Import to new seasons table

#### 2.5 Integration Tests - Phase 2
- [ ] Update `seasonQueries.integration.test.ts` for new structure
- [ ] Update `seasonOperations.integration.test.ts` for new structure
- [ ] Update `createSeason.integration.test.ts` for new structure
- [ ] Run season tests: `npx vitest run --testPathPattern="season"`
- [ ] All season tests pass before proceeding

---

### Phase 3: Orders Table
**Estimated: 2-3 hours**

#### 3.1 CDK Changes
- [ ] Modify `orders` table: PK=seasonId, SK=orderId
- [ ] Add orderId-index GSI (sparse, for direct getOrder)
- [ ] Keep profileId-index GSI (for cross-season queries)
- [ ] Remove seasonId-index GSI (now PK)

#### 3.2 Resolver Updates
- [ ] Update `createOrder` resolver - use new key structure
- [ ] Update `getOrder` resolver - query orderId-index GSI
- [ ] Update `listOrdersBySeason` resolver - direct PK query
- [ ] Update `listOrdersByProfile` resolver - uses profileId-index
- [ ] Update `updateOrder` resolver - use new key structure
- [ ] Update `deleteOrder` resolver - use new key structure
- [ ] Update `DeleteSeasonOrdersFn` - query by PK (seasonId)

#### 3.3 Lambda Updates
- [ ] Update `order_operations.py` if applicable
- [ ] Update `report_generation.py` for new key structure

#### 3.4 Data Migration - Orders
- [ ] Export existing orders
- [ ] Transform: orderId→SK, seasonId→PK
- [ ] Import to new orders table

#### 3.5 Integration Tests - Phase 3
- [ ] Update `orderQueries.integration.test.ts` for new structure
- [ ] Update `orderOperations.integration.test.ts` for new structure
- [ ] Update `requestSeasonReport.integration.test.ts` for new structure
- [ ] Run order tests: `npx vitest run --testPathPattern="order|report"`
- [ ] All order tests pass before proceeding

---

### Phase 4: Final Validation
**Estimated: 1-2 hours**

#### 4.1 Full Test Suite
- [ ] Run complete integration test suite: `npx vitest run`
- [ ] All 369+ tests pass
- [ ] No GSI propagation timeouts

#### 4.2 Cleanup Old Tables
- [ ] Verify no references to old table structures
- [ ] Update any documentation referencing old structures

#### 4.3 Performance Validation
- [ ] Time listMyProfiles query (should be <100ms)
- [ ] Time listSeasonsByProfile query (should be <100ms)
- [ ] Time listOrdersBySeason query (should be <100ms)
- [ ] Verify no GSI-related delays in tests

#### 4.4 Commit and PR
- [ ] Commit all changes with descriptive message
- [ ] Push to `feature/dynamodb-restructure` branch
- [ ] Create PR for review

---

## Cost & Performance Impact

**After Refactoring:**
- ✅ 4 fewer GSIs across all tables (10 → 6)
- ✅ Primary queries use PK (strongly consistent)
- ✅ No GSI propagation delays for main operations
- ✅ Better cache locality (related data in same partition)
- ✅ Lower RCU/WCU for common operations
- ✅ Automatic TTL cleanup for expired invites

**Estimated Savings:** 15-25% lower query costs + eliminated GSI delays
