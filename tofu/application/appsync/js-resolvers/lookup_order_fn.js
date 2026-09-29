import { util } from '@aws-appsync/utils';
import { buildOrderLookupRequest } from './lib/order_lookup.js';

export function request(ctx) {
    const orderId = ctx.args.orderId || ctx.args.input.orderId;
    return buildOrderLookupRequest(orderId);
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
        util.error('Order not found', 'NOT_FOUND');
    }
    // Store order in stash for next function
    ctx.stash.order = order;
    return order;
}
