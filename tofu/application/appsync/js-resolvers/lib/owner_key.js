/**
 * Shared owner-verification key construction for the verify_profile_owner_for_*
 * resolver family (#534).
 *
 * The invariant (#438): ownership is decided ONLY by a strongly consistent
 * base-table GetItem keyed {ownerAccountId: <caller>, profileId} - an item
 * found under the caller's own partition key proves ownership. The three
 * owner-verifier resolvers differ only in their FORBIDDEN message, so the key
 * construction lives here, once, instead of being re-implemented (and
 * diverging) in each file.
 */
import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './ids.js';

// The caller's Cognito sub turned into the profiles-table owner partition key.
// Idempotent: an already-prefixed sub is left alone.
export function expectedOwnerKey(sub) {
    return normalizeIdOrPrefix(sub, 'ACCOUNT#');
}

// The strongly consistent base-table GetItem that proves ownership.
export function ownerGetItemRequest(sub, profileId) {
    const dbProfileId = normalizeIdOrPrefix(profileId, 'PROFILE#');
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ ownerAccountId: expectedOwnerKey(sub), profileId: dbProfileId }),
        consistentRead: true
    };
}
