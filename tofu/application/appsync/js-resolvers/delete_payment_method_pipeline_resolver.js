/**
 * Pipeline resolver for deletePaymentMethod mutation.
 * Steps:
 * 1. get_payment_method_for_delete: Validates and fetches preferences
 * 2. delete_payment_method_qr_code: Deletes the QR code object from S3 (best-effort)
 * 3. delete_payment_method_from_prefs: Removes from paymentMethods array
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    // Return true to indicate successful deletion
    return true;
}
