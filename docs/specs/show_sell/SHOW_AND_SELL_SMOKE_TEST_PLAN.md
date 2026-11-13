# Show & Sell and inventory smoke test plan

**Status:** Pre-implementation acceptance walkthroughs  
**Last updated:** 2026-10-29  
**Authoritative requirements:** [Show & Sell and inventory specification](SHOW_AND_SELL_INVENTORY_SPECIFICATION.md)  
**Technical data model:** [Show & Sell data model](SHOW_AND_SELL_DATA_MODEL.md)  
**Reporting architecture:** [Browser-only reporting and document generation](BROWSER_REPORTING_ARCHITECTURE.md)  
**Target environments:** Ephemeral PR stack preferred; shared dev only with the designated test Accounts and complete cleanup

## 1. Purpose and execution rules

These scenarios are human-executable smoke tests now and the source for future Playwright/browser and live-GraphQL automation. They use concrete people, Scouts, products, quantities, prices, payment details, and expected results so implementers do not need to invent test data.

- Unless a step explicitly says **API** or **fixture**, perform the action through the application UI.
- A hidden button is never sufficient evidence of authorization. Where a scenario includes an API denial, execute the same mutation as the named unprivileged Account and expect `FORBIDDEN` or the specified not-found behavior.
- Reload after important mutations and verify the persisted result, not only a transient success toast.
- Use fresh browser contexts for different Accounts. Do not request two existing E2E identity fixtures against the same Playwright `page` simultaneously.
- Every scenario must pass its assertions before cleanup. A scenario is **blocked**, not passed or waived, when a required fixture capability from Section 4 is absent.
- Do not run the destructive/full workflow against production under this plan. Production-safe smoke scope requires a separate explicit decision after the feature and cleanup exist.
- Save the environment, `RUN_ID`, `LANE_ID`, `DATA_ID`, scenario ID, relevant screenshots, downloaded artifacts, and cleanup result as evidence.

### 1.1 Test layers

| Layer | Purpose |
| --- | --- |
| Browser walkthrough | Unit setup, roster, inventory, event, signup, sale, finalization, reports, print, and ICS golden paths |
| Live GraphQL/API | Authorization denial, capacity/conflict enforcement, stock races, exact balances, and any operation that must remain safe without the UI |
| Artifact inspection | Parse ICS and printable sales/payment artifacts; do not merely assert that a Download button exists |
| Unit/component/integration tests outside this plan | Exhaustive arithmetic, rounding combinations, concurrency permutations, validation boundaries, and report reconciliation |

### 1.2 Concurrent lane model

The scenarios are designed to run concurrently, not as one ordered 45-minute workflow. Each concurrent worker acquires a **lane** containing four dedicated Accounts and isolated application data.

- Start with **4 lanes/workers**. Make the worker count configurable and increase only after observing browser CPU/memory, Cognito authentication throttling, AppSync/DynamoDB latency, and cleanup reliability. Parallelism is not assumed to produce linear speedup.
- A lane runs only one scenario at a time. A scenario may use multiple sequential identities within that lane, but no other scenario may use those identities or that lane's Units.
- Every scenario creates its own Units, Unit Campaigns, catalogs, payment methods, preferences, Scouts, and events. Unit-level payment renames and Council preferences therefore cannot race another scenario.
- Scenarios have no order dependency. `SS-SM-09` arranges its own finalized event rather than depending on `SS-SM-08`.
- Scenario-scoped `finally` cleanup is mandatory before a lane returns to the pool. There is no global pre-suite or post-suite cleanup that can delete another worker's active data.
- A run-scoped janitor may remove only expired resources from interrupted runs. It must not infer safety from a shared Account alone or delete a fresh/active `RUN_ID`.
- Full concurrent runs target ephemeral/dev only. Production remains a separate, bounded smoke decision.
- The current suite's global cleanup, shared users, and ordered module-state tests must not simply be run under `pytest -n`. Add a lane-aware scheduler/fixture first; `pytest-xdist` or an equivalent runner is a fixture acceptance dependency, not an assumption about the current dependencies.

## 2. Synthetic identities

### 2.1 Accounts and personas

Each lane has four dedicated, pre-provisioned, pre-confirmed Cognito users. `NN` is the zero-padded lane number (`01` through the configured maximum). Passwords come only from environment/secrets management and are never written into this document or test source.

| Shorthand | Dev username | Ephemeral username | Display name | Role in these tests |
| --- | --- | --- | --- | --- |
| **Alex** | `ss-lane-NN-alex@example.com` | `ss-<run-id>-lane-NN-alex@kernelworx.test` | `Alex Kernel LNN` | Creates the lane's Pack 3149 and becomes its initial Unit Admin. This lane user is deliberately not a global application ADMIN. |
| **Casey** | `ss-lane-NN-casey@example.com` | `ss-<run-id>-lane-NN-casey@kernelworx.test` | `Casey Kernel LNN` | Redeems the lane Alex's Unit invite and becomes a second equal Unit Admin. |
| **Morgan** | `ss-lane-NN-morgan@example.com` | `ss-<run-id>-lane-NN-morgan@kernelworx.test` | `Morgan Parent LNN` | Owns the lane's synthetic Scouts but has no Pack 3149 Unit Admin grant. |
| **Riley** | `ss-lane-NN-riley@example.com` | `ss-<run-id>-lane-NN-riley@kernelworx.test` | `Riley Outsider LNN` | Has no Pack 3149 access; creates and remains sole Unit Admin of the lane's Troop 7150. |

For the single assertion that global application ADMIN does not confer Unit access, `SS-SM-01` additionally uses the existing Owner (`owner@example.com` / `<run-id>-owner@kernelworx.test`) only to attempt access to the lane Riley's Troop 7150. That shared global-admin Account performs no setup or successful mutation and is never a general lane fixture.

