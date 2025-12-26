import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const orderId = ctx.args.orderId || ctx.args.input.orderId;
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
        util.error('Order not found', 'NotFound');
    }
    // Store order in stash for next function
    ctx.stash.order = items[0];
    return items[0];
}
