import { util } from '@aws-appsync/utils';
import { normalizeId } from './lib/ids.js';

export function request(ctx) {
    const profileId = ctx.args.profileId;
    
    // Add PROFILE# prefix if not present (frontend sends clean UUIDs)
    const dbProfileId = normalizeId(profileId, 'PROFILE#');
    
    // Validate profileId exists
    if (!profileId) {
        // Invalid - set flags to deny and skip Query
        ctx.stash.isOwner = false;
        ctx.stash.hasWritePermission = false;
        ctx.stash.skipGetItem = true;
        return {
            operation: 'Query',
            index: 'profileId-index',
            query: {
                expression: 'profileId = :profileId',
                expressionValues: util.dynamodb.toMapValues({ ':profileId': 'NOOP' })
            }
        };
    }
    
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': dbProfileId })
        }
    };
}

export function response(ctx) {
    // Check if we skipped Query due to validation
    if (ctx.stash.skipGetItem) {
        return { authorized: false };
    }
    
    if (ctx.error) {
        // If there's a DynamoDB error (e.g., invalid key format), treat as unauthorized
        ctx.stash.isOwner = false;
        ctx.stash.hasWritePermission = false;
        return { authorized: false };
    }
    
    const profile = ctx.result.items && ctx.result.items[0];
    
    if (!profile) {
        // Profile not found - return empty list
        ctx.stash.isOwner = false;
        ctx.stash.hasWritePermission = false;
        return { authorized: false };
    }
    
    // Check if caller is owner - ownerAccountId now has 'ACCOUNT#' prefix
    const callerSub = ctx.identity && ctx.identity.sub;
    const profileOwner = profile.ownerAccountId;
    
    if (profileOwner === normalizeId(callerSub, 'ACCOUNT#')) {
        ctx.stash.isOwner = true;
        ctx.stash.hasWritePermission = true;
        return { authorized: true };
    }
    
    // Not owner - check for WRITE permission via share
    ctx.stash.isOwner = false;
    // Store the profile's current owner so check_write_permission_fn can reject
    // stale shares (created before an ownership transfer) whose ownerAccountId
    // no longer matches (#432). Mirrors verify_profile_write_access_fn.
    ctx.stash.profileOwner = profile.ownerAccountId;
    
    // Only set profileId if it's valid, otherwise skip second function
    const profileIdArg = ctx.args.profileId;
    const normalizedProfileIdArg = normalizeId(profileIdArg, 'PROFILE#');
    if (normalizedProfileIdArg) {
        ctx.stash.profileId = normalizedProfileIdArg;
    } else {
        ctx.stash.hasWritePermission = false;
        ctx.stash.skipGetItem = true; // Signal to skip next function
    }
    
    // Get share to check permissions
    return profile;
}
