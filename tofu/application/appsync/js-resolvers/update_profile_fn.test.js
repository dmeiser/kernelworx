import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './update_profile_fn.js';

const PROFILE = {
    ownerAccountId: 'ACCOUNT#sub-user-123',
    profileId: 'PROFILE#p1',
    sellerName: 'Old Name',
};

function makeCtx(input) {
    return {
        stash: { profile: PROFILE },
        args: { input },
    };
}

describe('update_profile_fn request', () => {
    it('rejects whitespace-only sellerName', () => {
        assert.throws(
            () => request(makeCtx({ profileId: 'PROFILE#p1', sellerName: '   ' })),
            /INVALID_INPUT: sellerName is required/
        );
    });

    it('rejects sellerName exceeding 100 characters', () => {
        assert.throws(
            () => request(makeCtx({ profileId: 'PROFILE#p1', sellerName: 'A'.repeat(101) })),
            /INVALID_INPUT: sellerName cannot exceed 100 characters/
        );
    });

    it('stores the trimmed sellerName in the update expression', () => {
        const result = request(makeCtx({ profileId: 'PROFILE#p1', sellerName: '  New Name  ' }));

        assert.strictEqual(result.operation, 'UpdateItem');
        assert.strictEqual(result.key.ownerAccountId, 'ACCOUNT#sub-user-123');
        assert.strictEqual(result.key.profileId, 'PROFILE#p1');
        assert.strictEqual(result.update.expressionValues[':sellerName'], 'New Name');
    });

    it('accepts sellerName of exactly 100 characters', () => {
        const result = request(makeCtx({ profileId: 'PROFILE#p1', sellerName: 'A'.repeat(100) }));

        assert.strictEqual(result.update.expressionValues[':sellerName'], 'A'.repeat(100));
    });

    it('includes optional unit fields when provided', () => {
        const result = request(
            makeCtx({ profileId: 'PROFILE#p1', sellerName: 'New Name', unitType: 'Troop', unitNumber: 100 })
        );

        assert.match(result.update.expression, /unitType = :unitType/);
        assert.match(result.update.expression, /unitNumber = :unitNumber/);
        assert.strictEqual(result.update.expressionValues[':unitType'], 'Troop');
        assert.strictEqual(result.update.expressionValues[':unitNumber'], 100);
    });

    it('omits optional unit fields when not provided', () => {
        const result = request(makeCtx({ profileId: 'PROFILE#p1', sellerName: 'New Name' }));

        assert.doesNotMatch(result.update.expression, /unitType/);
        assert.doesNotMatch(result.update.expression, /unitNumber/);
    });

    it('omits optional unit fields when passed explicit null', () => {
        const result = request(
            makeCtx({ profileId: 'PROFILE#p1', sellerName: 'New Name', unitType: null, unitNumber: null })
        );

        assert.doesNotMatch(result.update.expression, /unitType/);
        assert.doesNotMatch(result.update.expression, /unitNumber/);
        assert.strictEqual(result.update.expressionValues[':unitType'], undefined);
        assert.strictEqual(result.update.expressionValues[':unitNumber'], undefined);
    });

    it('rejects a unitType outside the whitelist', () => {
        assert.throws(
            () => request(makeCtx({ profileId: 'PROFILE#p1', sellerName: 'New Name', unitType: 'Den' })),
            /INVALID_INPUT: unitType must be one of: Crew, Pack, Post, Ship, Troop/
        );
    });

    it('rejects an invalid unitNumber before writing anything', () => {
        for (const unitNumber of ['42', 0, -1, 2.5]) {
            assert.throws(
                () => request(makeCtx({ profileId: 'PROFILE#p1', sellerName: 'New Name', unitNumber })),
                /INVALID_INPUT: unitNumber must be a positive integer/
            );
        }
    });
});

describe('update_profile_fn response', () => {
    it('returns the merged profile with the trimmed sellerName', () => {
        const ctx = {
            stash: { profile: PROFILE },
            args: { input: { profileId: 'PROFILE#p1', sellerName: '  New Name  ' } },
            result: {},
        };

        const res = response(ctx);
        assert.strictEqual(res.sellerName, 'New Name');
        assert.strictEqual(res.ownerAccountId, 'ACCOUNT#sub-user-123');
        assert.strictEqual(res.profileId, 'PROFILE#p1');
    });

    it('echoes the unit fields it actually wrote', () => {
        const ctx = {
            stash: { profile: { ...PROFILE, unitType: 'Pack', unitNumber: 4 } },
            args: { input: { profileId: 'PROFILE#p1', sellerName: 'New Name', unitType: 'Troop', unitNumber: 100 } },
            result: {},
        };

        const res = response(ctx);
        assert.strictEqual(res.unitType, 'Troop');
        assert.strictEqual(res.unitNumber, 100);
    });

    it('keeps the stored unit fields when the input passes null', () => {
        const stored = { ...PROFILE, unitType: 'Troop', unitNumber: 100 };
        const input = { profileId: 'PROFILE#p1', sellerName: 'New Name', unitType: null, unitNumber: null };

        const res = response({ stash: { profile: stored }, args: { input }, result: {} });
        assert.strictEqual(res.unitType, 'Troop');
        assert.strictEqual(res.unitNumber, 100);

        // response() must not disagree with request() on the same input.
        const req = request({ stash: { profile: stored }, args: { input } });
        assert.doesNotMatch(req.update.expression, /unitType|unitNumber/);
    });

    it('keeps the stored unit fields when the input omits them', () => {
        const ctx = {
            stash: { profile: { ...PROFILE, unitType: 'Ship', unitNumber: 9 } },
            args: { input: { profileId: 'PROFILE#p1', sellerName: 'New Name' } },
            result: {},
        };

        const res = response(ctx);
        assert.strictEqual(res.unitType, 'Ship');
        assert.strictEqual(res.unitNumber, 9);
    });

    it('rejects an invalid unit value in response() too', () => {
        const ctx = {
            stash: { profile: PROFILE },
            args: { input: { profileId: 'PROFILE#p1', sellerName: 'New Name', unitType: 'Den' } },
            result: {},
        };

        assert.throws(() => response(ctx), /INVALID_INPUT: unitType must be one of/);
    });

    it('throws error when ctx.error is present', () => {
        const ctx = {
            stash: { profile: PROFILE },
            args: { input: { profileId: 'PROFILE#p1', sellerName: 'New Name' } },
            error: {
                message: 'DynamoDB update failure',
                type: 'DynamoDB:InternalServerError',
            },
        };

        assert.throws(
            () => response(ctx),
            /DynamoDB:InternalServerError: DynamoDB update failure/
        );
    });
});
