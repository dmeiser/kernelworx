import { util } from '@aws-appsync/utils';

/**
 * listMyShares pipeline resolver (Query.listMyShares).
 * Passes through the merged SharedProfile array produced by
 * batch_get_shared_profiles_fn. Migrated from the list-my-shares Lambda
 * invocation (#334) to remove per-call Lambda latency and cost.
 */

export function request(ctx) {
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.prev.result || [];
}