`FIX-AC-01` **Fixture acceptance criterion:** Test setup must provision/authenticate four dedicated users per lane, establish their display names, and keep their credentials in environment/secrets management. Lane users must not be global application ADMIN users. Dev may use a persistent lane pool; ephemeral runs should provision a run-scoped pool. Cognito provisioning must complete before browser workers start to avoid authentication/setup bottlenecks.

### 2.2 Scouts

All five SellerProfiles are owned by the current scenario lane's Morgan. Append the `DATA_ID` described below to every displayed name to prevent collisions across lanes, scenarios, and retries.

| Shorthand | Exact synthetic Scout name | Unit Campaign membership |
| --- | --- | --- |
| **Avery** | `Avery Scout <DATA_ID>` | Joined through the Unit Campaign code |
| **Blake** | `Blake Scout <DATA_ID>` | Joined through the Unit Campaign code |
| **Charlie** | `Charlie Scout <DATA_ID>` | Joined through the Unit Campaign code |
| **Devon** | `Devon Scout <DATA_ID>` | Joined through the Unit Campaign code |
| **Emery** | `Emery Scout <DATA_ID>` | Deliberately independent/unjoined |

`FIX-AC-02` **Fixture acceptance criterion:** Setup must create these five named SellerProfiles for Morgan and a separate Scout Campaign for each. Avery, Blake, Charlie, and Devon must join the scenario Unit Campaign through its join code. Emery must remain unjoined. Fixed shared Scout records must not be reused across runs.

### 2.3 Buyers

Buyers do not have application Accounts.

| Buyer name | Used for |
| --- | --- |
| `Nora Cash` | Cash immediate-handoff sale |
| `Quinn WeOwe` | Mixed immediate/We Owe sale with Other payment details and no contact information |
| `Sam Split` | Other payment containing a cash/Venmo split |
| `Taylor Door` | Individual door-to-door sales consuming With Scout stock |
| `Council Customer` | Unfulfilled individual demand in Council Needs |

## 3. Deterministic synthetic data

### 3.1 Naming, time, and evidence

- `RUN_ID`: Identifier for the entire test run, using UTC epoch seconds plus a short UUID, for example `1735420800-a1b2c3`.
- `LANE_ID`: Zero-padded lane identifier such as `L01`. It is bound to both the worker and the four `lane-01` Accounts.
- `SCENARIO_ID`: Stable identifier such as `SS-SM-05`.
- `ATTEMPT_ID`: A short UUID generated fresh for every scenario attempt, including every retry.
- `DATA_ID`: Unique scenario-attempt suffix formed as `<RUN_ID>-<SCENARIO_ID>-<LANE_ID>-<ATTEMPT_ID>`. The attempt UUID prevents collision with leftover entities or delayed cleanup from an earlier attempt in the same run/lane.
- `T0`: Scenario setup time. Compute event times relative to `T0`; do not hardcode calendar dates in automation.
- Unit timezone: `America/Denver` for display and ICS validation. Persist timestamps unambiguously.
- Every Unit, Unit Campaign, catalog, SellerProfile, Show & Sell, and location display name includes `DATA_ID` unless this plan explicitly tests an exact metadata duplicate.
- In expected tables, names are shown without the suffix for readability; the actual assertion uses the full suffixed name.

`FIX-AC-03` **Fixture acceptance criterion:** Setup must provide `RUN_ID`, `LANE_ID`, `DATA_ID`, `T0`, Unit timezone, and named-entity helpers to every scenario. A lane lease must be exclusive, and data names must remain unique when scenarios run concurrently or a failed scenario is retried.

### 3.2 Units

| Shorthand | Type | Number | City | State | Optional display name | Creator |
| --- | --- | --- | ---: | --- | --- | --- |
| **Pack 3149** | Pack | 3149 | `Denver-<DATA_ID>` | CO | `Smoke Pack 3149 <DATA_ID>` | Alex |
| **Duplicate Pack 3149** | Pack | 3149 | `Denver-<DATA_ID>` | CO | `Duplicate Pack 3149 <DATA_ID>` | Morgan |
| **Denver Pack 149** | Pack | 149 | `Denver-<DATA_ID>` | CO | `Denver Pack 149 <DATA_ID>` | Alex |
| **Boulder Pack 149** | Pack | 149 | `Boulder-<DATA_ID>` | CO | `Boulder Pack 149 <DATA_ID>` | Alex |
| **Troop 7150** | Troop | 7150 | `Aurora-<DATA_ID>` | CO | `Smoke Troop 7150 <DATA_ID>` | Riley |

Every scenario, including `SS-SM-01`, uses attempt-unique geographic metadata so another lane/run/retry cannot trigger an unexpected duplicate warning. `SS-SM-01` step 11 deliberately reuses the exact same attempt-unique type/number/city/state for its two Pack 3149 creations, while the Pack 149 pair uses two different attempt-unique geographies. The `DATA_ID` attempt UUID makes this metadata unique without changing stable Unit-ID or geography assertions.

### 3.3 Unit Campaign and catalog

Primary names:

- Unit Campaign: `Fall Popcorn 2026 <DATA_ID>`
- Catalog: `Smoke Popcorn Catalog <DATA_ID>`
- Additional isolated Unit Campaigns: `Stock Admin <DATA_ID>`, `Door to Door <DATA_ID>`, `Sales Desk <DATA_ID>`, `Split Math <DATA_ID>`, `Council Planning <DATA_ID>`, and `Dirty Campaign <DATA_ID>`.

Products use the same catalog identity within a scenario. No case quantities or conversions are permitted.

