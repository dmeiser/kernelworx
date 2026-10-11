import { util } from '@aws-appsync/utils';
import { composePublicOrderSettings } from './lib/public_settings.js';

// Root resolver of the updateProfilePublicOrderSettings pipeline (#679
// settings slice). Pipeline order:
//
//   verify_profile_write_access            (ProfilesDS, consistent ownership read)
//   verify_profile_write_access_step2      (ProfilesDS, GSI locator for non-owners)
//   verify_public_settings_owner           (gate: isOwner === true, else FORBIDDEN)
//   validate_public_settings_write         (CampaignsDS, anchor exists + owned + active)
//   validate_public_settings_catalog       (CatalogsDS, catalog exists + not soft-deleted)
//   write_public_order_settings            (ProfilesDS, the conditioned UpdateItem)
//
// The mutation returns the saved settings, not the raw profile item: the blob
// comes off the updated item, and the campaign display fields come from the
// CampaignsDS step's stash writes so the settings view can repaint without a
// second round trip.
export function request(ctx) {
    return {};
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const item = ctx.prev ? ctx.prev.result : null;
    const blob = item && item.publicOrders ? item.publicOrders : null;
    const stash = ctx.stash || {};

    return composePublicOrderSettings(
        blob,
        stash.publicSettingsCampaignName,
        stash.publicSettingsCampaignState,
        stash.publicSettingsOrderCount
    );
}
