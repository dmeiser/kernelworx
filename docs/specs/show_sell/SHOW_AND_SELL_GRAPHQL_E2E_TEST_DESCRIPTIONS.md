# Show & Sell GraphQL endpoint E2E test descriptions

**Status:** Pre-implementation endpoint acceptance descriptions; no test code  
**Last updated:** 2026-10-30  
**API contract:** [Show & Sell GraphQL API](SHOW_AND_SELL_GRAPHQL_API.md)  
**Business workflows:** [Show & Sell smoke test plan](SHOW_AND_SELL_SMOKE_TEST_PLAN.md)  
**Reporting architecture:** [Browser-only reporting and document generation](BROWSER_REPORTING_ARCHITECTURE.md)

## 1. Purpose and execution model

These are live GraphQL end-to-end test descriptions for every resolver in the API contract. They focus on endpoint behavior, authorization, validation, limits, and output shape. The browser-oriented business workflows remain in the smoke test plan and are not repeated here.

- Run against real AppSync/Cognito/DynamoDB in an ephemeral environment or isolated dev lanes; do not mock authorization or persistence.
- Each scenario acquires an exclusive lane and creates its own `DATA_ID` resources as defined in the smoke plan.
- Use direct GraphQL calls for both allowed and denied paths. A hidden UI button is not an authorization assertion.
- Assert structured errors in `extensions.errorCode`, absence of unintended writes, and output contents—not only HTTP 200.
- Revoke/remove roles only after the fixture's positive case, and verify that previously issued credentials/tokens cannot restore access.
- Every scenario cleans its own data. Shared global cleanup is forbidden while lanes are active.

### 1.1 Personas

| Persona | Access in the primary fixture |
| --- | --- |
| **Alex Kernel LNN** | Creator and Unit Admin of `Smoke Pack 3149 <DATA_ID>`; not a global application ADMIN |
| **Casey Kernel LNN** | Becomes a second equal Unit Admin by redeeming Alex's invite |
| **Morgan Parent LNN** | Owns Avery, Blake, Charlie, Devon, and Emery; no primary Unit Admin grant |
| **Riley Outsider LNN** | Has READ-only SellerProfile access to Avery but no Pack 3149 Unit Admin grant; owns a separate Troop 7150 for cross-Unit tests |
| **Taylor Collaborator LNN** | API-only fifth lane Account with non-owner WRITE access to Blake and no Unit Admin grant; used to prove Profile WRITE does not require ownership |
| **Global Owner** | Existing global application ADMIN with no grant to Riley's Troop 7150; used only to prove global ADMIN does not imply Unit access |

Avery, Blake, Charlie, and Devon join the primary Unit Campaign; Emery remains unjoined. Products and prices are those in the smoke plan. Buyer examples are Nora Cash, Quinn WeOwe, and Sam Split.

### 1.2 Required fixture capabilities

These are acceptance criteria if the current flow cannot create the state:

- `API-FIX-01` Create ACTIVE, ENDED, REOPENED, FINALIZED, CANCELLED, past, and future event fixtures without bypassing the rule under test.
- `API-FIX-02` Grant Riley READ-only access to Avery and Taylor non-owner WRITE access to Blake while keeping both outside the primary Unit; Morgan retains Owner access without Unit Admin. Taylor's API-only lane Account must be provisioned/authenticated and its WRITE grant must be revocable for access-removal tests.
- `API-FIX-03` Read and advance versions/revisions, create expired invites, and create stale-version fixtures without waiting or editing expected API inputs.
- `API-FIX-04` Capture GraphQL errors/extensions and inspect participant-safe versus Unit Admin output projections.
- `API-FIX-05` Arrange order origins in one Unit Campaign, move the Campaign's latest membership to another, and verify old Orders retain their original scope.
- `API-FIX-06` Provision isolated QR uploads and capture browser-generated CSV/XLSX/print/ICS artifacts with run-scoped cleanup; no server report/download artifacts are created.

A missing required fixture makes the scenario blocked; it does not justify skipping its security assertion.

## 2. Shared scenarios applied to multiple endpoints

These scenarios are referenced by the endpoint descriptions rather than repeated verbatim.

### 2.1 Unit Admin authorization suite

Apply to every resolver documented as **Unit Admin-only**:

- `AUTH-U-01` When Alex is a Unit Admin for the resource's Unit, he can invoke the operation with valid input and receives the documented output.
- `AUTH-U-02` When Alex's grant is removed, he can no longer invoke that operation. A visible resource/action returns `FORBIDDEN`; a cross-tenant ID returns `NOT_FOUND`. No data changes.
- `AUTH-U-03` Riley cannot invoke the operation against Pack 3149, and Global Owner cannot invoke it against Troop 7150 merely because of global ADMIN.
- `AUTH-U-04` An unauthenticated or API-key caller receives `UNAUTHORIZED`/the existing unauthenticated behavior; no field becomes public.
- `AUTH-U-05` IDs from another Unit return `NOT_FOUND` and do not reveal inventory, roster, buyer, payment, cash, or audit details.

### 2.2 Profile participant suite

Apply to participant read/mutation resolvers:

