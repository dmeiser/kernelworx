import { util } from '@aws-appsync/utils';

/**
 * Field resolver for ownerAccountId
 * Returns the ownerAccountId as-is (with ACCOUNT# prefix).
 * All IDs in GraphQL should include their type prefix.
 */
export function request(ctx) {
    // NONE datasource - no actual request needed
    return {
        version: '2018-05-29'
    };
}

export function response(ctx) {
    // Return ownerAccountId as-is with ACCOUNT# prefix
    return ctx.source.ownerAccountId;
}
