import { util } from '@aws-appsync/utils';

// This code backs TWO aws_appsync_function resources (verify_profile_read_access
// and verify_profile_read_access_step2 in functions_sharing.tf) that run
// back-to-back in the four profile-scoped read pipelines (getCampaign,
// listCampaignsByProfile, getOrder, listOrdersByCampaign), so it can perform a
// two-phase authorization - the same shape verify_profile_write_access_fn.js
// already implements for the write mutations (#438) and fetch_profile_fn.js for
// getProfile (#545):
//
//   Step 1: a strongly consistent base-table GetItem keyed
//           {ownerAccountId: <caller>, profileId: dbProfileId}. An item can only
//           live under the caller's partition key if the caller owns the
//           profile, so this read is authoritative for ownership.
//   Step 2: only when Step 1 proves the caller is NOT the owner, run the
//           profileId-index GSI query to locate the profile so
//           check_share_read_permissions_fn.js can evaluate the share.
//
// The GSI is eventually consistent: after an ownership transfer it can keep
// projecting the previous owner. Deciding ownership from it alone is a race
// (#508) - the former owner keeps passing the gate and reading the new owner's
// campaigns/orders while the new owner is refused with profileNotFound until the
// index catches up. Ownership is therefore decided exclusively by the Step 1
// base-table read; the GSI query is only a locator for the share check, and
// ctx.stash.isOwner - never the stashed item's ownerAccountId - drives
// downstream authorization (check_profile_read_auth_fn.js, #545).

// Resolve the profile id from the args or the stashed campaign/order. Returns
// the raw id (PROFILE# prefix normalized by the caller) or null.
function resolveProfileId(ctx) {
    if (ctx.args && ctx.args.profileId) {
        return ctx.args.profileId;
    }
    if (ctx.stash && ctx.stash.campaign && ctx.stash.campaign.profileId) {
        return ctx.stash.campaign.profileId;
    }
    if (ctx.stash && ctx.stash.profileId) {
        // For orders, profileId is set directly in stash
        return ctx.stash.profileId;
    }
    return null;
}

// A no-op read on the profiles table. Both keys are supplied because ownership
// is encoded in the ownerAccountId hash key.
function noOpRead() {
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
    };
}

export function request(ctx) {
    // If campaign not found, skip this function
    if (ctx.stash.campaignNotFound) {
        // Return a no-op read
        return noOpRead();
    }

    // If order not found, skip this function
    if (ctx.stash.orderNotFound) {
        // Return a no-op read
        return noOpRead();
    }

    // Extract profileId from args or stash
    const profileId = resolveProfileId(ctx);

    if (!profileId) {
        util.error('Profile ID not found in request', 'INVALID_INPUT');
    }

    // Store profileId in stash for next function
    ctx.stash.profileId = profileId;

    // Add PROFILE# prefix for DynamoDB query (field resolver strips it for API responses)
    const dbProfileId = profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;

    // Step 2 (owner confirmed in Step 1): no further read is needed.
    if (ctx.stash.isOwner === true) {
        return noOpRead();
    }

    // Step 2 (non-owner confirmed in Step 1): fall back to the GSI query purely
    // as a locator for the share check.
    if (ctx.stash.isOwner === false) {
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
    // to confirm ownership before any eventually-consistent GSI read (#508).
    const sub = ctx.identity && ctx.identity.sub ? ctx.identity.sub : '';
    const callerAccountId = sub.startsWith('ACCOUNT#') ? sub : `ACCOUNT#${sub}`;

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
    // If campaign not found, pass through (will return null at end)
    if (ctx.stash.campaignNotFound) {
        ctx.stash.authorized = false;
        return { authorized: false };
    }

    // If order not found, pass through (will return null at end)
    if (ctx.stash.orderNotFound) {
        ctx.stash.authorized = false;
        return { authorized: false };
    }

    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    // Step 2 response for the owner path: ownership was already decided by the
    // strongly consistent Step 1 read; pass the confirmed profile through.
    if (ctx.stash.isOwner === true) {
        return ctx.stash.profile;
    }

    // Step 1 response: the strongly consistent GetItem keyed on the caller's own
    // partition. Because ownership is encoded in that hash key, an item can only
    // be returned here if the caller owns the profile - mere existence is the
    // authoritative, race-free ownership signal (no attribute compare).
    if (ctx.stash.isOwner === undefined) {
        const ownerProfile = ctx.result;
        if (ownerProfile) {
            ctx.stash.isOwner = true;
            ctx.stash.authorized = true;
            // Store profile in stash for downstream functions (ensure PROFILE# prefix is used)
            ctx.stash.profile = ownerProfile;
            ctx.stash.profileId = ownerProfile.profileId;
            return { authorized: true };
        }
        // Not the owner: hand off to Step 2, whose GSI query locates the profile
        // so the share check can run. A profile that does not exist at all also
        // lands here, and Step 2's response is what sets profileNotFound.
        ctx.stash.isOwner = false;
        return null;
    }

    // Step 2 response for the non-owner path: ctx.result is the GSI Query. The
    // GSI only locates the profile now - ctx.stash.isOwner === false is the
    // ownership verdict, and check_share_read_permissions_fn.js decides access
    // from the share row.
    const profile = ctx.result && ctx.result.items && ctx.result.items[0];

    if (!profile) {
        // Profile doesn't exist - for getCampaign, we'll return null later
        // For listCampaignsByProfile, we'll return an empty connection ({ campaigns: [], nextToken: null })
        ctx.stash.profileNotFound = true;
        ctx.stash.authorized = false;
        return { authorized: false };
    }

    // Not owner - need to check for share (READ or WRITE)
    ctx.stash.isOwner = false;
    // Store profile in stash so subsequent functions use the DB-prefixed profileId
    ctx.stash.profile = profile;
    ctx.stash.profileId = profile.profileId;
    return profile;
}