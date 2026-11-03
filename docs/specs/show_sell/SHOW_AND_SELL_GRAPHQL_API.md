# Show & Sell and inventory GraphQL API contract

**Status:** Proposed resolver contracts; no resolver implementation  
**Last updated:** 2026-10-30  
**Requirements:** [Show & Sell and inventory specification](SHOW_AND_SELL_INVENTORY_SPECIFICATION.md)  
**Data model:** [Show & Sell data model](SHOW_AND_SELL_DATA_MODEL.md)  
**Acceptance workflows:** [Show & Sell smoke test plan](SHOW_AND_SELL_SMOKE_TEST_PLAN.md)  
**Endpoint E2E descriptions:** [Show & Sell GraphQL E2E test descriptions](SHOW_AND_SELL_GRAPHQL_E2E_TEST_DESCRIPTIONS.md)  
**Reporting architecture:** [Browser-only reporting and document generation](BROWSER_REPORTING_ARCHITECTURE.md)  
**Transaction sequences:** [Show & Sell sequence diagrams](SHOW_AND_SELL_SEQUENCE_DIAGRAMS.md)

## 1. Purpose

This document defines the required GraphQL queries and mutations, their inputs and outputs, who may invoke them, and the limits each operation must enforce. It is an API/security contract, not resolver code or GraphQL SDL.

The existing Account, SellerProfile, Campaign, Catalog, Product, Order, and Share APIs remain in place except for the explicit Order extensions in Section 10.

## 2. Security model

### 2.1 Actors

| Actor | Meaning and allowed boundary |
| --- | --- |
| **Authenticated Account** | Any valid Cognito caller. May create a Unit, redeem a Unit invite, inspect a Unit Campaign join preview, and join a Scout Campaign they can administer. |
| **Unit Admin (Unit Kernel)** | Holder of a current `UnitAccessGrant` for the resource's `unitId`. Full operational access within that Unit only. The two names are synonyms for one authorization check. |
| **SellerProfile Owner / WRITE** | Current owner or WRITE collaborator for a Scout. May manage that Scout's slot signups and individual sales. WRITE includes READ. |
| **SellerProfile READ** | May read that Scout's opportunities, custody, commitments, and sales summaries but cannot perform mutations. |
| **Global application Admin** | Existing operational role. Receives **no implicit Unit access** and cannot bypass Unit/Profile authorization. Existing global-admin APIs remain separate. |
| **Buyer / API-key caller** | No access to these Unit/Show & Sell APIs. Buyers do not create Show & Sell sales or read We Owe records. Public-order/API-key behavior is unchanged. |

### 2.2 Authorization rules

`SEC-01` **Resource-derived tenancy:** The server derives `unitId`, `unitCampaignId`, `profileId`, and `campaignId` from the requested object. Client-supplied tenancy fields are consistency checks only and are never the basis for granting access.

`SEC-02` **Current grants:** Every privileged operation re-reads the Unit grant, membership, or SellerProfile access on every call. Removed access takes effect immediately.

`SEC-03` **Cross-tenant behavior:** An ID outside the caller's authorized Unit/Profile scope returns `NOT_FOUND`, not a resource-existence oracle. An authenticated caller attempting a disallowed action on a resource they may otherwise see receives `FORBIDDEN`.

`SEC-04` **Role-specific output types:** Administrative and participant read models are separate. Participant types never contain inventory balances, buyer details, payment Other details, cash reconciliation, audit actors, finalization data, or other Scouts' credit.

`SEC-05` **No client-calculated authority:** Stock, capacity, overlap, membership, split, cash, and finalization results are calculated and validated server-side. UI previews are advisory until the mutation commits.

`SEC-06` **Strong checks for invariants:** Authorization, stock, membership status, signup conflicts, version checks, and finalization state use authoritative base-table reads/version checks. GSIs are for discovery only.

`SEC-07` **Field-level payment privacy:** `Other` details, buyer name/contact, and QR signing information are Unit Admin-only. Participant payment views, if any, contain only method display names needed for event information.

### 2.3 Access matrix

| Operation category | Authenticated Account | Unit Admin | Profile READ | Profile Owner/WRITE | Buyer/API key |
| --- | :---: | :---: | :---: | :---: | :---: |
| Create Unit / redeem Unit invite | Yes | Yes | Yes | Yes | No |
| Administer Unit, grants, settings, payment methods | No | Yes | No | No | No |
| Join own Scout Campaign with code | If Owner/WRITE | Yes | No | Yes | No |
| Read own Scout opportunities/summaries | No | Yes | Yes | Yes | No |
| Manage own Scout signups / download own ICS | No | Yes | No | Yes | No |
| Record individual sale using own Scout custody | No | Yes | No | Yes | No |
| Inventory, event stock, payments, We Owe, cash, administrative Unit/event reports | No | Yes | No | No | No |
| Own-Scout report facts, approved credit, and pending allocations | No | Yes | Yes | Yes | No |
| Event sale entry, correction, finalization, reopening | No | Yes | No | No | No |
| Any operation in another Unit | No | No | No | No | No |

All new types/fields require Cognito authentication at the schema boundary, but schema directives are authentication only. The resolver checks above are the actual Unit/Profile authorization layer; no field is API-key/public enabled.

## 3. Shared API contracts

### 3.1 Common input types

