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

