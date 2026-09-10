/**
 * Pipeline resolver for myPaymentMethods query.
 * 
 * Returns payment methods for the authenticated user:
 * 1. Fetch custom methods from DynamoDB
 * 2. Inject global methods (Cash, Check)
 * 3. Set owner account ID in stash for the batch QR URL step
 * 4. Batch-generate all presigned QR URLs in one Lambda invocation
 *
 * The final batch step maps each method's qrCodeUrl to a fresh presigned URL
 * (replaces the per-method field resolver; see #330).
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    // Return payment methods array
    return ctx.prev.result;
}

