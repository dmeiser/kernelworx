import { util, runtime } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';
import {
    resolveCampaignId,
    settingsWriteIsEnforcing,
    stashedProfileId
} from './lib/public_settings.js';

// CampaignsDS validation step of the updateProfilePublicOrderSettings pipeline
// (#679 settings slice). One GetItem on the campaigns table, keyed by the
// stashed profile's own partition key plus the chosen anchor campaign, so a
// campaign belonging to a DIFFERENT profile is a GetItem miss and answers with
// the same NOT_FOUND as a campaign that does not exist - never a cross-account
// read and never an existence oracle for other accounts' campaigns.
//
// The read runs whenever an anchor is in play, but it ENFORCES only when the
// request switches the feature on from an off state or picks/re-picks the
// anchor campaign (see settingsWriteIsEnforcing). Rotate-token, disable and
// method-list saves keep working over an anchor that has gone missing or
// inactive: rejecting them would strand the seller over a dead anchor with no
// working off switch or token revocation. A non-enforcing read just fills the
// campaignState staleness flag the write then persists nothing about - the
// settings read recomputes it anyway.
export function request(ctx) {
    const campaignId = resolveCampaignId(ctx);
    // resolveCampaignId already rejected an explicit null; a null here means
    // neither the request nor the stored blob named a campaign.
    if (!campaignId) {
        if (ctx.args && ctx.args.enabled === true) {
            util.error('campaignId is required to enable public orders', 'INVALID_INPUT');
            return;
        }
        // Nothing to read: a disable on a profile that never picked a campaign.
        return runtime.earlyReturn(null);
    }

    const profileId = stashedProfileId(ctx);
    if (!profileId) {
        // The owner gate already proved a stashed profile; reaching here means
        // the pipeline was rewired, not that the caller is wrong.
        util.error('Profile not found', 'NOT_FOUND');
        return;
    }

    if (ctx.stash) {
        ctx.stash.publicSettingsCampaignId = campaignId;
    }

    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: profileId, campaignId: campaignId }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const enforcing = settingsWriteIsEnforcing(ctx);
    const campaign = ctx.result;

    if (!campaign) {
        if (enforcing) {
            // Covers a foreign-profile campaign and a dangling stored anchor:
            // the owner has to pick a live campaign of their own, and the
            // message never hints whether the id exists elsewhere.
            util.error('Campaign not found', 'NOT_FOUND');
            return;
        }
        if (ctx.stash) {
            ctx.stash.publicSettingsCampaignState = 'MISSING';
            ctx.stash.publicSettingsCampaignName = null;
            ctx.stash.publicSettingsOrderCount = null;
        }
        return null;
    }

    // Back-compat default reproduced from get_campaign_for_order_fn.js: a
    // campaign predating the isActive attribute has none, and absence means
    // active. Only an explicit false is inactive.
    const active = campaign.isActive == null ? true : campaign.isActive === true;

    if (ctx.stash) {
        ctx.stash.publicSettingsCampaignName =
            campaign.campaignName === undefined ? null : campaign.campaignName;
        ctx.stash.publicSettingsCampaignState = active ? 'OK' : 'INACTIVE';
        ctx.stash.publicSettingsOrderCount =
            typeof campaign.publicOrderCount === 'number' ? campaign.publicOrderCount : 0;
    }

    if (!active) {
        if (enforcing) {
            util.error('Public orders can only be anchored to an active campaign', 'INVALID_INPUT');
            return;
        }
        // Turning the feature off over a deactivated anchor is allowed.
        return campaign;
    }

    if (!enforcing) {
        // Parked save that kept the stored anchor: no catalog gate, because
        // nothing is being published.
        return campaign;
    }

    if (!campaign.catalogId) {
        util.error('Campaign has no catalog assigned', 'INVALID_INPUT');
        return;
    }

    if (ctx.stash) {
        ctx.stash.publicSettingsCampaign = campaign;
        // CatalogsDS is a different table, so the catalog check is its own
        // function; hand it the normalized key.
        ctx.stash.publicSettingsCatalogId = normalizeIdOrPrefix(campaign.catalogId, 'CATALOG#');
    }

    return campaign;
}
