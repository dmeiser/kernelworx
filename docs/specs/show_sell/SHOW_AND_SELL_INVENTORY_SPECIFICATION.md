# Show & Sell and inventory: MoSCoW and specification

**Status:** Requirements specification; all identified product decisions resolved  
**Last updated:** 2026-10-29  
**Scope:** Major feature  
**Priority ruling:** Every confirmed product requirement in this document is **Must have**.  
**Smoke walkthroughs and fixture acceptance criteria:** [Show & Sell smoke test plan](SHOW_AND_SELL_SMOKE_TEST_PLAN.md)  
**Technical data model:** [Show & Sell data model](SHOW_AND_SELL_DATA_MODEL.md)  
**GraphQL resolver contracts:** [Show & Sell GraphQL API](SHOW_AND_SELL_GRAPHQL_API.md)  
**Endpoint E2E descriptions:** [Show & Sell GraphQL E2E test descriptions](SHOW_AND_SELL_GRAPHQL_E2E_TEST_DESCRIPTIONS.md)  
**Reporting architecture:** [Browser-only reporting and document generation](BROWSER_REPORTING_ARCHITECTURE.md)  
**Transaction sequences:** [Show & Sell sequence diagrams](SHOW_AND_SELL_SEQUENCE_DIAGRAMS.md)  
**Delivery execution:** [Show & Sell delivery checklist](SHOW_AND_SELL_DELIVERY_CHECKLIST.md)  
**Existing-system integration:** [Existing-application impact map](SHOW_AND_SELL_EXISTING_APPLICATION_IMPACT.md)

> This revision incorporates the requirements-discovery answers received after the first draft. Rules the first draft invented without confirmation have been removed or corrected. Section 16 records the resolution of every previously identified open decision; newly discovered requirements should continue to be added explicitly rather than implemented as assumptions.

## 1. Purpose

Add campaign-scoped popcorn inventory and unit-run **Show & Sells** so Popcorn Kernels can:

- receive, adjust, issue, assign, sell, return, and reconcile product inventory;
- schedule overlapping Show & Sells with capacity-based signup slots;
- split each Show & Sell's whole-event sales pool equally or by actual time worked;
- finalize event sales, inventory returns, cash, We Owe obligations, and Scout credit under Kernel control;
- issue stock to Scouts for door-to-door sales without prematurely marking it sold;
- compare actual unfulfilled customer demand with current inventory and separately displayed Council on-order quantities; and
- operate from printable sales/payment help sheets when internet access is unavailable.

Individual Scout Campaign sales are never blocked merely because inventory is unavailable.

## 2. Requirements status and MoSCoW

### 2.1 Meaning of labels

- **Must:** A confirmed product requirement and a feature-completion gate.
- **Constraint:** A technical integrity/security rule needed to implement confirmed behavior safely.
- **Open:** A product decision or workflow still requiring discovery.

### 2.2 MoSCoW summary

| Priority | Confirmed requirement group | Included capabilities |
| --- | --- | --- |
| **Must have** | Unit and leadership | Standalone Unit, multiple equal Unit Admins (Unit Kernels), Unit Campaign membership, server-enforced authorization |
| **Must have** | Kernel inventory | Campaign-scoped stock, one unit equals one sale unit, stock-only adjustments, receipts, current inventory lists |
| **Must have** | Scout stock custody | Issue unsold stock to Scouts, consume it for door-to-door sales, tracked and one-click returns |
| **Must have** | Show & Sells | Locations, arbitrary event times, overlapping events, event-level product allocations |
| **Must have** | Allocation safeguards | Block concurrent over-assignment, warn on sequential over-assignment, earlier-event priority during automatic later reduction, Kernel override |
| **Must have** | Slots and work | Variable-duration capacity-based slots, multiple non-overlapping signups, conflict blocking, per-shift actual work confirmation |
| **Must have** | Sales and splits | Kernel-only event sale entry, one whole-event pool, equal or time-worked method, unit default and event override |
| **Must have** | Finalization and credit | Kernel finalization after the event, expected/confirmed stock return, cash reconciliation, finalized-only Scout credit, reopen/suspend/reapprove |
| **Must have** | Unit payment methods | One shared Unit-level list for every Unit Campaign and Show & Sell, Cash/Check/Other and named methods, shared QR codes, Other details |
| **Must have** | Printable/calendar operation | Printable sales and payment/help sheets with applicable QR codes, later manual entry, downloadable ICS slot invites |
| **Must have** | We Owe | Per-event setting off by default, buyer/unit ledger, reports, Kernel-controlled inventory reservation and fulfillment |
| **Must have** | Reporting | Sales by Show & Sell, finalized Scout totals, inventory/custody/We Owe lists, Council Needs and separate on-order quantities |
| **Should have** | None | No confirmed requirement is deferred to this category. |
| **Could have** | None | No confirmed requirement is deferred to this category. |
| **Won't have** | Explicitly rejected behavior | See below. |

### 2.3 Explicit Won't / rejected behavior

These are scope decisions, not deferred Must requirements:

- No per-Show & Sell payment-method allowlist. The shared Unit-level list applies to every Unit Campaign and event.
- No separate Unit Admin and Unit Kernel permission sets. They are synonyms for one role.
- No case-pack or other quantity conversion: **one inventory unit always equals one sale unit**.
- No offline application mode or offline sales queue. Use printable sheets followed by manual Kernel entry.
- No separate sales pool per slot. Each event has one whole-event pool.
- No multiple-tender payment records on one sale. Use **Other** with explanatory details for split payments.
- No automatic parsing of Other payment notes and no dedicated cash-portion field for split payments.
- No automatic subtraction of Council on-order quantities from Council Needs.
- No future-demand projection in Council Needs.
- No automatic priority among individual orders, We Owe obligations, active events, and future events; the Kernel assigns priority, except for the explicitly confirmed earlier-event allocation-reduction rule.
- No separate post-finalization return/refund/exchange transaction workflow. The Kernel reopens and corrects the original event.
- No automatic reclaim of returned event stock when an event is reopened.
- No inter-unit trade, reimbursement, or backend money-exchange tracking. Inventory-only adjustments must not create financial side effects.
- No parent/Scout event-sale entry. Only Kernels enter Show & Sell sales.
- No automatic notifications, notification emails, notification center, or calendar synchronization. Calendar invites are downloaded manually as ICS files.

