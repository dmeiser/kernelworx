import { util } from '@aws-appsync/utils';

export function request(ctx) {
    return {
        operation: 'Invoke',
        payload: {
            arguments: ctx.args,
            identity: ctx.identity,
            stash: ctx.stash,
        },
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