| Input | Fields and rules |
| --- | --- |
| `PageInput` | `limit: Int = 50` (1–100), `cursor: String` opaque and server-issued |
| `IdempotencyInput` | `idempotencyKey: String!`, 1–128 trimmed characters; required on every new mutation |
| `VersionedInput` | `expectedVersion: Int!` for updates/destructive/state-changing operations; creates do not require it |
| `ProductQuantityInput` | `productId: ID!`, `quantity: Int!`, integer 1–1,000,000 unless otherwise stated |
| `AllocationTargetInput` | `productId: ID!`, `quantity: Int!`, integer 0–1,000,000; zero removes the remaining target allocation |
| `ProductReturnInput` | `productId`, `actualQty: Int!` (0–1,000,000), `reason: String` required whenever reconciliation creates a stock-only adjustment |
| `MoneyAdjustmentInput` | Integer cents; no floating-point money accepted |
| `DateRangeFilter` | Optional `startAt`/`endAt` ISO-8601 UTC; end must be after start; maximum report range 366 days |

All new mutations include `idempotencyKey`. A key is scoped to actor + operation type + resource scope and retained for seven days. Resource scope is `unitId` when one exists, `joinCode` for campaign join, `inviteCode` for Unit-invite redemption (which survives deletion of the invite), or the fixed bootstrap scope for `createUnit`. Marker items live in existing aggregate tables; bootstrap markers are not dependent on the newly created Unit or consumed invite. Reusing a key with different normalized content returns `INVALID_INPUT`; a valid retry returns the original result without new effects.

### 3.2 Common output types

| Output | Contents |
| --- | --- |
| `PageInfo` | `endCursor`, `hasNextPage`; connections contain `items` and `pageInfo` |
| `InventoryPosition` | `InventoryBalance`, `sellableKernelQty`, `assignedOpenQty`, `unassignedKernelQty`, `assignmentOverageQty`, `withScoutQty`, `totalUnitOwnedUndeliveredQty` |
| `AllocationWarning` | `code`, `productId`, `currentStockQty`, `assignedQty`, `overageQty`, `message`; currently `SEQUENTIAL_OVER_ASSIGNMENT` or `AUTOMATIC_ALLOCATION_REDUCTION` |
| `ValidationIssue` | `code`, `field`, `message`, optional `productId`/`profileId`; used by previews to explain finalization blockers |
| `CalendarInviteData` | Authorized Unit/Unit Campaign/event/slot/profile/signup identity, location/address, IANA `timezone`, and UTC timestamps used by the frontend to generate ICS; contains no generated file |
| `AdminOrderLineFact` | Full administrative Order/Campaign/Scout/customer contact/product name/quantity/fulfilled/price/subtotal/order-total/payment/date/origin fields needed for Order Details parity |
| `ParticipantOrderLineFact` | Own-Scout Order/Campaign/product ID and name/quantity/fulfilled/price/subtotal/order-total/date/origin fields; excludes customer contact and administrative audit data |
| `ParticipantSalesCredit` | Own-Scout `showAndSellId`, `unitCampaignId`, `campaignId`, `profileId`, `amountCents`, `actualMinutes`, `creditState`, and `eventVersion`; excludes finalizationId, actors, and other administrative finalization data |
| `ParticipantPendingAllocation` | Own-Scout `showAndSellId`, `unitCampaignId`, `campaignId`, `profileId`, `pendingAmountCents`, `eventVersion`, `computedAt`; excludes other Scouts, cash, returns, and administrative preview fields |
| `ShowAndSellSaleResult` | `sale`, affected `allocations`, `inventoryPositions`, `weOweObligations`, `warnings` |
| `FinalizationPreview` | `wholePoolCents`, `baseAllocations`, `unassignedCents`, `returnLines`, `cashPreview`, `issues`, `eventVersion` |
| `FinalizationResult` | `event`, `finalization`, approved `scoutAllocations`, affected `inventoryPositions`, later-allocation `warnings` |

`FinalizationPreview` and pending split results are computed, not approved credit. Approved summaries use the persisted finalization/projection models.

### 3.3 Error contract

| Error | Used for |
| --- | --- |
| `UNAUTHORIZED` | Missing/invalid session; sign in again |
| `FORBIDDEN` | Caller lacks Unit Admin or Profile WRITE on a resource they may otherwise see |
| `NOT_FOUND` | Unknown, inactive, or cross-tenant resource without disclosing its existence |
| `INVALID_INPUT` | Bad quantity/time/text/payment/reason/idempotency shape or an invalid state-specific input |
| `CONFLICT` | Stale version, concurrent stock/overlap/capacity conflict, last-grant removal, finalization precondition failure |
| `RESOURCE_BUSY` | Retryable transaction contention or infrastructure throttling |
| `RATE_LIMIT_EXCEEDED` | Invite-redemption abuse limit reached |
| `INTERNAL_ERROR` | Unexpected failure; no sensitive payload in the message |

Stock, slot, roster, and finalization errors identify the product/slot/field only when the caller is authorized to see it.

### 3.4 Shared validation limits

