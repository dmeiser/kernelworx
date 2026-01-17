/**
 * Pipeline resolver for myPaymentMethods query.
 * 
 * Returns payment methods for the authenticated user:
 * 1. Fetch custom methods from DynamoDB
 * 2. Inject global methods (Cash, Check)
 * 3. Return final array
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}