- `AUTH-P-01` Morgan, as Profile Owner, may perform the documented Owner/WRITE action for his Scout.
- `AUTH-P-02` Riley, with READ-only access, may perform documented reads but receives `FORBIDDEN` for every signup/calendar/individual-sale mutation, with no state change.
- `AUTH-P-03` Riley cannot read or mutate Blake, Emery, or another Account's Scout by substituting `profileId`/`campaignId`.
- `AUTH-P-04` Participant outputs never expose `actorAccountId`, `confirmedByAccountId`, `signedUpByAccountId`, `inventoryMovementId`, `finalizationId`, customer contact, buyer details, cash, other Scouts' allocations, or other administrative audit/finalization fields.
- `AUTH-P-05` Taylor, as a non-owner WRITE collaborator for Blake, can successfully join Blake's Campaign, manage Blake's signups, download Blake's ICS, read participant summaries, and create custody-consuming individual Orders. After Taylor's WRITE grant is revoked, those operations are denied immediately while appropriate READ-only behavior remains.

### 2.3 Cognito-only denial suite

Apply to authenticated-Account bootstrap endpoints and every participant endpoint, including `myUnits`, `unitCampaignJoinInfo`, `createUnit`, `redeemUnitInvite`, opportunity/custody/commitment/summary queries, and participant mutations:

- `AUTH-C-01` An anonymous or API-key caller receives `UNAUTHORIZED`/the existing unauthenticated behavior and no Unit, campaign, Scout, schedule, or report data.
- `AUTH-C-02` The same anonymous/API-key request performs no writes, including Unit creation, invite redemption, campaign join, signup, or individual sale. Public buyer/API-key access remains limited to the pre-existing public-order surface.

### 2.4 Version and idempotency suite

Apply to mutations with versions/idempotency:

- `VER-01` A stale `expectedVersion`, `expectedRevision`, `expectedEventVersion`, `expectedFulfillmentVersion`, or named guard version returns `CONFLICT` and writes nothing.
- `IDEM-01` Retrying the identical request with the same key returns the original result and creates no second sale, grant, stock movement, obligation, fulfillment, or approved version.
- `IDEM-02` Reusing the key with different normalized content returns `INVALID_INPUT`; `createUnit` and invite redemption retries work even after the Unit was created or invite consumed.
- `PAGE-01` Connection endpoints honor default page size, maximum 100, valid cursors, and stable `pageInfo`; a cursor cannot be used to enter another tenant's result set.

## 3. Unit and Unit Campaign endpoints

### 3.1 Unit queries

**`myUnits`**

- `UNIT-Q-01-01` When Alex belongs to two Units, `myUnits` returns exactly those Units, never Riley's Troop 7150 or Morgan's Units.
- `UNIT-Q-01-02` After Casey is removed from Pack 3149, Casey's next page no longer contains it, while Alex retains it.
- `UNIT-Q-01-03` `PAGE-01` applies.

**`unit`**

- `UNIT-Q-02-01` Alex receives Unit metadata, timezone, split default, Council preference, and current adminCount for Pack 3149.
- `UNIT-Q-02-02` `AUTH-U-02` through `AUTH-U-05` apply; Morgan receives no adminCount or Unit settings.

**`unitAdmins`**

- `UNIT-Q-03-01` Alex and Casey see all current grants with only required Account administration fields.
- `UNIT-Q-03-02` After Casey is revoked, subsequent pages exclude Casey immediately.
- `UNIT-Q-03-03` `AUTH-U` suite and `PAGE-01` apply.

**`unitInvites`**

- `UNIT-Q-04-01` Alex sees active unused invites and their codes/expiry, but redeemed, revoked, and expired invites do not appear.
- `UNIT-Q-04-02` `AUTH-U` suite and `PAGE-01` apply.

**`unitPaymentMethods`**

- `UNIT-Q-05-01` Alex receives built-in Cash, Check, and Other plus the Unit's named methods and QR references.
- `UNIT-Q-05-02` `includeInactive = false` excludes deactivated Venmo; `true` includes it without changing historical sale snapshots.
- `UNIT-Q-05-03` Morgan and Riley cannot read QR signing information or Other payment details (`AUTH-U`).

**`unitCampaignJoinInfo`**

- `UNIT-Q-06-01` Any authenticated persona with the active join code receives only Unit display name, campaign name/year, catalog name, and active status.
- `UNIT-Q-06-02` Unknown, inactive, or malformed codes return `NOT_FOUND` without revealing inventory, roster, Unit grants, or whether a different Unit exists.

**`unitCampaign`**

- `UNIT-Q-07-01` Alex receives the administrative Unit Campaign, including joinCode and current version.
- `UNIT-Q-07-02` Morgan and Riley cannot use this administrative query as an alternative to the limited join preview (`AUTH-U`).

**`unitCampaigns`**

- `UNIT-Q-08-01` Alex receives only campaigns belonging to the requested Unit and can filter active/deactivated campaigns.
- `UNIT-Q-08-02` `AUTH-U` suite and `PAGE-01` apply.

**`unitCampaignRoster`**

- `UNIT-Q-09-01` Alex sees joined and removed membership history with Scout Campaign identity and status.
- `UNIT-Q-09-02` `AUTH-U` suite and `PAGE-01` apply.

### 3.2 Unit mutations

**`createUnit`**

- `UNIT-M-01-01` When Morgan creates a Unit with valid metadata, Morgan becomes its initial Unit Admin and the result has a stable `unitId` and adminCount 1.
- `UNIT-M-01-02` An exact type/number/city/state duplicate with `duplicateConfirmed = false` requires confirmation; setting true creates a distinct Unit without merging.
- `UNIT-M-01-03` Identical numbers in different cities do not require a number-only collision workaround.
- `UNIT-M-01-04` `IDEM-01` and `IDEM-02` apply using the bootstrap scope.

