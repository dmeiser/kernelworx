import { describe, it } from 'node:test';
import assert from 'node:assert';

import { response as checkSharePermissions } from './check_share_permissions_fn.js';
import { response as checkProfileReadAuth } from './check_profile_read_auth_fn.js';
import { response as checkWritePermission } from './check_write_permission_fn.js';
import { response as checkShareReadPermissions } from './check_share_read_permissions_fn.js';
import { response as checkPaymentMethodsAccess } from './check_payment_methods_access_fn.js';
import { response as sellerProfilePermissions } from './seller_profile_permissions_resolver.js';

// #553: every authorization step must fail closed on a datastore error. Returning a
// value (null permissions, authorized: false) instead of util.error is silent
// fail-closed: the caller cannot tell an outage from a real denial, so the field
// vanishes from the response and never reaches AppSync's resolver error metrics.
// util.error is the only outcome that surfaces the failure.
const AUTHORIZATION_RESOLVERS = [
    ['check_share_permissions_fn', checkSharePermissions],
    ['check_profile_read_auth_fn', checkProfileReadAuth],
    ['check_write_permission_fn', checkWritePermission],
    ['check_share_read_permissions_fn', checkShareReadPermissions],
    ['check_payment_methods_access_fn', checkPaymentMethodsAccess],
    ['seller_profile_permissions_resolver', sellerProfilePermissions],
];

describe('authorization resolvers fail closed on ctx.error', () => {
    for (const [name, response] of AUTHORIZATION_RESOLVERS) {
        it(`${name} propagates the datastore error via util.error`, () => {
            const ctx = {
                stash: {},
                error: { message: 'DynamoDB failure', type: 'DynamoDBException' },
            };

            assert.throws(
                () => response(ctx),
                (err) => {
                    assert.strictEqual(
                        err.message,
                        'DynamoDBException: DynamoDB failure',
                        `${name} must surface the underlying datastore error, not swallow it`
                    );
                    return true;
                }
            );
        });

    }
});
