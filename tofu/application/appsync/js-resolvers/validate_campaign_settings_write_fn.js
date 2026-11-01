import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';
import {
    campaignIsActive,
    getCampaignPublicSettings,
    settingsWriteIsEnforcing
} from './lib/public_settings.js';

// CampaignsDS validation step of the updateCampaignPublicOrderSettings pipeline
// (KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1). One strongly consistent GetItem on the
// campaign item, keyed by the partition key the locator step learned from the
// GSI. A caller who does not own the profile is refused FORBIDDEN by
// verify_public_settings_owner two steps before this GetItem runs, so the
// GetItem miss answers NOT_FOUND only for a campaign deleted between the
// locator read and this consistent read - never a cross-account read and
// never an existence oracle for other accounts' campaigns.
//
// The read also re-confirms the campaign after the ownership pair ran, and it
// ENFORCES only when the request switches the feature on from an off state (see
// settingsWriteIsEnforcing). Disable, method-list and rotate-token saves keep
// working over a campaign that has gone inactive or whose catalog was deleted:
// rejecting those would strand the seller with no working off switch and no
// token revocation path.
//
// When it does enforce, an inactive campaign is INVALID_INPUT (a paused
// campaign must not be publicly orderable) and a campaign with no catalog is
// INVALID_INPUT. The catalog's own existence is the next step's job: Catalogs is
// a different table, and one APPSYNC_JS function makes one datastore call.
export function request(ctx) {
    return getCampaignPublicSettings(ctx);
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
        return;
    }

    const campaign = ctx.result;
    if (!campaign) {
        // Only a campaign deleted between the locator read and this consistent
        // read can miss: ownership was already decided by
        // verify_public_settings_owner two steps earlier.
        util.error('Campaign not found', 'NOT_FOUND');
        return;
    }

    // The write step reads the effective stored blob off this consistent copy,
    // never off the locator's GSI projection.
    if (ctx.stash) {
        ctx.stash.publicSettingsCampaign = campaign;
    }

    if (campaignIsActive(campaign)) {
        if (!settingsWriteIsEnforcing(ctx)) {
            return campaign;
        }
        if (!campaign.catalogId) {
            util.error('Campaign has no catalog assigned', 'INVALID_INPUT');
            return;
        }
        if (ctx.stash) {
            // CatalogsDS is a different table, so the catalog check is its own
            // function; hand it the normalized key.
            ctx.stash.publicSettingsCatalogId = normalizeIdOrPrefix(campaign.catalogId, 'CATALOG#');
        }
        return campaign;
    }

    if (settingsWriteIsEnforcing(ctx)) {
        util.error('Public orders can only be enabled on an active campaign', 'INVALID_INPUT');
        return;
    }

    // Turning the feature off, rotating the token, or editing the method list on
    // a deactivated campaign is allowed: none of them publishes anything new.
    return campaign;
}
