import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    const callerAccountId = ctx.identity.sub;
    const ownerAccountId = ctx.source.ownerAccountId;
    const profileId = ctx.source.profileId;
    
    // Check ownership - handle both prefixed (ACCOUNT#xxx) and clean (xxx) ownerAccountId
    const expectedOwnerPrefixed = normalizeIdOrPrefix(callerAccountId, 'ACCOUNT#');
    if (expectedOwnerPrefixed === ownerAccountId || callerAccountId === ownerAccountId) {
        ctx.stash.isOwner = true;
        // Return a no-op query
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    // Normalize profileId to ensure PROFILE# prefix for share lookup
    const dbProfileId = normalizeIdOrPrefix(profileId, 'PROFILE#');
    // Normalize targetAccountId to ensure ACCOUNT# prefix for share lookup
    const dbTargetAccountId = normalizeIdOrPrefix(callerAccountId, 'ACCOUNT#');
    
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
        // Fail closed loudly: a swallowed datastore error is indistinguishable from
        // a real "no permissions" answer, so a throttle silently strips write access
        // from the UI and never reaches AppSync's resolver error metrics (#553).
        util.error(ctx.error.message, ctx.error.type);
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
