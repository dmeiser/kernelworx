import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If share already exists from previous check in pipeline, reject immediately
    if (ctx.stash && ctx.stash.existingShare) {
        util.error('This profile is already shared with this user.', 'ALREADY_SHARED');
    }

    const input = ctx.args && ctx.args.input ? ctx.args.input : {};
    var targetAccountId = ctx.stash ? ctx.stash.targetAccountId : undefined;
    const profileId = input.profileId || (ctx.stash && ctx.stash.invite ? ctx.stash.invite.profileId : undefined);
    const permissions = input.permissions || (ctx.stash && ctx.stash.invite ? ctx.stash.invite.permissions : undefined);
    const now = util.time.nowISO8601();
    
    // Get ownerAccountId from stash - check profile (shareProfileDirect) or invite (redeemProfileInvite)
    var ownerAccountId = null;
    if (ctx.stash && ctx.stash.profile && ctx.stash.profile.ownerAccountId) {
        ownerAccountId = ctx.stash.profile.ownerAccountId;
    } else if (ctx.stash && ctx.stash.invite && ctx.stash.invite.ownerAccountId) {
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

    const callerSub = ctx.identity && ctx.identity.sub ? ctx.identity.sub : '';
    const shareItem = {
        profileId: dbProfileId,
        targetAccountId: targetAccountId,
        shareId: shareId,
        permissions: permissions,
        ownerAccountId: ownerAccountId,  // Store for BatchGetItem lookup
        createdByAccountId: `ACCOUNT#${callerSub}`,
        createdAt: now
    };
    
    // Store full share item in stash for response
    if (ctx.stash) {
        ctx.stash.shareItem = shareItem;
    }
    
    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({ profileId: dbProfileId, targetAccountId: targetAccountId }),
        attributeValues: util.dynamodb.toMapValues(shareItem),
        condition: {
            expression: 'attribute_not_exists(profileId) AND attribute_not_exists(targetAccountId)'
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException' || (ctx.error.message && ctx.error.message.includes('ConditionalCheckFailed'))) {
            util.error('This profile is already shared with this user.', 'ALREADY_SHARED');
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    // Return the share item with targetAccountId stripped of ACCOUNT# prefix
    // Keep profileId with PROFILE# prefix for consistency with createSellerProfile
    const shareItem = (ctx.stash && ctx.stash.shareItem) ? ctx.stash.shareItem : (ctx.result || {});
    const cleanTargetAccountId = shareItem.targetAccountId && shareItem.targetAccountId.startsWith('ACCOUNT#')
        ? shareItem.targetAccountId.substring(8)
        : shareItem.targetAccountId;
    
    return {
        ...shareItem,
        targetAccountId: cleanTargetAccountId
    };
}
