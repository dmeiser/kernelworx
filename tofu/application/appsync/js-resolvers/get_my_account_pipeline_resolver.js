import { util } from '@aws-appsync/utils';

export function request(ctx) {
    return {};
}

export function response(ctx) {
    if (!ctx.prev.result) {
        util.error('Account not found', 'NotFound');
    }
    return ctx.prev.result;
}
