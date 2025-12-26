import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const targetAccountId = ctx.source.targetAccountId;
    
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
        accountId: 'ACCOUNT#' + targetAccountId
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        return null;  // Return null if account not found
    }
    
    return ctx.result;
}
