import { util } from '@aws-appsync/utils';
import { normalizeId } from './ids.js';

// Shared argument semantics for the two public-order settings pipelines
// (#679 settings slice). Both the CampaignsDS validation step and the
// ProfilesDS write step resolve the SAME effective values from the request,
// so they cannot disagree about what an omitted argument means.
//
// An omitted nullable APPSYNC_JS input arrives as null and is indistinguishable
// from an explicit clear, so key presence decides (#506 Object.hasOwn pattern,
// as in update_order_fn.js and update_campaign_fn.js): omitted keeps the stored
// value, an explicit null is INVALID_INPUT.

// Version of the acknowledgement text the owner must accept. Bumping this
// constant re-prompts every owner whose stored ackVersion lags it.
export const ACK_VERSION = 1;

// The stored publicOrders blob off the profile the write-access pair stashed,
// or null when the profile never enabled the feature.
export function storedPublicOrders(ctx) {
    const profile = ctx.stash ? ctx.stash.profile : null;
    const blob = profile ? profile.publicOrders : null;
    return blob && typeof blob === 'object' ? blob : null;
}

// The profile's canonical PROFILE# id as the pair normalized it in step 1.
// Falls back to the stashed item's own attribute for a pipeline that stashed
// the item without the id (the pair always sets both).
export function stashedProfileId(ctx) {
    const stash = ctx.stash || {};
    if (typeof stash.profileId === 'string' && stash.profileId) {
        return stash.profileId;
    }
    const profile = stash.profile;
    return profile && typeof profile.profileId === 'string' ? profile.profileId : null;
}

// Effective anchor campaign in canonical CAMPAIGN# form, or null when neither
// the request nor the stored blob supplies one.
export function resolveCampaignId(ctx) {
    const args = ctx.args || {};
    if (Object.hasOwn(args, 'campaignId')) {
        const value = args.campaignId;
        if (value === null || value === undefined || value === '') {
            util.error(
                'campaignId cannot be null; omit the field to keep the current campaign',
                'INVALID_INPUT'
            );
            return null;
        }
        return normalizeId(value, 'CAMPAIGN#');
    }
    const stored = storedPublicOrders(ctx);
    return stored && stored.campaignId ? normalizeId(stored.campaignId, 'CAMPAIGN#') : null;
}

// Effective allowed-method list, or null when neither the request nor the
// stored blob supplies one. An explicit null is INVALID_INPUT; a provided list
// must hold non-empty strings.
export function resolveAllowedPaymentMethods(ctx) {
    const args = ctx.args || {};
    let list;
    if (Object.hasOwn(args, 'allowedPaymentMethods')) {
        const value = args.allowedPaymentMethods;
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
    for (const name of list) {
        if (typeof name !== 'string' || name.trim() === '') {
            util.error('allowedPaymentMethods must be a list of non-empty names', 'INVALID_INPUT');
            return null;
        }
    }
    return list;
}

// True when the request is publishing or re-pointing the public surface: it
// turns the feature ON from an off state, or it explicitly picks/re-picks the
// anchor campaign by carrying campaignId. Only those saves get the
// campaign/catalog enforcement. Rotate-token, disable and method-list saves
// keep working over a stale anchor (campaign deleted or deactivated) - none of
// them changes what is published, so none must be able to strand the seller
// over a dead campaign.
export function settingsWriteIsEnforcing(ctx) {
    const args = ctx.args || {};
    const stored = storedPublicOrders(ctx);
    const rePicking = Object.hasOwn(args, 'campaignId');
    if (rePicking) {
        return true;
    }
    return args.enabled === true && !(stored && stored.enabled === true);
}

// True when the stored acknowledgement is missing or predates ACK_VERSION, in
// which case enabling requires acknowledgementsAccepted: true.
export function acknowledgementIsBehind(ctx) {
    const stored = storedPublicOrders(ctx);
    const version = stored ? stored.ackVersion : null;
    return typeof version !== 'number' || version < ACK_VERSION;
}

// The PublicOrderSettings output object. `blob` is the stored (or freshly
// merged) publicOrders map; the campaign fields come from the pipeline's
// CampaignsDS step and stay null when no anchor campaign was read.
export function composePublicOrderSettings(blob, campaignName, campaignState, publicOrderCount) {
    const settings = blob && typeof blob === 'object' ? blob : null;
    return {
        enabled: settings ? settings.enabled === true : false,
        campaignId: settings && settings.campaignId ? settings.campaignId : null,
        campaignName: campaignName === undefined ? null : campaignName,
        campaignState: campaignState === undefined ? null : campaignState,
        allowedPaymentMethods:
            settings && Array.isArray(settings.allowedPaymentMethods)
                ? settings.allowedPaymentMethods
                : [],
        shareToken: settings && settings.token ? settings.token : null,
        publicOrderCount: typeof publicOrderCount === 'number' ? publicOrderCount : null,
        acknowledgedAt: settings && settings.acknowledgedAt ? settings.acknowledgedAt : null,
        ackVersion: typeof (settings && settings.ackVersion) === 'number' ? settings.ackVersion : null
    };
}
