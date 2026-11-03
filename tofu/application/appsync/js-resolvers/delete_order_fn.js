import { util } from '@aws-appsync/utils';

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
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ campaignId: order.campaignId, orderId: order.orderId })
    };
}

export function response(ctx) {
    if (ctx.error && !ctx.stash.skipDelete) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Always return true (idempotent)
    return true;
}
