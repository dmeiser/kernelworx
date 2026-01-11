/**
 * Pipeline resolver for myPaymentMethods query.
 * 
 * Returns payment methods for the authenticated user:
 * 1. Fetch custom methods from DynamoDB
 * 2. Inject global methods (Cash, Check)
 * 3. Sort alphabetically
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    // Return final result from last pipeline function
    return ctx.prev.result;
}
