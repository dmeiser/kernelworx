import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const input = ctx.args && ctx.args.input ? ctx.args.input : {};
    const hasSharedCampaignCode = !!(input.sharedCampaignCode && (typeof input.sharedCampaignCode !== 'string' || input.sharedCampaignCode.trim() !== ''));
    const shareWithCreator = input.shareWithCreator === true;
    const sharedCampaign = ctx.stash && ctx.stash.sharedCampaign;

    if (!hasSharedCampaignCode || !shareWithCreator || !sharedCampaign) {
        ctx.stash.skipShare = true;
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({
                profileId: 'NOOP',
                targetAccountId: 'NOOP',
            }),
        };
    }

    const createdBy = sharedCampaign.createdBy;
    if (!createdBy) {
        ctx.stash.skipShare = true;
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({
                profileId: 'NOOP',
                targetAccountId: 'NOOP',
            }),
        };
    }

    const creatorRaw = (typeof createdBy === 'string' && createdBy.startsWith('ACCOUNT#'))
        ? createdBy.substring(8)
        : createdBy;

    const profile = ctx.stash && ctx.stash.profile ? ctx.stash.profile : {};
    const ownerAccountId = profile.ownerAccountId || (ctx.stash && ctx.stash.profileOwner) || '';
    const ownerRaw = (typeof ownerAccountId === 'string' && ownerAccountId.startsWith('ACCOUNT#'))
        ? ownerAccountId.substring(8)
        : ownerAccountId;

    if (creatorRaw === ownerRaw) {
        ctx.stash.skipShare = true;
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({
                profileId: 'NOOP',
                targetAccountId: 'NOOP',
            }),
        };
    }

    const rawProfileId = input.profileId || profile.profileId;
    const dbProfileId = (typeof rawProfileId === 'string' && rawProfileId.startsWith('PROFILE#'))
        ? rawProfileId
        : 'PROFILE#' + rawProfileId;

    const targetAccountId = 'ACCOUNT#' + creatorRaw;
    const callerSub = ctx.identity && ctx.identity.sub ? ctx.identity.sub : '';
    const callerAccountId = callerSub.startsWith('ACCOUNT#') ? callerSub : 'ACCOUNT#' + callerSub;
    const dbOwnerAccountId = ownerAccountId.startsWith('ACCOUNT#') ? ownerAccountId : 'ACCOUNT#' + ownerAccountId;
    const shareId = 'SHARE#' + util.autoId();
    const now = util.time.nowISO8601();

    const shareItem = {
        profileId: dbProfileId,
        targetAccountId: targetAccountId,
        shareId: shareId,
        permissions: ['READ'],
        ownerAccountId: dbOwnerAccountId,
        createdAt: now,
        createdByAccountId: callerAccountId,
    };

    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({
            profileId: dbProfileId,
            targetAccountId: targetAccountId,
        }),
        attributeValues: util.dynamodb.toMapValues(shareItem),
        condition: {
            expression: 'attribute_not_exists(profileId) AND attribute_not_exists(targetAccountId)',
        },
    };
}

export function response(ctx) {
    if (ctx.stash && ctx.stash.skipShare) {
        return null;
    }

    if (ctx.error) {
        if (
            ctx.error.type === 'DynamoDB:ConditionalCheckFailedException' ||
            (ctx.error.message && ctx.error.message.includes('ConditionalCheckFailed'))
        ) {
            // Share already exists, skip without failing campaign creation
            return null;
        }
        util.error(ctx.error.message, ctx.error.type);
    }

    return ctx.result;
}