## 3. Terminology

| Term | Meaning |
| --- | --- |
| **Account** | A signed-in application user. A buyer need not have an Account. |
| **Scout** | An individual seller, represented by the existing `SellerProfile`. |
| **Campaign** | A Scout's existing individual sales container. |
| **Unit** | A standalone organization with a stable `unitId`, descriptive unit metadata, access grants, payment methods, defaults, and one or more Unit Campaigns. Mutable metadata such as unit number or city is not its identity. |
| **Unit Admin (Unit Kernel)** | One Unit-scoped administrator role with two synonymous names. Every grant has identical full Unit permissions. This is not the global application Admin role or a SellerProfile Share. |
| **Unit access grant** | The association giving an Account the Unit Admin (Unit Kernel) role. Accounts may administer multiple Units, and Units may have multiple grants. |
| **Unit Campaign** | A shared unit sales season belonging to exactly one Unit. Joined Scout Campaigns, campaign-scoped inventory, Council on-order quantities, and Show & Sells belong to it. |
| **Kernel** | Operational shorthand for Unit Admin (Unit Kernel) throughout this specification; it never denotes a separate or lesser role. |
| **Show & Sell** | A unit inventory sales event with a time window and location. |
| **Slot** | A variable-duration, capacity-based work shift within a Show & Sell. |
| **Confirmed work** | Kernel-confirmed participation and actual time worked per slot. A signup alone is not confirmed work. |
| **Individual sale** | An existing Scout Campaign order outside the Show & Sell sales pool. |
| **Show & Sell sale** | A sale belonging to the event's whole-event pool, not to one Scout's personal sale total at entry time. |
| **Scout sales allocation** | A Scout's monetary share calculated from the whole-event pool. Product quantities are not split among Scouts. |
| **Kernel stock** | Undelivered physical stock in the Kernel/unit's central custody. It excludes stock issued to Scouts. |
| **With Scout** | Unit-owned, unsold stock issued to a Scout for future individual/door-to-door sales. It is unavailable to the Kernel until returned or consumed by a sale. |
| **We Owe** | Product owed to a buyer because it was not handed over at a Show & Sell. |
| **Sold product in our possession** | Kernel stock reserved for a We Owe buyer; physically present but unavailable for any other use. |
| **Council on order** | Product ordered from Council but not yet received. It is displayed separately from current stock and actual need. |

### 3.1 Canonical language

`TERM-01` **Must:** Use **Show & Sell** as the canonical singular user-facing term and **Show & Sells** as its plural in navigation, forms, validation, reports, exports, help, and notifications. Do not use “Show and Sell,” “Show-and-Sell,” or “S&S” in user-facing copy. Internal identifiers may use `ShowAndSell`.

`TERM-02` **Must:** Use **We Owe** in user-facing copy. It describes a product obligation, not a payment status.

## 4. Standalone Unit, access, and Unit Campaigns

`UNIT-01` **Must:** A Unit is a standalone entity with a stable `unitId` and descriptive metadata such as unit type, unit number, city, state, and display name. Relationships and authorization use `unitId`, not a concatenation of mutable metadata.

`UNIT-02` **Must:** A Unit has one or more Unit access grants linking Accounts to the single **Unit Admin (Unit Kernel)** role. “Unit Admin” and “Unit Kernel” are exact synonyms: there is one logical role, one permission set, and one authorization path, not two role values with separate behavior.

`UNIT-03` **Must:** A Unit supports multiple equal access grants, and an Account may hold grants for multiple Units. Any Unit Admin may add or remove other Unit Admins and perform every Unit operation, including access management, Unit settings, payment methods, campaigns, inventory, Show & Sell sales/finalization/reopening, and reports.

`UNIT-04` **Must:** A Unit must always retain at least one Unit access grant. Removing the final grant is not allowed.

`UNIT-05` **Must:** A Unit Campaign belongs to exactly one Unit through `unitId`. Inventory, Council on-order quantities, and Show & Sells remain Unit-Campaign-scoped; payment methods, split defaults, and the primary Council-need preference are Unit-scoped and shared by all of the Unit's campaigns.

`UNIT-06` **Must:** Products used by a Unit Campaign and its Show & Sells come from that campaign's catalog and use stable product IDs, never product names as identity.

`UNIT-07` **Must:** A Scout is eligible for Show & Sell signup only when that Scout has a Campaign explicitly joined to the Unit Campaign. A SellerProfile Share, matching Unit metadata, or viewing a SharedCampaign is not membership.

`UNIT-08` **Must:** Show & Sell allocations accrue to the Scout Campaign joined to that Unit Campaign, not to another Campaign owned by the same Scout.

`UNIT-09` **Must:** Only Unit Admins (Unit Kernels) may enter Show & Sell sales. Accounts that own or have WRITE access to a Scout may manage that Scout's signups, subject to slot and eligibility rules, but cannot enter event-wide sales.

`UNIT-10` **Constraint:** Every mutation must re-evaluate Unit access, SellerProfile access, Campaign membership, event state, slot conflicts/capacity, and stock rules on the server. Global application Admin status does not implicitly confer Unit access, and Unit access in one Unit grants no access to another.

`UNIT-11` **Must:** Creating a Unit requires unit type, unit number, city, and state, and permits an optional display name. When omitted, the display name is generated from the Unit's descriptive metadata. The generated or entered name never replaces `unitId` as identity.

`UNIT-12` **Must:** Any authenticated Account may create a Unit. The creator automatically receives its initial Unit Admin (Unit Kernel) grant.

`UNIT-13` **Must:** Unit access follows the existing Scout-profile invite-code flow: a Unit Admin generates a single-use 16-character code and shares it manually; any authenticated Account possessing the code may redeem it within 14 days; redemption creates an ongoing Unit access grant; and the code is deleted/consumed. There are no READ/WRITE choices because every grant has identical full access.

`UNIT-14` **Must:** A Unit Admin may list and revoke unused Unit invites and revoke redeemed access grants, subject to the final-grant invariant. As with current Scout-profile sharing, recipient self-removal is not required for this version; another Unit Admin revokes access.

