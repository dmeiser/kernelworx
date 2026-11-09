// Custody router for createOrder (Show & Sell wave 3, r2 C-1).
//
// Runs AFTER the auth/campaign/catalog steps and BEFORE the legacy
// create_order_fn write step. Invokes the order-operations Lambda, which
// answers {"__continue__": true} for the NONE path (this function then
// returns ctx.prev.result and the pipeline runs the legacy steps exactly
// as the golden oracles pin them) or performs the CONSUME_SCOUT_CUSTODY
// transaction and returns the order, which this function early-returns —
// skipping the legacy write and the totals sync (the custody transaction
// already updated the totals atomically).
import { runtime, util } from '@aws-appsync/utils';

export function request(ctx) {
    return {
        operation: 'Invoke',
        payload: ctx,
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (ctx.result && ctx.result.__continue__) {
        // NONE path: proceed to the legacy create_order_fn + totals sync.
        return ctx.prev.result;
    }
    // Custody path (or a structured handler error surfaced by the Lambda
    // decorator): end the pipeline with this result.
    return runtime.earlyReturn(ctx.result);
}
