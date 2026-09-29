import { util } from '@aws-appsync/utils';
import { normalizeId } from './ids.js';

export function expectedOwnerKey(sub) {
    return normalizeId(sub, 'ACCOUNT#');
}

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
