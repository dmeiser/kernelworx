import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const orderId = ctx.args.orderId;
    // Query orderId-index GSI (V2 schema: PK=campaignId, SK=orderId)
    return {
        operation: 'Query',
        index: 'orderId-index',
        query: {
        expression: 'orderId = :orderId',
        expressionValues: util.dynamodb.toMapValues({ ':orderId': orderId })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const items = ctx.result.items || [];
    if (items.length === 0) {
        // Order not found - return null (auth check will be skipped)
        ctx.stash.orderNotFound = true;
        return null;
    }
    
    const order = items[0];
    ctx.stash.order = order;
    
    // profileId is stored directly on the order
    ctx.stash.profileId = order.profileId;
    
    return order;
}
