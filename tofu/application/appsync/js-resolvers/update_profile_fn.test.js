import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './update_profile_fn.js';

const STASHED_PROFILE = {
    ownerAccountId: 'ACCOUNT#user-123',
    profileId: 'PROFILE#abc',
    sellerName: 'Old Name',
    unitType: 'Pack',
    unitNumber: 158,
};

describe('update_profile_fn request', () => {
    it('rejects a unitType outside Pack, Troop, Crew, Ship, Post', () => {
        const ctx = {
            args: { input: { sellerName: 'New Name', unitType: 'Battalion' } },
            stash: { profile: STASHED_PROFILE },
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: unitType must be one of: Crew, Pack, Post, Ship, Troop/
        );
    });

    it('rejects a unitType that differs only in case', () => {
        const ctx = {
            args: { input: { sellerName: 'New Name', unitType: 'pack' } },
            stash: { profile: STASHED_PROFILE },
        };

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: unitType must be one of: Crew, Pack, Post, Ship, Troop/
        );
    });

    it('accepts every valid unitType: Pack, Troop, Crew, Ship, Post', () => {
        for (const unitType of ['Pack', 'Troop', 'Crew', 'Ship', 'Post']) {
            const ctx = {
                args: { input: { sellerName: 'New Name', unitType: unitType } },
                stash: { profile: STASHED_PROFILE },
            };

            const result = request(ctx);

            assert.strictEqual(result.operation, 'UpdateItem');
            assert.deepStrictEqual(result.key, {
                ownerAccountId: 'ACCOUNT#user-123',
                profileId: 'PROFILE#abc',
            });
            assert.match(result.update.expression, /unitType = :unitType/);
            assert.strictEqual(result.update.expressionValues[':unitType'], unitType);
        }
    });

    it('omits the unit expressions when unitType and unitNumber are absent', () => {
        const ctx = {
            args: { input: { sellerName: 'New Name' } },
            stash: { profile: STASHED_PROFILE },
        };

        const result = request(ctx);

        assert.strictEqual(result.update.expression, 'SET sellerName = :sellerName, updatedAt = :updatedAt');
        assert.deepStrictEqual(Object.keys(result.update.expressionValues).sort(), [':sellerName', ':updatedAt']);
    });

    it('includes both unit expressions when both are provided', () => {
        const ctx = {
            args: { input: { sellerName: 'New Name', unitType: 'Troop', unitNumber: 100 } },
            stash: { profile: STASHED_PROFILE },
        };

        const result = request(ctx);

        assert.strictEqual(
            result.update.expression,
            'SET sellerName = :sellerName, updatedAt = :updatedAt, unitType = :unitType, unitNumber = :unitNumber'
        );
        assert.strictEqual(result.update.expressionValues[':unitNumber'], 100);
    });
});

describe('update_profile_fn response', () => {
    it('merges the provided unit fields over the stashed profile', () => {
        const ctx = {
            result: {},
            args: { input: { sellerName: 'New Name', unitType: 'Troop', unitNumber: 100 } },
            stash: { profile: STASHED_PROFILE },
        };

        const res = response(ctx);

        assert.strictEqual(res.sellerName, 'New Name');
        assert.strictEqual(res.unitType, 'Troop');
        assert.strictEqual(res.unitNumber, 100);
    });

    it('keeps the stashed unit fields when the input omits them', () => {
        const ctx = {
            result: {},
            args: { input: { sellerName: 'New Name' } },
            stash: { profile: STASHED_PROFILE },
        };

        const res = response(ctx);

        assert.strictEqual(res.unitType, 'Pack');
        assert.strictEqual(res.unitNumber, 158);
    });

    it('throws error when ctx.error is present', () => {
        const ctx = {
            error: { message: 'DynamoDB update failure', type: 'DynamoDB:InternalServerError' },
        };

        assert.throws(
            () => response(ctx),
            /DynamoDB:InternalServerError: DynamoDB update failure/
        );
    });
});
