import { util } from '@aws-appsync/utils';
import { composePublicOrderSettings, settingsCampaign, storedPublicOrders } from './lib/public_settings.js';

// Root resolver of the getCampaignPublicOrderSettings pipeline
// (KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1). Pipeline order:
//
//   locate_campaign_public_settings      (CampaignsDS, GSI locator: campaignId -> profileId)
//   verify_profile_write_access          (ProfilesDS, consistent ownership read)
//   verify_profile_write_access_step2    (ProfilesDS, GSI locator for non-owners)
//   verify_public_settings_owner         (gate: isOwner === true, else FORBIDDEN)
//   lookup_campaign_public_settings      (CampaignsDS, consistent settings read)
//
// The shaped PublicOrderSettings is composed here rather than in the last
// function so the settings map, the counter and the campaign's own name and
// active state are read off one consistent campaign item - the locator's
// eventually-consistent GSI copy is deliberately shadowed by the last step's
// stash write.
export function request(ctx) {
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
        return;
    }

    return composePublicOrderSettings(settingsCampaign(ctx), storedPublicOrders(ctx));
}
