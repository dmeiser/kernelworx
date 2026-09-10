/**
 * Pipeline resolver for confirmPaymentMethodQRCodeUpload mutation.
 *
 * Steps:
 * 1. confirm_qr_upload: Invoke the confirm-qr-upload Lambda (validates the S3
 *    object, deletes any replaced QR object, stores the new key) which returns
 *    the payment method with its raw S3 key
 * 2. batch_qr_urls: Sign the returned key into a fresh presigned URL in one
 *    Lambda invocation (same batch step as the query pipelines; #330)
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    return ctx.prev.result;
}
