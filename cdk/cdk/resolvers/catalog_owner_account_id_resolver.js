export function request(ctx) {
    return {};
}

export function response(ctx) {
    const ownerAccountId = ctx.source.ownerAccountId;
    if (!ownerAccountId) return null;
    // Strip ACCOUNT# prefix if present
    if (ownerAccountId.startsWith('ACCOUNT#')) {
        return ownerAccountId.substring(8);
    }
    return ownerAccountId;
}
