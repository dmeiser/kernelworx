/**
 * Pipeline resolver for myPaymentMethods query.
 * 
 * Returns payment methods for the authenticated user:
 * 1. Fetch custom methods from DynamoDB
 * 2. Inject global methods (Cash, Check)
 * 3. Set owner account ID in stash for field resolvers
 * 
 * The PaymentMethod.qrCodeUrl field resolver will handle generating presigned URLs.
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    // Return payment methods array
    return ctx.prev.result;
}

