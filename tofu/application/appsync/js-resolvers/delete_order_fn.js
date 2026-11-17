import { util } from '@aws-appsync/utils';

// ARCH-1: a hard Order delete takes its fulfillment history with it.
//
// `OrderFulfillment` rows are keyed by the Order and append-only (data model §6.5), and
// both the reversal path and the audit read re-load the Order to authorize themselves. An
// Order deleted on its own therefore strands records that cannot be reversed, cannot be
// read, and name inventory movements that already moved stock. The impact assessment
// requires children-first cleanup on every hard-delete path, and doing it in the SAME
// transaction as the Order delete is what makes a half-cleanup unreachable: either the
// Order and every record of its history are gone, or nothing is.
//
// `get_order_fulfillments_for_delete` supplies the keys, and refuses an Order whose
// history is larger than one transaction can carry, so the delete never has to choose
// between deleting some of the history and deleting none of it.
const orderFulfillmentsTableName = '${order_fulfillments_table_name}';

export function request(ctx) {
    const order = ctx.stash.order;
    
    // If order doesn't exist (lookup failed), skip the delete operation
    // This makes deleteOrder idempotent - deleting a non-existent order returns true
    if (!order) {
        // Return a no-op - just set a flag in stash
        ctx.stash.skipDelete = true;
        return {
        operation: 'Query',
        index: 'orderId-index',
        query: {
            expression: 'orderId = :orderId',
            expressionValues: util.dynamodb.toMapValues({ ':orderId': 'NOOP' })
        },
        limit: 1
        };
    }
    
    // #746: denormalized-totals delta for sync_campaign_totals_fn (the step
    // after this one). The order row's profileId/campaignId are the
    // campaigns-table key, so no lookup is needed to address the counter. A
    // missing totalAmount (never written by any order path) degrades to a
    // count-only decrement rather than failing the delete.
    const revenue = typeof order.totalAmount === 'number' ? -order.totalAmount : 0;
    ctx.stash.totalsDelta = {
        profileId: order.profileId,
        campaignId: order.campaignId,
        count: -1,
        revenue: revenue
    };

    // V2 schema: composite key (campaignId, orderId)
    const children = ctx.stash && Array.isArray(ctx.stash.fulfillmentKeys) ? ctx.stash.fulfillmentKeys : [];
    const deletions = [];
    for (const child of children) {
        deletions.push({
            operation: 'Delete',
            table: orderFulfillmentsTableName,
            key: util.dynamodb.toMapValues({ pk: child.pk, sk: child.sk })
        });
    }
    if (children.length === 0) {
        // The overwhelmingly common case, and the pre-Wave-3 shape: an Order with no
        // fulfillment history is one DeleteItem, with no transaction around it.
        return {
            operation: 'DeleteItem',
            key: util.dynamodb.toMapValues({ campaignId: order.campaignId, orderId: order.orderId })
        };
    }
    deletions.push({
        operation: 'Delete',
        key: util.dynamodb.toMapValues({ campaignId: order.campaignId, orderId: order.orderId })
    });
    return { operation: 'TransactWriteItems', transactItems: deletions };
}

export function response(ctx) {
    if (ctx.error && !ctx.stash.skipDelete) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Always return true (idempotent)
    return true;
}
