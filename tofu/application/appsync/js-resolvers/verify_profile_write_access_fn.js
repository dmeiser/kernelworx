import { util } from '@aws-appsync/utils';

// This code backs TWO aws_appsync_function resources (verify_profile_write_access
// and verify_profile_write_access_step2 in functions_sharing.tf) that run
// back-to-back in each write-mutation pipeline so it can perform a two-phase
// authorization:
//
//   Step 1: a strongly consistent base-table GetItem keyed
//           {ownerAccountId: <caller>, profileId}. An item can only live under
//           the caller's partition key if the caller owns the profile, so this
//           read is authoritative for ownership.
//   Step 2: only when Step 1 proves the caller is NOT the owner, run the
//           profileId-index GSI query to locate the profile so the downstream
//           share-inspection function can authorize a WRITE share.
//
// The GSI is eventually consistent: after an ownership transfer it can keep
// projecting the previous owner. Authorizing writes off that GSI read alone is
// a race (#438). Ownership is therefore decided exclusively by the Step 1
// base-table read; the GSI query is used only to surface the profile item and
// to drive the unchanged share path. All existing authz semantics (shares,
// idempotent deletes) are preserved.

// idempotent-delete detection: deleteOrder/deleteCampaign where the lookup step
// already stashed a null item (item already gone = success).
function isIdempotentDeleteSkip(ctx) {
    const isDeletingOrder = ctx.info.fieldName === 'deleteOrder';
    const isDeletingCampaign = ctx.info.fieldName === 'deleteCampaign';
    if (!isDeletingOrder && !isDeletingCampaign) {
        return false;
    }
    return (isDeletingOrder && ctx.stash.order === null) ||
        (isDeletingCampaign && ctx.stash.campaign === null);
}

// Resolve + normalize the profileId from input args or stash. Returns the
// PROFILE# DB form, or null when it cannot be resolved.
function resolveDbProfileId(ctx) {
    let profileId = null;

    if (ctx.args.input && ctx.args.input.profileId) {
        profileId = ctx.args.input.profileId;
    } else if (ctx.stash && ctx.stash.order) {
        // Orders have profileId attribute - use it directly (not PK which is the campaign key)
        profileId = ctx.stash.order.profileId;
    } else if (ctx.stash && ctx.stash.campaign && ctx.stash.campaign.profileId) {
        // Campaigns have profileId attribute - use it directly (not PK which is composite)
        profileId = ctx.stash.campaign.profileId;
    }

    if (!profileId) {
        return null;
    }

    return (typeof profileId === 'string' && profileId.startsWith('PROFILE#'))
        ? profileId
        : 'PROFILE#' + profileId;
}

export function request(ctx) {
    // Idempotent delete: skip auth entirely (item already gone = success).
    // Set the flag in Step 1; honor it in Step 2 as well.
    if (ctx.stash.skipAuth || isIdempotentDeleteSkip(ctx)) {
        ctx.stash.skipAuth = true;
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
        };
    }

    // Step 2 (owner confirmed in Step 1): no further read is needed.
    if (ctx.stash.isOwner === true) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
        };
    }

    // Step 2 (non-owner confirmed in Step 1): fall back to the GSI query.
    if (ctx.stash.isOwner === false) {
        const dbProfileId = resolveDbProfileId(ctx);
        return {
            operation: 'Query',
            index: 'profileId-index',
            query: {
                expression: 'profileId = :profileId',
                expressionValues: util.dynamodb.toMapValues({ ':profileId': dbProfileId })
            }
        };
    }

    // Step 1: strongly consistent base-table GetItem under the caller's account
    // to confirm ownership before any eventually-consistent GSI read (#438).
    const dbProfileId = resolveDbProfileId(ctx);
    if (!dbProfileId) {
        util.error('Profile ID not found in request or stash - debugging: ' + JSON.stringify({
            hasInput: !!ctx.args.input,
            hasOrder: !!(ctx.stash && ctx.stash.order),
            hasCampaign: !!(ctx.stash && ctx.stash.campaign),
            orderKeys: ctx.stash && ctx.stash.order ? Object.keys(ctx.stash.order) : []
        }), 'INVALID_INPUT');
    }

    const callerAccountId = ctx.identity.sub.startsWith('ACCOUNT#')
        ? ctx.identity.sub
        : 'ACCOUNT#' + ctx.identity.sub;

    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
            ownerAccountId: callerAccountId,
            profileId: dbProfileId
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    // Idempotent delete: auth was skipped.
    if (ctx.stash.skipAuth) {
        return { authorized: true };
    }

    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    // Step 1 response: the strongly consistent GetItem under the caller's own
    // partition key. Because ownership is encoded in that hash key, an item can
    // only be returned here if the caller owns the profile - so mere existence
    // is the authoritative, race-free ownership signal (no attribute compare).
    if (ctx.stash.isOwner === undefined) {
        const ownerProfile = ctx.result;
        if (ownerProfile) {
            ctx.stash.isOwner = true;
            ctx.stash.profile = ownerProfile;
            ctx.stash.profileOwner = ownerProfile.ownerAccountId;
            return ownerProfile;
        }
        // Not the owner: proceed to the GSI query in Step 2. (The returned
        // value is unused by the next step, which branches on ctx.stash.)
        ctx.stash.isOwner = false;
        return null;
    }

    // Step 2 response for the owner path: pass the confirmed profile through.
    if (ctx.stash.isOwner === true) {
        return ctx.stash.profile;
    }

    // Step 2 response for the non-owner path: ctx.result is the GSI Query.
    const profile = ctx.result.items && ctx.result.items[0];
    if (!profile) {
        util.error('Profile not found', 'NOT_FOUND');
    }

    // Ownership was already ruled out by the consistent Step 1 read; the GSI
    // result is used only to hand the profile to the share-inspection step.
    ctx.stash.isOwner = false;
    ctx.stash.profile = profile;
    ctx.stash.profileOwner = profile.ownerAccountId;
    return profile;
}