**`updateUnit`**

- `UNIT-M-02-01` Alex can change display metadata, timezone, split default, or Council preference while `unitId` and adminCount remain unchanged.
- `UNIT-M-02-02` After Alex is removed, the same update is denied; `VER-01`, `IDEM`, and cross-Unit rules apply.

**`createUnitInvite`**

- `UNIT-M-03-01` Alex and Casey can each create a 16-character invite expiring in 14 days, and actor/unit are recorded.
- `UNIT-M-03-02` The 21st active unused invite is rejected without deleting or extending an existing invite.
- `UNIT-M-03-03` `AUTH-U` and `IDEM` suites apply.

**`revokeUnitInvite`**

- `UNIT-M-04-01` Alex can revoke an unused invite, after which redemption returns `NOT_FOUND`.
- `UNIT-M-04-02` Revoking an already redeemed/deleted invite is idempotent only through a matching retry; a different request receives `NOT_FOUND` and creates no side effect.
- `UNIT-M-04-03` `AUTH-U` applies.

**`redeemUnitInvite`**

- `UNIT-M-05-01` Casey can redeem a valid code, receives full Unit Admin access, and the code becomes single-use.
- `UNIT-M-05-02` Morgan cannot reuse Casey's consumed code, and an expired/revoked code returns `NOT_FOUND`.
- `UNIT-M-05-03` Redeeming a second valid invite while already granted returns the existing grant and does not increment adminCount.
- `UNIT-M-05-04` Ten failed attempts in one hour trigger `RATE_LIMIT_EXCEEDED`; a valid retry with the original idempotency key still returns the original grant.

**`revokeUnitAccessGrant`**

- `UNIT-M-06-01` Alex can revoke Casey when another grant remains; Casey's subsequent privileged calls fail immediately.
- `UNIT-M-06-02` Revoking the final grant returns `CONFLICT` even when attempted through the direct API by the sole admin.
- `UNIT-M-06-03` `VER-01`, `IDEM`, `AUTH-U`, and concurrent add/revoke safety apply.

### 3.3 Unit payment-method mutations

**`createUnitPaymentMethod`**

- `PAY-M-01-01` Alex can create Venmo and Casey can create Zelle; both are visible to every Show & Sell in that Unit.
- `PAY-M-01-02` Cash, Check, Other, case variants, and duplicate normalized names are rejected without creating a method.
- `PAY-M-01-03` The 51st active custom method is rejected; deactivating one does not permit more than 50 active methods by accident.

**`updateUnitPaymentMethod`**

- `PAY-M-02-01` Alex can rename Venmo using `unitId + paymentMethodId`; subsequent displays use the new name while historical sales retain the old snapshot.
- `PAY-M-02-02` `VER-01`, reserved-name validation, `AUTH-U`, and consistent Unit-collection lookup apply.

**`deactivateUnitPaymentMethod`**

- `PAY-M-03-01` Deactivation makes a method unavailable for new sales but preserves it in historical sales and `includeInactive = true` results.
- `PAY-M-03-02` `AUTH-U`, `VER-01`, and `IDEM` apply.

**`requestUnitPaymentMethodQrUpload`**

- `PAY-M-04-01` Alex receives an S3 POST scoped to the requested Unit method, not an arbitrary Account/path.
- `PAY-M-04-02` Riley cannot request an upload URL, and a URL for Pack 3149 cannot be used to authorize a Troop 7150 method.

**`confirmUnitPaymentMethodQrUpload`**

- `PAY-M-05-01` After a valid upload, confirmation attaches the QR to the Unit method and subsequent payment-help output references it.
- `PAY-M-05-02` Wrong Unit ownership, unscoped/missing keys, invalid content type/size, and stale versions are rejected without changing the method.

**`deleteUnitPaymentMethodQrCode`**

- `PAY-M-06-01` Deleting a QR removes its object/reference while leaving the payment method and historical sales intact.
- `PAY-M-06-02` `AUTH-U`, `VER-01`, and `IDEM` apply.

### 3.4 Unit Campaign mutations

**`createUnitCampaign`**

- `CAMP-M-01-01` Alex can create a campaign with a valid catalog and receives its Unit relationship and unique joinCode.
- `CAMP-M-01-02` Unknown/deleted/unusable catalog IDs fail without creating a campaign or join-code pointer.

**`updateUnitCampaign`**

- `CAMP-M-02-01` Alex can rename/deactivate a campaign without changing inventory, With Scout, We Owe, on-order balances, or catalogId.
- `CAMP-M-02-02` Any attempt to supply/change catalogId is rejected; a different catalog requires a new independent Unit Campaign.
- `CAMP-M-02-03` `AUTH-U`, `VER-01`, and `IDEM` apply.

**`joinUnitCampaign`**

- `CAMP-M-03-01` Morgan can join Avery's Campaign with the code and immediately gains signup eligibility without separate approval.
- `CAMP-M-03-02` Riley with READ-only access cannot join Avery's Campaign; Emery cannot be joined by substituting another Scout's campaignId.
- `CAMP-M-03-03` A second active membership for one Scout Campaign is rejected, while a removed Campaign may join another Unit Campaign without moving historical Orders/credit.
- `CAMP-M-03-04` Unknown/inactive codes return `NOT_FOUND`; retries use the joinCode idempotency scope.