| Field/operation | Limit |
| --- | --- |
| Page size | Default 50; maximum 100 |
| Sale/allocation/return product lines | Computed per mutation from the complete write plan, capped at 90 actions. Typical immediate-sale capacity is about 29 products (`3 + 3P`); worst-case mixed We Owe capacity is about 21 (`3 + 4P`), and actual capacity may be lower with other writes. Larger orders must be split into independently atomic sales. Finalization accepts 0 only when the event has no allocated products and otherwise requires every allocated product, with no event-wide product-count cap |
| Slots per Show & Sell | 1–20 |
| Slot capacity | 1–100 active Scouts per slot; also subject to the combined write-set limit below |
| Confirmed work | `actualMinutes = 0` means unconfirmed/no credit; confirmed work is integer 1 through the slot's duration in minutes |
| Location name | 1–100 trimmed characters |
| Optional address | Maximum 500 characters |
| Unit/payment/display names | 1–100 trimmed characters |
| Buyer name | 1–200 trimmed characters when We Owe is present |
| Other payment details | 1–500 trimmed characters when method is Other; split payments use this field |
| Adjustment/correction/cash reasons | 1–500 trimmed characters when required |
| Quantity | Integer 0–1,000,000 where zero is meaningful; positive when receiving/selling/issuing/fulfilling |
| Money | Integer cents; sale price/total non-negative; manual cash adjustment may be signed |
| QR upload | Reuse existing payment-QR content-type/size/signature validation and S3 authorization |
| Custom Unit payment methods | Maximum 50 active methods per Unit |
| Active unused Unit invites | Maximum 20 per Unit |
| Invite redemption | 16-character code, 14-day expiry, 10 failed attempts per Account per hour |
| Event/sale timestamps | Event end after start; slot within event; `saleAt` within event; no event-time updates |

**Combined write-set and finalization-feasibility limits:** Field maxima are not independently composable. Before writing, every mutation computes its complete action count (business writes, snapshots, balances, commitments, movements, credit projections, and idempotency marker). A logical mutation may use at most 90 DynamoDB transaction actions, leaving headroom below the service limit. If the complete operation exceeds 90, it fails before any write with `CONFLICT`/`OPERATION_TOO_LARGE` and identifies the required reduction.

Additionally, every mutation that adds signups, confirmed participants, sales, products, or later-event allocation work must preflight the **minimum resulting finalization write set**, not merely its own writes. It is rejected while the event is still correctable if the resulting event could not legally finalize within 90 actions. Unit Admins may reduce the set by cancelling signups during allowed correction states, setting `actualMinutes = 0` to unconfirm a participant, correcting/voiding sales, or reducing allocations/later-event commitments. Thus an event cannot be allowed to reach an irreducible state where finalization permanently fails. Tests must cover the largest supported combinations, not only 15-line sales. No partial commit or oversized coordinator is used.

There is no per-event payment-method allowlist, no event rescheduling input, no multiple-tender input, no offline queue input, and no cross-campaign transfer input.

### 3.5 Event-state mutation matrix

| Operation | Allowed event states | Additional timing rule |
| --- | --- | --- |
| Update location/split/We Owe, assign inventory | `SCHEDULED`, `ACTIVE`, `ENDED`; draft-only in `REOPENED` | Never `FINALIZED` or `CANCELLED` |
| Create/update/delete slots | `SCHEDULED` only | Existing commitments are revalidated |
| Create signup | `SCHEDULED` only | ACTIVE membership required |
| Cancel signup | `SCHEDULED` for Unit Admin or Profile Owner/WRITE; `ACTIVE`, `ENDED`, `REOPENED` for Unit Admin correction only | Finalized events require reopen; removed membership does not block historical cleanup |
| Confirm/unconfirm work | `ACTIVE`, `ENDED`, `REOPENED` | `actualMinutes = 0` unconfirms/frees finalization budget; positive minutes confirm; reopened changes are drafts |
| Create sale | `ACTIVE`, `ENDED`; draft-only in `REOPENED` | `saleAt` must be inside the event; scheduled future events reject sale entry |
| Correct/void sale | `ACTIVE`, `ENDED`, `REOPENED` | Applies immediate deltas before first approval and deferred deltas after reopen |
| Cancel event | `SCHEDULED` only | Current time must be before `startAt` |
| Finalize | `ENDED`, `REOPENED` | Never active/scheduled/finalized/cancelled |
| Reopen | `FINALIZED` only | Suspends credit without changing returned stock |

Any mutation attempted outside this matrix returns `CONFLICT`, except a cross-tenant resource which returns `NOT_FOUND` and a caller without the required role which receives `FORBIDDEN`.

## 4. Unit and Unit Campaign resolvers

### 4.1 Unit queries

| Resolver | Input | Output | Caller and limits |
| --- | --- | --- | --- |
| `myUnits` | `page: PageInput` | `UnitConnection` containing only Units with the caller's grant | Any authenticated Account; no cross-Unit data |
| `unit` | `unitId: ID!` | `Unit` including settings/adminCount | Unit Admin for that Unit |
| `unitAdmins` | `unitId`, `page` | `UnitAccessGrantConnection` | Unit Admin; account email/name limited to necessary administration fields |
| `unitInvites` | `unitId`, `page` | `UnitInviteConnection` | Unit Admin; invite code returned only for active unused invites |
| `unitPaymentMethods` | `unitId`, `includeInactive: Boolean = false` | `[UnitPaymentMethod!]!` plus built-in Cash/Check/Other | Unit Admin; maximum 50 active custom methods |
| `unitPaymentMethodQrDownloadUrl` | `unitId`, `paymentMethodId` | `{ downloadUrl, expiresAt }` for the authorized QR image only | Unit Admin; short-lived S3 GET URL for frontend image embedding, not a report download; browser fetches/embeds image before offline printing |
| `unitCampaignJoinInfo` | `joinCode: String!` | `UnitCampaignJoinPreview { unitDisplayName, campaignName, campaignYear, catalogName, isActive }` | Any authenticated Account; inactive/unknown code returns `NOT_FOUND`; no inventory/roster/grant data |
| `unitCampaign` | `unitCampaignId: ID!` | `UnitCampaignAdmin` including joinCode and settings | Unit Admin; member-safe preview uses `unitCampaignJoinInfo` |
| `unitCampaignCatalog` | `unitCampaignId` | `{ catalogId, catalogName, products[{productId, productName, description, price, sortOrder}] }` | Unit Admin; current catalog/product inputs for browser sales sheets, including events with no sales |
| `unitCampaigns` | `unitId`, `isActive`, `page` | `UnitCampaignConnection` | Unit Admin for the parent Unit |
| `unitCampaignRoster` | `unitCampaignId`, `status`, `page` | `UnitCampaignMembershipConnection` | Unit Admin; includes removed history |