| Product | Price per one inventory/sale unit | Primary use |
| --- | ---: | --- |
| `Caramel Popcorn <DATA_ID>` | `$30.00` | Four-box allocation and $60 time-worked split |
| `Butter Popcorn <DATA_ID>` | `$20.00` | Custody, $100 whole-pool component, rounding, Council Needs |
| `Chocolate Popcorn <DATA_ID>` | `$25.00` | $300 whole-pool component and We Owe sales |

`FIX-AC-04` **Fixture acceptance criterion:** Setup must create the Unit Campaigns, catalog, products/prices, and Scout Campaign joins using public application operations or documented test fixtures. A fixture may arrange state but must not bypass the rule being asserted in the scenario.

### 3.4 Locations

| Short location name | Optional address | Used for |
| --- | --- | --- |
| `Kroger on Monroe <DATA_ID>` | `100 Monroe St, Denver, CO` | Morning/afternoon allocation and finalization |
| `Library on Main <DATA_ID>` | Omitted | Variable slots, optional address, and ICS |
| `Church on Elm <DATA_ID>` | `200 Elm St, Denver, CO` | Sales, Other payments, We Owe, cash reconciliation |
| `School on Pine <DATA_ID>` | `500 Pine St, Denver, CO` | Whole-event pool and rounding |
| `Park Pavilion <DATA_ID>` | Omitted | Cancel and recreate |
| `Council Future Booth <DATA_ID>` | Omitted | Assigned stock in Council Needs |

### 3.5 Fixture timing and state control

Browser tests cannot wait for an event to start/end and cannot sign up for an already ended event through the normal flow. The test harness therefore needs an explicit, test-only arrangement capability.

`FIX-AC-05` **Fixture acceptance criterion:** A fixture must be able to arrange valid past or future Show & Sells and their signups/work records relative to `T0`, while leaving the action under test to the UI/API. It must enforce normal stock, membership, slot, and timestamp rules. There must be no production time-override endpoint.

Required states:

- Past events for sale entry/finalization: start/end on `T0 - 1 day`.
- Future events for signup/cancellation: start on `T0 + 7 days`.
- An event that has already started for cancellation denial: start on `T0 - 1 hour`, end on `T0 + 2 hours`.
- Invites expiring in the past for expiry integration coverage; do not wait 14 days in a smoke test.

### 3.6 Inspection, artifacts, and cleanup capabilities

`FIX-AC-06` **Fixture acceptance criterion:** Each persona must have an authenticated API client for negative authorization tests. UI visibility alone is not accepted as proof.

`FIX-AC-07` **Fixture acceptance criterion:** Tests must be able to download and parse ICS files and printable sales/payment artifacts. The existing `tests/e2e/fixtures/payment_qr.png` may be used for the Unit QR upload. Print output may be print-ready HTML or PDF, but its content and QR references must be inspectable.

`FIX-AC-08` **Fixture acceptance criterion:** Tests must have a supported way to inspect balances, approved/pending allocations, event versions, and audit results through the application UI or API. Direct database mutation is not an acceptable substitute for workflow assertions.

`FIX-AC-09` **Fixture acceptance criterion:** Before these tests can run unattended, cleanup must cover all new synthetic entities and artifacts: We Owe fulfillments/reservations, cash/finalization versions, Scout allocations, sales, signups/slots/events, inventory movements/custody/on-order records, Unit Campaign membership, orders/Campaigns, Unit payment QR objects/methods, Unit invites/grants/Units, and SellerProfiles. Persistent lane Cognito personas remain. Cleanup must be scoped by `DATA_ID` and the lane's Account/Unit IDs, must not delete another active lane's data, and must not delete audit evidence before the scenario has asserted it. It must include a test-only Unit cascade that deletes a Unit and its grants together rather than violating the product's final-grant invariant through an ordinary revocation call.

`FIX-AC-10` **Fixture acceptance criterion:** The test runner must support bounded parallel workers and exclusive lane leases. The existing global session cleanup and shared-Account fixtures are not compatible with this model and must be replaced or bypassed deliberately for lane-aware suites. A scenario may return its lane only after its own cleanup completes successfully. If cleanup fails, that lane remains leased and quarantined for the rest of the run; a retry requires a different clean lane or waits for complete deletion. Merely scheduling janitor work never makes a lane reusable.

## 4. Scenario index and traceability

| Scenario | Workflow | Primary requirements |
| --- | --- | --- |
| `SS-SM-01` | Standalone Units, equal admins, invites, duplicate geography, access isolation | `UNIT-01`–`UNIT-16` |
| `SS-SM-02` | Unit Campaign, catalog, roster join/removal | `UNIT-05`–`UNIT-09`, `ROSTER-01`–`ROSTER-04` |
| `SS-SM-03` | Shared payment methods, QR, receipts, stock-only adjustments | `INV-01`–`INV-04`, `PAY-01`–`PAY-03`, `CYCLE-03` |
| `SS-SM-04` | With Scout issue, door-to-door sale, quick return | `CUST-01`–`CUST-07` |
| `SS-SM-05` | Four-box allocation, time-worked split, finalization, automatic afternoon reduction | `ALLOC-01`–`ALLOC-08`, `SPLIT-01`–`SPLIT-09`, `FIN-01`–`FIN-04`, `CASH-01`–`CASH-04` |
| `SS-SM-06` | Variable slots, capacity, conflicts, eligibility, ICS, no notifications | `SLOT-01`–`SLOT-05`, `CAL-01`–`CAL-02`, `NOTIFY-01` |
| `SS-SM-07` | Kernel-only sales, Other payments, We Owe, print, cash, partial fulfillment | `SALE-01`–`SALE-06`, `PAY-04`–`PAY-07`, `OWE-01`–`OWE-10`, `PRINT-01`–`PRINT-04` |
| `SS-SM-08` | Whole-event equal split, payment snapshot, Kernel-assigned rounding cents | `SPLIT-02`–`SPLIT-10`, `PAY-06` |
| `SS-SM-09` | Reopen, suspend credit, change rounding assignment, re-finalize | `SPLIT-07`, `SPLIT-10`, `REOPEN-01`–`REOPEN-03` |
| `SS-SM-10` | Inventory list, both Council Needs, on-order, fulfillment | `RPT-04`–`RPT-09`, `CUST-05` |
| `SS-SM-11` | Pre-start cancellation, cancel/recreate, independent dirty campaign | `SSE-05`–`SSE-07`, `CYCLE-01`–`CYCLE-03` |

