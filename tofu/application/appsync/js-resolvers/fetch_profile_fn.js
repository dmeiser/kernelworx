import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

// This code backs TWO aws_appsync_function resources (fetch_profile and
// fetch_profile_step2 in functions_profiles.tf) that run back-to-back in
// pipeline resolvers (e.g. paymentMethodsForProfile, getProfile) to perform
// two-phase authorization (#545):
//
//   Step 1: a strongly consistent base-table GetItem keyed
//           {ownerAccountId: <caller>, profileId: dbProfileId}. An item can only
//           live under the caller's partition key if the caller owns the profile,
//           so this read is authoritative for ownership.
//   Step 2: only when Step 1 proves the caller is NOT the owner, run the
//           profileId-index GSI query to locate the profile so downstream
//           functions (shares inspection) can verify access.
//
// The GSI is eventually consistent: after an ownership transfer it can keep
// projecting the previous owner. Authorizing ownership off that GSI read alone
// is a race (#545). Ownership is therefore decided exclusively by the Step 1
// base-table read; the GSI query is used only as a locator on a miss.

export function request(ctx) {
    const profileId = (ctx.args && ctx.args.profileId) ? ctx.args.profileId : (ctx.stash && ctx.stash.profileId);

    if (!profileId) {
        util.error('profileId is required', 'INVALID_INPUT');
    }

    // Store profileId in stash for subsequent functions
    if (ctx.stash) {
        ctx.stash.profileId = profileId;
    }

    // Add PROFILE# prefix for DynamoDB query (field resolver strips it for API responses)
    const dbProfileId = normalizeIdOrPrefix(profileId, 'PROFILE#');

    // Step 2 (owner confirmed in Step 1): no further read is needed.
    if (ctx.stash && ctx.stash.isOwner === true) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
        };
    }

    // Step 2 (non-owner confirmed in Step 1): fall back to the GSI query.
    if (ctx.stash && ctx.stash.isOwner === false) {
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
    // to confirm ownership before any eventually-consistent GSI read (#545).
    const callerId = ctx.identity && ctx.identity.sub ? ctx.identity.sub : '';
    const callerAccountId = normalizeIdOrPrefix(callerId, 'ACCOUNT#');

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
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    // Step 1 response: strongly consistent GetItem under caller's partition key.
    // If found, caller is guaranteed to be the owner.
    if (ctx.stash && ctx.stash.isOwner === undefined) {
        const ownerProfile = ctx.result;
        if (ownerProfile) {
            ctx.stash.isOwner = true;
            ctx.stash.profile = ownerProfile;
            ctx.stash.profileOwner = ownerProfile.ownerAccountId;
            ctx.stash.ownerAccountId = ownerProfile.ownerAccountId;
            return ownerProfile;
        }
        // Not the owner: proceed to GSI query in Step 2.
        ctx.stash.isOwner = false;
        return null;
    }

    // Step 2 response for owner: pass confirmed profile through.
    if (ctx.stash && ctx.stash.isOwner === true) {
        return ctx.stash.profile;
    }

    // Step 2 response for non-owner: ctx.result is the GSI Query.
    const items = ctx.result && ctx.result.items;
    if (!items || items.length === 0) {
        util.error('Profile not found', 'NOT_FOUND');
    }

    const profile = items[0];
    if (ctx.stash) {
        ctx.stash.isOwner = false;
        ctx.stash.profile = profile;
        ctx.stash.profileOwner = profile.ownerAccountId;
        ctx.stash.ownerAccountId = profile.ownerAccountId;
    }
    return profile;
}
