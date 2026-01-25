/**
 * Check authorization and determine access level for payment methods.
 * 
 * This function checks if the caller has access to the profile and determines
 * whether they can see QR codes based on ownership/WRITE/READ permissions.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profile = ctx.stash.profile;
    const callerId = ctx.identity.sub;
    
    if (!profile) {
        util.error('Profile not found', 'NotFound');
    }
    
    // Store owner account ID for next steps (already has ACCOUNT# prefix)
    ctx.stash.ownerAccountId = profile.ownerAccountId;
    
    // Check if caller is owner (profile.ownerAccountId has ACCOUNT# prefix)
    const callerAccountId = callerId.startsWith('ACCOUNT#') ? callerId : `ACCOUNT#${callerId}`;
    if (profile.ownerAccountId === callerAccountId) {
        ctx.stash.accessLevel = 'OWNER';
        ctx.stash.canSeeQR = true;
        // Return NOOP GetItem - must have operation for data source
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    // Check if caller has share access in the shares table
    // Shares table uses profileId (with PROFILE# prefix) and targetAccountId (with ACCOUNT# prefix)
    const dbProfileId = profile.profileId.startsWith('PROFILE#') ? profile.profileId : `PROFILE#${profile.profileId}`;
    
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
            profileId: dbProfileId,
            targetAccountId: callerAccountId
        }),
        consistentRead: false
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const accessLevel = ctx.stash.accessLevel;
    
    // If already determined to be OWNER, skip share check
    if (accessLevel === 'OWNER') {
        return {};
    }
    
    // Check share permissions
    const share = ctx.result;
    if (!share) {
        util.error('Unauthorized access to profile', 'Forbidden');
    }
    
    const permissions = share.permissions || [];
    
    if (permissions.includes('WRITE')) {
        ctx.stash.accessLevel = 'WRITE';
        ctx.stash.canSeeQR = true;  // WRITE users can see QR codes
    } else if (permissions.includes('READ')) {
        ctx.stash.accessLevel = 'READ';
        ctx.stash.canSeeQR = false;  // READ users cannot see QR codes
    } else {
        util.error('Insufficient permissions', 'Forbidden');
    }
    
    return {};
}
