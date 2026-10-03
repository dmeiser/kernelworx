import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    return {
        operation: 'GetItem',
        consistentRead: true,
        key: util.dynamodb.toMapValues({ accountId: normalizeIdOrPrefix(ctx.identity.sub, 'ACCOUNT#') })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    return ctx.result || null;
}
