/**
 * Pipeline resolver for deletePaymentMethodQRCode mutation.
 * Steps:
 * 1. delete_payment_method_qr: Lambda deletes S3 object and clears qrCodeUrl in DynamoDB
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
