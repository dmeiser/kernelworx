import { util } from '@aws-appsync/utils';
import { stripIdPrefix } from './lib/ids.js';
import { enrichLineItems } from './lib/line_items.js';
import { composePublicOrderReceipt } from './lib/public_order.js';

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

// Step 7 of the publicCreateOrder pipeline (#679 write slice, spec §5.3):
// write the order. A CLONE of create_order_fn.js that shares its price and
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
// ARCH-1 fix: race between public order creation and campaign deletion.
// The increment_public_order_count step (step 6) increments the campaign's
// publicOrderCount with a condition that the campaign row exists. However,
// the campaign could be deleted between step 6 and this step (step 7), leaving
// an orphaned order under a deleted campaign. To prevent this, the write runs
// as a TransactWriteItems with two operations (each transact item MUST carry
// its own `operation` field - AppSync rejects an item without one):
//   1. UpdateItem on the campaigns table: maintains the denormalized
//      totalOrders/totalRevenue counters (#746) AND, through its condition,
//      verifies the campaign item still exists (attribute_exists(campaignId)
//      on the campaign's partition key) - the ARCH-1 existence guard. The
//      guard lives ON this UpdateItem, not on a standalone ConditionCheck,
//      because DynamoDB rejects a transaction with two operations on the
//      same item ("Transaction request cannot include multiple operations on
//      one item"), and the counters must live on exactly this item.
//   2. PutItem on the orders table: writes the order row.
// The totals update rides INSIDE the transaction rather than as a follow-up
// sync_campaign_totals pipeline step because the publicCreateOrder resolver
// is already at AppSync's 10-function cap; atomic is also strictly better -
// order row and counters commit or cancel together, so the partial-failure
// drift documented on sync_campaign_totals_fn cannot occur on this path.
// Both operations succeed or fail atomically, so a concurrent campaign deletion
// (which deletes the campaign item) cancels the transaction with
// TransactionCanceledException and no order row is written. The cap itself is
// still enforced only by step 6 - this transaction's condition guards
// existence, not the count, so a cancellation here means the campaign is
// gone and surfaces as NOT_FOUND, never as a limit error.
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

    const campaignIdWithoutPrefix = stripIdPrefix(campaignId, 'CAMPAIGN#');
    const orderId = 'ORDER#' + campaignIdWithoutPrefix + '#' + util.autoId();
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

    // The campaign item's partition key is the profileId. We verify the
    // campaign still exists before writing the order: a ConditionCheck on the
    // campaign table plus the PutItem on the orders table, atomically.
    return {
        operation: 'TransactWriteItems',
        transactItems: [
            {
                // UpdateItem on the campaigns table (#746): maintains the
                // denormalized totalOrders/totalRevenue counters, and through
                // its condition verifies the campaign item still exists (the
                // ARCH-1 guard). A concurrent deleteCampaign deletes this
                // item, failing the condition and cancelling the entire
                // transaction. DynamoDB forbids two operations on one item in
                // a transaction, so the existence guard cannot be a separate
                // ConditionCheck on this same item.
                operation: 'UpdateItem',
                table: campaignsTableName,
                key: util.dynamodb.toMapValues({ profileId: profileId, campaignId: campaignId }),
                update: {
                    expression: 'ADD #totalOrders :one, #totalRevenue :amount',
                    expressionNames: { '#totalOrders': 'totalOrders', '#totalRevenue': 'totalRevenue' },
                    expressionValues: util.dynamodb.toMapValues({ ':one': 1, ':amount': orderItem.totalAmount })
                },
                condition: {
                    expression: 'attribute_exists(campaignId)'
                }
            },
            {
                // PutItem: write the order row.
                operation: 'PutItem',
                table: ordersTableName,
                key: util.dynamodb.toMapValues({ campaignId: campaignId, orderId: orderId }),
                attributeValues: util.dynamodb.toMapValues(orderItem)
            }
        ]
    };
}

export function response(ctx) {
    if (ctx.error) {
        // A cancellation at this step means the ConditionCheck found no
        // campaign row: the campaign was deleted between step 6's increment
        // and this write. No order row was written (the transaction is
        // atomic). The cap is enforced only by step 6, so this is a
        // NOT_FOUND, not a limit error.
        if (ctx.error.type === 'DynamoDB:TransactionCanceledException') {
            util.error('Campaign is no longer available', 'NOT_FOUND');
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
