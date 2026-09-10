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
    // #337: the decorated delete-profile-cascade handler returns a
    // structured error payload instead of raising.
    if (ctx.result && ctx.result.__isError) {
        util.error(ctx.result.message, ctx.result.errorCode, null, { errorCode: ctx.result.errorCode });
    }
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
