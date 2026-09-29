import { util } from '@aws-appsync/utils';
import { expectedOwnerKey } from './lib/owner_key.js';

export function request(ctx) {
    return {
        operation: 'GetItem',
        consistentRead: true,
        key: util.dynamodb.toMapValues({ accountId: expectedOwnerKey(ctx.identity.sub) })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    return ctx.result || null;
}