## 5. Smoke walkthroughs

### SS-SM-01 — Standalone Units and equal Unit Admins

**Actors:** Alex, Casey, Morgan, Riley  
**Starting state:** No scenario Units exist.

| Step | Actor/action | Expected result |
| ---: | --- | --- |
| 1 | Alex creates Pack 3149 with the required metadata and optional display name. | A stable `unitId` is returned; Alex is the initial Unit Admin (Unit Kernel). |
| 2 | Alex edits only the display name and then the city back/forth. | `unitId`, access grants, and relationships do not change. Authorization continues to work. |
| 3 | Alex generates a Unit Admin invite for Casey. | The code is 16 characters and has a 14-day expiry. There is no READ/WRITE selection. |
| 4 | Casey redeems the code in a fresh browser context. | Casey receives the same full Unit Admin grant; the code is consumed. |
| 5 | Morgan attempts to redeem the same code. | Redemption fails because the code is single-use; Morgan receives no grant. |
| 6 | Casey adds a Unit-level setting/payment method and creates a second invite, then revokes it unused. | Casey can perform every Unit Admin operation. The revoked unused code cannot be redeemed by Morgan. |
| 7 | Riley attempts to read Pack 3149 or mutate its settings through the UI/API. | Riley receives no data and `FORBIDDEN`/not-found behavior; no hidden-information leak occurs. |
| 8 | Riley creates Troop 7150. | Riley is its sole Unit Admin. |
| 9 | The existing global-admin Owner, who has no Troop 7150 grant, attempts to administer it through the API. | Access is denied. Global Admin does not imply Unit Admin. Lane Alex remains a non-global-admin persona. |
| 10 | Riley attempts to revoke their own final Troop 7150 grant through the direct revocation API. No self-removal UI is required. | The operation is rejected because a Unit must retain at least one grant. |
| 11 | Morgan creates Duplicate Pack 3149 with the same type/number/city/state and confirms the warning. | Creation is allowed after explicit duplicate confirmation; no automatic merge occurs and a different `unitId` is issued. |
| 12 | Alex creates Denver Pack 149 and Boulder Pack 149. | Both are created without a unit-number-only collision. Geography distinguishes the Units. |

**Evidence:** Unit IDs, invite code length/expiry (do not retain a live code in evidence), cross-Unit denial responses, duplicate warning screenshot.

### SS-SM-02 — Unit Campaign and Scout roster

**Actors:** Alex, Morgan, Riley  
**Starting state:** Pack 3149 exists with Alex and Casey as admins.

| Step | Actor/action | Expected result |
| ---: | --- | --- |
| 1 | Alex creates `Fall Popcorn 2026 <DATA_ID>` under Pack 3149 and selects the Smoke Popcorn Catalog with the three products/prices from Section 3. | The Unit Campaign references Pack 3149's `unitId`; products use stable IDs and one unit equals one sale unit. |
| 2 | Alex obtains the Unit Campaign join code. | A shareable code exists; it is not a SellerProfile Share. |
| 3 | Morgan creates the five SellerProfiles from Section 2.2. | All five are owned by Morgan and have the exact suffixed names. |
| 4 | Morgan creates Scout Campaigns for Avery, Blake, Charlie, and Devon using the join code. | Each Campaign joins the Unit Campaign immediately without separate approval and its Scout becomes signup-eligible. |
| 5 | Morgan creates Emery's Campaign without the join code. | Emery remains ineligible even with matching unit metadata. |
| 6 | Riley attempts to sign Avery up through the API. | Riley is denied; no SellerProfile Owner/WRITE or Unit access exists. |
| 7 | Fixture arranges an existing future signup and unfinalized work record for Blake. | The records are visible before membership removal. |
| 8 | Alex removes Blake's Unit Campaign membership. | New signups for Blake are blocked, but the arranged signup/work and all finalized history remain unchanged. |
| 9 | Morgan attempts a new signup for Blake and Emery. | Both are rejected as ineligible; existing records for Blake are still present for Kernel review. |
| 10 | Alex reviews Blake's unfinalized event and chooses whether to retain or correct the work before finalization. | No automatic recalculation or deletion occurs merely because membership was removed. |

**Evidence:** Roster before/after, join-code membership records, Emery denial, Blake's preserved signup/work.

### SS-SM-03 — Unit payment methods and stock-only adjustments

**Actors:** Alex, Casey  
**Starting state:** Pack 3149 and at least two Unit Campaigns exist.

