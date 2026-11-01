import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_shared_campaign_for_delete_fn.js';

describe('get_shared_campaign_for_delete_fn request', () => {
    it('reads the shared campaign by the raw sharedCampaignCode key', () => {
        const ctx = { args: { sharedCampaignCode: 'SHARED-ABC123' }, identity: { sub: 'user-1' }, stash: {} };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        // sharedCampaignCode is the table's own partition key and carries no
        // ACCOUNT#/CAMPAIGN# prefix, so it must pass through untouched.
        assert.deepStrictEqual(result.key, { sharedCampaignCode: 'SHARED-ABC123' });
    });
});

describe('get_shared_campaign_for_delete_fn response', () => {
    const owned = { sharedCampaignCode: 'SHARED-ABC123', createdBy: 'ACCOUNT#user-1' };

    it('authorizes the creator and stashes the item for the delete step', () => {
        const ctx = { result: owned, identity: { sub: 'user-1' }, stash: {} };

        assert.strictEqual(response(ctx), owned);
        assert.strictEqual(ctx.stash.sharedCampaign, owned);
    });

    it('authorizes a creator whose sub already carries the ACCOUNT# prefix', () => {
        const ctx = { result: owned, identity: { sub: 'ACCOUNT#user-1' }, stash: {} };

        assert.strictEqual(response(ctx), owned);
    });

    it('denies a non-creator with FORBIDDEN and stashes nothing', () => {
        const ctx = { result: owned, identity: { sub: 'user-2' }, stash: {} };

        assert.throws(
            () => response(ctx),
            /FORBIDDEN: Only the creator can delete this campaign sharedCampaign/,
        );
        assert.strictEqual(ctx.stash.sharedCampaign, undefined);
    });

    it('denies a caller whose sub is a bare prefix that matches no account', () => {
        // normalizeIdOrPrefix turns a missing sub into the bare 'ACCOUNT#'
        // placeholder; that must never match a real createdBy value.
        const ctx = { result: owned, identity: {}, stash: {} };

        assert.throws(() => response(ctx), /FORBIDDEN: Only the creator can delete/);
    });

    it('fails with NOT_FOUND when the shared campaign does not exist', () => {
        for (const result of [undefined, null]) {
            const ctx = { result, identity: { sub: 'user-1' }, stash: {} };

            assert.throws(() => response(ctx), /NOT_FOUND: Shared Campaign not found/);
        }
    });

    it('propagates a DynamoDB error before the ownership check', () => {
        const ctx = { error: { message: 'Throttling', type: 'RESOURCE_BUSY' }, identity: { sub: 'user-1' }, stash: {} };

        assert.throws(() => response(ctx), /RESOURCE_BUSY: Throttling/);
    });
});
