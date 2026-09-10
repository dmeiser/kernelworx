/**
 * Pipeline resolver for updatePaymentMethod mutation.
 * Steps:
 * 1. validate_update_payment_method: Validates input and checks uniqueness
 * 2. update_payment_method: Updates the payment method name in DynamoDB
 * 3. batch_qr_urls: No-op for the rename payload (qrCodeUrl is null); keeps
 *    the PaymentMethod response shape consistent with the query pipelines
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
