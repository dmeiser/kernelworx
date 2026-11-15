import { util } from '@aws-appsync/utils';
import { enrichLineItems } from './lib/line_items.js';
import { buildOrderKey } from './lib/order_keys.js';
import { composePublicOrderReceipt, PUBLIC_ORDER_CAP, isConditionFailure } from './lib/public_order.js';
import { orderOrigin, membershipGuardCurrencyCheck, cancelledTransactIndexes } from './lib/order_origin.js';

// Loaded via Terraform templatefile() (functions_orders.tf): a dollar-brace
// sequence here is Terraform-interpolated, not JS. In a template/string literal
// that aborts every plan/apply with "Invalid expression"; ordinary comments are
// stripped by the esbuild bundle, but are banned too as defense-in-depth.
// Enforced by tests/unit/check_templatefile_escaping.test.ts (#570).
//
// The real table names MUST be injected: unlike single-table operations, a
// TransactWriteItems item's `table` field is the literal AWS table name, not
// the datasource's logical name. Hardcoding 'Orders'/'Campaigns' made AppSync
// target a nonexistent table/Orders and fail with AccessDenied (ephemeral
// integration run on the mega branch).
const ordersTableName = '${orders_table_name}';
const campaignsTableName = '${campaigns_table_name}';
const unitCampaignsTableName = '${unit_campaigns_table_name}';