| Step | Actor/action | Expected result |
| ---: | --- | --- |
| 1 | Alex opens Unit payment methods. | Built-in Cash, Check, and Other are present. |
| 2 | Alex creates named method `Venmo <DATA_ID>` and uploads `payment_qr.png`; Alex creates `Zelle <DATA_ID>` without a QR. | Both methods are saved at Unit scope. |
| 3 | Casey opens a different Unit Campaign and a Show & Sell payment/help preview. | The same Unit methods and Venmo QR appear without any campaign/event allowlist. |
| 4 | In `Stock Admin <DATA_ID>`, Alex records receipt of 2 Butter Popcorn units. | Kernel physical, sellable, and unassigned Butter stock are 2. |
| 5 | Alex applies `+2` Butter with reason `Trade with Troop 7150; money settled outside app`. | Butter becomes 4. No order, payment, reimbursement, fulfillment, or Scout credit is created. |
| 6 | Alex applies `-1` Butter with reason `Gift to outgoing volunteer`. | Butter becomes 3. No sale or payment is created. |
| 7 | Alex reloads inventory and opens its movement history. | Receipt and both adjustments show product, quantity, actor, reason, and timestamp. |
| 8 | Casey records a receipt in the same campaign. | Casey's equal Unit Admin permissions allow it; history identifies Casey rather than Alex. |

**Evidence:** Shared method list, QR preview, stock movements and absence of financial side effects.

### SS-SM-04 — With Scout custody and door-to-door sales

**Actors:** Alex, Morgan  
**Fixture:** `Door to Door <DATA_ID>`; Avery is joined; record 10 Butter Popcorn units received.

| Step | Actor/action | Expected result |
| ---: | --- | --- |
| 1 | Alex issues 4 Butter to Avery for future door-to-door sales. | Kernel physical/unassigned becomes 6; Avery With Scout becomes 4; total unit-owned remains 10; no sale or fulfillment is created. |
| 2 | Morgan records Avery's individual sale to Taylor Door for 3 Butter (`$60`). | Avery With Scout becomes 1; the sale has 3 fulfilled and 0 unfulfilled; Kernel physical remains 6. |
| 3 | Morgan records a second individual sale to Taylor Door for 2 Butter (`$40`). | The sale is accepted. The remaining 1 With Scout is consumed and 1 unit is fulfilled; 1 remains unfulfilled. With Scout is 0, never negative; Kernel physical remains 6. |
| 4 | Alex reviews Avery's individual sales and custody. | Total individual sales are `$100`; 4 units are fulfilled and 1 is unfulfilled; no Kernel-stock deduction occurred twice. |
| 5 | Alex issues 2 more Butter to Avery. | Kernel physical becomes 4; Avery With Scout becomes 2. |
| 6 | Alex enters a stated return of 1 Butter and clicks **Return to Unit stock** once. | Kernel physical/unassigned becomes 5; Avery With Scout becomes 1; total unit-owned is 6. No sale or credit is created. |
| 7 | Alex reloads the per-Scout inventory report. | Avery's one remaining With Scout unit is visible and excluded from available Council/event stock. |

**Evidence:** Balance snapshots after steps 1, 3, and 6; sale fulfilled/unfulfilled quantities.

### SS-SM-05 — Four-box workflow and time-worked finalization

**Actors:** Alex, Casey, Morgan  
**Fixture:** In `Fall Popcorn 2026 <DATA_ID>`, record exactly 4 Caramel Popcorn units. Arrange past valid signups/work for Avery, Blake, Charlie, and Devon. Unit default split is **Split by actual time worked**.

Event fixtures:

- Morning: `Kroger on Monroe <DATA_ID>`, `T0 - 1 day`, 09:00–12:00.
- Afternoon: same location, `T0 - 1 day`, 13:00–16:00.
- Overlap attempt: same location, `T0 - 1 day`, 10:00–11:00.

| Step | Actor/action | Expected result |
| ---: | --- | --- |
| 1 | Alex assigns 3 Caramel to Morning. | Assignment succeeds; Kernel physical remains 4; assigned is 3. |
| 2 | Alex assigns 3 Caramel to Afternoon. | Sequential assignment succeeds. Warning states only 4 are currently available, assigned total is 6, and assignment overage is 2. |
| 3 | Using keyboard and then touch/mobile, open the warning help. | The tooltip/help is accessible without hover-only behavior and identifies Caramel and the actual quantity 4. |
| 4 | Alex attempts to assign 3 Caramel to the overlapping event. | Server rejects the concurrent over-assignment; no partial allocation is saved. |
| 5 | Casey enters the Morning sale: 2 Caramel, `$60`, buyer `Nora Cash`, payment Cash. | Only a Unit Admin can enter it. Kernel physical becomes 2; Morning remaining allocation becomes 1; Afternoon remains 3 until Morning finalization. |
| 6 | Before finalization, Casey reviews Scout summaries. | Approved Show & Sell credit is `$0` for every Scout; the event shows pending credit only. |
| 7 | Casey confirms actual work: Avery 180 minutes, Blake 60, Charlie 60, Devon 60. | Total confirmed time is 360 minutes. |
| 8 | Casey reviews the split preview. | Whole-event pool is `$60`; pending allocations are Avery `$30`, Blake `$10`, Charlie `$10`, Devon `$10`; total is exactly `$60`. |
| 9 | Casey confirms expected/actual unsold Caramel return of 1, expected cash `$60`, actual cash `$60`, and finalizes Morning. | Morning becomes approved; unsold assignment releases; cash discrepancy is `$0`; Scout credit becomes approved. |
| 10 | Casey opens Afternoon allocation. | It has automatically reduced from 3 to 2 using earlier-event priority. The reduction is visible in audit history without an automatic notification. |
| 11 | Alex opens Scout totals for this Unit Campaign. | Avery includes `$30`, Blake/Charlie/Devon each include `$10` of approved Show & Sell sales. No Scout received the full `$60`. |
| 12 | Alex checks Caramel inventory. | Kernel physical is 2, Afternoon assigned is 2, unassigned is 0, assignment overage is 0; no With Scout movement exists. |

**Evidence:** Sequential warning, blocked overlap response, split preview, finalization report, Afternoon audit reduction.

