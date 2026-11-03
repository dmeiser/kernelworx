# Show & Sell and inventory transaction sequence diagrams

**Status:** Proposed implementation sequencing for the highest-risk workflows  
**Last updated:** 2026-10-30  
**Requirements:** [Show & Sell and inventory specification](SHOW_AND_SELL_INVENTORY_SPECIFICATION.md)  
**Data model:** [Show & Sell data model](SHOW_AND_SELL_DATA_MODEL.md)  
**API contract:** [Show & Sell GraphQL API](SHOW_AND_SELL_GRAPHQL_API.md)

## 1. Purpose

These diagrams specify actor order, authorization checks, authoritative reads, validations, version conditions, writes, retry behavior, and externally visible results for the workflows most likely to cause implementation rework.

They are design contracts, not resolver code. Names in diagrams refer to logical resolvers/models, not required class names.

## 2. Shared transaction contract

Every mutation follows this sequence unless its diagram explicitly says otherwise:

1. **Authenticate** the Cognito caller.
2. **Derive tenancy from the requested resource.** Client-supplied Unit/Campaign IDs are consistency checks, never authorization authorities.
3. **Authorize now** using the current Unit grant or SellerProfile access. Global application ADMIN and API-key access do not substitute.
4. **Read the idempotency marker** in the relevant aggregate table. Completed identical retries return the original result — same-key/different-fingerprint requests fail.
5. **Read authoritative records consistently**, including all versioned records whose state is validated.
6. **Validate current state and compute the complete write plan**, including the 90-action ceiling and finalization-feasibility preflight where applicable.
7. **Conditionally write in one DynamoDB transaction**: marker, business records, movements/snapshots, counters, and every checked version. Any failed condition writes nothing.
8. **Return only the authorized output projection.** Participant and Unit Admin projections differ by design.

A stale version returns `CONFLICT` — retry recomputes from a new consistent read rather than applying stale deltas. Retryable infrastructure contention returns `RESOURCE_BUSY`. No diagram uses a standalone idempotency/coordinator table or a multi-stage coordinator.

## 3. Signup: `signupScoutForShowAndSellSlot`

```mermaid
sequenceDiagram
    autonumber
    actor Caller as Morgan / Unit Admin
    participant API as signup resolver
    participant Auth as Unit/Profile auth
    participant DB as DynamoDB

    Caller->>API: showAndSellId, slotId, campaignId, profileId, idempotencyKey
    API->>Auth: Authenticate and derive Unit/Profile scope
    Auth-->>API: Unit Admin or Owner/WRITE for same Scout

    API->>DB: Read idempotency marker
    DB-->>API: No completed result
    API->>DB: Consistent read: membership + guard, event + slot, ScoutCommitmentGuard, all Scout commitments
    DB-->>API: Current records and versions

    API->>API: Validate ACTIVE membership, SCHEDULED state, campaign/profile match, no duplicate, capacity, no cross-campaign overlap, finalization feasibility

    alt Validation fails
        API-->>Caller: INVALID_INPUT / FORBIDDEN / NOT_FOUND / CONFLICT — no writes
    else Validation passes
        API->>DB: TransactWrite: insert marker — condition membership ACTIVE + version — condition commitmentGuard version — condition slot version/count — condition event version — put signup + commitment — increment slot count, guard, event version
        alt Any condition fails
            DB-->>API: Transaction canceled — nothing committed
            API-->>Caller: CONFLICT — retry from fresh reads if appropriate
        else Commit succeeds
            DB-->>API: New signup version and original result reference
            API-->>Caller: ParticipantSignup — no actor/account IDs
        end
    end

    Note over Caller,DB: Membership removal after the read increments membership.version, so the new signup cannot commit. Calendar data is fetched separately — no notification or ICS is generated here.
```

**Required proof cases:** successful Owner/WRITE and Unit Admin signup — READ denial — capacity race — cross-campaign conflict — duplicate retry — membership-removal race — finalization-budget preflight.

## 4. Inventory assignment: `assignShowAndSellInventory`

