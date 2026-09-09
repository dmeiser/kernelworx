/**
 * Recompute step for the denormalized profile.latestCampaignId (#331).
 *
 * Runs in the updateCampaign pipeline (after update_campaign_fn) and the
 * deleteCampaign pipeline (after delete_campaign_fn), paired with
 * refresh_latest_campaign_write_fn. Whenever a mutation can change which
 * campaign is the "latest ACTIVE by createdAt" for a profile —
 * updateCampaign touching isActive, or deleteCampaign removing a campaign —
 * this function re-queries the profileId-createdAt-index with the same
 * active-only filter the SellerProfile.latestCampaign resolver implements
 * and stashes the canonical latest active campaign id
 * (ctx.stash.latestActiveCampaignId, null when none remains).
 *
 * Skips (runtime.earlyReturn) when the mutation cannot affect the semantics
 * (updateCampaign without an isActive change) or when there is no campaign
 * in the stash (idempotent deleteCampaign of an already-gone campaign). In
 * the skip case refresh_latest_campaign_write_fn is a no-op as well.
 *
 * Always returns ctx.prev.result so the mutation result is preserved for
 * the rest of the pipeline.
 */
import { util, runtime } from '@aws-appsync/utils';

export function request(ctx) {
    const campaign = ctx.stash && ctx.stash.campaign;
    const fieldName = ctx.info && ctx.info.fieldName;

    let shouldRefresh = false;
    if (fieldName === 'deleteCampaign') {
        shouldRefresh = !!campaign;
    } else if (fieldName === 'updateCampaign') {
        const input = (ctx.args && ctx.args.input) || {};
        shouldRefresh = !!campaign && input.isActive !== undefined;
    }

    if (!shouldRefresh) {
        return runtime.earlyReturn(ctx.prev.result);
    }

    const rawProfileId = campaign.profileId;
    const dbProfileId = (typeof rawProfileId === 'string' && rawProfileId.startsWith('PROFILE#'))
        ? rawProfileId
        : 'PROFILE#' + rawProfileId;

    return {
        operation: 'Query',
        index: 'profileId-createdAt-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': dbProfileId })
        },
        filter: {
            expression: 'isActive = :isActive OR attribute_not_exists(isActive)',
            expressionValues: util.dynamodb.toMapValues({ ':isActive': true })
        },
        scanIndexForward: false
        // No limit: DynamoDB applies limit BEFORE filter, so filtering must
        // happen over the full result (same rationale as the
        // SellerProfile.latestCampaign resolver).
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const items = (ctx.result && ctx.result.items) || [];
    const campaign = ctx.stash.campaign;
    const fieldName = ctx.info && ctx.info.fieldName;
    const input = (ctx.args && ctx.args.input) || {};
    const targetCampaignId = (campaign && campaign.campaignId) || null;

    let liveItems = items;
    if (targetCampaignId && fieldName !== 'updateCampaign') {
        // The deleteCampaign pipeline runs this query milliseconds after
        // DeleteItem; the GSI is eventually consistent and may still project
        // the just-deleted row. Never resurrect it as the profile's latest
        // campaign.
        liveItems = liveItems.filter(item => item && item.campaignId !== targetCampaignId);
    } else if (targetCampaignId && input.isActive === false) {
        // The GSI may likewise still project the just-deactivated campaign
        // as active; merge the caller's isActive intent and drop it.
        liveItems = liveItems.filter(item => item && item.campaignId !== targetCampaignId);
    } else if (targetCampaignId && input.isActive === true) {
        // Conversely the stale GSI may still show the just-reactivated
        // campaign as inactive and omit it; add it back as a candidate.
        const present = liveItems.some(item => item && item.campaignId === targetCampaignId);
        if (!present) {
            liveItems = liveItems.concat([{ ...campaign, isActive: true }]);
        }
    }

    // ISO8601 UTC strings compare lexicographically; pick the newest active
    // campaign by createdAt (same canonical semantics as the field resolver).
    let newest = null;
    for (const item of liveItems) {
        if (!item) {
            continue;
        }
        if (!newest || (item.createdAt || '') > (newest.createdAt || '')) {
            newest = item;
        }
    }
    ctx.stash.latestActiveCampaignId = newest ? newest.campaignId : null;
    ctx.stash.latestActiveCampaignResolved = true;

    return ctx.prev.result;
}