**`removeUnitCampaignMembership`**

- `CAMP-M-04-01` Alex can remove Blake, blocking new signups while preserving existing signups, work, credit, Orders, and history.
- `CAMP-M-04-02` A removal racing a new signup invalidates that signup's membership-version condition; no post-removal signup is committed.
- `CAMP-M-04-03` `AUTH-U`, `VER-01`, and `IDEM` apply to both membership and guard versions.

## 4. Inventory and Scout-custody endpoints

### 4.1 Inventory queries

**`inventoryPositions`**

- `INV-Q-01-01` Alex receives physical, reserved, sellable, assigned, unassigned, overage, With Scout, and total-owned values that reconcile to detail records.
- `INV-Q-01-02` Filtering more than 15 productIds returns `INVALID_INPUT`; `AUTH-U` and `PAGE-01` apply.

**`inventoryMovements`**

- `INV-Q-02-01` Alex can filter by product, movement type, event, Scout, and a maximum 366-day range; results include actor/reason/source links.
- `INV-Q-02-02` An excessive range returns `INVALID_INPUT`; `AUTH-U` and `PAGE-01` apply.

**`orderFulfillments`**

- `INV-Q-03-01` Alex sees full administrative source/actor/movement/reversal history only for Orders originating in his Unit.
- `INV-Q-03-02` `AUTH-U` and `PAGE-01` apply; participant Orders never use this admin output for their default fulfillment field.

**`scoutCustodyBalances`**

- `INV-Q-04-01` Alex sees aggregate and per-Scout With Scout balances and can filter by Scout/product.
- `INV-Q-04-02` `AUTH-U` and `PAGE-01` apply.

**`myScoutCustody`**

- `INV-Q-05-01` Morgan and Riley can read Avery's balances, but only their own Scout's data; Riley cannot read Blake's.
- `INV-Q-05-02` Unit Admins receive only balances in their authorized Unit Campaign, and `AUTH-P-04` applies to participant output.

**`myScoutCommitments`**

- `INV-Q-06-01` Morgan and Riley can read Avery's commitments across Unit Campaigns without actor/account identifiers.
- `INV-Q-06-02` Alex must supply his authorized unitId and receives only that Unit's commitments; he cannot use the endpoint to discover another Unit's schedule.
- `INV-Q-06-03` `AUTH-P` and `PAGE-01` apply.

### 4.2 Inventory mutations

**`recordInventoryReceipt`**

- `INV-M-01-01` When Alex records four Caramel units, physical, sellable, and unassigned increase by four without an Order, payment, fulfillment, or credit record.
- `INV-M-01-02` Zero, negative, fractional, or excessive quantities return `INVALID_INPUT`; `AUTH-U` and `IDEM` apply.

**`adjustInventory`**

- `INV-M-02-01` Alex can apply a reasoned positive/negative adjustment without creating financial or sales side effects.
- `INV-M-02-02` Any result where physical is negative or less than sold-in-possession is rejected atomically.
- `INV-M-02-03` Missing reason, `AUTH-U`, and `IDEM` rules apply.

**`adjustCouncilOnOrder`**

- `INV-M-03-01` Alex can increase/decrease on-order independently, and neither Council Needs calculation subtracts it automatically.
- `INV-M-03-02` A negative resulting on-order balance is rejected; `AUTH-U` and `IDEM` apply.

**`issueStockToScout`**

- `INV-M-04-01` Issuing three units to Avery decreases available Kernel stock and increases With Scout by three while total-owned, sales, fulfillment, and credit remain unchanged.
- `INV-M-04-02` Exceeding unassigned stock or mismatching campaignId/profileId/roster identity is rejected without a balance change.
- `INV-M-04-03` `AUTH-U` and `IDEM` apply.

**`returnStockFromScout`**

- `INV-M-05-01` Alex can submit two of X and three of Y in one click and receive both updated inventory and custody balances in one atomic result.
- `INV-M-05-02` Returning more than With Scout for any product rejects the entire batch; no product is partially returned.
- `INV-M-05-03` Empty batches fail validation, and a batch whose computed write plan exceeds 90 actions fails before writing; larger returns are split into independently atomic batches. `AUTH-U` and `IDEM` apply.

**`fulfillIndividualOrderLine`**

- `INV-M-06-01` Alex can fulfill part of an unfulfilled line from unassigned Kernel stock; fulfilled quantity and stock each change exactly once.
- `INV-M-06-02` External-Council fulfillment changes fulfilled quantity without changing stock, including when no inventory balance exists.
- `INV-M-06-03` Quantity above remaining, wrong source scope, and stale `expectedFulfillmentVersion` are rejected without over-fulfilling.

**`reverseIndividualOrderFulfillment`**

- `INV-M-07-01` Reversing a Kernel-stock fulfillment restores stock and demand exactly once; reversing external fulfillment restores demand only.
- `INV-M-07-02` A second reversal for the same fulfillment or a stale version returns `CONFLICT` and creates no extra stock.
- `INV-M-07-03` `AUTH-U` and `IDEM` apply using `orderId + fulfillmentId` for authoritative lookup.

## 5. Show & Sell event, slot, and signup endpoints

### 5.1 Event and participant queries

**`showAndSell` / `showAndSells`**

