/**
 * Pipeline resolver for deletePaymentMethod mutation.
 * Steps:
 * 1. get_payment_method_for_delete: Validates and fetches preferences
 * 2. delete_qr_code: Deletes S3 object if QR exists (Lambda)
 * 3. delete_payment_method_from_prefs: Removes from paymentMethods array
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    // Return true to indicate successful deletion (UpdateItem returns null by default)
    return true;
}
