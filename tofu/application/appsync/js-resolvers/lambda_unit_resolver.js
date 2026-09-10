import { util } from '@aws-appsync/utils';

/**
 * Direct unit resolver for Lambda handlers wrapped in the `lambda_handler`
 * decorator (#337). Mirrors AppSync's default Lambda Invoke request (the
 * whole context as payload, so handlers keep reading event["arguments"] /
 * event["identity"]) and adds #329 structured-error detection so typed
 * error codes land in GraphQL extensions instead of leaking into the field
 * result as a type-coercion error.
 */
export function request(ctx) {
    return {
        operation: 'Invoke',
        payload: ctx,
    };
}

export function response(ctx) {
    // #329: decorated handlers return structured error payloads
    // (`__isError` + errorCode + message) instead of raising. Surface the
    // code in both errorType and extensions.errorCode for the frontend's
    // typed matchers.
    if (ctx.result && ctx.result.__isError) {
        util.error(ctx.result.message, ctx.result.errorCode, null, { errorCode: ctx.result.errorCode });
    }
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
