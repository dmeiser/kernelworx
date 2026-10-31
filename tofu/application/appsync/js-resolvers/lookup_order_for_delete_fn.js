import { util } from '@aws-appsync/utils';
import { buildOrderLookupRequest } from './lib/order_lookup.js';

export function request(ctx) {
    // Same shared lookup as getOrder/lookup_order: a new-format ORDER#<campaign>#<uuid>
    // ID carries the campaignId, so read the base table strongly consistently.
    // The orderId-index GSI is only eventually consistent, so deleteOrder issued
    // right after createOrder could look up nothing and silently no-op (#717).
    return buildOrderLookupRequest(ctx.args.orderId);
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // GetItem returns the item directly; the legacy GSI fallback returns items.
    let order = null;
    if (ctx.result && Array.isArray(ctx.result.items)) {
        order = ctx.result.items[0] || null;
    } else {
        order = ctx.result || null;
    }

    // For delete, if order not found, that's OK (idempotent)
    // Just store null in stash and let delete function handle it
    if (!order) {
        ctx.stash.order = null;
        return null;
    }
    
    ctx.stash.order = order;
    return order;
}
