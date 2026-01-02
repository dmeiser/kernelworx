import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If already owner or profile was invalid/not found, skip this check
    if (ctx.stash.isOwner || ctx.stash.skipGetItem) {
        return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    const profileId = ctx.stash.profileId;
    
    // Additional validation - if profileId is not set or invalid, skip
    if (!profileId || !profileId.startsWith('PROFILE#')) {
        ctx.stash.hasWritePermission = false;
        return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    // Get share from shares table using profileId + targetAccountId (caller's sub)
    const targetAccountId = ctx.identity.sub.startsWith('ACCOUNT#') ? ctx.identity.sub : `ACCOUNT#${ctx.identity.sub}`;
    
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
        profileId: profileId, 
        targetAccountId: targetAccountId 
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    // If owner, pass through
    if (ctx.stash.isOwner) {
        ctx.stash.hasWritePermission = false; // Not needed
        return { authorized: true };
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const share = ctx.result;
    
    // No share found - not authorized (check profileId instead of PK)
    if (!share || !share.profileId) {
        ctx.stash.hasWritePermission = false;
        return { authorized: false };
    }
    
    // Check for WRITE permission
    if (share.permissions && Array.isArray(share.permissions) && share.permissions.includes('WRITE')) {
        ctx.stash.hasWritePermission = true;
        return { authorized: true };
    }
    
    // Share exists but no WRITE permission
    ctx.stash.hasWritePermission = false;
    return { authorized: false };
}
