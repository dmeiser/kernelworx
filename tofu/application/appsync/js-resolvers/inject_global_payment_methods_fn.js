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
    // 1. Add lowercase sortKey to each method
    // 2. Extract and sort keys using default .sort()
    // 3. Reorder methods based on sorted keys
    const withKeys = allMethods.map(m => ({ ...m, sortKey: m.name.toLowerCase() }));
    const sortedKeys = withKeys.map(m => m.sortKey);
    sortedKeys.sort();
    
    // Reorder based on sorted keys and strip the sortKey
    const sorted = sortedKeys.map(k => withKeys.find(m => m.sortKey === k));
    const result = sorted.map(m => ({ name: m.name, qrCodeUrl: m.qrCodeUrl }));
    
    return result;
}
