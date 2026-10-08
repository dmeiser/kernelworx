import { util } from '@aws-appsync/utils';
import { stripIdPrefix } from './lib/ids.js';
import { enrichLineItems } from './lib/line_items.js';
import { composePublicOrderReceipt } from './lib/public_order.js';

// Step 7 of the publicCreateOrder pipeline (#679 write slice, spec §4.2/§5.3):
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
//   status: "NEW"          - the seller marks CONFIRMED in the lifecycle slice;
//                            authenticated orders leave the attribute absent,
//                            which is why Order.status is nullable.
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

    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({ campaignId: campaignId, orderId: orderId }),
        attributeValues: util.dynamodb.toMapValues(orderItem)
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
        return null;
    }

    // PutItem returns the written item, so the receipt is composed from what was
    // actually stored - including the minted receiptToken - rather than from a
    // second read that could race.
    return composePublicOrderReceipt(ctx.result);
}
