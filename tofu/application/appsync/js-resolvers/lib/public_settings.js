import { util } from '@aws-appsync/utils';
import { normalizeId } from './ids.js';

// Shared argument and state semantics for the two campaign-level public-order
// settings pipelines (KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1). Both the CampaignsDS
// validation step and the CampaignsDS write step resolve the SAME effective
// values from the request and from the same stashed campaign item, so they
// cannot disagree about what an omitted argument means.
//
// Rev 7 moved the settings blob from the scout profile item onto the campaign
// item, so the campaign is both the settings subject and the settings carrier:
// there is no anchor-campaign indirection and no campaignId argument to pick.
//
// An omitted nullable APPSYNC_JS input arrives as null and is indistinguishable
// from an explicit clear, so key presence decides (#506 Object.hasOwn pattern,
// as in update_order_fn.js and update_campaign_fn.js): omitted keeps the stored
// value, an explicit null is INVALID_INPUT.

// Version of the acknowledgement text the owner must accept. Bumping this
// constant re-prompts every owner whose stored ackVersion lags it.
export const ACK_VERSION = 1;

// The campaign's canonical CAMPAIGN# id from the request. The settings mutation
// carries it inside its input object; the settings query carries it as a
// top-level argument. Returns null when neither names one.
export function requestCampaignId(ctx) {
    const args = ctx.args || {};
    if (args.input && args.input.campaignId) {
        return normalizeId(args.input.campaignId, 'CAMPAIGN#');
    }
    if (args.campaignId) {
        return normalizeId(args.campaignId, 'CAMPAIGN#');
    }
    return null;
}

// The authoritative campaign item for the pipeline: the strongly consistent
// CampaignsDS read (the write pipeline's validate step, the read pipeline's
// lookup step) wins over the locator read, because the locator runs on the
// eventually-consistent campaignId-index GSI and can lag a just-saved write.
export function settingsCampaign(ctx) {
    const stash = ctx.stash || {};
    if (stash.publicSettingsCampaign && typeof stash.publicSettingsCampaign === 'object') {
        return stash.publicSettingsCampaign;
    }
    if (stash.campaign && typeof stash.campaign === 'object') {
        return stash.campaign;
    }
    return null;
}

// The stored publicOrders map off the campaign, or null when the campaign never
// enabled the feature. Deleting the campaign deletes this map with it, which is
// why rev 7 needs no auto-disable hook.
export function storedPublicOrders(ctx) {
    const campaign = settingsCampaign(ctx);
    const blob = campaign ? campaign.publicOrders : null;
    return blob && typeof blob === 'object' ? blob : null;
}

// The campaign item's partition key. The locator step read the campaign through
// the campaignId-index GSI precisely to learn this value, which the base table
// GetItem and the write both need. Returns null when no campaign was located.
export function stashedProfileId(ctx) {
    const stash = ctx.stash || {};
    if (typeof stash.profileId === 'string' && stash.profileId) {
        return stash.profileId;
    }
    const campaign = settingsCampaign(ctx);
    return campaign && typeof campaign.profileId === 'string' ? campaign.profileId : null;
}

// The campaign item's sort key, in canonical CAMPAIGN# form.
export function stashedCampaignId(ctx) {
    const fromRequest = requestCampaignId(ctx);
    if (fromRequest) {
        return fromRequest;
    }
    const campaign = settingsCampaign(ctx);
    return campaign && typeof campaign.campaignId === 'string'
        ? normalizeId(campaign.campaignId, 'CAMPAIGN#')
        : null;
}

// Bounds for the stored allowedPaymentMethods list (SEC-14): the whole map lives
// on the campaign item, which must stay under DynamoDB's 400KB ceiling. Cap the
// method count and the per-method label length.
export const MAX_ALLOWED_PAYMENT_METHODS = 25;
export const MAX_PAYMENT_METHOD_NAME_LENGTH = 100;