### 4.2 Unit mutations

| Resolver | Input | Output | Caller and limits |
| --- | --- | --- | --- |
| `createUnit` | `unitType`, `unitNumber`, `city`, `state`, optional `displayName`, `timezone`, `splitDefault`, `councilNeedBasis`, `duplicateConfirmed: Boolean = false`, `idempotencyKey` | `Unit` and creator `UnitAccessGrant` | Any authenticated Account; creator becomes initial Unit Admin; exact metadata duplicate requires `duplicateConfirmed: true` |
| `updateUnit` | `unitId`, optional metadata/settings fields, `expectedVersion`, `idempotencyKey` | `Unit` | Unit Admin; cannot edit `unitId` or adminCount; duplicate warning rules apply |
| `createUnitInvite` | `unitId`, `idempotencyKey` | `UnitInvite` | Unit Admin; 16-character, 14-day code; maximum 20 active unused invites |
| `revokeUnitInvite` | `unitId`, `inviteCode`, `idempotencyKey` | `Boolean` | Unit Admin; unused invite only; redeemed/deleted code returns `NOT_FOUND` |
| `redeemUnitInvite` | `inviteCode`, `idempotencyKey` | `UnitAccessGrant` | Any authenticated Account; single-use, unexpired code; duplicate existing grant returns current grant without incrementing adminCount; failed-attempt throttle |
| `revokeUnitAccessGrant` | `unitId`, `accountId`, `expectedVersion` (Unit), `idempotencyKey` | `Unit` | Unit Admin; last grant returns `CONFLICT`; no self-removal UI required |

### 4.3 Unit payment-method mutations

| Resolver | Input | Output | Caller and limits |
| --- | --- | --- | --- |
| `createUnitPaymentMethod` | `unitId`, `displayName`, `idempotencyKey` | `UnitPaymentMethod` | Unit Admin; Cash/Check/Other names reserved case-insensitively; maximum 50 active |
| `updateUnitPaymentMethod` | `unitId`, `paymentMethodId`, `displayName`, `expectedVersion`, `idempotencyKey` | `UnitPaymentMethod` | Unit Admin; same reserved/duplicate-name rules; server consistently queries the Unit's payment collection to resolve ID; historical snapshots unchanged |
| `deactivateUnitPaymentMethod` | `unitId`, `paymentMethodId`, `expectedVersion`, `idempotencyKey` | `UnitPaymentMethod` | Unit Admin; soft deactivate only; historical sales remain readable |
| `requestUnitPaymentMethodQrUpload` | `unitId`, `paymentMethodId`, `contentType`, `idempotencyKey` | `S3UploadInfo` containing scoped upload URL/fields/key | Unit Admin; existing QR validation and S3 key rules |
| `confirmUnitPaymentMethodQrUpload` | `unitId`, `paymentMethodId`, `s3Key`, `expectedVersion`, `idempotencyKey` | `UnitPaymentMethod` with QR reference | Unit Admin; validates Unit ownership, upload, type, and size |
| `deleteUnitPaymentMethodQrCode` | `unitId`, `paymentMethodId`, `expectedVersion`, `idempotencyKey` | `UnitPaymentMethod` | Unit Admin; removes S3 object and reference without altering sale history |

### 4.4 Unit Campaign mutations

| Resolver | Input | Output | Caller and limits |
| --- | --- | --- | --- |
| `createUnitCampaign` | `unitId`, `campaignName`, `campaignYear`, `catalogId`, `idempotencyKey` | `UnitCampaignAdmin` including joinCode | Unit Admin; catalog must exist and be usable by the Unit Campaign |
| `updateUnitCampaign` | `unitCampaignId`, optional name/year/isActive, `expectedVersion`, `idempotencyKey` | `UnitCampaignAdmin` | Unit Admin; deactivation has no inventory/obligation side effects; `catalogId` is immutable after creation |
| `joinUnitCampaign` | `joinCode`, `campaignId`, `idempotencyKey` | `UnitCampaignMembership` | Account with Owner/WRITE for the Campaign's SellerProfile; one active membership per Campaign; target roster identity must match the Scout; removed historical links do not block a new target |
| `removeUnitCampaignMembership` | `unitCampaignId`, `campaignId`, `expectedMembershipVersion`, `expectedGuardVersion`, `idempotencyKey` | `UnitCampaignMembership` | Unit Admin; sets `REMOVED`, blocks new signups only, performs no historical cascade |

## 5. Inventory and Scout-custody resolvers

### 5.1 Inventory queries