```mermaid
sequenceDiagram
    autonumber
    actor Kernel as Unit Admin
    participant API as allocation resolver
    participant DB as Inventory + event tables

    Kernel->>API: showAndSellId, expectedVersion, target quantities (0 allowed), idempotencyKey
    API->>API: Authenticate, derive Unit from event, verify current Unit Admin
    API->>DB: Read marker — consistent read of event, product balances, and every open allocation for each requested product
    DB-->>API: Current records, allocations, intervals, versions

    API->>API: Validate event state, immutable intervals, catalog membership, and write/finalization budgets

    alt Event is REOPENED
        API->>DB: TransactWrite: insert marker — condition event version — write only draft allocation inputs, new productIds, and event version
        DB-->>API: Draft allocation state committed without balance/allocation movements
        API-->>Kernel: Updated pending allocation preview — live targets apply at re-finalization
    else Concurrent allocations exceed sellable stock at any instant
        API-->>Kernel: CONFLICT / concurrent over-assignment — no writes
    else Targets valid (including sequential over-assignment)
        API->>API: Compute target allocation state and SEQUENTIAL_OVER_ASSIGNMENT warnings
        API->>DB: TransactWrite: insert marker — condition event and balance versions — upsert allocations — add EVENT_ASSIGN/EVENT_MANUAL_REDUCE movements — update productIds + event version — update balance versions
        alt Version race
            DB-->>API: Nothing committed
            API-->>Kernel: CONFLICT — re-read and retry
        else Commit succeeds
            DB-->>API: New allocation/balance versions
            API-->>Kernel: allocations, derived inventoryPositions, warnings
        end
    end

    Note over Kernel,DB: Assignment changes commitments, not physical stock. Zero releases remaining allocation — omitted products remain unchanged. Automatic earlier-event-priority reduction occurs only during finalization of an earlier event.
```

**Required proof cases:** overlapping 3+3 blocked on four units — sequential 3+3 warning — target zero — omitted product unchanged — concurrent writers cannot both succeed — a 16th distinct catalog product is allowed in a separate assignment and included in finalization.

## 5. Sale entry: `createShowAndSellSale`

```mermaid
sequenceDiagram
    autonumber
    actor Kernel as Unit Admin
    participant API as sale resolver
    participant DB as Event + inventory tables

    Kernel->>API: showAndSellId, expectedEventVersion, saleAt, buyer, transaction-safe line batch, paymentMethod, idempotencyKey
    API->>API: Authenticate, derive Unit from event, verify Unit Admin
    API->>DB: Read marker — consistent read of event, catalog/products, allocations/balances, active Unit payment method
    DB-->>API: Current records and versions

    API->>API: Validate ACTIVE, ENDED, or draft-only REOPENED state, saleAt within event, payment/Other, catalog membership, per-sale line limit, prices/totals, write/finalization budgets

    alt Event is REOPENED
        API->>DB: TransactWrite: insert marker — condition event version and custom payment-method version including isActive — put draft sale/revision, any new productIds, and zero-baseline allocation inputs — increment event version — apply no allocation, stock, or obligation effects
        DB-->>API: Draft sale committed — effects deferred to re-finalization
        API-->>Kernel: ShowAndSellSaleResult with deferred effects
    else Any immediate quantity unavailable and We Owe disabled
        API-->>Kernel: CONFLICT — no sale or stock change
    else Immediate and/or We Owe lines valid
        API->>API: Compute immediate consumption, We Owe obligations, snapshots, and movements
        API->>DB: TransactWrite: insert marker — condition event, balance, allocation, and custom payment-method versions including isActive — put sale — increase soldQty/decrease remaining and physical for immediate lines — put movements and We Owe obligations — update productIds + event version
        alt Any version or stock condition fails
            DB-->>API: Nothing committed
            API-->>Kernel: CONFLICT — retry from fresh state
        else Commit succeeds
            DB-->>API: Sale ID and updated balances
            API-->>Kernel: ShowAndSellSaleResult
        end
    end

    Kernel->>API: Retry same idempotencyKey/content
    API->>DB: Read completed marker
    DB-->>API: Original result reference
    API-->>Kernel: Original sale result — no second sale or stock movement

    Note over Kernel,DB: REOPENED sale entry and sale corrections use draft revisions only — stock and obligations are adjusted at re-finalization.
```

