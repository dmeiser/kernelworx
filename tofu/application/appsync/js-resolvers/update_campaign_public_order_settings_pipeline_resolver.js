import { util } from '@aws-appsync/utils';
import { composePublicOrderSettings, settingsCampaign } from './lib/public_settings.js';

// Root resolver of the updateCampaignPublicOrderSettings pipeline
// (KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1). Pipeline order:
//
//   locate_campaign_public_settings        (CampaignsDS, GSI locator: campaignId -> profileId)
//   verify_profile_write_access            (ProfilesDS, consistent ownership read)
//   verify_profile_write_access_step2      (ProfilesDS, GSI locator for non-owners)
//   verify_public_settings_owner           (gate: isOwner === true, else FORBIDDEN)
//   validate_campaign_settings_write       (CampaignsDS, campaign exists + active when enforcing)
//   validate_public_settings_catalog       (CatalogsDS, catalog exists + not soft-deleted)
//   write_campaign_public_order_settings   (CampaignsDS, the conditioned UpdateItem)
//
// The mutation returns the saved settings, not the raw campaign item: the map
// comes off the item the write step just returned, so the settings view can
// repaint - including a freshly minted or rotated share token - without a second
// round trip that would have to race the campaignId-index GSI.
export function request(ctx) {
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
        return;
    }

    const written = ctx.prev ? ctx.prev.result : null;
    const campaign = written && typeof written === 'object' ? written : settingsCampaign(ctx);

    return composePublicOrderSettings(campaign, campaign ? campaign.publicOrders : null);
}