- `EVT-Q-01-01` Alex receives administrative event detail/list with location, immutable times, split, We Owe, allocations, slots, status, and version only for his Unit Campaign.
- `EVT-Q-01-02` `AUTH-U`, date/status filters, and `PAGE-01` apply.

**`unitCampaignOpportunities`**

- `EVT-Q-02-01` Morgan and Riley can read eligible Scout opportunities containing only participant-safe event/slot/signup fields and `pageInfo`.
- `EVT-Q-02-02` Removed-membership Scouts retain only existing-participation visibility; Emery receives no new opportunity access, and no stock/sales/buyer data appears.

**`showAndSellOpportunity`**

- `EVT-Q-03-01` Morgan can read Avery's slot/commitment view; Riley receives the same participant-safe read for Avery.
- `EVT-Q-03-02` Emery, another Scout's profileId, or a cross-Unit event returns `NOT_FOUND`; administrative fields are absent.

**`showAndSellSales`**

- `EVT-Q-04-01` Alex can page through buyer/payment sale snapshots for his event.
- `EVT-Q-04-02` `AUTH-U` and `PAGE-01` apply; participant opportunity APIs cannot substitute for this output.

**`showAndSellSignups`**

- `EVT-Q-05-01` Alex receives full actor/confirmation/work audit for event signups, while shared participant mutations return only `ParticipantSignup`.
- `EVT-Q-05-02` `AUTH-U` and `PAGE-01` apply.

**`showAndSellFinalizationPreview`**

- `EVT-Q-06-01` Alex receives computed pool, base allocations, unassigned cents, expected returns, cash preview, issues, and eventVersion without approving credit.
- `EVT-Q-06-02` Calling preview repeatedly creates no finalization, allocation, cash, or inventory record.

**`showAndSellFinalization`**

- `EVT-Q-07-01` Alex can read metadata/cash/status/version IDs for current and prior approved versions.
- `EVT-Q-07-02` Mismatched event/finalization IDs or another Unit returns `NOT_FOUND`; child data is not returned unpaginated.

**`showAndSellFinalizationSaleSnapshots` / `showAndSellFinalizationWorkSnapshots` / `showAndSellFinalizationReturnLines` / `showAndSellFinalizationCredits`**

- `EVT-Q-08-01` Alex can independently page each immutable collection and reconstruct the version's exact sales, per-slot work, returns, and credit after current drafts change.
- `EVT-Q-08-02` `AUTH-U` and `PAGE-01` apply to all four; participant actors never access buyer or administrative audit content.

### 5.2 Event mutations

**`createShowAndSell`**

- `EVT-M-01-01` Alex can create overlapping events with required short location name, optional address, immutable times, inherited/overridden split, and We Owe defaulting off.
- `EVT-M-01-02` Missing location or end ≤ start is rejected. Any number of products from the Unit Campaign catalog may be used over the event's lifetime, subject only to per-mutation and finalization-feasibility checks.
- `EVT-M-01-03` `AUTH-U` and `IDEM` apply.

**`updateShowAndSell`**

- `EVT-M-02-01` Alex can edit location/split/We Owe in allowed states but cannot supply startAt/endAt or update a finalized event without reopening.
- `EVT-M-02-02` Disabling We Owe cannot invalidate or strand an existing We Owe sale/obligation.
- `EVT-M-02-03` `AUTH-U`, `VER-01`, and state-matrix checks apply.

**`cancelShowAndSell`**

- `EVT-M-03-01` Casey can cancel a future event and receive one coherent result with released allocations, cancelled signups/commitments, zero counters, and stored reason/actor.
- `EVT-M-03-02` Cancellation at/after start or by Morgan is rejected without changing allocations/signups.
- `EVT-M-03-03` `AUTH-U`, `VER-01`, `IDEM`, and combined-write-limit preflight apply.

**`assignShowAndSellInventory`**

- `EVT-M-04-01` Alex receives sequential-over-assignment warnings while concurrent over-assignment returns `CONFLICT` without physical-stock changes.
- `EVT-M-04-02` Target zero releases remaining allocation, omitted products remain unchanged, and automatic reductions can be manually adjusted.
- `EVT-M-04-03` A 16th distinct catalog product is allowed when its computed write plan fits within 90 actions; a batch that exceeds the computed budget is split into independently atomic assignments, and finalization includes every product; `AUTH-U`, `VER-01`, `IDEM`, and finalization-feasibility preflight apply.

### 5.3 Slot mutations

**`upsertShowAndSellSlot`**

- `SLOT-M-01-01` Alex can create 90-, 120-, and 180-minute slots with arbitrary capacities and update them in SCHEDULED state.
- `SLOT-M-01-02` Slot outside event, capacity below active signups, more than 20 slots, or a time update that creates a Scout conflict is rejected without changing existing signups.
- `SLOT-M-01-03` `AUTH-U`, `VER-01` for event and slot, and `IDEM` apply.

**`deleteShowAndSellSlot`**

- `SLOT-M-02-01` Alex can delete a slot with zero active signups using `showAndSellId + slotId`.
- `SLOT-M-02-02` A slot with active signups cannot be deleted and no implicit cancellation occurs; `AUTH-U`, `VER-01`, and state checks apply.

### 5.4 Signup and work mutations

**`signupScoutForShowAndSellSlot`**