`UNIT-15` **Must:** Unit numbers are not globally unique. Geographic metadata distinguishes Units with the same type/number, including cases such as “Pack 149” in different councils/geographies. Duplicate detection considers the complete unit type + unit number + city + state combination, never unit number alone. An exact metadata match displays a possible-duplicate warning and requires confirmation but does not block creation or merge Units automatically.

`UNIT-16` **Must:** No legacy production-user or production-data migration is required because there are no production users at this decision point. Unit, Unit access, Unit Campaign, and fulfillment relationships are implemented natively for launch; no self-service claiming or automatic administrative-access migration is in scope.

### 4.1 Scout roster lifecycle

`ROSTER-01` **Must:** Creating a Scout Campaign from a Unit Campaign/shared-campaign code automatically joins that Scout Campaign to the Unit Campaign. No separate Kernel approval is required. The join establishes Show & Sell signup eligibility.

`ROSTER-02` **Must:** A Unit Admin may remove a Scout Campaign's Unit Campaign membership. Removal blocks new Show & Sell signups but does not automatically cancel existing signups, remove confirmed work, recalculate pending allocations, or alter finalized history. The Kernel reviews and corrects any unfinalized records manually.

`ROSTER-03` **Must:** Removing membership does not make existing unfinalized participation ineligible by itself. The Kernel may retain that historical participation or correct it before finalization. Finalized history changes only through the reopen/re-finalize workflow.

`ROSTER-04` **Must:** Scout Campaigns and their history are not transferred automatically between independent Unit Campaigns. Joining another Unit Campaign does not move prior sales, allocations, inventory custody, or We Owe history.

## 5. Inventory model

### 5.1 Quantity and ownership rules

`INV-01` **Must:** Inventory is campaign-scoped. One inventory unit equals one sale unit for that product. Quantities are non-negative integers; there are no cases, fractional sale units, or unit conversions.

`INV-02` **Must:** A Kernel may record received product and make stock-only positive or negative adjustments. An adjustment records product, quantity, reason, actor, and timestamp.

`INV-03` **Must:** A stock-only adjustment does not create or change an order, sale, payment, trade, reimbursement, fulfillment, Scout credit, or financial record. For example, an inter-troop trade can be represented by stock adjustments while its money exchange remains outside the application.

`INV-04` **Must:** The Kernel decides how to prioritize scarce stock among individual fulfillment, Scout issue, We Owe reservation, active events, and future events. New stock must not silently become committed to one of those demand classes through an automatic oldest-first or customer-class rule.

`INV-05` **Constraint:** Physical balances and custody balances cannot become negative. A Kernel action that would consume more than the selected source contains must be rejected or split into available and unfulfilled quantities as specified below.

### 5.2 Inventory quantities

All quantities are per unit campaign and product:

- **Kernel physical on hand:** Undelivered stock in central Kernel/unit custody, including sold product in our possession and stock assigned to open Show & Sells. It excludes With Scout stock.
- **Sold product in our possession:** Kernel physical on hand reserved for We Owe buyers.
- **Sellable Kernel stock:** `Kernel physical on hand - sold product in our possession`.
- **Assigned to open Show & Sells:** Unsold, unreleased event allocations. Finalized events do not retain an allocation.
- **Unassigned Kernel stock:** `max(0, sellable Kernel stock - assigned to open Show & Sells)`.
- **Assignment overage:** `max(0, assigned to open Show & Sells - sellable Kernel stock)`. This explains the allowed sequential-event warning; it is not Council demand.
- **With Scout:** Unsold unit-owned stock in each Scout's custody, plus the aggregate across Scouts.
- **Total unit-owned undelivered stock:** `Kernel physical on hand + With Scout`.

Assigned stock remains part of Kernel physical on hand until sold or otherwise adjusted. Returning unsold event stock releases its assignment; it does not fabricate additional physical stock.

### 5.3 Issue stock to Scouts for future sales

`CUST-01` **Must:** A Kernel may issue available unassigned Kernel stock to an eligible Scout for future individual/door-to-door sales. Issuance:

- decreases unassigned/sellable Kernel stock;
- increases that Scout's With Scout balance;
- preserves total unit-owned undelivered stock;
- creates no sale;
- fulfills no existing order; and
- creates no Scout sales credit.

`CUST-02` **Must:** The inventory view shows With Scout quantities in aggregate and per Scout. With Scout stock is not available for event assignment, We Owe reservation, Kernel-stock fulfillment, or either Council-need stock calculation until returned.

`CUST-03` **Must:** When a Scout records an individual door-to-door sale, available With Scout stock is consumed for that sale and the consumed quantity is marked fulfilled. Kernel stock must not be decremented again.

`CUST-04` **Must:** If the individual sale quantity exceeds available With Scout stock, the sale is still accepted. Only available custody is consumed; the remaining quantity stays unfulfilled and contributes to Council demand. With Scout cannot become negative.

`CUST-05` **Must:** A Kernel may fulfill an unfulfilled individual order directly from unassigned Kernel stock. This decrements Kernel stock and increases the order's fulfilled quantity in one operation. Fulfillment from product supplied directly by Council changes fulfillment without changing Kernel stock.

`CUST-06` **Must:** A Kernel may return unsold With Scout stock to unit stock. The return decreases Scout custody and increases unassigned Kernel stock without creating a sale or changing Scout credit.

`CUST-07` **Must:** Provide a one-click **Return to Unit stock** action after the Kernel enters the stated return quantities, such as two of product X and three of product Y. Confirmation and submission of those quantities must be one workflow, not a series of per-unit adjustments.

### 5.4 Independent campaigns and deactivation

`CYCLE-01` **Must:** Unit Campaigns are independent. There is no automatic inventory, custody, We Owe, Council on-order, or product transfer between campaigns and no cross-catalog product-mapping workflow.

`CYCLE-02` **Must:** A Kernel may deactivate a Unit Campaign with its balances and obligations in any state. Deactivation does not require cleanup and does not automatically zero stock, transfer stock, cancel events, remove With Scout balances, close We Owe obligations, cancel Council on-order quantities, or alter historical records.

`CYCLE-03` **Must:** Leftover stock may remain in a deactivated campaign or be reduced through ordinary reasoned stock-only adjustments, including stock given away as gifts. A gift/write-off adjustment creates no sale, payment, fulfillment, or Scout credit.

## 6. Show & Sell events and slots

### 6.1 Event fields and timing

`SSE-01` **Must:** A Kernel may create a Show & Sell with:

