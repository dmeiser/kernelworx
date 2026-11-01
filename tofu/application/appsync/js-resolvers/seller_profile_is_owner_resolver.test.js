import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './seller_profile_is_owner_resolver.js';

describe('seller_profile_is_owner_resolver request', () => {
    it('returns an empty request', () => {
        const result = request({});
        assert.deepStrictEqual(result, {});
    });
});

describe('seller_profile_is_owner_resolver response', () => {
    it('returns true when caller sub matches clean ownerAccountId directly', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            source: { ownerAccountId: 'user-123' },
        };
        assert.strictEqual(response(ctx), true);
    });

    it('returns true when caller sub is clean and ownerAccountId has ACCOUNT# prefix', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            source: { ownerAccountId: 'ACCOUNT#user-123' },
        };
        assert.strictEqual(response(ctx), true);
    });

    it('returns false when caller sub is prefixed but ownerAccountId is clean without prefix', () => {
        const ctx = {
            identity: { sub: 'ACCOUNT#user-123' },
            source: { ownerAccountId: 'user-123' },
        };
        // normalizeIdOrPrefix prefixes callerAccountId; neither expectedOwnerPrefixed nor callerAccountId matches clean
        assert.strictEqual(response(ctx), false);
    });

    it('returns true when both caller sub and ownerAccountId have ACCOUNT# prefix', () => {
        const ctx = {
            identity: { sub: 'ACCOUNT#user-123' },
            source: { ownerAccountId: 'ACCOUNT#user-123' },
        };
        assert.strictEqual(response(ctx), true);
    });

    it('returns false when caller sub does not match ownerAccountId', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            source: { ownerAccountId: 'user-456' },
        };
        assert.strictEqual(response(ctx), false);
    });

    it('returns false when caller sub does not match prefixed ownerAccountId', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            source: { ownerAccountId: 'ACCOUNT#user-456' },
        };
        assert.strictEqual(response(ctx), false);
    });
});
