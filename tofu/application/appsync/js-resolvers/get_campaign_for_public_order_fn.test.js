import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_campaign_for_public_order_fn.js';

// #679 write slice, spec §10.1: the anchor campaign read and the cheap cap
// pre-check. The authoritative bound is the increment's condition; this read
// only rejects an obviously exhausted campaign before the paid steps run.

function ctxWith(stash) {
    return { stash: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1', ...(stash || {}) }, result: null, error: null };
}

describe('get_campaign_for_public_order_fn request', () => {
    it('GetItems the anchor under the stashed profile key, consistently', () => {
        const result = request(ctxWith());

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' });
        assert.strictEqual(result.consistentRead, true);
    });

    it('answers NOT_FOUND when the stash is missing a key', () => {
        assert.throws(() => request(ctxWith({ campaignId: null })), /NOT_FOUND: Order could not be placed/);
    });
});

describe('get_campaign_for_public_order_fn response', () => {
    it('stashes the campaign and the normalized catalog id for the reused get_catalog step', () => {
        const ctx = ctxWith();
        ctx.result = { campaignId: 'CAMPAIGN#c1', campaignName: 'Fall', isActive: true, catalogId: 'cat1' };

        response(ctx);

        assert.strictEqual(ctx.stash.campaign.campaignName, 'Fall');
        assert.strictEqual(ctx.stash.catalogId, 'CATALOG#cat1');
    });

    it('treats a campaign without isActive as active (back-compat default)', () => {
        const ctx = ctxWith();
        ctx.result = { campaignId: 'CAMPAIGN#c1', catalogId: 'CATALOG#cat1' };
        assert.doesNotThrow(() => response(ctx));
    });

    it('treats isActive null as active', () => {
        const ctx = ctxWith();
        ctx.result = { campaignId: 'CAMPAIGN#c1', catalogId: 'CATALOG#cat1', isActive: null };
        assert.doesNotThrow(() => response(ctx));
    });

    it('rejects a deactivated anchor with NOT_FOUND', () => {
        const ctx = ctxWith();
        ctx.result = { campaignId: 'CAMPAIGN#c1', catalogId: 'CATALOG#cat1', isActive: false };
        assert.throws(() => response(ctx), /NOT_FOUND: Order could not be placed/);
    });

    it('rejects a missing anchor with NOT_FOUND', () => {
        const ctx = ctxWith();
        ctx.result = null;
        assert.throws(() => response(ctx), /NOT_FOUND: Order could not be placed/);
    });

    it('rejects at the cap with the non-retryable limit code', () => {
        const ctx = ctxWith();
        ctx.result = { campaignId: 'CAMPAIGN#c1', catalogId: 'CATALOG#cat1', isActive: true, publicOrderCount: 500 };
        assert.throws(() => response(ctx), /PUBLIC_ORDER_LIMIT_EXCEEDED: This campaign has reached its public order limit/);
    });

    it('accepts one below the cap', () => {
        const ctx = ctxWith();
        ctx.result = { campaignId: 'CAMPAIGN#c1', catalogId: 'CATALOG#cat1', isActive: true, publicOrderCount: 499 };
        assert.doesNotThrow(() => response(ctx));
    });

    it('treats an absent counter as zero orders served', () => {
        const ctx = ctxWith();
        ctx.result = { campaignId: 'CAMPAIGN#c1', catalogId: 'CATALOG#cat1', isActive: true };
        assert.doesNotThrow(() => response(ctx));
    });

    it('rejects a campaign with no catalog', () => {
        const ctx = ctxWith();
        ctx.result = { campaignId: 'CAMPAIGN#c1', isActive: true };
        assert.throws(() => response(ctx), /INVALID_INPUT: Campaign has no catalog assigned/);
    });

    it('surfaces a datastore error unchanged', () => {
        const ctx = ctxWith();
        ctx.error = { type: 'DynamoDB:ThrottlingException', message: 'slow down' };
        assert.throws(() => response(ctx), /ThrottlingException/);
    });
});