### SS-SM-06 — Variable slots, conflicts, and ICS

**Actors:** Casey, Morgan, Riley  
**Fixture:** Casey creates future `Library on Main <DATA_ID>` for `T0 + 7 days`, 09:00–12:30, with no address.

Slots:

| Slot | Time | Capacity |
| --- | --- | ---: |
| `First Sales` | 09:00–10:30 (90 minutes) | 1 |
| `Midday` | 10:30–12:30 (120 minutes) | 1 |
| `Full Booth` | 09:00–12:00 (180 minutes) | 1 |

| Step | Actor/action | Expected result |
| ---: | --- | --- |
| 1 | Morgan signs Avery up for First Sales. | Signup succeeds. |
| 2 | Morgan downloads Avery's ICS invite. | `.ics` parses as VCALENDAR/VEVENT and contains stable UID, generation timestamp, correct 09:00–10:30 timezone-aware times, Show & Sell/slot summary, and `Library on Main`. No street address is required. |
| 3 | Morgan signs Blake up for First Sales. | Capacity 1 is enforced; signup is rejected and no waitlist is invented. |
| 4 | Morgan signs Avery up for Midday. | Adjacent non-overlapping signup succeeds; Avery now has two slots. |
| 5 | Morgan attempts to sign Avery up for Full Booth. | The time conflict is blocked because Full Booth overlaps both existing commitments. |
| 6 | Morgan signs Charlie up for Full Booth. | Signup succeeds because Charlie has no conflicting commitment and capacity is available. |
| 7 | Morgan attempts to sign Emery up for any slot. | Emery is rejected as unjoined. |
| 8 | Riley attempts to sign Avery up through the API. | Riley is denied. |
| 9 | Casey confirms actual work for Avery: 75 minutes in First Sales and 115 in Midday. | Actual work is stored per slot and totals 190 minutes; it does not have to equal slot duration. |
| 10 | Morgan checks for automatic email/in-app notifications after signup. | None is generated. Only the on-demand ICS download and visible application/audit records exist. |

**Evidence:** Parsed ICS content, capacity/conflict errors, Avery's 190-minute work record.

### SS-SM-07 — Sales, Other payments, We Owe, print, and cash

**Actors:** Alex, Casey, Morgan  
**Fixture:** In this scenario's isolated Unit, create `Venmo <DATA_ID>` with `payment_qr.png`. Arrange past `Church on Elm <DATA_ID>` in `Sales Desk <DATA_ID>` with 3 Chocolate and 1 Butter in Kernel stock. Assign 2 Chocolate and 1 Butter. We Owe starts disabled. Avery and Blake have valid signups/work.

| Step | Actor/action | Expected result |
| ---: | --- | --- |
| 1 | Morgan attempts to enter a Show & Sell sale through the API. | Morgan is denied; only Unit Admins may enter event sales. |
| 2 | Alex attempts to submit 3 Chocolate to Nora Cash while We Owe is off and only 2 are allocated. | Submission is rejected; no partial sale, We Owe, negative balance, or silent individual order is created. |
| 3 | Alex enables We Owe for this event and downloads the sales sheet and payment/help sheet. | Sales sheet contains event/location/products/prices/blank rows/payment names/Other details/We Owe indicator. Help sheet contains Unit methods, Venmo QR, and Other/split instructions. |
| 4 | Alex enters sale 1: Nora Cash, 1 Chocolate, `$25`, Cash, immediate handoff. | Chocolate physical becomes 2 and event remaining allocation becomes 1. |
| 5 | Alex enters sale 2: Quinn WeOwe, 3 Chocolate, `$75`, Other details `Apple Pay; Kernel reimbursed unit by Venmo`. One is immediate and two are We Owe. No phone/email is entered. | Sale succeeds with buyer name only. Chocolate physical becomes 1; event allocation becomes 0; open We Owe is 2. Sale total/payment details are preserved. |
| 6 | Alex enters sale 3: Sam Split, 1 Butter, `$20`, Other details `$10 cash + $10 Venmo`. | Butter physical/allocation becomes 0. The sale has one payment method, Other; no tender records are created. |
| 7 | Alex reserves 1 unassigned Chocolate for Quinn's We Owe. | Chocolate Kernel physical remains 1; sold product in our possession becomes 1; sellable/unassigned becomes 0; covered We Owe is 1 and uncovered is 1. |
| 8 | Casey confirms equal participation for Avery and Blake and reviews the whole-event pool. | Pool is `$120` (`$25 + $75 + $20`); pending equal allocations are `$60` each, including open We Owe. |
| 9 | Casey opens cash reconciliation. | Calculated expected cash is `$25`; Other notes are not parsed. |
| 10 | Casey enters expected-cash adjustment `+$10` with reason `Cash portion of Sam Split Other payment`; actual cash `$34`; explanation `$1 short at closeout`. | Adjusted expected is `$35`; discrepancy is `-$1`; finalization is allowed because an explanation is present. |
| 11 | Casey confirms expected/actual returns of 0 Chocolate and 0 Butter and finalizes. | Event and `$60` allocations per Scout are approved. Quinn's 2 We Owe remain open but were included in credit. Cash details are auditable. |
| 12 | Alex fulfills 1 We Owe from the reserved Chocolate. | Kernel physical and sold-in-possession each decrease from 1 to 0; covered becomes 0; 1 We Owe remains open/uncovered; sale totals and Scout credit do not change. |
| 13 | Alex fulfills the remaining 1 from direct Council supply. | The obligation closes without changing Kernel stock. No second sale or credit is created. |
| 14 | Alex opens We Owe reports. | The obligation appears closed with correct buyer/event/product/value; no delivery assignee, due date, or aging field is required. Open/closed filtering works. |

