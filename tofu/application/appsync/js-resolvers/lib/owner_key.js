import { util } from '@aws-appsync/utils';
import { normalizeId } from './ids.js';

export function expectedOwnerKey(sub) {
    return normalizeId(sub, 'ACCOUNT#');
}

// Owner-verification read for the #438 write-authz invariant: ownership is
// decided ONLY by a strongly consistent base-table GetItem keyed
// {ownerAccountId: <caller>, profileId} — never by the profileId-index GSI,
// which can keep projecting the previous owner right after a transfer.
export function ownerGetItemRequest(sub, profileId) {
    const expectedOwner = expectedOwnerKey(sub);
    const dbProfileId = normalizeId(profileId, 'PROFILE#');
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
            ownerAccountId: expectedOwner,
            profileId: dbProfileId
        }),
        consistentRead: true
    };
}
