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
            { 'cognito:groups': ['ADMIN'], mfa: true },
            { ...baseCatalog, ownerAccountId: 'ACCOUNT#somebody-else' },
            'admin-123'
        );

        response(ctx);

        assert.strictEqual(ctx.stash.authorized, true);
    });

    it('denies an admin with amr claim but without mfa:true', () => {
        const ctx = makeCtx(
            { 'cognito:groups': ['ADMIN'], amr: ['mfa', 'pwd'] },
            { ...baseCatalog, ownerAccountId: 'ACCOUNT#somebody-else' },
            'admin-123'
        );

        assert.throws(() => response(ctx), /FORBIDDEN: MFA required/);
        assert.strictEqual(ctx.stash.authorized, undefined);
    });

    it('denies an admin when mfa claim is false even with amr present', () => {
        const ctx = makeCtx(
            { 'cognito:groups': ['ADMIN'], mfa: false, amr: ['mfa', 'pwd', 'webauthn'] },
            { ...baseCatalog, ownerAccountId: 'ACCOUNT#somebody-else' },
            'admin-123'
        );

        assert.throws(() => response(ctx), /FORBIDDEN: MFA required/);
        assert.strictEqual(ctx.stash.authorized, undefined);
    });

    it('denies an admin when mfa claim is a non-boolean string "true"', () => {
        const ctx = makeCtx(
            { 'cognito:groups': ['ADMIN'], mfa: 'true' },
            { ...baseCatalog, ownerAccountId: 'ACCOUNT#somebody-else' },
            'admin-123'
        );

        assert.throws(() => response(ctx), /FORBIDDEN: MFA required/);
        assert.strictEqual(ctx.stash.authorized, undefined);
    });

    it('denies an admin without MFA with exactly "MFA required"', () => {
        const ctx = makeCtx(
            { 'cognito:groups': ['ADMIN'] }, // no mfa claim
            { ...baseCatalog, ownerAccountId: 'ACCOUNT#somebody-else' },
            'admin-123'
        );

        assert.throws(() => response(ctx), /FORBIDDEN: MFA required/);
        assert.strictEqual(ctx.stash.authorized, undefined);
    });

    it('does not treat the lowercase group "admin" as admin (#504)', () => {
        // The Cognito admin group is created out-of-band and is uppercase
        // everywhere else in the codebase. A lowercase 'admin' group must not
        // grant deleteCatalog over someone else's catalog, MFA or not.
        for (const mfa of [true, false, undefined]) {
            const ctx = makeCtx(
                { 'cognito:groups': ['admin'], mfa },
                { ...baseCatalog, ownerAccountId: 'ACCOUNT#somebody-else' },
                'admin-123'
            );

            assert.throws(
                () => response(ctx),
                /FORBIDDEN: Not authorized to delete this catalog/,
                `mfa=${String(mfa)} must not grant admin to the lowercase group`
            );
            assert.strictEqual(ctx.stash.authorized, undefined);
        }
    });

    it('still authorizes the uppercase group even among other groups', () => {
        const ctx = makeCtx(
            { 'cognito:groups': ['some-other-group', 'ADMIN'], mfa: true },
            { ...baseCatalog, ownerAccountId: 'ACCOUNT#somebody-else' },
            'admin-123'
        );

        response(ctx);

        assert.strictEqual(ctx.stash.authorized, true);
    });

    it('accepts a string-formatted groups claim (not just an array)', () => {
        const ctx = makeCtx(
            { 'cognito:groups': 'ADMIN', mfa: true },
            { ...baseCatalog, ownerAccountId: 'ACCOUNT#somebody-else' },
            'admin-123'
        );

        response(ctx);

        assert.strictEqual(ctx.stash.authorized, true);
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