| Resolver | Input | Output | Caller and limits |
| --- | --- | --- | --- |
| `inventoryPositions` | `unitCampaignId`, optional `productIds` (max 15), `page` | `InventoryPositionConnection` | Unit Admin; derived assigned/unassigned/overage values computed server-side |
| `inventoryMovements` | `unitCampaignId`, optional `productId`, `movementType`, `showAndSellId`, `profileId`, `dateRange`, `page` | `InventoryMovementConnection` | Unit Admin; maximum date range 366 days |
| `orderFulfillments` | `orderId`, `page` | `OrderFulfillmentConnection` with actor/source/movement/reversal audit | Unit Admin for the Order's originating Unit; full administrative history |
| `scoutCustodyBalances` | `unitCampaignId`, optional `profileId`, optional `productId`, `page` | `ScoutCustodyBalanceConnection` | Unit Admin; includes per-Scout and aggregate views |
| `myScoutCustody` | `profileId`, `unitCampaignId` | `[ScoutCustodyBalance!]!` | Profile READ/Owner/WRITE for that Scout or Unit Admin; no other Scouts' balances |
| `myScoutCommitments` | `profileId`, optional `unitId`, optional `includeCancelled = false`, `page` | `ParticipantCommitmentConnection` without actor/account IDs | Profile READ/Owner/WRITE may see the Scout's cross-Unit commitments. Unit Admin must supply an authorized `unitId` and receives only that Unit's commitments; conflict enforcement remains global without exposing other-Unit details |

### 5.2 Inventory mutations

All inventory mutations are Unit Admin-only and require `idempotencyKey`. Balance versions are server-managed and returned for subsequent retry/verification.

| Resolver | Input | Output | Limits and behavior |
| --- | --- | --- | --- |
| `recordInventoryReceipt` | `unitCampaignId`, `productId`, `quantity`, optional `occurredAt`, `idempotencyKey` | `InventoryPosition` | Positive integer quantity; no order/payment/credit effects |
| `adjustInventory` | `unitCampaignId`, `productId`, `quantityDelta` (signed nonzero), `reason`, `idempotencyKey` | `InventoryPosition` | Stock-only adjustment; resulting balances must satisfy `kernelPhysicalQty >= soldInPossessionQty >= 0`; no trade/payment/sale effects |
| `adjustCouncilOnOrder` | `unitCampaignId`, `productId`, `quantityDelta`, optional `reason`, `idempotencyKey` | `InventoryPosition` | Separate on-order balance; cannot become negative; never auto-subtracted from Council Needs |
| `issueStockToScout` | `unitCampaignId`, `campaignId`, `profileId`, `productId`, `quantity`, `idempotencyKey` | `inventoryPosition`, `custodyBalance` | Campaign/Profile must match roster identity; uses unassigned stock; creates no sale/fulfillment/credit |
| `returnStockFromScout` | `unitCampaignId`, `campaignId`, `profileId`, `items[ProductQuantityInput]` (computed transaction-safe batch), `idempotencyKey` | `inventoryPositions`, `custodyBalances` | One-click atomic return; cannot exceed per-product With Scout balance or the 90-action write plan; larger returns are split |
| `fulfillIndividualOrderLine` | `orderId`, `lineItemId`, `quantity`, `source: KERNEL_STOCK or EXTERNAL_COUNCIL`, `expectedFulfillmentVersion`, `idempotencyKey` | `order`, `fulfillment`, optional `inventoryPosition` | Unit Admin for the Order's originating Unit; quantity cannot exceed unfulfilled; Kernel source uses unassigned stock; external source changes no stock |
| `reverseIndividualOrderFulfillment` | `orderId`, `fulfillmentId`, `expectedFulfillmentVersion`, `idempotencyKey` | `order`, `reversal`, optional `inventoryPosition` | Unit Admin for the originating Unit; at most one reversal per fulfillment; restores only original stock source and demand |

## 6. Show & Sell event, slot, and signup resolvers

### 6.1 Event and participant queries

| Resolver | Input | Output | Caller and limits |
| --- | --- | --- | --- |
| `showAndSell` | `showAndSellId: ID!` | `ShowAndSellAdmin` including allocations/slots/status/version | Unit Admin |
| `showAndSells` | `unitCampaignId`, optional `status`, `dateRange`, `page` | `ShowAndSellAdminConnection` | Unit Admin; administrative schedule/history |
| `unitCampaignOpportunities` | `unitCampaignId`, optional `includePast = false`, `page` | `ShowAndSellOpportunityConnection` with public event/slot fields and caller's Scout signup summaries | Profile READ/Owner/WRITE with an eligible joined Scout or existing participation; Unit Admin may use admin query; no stock/sales/buyer data |
| `showAndSellOpportunity` | `showAndSellId`, `profileId` | `ShowAndSellOpportunity` including slots and that Scout's commitments | Profile READ/Owner/WRITE for the Scout or Unit Admin; ineligible Scout receives `NOT_FOUND` |
| `showAndSellSales` | `showAndSellId`, optional `status`, `page` | `ShowAndSellSaleConnection` | Unit Admin; contains buyer/payment snapshots |
| `showAndSellSignups` | `showAndSellId`, optional `status`, `page` | `ShowAndSellSignupAdminConnection` including actor/confirmation audit | Unit Admin; full administrative signup/work records |
| `showAndSellFinalizationPreview` | `showAndSellId` | `FinalizationPreview` | Unit Admin; computes pool, base shares, unassigned cents, expected returns, cash, and blockers without approving credit |
| `showAndSellFinalizations` | `showAndSellId`, `page` | `ShowAndSellFinalizationSummaryConnection` with `finalizationId`, `versionNumber`, `status`, `approvedAt`, `previousFinalizationId` | Unit Admin; discovery of approved, suspended, and superseded versions for historical browser reports |
| `showAndSellFinalization` | `showAndSellId`, `finalizationId` | `ShowAndSellFinalization` metadata, cash, status, and version identifiers | Unit Admin; detail collections use the paginated child resolvers below |
| `showAndSellFinalizationSaleSnapshots` | `showAndSellId`, `finalizationId`, `page` | `FinalizationSaleSnapshotConnection` | Unit Admin; immutable sale/payment/buyer details |
| `showAndSellFinalizationWorkSnapshots` | `showAndSellId`, `finalizationId`, `page` | `FinalizationWorkSnapshotConnection` | Unit Admin; immutable per-slot work |
| `showAndSellFinalizationReturnLines` | `showAndSellId`, `finalizationId`, `page` | `ReturnReconciliationLineConnection` | Unit Admin; immutable expected/actual/net stock effects |
| `showAndSellFinalizationCredits` | `showAndSellId`, `finalizationId`, `page` | `ScoutSalesAllocationConnection` | Unit Admin; immutable credit amounts/status for the version |

