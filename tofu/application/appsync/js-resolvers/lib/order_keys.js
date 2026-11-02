// Shared ORDER#<campaign>#<suffix> key grammar for public (and authenticated)
// orders (KW-784 DRY-11 JS half). One builder/parser so the shape cannot drift
// across resolvers that mint or read an order id.
import { normalizeId, stripIdPrefix } from './ids.js';

export function buildOrderKey(campaignId, suffix) {
    const campaignWithoutPrefix = stripIdPrefix(campaignId, 'CAMPAIGN#');
    return normalizeId(campaignWithoutPrefix + '#' + suffix, 'ORDER#');
}

export function parseOrderKey(orderId) {
    if (typeof orderId !== 'string' || stripIdPrefix(orderId, 'ORDER#') === orderId) {
        return null;
    }
    const parts = orderId.split('#');
    if (parts.length !== 3 || !parts[1] || !parts[2]) {
        return null;
    }
    return {
        campaignId: normalizeId(parts[1], 'CAMPAIGN#'),
        suffix: parts[2]
    };
}