- a required short location name, such as “Kroger on Monroe”;
- an optional address;
- start and end date/time;
- a split method inherited from the unit default, with an event override;
- We Owe enabled or disabled, defaulting to disabled;
- product allocations; and
- one or more variable-duration slots.

`SSE-02` **Must:** Multiple Show & Sells may run at the same time or overlap. Overlap alone is never a rejection reason.

`SSE-03` **Must:** Event end must be after event start. Slots may have any valid duration; the application must not assume one-hour increments.

`SSE-04` **Must:** Ending time and Kernel finalization are distinct. An ended event awaits Kernel finalization. Scout credit and final event outputs are not approved merely because the end time passed.

`SSE-05` **Must:** Only a Unit Admin may cancel a Show & Sell, and only before its scheduled start. Cancellation releases its remaining inventory allocations and signups and retains an audit record; it does not delete sales, We Owe, or other historical records.

`SSE-06` **Must:** A Show & Sell cannot be cancelled at or after its scheduled start. Use finalization and, when necessary, reopening/correction instead.

`SSE-07` **Must:** Show & Sell rescheduling is not supported. To change an event's date/time, a Unit Admin cancels the not-yet-started event and creates a new one. Allocations and signups are not copied or moved automatically. An event that has already started cannot use this workflow to rewrite its time.

### 6.2 Capacity-based signup slots

`SLOT-01` **Must:** Each slot has an arbitrary start/end within its event, a Scout capacity, and an optional label. Slot capacity is enforced on the server.

`SLOT-02` **Must:** Only eligible joined Scouts may sign up or be added by a Kernel. Duplicate signup to one slot is not allowed.

`SLOT-03` **Must:** A Scout may sign up for multiple non-overlapping slots, including slots at different Show & Sells.

`SLOT-04` **Must:** Any overlapping signup commitment for the same Scout is blocked, including overlaps between slots at different Show & Sells. Events themselves may still overlap.

`SLOT-05` **Must:** Signup is not work confirmation. A Kernel confirms actual participation and actual time worked per slot. Multiple confirmed slot durations are summed for the event's time-worked calculation.

## 7. Event inventory assignment

`ALLOC-01` **Must:** A Kernel may assign non-negative integer product quantities to a Show & Sell. Assignment commits sellable Kernel stock but does not change physical on-hand quantity or create Scout custody.

`ALLOC-02` **Must:** For each product, at every point in time, allocations for all Show & Sells active at that point must not exceed sellable Kernel stock. The server must reject an assignment that violates this concurrent-stock rule.

`ALLOC-03` **Must:** Assignments to non-overlapping Show & Sells may exceed current stock. The save succeeds with a prominent warning and accessible tooltip stating actual current stock and the assignment overage.

`ALLOC-04` **Must:** With four boxes available, assigning three boxes to each of two overlapping Show & Sells is blocked. Assigning three to a morning event and three to a non-overlapping afternoon event is allowed with a warning explaining that only four boxes are currently available.

`ALLOC-05` **Must:** After an earlier event is finalized and its actual remaining stock is confirmed, affected later allocations automatically reconcile using **earlier-event priority**. Process later events in start-time order: an earlier event retains its allocation up to available remaining stock, and subsequent events receive what remains. A Kernel may manually adjust the results.

`ALLOC-06` **Must:** In the four-box example, once the morning event has sold two boxes and is finalized, the afternoon allocation automatically becomes two boxes. If two later non-overlapping events each request three boxes when two remain, the earlier receives two and the later receives zero unless the Kernel changes the allocations.

`ALLOC-07` **Must:** Automatic reconciliation never changes a recorded sale or a finalized event, never increases physical stock, and is visible and auditable by the Kernel.

`ALLOC-08` **Constraint:** Concurrent assignment and sale attempts must use server-side atomic/conditional updates so stale clients cannot over-assign or drive balances below zero.

## 8. Show & Sell sales and payment methods

### 8.1 Sale entry

`SALE-01` **Must:** Only a Kernel may enter Show & Sell sales. Entry may occur during the event or later from a printable sales sheet, but must be complete before Kernel finalization.

`SALE-02` **Must:** Each sale records event, actual sale date/time, entry timestamp, entering Kernel, products/quantities, captured prices, total, one payment method, any required Other details, and buyer information needed for the transaction.

`SALE-03` **Must:** Immediate-handoff quantities consume event allocation and Kernel physical stock once. Show & Sell product quantities and inventory remain event/unit-level; they are not divided among Scout allocations.

`SALE-04` **Must:** If product is unavailable for immediate handoff and We Owe is disabled, that quantity cannot be submitted as part of the Show & Sell sale. The adult may handle it later as an individual/personal sale with the Kernel; it is not silently converted or allowed to create a negative event balance.

`SALE-05` **Must:** If We Owe is enabled, the unavailable quantity may instead be recorded as We Owe according to Section 10.

`SALE-06` **Must:** Individual Campaign sales remain accepted regardless of stock. The Show & Sell block in `SALE-04` does not apply to individual sales.

### 8.2 Shared unit payment methods

`PAY-01` **Must:** The standalone Unit owns one shared payment-method list used by every Unit Campaign and Show & Sell. There is no campaign-level or event-level allowlist or override.

`PAY-02` **Must:** All Unit Admins (Unit Kernels) may manage named Unit payment methods. Built-in methods are **Cash**, **Check**, and **Other**; named methods may include options such as Venmo or Zelle.

`PAY-03` **Must:** A named unit payment method may have one shared optional QR code, usable wherever that method is shown for a Show & Sell.

`PAY-04` **Must:** Each sale selects exactly one method. **Other** displays a free-text details field for the actual payment handling, such as “Apple Pay; Kernel reimbursed unit by Venmo.”

`PAY-05` **Must:** For a split payment, the Kernel selects **Other** and records each method and amount in the details. A tooltip must explain: “For split payments, select Other and enter each payment method and amount.” Do not create multiple tender records or parse the details.

`PAY-06` **Must:** Sales snapshot the selected method name and Other details. Later payment-method edits, deletion, or QR changes must not rewrite historical sales.

`PAY-07` **Must:** Event reports total sales by snapshotted payment method. Other details remain available in sale detail and exports.

## 9. Whole-event splitting and Scout credit

