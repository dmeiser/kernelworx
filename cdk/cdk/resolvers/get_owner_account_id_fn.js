import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // NONE datasource - no actual request needed
    return {
        version: '2018-05-29'
    };
}

export function response(ctx) {
    // Strip the ACCOUNT# prefix from ownerAccountId to get the actual account ID
    const ownerAccountId = ctx.source.ownerAccountId || '';
    if (ownerAccountId.startsWith('ACCOUNT#')) {
        return ownerAccountId.substring(8);
    }
    return ownerAccountId;
}
