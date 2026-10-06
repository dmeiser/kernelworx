import { util, runtime } from '@aws-appsync/utils';
import { normalizeId } from './lib/ids.js';
import { stashedProfileId, storedPublicOrders } from './lib/public_settings.js';

// CampaignsDS step of the getProfilePublicOrderSettings pipeline (#679
// settings slice). The counter and the campaign name live on the CAMPAIGNS
// item, not on the profile blob, so the settings read needs exactly one
// CampaignsDS GetItem to fill publicOrderCount / campaignName / campaignState.
//
// The GetItem is keyed by the stashed profile's own partition key, so a
// dangling anchor (a campaignId pointing at a campaign this profile does not
// own, e.g. after a partial delete or a transfer) is a GetItem miss and reads
// as MISSING - never a cross-account read.
//
// campaignState is the staleness flag the settings UI renders:
//   OK       the anchor row exists and is active
//   INACTIVE the anchor row exists but isActive is false (deactivated)
//   MISSING  the anchor row is gone (deleted, or a pointer left by a partial
//            delete whose auto-disable step never ran)
//   null     no anchor at all - the feature was never enabled. That is not an
//            error: a never-enabled profile answers enabled: false with nulls.
export function request(ctx) {
    const blob = storedPublicOrders(ctx);
    const campaignId = blob && blob.campaignId ? normalizeId(blob.campaignId, 'CAMPAIGN#') : null;
    const profileId = stashedProfileId(ctx);

    if (!campaignId || !profileId) {
        // Never-enabled (or an anchor-less blob): no read, and campaignState
        // stays null so the UI shows no campaign at all.
        if (ctx.stash) {
            ctx.stash.publicSettingsCampaignState = null;
            ctx.stash.publicSettingsCampaignName = null;
            ctx.stash.publicSettingsOrderCount = null;
        }
        return runtime.earlyReturn(null);
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

    const campaign = ctx.result;
    if (!campaign) {
        if (ctx.stash) {
            ctx.stash.publicSettingsCampaignState = 'MISSING';
            ctx.stash.publicSettingsCampaignName = null;
            ctx.stash.publicSettingsOrderCount = null;
        }
        return null;
    }

    // Back-compat default shared with get_campaign_for_order_fn.js: campaigns
    // written before isActive existed carry no attribute, and absence means
    // active. Only an explicit false is inactive.
    const active = campaign.isActive == null ? true : campaign.isActive === true;

    if (ctx.stash) {
        ctx.stash.publicSettingsCampaignState = active ? 'OK' : 'INACTIVE';
        ctx.stash.publicSettingsCampaignName =
            campaign.campaignName === undefined ? null : campaign.campaignName;
        // The counter is created by the public write path (later slice); an
        // anchor campaign without it has served zero public orders.
        ctx.stash.publicSettingsOrderCount =
            typeof campaign.publicOrderCount === 'number' ? campaign.publicOrderCount : 0;
    }

    return campaign;
}