`SPLIT-01` **Must:** The unit has a default split method: **Equal split** or **Split by actual time worked**. A new Show & Sell inherits it, and a Kernel may override it for that event.

`SPLIT-02` **Must:** Each Show & Sell has exactly one whole-event sales pool. Slot totals do not create separate pools. For example, $300 sold in the morning and $100 in the afternoon produce one $400 pool.

`SPLIT-03` **Must:** Under **Equal split**, every eligible Scout with Kernel-confirmed work at the event receives an equal share, regardless of which slots they worked.

`SPLIT-04` **Must:** Under **Split by actual time worked**, each eligible confirmed Scout's share is:

`Scout share = whole-event sales pool × Scout's confirmed minutes across slots ÷ all eligible confirmed Scouts' minutes`

`SPLIT-05` **Must:** Scout allocations include finalized non-voided Show & Sell sales, including We Owe sales. Product quantities are not allocated to Scouts, and Show & Sell allocations do not consume or create With Scout stock.

`SPLIT-06` **Must:** Scout credit is pending while an event is scheduled, active, ended-awaiting-finalization, or reopened. It becomes approved and enters Scout total sales only when a Kernel finalizes the event.

`SPLIT-07` **Must:** Once finalized, Scout allocations and reports are final unless a Kernel reopens the event. Reopening immediately suspends that event's Scout credit and removes it from current Scout totals until the Kernel finalizes a revised version.

`SPLIT-08` **Must:** Scout total sales are:

`individual Campaign sales + approved allocations from finalized Show & Sells`

Pending or reopened-event allocations are shown separately as pending and are not included in approved totals.

`SPLIT-09` **Must:** Across all Scouts, approved allocations for an event equal its whole-event sales pool exactly once. The full event total is never added to every Scout.

`SPLIT-10` **Must:** Calculate shares without storing repeating decimals, then round each Scout's share down to whole cents. Display the remaining unassigned cents in the split preview. During finalization, the Kernel assigns every leftover cent to one or more Scouts; the application does not choose rounding winners automatically. An event cannot be finalized while any cent remains unassigned or while assignments exceed the remaining cents. For example, $100 split three ways starts at $33.33 per Scout with one cent unassigned; after the Kernel assigns that cent, the result is $33.34, $33.33, and $33.33 in the Kernel-chosen order.

## 10. We Owe

`OWE-01` **Must:** We Owe is configured per Show & Sell and defaults to **off** on every new event.

`OWE-02` **Must:** When enabled, an unavailable Show & Sell quantity may create a durable We Owe obligation linked to the Unit Campaign, event, sale, buyer, product, quantity, amount, and status. Buyer name is required; phone, email, and other contact details are optional. The buyer does not need an application Account.

`OWE-03` **Must:** We Owe sales enter the whole-event sales pool and receive Scout credit when the event is finalized, even if product delivery remains open. Fulfillment does not create a second sale or second Scout credit.

`OWE-04` **Must:** The Kernel decides whether available stock is reserved for a We Owe obligation. Reserved stock becomes **sold product in our possession**: it remains in Kernel physical on hand but leaves sellable/unassigned stock and cannot be used elsewhere.

`OWE-05` **Must:** New receipts do not automatically reserve stock for old We Owe obligations. The Kernel prioritizes reservation against other demand. Any owed quantity without reserved stock remains uncovered.

`OWE-06` **Must:** We Owe reports use open/closed status and show buyer, event, product, quantity, value, covered quantity, and uncovered quantity. Closed obligations retain their fulfillment/cancellation details in audit history without adding a separate report-status category. Inventory reports include covered and uncovered We Owe quantities per product.

`OWE-07` **Must:** Fulfilling reserved We Owe stock decrements Kernel physical on hand and sold product in our possession together. External/Council fulfillment closes the supplied quantity without changing Kernel stock. Every reserved quantity must be fulfilled or explicitly released before the obligation can be fully resolved.

`OWE-08` **Must:** Post-finalization customer returns, exchanges, refunds, and sale corrections are handled by reopening and correcting the original event, not by separate return transactions.

`OWE-09` **Must:** A We Owe obligation supports partial fulfillment. Each fulfillment records quantity and stock source, decreases the remaining open quantity, and preserves the original obligation. The line closes only when its remaining quantity reaches zero and no unresolved reservation remains.

`OWE-10` **Must:** We Owe obligations remain Unit Admin-managed without a responsible-person/delivery-assignment field. Reports require open/closed status only; no due date, expected-delivery date, overdue view, or days-open aging is required.

## 11. Finalization, cash, returns, and reopening

### 11.1 Finalization workflow

`FIN-01` **Must:** After a Show & Sell ends, the Kernel finalizes it through one workflow that includes:

1. completing manual sale entry from any paper sheets;
2. confirming eligible participants and actual work per slot;
3. reviewing the whole-event pool and Scout split preview;
4. reviewing expected unsold event stock and confirming the actual return count;
5. reconciling expected and actual cash, including any manual expected-cash adjustment;
6. reviewing open We Owe obligations; and
7. approving the event, which finalizes Scout allocations and releases unsold event assignments.

`FIN-02` **Must:** Expected unsold stock for each product is calculated as assigned quantity minus recorded immediate-handoff sales, adjusted for any already recorded event inventory movements. The Kernel sees the expected quantity and confirms or corrects the actual physical return before approval.

`FIN-03` **Must:** If expected and actual return counts differ, the Kernel reconciles the difference and adjusts stock to the actual physical quantity. The Kernel may first correct a missed/incorrect sale when that explains the difference; otherwise the difference uses the stock-only adjustment behavior in `INV-02` and `INV-03`, including a reason. No variance-category subsystem or additional approval is required.

`FIN-04` **Must:** A physical return variance never automatically changes sales, expected cash, or Scout credit. The event closeout records expected quantity, actual returned quantity, and the reconciling stock adjustment. Council and inventory reports use the reconciled actual stock. The same rule applies to shortages and overages.

### 11.2 Cash reconciliation

`CASH-01` **Must:** Finalization calculates expected cash from sales whose snapshotted payment method is **Cash**. Other payments are not parsed for cash content.

`CASH-02` **Must:** The Kernel may manually adjust expected cash, including for an Other/split payment containing cash. The adjustment amount and reason are recorded; no cash-portion field is added to the sale.

`CASH-03` **Must:** The reconciliation shows:

