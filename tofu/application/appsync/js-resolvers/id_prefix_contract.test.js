/**
 * Behavior-preservation contract for the #534 tree-wide ID-prefix sweep.
 *
 * Every resolver here used to hand-roll its `value.startsWith('PREFIX#') ?
 * value : 'PREFIX#' + value` ternary (or its template-literal twin). Each now
 * routes through lib/ids.js. These tests re-run the same resolvers with
 * already-prefixed, unprefixed, and foreign-prefixed ids and pin the emitted
 * DynamoDB request (or response), proving the conversion did not change what
 * a previously-working caller observes.
 *
 * The one intentional behavior change in the whole sweep - the
 * verify_profile_owner_for_share path no longer double-prefixes an
 * already-prefixed sub - is pinned in lib/verify_profile_owner_cases.js.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert';

import { request as deleteCatalogRequest } from './delete_catalog_fn.js';
import { request as checkCatalogUsageRequest } from './check_catalog_usage_fn.js';
import { request as checkSharePermissionsRequest } from './check_share_permissions_fn.js';
import { request as deleteProfileInviteRequest } from './delete_profile_invite_fn.js';
import { request as queryCampaignsRequest } from './query_campaigns_fn.js';
import { request as createOrderRequest } from './create_order_fn.js';
import { request as listMyProfilesRequest } from './list_my_profiles_fn.js';
import { request as updateCampaignRequest } from './update_campaign_fn.js';
import { request as verifyProfileReadAccessRequest } from './verify_profile_read_access_fn.js';
import { response as querySharesResponse } from './query_shares_fn.js';

const OWNER = { sub: 'user-123' };

describe('guarded-normalization resolvers behave identically for every id shape', () => {
    it('delete_catalog_fn keys its GetItem the same for prefixed, unprefixed, and foreign ids', () => {
        const keyOf = (catalogId) =>
            deleteCatalogRequest({ args: { catalogId } }).key.catalogId;

        assert.strictEqual(keyOf('CATALOG#cat-1'), 'CATALOG#cat-1');
        assert.strictEqual(keyOf('cat-1'), 'CATALOG#cat-1');
        // A foreign prefix is treated as part of the id, not stripped -
        // identical to the old hand-rolled ternary.
        assert.strictEqual(keyOf('PROFILE#cat-1'), 'CATALOG#PROFILE#cat-1');
    });

    it('check_catalog_usage_fn queries with the same normalized key', () => {
        const exprValueOf = (catalogId) =>
            checkCatalogUsageRequest({ args: { catalogId } }).query.expressionValues[':catalogId'];

        assert.strictEqual(exprValueOf('CATALOG#cat-1'), 'CATALOG#cat-1');
        assert.strictEqual(exprValueOf('cat-1'), 'CATALOG#cat-1');
    });

    it('check_share_permissions_fn normalizes both the profile and the caller sub idempotently', () => {
        const keyOf = (profileId, sub) =>
            checkSharePermissionsRequest({
                args: { input: { profileId } },
                identity: { sub },
                stash: {},
            }).key;

        assert.deepStrictEqual(keyOf('prof-1', 'user-123'), {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
        });
        assert.deepStrictEqual(keyOf('PROFILE#prof-1', 'ACCOUNT#user-123'), {
            profileId: 'PROFILE#prof-1',
            targetAccountId: 'ACCOUNT#user-123',
        });
    });

    it('delete_profile_invite_fn builds the owner-keyed GetItem identically', () => {
        const keyOf = (profileId) =>
            deleteProfileInviteRequest({ args: { profileId }, identity: OWNER, stash: {} }).key;

        assert.deepStrictEqual(keyOf('PROFILE#prof-1'), {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-1',
        });
        assert.deepStrictEqual(keyOf('prof-1'), {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-1',
        });
    });
});

describe('unconditional-normalization resolvers behave identically', () => {
    it('query_campaigns_fn queries by the same prefixed profileId', () => {
        const exprValueOf = (profileId) =>
            queryCampaignsRequest({ args: { profileId }, stash: { authorized: true } })
                .query.expressionValues[':profileId'];

        assert.strictEqual(exprValueOf('PROFILE#prof-1'), 'PROFILE#prof-1');
        assert.strictEqual(exprValueOf('prof-1'), 'PROFILE#prof-1');
    });

    it('list_my_profiles_fn keys the caller partition idempotently', () => {
        const accountIdOf = (sub) =>
            listMyProfilesRequest({ identity: { sub }, args: {} })
                .query.expressionValues[':accountId'].S;

        assert.strictEqual(accountIdOf('user-123'), 'ACCOUNT#user-123');
        assert.strictEqual(accountIdOf('ACCOUNT#user-123'), 'ACCOUNT#user-123');
    });

    it('verify_profile_read_access_fn keys its step 1 GetItem byte-identically for a bare sub', () => {
        // #508 rewrote this resolver to decide ownership from a strongly
        // consistent base-table GetItem, and #534 routed its two prefix
        // constructions through lib/ids.js. The GetItem key is the whole
        // authorization signal, so the composite key must stay byte-for-byte
        // what the pre-#534 hand-rolled ternaries emitted - a bare Cognito
        // `sub` must still yield exactly 'ACCOUNT#<sub>'.
        const keyOf = (sub, profileId) =>
            verifyProfileReadAccessRequest({
                identity: { sub },
                args: { profileId },
                stash: {},
            }).key;

        assert.deepStrictEqual(keyOf('user-123', 'prof-1'), {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-1',
        });
        assert.deepStrictEqual(keyOf('ACCOUNT#user-123', 'PROFILE#prof-1'), {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-1',
        });
        // A foreign prefix is part of the id, exactly as the old ternary treated it.
        assert.strictEqual(keyOf('PROFILE#user-123', 'prof-1').ownerAccountId, 'ACCOUNT#PROFILE#user-123');
    });

    it('create_order_fn mints the same ORDER# sort key for prefixed and unprefixed campaign ids', () => {
        const orderIdOf = (campaignId) =>
            createOrderRequest({
                args: {
                    input: {
                        profileId: 'PROFILE#prof-1',
                        campaignId,
                        customerName: 'Alice',
                        orderDate: '2024-01-01T00:00:00Z',
                        lineItems: [{ productId: 'PROD#1', quantity: 1 }],
                    },
                },
                identity: OWNER,
                stash: {
                    campaign: { profileId: 'PROFILE#prof-1' },
                    catalog: { products: [{ productId: 'PROD#1', productName: 'Popcorn', price: 1.99 }] },
                },
            }).attributeValues.orderId;

        // util.autoId() is mocked to a constant; only the prefix handling differs.
        const prefixed = orderIdOf('CAMPAIGN#camp-1');
        const unprefixed = orderIdOf('camp-1');
        assert.strictEqual(prefixed, unprefixed);
        assert.ok(prefixed.startsWith('ORDER#camp-1#'));
    });
});

describe('update_campaign_fn keeps its deliberate null passthrough', () => {
    it('still writes catalogId = null when the input clears the catalog', () => {
        const request = updateCampaignRequest({
            args: { input: { catalogId: null } },
            stash: { campaign: { profileId: 'PROFILE#prof-1', campaignId: 'CAMPAIGN#camp-1' } },
        });

        assert.strictEqual(request.operation, 'UpdateItem');
        assert.strictEqual(request.update.expressionValues[':catalogId'], null);
        assert.ok(request.update.expression.includes('catalogId = :catalogId'));
    });

    it('normalizes a non-null catalogId exactly as the old ternary did', () => {
        const request = updateCampaignRequest({
            args: { input: { catalogId: 'cat-1' } },
            stash: { campaign: { profileId: 'PROFILE#prof-1', campaignId: 'CAMPAIGN#camp-1' } },
        });

        assert.strictEqual(request.update.expressionValues[':catalogId'], 'CATALOG#cat-1');
    });
});

describe('prefix-stripping resolvers behave identically', () => {
    it('query_shares_fn strips the ACCOUNT# prefix from returned share targets and nothing else', () => {
        const result = querySharesResponse({
            result: {
                items: [
                    { profileId: 'PROFILE#prof-1', targetAccountId: 'ACCOUNT#user-1' },
                    { profileId: 'PROFILE#prof-1', targetAccountId: 'user-2' },
                ],
            },
        });

        assert.deepStrictEqual(result[0].targetAccountId, 'user-1');
        assert.deepStrictEqual(result[1].targetAccountId, 'user-2');
    });
});
