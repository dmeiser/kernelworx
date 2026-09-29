export function normalizeId(value, prefix) {
    if (typeof value !== 'string' || !value) {
        return null;
    }
    return value.startsWith(prefix) ? value : prefix + value;
}

export function stripIdPrefix(value, prefix) {
    if (typeof value !== 'string' || !value) {
        return value;
    }
    return value.startsWith(prefix) ? value.substring(prefix.length) : value;
}

// normalizeId returns null for a falsy value, but a DynamoDB key attribute may
// never be null. A resolver building a key from a possibly-absent value uses
// this to keep a well-formed placeholder instead of copying the fallback into
// its own local shim.
export function normalizeIdOrPrefix(value, prefix) {
    const normalized = normalizeId(value, prefix);
    return normalized === null ? prefix : normalized;
}

export function parseEmbeddedCampaignId(orderId) {
    if (typeof orderId !== 'string' || !orderId.startsWith('ORDER#')) {
        return null;
    }
    const parts = orderId.split('#');
    // New format: ORDER#<campaignId without CAMPAIGN# prefix>#<uuid>
    if (parts.length !== 3 || !parts[1] || !parts[2]) {
        return null;
    }
    return normalizeId(parts[1], 'CAMPAIGN#');
}

// The inverse of parseEmbeddedCampaignId, kept beside it so the composite
// order-id format has a single owner. `suffix` is the trailing uuid segment.
// Built by concatenation, not a template literal: lib/ids.js is inlined by
// esbuild into resolvers that tofu loads with templatefile(), where every
// template placeholder would be read as a Terraform expression (#570).
export function buildOrderId(campaignId, suffix) {
    return 'ORDER#' + stripIdPrefix(campaignId, 'CAMPAIGN#') + '#' + suffix;
}

