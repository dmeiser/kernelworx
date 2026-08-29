import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request as createOrderRequest } from './create_order_fn.js';
import {
    request as getCampaignForOrderRequest,
    response as getCampaignForOrderResponse,
} from './get_campaign_for_order_fn.js';
import { request as getCatalogRequest, response as getCatalogResponse } from './get_catalog_fn.js';
import {
    request as getCatalogForDeleteRequest,
    response as getCatalogForDeleteResponse,
} from './get_catalog_for_delete_fn.js';

/**
 * Verifies that the resolvers touched by the console.log removal continue to
 * behave correctly and do not write anything to console.log. This is a
 * behavioral guard: it executes the public request/response interfaces rather
 * than grepping source text.
 */
describe('production AppSync resolvers do not log to console', () => {
    /**
     * Captures any console.log calls made while `fn` runs and returns them.
     * The original method is restored afterwards.
     */
    function captureLogs(fn) {
        const calls = [];
        const original = console.log;
        console.log = (...args) => {
            calls.push(args);
        };
        try {
            return { result: fn(), calls, error: null };
        } catch (error) {
            return { result: null, calls, error };
        } finally {
            console.log = original;
        }
    }

    it('create_order_fn request builds PutItem without logging', () => {
        const { result, calls } = captureLogs(() =>
            createOrderRequest({
                args: {
                    input: {
                        profileId: 'PROFILE#scout',
                        campaignId: 'CAMPAIGN#c1',
                        customerName: 'Alice Example',
                        customerPhone: '555-123-4567',
                        orderDate: '2024-01-15',
                        paymentMethod: 'cash',
                        lineItems: [{ productId: 'PRODUCT#1', quantity: 2 }],
                    },
                },
                stash: {
                    campaign: { profileId: 'PROFILE#scout', campaignId: 'CAMPAIGN#c1' },
                    catalog: {
                        products: [
                            { productId: 'PRODUCT#1', productName: 'Widget', price: 10.0 },
                        ],
                    },
                },
            })
        );

        assert.strictEqual(result.operation, 'PutItem');
        assert.strictEqual(result.key.campaignId, 'CAMPAIGN#c1');
        assert.strictEqual(result.attributeValues.customerName, 'Alice Example');
        assert.deepStrictEqual(calls, []);
    });

    it('get_campaign_for_order_fn request and response do not log', () => {
        const requestResult = captureLogs(() =>
            getCampaignForOrderRequest({
                args: { input: { campaignId: 'CAMPAIGN#c1' } },
            })
        );
        assert.strictEqual(requestResult.result.operation, 'Query');
        assert.deepStrictEqual(requestResult.calls, []);

        const responseResult = captureLogs(() =>
            getCampaignForOrderResponse({
                result: {
                    items: [
                        {
                            campaignId: 'CAMPAIGN#c1',
                            catalogId: 'cat-123',
                            profileId: 'PROFILE#scout',
                        },
                    ],
                },
                stash: {},
            })
        );
        assert.strictEqual(responseResult.result.campaignId, 'CAMPAIGN#c1');
        assert.deepStrictEqual(responseResult.calls, []);
    });

    it('get_catalog_fn request and response do not log', () => {
        const requestResult = captureLogs(() =>
            getCatalogRequest({
                stash: { catalogId: 'cat-123' },
            })
        );
        assert.strictEqual(requestResult.result.operation, 'GetItem');
        assert.strictEqual(requestResult.result.key.catalogId, 'CATALOG#cat-123');
        assert.deepStrictEqual(requestResult.calls, []);

        const responseResult = captureLogs(() =>
            getCatalogResponse({
                result: {
                    catalogId: 'CATALOG#cat-123',
                    products: [{ productId: 'PRODUCT#1' }],
                },
                stash: {},
            })
        );
        assert.strictEqual(responseResult.result.catalogId, 'CATALOG#cat-123');
        assert.deepStrictEqual(responseResult.calls, []);

        const missingResult = captureLogs(() =>
            getCatalogResponse({
                result: null,
                stash: { catalogId: 'CATALOG#missing' },
            })
        );
        assert.strictEqual(
            missingResult.error.message,
            'NotFound: Catalog not found for id: CATALOG#missing'
        );
        assert.deepStrictEqual(missingResult.calls, []);
    });

    it('get_catalog_for_delete_fn request and response do not log', () => {
        const requestResult = captureLogs(() =>
            getCatalogForDeleteRequest({
                args: { catalogId: 'cat-123' },
                identity: { sub: 'user-1' },
                stash: {},
            })
        );
        assert.strictEqual(requestResult.result.operation, 'GetItem');
        assert.strictEqual(requestResult.result.key.catalogId, 'CATALOG#cat-123');
        assert.deepStrictEqual(requestResult.calls, []);

        const responseResult = captureLogs(() =>
            getCatalogForDeleteResponse({
                result: {
                    catalogId: 'CATALOG#cat-123',
                    ownerAccountId: 'ACCOUNT#user-1',
                },
                identity: {
                    sub: 'user-1',
                    claims: { 'cognito:groups': [] },
                },
                stash: { callerId: 'user-1' },
            })
        );
        assert.strictEqual(responseResult.result.catalogId, 'CATALOG#cat-123');
        assert.deepStrictEqual(responseResult.calls, []);
    });
});