**Evidence:** Downloaded artifacts, blocked off-We Owe sale, three sale records, cash reconciliation, open/closed obligation states.

### SS-SM-08 — Whole-event pool, payment snapshot, and rounding

**Actors:** Alex, Casey  
**Fixture A:** In this scenario's isolated Unit, create `Venmo <DATA_ID>` with `payment_qr.png`. Arrange past `School on Pine <DATA_ID>` in `Split Math <DATA_ID>` with two slots. Stock/assign 12 Chocolate and 5 Butter. Four Scouts have confirmed work.

| Step | Actor/action | Expected result |
| ---: | --- | --- |
| 1 | Alex enters morning sale: 12 Chocolate, `$300`, Cash. | Morning product/payment totals are `$300`. |
| 2 | Alex enters afternoon sale: 5 Butter, `$100`, named method `Venmo <DATA_ID>`. | Afternoon total is `$100`; sale snapshots that exact method name. |
| 3 | Casey selects Equal split and reviews the event. | There is one `$400` whole-event pool, not separate `$300` and `$100` slot pools. Four Scouts each have pending `$100`. |
| 4 | Before finalization, Casey checks approved Scout totals; afterward Casey confirms returns/cash and finalizes. | Approved totals contain no event credit before approval and exactly `$100` per Scout afterward. |
| 5 | Casey renames the Unit method to `Venmo (Unit) <DATA_ID>` and regenerates payment help. | Future sheets use the new name/QR; the historical afternoon sale still reports `Venmo <DATA_ID>`. |

**Fixture B:** Past `Rounding Garage <DATA_ID>` with 5 Butter stock/assigned and exactly three eligible confirmed Scouts: Avery, Blake, Charlie.

| Step | Actor/action | Expected result |
| ---: | --- | --- |
| 6 | Alex enters one 5-Butter Cash sale for `$100` and selects Equal split. | Preview rounds each Scout down to `$33.33` and displays one unassigned cent. |
| 7 | Casey confirms expected/actual Butter returns of 0 and expected/actual cash of `$100`, then attempts to finalize without assigning the cent. | Finalization is blocked specifically because one cent remains unassigned; no allocation is approved and the other finalization inputs are valid. |
| 8 | Casey assigns the one cent to Blake and re-submits finalization. | Approved allocations are Avery `$33.33`, Blake `$33.34`, Charlie `$33.33`; total is exactly `$100`. The application did not choose the recipient automatically. |

**Evidence:** `$400` pool preview, historical payment-name snapshot, blocked rounding finalization, final cent assignment.

### SS-SM-09 — Reopen and re-finalize

**Actors:** Alex, Casey  
**Starting state:** Independently arrange a finalized `Rounding Garage <DATA_ID>` with a `$100` sale and approved allocations Avery `$33.33`, Blake `$33.34`, Charlie `$33.33`. Do not invoke `SS-SM-08` or share its event; this scenario must be schedulable in any lane/order.

| Step | Actor/action | Expected result |
| ---: | --- | --- |
| 1 | Alex records each Scout's current approved total, then Casey reopens Rounding Garage. | The event's allocations become suspended and are removed from current approved Scout totals. The prior approved version remains readable in audit history. |
| 2 | Casey inspects inventory. | No returned stock is reclaimed and no inventory movement occurs merely because the event reopened. |
| 3 | Casey changes the one-cent assignment from Blake to Avery and re-finalizes with unchanged sales/cash/stock. | New approved allocations are Avery `$33.34`, Blake `$33.33`, Charlie `$33.33`. Credit is restored from the new approved version only. |
| 4 | Alex compares finalization history. | The old version shows Blake receiving the cent; the new version shows Avery. Both versions and actors/timestamps are preserved. |

**Evidence:** Approved totals before/during/after reopen and both finalization versions.

### SS-SM-10 — Inventory list and Council Needs

**Actors:** Alex, Casey, Morgan  
**Fixture:** `Council Planning <DATA_ID>`; Butter price `$20`.

1. Morgan creates Council Customer's individual order for 10 Butter, entirely unfulfilled.
2. Alex records 8 Butter received, issues 2 to Avery, and assigns 4 of the remaining Kernel stock to future `Council Future Booth <DATA_ID>`.
3. Alex records 3 Butter as Council on order.

Expected starting balances:

- Actual unfulfilled individual demand: 10 Butter.
- With Scout: 2 Butter.
- Kernel physical/sellable: 6 Butter.
- Assigned: 4 Butter.
- Unassigned: 2 Butter.
- Council on order: 3 Butter.

| Step | Actor/action | Expected result |
| ---: | --- | --- |
| 1 | Alex opens the product-level inventory list. | Every starting balance above is shown, including per-Scout custody and total unit-owned stock of 8. |
| 2 | Alex opens Council Needs with Unit preference `Physical stock`. | Physical-stock need is 4 (`10 - 6`); after-assignments need is 8 (`10 - 2`). Physical-stock is primary, but both are visible. |
| 3 | Casey changes the Unit preference to `After assignments`. | After-assignments becomes the primary presentation across the Unit; values remain 4 and 8, and the other calculation is still visible. |
| 4 | Alex checks the on-order and custody columns. | On-order 3 and With Scout 2 are separate; neither reduces need 4 or 8. No future event sales or assignment overage is added to demand. |
| 5 | Alex fulfills 1 unit of Council Customer's order from unassigned Kernel stock. | Demand becomes 9, sellable becomes 5, unassigned becomes 1; both needs remain 4 and 8 because demand and available stock each fell by 1. |
| 6 | Alex fulfills 1 more unit using direct Council supply. | Demand becomes 8 with no stock change; physical need becomes 3 (`8 - 5`) and after-assignments need becomes 7 (`8 - 1`). On-order display changes only if the Kernel explicitly updates that separate balance. |

