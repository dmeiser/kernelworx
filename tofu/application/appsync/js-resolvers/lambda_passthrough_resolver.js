import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // Forward the AppSync context to the Lambda handler: the admin
    // dispatcher needs info.fieldName and is_admin needs identity.claims.
    // Lambda data sources require operation: 'Invoke' and a payload.
    // #748: no fabricated prev/stash payload — this resolver backs only
    // unit resolvers, which never run pipeline functions, so the old
    // payment-methods stash reads were dead code. Forward requestId so
    // handlers can correlate with AppSync logs.
    return {
        operation: 'Invoke',
        payload: {
            arguments: ctx.arguments,
            identity: ctx.identity,
            info: ctx.info,
            stash: ctx.stash,
            requestId: ctx.request?.headers?.['x-amzn-requestid'],
        }
    };
}

export function response(ctx) {
    // #329: Lambda handlers wrapped in the `lambda_handler` decorator return
    // structured error payloads (`__isError` + errorCode + message) instead of
    // raising, so the error code survives Lambda serialization. Surface it in
    // both errorType and extensions.errorCode for the frontend's typed
    // matchers.
    if (ctx.result && ctx.result.__isError) {
        util.error(ctx.result.message, ctx.result.errorCode, null, { errorCode: ctx.result.errorCode });
    }
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
