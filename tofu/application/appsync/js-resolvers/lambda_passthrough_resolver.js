import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // Forward context to Lambda including previous result and stash
    // Lambda data sources require operation: 'Invoke' and a payload
    
    // Get ownerAccountId from multiple possible stash locations:
    // 1. ctx.stash.profileOwner (set by verify_profile_write_access_fn)
    // 2. ctx.stash.profile.ownerAccountId (from the profile record)
    // 3. ctx.stash.ownerAccountId (set by other resolvers)
    const ownerAccountId = ctx.stash.profileOwner || 
                           (ctx.stash.profile && ctx.stash.profile.ownerAccountId) ||
                           ctx.stash.ownerAccountId || 
                           null;
    
    return {
        operation: 'Invoke',
        payload: {
            arguments: ctx.arguments,
            identity: ctx.identity,
            info: ctx.info,
            prev: {
                result: {
                    paymentMethods: ctx.stash.customPaymentMethods || [],
                    ownerAccountId: ownerAccountId
                }
            },
            stash: ctx.stash
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