- calculated expected cash;
- manual expected-cash adjustment and reason;
- adjusted expected cash;
- actual cash counted; and
- `cash discrepancy = actual cash - adjusted expected cash`.

`CASH-04` **Must:** A nonzero cash discrepancy does not block finalization, but the Kernel must enter an explanation before approval. All values and the approving Kernel are auditable.

### 11.3 Reopening

`REOPEN-01` **Must:** Any Kernel may reopen a finalized Show & Sell. Reopening suspends Scout credit as required by `SPLIT-07` and permits correction of sales, payments, participants, times, cash, We Owe, and return counts.

`REOPEN-02` **Must:** Reopening leaves previously returned stock where it is. It does not automatically reclaim stock from unit inventory, Scout custody, later events, or fulfilled sales. Inventory effects of corrections are applied only when the Kernel re-finalizes.

`REOPEN-03` **Must:** Re-finalization creates a new approved version, replaces suspended Scout allocations, and preserves the complete prior-version audit history.

## 12. Printable sales and payment help

`PRINT-01` **Must:** Generate the printable Show & Sell sales sheet in the browser for use without internet access after its data has loaded. It includes event identity, date/time, location, product names/prices, blank sale rows, product quantities, totals, the shared unit payment-method names, an Other-details area, and a We Owe indicator when enabled. No server-generated printable document is produced.

`PRINT-02` **Must:** Generate printable payment/help sheets in the browser containing the shared unit payment methods, applicable QR codes, buyer instructions, and the Other/split-payment explanation.

`PRINT-03` **Must:** Printable materials identify the Unit, Unit Campaign, and Show & Sell and display their generation timestamp so a Kernel can recognize stale prices, payment details, or QR codes.

`PRINT-04` **Must:** Paper sales are entered manually by a Kernel before finalization. The application does not queue offline sales or treat a printed sheet itself as a sale.

## 12.1 Calendar downloads and notification policy

`CAL-01` **Must:** Every successful slot signup offers a downloadable `.ics` calendar invite generated in the browser from authorized slot/event data. The invite contains a stable event UID, generation timestamp, slot start/end with correct timezone handling, Show & Sell and slot summary, short location name, optional address, and Unit/Unit Campaign context in the description. No server-generated ICS file is produced.

`CAL-02` **Must:** The ICS download is a snapshot generated on demand, not a calendar subscription or synchronization channel. Cancelling a signup or Show & Sell does not update an already downloaded file. No automatic calendar email is sent.

`NOTIFY-01` **Must:** No automatic notifications are required for launch for signups, reminders, event changes, allocation reductions, finalization, reopening, We Owe, or With Scout balances. Relevant information remains visible in application screens, reports, and audit history. Unit access invitations continue to use manually shared codes under `UNIT-13`.

## 13. Reporting

`RPT-00` **Must:** All reporting across KernelWorx happens in the browser. GraphQL provides authorized domain data; the browser performs report assembly, aggregation, rendering, CSV/XLSX generation, printable-document generation, and ICS generation. No report-generation Lambda, S3 report output, pre-signed report-download URL, server-generated printable document, or server-generated ICS file is permitted. Existing server-generated campaign/unit reports migrate to this rule according to `docs/BROWSER_REPORTING_ARCHITECTURE.md`.

### 13.1 Show & Sell and Scout reports

`RPT-01` **Must:** Sales by Show & Sell include event date/time/location, product quantities, immediate and We Owe sales, payment-method totals, participants/work time, split method, pending or approved Scout allocations, inventory assigned/sold/returned, cash reconciliation, and status.

`RPT-02` **Must:** Scout summaries and unit seller reports show individual sales, approved Show & Sell allocations, pending Show & Sell allocations separately, and combined approved total sales.

`RPT-03` **Must:** Show & Sell product quantities remain event/unit-level. Scout allocations are monetary only and do not imply Scout-held inventory.

### 13.2 Inventory and custody report

`RPT-04` **Must:** At any point, a Kernel may run a product-level inventory list showing:

- Kernel physical on hand;
- sold product in our possession;
- sellable Kernel stock;
- assigned to open Show & Sells;
- unassigned Kernel stock;
- assignment overage;
- With Scout in aggregate and per Scout;
- total unit-owned undelivered stock;
- covered and uncovered We Owe; and
- Council on order, separately.

### 13.3 Council Needs: actual demand only

`RPT-05` **Must:** Council demand includes unfulfilled individual-sale quantities and uncovered We Owe quantities. Fulfilled individual sales, covered We Owe, and future hypothetical sales do not create demand.

`RPT-06` **Must:** Show both actual stock-coverage calculations:

`Physical-stock Council need = max(0, actual demand - sellable Kernel stock)`

`After-assignments Council need = max(0, actual demand - unassigned Kernel stock)`

where `actual demand = unfulfilled individual quantity + uncovered We Owe quantity`.

`RPT-07` **Must:** A Unit-level preference, managed by any Unit Admin, selects which calculation is the primary summary across the Unit's campaigns. Both values remain visible with explicit labels so the preference cannot hide the alternative.

Example: for ten units of actual individual-sale demand, six sellable Kernel units, four assigned to a future Show & Sell, and therefore two unassigned, the report shows physical-stock need **4** and after-assignments need **8**.

`RPT-08` **Must:** Council on-order quantities appear beside both needs but never reduce either value automatically. The report does not include projected future Show & Sell sales or assignment overage as demand.

`RPT-09` **Must:** With Scout stock does not count as available supply in either calculation. It is shown separately because it is unsold but already issued for future individual sales.

## 14. Logical records and integrity constraints

The physical persistence design remains open, but confirmed workflows require these logical records:

