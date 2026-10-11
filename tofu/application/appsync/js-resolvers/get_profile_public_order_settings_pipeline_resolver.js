import { util } from '@aws-appsync/utils';
import { composePublicOrderSettings, storedPublicOrders } from './lib/public_settings.js';

// Root resolver of the getProfilePublicOrderSettings pipeline (#679 settings
// slice). Pipeline order:
//
//   verify_profile_write_access            (ProfilesDS, consistent ownership read)
//   verify_profile_write_access_step2      (ProfilesDS, GSI locator for non-owners)
//   verify_public_settings_owner           (gate: isOwner === true, else FORBIDDEN)
//   lookup_public_settings_campaign        (CampaignsDS, counter + name + state)
//
// The shaped PublicOrderSettings is composed here rather than in the last
// function because the blob lives on the stashed profile item while the
// campaign fields come from the CampaignsDS step's stash writes.
export function request(ctx) {
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const stash = ctx.stash || {};
    return composePublicOrderSettings(
        storedPublicOrders(ctx),
        stash.publicSettingsCampaignName,
        stash.publicSettingsCampaignState,
        stash.publicSettingsOrderCount
    );
}
