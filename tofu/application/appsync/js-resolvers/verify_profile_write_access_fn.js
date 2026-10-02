import { util } from '@aws-appsync/utils';
import { normalizeId, normalizeIdOrPrefix } from './lib/ids.js';

// This code backs TWO aws_appsync_function resources (verify_profile_write_access
// and verify_profile_write_access_step2 in functions_sharing.tf) that run
// back-to-back in the six write-mutation pipelines and in the two profile
// read-list queries (listSharesByProfile / listInvitesByProfile), so it can
// perform a two-phase authorization:
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

// Route an unresolvable profileId through the same silent-deny branch as the
// "profile not found" case, so the read-list queries (listSharesByProfile /
// listInvitesByProfile) answer with an empty list instead of an error. The
// retired verifier returned `{ authorized: false }` for a missing profileId;
// both queries must keep that contract, and neither must turn an empty result
// into a GraphQL error or a profile-existence oracle.
function denyUnresolvedProfileId(ctx) {
    ctx.stash.isOwner = false;
    ctx.stash.hasWritePermission = false;
    ctx.stash.skipGetItem = true;
}

// idempotent-delete detection: deleteOrder/deleteCampaign where the lookup step
// already stashed a null item (item already gone = success).
function isIdempotentDeleteSkip(ctx) {
    const fieldName = ctx.info && ctx.info.fieldName;
    const isDeletingOrder = fieldName === 'deleteOrder';
    const isDeletingCampaign = fieldName === 'deleteCampaign';
    if (!isDeletingOrder && !isDeletingCampaign) {
        return false;
    }
    return (isDeletingOrder && ctx.stash && ctx.stash.order === null) ||
        (isDeletingCampaign && ctx.stash && ctx.stash.campaign === null);
}

// Resolve + normalize the profileId from input args or stash. Returns the
// PROFILE# DB form, or null when it cannot be resolved.
function resolveDbProfileId(ctx) {
    let profileId = null;

    if (ctx.args && ctx.args.input && ctx.args.input.profileId) {
        profileId = ctx.args.input.profileId;
    } else if (ctx.args && ctx.args.profileId) {
        // Query resolvers (listSharesByProfile / listInvitesByProfile, #547) pass
        // the id as a top-level argument rather than under input.
        profileId = ctx.args.profileId;
    } else if (ctx.stash && ctx.stash.order && ctx.stash.order.profileId) {
        // Orders have profileId attribute - use it directly (not PK which is the campaign key)
        profileId = ctx.stash.order.profileId;
    } else if (ctx.stash && ctx.stash.campaign && ctx.stash.campaign.profileId) {
        // Campaigns have profileId attribute - use it directly (not PK which is composite)
        profileId = ctx.stash.campaign.profileId;
    }

    // Owned by lib/ids.js so both phases resolve a clean, unprefixed id to
    // the same PROFILE# DB form (and never re-prefix an already-normalized
    // one); a re-inlined ternary here is caught by
    // tests/unit/check_id_prefix_normalization.test.ts.
    if (typeof profileId !== 'string' || !profileId) {
        return null;
    }

    return normalizeId(profileId, 'PROFILE#');
}

export function request(ctx) {
    // Idempotent delete: skip auth entirely (item already gone = success).
    // Set the flag in Step 1; honor it in Step 2 as well.
    if ((ctx.stash && ctx.stash.skipAuth) || isIdempotentDeleteSkip(ctx)) {
        if (ctx.stash) {
            ctx.stash.skipAuth = true;
        }
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
        };
    }

    // Step 2 (owner confirmed in Step 1): no further read is needed.
    if (ctx.stash && ctx.stash.isOwner === true) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
        };
    }

    // Step 2 (non-owner confirmed in Step 1): fall back to the GSI query.
    if (ctx.stash && ctx.stash.isOwner === false) {
        // The unresolvable-id path stashed skipGetItem instead of a usable id;
        // issue no live read.
        if (ctx.stash.skipGetItem) {
            return {
                operation: 'GetItem',
                key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
            };
        }
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
        const isQueryParent = ctx.info && ctx.info.parentTypeName === 'Query';
        if (isQueryParent) {
            // S1: a blank or unresolvable profileId on the two read-list queries
            // must not surface as a GraphQL error; route through the same
            // silent-deny branch as the not-found case so the result is [].
            denyUnresolvedProfileId(ctx);
            return {
                operation: 'GetItem',
                key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
            };
        }
        console.error(
            'Profile ID not found in request or stash: ' +
                JSON.stringify({
                    hasInput: !!(ctx.args && ctx.args.input),
                    hasOrder: !!(ctx.stash && ctx.stash.order),
                    hasCampaign: !!(ctx.stash && ctx.stash.campaign),
                    orderKeys: ctx.stash && ctx.stash.order ? Object.keys(ctx.stash.order) : [],
                })
        );
        util.error('Profile ID is required', 'INVALID_INPUT');
    }

    // Expose the normalized id on the stash for downstream pipeline steps. #547:
    // check_write_permission (listSharesByProfile / listInvitesByProfile) reads
    // ctx.stash.profileId; the mutation steps keep resolving their own id, so
    // storing the same value here is inert for them.
    if (ctx.stash) {
        ctx.stash.profileId = dbProfileId;
    }

    // Idempotent: a sub that already carries ACCOUNT# is left alone; the
    // placeholder fallback matches the historical 'ACCOUNT#' + '' key.
    const callerAccountId = normalizeIdOrPrefix(ctx.identity && ctx.identity.sub, 'ACCOUNT#');

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
    if (ctx.stash && ctx.stash.skipAuth) {
        return { authorized: true };
    }

    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    // Step 1 response: the strongly consistent GetItem under the caller's own
    // partition key. Because ownership is encoded in that hash key, an item can
    // only be returned here if the caller owns the profile - so mere existence
    // is the authoritative, race-free ownership signal (no attribute compare).
    if (ctx.stash && ctx.stash.isOwner === undefined) {
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
    if (ctx.stash && ctx.stash.isOwner === true) {
        return ctx.stash.profile;
    }

    // Step 2 response for the non-owner path: ctx.result is the GSI Query.
    const profile = ctx.result && ctx.result.items && ctx.result.items[0];
    if (!profile) {
        // Read path (#547): listSharesByProfile / listInvitesByProfile answer
        // with an empty list for a profile that does not exist (or is not yet
        // projected on the GSI) - never an error, and never a NOT_FOUND
        // existence oracle. Deny silently so the downstream check_write_permission
        // and query_shares / query_invites steps fall through to their empty
        // result, which is the contract these queries had before #547.
        // S1: an unresolvable profileId (skipGetItem set in request) routes here
        // too, so a blank id produces the same empty list rather than an error.
        if (ctx.stash.skipGetItem || (ctx.info && ctx.info.parentTypeName === 'Query')) {
            denyUnresolvedProfileId(ctx);
            return null;
        }
        // Write path: the profile must exist to be mutated, so a missing profile
        // is a client error rather than a silent skip.
        util.error('Profile not found', 'NOT_FOUND');
    }

    // Ownership was already ruled out by the consistent Step 1 read; the GSI
    // result is used only to hand the profile to the share-inspection step.
    if (ctx.stash) {
        ctx.stash.isOwner = false;
        ctx.stash.profile = profile;
        ctx.stash.profileOwner = profile.ownerAccountId;
    }
    return profile;
}
