import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './create_seller_profile_resolver.js';

describe('create_seller_profile_resolver request', () => {
    it('requires authentication when identity is missing', () => {
        const ctx = {
            args: {
                input: {
                    sellerName: 'Valid Name',
                },
            },
        };

        assert.throws(
            () => request(ctx),
            /Unauthorized: Authentication required/
        );
    });

    it('requires authentication when identity.sub is missing', () => {
        const ctx = {
            identity: {},
            args: {
                input: {
                    sellerName: 'Valid Name',
                },
            },
        };

        assert.throws(
            () => request(ctx),
            /Unauthorized: Authentication required/
        );
    });

    it('rejects missing sellerName', () => {
        const ctx = {
            identity: { sub: 'user-sub-123' },
            args: {
                input: {},
            },
        };

        assert.throws(
            () => request(ctx),
            /BadRequest: sellerName is required/
        );
    });

    it('rejects missing input argument object', () => {
        const ctx = {
            identity: { sub: 'user-sub-123' },
            args: {},
        };

        assert.throws(
            () => request(ctx),
            /BadRequest: sellerName is required/
        );
    });

    it('rejects empty or whitespace sellerName', () => {
        const ctx = {
            identity: { sub: 'user-sub-123' },
            args: {
                input: {
                    sellerName: '   ',
                },
            },
        };

        assert.throws(
            () => request(ctx),
            /BadRequest: sellerName is required/
        );
    });

    it('rejects sellerName exceeding 100 characters', () => {
        const ctx = {
            identity: { sub: 'user-sub-123' },
            args: {
                input: {
                    sellerName: 'A'.repeat(101),
                },
            },
        };

        assert.throws(
            () => request(ctx),
            /BadRequest: sellerName cannot exceed 100 characters/
        );
    });

    it('accepts sellerName of exactly 100 characters', () => {
        const ctx = {
            identity: { sub: 'user-sub-123' },
            args: {
                input: {
                    sellerName: 'A'.repeat(100),
                },
            },
        };

        const result = request(ctx);
        assert.strictEqual(result.attributeValues.sellerName, 'A'.repeat(100));
    });

    it('rejects invalid unitType with allowed enum values in error', () => {
        const ctx = {
            identity: { sub: 'user-sub-123' },
            args: {
                input: {
                    sellerName: 'Valid Name',
                    unitType: 'InvalidType',
                },
            },
        };

        assert.throws(
            () => request(ctx),
            /BadRequest: unitType must be one of: Crew, Pack, Post, Ship, Troop/
        );
    });

    it('accepts all valid unitTypes: Pack, Troop, Crew, Ship, Post', () => {
        const validUnitTypes = ['Pack', 'Troop', 'Crew', 'Ship', 'Post'];

        for (const unitType of validUnitTypes) {
            const ctx = {
                identity: { sub: 'user-sub-123' },
                args: {
                    input: {
                        sellerName: 'Valid Name',
                        unitType: unitType,
                    },
                },
            };

            const result = request(ctx);
            assert.strictEqual(result.attributeValues.unitType, unitType);
        }
    });

    it('rejects invalid unitNumber (non-number string)', () => {
        const ctx = {
            identity: { sub: 'user-sub-123' },
            args: {
                input: {
                    sellerName: 'Valid Name',
                    unitNumber: '42',
                },
            },
        };

        assert.throws(
            () => request(ctx),
            /BadRequest: unitNumber must be a positive integer/
        );
    });

    it('rejects invalid unitNumber (non-integer decimal)', () => {
        const ctx = {
            identity: { sub: 'user-sub-123' },
            args: {
                input: {
                    sellerName: 'Valid Name',
                    unitNumber: 12.5,
                },
            },
        };

        assert.throws(
            () => request(ctx),
            /BadRequest: unitNumber must be a positive integer/
        );
    });

    it('rejects invalid unitNumber (zero)', () => {
        const ctx = {
            identity: { sub: 'user-sub-123' },
            args: {
                input: {
                    sellerName: 'Valid Name',
                    unitNumber: 0,
                },
            },
        };

        assert.throws(
            () => request(ctx),
            /BadRequest: unitNumber must be a positive integer/
        );
    });

    it('rejects invalid unitNumber (negative integer)', () => {
        const ctx = {
            identity: { sub: 'user-sub-123' },
            args: {
                input: {
                    sellerName: 'Valid Name',
                    unitNumber: -5,
                },
            },
        };

        assert.throws(
            () => request(ctx),
            /BadRequest: unitNumber must be a positive integer/
        );
    });

    it('builds PutItem request object construction with generated PROFILE# SK, ACCOUNT# PK, and ISO-8601 timestamps', () => {
        const ctx = {
            identity: { sub: 'sub-user-456' },
            args: {
                input: {
                    sellerName: '  Scout Troop 100  ',
                    unitType: 'Troop',
                    unitNumber: 100,
                },
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'PutItem');
        assert.strictEqual(result.key.ownerAccountId, 'ACCOUNT#sub-user-456');
        assert.strictEqual(result.key.profileId, 'PROFILE#auto-generated-id');
        assert.deepStrictEqual(result.attributeValues, {
            ownerAccountId: 'ACCOUNT#sub-user-456',
            profileId: 'PROFILE#auto-generated-id',
            sellerName: 'Scout Troop 100',
            unitType: 'Troop',
            unitNumber: 100,
            createdAt: '2024-01-01T00:00:00Z',
            updatedAt: '2024-01-01T00:00:00Z',
        });
    });

    it('builds PutItem request object without optional unit fields when omitted or null', () => {
        const ctx = {
            identity: { sub: 'sub-user-789' },
            args: {
                input: {
                    sellerName: 'Individual Seller',
                    unitType: null,
                    unitNumber: null,
                },
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'PutItem');
        assert.strictEqual(result.key.ownerAccountId, 'ACCOUNT#sub-user-789');
        assert.strictEqual(result.key.profileId, 'PROFILE#auto-generated-id');
        assert.strictEqual(result.attributeValues.unitType, undefined);
        assert.strictEqual(result.attributeValues.unitNumber, undefined);
        assert.strictEqual(result.attributeValues.sellerName, 'Individual Seller');
        assert.strictEqual(result.attributeValues.createdAt, '2024-01-01T00:00:00Z');
        assert.strictEqual(result.attributeValues.updatedAt, '2024-01-01T00:00:00Z');
    });
});

describe('create_seller_profile_resolver response', () => {
    it('returns ctx.result on success', () => {
        const ctx = {
            result: {
                profileId: 'PROFILE#auto-generated-id',
                ownerAccountId: 'ACCOUNT#sub-user-456',
                sellerName: 'Scout Troop 100',
                createdAt: '2024-01-01T00:00:00Z',
                updatedAt: '2024-01-01T00:00:00Z',
            },
        };

        const res = response(ctx);
        assert.deepStrictEqual(res, ctx.result);
    });

    it('throws error when ctx.error is present', () => {
        const ctx = {
            error: {
                message: 'DynamoDB put failure',
                type: 'DynamoDB:InternalServerError',
            },
        };

        assert.throws(
            () => response(ctx),
            /DynamoDB:InternalServerError: DynamoDB put failure/
        );
    });
});
