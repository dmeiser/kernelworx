import { util } from '@aws-appsync/utils';

// Shared sellerName validation for profile create and update paths.
// Returns the trimmed name; util.errors with INVALID_INPUT when the rule fails.
export function validateSellerName(sellerName) {
    const trimmed = sellerName ? sellerName.trim() : '';
    if (!trimmed) {
        util.error('sellerName is required', 'INVALID_INPUT');
    }
    if ([...trimmed].length > 100) {
        util.error('sellerName cannot exceed 100 characters', 'INVALID_INPUT');
    }
    return trimmed;
}
