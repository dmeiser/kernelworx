/**
 * Query.listMyShares resolver
 * 
 * Returns all shares for the current user with profile data resolved via field resolvers.
 */

import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const targetAccountId = ctx.identity.sub.startsWith('ACCOUNT#') ? ctx.identity.sub : `ACCOUNT#${ctx.identity.sub}`;
    
    return {
        operation: 'Query',
        index: 'targetAccountId-index',
        query: {
            expression: 'targetAccountId = :targetAccountId',
            expressionValues: util.dynamodb.toMapValues({
                ':targetAccountId': targetAccountId
            })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Ensure we always return an array, never null
    const shares = ctx.result?.items || [];
    
    // Return shares with permissions - profile fields will be resolved by field resolvers
    // Strip PROFILE# prefix from profileId for GraphQL API response
    return shares.map(share => {
        const cleanProfileId = share.profileId && share.profileId.startsWith('PROFILE#')
            ? share.profileId.substring(8)
            : share.profileId;
        return {
            profileId: cleanProfileId,
            ownerAccountId: null, // Will be resolved by field resolver
            sellerName: null, // Will be resolved by field resolver  
            unitType: null, // Will be resolved by field resolver
            unitNumber: null, // Will be resolved by field resolver
            createdAt: share.createdAt || null, // Will be resolved by field resolver
            updatedAt: share.updatedAt || null, // Will be resolved by field resolver
            isOwner: false, // Always false for shared profiles
            permissions: share.permissions || ['READ', 'WRITE']
        };
    });
}
