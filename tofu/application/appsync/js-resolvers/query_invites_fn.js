import { util } from '@aws-appsync/utils';
import { normalizeId } from './lib/ids.js';

export function request(ctx) {
    // Write access is required, matching the schema's "The caller must have
    // write access to the profile" and the sibling listSharesByProfile, which
    // gates on the same pair of pipeline functions. Upstream
    // verify_profile_write_access_or_owner_fn + check_write_permission_fn have
    // already denied a caller with no share, a READ-only share, and a stale
    // post-transfer WRITE share (#432), so honouring hasWritePermission here
    // does not widen access beyond what those two established.
    if (!ctx.stash.isOwner && !ctx.stash.hasWritePermission) {
        return {
            operation: 'Query',
            index: 'profileId-index',
            query: {
                expression: 'profileId = :profileId',
                expressionValues: util.dynamodb.toMapValues({ ':profileId': 'NOOP' })
            }
        };
    }
    
    const profileId = ctx.args.profileId;
    // Add PROFILE# prefix for DynamoDB query
    const dbProfileId = normalizeId(profileId, 'PROFILE#');
    
    // Query invites for this profile using profileId-index GSI
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({
                ':profileId': dbProfileId
            })
        },
        scanIndexForward: false  // Sort by SK descending (newest first if SK is timestamp-based)
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Same write-access gate as request(): the two must not disagree, or a
    // WRITE co-owner would query the index and then have the rows discarded.
    if (!ctx.stash.isOwner && !ctx.stash.hasWritePermission) {
        return [];
    }
    
    const items = ctx.result.items || [];
    const nowEpochSeconds = Math.floor(util.time.nowEpochSeconds());
    
    // Transform items to match GraphQL schema, filtering out expired and used invites
    // Note: AppSync JS runtime does not support 'continue', so we use filter logic instead
    const validItems = items.filter((item) => {
        // Skip expired invites (expiresAt is epoch seconds)
        if (item.expiresAt && item.expiresAt < nowEpochSeconds) {
            return false;
        }
        
        // Skip used invites (has used=true or usedAt set)
        if (item.used === true || item.usedAt) {
            return false;
        }
        
        return true;
    });
    
    const transformedItems = validItems.map((item) => {
        return {
            inviteCode: item.inviteCode,
            profileId: item.profileId, // Keep PROFILE# prefix
            permissions: item.permissions,
            // Convert epoch seconds to ISO 8601 string
            expiresAt: util.time.epochMilliSecondsToISO8601(item.expiresAt * 1000),
            createdAt: item.createdAt,
            // Map createdBy to createdByAccountId
            createdByAccountId: item.createdBy
        };
    });
    
    return transformedItems;
}
