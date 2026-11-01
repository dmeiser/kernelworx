/**
 * Inject global payment methods (Cash, Check) and sort alphabetically.
 * 
 * This function takes custom payment methods from stash, adds the global
 * methods, and returns a sorted list.
 * 
 * Note: APPSYNC_JS doesn't support passing functions as arguments (no comparator
 * in .sort()). We use a workaround: extract lowercase keys, sort them, then
 * reorder the original array.
 */
export function request(ctx) {
    // Pass through - no DynamoDB operation needed
    return {};
}

export function response(ctx) {
    // Get custom methods from previous step
    const customMethods = ctx.prev.result || [];
    
    // Global methods (always available, never stored in DB)
    const globalMethods = [
        { name: 'Cash', qrCodeUrl: null },
        { name: 'Check', qrCodeUrl: null }
    ];
    
    // Combine all methods
    const allMethods = [...globalMethods, ...customMethods];
    
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
