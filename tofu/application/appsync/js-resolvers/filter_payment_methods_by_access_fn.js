/**
 * Filter and inject global payment methods based on access level.
 *
 * This function:
 * - Adds global methods (Cash, Check)
 * - Filters out QR codes for READ users (before the batch QR signing step)
 * - Sorts alphabetically (case-insensitive)
 *
 * QR signing context (owner/profile) lives in the stash; the batch_qr_urls
 * step at the end of the pipeline consumes it.
 *
 * Note: APPSYNC_JS doesn't support passing functions as arguments (no comparator
 * in .sort()). We use a workaround: extract lowercase keys, sort them, then
 * reorder the original array.
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    // Get custom payment methods from previous step (get_owner_payment_methods)
    const customPaymentMethods = ctx.prev.result || [];
    const canSeeQR = ctx.stash.canSeeQR;

    // Filter QR codes based on access level. Runs before the batch QR
    // signing step, so nulling here means the key is never signed.
    const filteredMethods = customPaymentMethods.map(method => {
        const filtered = { ...method };
        if (!canSeeQR && filtered.qrCodeUrl) {
            filtered.qrCodeUrl = null;  // Remove QR URL for READ users
        }
        return filtered;
    });

    // Add global methods (no QR codes)
    const globalMethods = [
        { name: 'Cash', qrCodeUrl: null },
        { name: 'Check', qrCodeUrl: null }
    ];

    // Combine all methods
    const allMethods = [...globalMethods, ...filteredMethods];

    // Sort alphabetically (case-insensitive) using APPSYNC_JS-compatible approach:
    // Build the lookup index once, sort the keys, and reorder.
    // NOTE: relies on case-insensitively-unique payment method names, enforced by
    // payment_methods.py:_check_duplicate_name and validate_create_payment_method_fn.js.
    const byKey = {};
    for (const m of allMethods) {
        byKey[m.name.toLowerCase()] = m;
    }
    const sortedKeys = Object.keys(byKey);
    sortedKeys.sort();

    const result = sortedKeys.map(k => ({
        name: byKey[k].name,
        qrCodeUrl: byKey[k].qrCodeUrl,
    }));

    return result;
}
