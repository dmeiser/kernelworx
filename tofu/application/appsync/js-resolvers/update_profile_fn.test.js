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
