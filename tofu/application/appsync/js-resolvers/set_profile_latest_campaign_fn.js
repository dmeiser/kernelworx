/**
 * Denormalized write for #331: after create_campaign_fn PutItems the new
 * campaign, stamp the owning profile's latestCampaignId with the new
 * campaign's id.
 *
 * create_campaign_fn always creates campaigns with isActive=true and
 * createdAt=now, so a brand-new campaign is always the canonical
 * latest-by-createdAt ACTIVE campaign for the profile — an unconditional
 * SET cannot drift from the semantics the SellerProfile.latestCampaign
 * resolver implements.
 *
 * Runs inside the createCampaign pipeline (immediately after
 * create_campaign_fn) so the denormalized field is written in the same
 * mutation as the campaign and cannot drift. The profile (with
 * ownerAccountId + profileId keys) was fetched into the stash by
 * verify_profile_write_access earlier in the pipeline.
 */
import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profile = (ctx.stash && ctx.stash.profile) || {};
    const campaign = (ctx.stash && ctx.stash.createdCampaign) || ctx.prev.result || {};

    if (!profile.ownerAccountId || !profile.profileId) {
        util.error('Profile not found in stash for latestCampaignId write', 'InternalError');
    }
    if (!campaign.campaignId) {
        util.error('Created campaign not found for latestCampaignId write', 'InternalError');
    }

    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({
            ownerAccountId: profile.ownerAccountId,
            profileId: profile.profileId,
        }),
        update: {
            expression: 'SET latestCampaignId = :campaignId',
            expressionValues: util.dynamodb.toMapValues({
                ':campaignId': campaign.campaignId,
            }),
        },
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // The mutation result is the created campaign produced by
    // create_campaign_fn; pass it through untouched.
    return ctx.prev.result;
}
