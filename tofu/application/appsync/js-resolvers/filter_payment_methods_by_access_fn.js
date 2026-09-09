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
    // 1. Add lowercase sortKey to each method
    // 2. Extract and sort keys using default .sort()
    // 3. Reorder methods based on sorted keys
    const withKeys = allMethods.map(m => ({ ...m, sortKey: m.name.toLowerCase() }));
    const sortedKeys = withKeys.map(m => m.sortKey);
    sortedKeys.sort();

    // Reorder based on sorted keys and strip the sortKey
    const sorted = sortedKeys.map(k => withKeys.find(m => m.sortKey === k));
    const result = sorted.map(m => ({
        name: m.name,
        qrCodeUrl: m.qrCodeUrl,
    }));

    return result;
}