**Evidence:** Starting inventory list, both preferences, needs before/after each fulfillment source.

### SS-SM-11 — Cancellation and independent campaign deactivation

**Actors:** Alex, Casey, Morgan  
**Fixture:** Future `Park Pavilion <DATA_ID>` with 1 Butter assigned and Avery signed up; one already-started event; `Dirty Campaign <DATA_ID>` with 2 Kernel Butter, 1 With Scout Butter, 1 open We Owe Butter, and 2 Butter Council on order.

| Step | Actor/action | Expected result |
| ---: | --- | --- |
| 1 | Morgan attempts to cancel future Park Pavilion through the API. | Morgan is denied; only a Unit Admin may cancel. |
| 2 | Casey cancels Park Pavilion before its start. | Remaining allocation and signups are released; cancellation is audited. |
| 3 | Casey looks for a reschedule action or attempts a reschedule mutation. | No reschedule operation exists. |
| 4 | Casey creates `Park Pavilion Replacement <DATA_ID>`. | The new event has a new ID and no automatically copied allocation or signup. Casey can assign/sign up afresh. |
| 5 | Casey attempts to cancel the already-started event. | Cancellation is rejected; finalization/reopening is the only correction path. |
| 6 | Alex deactivates Dirty Campaign without cleaning it. | Deactivation succeeds. Kernel stock 2, With Scout 1, open We Owe 1, and on-order 2 remain unchanged and do not move to another campaign. |
| 7 | Alex reviews the deactivated campaign and applies a `-1` Butter stock-only adjustment with reason `Gift to volunteer`. | Kernel Butter becomes 1; no other balance, sale, payment, fulfillment, or Scout credit changes. No product mapping or transfer workflow appears. |

**Evidence:** Cancellation audit, absent reschedule operation, dirty-campaign balances before/after deactivation.

## 6. Additional API smoke invariants

These are short live-GraphQL checks that accompany the browser walkthroughs. Each API check is its own independently scheduled scenario with a fresh `DATA_ID`, its own lane/Unit/Campaign/stock/event/grant fixtures, and its own cleanup. They reuse the persona and product naming conventions, but never mutate a browser walkthrough's fixtures or balances. `SS-API-01` and `SS-API-02` use the API scenario's own Alex and Casey; `SS-API-05` uses its own sale/finalization fixture; `SS-API-06` uses a dedicated Unit created by that API scenario's Riley.

| ID | Actor/action | Expected result |
| --- | --- | --- |
| `SS-API-01` | Two Unit Admin clients concurrently assign the last available units to overlapping events. | Only assignments within the concurrent stock rule succeed; no negative or excess allocation results. |
| `SS-API-02` | Two Unit Admin clients concurrently enter sales against the last event unit. | One sale succeeds or both are explicitly split only when stock/We Owe permits; physical and event balances never become negative and no sale/inventory effect is duplicated. |
| `SS-API-03` | Morgan calls event sale, stock adjustment, finalization, payment-method management, or Unit grant mutations directly. | Every privileged mutation is denied server-side. |
| `SS-API-04` | The existing global-admin Owner calls the lane Riley's Troop 7150 operations without a Unit grant. | Every operation is denied; global ADMIN does not bypass Unit tenancy. The lane Alex is not used for this assertion. |
| `SS-API-05` | Retry the same sale/finalization request using its idempotency identity. | No duplicate sale, stock movement, We Owe reservation, fulfillment, cash record, or Scout allocation is created. |
| `SS-API-06` | Remove the final Unit grant while another client is adding/redeeming a new grant. | The Unit can never enter a zero-grant committed state. |

## 7. Cleanup and completion criteria

### 7.1 Cleanup order

After all evidence/assertions for each scenario complete, delete that scenario's `DATA_ID` synthetic data in dependency order. Each lane performs this cleanup independently; do not invoke the current account-wide/global cleanup while any lane is active:

1. Downloaded local artifacts and temporary browser contexts.
2. We Owe fulfillments/reservations and open obligations.
3. Reopened/finalized event versions, cash reconciliations, and Scout allocations.
4. Show & Sell sales, signups, work records, slots, allocations, and events.
5. Individual fulfillments/orders, Scout custody, inventory movements, and Council on-order balances.
6. Unit Campaign memberships and Scout Campaigns.
7. Catalogs/products where owned by the fixture.
8. Unit payment QR objects and named Unit payment methods.
9. Unit invites and Unit Campaigns.
10. Units and their access grants using a test-only Unit cascade that deletes the Unit and all grants together. Do not call the product's revoke-last-grant mutation, which is required to reject orphaning an existing Unit.
11. Morgan's five SellerProfiles.

Retain the lane pool's Alex, Casey, Morgan, and Riley Cognito/Account records for reuse; ephemeral run-scoped pools may instead be deleted after every lane has finished. Verify that no `DATA_ID` entities or Unit QR objects remain and that cleanup did not touch another lane. CI must fail on cleanup errors when strict cleanup is enabled. If cleanup fails, the lane remains leased and quarantined for the rest of the run; it cannot be reused until complete deletion is verified, and scheduling janitor work alone does not release it.

### 7.2 Smoke completion gate

A build passes this smoke plan only when:

- every `FIX-AC` capability needed by the selected scenarios exists;
- every selected scenario reaches its expected persisted/audit state before cleanup;
- API denial and concurrency checks pass without relying on hidden UI controls;
- ICS and printable artifacts have been inspected, not merely downloaded;
- no automatic notification was observed;
- cleanup removed every synthetic entity/artifact; and
- no acceptance expectation was changed to match an implementation defect without a product decision.
