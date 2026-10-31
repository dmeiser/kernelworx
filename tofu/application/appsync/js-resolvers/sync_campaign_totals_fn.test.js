import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './sync_campaign_totals_fn.js';

// #746: the denormalized Campaign.totalOrders / Campaign.totalRevenue counter
// sync. The producers (create/update/delete order steps) stash the delta on
// ctx.stash.totalsDelta; this function turns it into one atomic ADD on the
// campaign item.

describe('sync_campaign_totals_fn request', () => {
    it('turns a create delta into an atomic ADD on the campaign key', () => {
        const result = request({
            stash: {
                totalsDelta: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1', count: 1, revenue: 19.99 },
            },
            prev: { result: { orderId: 'ORDER#x' } },
        });
        assert.strictEqual(result.operation, 'UpdateItem');
        assert.deepStrictEqual(result.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' });
        assert.strictEqual(result.update.expression, 'ADD #totalOrders :count, #totalRevenue :revenue');
        assert.deepStrictEqual(result.update.expressionNames, {
            '#totalOrders': 'totalOrders',
            '#totalRevenue': 'totalRevenue',
        });
        assert.deepStrictEqual(result.update.expressionValues, { ':count': 1, ':revenue': 19.99 });
        assert.strictEqual(result.condition.expression, 'attribute_exists(campaignId)');
    });

    it('rounds a sub-cent float tail out of the revenue delta', () => {
        const result = request({
            stash: {
                totalsDelta: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1', count: 0, revenue: 0.010000000000000231 },
            },
            prev: { result: {} },
        });
        assert.deepStrictEqual(result.update.expressionValues, { ':count': 0, ':revenue': 0.01 });
    });

    it('applies a delete delta with negative count and revenue', () => {
        const result = request({
            stash: {
                totalsDelta: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1', count: -1, revenue: -59.97 },
            },
            prev: { result: true },
        });
        assert.deepStrictEqual(result.update.expressionValues, { ':count': -1, ':revenue': -59.97 });
    });

    it('skips the datastore call entirely when no delta was stashed', () => {
        const result = request({
            stash: {},
            prev: { result: { orderId: 'ORDER#x' } },
        });
        assert.deepStrictEqual(result, { orderId: 'ORDER#x' });
    });

    it('skips the datastore call when the delta is all zeros', () => {
        const result = request({
            stash: {
                totalsDelta: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1', count: 0, revenue: 0 },
            },
            prev: { result: true },
        });
        assert.strictEqual(result, true);
    });
});

describe('sync_campaign_totals_fn response', () => {
    it('passes the previous step result through on success', () => {
        const result = response({
            result: {},
            prev: { result: { orderId: 'ORDER#x', totalAmount: 19.99 } },
        });
        assert.deepStrictEqual(result, { orderId: 'ORDER#x', totalAmount: 19.99 });
    });

    it('swallows the race where deleteCampaign removed the campaign mid-mutation', () => {
        const result = response({
            error: { type: 'DynamoDB:ConditionalCheckFailedException', message: 'The conditional request failed' },
            prev: { result: { orderId: 'ORDER#x' } },
        });
        assert.deepStrictEqual(result, { orderId: 'ORDER#x' });
    });

    it('aborts the mutation on any other data source error', () => {
        assert.throws(
            () =>
                response({
                    error: { type: 'DynamoDB:ProvisionedThroughputExceededException', message: 'throttled' },
                    prev: { result: true },
                }),
            /DynamoDB:ProvisionedThroughputExceededException: throttled/
        );
    });
});
