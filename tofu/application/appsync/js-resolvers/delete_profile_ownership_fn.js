import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // In the new multi-table design, there is no separate ownership record
    // Ownership is tracked via the ownerAccountId field on the profile METADATA record
    // This is now a no-op - just return success
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
    };
}

export function response(ctx) {
    // No-op - ownership is implicit via ownerAccountId field
    return true;
}
