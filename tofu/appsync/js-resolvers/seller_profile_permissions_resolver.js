import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const callerAccountId = ctx.identity.sub;
    const ownerAccountId = ctx.source.ownerAccountId;
    const profileId = ctx.source.profileId;
    
    // Check ownership - handle both prefixed (ACCOUNT#xxx) and clean (xxx) ownerAccountId
    const expectedOwnerPrefixed = 'ACCOUNT#' + callerAccountId;
    if (expectedOwnerPrefixed === ownerAccountId || callerAccountId === ownerAccountId) {
        ctx.stash.isOwner = true;
        // Return a no-op query
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    // Normalize profileId to ensure PROFILE# prefix for share lookup
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    // Normalize targetAccountId to ensure ACCOUNT# prefix for share lookup
    const dbTargetAccountId = callerAccountId && callerAccountId.startsWith('ACCOUNT#') ? callerAccountId : `ACCOUNT#${callerAccountId}`;
    
    // Query shares table for share record: profileId + targetAccountId
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: dbProfileId, 
            targetAccountId: dbTargetAccountId 
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    // If owner, return full permissions
    if (ctx.stash.isOwner) {
        return ['READ', 'WRITE'];
    }
    
    if (ctx.error) {
        // Don't error out - just return null for permissions
        return null;
    }
    
    const share = ctx.result;
    
    // No share found - return null
    if (!share || !share.profileId) {
        return null;
    }
    
    // Return the permissions from the share
    if (share.permissions && Array.isArray(share.permissions)) {
        return share.permissions;
    }
    
    // Share exists but no valid permissions - return null
    return null;
}
