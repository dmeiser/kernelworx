import { util } from '@aws-appsync/utils';
import { expectedOwnerKey } from './lib/owner_key.js';

export function request(ctx) {
    // accountId has ACCOUNT# prefix in DynamoDB
    const accountId = expectedOwnerKey(ctx.identity.sub);
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ accountId: accountId })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (!ctx.result) {
        util.error('Account not found', 'NOT_FOUND');
    }
    ctx.stash.account = ctx.result;
    return ctx.result;
}