**Required proof cases:** immediate sale — mixed immediate/We Owe — unavailable with We Owe off — Other details — inactive/wrong-Unit method — stale balance/event versions — duplicate retry — scheduled/finalized event denial.

## 6. First finalization: `finalizeShowAndSell`

```mermaid
sequenceDiagram
    autonumber
    actor Kernel as Unit Admin
    participant API as finalization resolver
    participant DB as Event + inventory tables

    Kernel->>API: showAndSellId, expectedVersion, returns, cash, roundingAssignments, idempotencyKey
    API->>API: Authenticate, derive Unit, verify Unit Admin
    API->>DB: Read marker — consistent read of event, slots/signups, sales, obligations, productIds allocations/balances, later event metadata/allocations, prior finalization if any
    DB-->>API: Complete source set and versions

    API->>API: Validate ENDED, event version, eligible work, actual returns/reasons, cash reasons/explanation, exact cents, obligations, ≤90-action write plan

    API->>API: Compute whole pool, base shares, expected returns, first adjustment = actual - expected, allocation releases, and earlier-priority later reductions

    alt Any precondition or version fails
        API-->>Kernel: INVALID_INPUT / CONFLICT / OPERATION_TOO_LARGE — no writes
    else Complete plan is valid
        API->>DB: TransactWrite: insert marker — condition every source version — put finalization + sale/work/return snapshots — put credits and Scout totals — release allocations — apply return movements and later reductions — set approvedFinalizationId and latestFinalizationId + status FINALIZED + increment event version and each affected later event version
        alt Any condition fails
            DB-->>API: Nothing committed
            API-->>Kernel: CONFLICT — recompute entire finalization
        else Commit succeeds
            DB-->>API: Approved finalization and complete new balances
            API-->>Kernel: FinalizationResult + later-allocation warnings
        end
    end

    Note over Kernel,DB: Only this commit makes Scout credit approved. Before commit, allocations are pending previews. Open We Owe may remain open and still counts in the finalized sales pool.
```

**Required proof cases:** $60/360-minute split — Kernel-assigned cent — expected/actual return and cash mismatch explanations — automatic Afternoon reduction — stale source mutation during finalization — no partial credit on failure.

## 7. Reopen and re-finalization

### 7.1 Reopen: `reopenShowAndSell`

```mermaid
sequenceDiagram
    autonumber
    actor Kernel as Unit Admin
    participant API as reopen resolver
    participant DB as Event + credit tables

    Kernel->>API: showAndSellId, expectedVersion, reason, idempotencyKey
    API->>API: Verify Unit Admin and FINALIZED state
    API->>DB: Read marker — consistent read of event, approved finalization, credits/totals
    DB-->>API: Current approved version and versions

    API->>DB: TransactWrite: insert marker — condition event/finalization versions — mark finalization and credits SUSPENDED with actor/time/reason — subtract Scout totals — clear approvedFinalizationId — set event REOPENED and increment event version
    alt Condition fails
        DB-->>API: Nothing committed
        API-->>Kernel: CONFLICT
    else Commit succeeds
        DB-->>API: Reopened event — suspended historical version
        API-->>Kernel: ShowAndSellAdmin + suspended finalization + updated Scout summaries
    end

    Note over Kernel,DB: No returned stock, allocation, sale, or We Owe quantity is reclaimed or changed by reopening.
```

### 7.2 Draft corrections while reopened

```mermaid
sequenceDiagram
    autonumber
    actor Kernel as Unit Admin
    participant API as correction resolver
    participant DB as Event + sale tables

    Kernel->>API: correctShowAndSellSale or voidShowAndSellSale or confirmShowAndSellWork or updateShowAndSellRoundingDraft with expected versions
    API->>API: Verify Unit Admin and REOPENED state
    API->>DB: Read source + marker — validate the contracted operation
    alt Sale correction or void
        API->>DB: TransactWrite: preserve prior revision — update draft sale and event version — add new productIds and zero-baseline allocation inputs if needed
        DB-->>API: Sale draft committed without stock effects
        API-->>Kernel: ShowAndSellSaleResult
    else Work correction
        API->>DB: TransactWrite: update actualMinutes and event version
        DB-->>API: Work draft committed
        API-->>Kernel: Updated signups + FinalizationPreview
    else Rounding correction
        API->>DB: TransactWrite: update roundingDraftByProfileId and event version
        DB-->>API: Rounding draft committed
        API-->>Kernel: FinalizationPreview
    end

    Note over Kernel,DB: We Owe targets and stock deltas wait for re-finalization. Cash and actual returns are finalizeShowAndSell inputs, not separate persisted draft resolvers.
```

