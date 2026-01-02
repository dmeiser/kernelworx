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
    // For delete, if order not found, that's OK (idempotent)
    // Just store null in stash and let delete function handle it
    if (items.length === 0) {
        ctx.stash.order = null;
        return null;
    }
    
    ctx.stash.order = items[0];
    return items[0];
}
