import { util } from '@aws-appsync/utils';

export function request(ctx) {
    return {};
}

export function response(ctx) {
    if (!ctx.prev.result) {
        util.error('Account not found', 'NOT_FOUND');
    }
    return ctx.prev.result;
}
