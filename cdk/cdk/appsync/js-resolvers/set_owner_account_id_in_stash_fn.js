/**
 * Set owner account ID in stash for field resolvers.
 * 
 * For myPaymentMethods, the owner is the authenticated user.
 * This allows the qrCodeUrl field resolver to generate presigned URLs.
 */
export function request(ctx) {
    // Set owner account ID in stash for downstream resolvers
    ctx.stash.ownerAccountId = ctx.identity.sub;
    
    // Pass through - no DynamoDB operation needed
    return {};
}

export function response(ctx) {
    // Return payment methods array from previous step
    return ctx.prev.result;
}
