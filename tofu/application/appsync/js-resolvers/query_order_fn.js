import { util } from '@aws-appsync/utils';
import { buildOrderLookupRequest } from './lib/order_lookup.js';

export function request(ctx) {
    return buildOrderLookupRequest(ctx.args.orderId);
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    let order = null;
    if (ctx.result && Array.isArray(ctx.result.items)) {
        // Query result (legacy fallback)
        order = ctx.result.items[0] || null;
    } else {
        // GetItem result
        order = ctx.result || null;
    }
    if (!order) {
        // Order not found - return null (auth check will be skipped)
        ctx.stash.orderNotFound = true;
        return null;
    }

    ctx.stash.order = order;

    // profileId is stored directly on the order
    ctx.stash.profileId = order.profileId;

    return order;
}
