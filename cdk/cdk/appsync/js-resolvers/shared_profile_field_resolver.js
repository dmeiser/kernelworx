import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // Check if profile is already cached in source
    if (ctx.source._profile) {
        // Profile already fetched, return no-op
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ 
                ownerAccountId: 'NOOP',
                profileId: 'NOOP' 
            })
        };
    }
    
    let profileId = ctx.source.profileId;
    
    // Ensure profileId has PROFILE# prefix for GSI lookup
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    
    // Query using profileId-index GSI
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({
                ':profileId': dbProfileId
            })
        },
        limit: 1
    };
}

export function response(ctx) {
    const fieldName = ctx.info.fieldName;
    
    // Check if profile was already cached
    let profile = ctx.source._profile;
    
    if (!profile && ctx.result) {
        // Get profile from query result
        const items = ctx.result.items || [];
        if (items.length > 0) {
            profile = items[0];
            // Cache it for other field resolvers
            ctx.source._profile = profile;
        }
    }
    
    // Return null if no profile found
    if (!profile) {
        return null;
    }
    
    // Return the requested field
    switch (fieldName) {
        case 'sellerName':
            return profile.sellerName || null;
        case 'ownerAccountId':
            return profile.ownerAccountId || null;
        case 'unitType':
            return profile.unitType || null;
        case 'unitNumber':
            return profile.unitNumber || null;
        case 'createdAt':
            return profile.createdAt || null;
        case 'updatedAt':
            return profile.updatedAt || null;
        default:
            return null;
    }
}
