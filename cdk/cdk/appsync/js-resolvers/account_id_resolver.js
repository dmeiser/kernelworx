/**
 * Field resolver for Account.accountId
 * Returns the accountId as-is (with ACCOUNT# prefix).
 * All IDs in GraphQL should include their type prefix.
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    // Return accountId as-is with ACCOUNT# prefix
    return ctx.source.accountId;
}
