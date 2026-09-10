import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './list_my_shares_pipeline_resolver.js';

describe('list_my_shares_pipeline_resolver request', () => {
    it('returns an empty request (functions carry the operations)', () => {
        assert.deepStrictEqual(request({}), {});
    });
});

describe('list_my_shares_pipeline_resolver response', () => {
    it('passes through the merged SharedProfile array from the previous function', () => {
        const sharedProfiles = [
            {
                profileId: 'PROFILE#p1',
                ownerAccountId: 'ACCOUNT#owner-1',
                sellerName: 'Alice',
                unitType: null,
                unitNumber: null,
                createdAt: '2024-01-01T00:00:00Z',
                updatedAt: '2024-02-01T00:00:00Z',
                isOwner: false,
                permissions: ['READ'],
            },
        ];
        const ctx = { prev: { result: sharedProfiles } };

        const result = response(ctx);

        assert.deepStrictEqual(result, sharedProfiles);
    });

    it('returns an empty array when prev.result is missing', () => {
        assert.deepStrictEqual(response({ prev: {} }), []);
    });

    it('throws error when ctx.error is present', () => {
        const ctx = {
            error: { message: 'pipeline failed', type: 'InternalServerError' },
            prev: { result: [] },
        };

        assert.throws(() => response(ctx), /InternalServerError: pipeline failed/);
    });
});
