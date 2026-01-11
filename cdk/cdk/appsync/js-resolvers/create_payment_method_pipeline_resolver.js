/**
 * Pipeline resolver for createPaymentMethod mutation.
 * 
 * Creates a custom payment method for the authenticated user:
 * 1. Validate name (not reserved, unique, max 50 chars)
 * 2. Create in DynamoDB preferences
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
