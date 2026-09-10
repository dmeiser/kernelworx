/**
 * Write step for the denormalized profile.latestCampaignId (#331), paired
 * with refresh_latest_campaign_lookup_fn in the updateCampaign and
 * deleteCampaign pipelines.
 *
 * When the lookup ran (ctx.stash.latestActiveCampaignResolved), write its
 * result onto the owning profile: SET latestCampaignId to the canonical
 * latest active campaign, or REMOVE the attribute when no active campaigns
 * remain. When the lookup skipped (earlyReturn — mutation cannot affect
 * latest-campaign semantics), this function is a no-op.
 *
 * The profile (with ownerAccountId + profileId keys) was fetched into the
 * stash by verify_profile_write_access earlier in the pipeline.
 *
 * Always returns ctx.prev.result so the mutation result is preserved.
 */
import { util, runtime } from '@aws-appsync/utils';

export function request(ctx) {
    if (!ctx.stash || ctx.stash.latestActiveCampaignResolved !== true) {
        return runtime.earlyReturn(ctx.prev.result);
    }

    const profile = ctx.stash.profile || {};
    if (!profile.ownerAccountId || !profile.profileId) {
        util.error('Profile not found in stash for latestCampaignId refresh', 'InternalError');
    }

    const key = util.dynamodb.toMapValues({
        ownerAccountId: profile.ownerAccountId,
        profileId: profile.profileId,
    });

    if (ctx.stash.latestActiveCampaignId) {
        return {
            operation: 'UpdateItem',
            key: key,
            update: {
                expression: 'SET latestCampaignId = :campaignId',
                expressionValues: util.dynamodb.toMapValues({
                    ':campaignId': ctx.stash.latestActiveCampaignId,
                }),
            },
        };
    }

    return {
        operation: 'UpdateItem',
        key: key,
        update: {
            expression: 'REMOVE latestCampaignId',
        },
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return ctx.prev.result;
}
