import { util } from '@aws-appsync/utils';

/**
 * Field resolver for SellerProfile.profileId
 * Returns the profileId as-is (with PROFILE# prefix).
 * 
 * All IDs in GraphQL should include their type prefix (PROFILE#, CATALOG#, etc.)
 * The prefix is only stripped in URLs for cleaner paths (e.g., /scouts/UUID)
 */
export function request(ctx) {
    return {};
}

export function response(ctx) {
    // Return profileId as-is, with PROFILE# prefix
    return ctx.source.profileId;
}