// Effective allowed-method list, or null when neither the request nor the
// stored blob supplies one. An explicit null is INVALID_INPUT; a provided list
// must hold non-empty strings.
export function resolveAllowedPaymentMethods(ctx) {
    const input = (ctx.args && ctx.args.input) || {};
    let list;
    if (Object.hasOwn(input, 'allowedPaymentMethods')) {
        const value = input.allowedPaymentMethods;
        if (!Array.isArray(value)) {
            util.error(
                'allowedPaymentMethods cannot be null; omit the field to keep the current list',
                'INVALID_INPUT'
            );
            return null;
        }
        list = value;
    } else {
        const stored = storedPublicOrders(ctx);
        list = stored && Array.isArray(stored.allowedPaymentMethods)
            ? stored.allowedPaymentMethods
            : null;
    }

    if (list === null) {
        return null;
    }
    if (list.length > MAX_ALLOWED_PAYMENT_METHODS) {
        util.error('allowedPaymentMethods must contain at most ' + MAX_ALLOWED_PAYMENT_METHODS + ' methods', 'INVALID_INPUT');
        return null;
    }
    for (const name of list) {
        if (typeof name !== 'string' || name.trim() === '' || name.trim().length > MAX_PAYMENT_METHOD_NAME_LENGTH) {
            util.error('allowedPaymentMethods must be a list of non-empty names of at most ' + MAX_PAYMENT_METHOD_NAME_LENGTH + ' characters', 'INVALID_INPUT');
            return null;
        }
    }
    return list;
}

// True when the request is publishing the public surface: it turns the feature
// ON from an off state. Only those saves get the campaign-active and
// catalog-exists enforcement. Disable, method-list and rotate-token saves keep
// working over a campaign that has gone inactive or whose catalog was deleted -
// none of them publishes anything new, so none may be able to strand the seller
// with no working off switch or token revocation path.
export function settingsWriteIsEnforcing(ctx) {
    const input = (ctx.args && ctx.args.input) || {};
    const stored = storedPublicOrders(ctx);
    return input.enabled === true && !(stored && stored.enabled === true);
}

// True when the stored acknowledgement is missing or predates ACK_VERSION, in
// which case enabling requires acknowledgementsAccepted: true.
export function acknowledgementIsBehind(ctx) {
    const stored = storedPublicOrders(ctx);
    const version = stored ? stored.ackVersion : null;
    return typeof version !== 'number' || version < ACK_VERSION;
}

// Back-compat default shared with get_campaign_for_order_fn.js: campaigns
// written before the isActive attribute existed carry no such attribute, and
// absence means active. Only an explicit false is inactive.
export function campaignIsActive(campaign) {
    if (!campaign) {
        return false;
    }
    return campaign.isActive == null ? true : campaign.isActive === true;
}

// The PublicOrderSettings output object, shaped from the campaign item and its
// publicOrders map. campaignId / campaignName / campaignState are non-null in
// the schema because the settings live on the campaign itself: the campaign is
// always present (a missing campaign is a NOT_FOUND before this runs) and
// campaignState has exactly two values, OK and INACTIVE. Rev 6's MISSING state
// is gone - it existed only to describe a dangling profile-level anchor.
export function composePublicOrderSettings(campaign, blob) {
    const settings = blob && typeof blob === 'object' ? blob : null;
    return {
        enabled: settings ? settings.enabled === true : false,
        campaignId: campaign ? campaign.campaignId : null,
        campaignName: campaign ? campaign.campaignName : null,
        campaignState: campaignIsActive(campaign) ? 'OK' : 'INACTIVE',
        allowedPaymentMethods:
            settings && Array.isArray(settings.allowedPaymentMethods)
                ? settings.allowedPaymentMethods
                : [],
        shareToken: settings && settings.token ? settings.token : null,
        publicOrderCount:
            campaign && typeof campaign.publicOrderCount === 'number'
                ? campaign.publicOrderCount
                : 0,
        acknowledgedAt: settings && settings.acknowledgedAt ? settings.acknowledgedAt : null,
        ackVersion: typeof (settings && settings.ackVersion) === 'number' ? settings.ackVersion : null
    };
}

// Shared base-table GetItem for the campaign public-order settings surface
// (KW-784 DRY-7): the strongly consistent read keyed by the located
// profileId + campaignId that both the settings lookup and the settings write
// validation step need. Returns the request object, calling util.error
// (NOT_FOUND) and returning undefined when pipeline state is missing - identical
// to the inlined copies it replaces, so callers keep their response handling.
export function getCampaignPublicSettings(ctx) {
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

// Alias retained for callers/tests using the shorter name (DRY-7).
export const getPublicSettings = getCampaignPublicSettings;