### 7.3 Re-finalization

```mermaid
sequenceDiagram
    autonumber
    actor Kernel as Unit Admin
    participant API as re-finalization resolver
    participant DB as Event + inventory tables

    Kernel->>API: Re-finalize with expected versions and confirmed actuals
    API->>DB: Read marker, current drafts, prior approved snapshots, obligations, allocations, balances, later events
    DB-->>API: Current and previous approved baselines

    API->>API: Recompute pool/credits/cash/returns and target We Owe quantities
    API->>API: Per product: adjustment = (newActual - newAllocated) - (previousActual - previousAllocated)

    alt Adjustment cannot be satisfied by current stock or correction overtakes fulfilled We Owe
        API-->>Kernel: CONFLICT — reconcile explicitly — no writes
    else Delta plan valid and ≤90 actions
        API->>DB: TransactWrite: insert marker — condition all source versions — supersede old version — put new snapshots/credits/totals — write target allocations and complete We Owe creations/target fulfilled/cancelled/remaining/reserved/uncovered/status values and excess-reservation releases — apply only net stock delta and later reductions — set status FINALIZED + new approvedFinalizationId and latestFinalizationId + increment event version and each affected later event version
        alt Any condition fails
            DB-->>API: Nothing committed
            API-->>Kernel: CONFLICT — recompute
        else Commit succeeds
            DB-->>API: New approved version — old history preserved
            API-->>Kernel: New FinalizationResult
        end
    end

    Note over Kernel,DB: Unchanged inputs produce zero stock adjustment. Prior releases and immediate-sale effects are never replayed.
```

**Required proof cases:** credit suspended on reopen — no stock reclaimed — unchanged re-finalization has zero adjustment — added sale applies only delta — voided sale reverses only delta — We Owe cancellation releases only excess reservation — prior snapshots remain exact.

## 8. Individual and Scout-custody fulfillment

### 8.1 `fulfillIndividualOrderLine` and reversal

```mermaid
sequenceDiagram
    autonumber
    actor Kernel as Unit Admin
    participant API as fulfillment resolver
    participant DB as Orders + inventory tables

    Kernel->>API: orderId, lineItemId, quantity, source, expectedFulfillmentVersion, idempotencyKey
    API->>API: Verify Unit Admin for the Order's immutable originating Unit
    API->>DB: Read marker — consistent read of Order/line and relevant balance or custody
    DB-->>API: Current unfulfilled quantity and versions

    API->>API: Validate quantity ≤ unfulfilled and source: KERNEL_STOCK uses unassigned stock — EXTERNAL_COUNCIL uses no stock

    alt Invalid quantity/source/version
        API-->>Kernel: INVALID_INPUT / CONFLICT — no writes
    else Valid
        API->>DB: TransactWrite: insert marker — condition Order.fulfillmentVersion and stock/custody versions — increment line fulfilledQuantity + Order version — put OrderFulfillment — apply only source stock effect and movement
        alt Condition fails
            DB-->>API: Nothing committed
            API-->>Kernel: CONFLICT — retry from fresh Order version
        else Commit succeeds
            DB-->>API: Fulfillment and current Order/balance
            API-->>Kernel: order, fulfillment, optional inventoryPosition
        end
    end

    Kernel->>API: reverse with orderId, fulfillmentId, expectedFulfillmentVersion, idempotencyKey
    API->>DB: TransactWrite: insert marker — condition Order version and original source balance/custody version — put unique REVERSAL#originalFulfillmentId — restore original demand and only original stock source with version updates
    DB-->>API: Reversal committed once
    API-->>Kernel: order, reversal, optional inventoryPosition
```

### 8.2 `createOrder(CONSUME_SCOUT_CUSTODY)`

