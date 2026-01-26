import { util } from '@aws-appsync/utils';

/**
 * List all profiles owned by the current user.
 * Query profiles table by ownerAccountId (partition key).
 */
export function request(ctx) {
    const accountId = `ACCOUNT#${ctx.identity.sub}`;
    
    // Using low-level DynamoDB API to query by partition key
    const request = {
        operation: 'Query',
        index: null,
        query: {
            expression: 'ownerAccountId = :accountId',
            expressionValues: {
                ':accountId': { S: accountId }
            }
        }
    };
    
    return request;
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const items = ctx.result.items || [];
    
    // Filter out any incomplete/deleted records (must have createdAt)
    const validItems = items.filter(item => item.createdAt);
    
    // Convert from DynamoDB format and add computed fields
    return validItems.map(item => ({
        ...item,
        isOwner: true,
        permissions: ["READ", "WRITE"]
    }));
}
