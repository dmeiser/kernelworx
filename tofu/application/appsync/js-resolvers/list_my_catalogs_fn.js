import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // Add ACCOUNT# prefix to match DynamoDB storage format
    const ownerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    
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