- `SIGN-M-01-01` Morgan can sign up Avery and Alex can sign up Blake; both receive participant-safe signup output without actor IDs.
- `SIGN-M-01-02` Riley receives `FORBIDDEN`; duplicate signup, capacity overflow, unjoined Emery, or cross-Unit-Campaign time overlap returns `CONFLICT`/`FORBIDDEN` as appropriate.
- `SIGN-M-01-03` A membership removal racing signup invalidates the membership-version condition; no new commitment is created.
- `SIGN-M-01-04` Finalization-feasibility preflight rejects an addition that would make the event impossible to finalize while correction is still possible.

**`cancelShowAndSellSignup`**

- `SIGN-M-02-01` Morgan can cancel Avery before start; Unit Admin can correct signup records in ACTIVE, ENDED, or REOPENED states, including after membership removal.
- `SIGN-M-02-02` Riley cannot cancel, and a finalized event requires reopen before Unit Admin correction.
- `SIGN-M-02-03` Cancellation updates signup, commitment, slot count, and event version atomically without changing approved history until re-finalization.

**`confirmShowAndSellWork`**

- `SIGN-M-03-01` Alex can confirm actual minutes per slot and receives admin work output plus a recomputed pending preview without approved credit.
- `SIGN-M-03-02` Zero unconfirms a participant and frees finalization budget; values above slot duration, duplicate Scout/slot rows, or ineligible participants are rejected.
- `SIGN-M-03-03` `AUTH-U`, `VER-01`, `IDEM`, and finalization-feasibility preflight apply.

## 6. Show & Sell sale and We Owe endpoints

### 6.1 Sale mutations

**`createShowAndSellSale`**

- `SALE-M-01-01` Alex can enter an ACTIVE/ENDED event sale and receive sale, allocation, inventory, We Owe, and warning results; Morgan and Riley are denied.
- `SALE-M-01-02` Scheduled events, finalized/cancelled events, saleAt outside the event, stale eventVersion, or a line batch whose computed write plan exceeds 90 actions are rejected without effects. The largest computed transaction-safe batch succeeds, and larger orders are split into independently atomic sales.
- `SALE-M-01-03` We Owe-disabled unavailable quantity is rejected; enabled mixed immediate/We Owe lines create linked obligations with buyer name only.
- `SALE-M-01-04` Other requires details; custom methods must be active and belong to the event Unit. Sending only product IDs/quantities returns server-derived name/price/subtotal/total snapshots; malicious extra price/name/total input fields fail GraphQL input validation rather than being accepted or overridden.
- `SALE-M-01-05` Reopened sales create draft revisions without immediate stock effects; retries cannot create two sale IDs or duplicate stock.

**`correctShowAndSellSale`**

- `SALE-M-02-01` Before first finalization, Alex can correct an existing line by `lineItemId` and only its immediate/We Owe deltas are applied with a preserved prior revision.
- `SALE-M-02-02` Reopened corrections defer effects, add new product IDs/zero baselines where needed, and preserve immutable previous sale content.
- `SALE-M-02-03` Omitted lines are voided, new lines create supplemental obligations, and reducing below fulfilled We Owe or using a stale revision/eventVersion is rejected.
- `SALE-M-02-04` Unchanged corrections may retain a deactivated original payment method; `AUTH-U` and `IDEM` apply.

**`voidShowAndSellSale`**

- `SALE-M-03-01` Alex can void an entire unfulfilled sale with a reason and receive correct stock/obligation reversals and sales-pool updates. Line-level voiding is covered through `correctShowAndSellSale` by omitting an existing line from `lineItems`, including fulfilled-We Owe rejection and reservation release checks.
- `SALE-M-03-02` Fulfilled We Owe cannot be voided as unfulfilled; no reservation may remain after corrected remaining quantity reaches zero.
- `SALE-M-03-03` `AUTH-U`, stale revision/eventVersion, and `IDEM` rules apply.

### 6.2 We Owe queries and mutations

**`weOweObligation` / `weOweObligations`**

- `OWE-Q-01-01` Alex can read one obligation and page/filter by open/closed, event, product, and buyer without due-date, aging, or assignee fields.
- `OWE-Q-01-02` `AUTH-U` and `PAGE-01` apply; participants/buyers cannot access these endpoints.

**`setWeOweReservation`**

- `OWE-M-01-01` Alex can set partial reservation, moving that quantity to sold-in-possession while physical stock stays unchanged and uncovered decreases consistently.
- `OWE-M-01-02` Target below zero, above remaining, or above unassigned stock is rejected; target zero releases reservation without automatic reassignment.
- `OWE-M-01-03` `AUTH-U`, `VER-01`, and `IDEM` apply; new receipts never auto-reserve.

**`fulfillWeOwe`**

- `OWE-M-02-01` Partial Kernel-stock fulfillment decreases physical, reserved, covered, and remaining quantities together without changing sale/credit.
- `OWE-M-02-02` External fulfillment is allowed only up to uncovered quantity and changes no stock; fulfilling covered stock externally first requires explicit reservation release.
- `OWE-M-02-03` The obligation closes only at zero remaining and zero reserved; stale versions/excess quantities write nothing.

## 7. Finalization and reopening endpoints

**`updateShowAndSellRoundingDraft`**

- `FIN-M-01-01` Alex can assign whole cents to unique eligible participants and receives an updated preview without approved credit.
- `FIN-M-01-02` Negative cents, duplicate profiles, ineligible participants, or a draft sum above unassigned cents are rejected; `AUTH-U`, `VER-01`, and `IDEM` apply.

