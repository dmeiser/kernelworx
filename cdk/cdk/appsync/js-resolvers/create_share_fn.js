import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const input = ctx.args.input;
    var targetAccountId = ctx.stash.targetAccountId;
    const profileId = input.profileId || ctx.stash.invite.profileId;
    const permissions = input.permissions || ctx.stash.invite.permissions;
    const now = util.time.nowISO8601();
    
    // Get ownerAccountId from stash - check profile (shareProfileDirect) or invite (redeemProfileInvite)
    var ownerAccountId = null;
    if (ctx.stash.profile && ctx.stash.profile.ownerAccountId) {
        ownerAccountId = ctx.stash.profile.ownerAccountId;
    } else if (ctx.stash.invite && ctx.stash.invite.ownerAccountId) {
        ownerAccountId = ctx.stash.invite.ownerAccountId;
    }
    
    // Validate that ownerAccountId was found
    if (!ownerAccountId) {
        util.error('Failed to determine profile owner', 'InternalServerError');
    }
    
    // Ensure targetAccountId has ACCOUNT# prefix
    if (targetAccountId && !targetAccountId.startsWith('ACCOUNT#')) {
        targetAccountId = `ACCOUNT#${targetAccountId}`;
    }
    
    // Generate shareId for backward compatibility with tests
    // Format: SHARE#{targetAccountId} (targetAccountId already has ACCOUNT# prefix)
    const shareId = `SHARE#${targetAccountId}`;
    
    // Normalize profileId to ensure PROFILE# prefix is used when storing shares
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;

    const shareItem = {
        profileId: dbProfileId,
        targetAccountId: targetAccountId,
        shareId: shareId,
        permissions: permissions,
        ownerAccountId: ownerAccountId,  // Store for BatchGetItem lookup
        createdByAccountId: ctx.identity.sub,
        createdAt: now
    };
    
    // Store full share item in stash for response
    ctx.stash.shareItem = shareItem;
    
    // Use PutItem without condition to support both create and update (upsert)
    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({ profileId: dbProfileId, targetAccountId: targetAccountId }),
        attributeValues: util.dynamodb.toMapValues(shareItem)
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Return the share item with targetAccountId stripped of ACCOUNT# prefix
    // Keep profileId with PROFILE# prefix for consistency with createSellerProfile
    const shareItem = ctx.stash.shareItem;
    const cleanTargetAccountId = shareItem.targetAccountId && shareItem.targetAccountId.startsWith('ACCOUNT#')
        ? shareItem.targetAccountId.substring(8)
        : shareItem.targetAccountId;
    
    return {
        ...shareItem,
        targetAccountId: cleanTargetAccountId
    };
}
