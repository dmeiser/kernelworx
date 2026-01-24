import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const isPublic = ctx.args.isPublic !== undefined ? ctx.args.isPublic : true;
    const isPublicStr = isPublic ? 'true' : 'false';
    
    // Query catalogs by isPublic + createdAt using the isPublic-createdAt-index
    return {
        operation: 'Query',
        index: 'isPublic-createdAt-index',
        query: {
            expression: 'isPublicStr = :isPublic',
            expressionValues: util.dynamodb.toMapValues({
                ':isPublic': isPublicStr
            })
        },
        scanIndexForward: false  // Sort by createdAt descending (newest first)
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const items = ctx.result.items || [];
    return items;
}