// Step 6 of the publicCreateOrder pipeline (#679 write slice, spec §5.3):
// write the order AND enforce the cap. A CLONE of create_order_fn.js that shares its price and
// line-item core (lib/line_items.js) but reads the STASH, not ctx.args.input -
// the values that passed the anonymous-input checks are the trimmed, bounded
// ones step 2 mapped, and re-reading the caller's raw input here would write
// unvalidated strings.
//
// What a public order adds to an ordinary order row:
//   orderSource: "PUBLIC"  - the enum spelling is load-bearing. AppSync does
//                            not validate enum OUTPUT, so a lowercase stored
//                            value would flow to clients as an invalid enum
//                            literal and break codegen.
//   status: "NEW"          - the seller marks CONFIRMED through updateOrder
//                            (one-way, public orders only); authenticated
//                            orders leave the attribute absent, which is why
//                            Order.status is nullable.
//   receiptToken           - a 128-bit random capability (util.autoId; the
//                            version nibble may be nonstandard, ~122 bits of
//                            entropy is the claim) minted for public orders
//                            only and NEVER exposed on the Order type. It is
//                            carried only inside the buyer's receipt link.
//   customerFirstName / customerLastName / customerEmail - collected by the
//                            public form, absent on pre-feature rows.
//
// The soft-deleted-catalog guard belongs here: the reused get_catalog step
// rejects missing catalogs but has never checked isDeleted, and the authenticated
// path carries the same gap. Fixing that path is a separate issue - silently
// changing live authenticated behavior is not this slice's call.
//
// ARCH-1 fix, both halves: the folded cap ADD below replaces the old
// increment_public_order_count step (this resolver is at the 10-function cap,
// so the cap gate had to move into this transaction), and the race with
// campaign deletion is closed the same way. The write runs as a
// TransactWriteItems with two operations, plus a third when a guard row was
// read (each transact item MUST carry its own `operation` field - AppSync
// rejects an item without one):
//   1. UpdateItem on the campaigns table: the cap ADD plus the
//      denormalized totalOrders/totalRevenue counters (#746), with one
//      condition that is both the authoritative cap bound and the existence
//      guard. A concurrent deleteCampaign deletes this same item, failing the
//      condition and cancelling the whole transaction, so no orphaned order is
//      ever written. The guard lives ON this UpdateItem, not on a standalone
//      ConditionCheck, because DynamoDB rejects a transaction with two
//      operations on the same item ("Transaction request cannot include
//      multiple operations on one item"), and both ADDs must live on exactly
//      this item.
//   2. PutItem on the orders table: writes the order row.
//   3. ConditionCheck on the membership guard row (FUNC-3), present only when
//      the pipeline read a guard: a removal, move, or rejoin after the strong
//      read fails the pin and cancels the transaction, so the joined scope
//      this Order stamps is the one that was current at commit -- or nothing
//      commits at all.
// One UpdateItem instead of the old UpdateItem-plus-step because the
// publicCreateOrder resolver is at AppSync's 10-function cap; atomic is also
// strictly better -
// order row and counters commit or cancel together, so the partial-failure
// drift documented on sync_campaign_totals_fn cannot occur on this path.
// Both operations succeed or fail atomically, so a concurrent campaign deletion
// (which deletes the campaign item) cancels the transaction with
// TransactionCanceledException and no order row is written. The cap itself is
// enforced only by this transaction now: a cancellation whose campaigns-item
// reason fired means the cap bound refused or the campaign row is gone - the
// single condition cannot tell them apart, and the retired increment step
// answered that union as PUBLIC_ORDER_LIMIT_EXCEEDED with its
// PUBLIC_ORDER_CAP_REJECTED marker, so the folded transaction keeps that
// answer (HTTP 200, counted by the public-cap-rejected filter, invisible to
// the 4XX alarm). A cancellation whose guard-pin reason fired is a membership
// move, and answers CONFLICT so the buyer can retry against the new state.
// Folding also retires the accepted overcount the standalone step documented:
// the cap ADD is inside the transaction, so a cancelled create burns nothing.
//
// Result-shape note: a successful TransactWriteItems returns
// {keys: [<each item's key>], cancellationReasons: null} - the written
// ATTRIBUTES are not returned (unlike a standalone PutItem). The order row
// composed below is therefore stashed on ctx.stash by request() and reused by
// response(): the transaction is atomic, so the locally built item is by
// construction exactly what was stored - including the minted receiptToken.
export function request(ctx) {
    const stash = ctx.stash || {};
    const campaign = stash.campaign;
    const catalog = stash.catalog;
    const mapped = stash.publicOrder;
    const profileId = stash.profileId;
    const campaignId = stash.campaignId;

    if (!campaign || !catalog || !mapped || !profileId || !campaignId) {
        // Wiring fault, not a caller error: steps 1-4 stash all of these.
        util.error('Order could not be written', 'INTERNAL_ERROR');
        return null;
    }

    if (catalog.isDeleted === true) {
        util.error('Catalog is not available for this campaign', 'INVALID_INPUT');
        return null;
    }

    // The shared core rejects any productId absent from the catalog array,
    // which is exactly the offer-visible product set (products carry no
    // per-item tombstone; soft deletion is catalog-level only).
    const enriched = enrichLineItems(mapped.lineItems, catalog);

    // Same single owner for the order-id grammar as the authenticated write
    // path (#534) - both minters now emit buildOrderKey's shape, so the
    // public order id parseable by parseOrderKey cannot drift from the
    // authenticated one.
    const orderId = buildOrderKey(campaignId, util.autoId());
    const now = util.time.nowISO8601();

    const orderItem = {
        orderId: orderId,
        profileId: profileId,
        campaignId: campaignId,
        customerName: mapped.customerName,
        customerFirstName: mapped.customerFirstName,
        customerLastName: mapped.customerLastName,
        // The seller's display name as the buyer saw it on the offer page.
        // Denormalized deliberately: the publicGetOrderReceipt read is one
        // strongly consistent orders GetItem, and resolving this name from the
        // profile instead would add a GSI locate plus a consistent read (and a
        // transfer-window failure mode) to a path the receipt token already
        // authorizes. It is NOT an Order GraphQL field, so it is invisible to
        // every authenticated read; only the receipt read selects it.
        sellerName: typeof stash.sellerName === 'string' ? stash.sellerName : '',
        orderDate: mapped.orderDate,
        paymentMethod: mapped.paymentMethod,
        lineItems: enriched.enrichedLineItems,
        totalAmount: enriched.totalAmountCents / 100,
        orderSource: 'PUBLIC',
        status: 'NEW',
        // Never selected by any Order field; the publicGetOrderReceipt read is
        // the only code path that reads it back.
        receiptToken: util.autoId(),
        createdAt: now,
        updatedAt: now
    };

    // §1.4.3 (API-FIX-05): a public order belongs to the Unit the campaign was
    // joined to at the moment of sale. Unfulfilled public orders count toward
    // that Unit's Council demand, so the answer comes from the membership guard
    // the pipeline read strongly, not from the campaign's latest-link pair that
    // removal retains. The fields are storage-only: no public read selects them
    // (public API-key surface guard).
    const origin = orderOrigin(stash.membershipGuard);
    orderItem.unitId = origin.unitId;
    orderItem.unitCampaignId = origin.unitCampaignId;

    if (mapped.customerEmail) {
        orderItem.customerEmail = mapped.customerEmail;
    }
    if (mapped.customerPhone) {
        orderItem.customerPhone = mapped.customerPhone;
    }
    if (mapped.customerAddress) {
        orderItem.customerAddress = mapped.customerAddress;
    }
    if (mapped.notes) {
        orderItem.notes = mapped.notes;
    }

    for (const lineItem of enriched.enrichedLineItems) {
        if (typeof lineItem.productName !== 'string') {
            lineItem.productName = null;
        }
    }

    // Stash the exact row this request writes so response() can hand it to the
    // receipt composer and the best-effort email step: a TransactWriteItems
    // result carries only item keys, not the written attributes.
    if (ctx.stash) {
        ctx.stash.orderItem = orderItem;
    }

    // The campaign item's partition key is the profileId. The write runs as one
    // transaction with three effects: the cap ADD (folded in from the old
    // increment_public_order_count step, ARCH-1), the #746 totals ADD, and the
    // order PutItem. Folding is what keeps this resolver at the 10-function cap:
    // the ADD's own condition is the authoritative cap bound, and the totals
    // ADD's attribute_exists doubles as the existence guard -- a concurrent
    // deleteCampaign deletes this same item, failing the condition and
    // cancelling the whole transaction, so no orphaned order is ever written.
    // One transaction means one operation on this item is forbidden twice:
    // DynamoDB rejects two transact items on the same key, so the cap and the
    // totals ride a single ADD with both counters. Nothing burns on a
    // cancelled transaction -- the ADDs apply only on commit, so even the
    // accepted overcount the standalone step documented is retired here.
    // The guard pin (FUNC-3), appended last when a guard row was read, makes
    // the stamped origin current-at-commit or the order simply does not commit.
    // FUNC-3: the join-scope stamp is only as honest as the write that carries
    // it. When a guard row was read, the transaction pins it: a removal, a
    // move, or a rejoin between the strong read and this commit fails the
    // ConditionCheck and cancels the whole transaction, so no Order commits
    // with a scope that was not current at commit. The pin rides LAST, so the
    // response's positional reading of the cancellation reasons is stable.
    const transactItems = [
        {
            // UpdateItem on the campaigns table: the cap ADD plus the #746
            // denormalized totalOrders/totalRevenue counters, atomically.
            operation: 'UpdateItem',
            table: campaignsTableName,
            key: util.dynamodb.toMapValues({ profileId: profileId, campaignId: campaignId }),
            update: {
                expression: 'ADD #publicOrderCount :one, #totalOrders :one, #totalRevenue :amount',
                expressionNames: { '#publicOrderCount': 'publicOrderCount', '#totalOrders': 'totalOrders', '#totalRevenue': 'totalRevenue' },
                expressionValues: util.dynamodb.toMapValues({ ':one': 1, ':amount': orderItem.totalAmount })
            },
            condition: {
                expression: 'attribute_exists(campaignId) AND (attribute_not_exists(#publicOrderCount) OR #publicOrderCount < :cap)',
                expressionNames: { '#publicOrderCount': 'publicOrderCount' },
                expressionValues: util.dynamodb.toMapValues({ ':cap': PUBLIC_ORDER_CAP })
            }
        },
        {
            // PutItem: write the order row.
            operation: 'PutItem',
            table: ordersTableName,
            key: util.dynamodb.toMapValues({ campaignId: campaignId, orderId: orderId }),
            attributeValues: util.dynamodb.toMapValues(orderItem)
        }
    ];
    const guardPin = membershipGuardCurrencyCheck(unitCampaignsTableName, campaignId, stash.membershipGuard);
    if (guardPin !== null) {
        transactItems.push(guardPin);
    }
    return {
        operation: 'TransactWriteItems',
        transactItems: transactItems
    };
}