### 6.2 Event mutations

| Resolver | Input | Output | Caller and limits |
| --- | --- | --- | --- |
| `createShowAndSell` | `unitCampaignId`, `locationName`, optional `address`, `startAt`, `endAt`, optional `splitMethod`, `weOweEnabled = false`, `idempotencyKey` | `ShowAndSellAdmin` | Unit Admin; event times immutable after creation; overlap allowed |
| `updateShowAndSell` | `showAndSellId`, optional `locationName`, `address`, `splitMethod`, `weOweEnabled`, `expectedVersion`, `idempotencyKey` | `ShowAndSellAdmin` | Unit Admin; no startAt/endAt input; finalized event requires reopen; disabling We Owe cannot strand an invalid current sale |
| `cancelShowAndSell` | `showAndSellId`, `expectedVersion`, `reason`, `idempotencyKey` | `ShowAndSellAdmin` plus released allocations/signups | Unit Admin, before start only; atomically releases allocations and cancels signups; later events require finalization/reopen |
| `assignShowAndSellInventory` | `showAndSellId`, `items[AllocationTargetInput]` (computed transaction-safe batch), `expectedVersion`, `idempotencyKey` | `allocations`, `inventoryPositions`, `warnings` | Unit Admin; omitted products remain unchanged; target zero releases remaining allocation; hard-block concurrent over-assignment, warn on sequential over-assignment, never change physical stock; split batches that would exceed 90 actions |

### 6.3 Slot mutations

| Resolver | Input | Output | Caller and limits |
| --- | --- | --- | --- |
| `upsertShowAndSellSlot` | `showAndSellId`, optional `slotId`, `label`, `startAt`, `endAt`, `capacity`, `expectedEventVersion`, optional `expectedSlotVersion` (required on update), `idempotencyKey` | `ShowAndSellSlot` | Unit Admin; arbitrary duration inside event; maximum 20 slots; capacity 1–100; updates revalidate existing signups and reject new conflicts/capacity overflow |
| `deleteShowAndSellSlot` | `showAndSellId`, `slotId`, `expectedVersion`, `idempotencyKey` | `Boolean` | Unit Admin; parent ID enables consistent base-table lookup; requires zero active signups so deletion never silently cancels participants |

### 6.4 Signup and work mutations

| Resolver | Input | Output | Caller and limits |
| --- | --- | --- | --- |
| `signupScoutForShowAndSellSlot` | `showAndSellId`, `slotId`, `campaignId`, `profileId`, `idempotencyKey` | `ParticipantSignup` without actor/account IDs | Unit Admin or Profile Owner/WRITE for the same Scout; ACTIVE membership required; duplicate/capacity/cross-campaign time conflicts return `CONFLICT`; Unit Admin audit fields use `showAndSellSignups` |
| `cancelShowAndSellSignup` | `showAndSellId`, `slotId`, `profileId`, `expectedVersion`, `idempotencyKey` | `ParticipantSignup` | Unit Admin or Profile Owner/WRITE; allowed after membership removal for historical cleanup; cancels commitment atomically; finalized events require Kernel reopen |
| `confirmShowAndSellWork` | `showAndSellId`, `work[{slotId, profileId, actualMinutes}]` (1–100 per call), `expectedVersion`, `idempotencyKey` | `[ShowAndSellSignupAdmin!]!` and `FinalizationPreview` | Unit Admin; one record per Scout/slot; 0 unconfirms, 1 through slot duration confirms; applies finalization-feasibility preflight and updates pending preview only |

## 7. Show & Sell sale and We Owe resolvers

### 7.1 Sale mutations

| Resolver | Input | Output | Caller and limits |
| --- | --- | --- | --- |
| `createShowAndSellSale` | `showAndSellId`, `expectedEventVersion`, `saleAt`, optional buyer fields, `lineItems[ShowAndSellSaleLineInput]` (computed transaction-safe batch), `paymentMethod{methodCode, otherDetails}`, `idempotencyKey` | `ShowAndSellSaleResult` | Unit Admin only; `ACTIVE`/`ENDED` or draft-only `REOPENED`; saleAt inside event; immediate stock validated; We Owe setting enforced; reopened sales defer stock effects; larger orders are split into independently atomic sales |
| `correctShowAndSellSale` | `showAndSellId`, `saleId`, `expectedRevision`, `expectedEventVersion`, corrected sale fields including `lineItems[CorrectionLineInput]`, `reason`, `idempotencyKey` | `ShowAndSellSaleResult` including prior revision | Unit Admin; pre-first-finalization applies only deltas; reopened correction defers effects to re-finalization; cannot alter fulfilled We Owe quantity |
| `voidShowAndSellSale` | `showAndSellId`, `saleId`, `expectedRevision`, `expectedEventVersion`, `reason`, `idempotencyKey` | `ShowAndSellSaleResult` | Unit Admin; same correction timing/stock rules; fulfilled We Owe quantity cannot be voided as unfulfilled |

`ShowAndSellSaleLineInput`:

