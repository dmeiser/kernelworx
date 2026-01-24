import { util, runtime } from '@aws-appsync/utils';

export function request(ctx) {
    const ordersToDelete = ctx.stash.ordersToDelete || [];
    
    if (ordersToDelete.length === 0) {
        // No orders to delete - use early return to skip this step
        return runtime.earlyReturn(true);
    }
    
    // Delete first order only - simple approach for now
    const firstOrder = ordersToDelete[0];
    
    // V2 schema: composite key (campaignId, orderId)
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ campaignId: firstOrder.campaignId, orderId: firstOrder.orderId })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
