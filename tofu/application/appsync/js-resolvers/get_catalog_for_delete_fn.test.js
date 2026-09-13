import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_catalog_for_delete_fn.js';

describe('get_catalog_for_delete_fn request', () => {
    it('requests the catalog by catalogId, normalizing the CATALOG# prefix', () => {
        const ctx = { args: { catalogId: 'catalog-abc' }, stash: {}, identity: { sub: 'owner-123' } };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { catalogId: 'CATALOG#catalog-abc' });
        assert.strictEqual(ctx.stash.callerId, 'owner-123');
    });
});

describe('get_catalog_for_delete_fn response', () => {
    const baseCatalog = { catalogId: 'CATALOG#catalog-abc', ownerAccountId: 'ACCOUNT#owner-123' };

    // request() sets ctx.stash.callerId = ctx.identity.sub, so a response test
    // reproduces that before invoking response.
    function makeCtx(claims, catalog, callerSub = 'caller-123') {
        return {
            result: catalog || baseCatalog,
            identity: { sub: callerSub, claims },
            stash: { callerId: callerSub },
        };
    }

    it('authorizes the owner without MFA', () => {
        // owner-123 owns baseCatalog (ownerAccountId = 'ACCOUNT#owner-123'); no groups, no amr
        const ctx = makeCtx({}, undefined, 'owner-123');

        response(ctx);

        assert.strictEqual(ctx.stash.authorized, true);
    });

    it('authorizes an MFA-verified admin for any catalog', () => {
        const ctx = makeCtx(
            { 'cognito:groups': ['admin'], amr: ['mfa'] },
            { ...baseCatalog, ownerAccountId: 'ACCOUNT#somebody-else' },
            'admin-123'
        );

        response(ctx);

        assert.strictEqual(ctx.stash.authorized, true);
    });

    it('authorizes an MFA-verified admin when amr is a string', () => {
        const ctx = makeCtx(
            { 'cognito:groups': ['ADMIN'], amr: 'mfa' },
            { ...baseCatalog, ownerAccountId: 'ACCOUNT#somebody-else' },
            'admin-123'
        );

        response(ctx);

        assert.strictEqual(ctx.stash.authorized, true);
    });

    it('denies an admin without MFA with exactly "MFA required"', () => {
        const ctx = makeCtx(
            { 'cognito:groups': ['admin'] }, // no amr claim
            { ...baseCatalog, ownerAccountId: 'ACCOUNT#somebody-else' },
            'admin-123'
        );

        assert.throws(() => response(ctx), /FORBIDDEN: MFA required/);
        assert.strictEqual(ctx.stash.authorized, undefined);
    });

    it('denies a non-admin non-owner', () => {
        const ctx = makeCtx(
            {},
            { ...baseCatalog, ownerAccountId: 'ACCOUNT#somebody-else' },
            'stranger-123'
        );

        assert.throws(() => response(ctx), /FORBIDDEN: Not authorized to delete this catalog/);
    });

    it('throws the propagated DynamoDB error when ctx.error is set', () => {
        const ctx = makeCtx({}, undefined, 'owner-123');
        ctx.error = { message: 'DynamoDB timeout', type: 'INTERNAL_ERROR' };

        assert.throws(() => response(ctx), /INTERNAL_ERROR: DynamoDB timeout/);
    });
});