export function response(ctx) {
    if (ctx.error) {
        // A cancellation lists one reason per transact item, in the order of
        // request(): [0] the campaigns UpdateItem (cap bound + row existence,
        // one condition), [1] the orders PutItem (no condition), [2] the guard
        // pin (only when a guard row was read). Item 0 failing cannot say
        // whether the cap refused or the campaign was deleted -- the retired
        // increment step answered that union as the limit error with its
        // CloudWatch marker (the public-cap-rejected filter counts
        // PUBLIC_ORDER_CAP_REJECTED; cap rejections answer HTTP 200 and stay
        // invisible to the 4XX alarm), and the folded transaction keeps that
        // answer. Item 2 failing is a membership move: the join scope stamped
        // here would not have been current at commit, so the order is refused
        // (CONFLICT) and the buyer's retry re-reads the guard. Marker only --
        // no campaign material.
        if (ctx.error.type === 'DynamoDB:TransactionCanceledException') {
            const failed = cancelledTransactIndexes(ctx.error);
            if (failed.indexOf(2) !== -1) {
                util.error('The campaign changed while this order was being placed; try again', 'CONFLICT');
                return null;
            }
            console.error('PUBLIC_ORDER_CAP_REJECTED');
            util.error('This campaign has reached its public order limit', 'PUBLIC_ORDER_LIMIT_EXCEEDED');
            return null;
        }
        util.error(ctx.error.message, ctx.error.type);
        return null;
    }

    // request() stashed the exact row this transaction wrote (the
    // TransactWriteItems result carries only item keys, not attributes).
    const orderResult = ctx.stash && ctx.stash.orderItem;
    if (!orderResult) {
        util.error('Order could not be written', 'INTERNAL_ERROR');
        return null;
    }

    // The stashed row is what the best-effort email step (spec §5.3 step 8)
    // reads: the mailer is payload-driven and never re-reads orders, so the
    // enriched line items, totals, buyer contact, and the minted receiptToken
    // travel to it through the stash. The receipt composed below stays the
    // step result (it is what the pipeline root passes through).
    return composePublicOrderReceipt(orderResult);
}
