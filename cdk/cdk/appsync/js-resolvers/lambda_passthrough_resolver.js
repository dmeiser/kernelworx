import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // Forward context to Lambda including previous result and stash
    // Lambda data sources require operation: 'Invoke' and a payload
    return {
        operation: 'Invoke',
        payload: {
            arguments: ctx.arguments,
            identity: ctx.identity,
            prev: {
                result: {
                    paymentMethods: ctx.stash.customPaymentMethods || [],
                    ownerAccountId: ctx.stash.ownerAccountId || null
                }
            },
            stash: ctx.stash
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.result;
}