```mermaid
sequenceDiagram
    autonumber
    actor Caller as Morgan / Unit Admin
    participant API as existing Order resolver
    participant DB as Orders + inventory tables

    Caller->>API: Order lines, fulfillmentMode=CONSUME_SCOUT_CUSTODY, idempotencyKey
    API->>API: Verify Profile Owner/WRITE or Unit Admin — capture current joined Unit scope
    API->>DB: Read marker and Scout custody for originating Unit Campaign
    DB-->>API: Available custody and versions

    API->>API: For each line: consume = min(orderedQty, availableWithScoutQty) — remainder stays unfulfilled

    API->>DB: TransactWrite: insert marker — create Order with immutable unitId/unitCampaignId and fulfillmentVersion=0 — condition custody versions — decrement only consumed custody — put SCOUT_CUSTODY fulfillments and movements
    alt Any custody version fails
        DB-->>API: Nothing committed — no Order created
        API-->>Caller: CONFLICT — retry
    else Commit succeeds
        DB-->>API: Order with fulfilled and unfulfilled quantities
        API-->>Caller: Order + ParticipantOrderFulfillment facts
    end

    Note over Caller,DB: Kernel stock is never decremented. Insufficient custody never blocks the individual sale.
```

**Required proof cases:** partial Kernel fulfillment — external fulfillment with no inventory row — stale external fulfillment race — one reversal only — door-to-door full/partial custody — origin scope retained after later roster join — idempotent retry.

## 9. Write-set accounting

Engineering must compute action counts from the actual write plan before every mutation — validation maxima are not independently composable.

| Operation | Writes included in the count |
| --- | --- |
| Signup | Idempotency marker, signup, commitment projection, slot counter, commitment guard, event version |
| Allocation | Marker, each allocation, each movement, each balance version, event/productIds/version |
| Sale | Marker, sale, per-product allocation/balance/movements, We Owe obligations, event/productIds/version |
| Finalization | Marker, event/status/version, finalization metadata, sale/work/return snapshots, credits, Scout totals, allocation releases, balances, movements, later reductions and affected later-event versions |
| Reopen | Marker, event, suspended finalization, suspended credits, Scout-total decrements |
| Re-finalization | Marker, event/version/status, old-version supersession, new finalization/snapshots/credits/totals, target allocations, complete We Owe creations/targets/releases, only delta movements, and affected later-event versions |
| Individual fulfillment | Marker, Order/version, fulfillment, source balance or custody when applicable, movement when applicable, deterministic reversal when applicable |

Example first-finalization action estimate:

```text
3 baseline writes (marker + event + finalization)
+ S sale snapshots
+ W work snapshots
+ 2C (credit + Scout-total projection per participant)
+ 4P (return snapshot + allocation + balance + movement per touched product)
+ 2L (allocation + movement per later-event reduction)
+ E (one metadata/version write per affected later event)
```

`L` is the number of later-event allocation reductions and `E` is the number of distinct later events affected. `P` includes every touched product, including products whose balances change only because of later-event reductions. The implementation must include every additional conditional check/write in its real count. If the complete operation exceeds 90, reject before writing and allow the Kernel to reduce participants/products/sales/later-event commitments. Source mutations must preflight finalization feasibility so they cannot knowingly create an event that is impossible to finalize within this budget.

## 10. Engineering validation requirements

Before expanding to the full feature, implement these diagrams as a vertical slice and prove:

1. Every read used for authorization or invariants is authoritative and every validated version is included in the transaction condition set.
2. No failure after validation can expose partial sales, stock, obligations, cash, credit, or finalization results.
3. Every retry either returns the original result or recomputes safely from new versions.
4. All six areas have concurrency tests, not only happy-path browser tests.
5. Write-plan tests cover 1-, 2-, 5-, and 15-line sales, the largest computed transaction-safe sale, oversized orders split into independently atomic sales, and the largest supported finalization/reopen combinations.
6. Browser reports consume committed data only and generate all report/CSV/XLSX/print/ICS output locally.

These diagrams are the reference for implementation review. Deviating from their authorization, version, delta, or visibility rules requires updating this document and the corresponding acceptance descriptions rather than silently choosing different behavior.
