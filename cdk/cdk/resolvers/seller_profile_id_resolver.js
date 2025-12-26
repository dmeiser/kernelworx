import { util } from '@aws-appsync/utils';

/**
 * Field resolver for SellerProfile.profileId
 * Strips the 'PROFILE#' prefix from the stored profileId
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    const rawProfileId = ctx.source.profileId;
    
    // If profileId starts with 'PROFILE#', strip it
    if (rawProfileId && rawProfileId.startsWith('PROFILE#')) {
        return rawProfileId.substring(8); // 'PROFILE#'.length === 8
    }
    
    // Otherwise return as-is
    return rawProfileId;
}
