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