| Record | Purpose |
| --- | --- |
| Unit | Standalone `unitId`, descriptive metadata, and ownership root for access, settings, payment methods, and Unit Campaigns |
| Unit access grant | Links an Account to the single Unit Admin (Unit Kernel) role; supports multiple equal grants and leadership changes |
| Unit Campaign | Stable `unitId` relationship joining a sales season/catalog to its Unit |
| Unit Campaign membership | Proves Scout Campaign eligibility |
| Unit payment method | Unit-owned shared named method, optional QR reference, active state, and built-in Cash/Check/Other behavior |
| Unit settings | Unit-owned split default and primary Council-need preference |
| Inventory balance | Kernel physical, reserved, and derived available quantities |
| Scout custody balance | Unsold With Scout quantity per Scout/product |
| Inventory movement | Receipts, adjustments, issues, returns, sales, reservations, fulfillments, releases, and reversals |
| Council on-order balance | Product ordered but not received, displayed separately |
| Show & Sell | Schedule, location, state, split override, We Owe setting, and approved version |
| Event allocation | Assigned, sold, remaining, returned, and automatically reduced quantities |
| Slot and signup | Variable shift, capacity, and Scout commitment |
| Confirmed work | Kernel-confirmed participation and actual minutes per slot |
| Show & Sell sale | Event transaction, one snapshotted payment method, and Other details |
| Scout allocation | Pending/approved/suspended monetary share and finalization version |
| We Owe obligation | Buyer/product obligation and covered/uncovered/fulfilled state |
| Cash reconciliation | Calculated/adjusted/actual cash, discrepancy, reasons, and approval |
| Finalization audit | Approval, reopening, corrections, and approved versions |
| Individual fulfillment | Fulfilled quantity and source for Council demand |

`DATA-01` **Constraint:** Monetary calculations use integer cents; product quantities use integers. Multi-record writes for sales, custody, fulfillment, reservation, finalization, and reopening must be atomic and retry-safe.

`DATA-02` **Constraint:** A sale and its inventory effects cannot be applied twice. In particular, a door-to-door sale consumes With Scout stock, not both With Scout and Kernel stock.

`DATA-03` **Constraint:** Finalized reports derive from the approved event version. Reopened-event credit is excluded from approved totals until a new version is approved.

## 15. Acceptance criteria for confirmed behavior

### 15.1 Inventory and Scout custody

- **AC-01 — Stock-only adjustment:** A Kernel can increase or decrease stock with a reason without changing any sale, payment, trade, fulfillment, or Scout-credit record.
- **AC-02 — One unit equals one sale:** Every inventory and sale quantity uses the same integer product unit; no case or conversion field exists.
- **AC-03 — Issue is not a sale:** Issuing three units to a Scout decreases available Kernel stock and increases With Scout by three, while total unit-owned stock, sales, fulfillment, and Scout credit remain unchanged.
- **AC-04 — Door-to-door consumption:** Recording a two-unit individual sale with two or more With Scout consumes two custody units and fulfills two sale units without changing Kernel stock.
- **AC-05 — Insufficient custody does not block:** A three-unit individual sale with only one With Scout is accepted, consumes one, fulfills one, and leaves two unfulfilled.
- **AC-06 — Tracked quick return:** Entering two of X and three of Y and using Return to Unit stock updates both products and the Scout balance in one action.
- **AC-07 — Kernel priority:** Newly received stock remains uncommitted until the Kernel chooses among fulfillment, issue, We Owe reservation, or event allocation, except for the explicit later-event reconciliation rule.

### 15.2 Events, slots, and allocation

- **AC-08 — Overlap allowed:** Two Show & Sells may overlap when their allocations satisfy concurrent stock limits.
- **AC-09 — Concurrent over-assignment blocked:** Four boxes cannot support three boxes assigned to each of two overlapping events.
- **AC-10 — Sequential warning:** Four boxes allow three assigned to morning and three to afternoon with a visible, keyboard/touch-accessible four-box warning.
- **AC-11 — Required automatic example:** After the morning event sells two and is finalized, its afternoon allocation becomes two.
- **AC-12 — Earlier-event priority:** With two later non-overlapping events requesting three each and two remaining, the earlier becomes two and the later zero; a Kernel can adjust both.
- **AC-13 — Variable capacity slots:** A slot can last 90, 120, or 180 minutes and rejects signups above its Scout capacity.
- **AC-14 — Conflict blocking:** A Scout may take adjacent/non-overlapping slots but cannot hold overlapping commitments at the same or different Show & Sells.
- **AC-15 — Location:** A short location name is required; the address is optional.

### 15.3 Sales, payment, and splitting

- **AC-16 — Kernel-only sale entry:** A parent/Scout Account cannot submit a Show & Sell sale even with WRITE access to a participating Scout.
- **AC-17 — Unavailable with We Owe off:** The unavailable quantity cannot be submitted as an immediate event sale and cannot make event stock negative; an individual Campaign sale remains allowed.
- **AC-18 — Shared payment methods:** A Unit payment-method change applies to every Unit Campaign and Show & Sell without any campaign/event allowlist, while existing sale snapshots remain unchanged.
- **AC-19 — Other details:** A sale can record Other with “Apple Pay; Kernel reimbursed unit by Venmo” and preserves that exact detail in reports.
- **AC-20 — Split-payment guidance:** The UI tooltip directs split payments to Other with every method and amount; the sale still has one method.
- **AC-21 — Shared and printable QR:** A named unit method's QR can be displayed at every Show & Sell and included in printable payment help.
- **AC-22 — Whole-event pool:** Morning sales of $300 and afternoon sales of $100 produce one $400 split pool, not separate slot pools.
- **AC-23 — Equal split:** Four eligible confirmed workers equally share the whole-event pool regardless of slots worked.
- **AC-24 — Time-worked split:** In a $60 event with one three-hour Scout and three one-hour Scouts, allocations are $30, $10, $10, and $10.
- **AC-25 — No Scout inventory from split:** A Show & Sell monetary allocation creates no With Scout or other Scout-inventory movement.

### 15.4 Finalization, cash, and credit

- **AC-26 — Pending credit:** No Show & Sell allocation enters approved Scout totals before Kernel finalization, including after the event end time passes.
- **AC-27 — Finalized credit:** Finalization approves the allocations and adds them once to Scout totals, including finalized open We Owe sales.
- **AC-28 — Reopen suspends:** Reopening removes that event's credit from current approved totals until re-finalization; the prior approved version remains auditable.
- **AC-29 — Reopen leaves stock:** Returned stock is not reclaimed from wherever it went when the event is reopened.
- **AC-30 — Expected return confirmation:** Finalization displays assigned-minus-sales expected returns and requires the Kernel to confirm or correct actual counts.
- **AC-31 — Manual cash adjustment:** Calculated expected cash ignores Other notes; the Kernel can enter an expected-cash adjustment and reason for split payments.
- **AC-32 — Cash discrepancy allowed:** A nonzero actual-versus-adjusted-expected discrepancy can be finalized only with an explanation and is preserved in the event report.