```text
productId: ID!
immediateQty: Int! (>= 0)
weOweQty: Int! (>= 0)
immediateQty + weOweQty > 0
```

The server derives product name/price/subtotal/total from the Unit Campaign catalog. It never trusts client prices or inventory quantities. Buyer name is required if any line has `weOweQty > 0`; contact fields are optional. `methodCode` must identify a built-in method or an active custom method belonging to the event's Unit; the resolver snapshots the server-side display name. An unchanged historical correction may retain a now-inactive original method.

`CorrectionLineInput` contains `lineItemId` for every existing line, `productId`, `immediateQty`, and `weOweQty`. Existing-line quantities are corrected against that stable identity and its linked obligations. Omitted existing lines are treated as voided and must pass fulfilled-quantity rules. New lines omit `lineItemId` and create supplemental obligations where needed. No line may reduce We Owe below already fulfilled quantity. Added products must come from the Unit Campaign's catalog/inventory and are added to the event's complete `productIds` set without an event-wide count cap.

### 7.2 We Owe queries and mutations

| Resolver | Input | Output | Caller and limits |
| --- | --- | --- | --- |
| `weOweObligation` | `weOweId: ID!` | `WeOweObligation` with fulfillment history | Unit Admin |
| `weOweObligations` | `unitCampaignId`, optional `status: OPEN/CLOSED`, `showAndSellId`, `productId`, `buyerName` exact/prefix as supported, `page` | `WeOweObligationConnection` | Unit Admin; no due-date/aging/assignee filters |
| `setWeOweReservation` | `weOweId`, `targetReservedQty`, `expectedVersion`, `idempotencyKey` | `WeOweObligation`, `InventoryPosition` | Unit Admin; target 0 through remaining quantity; only unassigned stock; no automatic priority/reservation |
| `fulfillWeOwe` | `weOweId`, `quantity`, `source: KERNEL_STOCK or EXTERNAL_COUNCIL`, `expectedVersion`, `idempotencyKey` | `WeOweObligation`, `WeOweFulfillment`, optional `InventoryPosition` | Unit Admin; partial allowed; `KERNEL_STOCK` quantity ≤ reservedQty, `EXTERNAL_COUNCIL` quantity ≤ uncoveredQty; release covered reservation explicitly before external fulfillment of that portion; closed requires zero remaining/reserved |

## 8. Finalization and reopening resolvers

| Resolver | Input | Output | Caller and limits |
| --- | --- | --- | --- |
| `updateShowAndSellRoundingDraft` | `showAndSellId`, `assignments[{profileId, cents}]`, `expectedVersion`, `idempotencyKey` | `FinalizationPreview` | Unit Admin before approval/reopened only; unique eligible confirmed participants, integer `cents >= 0`, and draft sum ≤ unassigned cents |
| `finalizeShowAndSell` | `showAndSellId`, `expectedVersion`, `returns[ProductReturnInput]` (every allocated product), `cash{manualAdjustmentCents, manualAdjustmentReason, actualCashCents, discrepancyExplanation}`, `roundingAssignments[{profileId,cents}]`, `idempotencyKey` | `FinalizationResult` | Unit Admin after event end; all return/cash/credit preconditions required; publishes one approved version and applies earlier-event-priority reductions; no event-wide product-count cap |
| `reopenShowAndSell` | `showAndSellId`, `expectedVersion`, `reason`, `idempotencyKey` | `ShowAndSellAdmin`, suspended `finalization`, updated Scout summaries | Unit Admin; suspends approved credit; leaves returned stock untouched; requires re-finalization to restore credit |

Finalization-specific rules:

- Event must be `ENDED` or `REOPENED`; not active/scheduled/cancelled/already finalized.
- Every allocated product has an actual return count and any required stock-only reconciliation reason.
- Cash adjustment reason is required when nonzero; discrepancy explanation required when actual differs from adjusted expected.
- Rounding assignments contain only unique eligible confirmed participants with integer `cents >= 0`; their final sum equals all unassigned cents exactly, and base + rounding allocations equal the whole pool.
- Re-finalization computes stock/We Owe deltas against the previous approved version and never replays releases/sales.
- Response includes later-event automatic reductions and all affected balances.

## 9. Reporting data resolvers

All report assembly, rendering, CSV/XLSX generation, printable-document generation, and ICS generation happens in the browser under `docs/BROWSER_REPORTING_ARCHITECTURE.md`. There are no report/export/print-file resolvers and no S3/pre-signed report URLs.

The following resolvers supply authorized, paginated domain facts. They do not aggregate a report or generate a file.

