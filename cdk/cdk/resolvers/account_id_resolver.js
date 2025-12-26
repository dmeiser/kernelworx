/**
 * Field resolver for Account.accountId
 * Strips the "ACCOUNT#" prefix from the raw DynamoDB value
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    const rawAccountId = ctx.source.accountId;
    
    if (!rawAccountId) {
        return null;
    }
    
    // Strip "ACCOUNT#" prefix if present
    if (rawAccountId.startsWith("ACCOUNT#")) {
        return rawAccountId.substring(8); // "ACCOUNT#".length = 8
    }
    
    return rawAccountId;
}
