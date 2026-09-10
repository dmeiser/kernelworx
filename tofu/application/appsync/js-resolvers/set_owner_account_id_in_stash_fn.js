/**
 * Set owner account ID in stash for the batch QR URL signing step.
 * 
 * For myPaymentMethods, the owner is the authenticated user.
 * batch_qr_urls uses this (with no profileId) to authorize signing.
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
