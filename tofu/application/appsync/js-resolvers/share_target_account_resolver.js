import { util } from '@aws-appsync/utils';

// Fields of the DynamoDB account item that are safe to expose to any
// collaborator who can list shares on a profile (#455). The full item —
// in particular the opaque `preferences` blob (Account.preferences: AWSJSON)
// managed via updateMyPreferences — must never leak through Share.targetAccount.
const PUBLIC_ACCOUNT_FIELDS = [
    'accountId',
    'email',
    'givenName',
    'familyName',
    'city',
    'state',
    'unitType',
    'unitNumber',
    'createdAt',
    'updatedAt',
];

export function request(ctx) {
    const targetAccountId = ctx.source.targetAccountId;

    // Normalize accountId to ensure ACCOUNT# prefix
    const dbAccountId = targetAccountId && targetAccountId.startsWith('ACCOUNT#')
        ? targetAccountId
        : `ACCOUNT#${targetAccountId}`;

    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({
            accountId: dbAccountId
        })
    };
}

export function response(ctx) {
    if (ctx.error) {
        return null;  // Return null if account not found
    }
    if (!ctx.result) {
        return null;
    }

    // Explicit per-field copy (no spread): APPSYNC_JS 1.0.0 rejects some
    // modern JS constructs at CreateResolver time, and a whitelist makes the
    // collaborator-visible surface reviewable.
    const account = {};
    for (const field of PUBLIC_ACCOUNT_FIELDS) {
        if (ctx.result[field] !== undefined) {
            account[field] = ctx.result[field];
        }
    }
    return account;
}