### 15.5 We Owe, print, and Council reporting

- **AC-33 — We Owe default:** Every new Show & Sell starts with We Owe disabled.
- **AC-34 — Kernel-controlled reservation:** New stock does not automatically become reserved for an old We Owe. Kernel reservation moves it to sold product in our possession and makes it unavailable elsewhere.
- **AC-35 — Printable fallback:** The sales sheet supports later manual entry and the payment/help sheet includes applicable unit QR codes and Other instructions.
- **AC-36 — Both Council calculations:** The ten-demand/six-stock/four-assigned example shows needs of four and eight, with the unit preference selecting only the primary presentation.
- **AC-37 — Actual demand only:** Fulfilled sales, covered We Owe, future event sales, and assignment overage do not add to Council demand.
- **AC-38 — On-order separate:** Council on-order quantities are visible and do not reduce either calculated need.
- **AC-39 — Custody excluded:** With Scout quantities appear separately and do not reduce either Council need as available supply.
- **AC-40 — Standalone Unit access:** One Unit Admin can add another, both have identical full permissions whether called Unit Admin or Unit Kernel, an Account can administer multiple Units, and the final remaining Unit access grant cannot be removed.
- **AC-41 — Stable Unit relationships:** Changing a Unit's number, city, or other descriptive metadata does not change its `unitId`, access grants, Unit Campaign relationships, payment methods, or authorization.
- **AC-42 — Unit creation:** Any authenticated Account can create a Unit with type, number, city, state, and optional name; the creator becomes its initial Unit Admin.
- **AC-43 — Unit invite parity:** A Unit Admin can generate a 16-character, single-use, 14-day invite; another authenticated Account can redeem it for full equal access; and admins can revoke unused invites and redeemed grants.
- **AC-44 — Geographic identity:** Identical unit numbers in different geographic locations remain distinct Units, while an exact type/number/city/state match requires duplicate confirmation and never triggers an automatic merge.
- **AC-45 — No legacy admin claim:** Launch includes no production-data migration or self-service Unit claiming path that could grant administrative access based only on legacy metadata.
- **AC-46 — Return reconciliation:** With ten assigned, six recorded sold, four expected, and three actually returned, the Kernel can reconcile the missing box with a reasoned stock-only adjustment and finalize without any automatic sale, cash, or Scout-credit change.
- **AC-47 — Independent campaign deactivation:** A Kernel can deactivate a campaign with leftover stock, With Scout balances, open obligations, or on-order quantities, and none of those balances changes automatically or moves to another campaign.
- **AC-48 — Gift stock:** A reasoned stock adjustment can record popcorn given away without creating a sale, payment, fulfillment, or Scout credit.
- **AC-49 — Code-based roster join:** Creating a Scout Campaign from the Unit Campaign code immediately establishes signup eligibility without a separate approval.
- **AC-50 — Membership removal preserves records:** Removing a Scout blocks new signups but leaves existing signups, work, pending allocations, and finalized history unchanged for Kernel review.
- **AC-51 — Pre-start cancellation:** A Unit Admin can cancel a future Show & Sell, releasing allocations/signups while preserving audit history; cancellation is rejected at or after start.
- **AC-52 — Cancel and recreate instead of reschedule:** No reschedule mutation exists; changing a future event's time requires cancellation and a new event with no automatic signup/allocation transfer.
- **AC-53 — Minimal We Owe buyer data:** A We Owe can be created with buyer name and product/quantity without phone or email, and it has no delivery assignee or due date.
- **AC-54 — Partial We Owe fulfillment:** Multiple partial fulfillments reduce the remaining quantity and close the obligation only when nothing remains owed or reserved.
- **AC-55 — Kernel-assigned rounding cents:** A $100 equal split among three Scouts begins at $33.33 each with one unassigned cent; finalization is blocked until the Kernel assigns that cent, after which allocations total exactly $100.
- **AC-56 — ICS without automatic notifications:** A successful signup offers a standards-compliant ICS download with the slot time/location, while no automatic email, in-app notification, or later calendar update is sent.

## 16. Decision-resolution log

All previously identified open decisions are resolved:

| Former item | Resolution | Authoritative requirements |
| --- | --- | --- |
| `OPEN-01` Physical return variance | Kernel reviews and reconciles to actual stock with a reasoned stock-only adjustment; no inferred sale/cash/credit or variance-category subsystem | `FIN-03`, `FIN-04` |
| `OPEN-02` Cent rounding | Shares round down; Kernel assigns every leftover cent before finalization | `SPLIT-10` |
| `OPEN-03` Campaign close/rollover | Independent campaigns; no forced cleanup, transfer, or product mapping; deactivation changes no balances | `CYCLE-01`–`CYCLE-03` |
| `OPEN-04` Roster lifecycle | Campaign-code join; membership removal blocks new signups but changes no existing records automatically | `ROSTER-01`–`ROSTER-04` |
| `OPEN-05` Cancellation/rescheduling | Unit Admin cancellation before start only; cancel and recreate instead of rescheduling | `SSE-05`–`SSE-07` |
| `OPEN-06` Historical fulfillment migration | No production users/data migration burden; relationships are native at launch | `UNIT-16` |
| `OPEN-07` We Owe operations | Buyer name only, optional contact details, partial fulfillment, no delivery assignment/due dates/aging | `OWE-02`, `OWE-09`, `OWE-10` |
| `OPEN-08` Notifications | No automatic notifications; downloadable per-slot ICS calendar invites | `CAL-01`, `CAL-02`, `NOTIFY-01` |
| `OPEN-09` Unit bootstrap/migration | Any Account creates; creator admin; profile-style invite codes; geographic duplicate handling; no production migration | `UNIT-11`–`UNIT-16` |

## 17. Delivery gate

All confirmed Must requirements are release gates. No known `OPEN` product decisions remain. Historical production-data migration is explicitly out of scope under `UNIT-16` because there are no production users.

The next phase is technical design and implementation planning: map these requirements to the GraphQL schema, persistence model, resolver authorization, Unit/Unit Campaign migration of the current pre-production model, printable/ICS generation, and test slices without weakening the acceptance criteria. Any newly discovered product behavior must be added explicitly rather than resolved by implementation convention.
