import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './update_seller_profile_resolver.js';

describe('update_seller_profile_resolver request', () => {
    it('returns empty request object', () => {
        assert.deepStrictEqual(request({}), {});
    });
});

describe('update_seller_profile_resolver response', () => {
    it('passes through previous step result', () => {
        const profile = { profileId: 'p-1', sellerName: 'Scout' };
        assert.strictEqual(response({ prev: { result: profile } }), profile);
    });

    it('passes through null previous result', () => {
        assert.strictEqual(response({ prev: { result: null } }), null);
    });
});