| Resolver | Input | Output | Caller and limits |
| --- | --- | --- | --- |
| `unitCampaignOrderLines` | `unitCampaignId`, optional `campaignId`, `profileId`, `productId`, `fulfilled: Boolean`, `dateRange`, `page` | `AdminOrderLineFactConnection` with full administrative Order Details fields and originating Unit Campaign | Unit Admin; raw individual-sale facts for browser seller/Council/Order Details reports; every page must be fetched for a complete report |
| `unitCampaignCreditAllocations` | `unitCampaignId`, optional `campaignId`, `profileId`, `status`, `showAndSellId`, `page` | `ScoutSalesAllocationConnection` with finalization/event/Scout identity, base/rounding/total cents, minutes, status, and version | Unit Admin; raw credit facts for browser seller/event reports; pending previews use `showAndSellFinalizationPreview` |
| `eventInventoryAllocations` | `unitCampaignId`, optional `productId`, `showAndSellId`, `status`, `page` | `EventInventoryAllocationConnection` with immutable event interval, allocated/sold/released/remaining quantities, and version | Unit Admin; raw allocation facts for browser inventory/Council reports |
| `scoutCampaignOrderLines` | `campaignId`, optional `unitCampaignId`, optional `productId`, `page` | `ParticipantOrderLineFactConnection` | Profile READ/Owner/WRITE may read all authorized Scout scopes; Unit Admin must supply an authorized scope and receives only that scope; no customer contact or aggregate summary is returned |
| `scoutCampaignCreditAllocations` | `campaignId`, optional `unitCampaignId`, optional `creditState`, `page` | `ParticipantSalesCreditConnection` | Same caller/scope rules as `scoutCampaignOrderLines`; own-Scout approved/suspended credit facts only, without finalizationId/actor fields; browser composes independent scopes without duplicating individual sales |
| `scoutCampaignPendingAllocations` | `campaignId`, optional `unitCampaignId`, `page` | `ParticipantPendingAllocationConnection` | Profile READ/Owner/WRITE for the Scout; Unit Admin must supply an authorized scope; computes only the caller-visible Scout's pending amount and eventVersion, never the admin pool/cash/returns/other-Scout preview |
| `showAndSellSignupCalendarData` | `showAndSellId`, `slotId`, `profileId` | `CalendarInviteData` with Unit/Unit Campaign/event/slot/signup IDs, arbitrary slot start/end, location/address, and description metadata | Unit Admin or Profile Owner/WRITE for that Scout; returns data only, not an ICS file; READ-only collaborators cannot invoke it |

Existing data resolvers supply the remaining report inputs: `inventoryPositions`, `scoutCustodyBalances`, `weOweObligations`, `showAndSell`, `showAndSellSales`, `showAndSellSignups`, `showAndSellFinalization` and its child collections, `unitCampaignRoster`, `unit`, `unitPaymentMethods`, and `unitCampaignCatalog`. The browser fetches every required page and generates the rendered report, CSV/XLSX, printable HTML, or ICS locally.

Every reporting-data item exposes its relevant domain version: InventoryBalance/allocation/custody/obligation versions, Order `fulfillmentVersion`, credit version where administrative, and `eventVersion` for participant/pending data. `showAndSellFinalizations` provides historical-version discovery and `previousFinalizationId` chaining. The browser uses these fields to reject version-matched/incomplete datasets rather than silently mixing current and historical states.

## 10. Existing individual Order resolver extensions

The existing `createOrder` and Order read models remain the individual-sale path. They require these contract extensions:

### 10.1 `CreateOrderInput` additions

| Field | Type | Rule |
| --- | --- | --- |
| `fulfillmentMode` | `NONE` or `CONSUME_SCOUT_CUSTODY`; default `NONE` | `CONSUME_SCOUT_CUSTODY` identifies a door-to-door sale. It consumes available With Scout stock and never blocks for insufficient custody. |
| `idempotencyKey` | String, 1–128 | Required when `fulfillmentMode = CONSUME_SCOUT_CUSTODY`; recommended for all new orders |

The server captures the Campaign's current joined `unitId`/`unitCampaignId` at Order creation and stores them immutably. An independent individual Order may have null campaign scope and does not consume custody.

### 10.2 Order output additions

| Field | Type | Meaning |
| --- | --- | --- |
| `unitId` / `unitCampaignId` | ID/null | Originating demand/inventory scope; does not change after later roster joins |
| `fulfillmentVersion` | Int | Optimistic concurrency version for fulfill/reverse operations |
| `LineItem.lineItemId` | ID | Stable line identity |
| `LineItem.fulfilledQuantity` | Int | 0 through ordered quantity |
| `fulfillments` | `[ParticipantOrderFulfillment!]!` for every caller | Source/quantity/reversal history without actorAccountId, inventoryMovementId, or other administrative audit fields; Unit Admin uses `orderFulfillments` for full audit |

`CONSUME_SCOUT_CUSTODY` behavior:

- Caller must have Profile Owner/WRITE; Unit Admin may also record for the Scout.
- For each line, consume `min(orderedQty, availableWithScoutQty)` and create corresponding `SCOUT_CUSTODY` fulfillment records.
- Any remainder stays unfulfilled and contributes to Council demand.
- Kernel stock is not decremented. With Scout cannot become negative. Insufficient custody is never a sale-blocking error.

## 11. Resolver coverage summary

| Workflow | Resolvers |
| --- | --- |
| Unit creation/access | `createUnit`, `updateUnit`, `createUnitInvite`, `revokeUnitInvite`, `redeemUnitInvite`, `revokeUnitAccessGrant` |
| Unit settings/payments | `updateUnit`, Unit payment queries/mutations and QR operations |
| Campaign/roster | `createUnitCampaign`, `updateUnitCampaign`, `joinUnitCampaign`, `removeUnitCampaignMembership`, roster queries |
| Inventory/custody | Receipt, adjustment, on-order, issue/return, inventory/custody queries |
| Events/slots/signups | Event create/update/cancel/assign, slot upsert/delete, signup/cancel/work, opportunity queries |
| Sales/We Owe | Sale create/correct/void, reservation/fulfillment, We Owe queries |
| Finalization | Preview, rounding draft, finalize, reopen, versioned finalization query |
| Reporting data | Raw Order/credit/allocation/inventory/event/We Owe queries and `showAndSellSignupCalendarData`; browser generates all reports, CSV/XLSX, print documents, and ICS |
| Individual sales | Existing Order API plus custody-fulfillment extensions |

Every confirmed user workflow has an API contract without exposing resolver implementation details or introducing per-event payment settings, rescheduling, offline queues, automatic notifications, or direct-to-Council mega-order handling.
