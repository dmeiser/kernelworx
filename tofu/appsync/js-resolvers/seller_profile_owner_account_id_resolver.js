/**
 * Field resolver for SellerProfile.ownerAccountId
 * Returns the ownerAccountId as-is (with ACCOUNT# prefix).
 * All IDs in GraphQL should include their type prefix.
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    // Return ownerAccountId as-is with ACCOUNT# prefix
    return ctx.source.ownerAccountId;
}