**`finalizeShowAndSell`**

- `FIN-M-02-01` Alex can finalize an ENDED event with valid returns, cash, and complete rounding assignments, receiving one approved version, credit, inventory movements, and later-allocation reductions.
- `FIN-M-02-02` Active/scheduled/finalized/cancelled states, stale versions, missing actual returns/reasons, incomplete cash explanations, or unassigned cents block approval without partial effects.
- `FIN-M-02-03` Re-finalization computes deltas against the previous approved version; unchanged returns produce zero stock adjustment and old/new snapshots remain queryable.
- `FIN-M-02-04` `IDEM`, combined-write and finalization-feasibility limits apply; oversized input fails before any write with `OPERATION_TOO_LARGE`.

**`reopenShowAndSell`**

- `FIN-M-03-01` Alex can reopen a finalized event with a reason, immediately suspending approved credit while leaving returned stock and all prior versions intact.
- `FIN-M-03-02` Reopening a non-finalized event is rejected; the suspended version preserves actor/time/reason and current totals exclude only the suspended credit.
- `FIN-M-03-03` `AUTH-U`, `VER-01`, and `IDEM` apply.

## 8. Reporting data endpoints and browser-generated artifacts

All report/CSV/XLSX/print/ICS generation happens in the browser. No scenario calls a report-generation, export, printable-file, or ICS-file resolver.

**`unitCampaignOrderLines`**

- `DATA-Q-01-01` Alex receives paginated `AdminOrderLineFact` rows with full Order/Campaign/Scout/customer-contact/product/quantity/fulfilled/price/subtotal/order-total/payment/date/origin fields required for Seller Report and Order Details parity.
- `DATA-Q-01-02` `AUTH-U` and `PAGE-01` apply; failed/forbidden pages fail report assembly rather than returning a shortened report as complete.

**`unitCampaignCreditAllocations`**

- `DATA-Q-02-01` Alex receives raw finalization/event/Scout/base/rounding/total/minutes/status facts without server-built seller summaries.
- `DATA-Q-02-02` `AUTH-U` and `PAGE-01` apply; pending split data comes from the operational preview, not a report resolver.

**`eventInventoryAllocations`**

- `DATA-Q-03-01` Alex receives raw intervals and allocated/sold/released/remaining quantities for browser assigned/unassigned/overage calculations.
- `DATA-Q-03-02` `AUTH-U` and `PAGE-01` apply; the browser fetches every required page before producing totals.

**`scoutCampaignOrderLines` / `scoutCampaignCreditAllocations`**

- `DATA-Q-04-01` Morgan and Riley receive `ParticipantOrderLineFact` and `ParticipantSalesCredit` rows for Avery across scopes, with no customer contact, finalizationId, actor, or administrative audit fields and no server-computed aggregate summary.
- `DATA-Q-04-02` Alex must supply an authorized unitCampaignId and receives only that scope; `AUTH-P` and `PAGE-01` apply.

**`scoutCampaignPendingAllocations`**

- `DATA-Q-04A-01` Morgan and Riley receive only Avery's pending amount, eventVersion, and computedAt for current unfinalized/reopened events, with no admin pool, cash, returns, or other Scouts' allocations.
- `DATA-Q-04A-02` Riley cannot query Blake, revoked access is denied immediately, and after re-finalization the old pending rows disappear while approved ParticipantSalesCredit remains correctly scoped.

**`showAndSellSignupCalendarData`**

- `DATA-Q-05-01` After Morgan signs Avery up, Morgan or Alex can fetch the authorized Unit/Campaign/event/slot/signup/time/location/description data needed to generate ICS in the browser.
- `DATA-Q-05-02` Riley cannot invoke the mutation-adjacent data endpoint with READ-only access, and no generated ICS file or automatic notification is returned.

**`showAndSellFinalizations`**

- `DATA-Q-05A-01` Alex can page approved, suspended, and superseded version summaries and follow previousFinalizationId to select an exact historical version for browser reporting.
- `DATA-Q-05A-02` `AUTH-U` and `PAGE-01` apply; mismatched versions are rejected during browser assembly.

**Existing raw data resolvers**

- `DATA-Q-06-01` Browser tests assemble inventory from `inventoryPositions`, custody, We Owe, events, sales, finalization snapshots, roster, Unit settings, `unitCampaignCatalog`, and payment methods, verifying each resolver's existing authorization, domain-version fields, and pagination contracts.
- `DATA-Q-06-02` No call is made to `showAndSellReport`, `scoutCampaignSalesSummary`, `unitSellerReport`, `inventoryReport`, `councilNeedsReport`, `weOweReport`, `requestUnitReportExport`, `showAndSellSalesSheet`, `showAndSellPaymentHelpSheet`, or `showAndSellSignupCalendar` because those resolvers do not exist in the target API.

### 8.1 Browser report generation

