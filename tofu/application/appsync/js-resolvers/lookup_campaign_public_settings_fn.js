import { util } from '@aws-appsync/utils';
import { stashedCampaignId, stashedProfileId } from './lib/public_settings.js';

// Authoritative settings read of the getCampaignPublicOrderSettings pipeline
// (KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1). Rev 7 stores the publicOrders map on the
// campaign item itself, so one strongly consistent GetItem on Campaigns returns
// the whole settings surface: enabled, token, allowedPaymentMethods,
// acknowledgedAt, ackVersion - plus the lifetime publicOrderCount counter and
// the campaign's own name and isActive state, which the settings view renders.
//
// The read is keyed by the partition key the locator step learned from the GSI,
// so it runs against the base table and cannot lag the owner's previous save.
// A caller who does not own the profile is refused FORBIDDEN by
// verify_public_settings_owner two steps before this GetItem runs, so this
// read is never a cross-account read.
//
// A missing row here is NOT_FOUND, not a null settings object: the campaign was
// located moments earlier in the same pipeline, so a miss means it was deleted
// in between. There is no "never enabled" branch to model - a campaign that
// never enabled public orders simply has no publicOrders attribute, and the
// composition in the pipeline root answers enabled: false with empty defaults.
export function request(ctx) {
    const profileId = stashedProfileId(ctx);
    const campaignId = stashedCampaignId(ctx);

    if (!profileId || !campaignId) {
        // The locator and the owner gate both proved a campaign exists; reaching
        // here means the pipeline was rewired, not that the caller is wrong.
        util.error('Campaign not found', 'NOT_FOUND');
        return;
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
        return;
    }

    const campaign = ctx.result;
    if (!campaign) {
        util.error('Campaign not found', 'NOT_FOUND');
        return;
    }

    // Preferred over the locator's GSI copy by lib/public_settings.js
    // settingsCampaign(), so the composed settings are the consistent ones.
    if (ctx.stash) {
        ctx.stash.publicSettingsCampaign = campaign;
    }
    return campaign;
}
