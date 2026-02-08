import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // No-op request (using None data source)
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // If order not found, return null
    if (ctx.stash.orderNotFound) {
        return null;
    }
    
    // If not authorized, return null (query permissions model - don't error)
    if (!ctx.stash.authorized) {
        return null;
    }
    
    // Map DynamoDB field campaignId to GraphQL field campaignId
    const order = ctx.stash.order;
    if (order && order.campaignId) {
        order.campaignId = order.campaignId;
    }
    
    // Return the order
    return order;
}
