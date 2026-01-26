import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const targetAccountId = ctx.source.targetAccountId;
    
    // Normalize accountId to ensure ACCOUNT# prefix
    const dbAccountId = targetAccountId && targetAccountId.startsWith('ACCOUNT#') 
        ? targetAccountId 
        : `ACCOUNT#${targetAccountId}`;
    
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
            accountId: dbAccountId
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        return null;  // Return null if account not found
    }
    
    return ctx.result;
}
