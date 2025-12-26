import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const createdBy = ctx.identity.sub;
    return {
        operation: 'Query',
        index: 'GSI1',
        query: {
            expression: 'createdBy = :createdBy',
            expressionValues: util.dynamodb.toMapValues({ ':createdBy': createdBy })
        },
        scanIndexForward: false  // Most recent first
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Filter out inactive shared campaigns (for loop instead of filter())
    const items = ctx.result.items || [];
    const activeItems = [];
    for (const item of items) {
        if (item.isActive !== false) {
            activeItems.push(item);
        }
    }
    return activeItems;
}
