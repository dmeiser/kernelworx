import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const ownerAccountId = ctx.identity.sub;
    
    // Query catalogs created by this user using the ownerAccountId-index
    return {
        operation: 'Query',
        index: 'ownerAccountId-index',
        query: {
            expression: 'ownerAccountId = :ownerAccountId',
            expressionValues: util.dynamodb.toMapValues({
                ':ownerAccountId': ownerAccountId
            })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const items = ctx.result.items || [];
    return items;
}