- `WEB-RPT-01` Given 10 demand, 6 sellable, 4 assigned, and 2 With Scout, the browser computes physical need 4 and after-assignments need 8 while displaying on-order and custody separately without subtracting them.
- `WEB-RPT-02` Browser-generated Unit seller and all-scope Scout reports group raw Orders/credits only in their originating Unit Campaign, keep pending separate from approved, and do not duplicate individual sales after a later join.
- `WEB-RPT-03` Browser-generated inventory, We Owe, and Show & Sell reports reconcile to raw balances, allocations, sales, fulfillments, finalization versions, and payment snapshots.
- `WEB-RPT-04` A failed/forbidden data page, version mismatch, or incomplete cursor sequence prevents file generation and shows an error rather than silently truncating results.
- `WEB-RPT-05` CSV and XLSX files are generated locally with sanitized values, correct integer-cent display, scoped filenames, and no request to a server export endpoint or third-party converter.
- `WEB-RPT-06` Rendered tables, CSV, XLSX, and printable output generated from the same dataset contain identical rows and totals.

### 8.2 Browser-generated printable documents and ICS

- `WEB-PRINT-01` Browser-generated sales/payment HTML displays Unit, Unit Campaign, event identity/location/time, generation timestamp, required sale/payment/Other/We Owe content, and applicable QR references without a printable-document resolver.
- `WEB-PRINT-02` Printing uses the native browser print flow, and changing methods after HTML generation does not alter the already generated document.
- `WEB-PRINT-03` For an event with no sales, `unitCampaignCatalog` supplies current product names/prices. The browser fetches `unitPaymentMethodQrDownloadUrl`, loads the authorized QR image while online, and embeds the actual image/data URL so it remains visible in offline print output rather than merely retaining an S3 reference.
- `WEB-ICS-01` The browser generates one VEVENT from `showAndSellSignupCalendarData` with stable UID, DTSTAMP, arbitrary start/end converted using the supplied IANA timezone, location/address, and Unit/Campaign description, then downloads it as `.ics` without an ICS resolver.
- `WEB-ICS-02` ICS escaping, line folding, injection prevention, 64 KiB limit, non-admin participant timezone handling, arbitrary durations, and a DST-transition fixture pass; cancelling does not modify an already downloaded file and no automatic email/notification/sync occurs.

### 8.3 Existing application reporting migration

- `WEB-MIG-01` Existing CampaignReportsPage produces Unit Summary, Seller Report, and Order Details from `listMyProfiles`/`listMyShares` discovery plus complete `listCampaignsByProfile` and `listOrdersByCampaign` pagination in the browser, with output parity and no `getUnitReport` call. Owners and READ collaborators receive their currently authorized records, revoked collaborators disappear immediately, and cross-tenant callers receive nothing.
- `WEB-MIG-02` Existing ReportsPage continues CSV/XLSX download through the shared browser engine with no `requestCampaignReport` call or S3 report URL.
- `WEB-MIG-03` After parity, schema/IaC review confirms `getUnitReport`, `requestCampaignReport`, their Lambda report writers, S3 report output, and unneeded IAM permissions are removed rather than merely unused.
- `WEB-MIG-04` From Phase 1 onward, a static schema/IaC/frontend CI guard rejects every new report/document/ICS resolver, report-download type/URL, Lambda report writer, or S3 report output while allowlisting only the two legacy paths awaiting removal.

## 9. Existing individual Order API extensions

**`createOrder(fulfillmentMode = NONE)`**

- `ORD-API-01-01` Existing individual Orders retain current behavior: no inventory/custody is consumed, fulfillment starts at zero, and lack of stock never blocks the sale.
- `ORD-API-01-02` The Order captures the Campaign's current joined Unit scope immutably, or null for an independent Campaign.

**`createOrder(fulfillmentMode = CONSUME_SCOUT_CUSTODY)`**

- `ORD-API-02-01` Morgan can record Avery's door-to-door sale with sufficient custody; it consumes With Scout and marks that quantity fulfilled without decrementing Kernel stock.
- `ORD-API-02-02` A larger sale consumes only available custody and leaves the remainder unfulfilled/Council demand; With Scout never becomes negative and the sale is not blocked.
- `ORD-API-02-03` Riley with READ-only access cannot create the Order; retrying the same idempotency key cannot consume custody twice.
- `ORD-API-02-04` After the Campaign joins another Unit Campaign, the old Order, fulfillment, and Council demand retain the original scope.

**Order `fulfillments` participant output versus `orderFulfillments` admin output**

- `ORD-API-03-01` Morgan and Riley can read source/quantity/reversal history on Avery's Order without actorAccountId, inventoryMovementId, or administrative audit fields.
- `ORD-API-03-02` Alex can call the separate administrative endpoint for full actor/source/movement/reversal history, while `AUTH-U` and `AUTH-P` restrictions remain intact.

## 10. Endpoint acceptance completion gate

The endpoint E2E suite is complete only when:

- Every resolver in `SHOW_AND_SELL_GRAPHQL_API.md` has at least one positive scenario and every privileged resolver has a denied scenario.
- All applicable shared `AUTH-U`, `AUTH-P`, `VER`, `IDEM`, and `PAGE` scenarios pass.
- Revoked Unit Admin and READ-only Profile access are tested through direct GraphQL calls, not inferred from UI visibility.
- No denied call changes balances, roster, commitments, sales, obligations, cash, credit, or audit state.
- All versioned/idempotent retries preserve one logical result, including bootstrap and consumed-invite retries.
- Limit tests cover combined write/finalization feasibility as well as individual field maxima.
- Participant outputs and admin outputs are verified as separate GraphQL projections.
- Reports, CSV/XLSX, printable documents, and ICS files are generated and inspected in the browser; no server report/document-generation endpoint, S3 report output, or pre-signed report URL is used.
- Every scenario's lane-scoped cleanup passes without affecting another active lane.
