import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './update_shared_campaign_fn.js';

describe('update_shared_campaign_fn request', () => {
    it('builds UpdateItem request with all updated fields', () => {
        const ctx = {
            args: {
                input: {
                    sharedCampaignCode: 'SHARE123',
                    creatorMessage: 'Welcome to our campaign!',
                    description: 'Updated campaign description',
                    isActive: true,
                },
            },
            stash: { sharedCampaign: {} },
        };
        const result = request(ctx);
        assert.strictEqual(result.operation, 'UpdateItem');
        assert.deepStrictEqual(result.key, { sharedCampaignCode: 'SHARE123' });
        assert.strictEqual(
            result.update.expression,
            'SET #creatorMessage = :creatorMessage, #description = :description, #isActive = :isActive'
        );
        assert.deepStrictEqual(result.update.expressionNames, {
            '#creatorMessage': 'creatorMessage',
            '#description': 'description',
            '#isActive': 'isActive',
        });
        assert.deepStrictEqual(result.update.expressionValues, {
            ':creatorMessage': 'Welcome to our campaign!',
            ':description': 'Updated campaign description',
            ':isActive': true,
        });
    });

    it('builds UpdateItem when only creatorMessage is updated', () => {
        const ctx = {
            args: {
                input: {
                    sharedCampaignCode: 'SHARE123',
                    creatorMessage: 'New note',
                },
            },
            stash: {},
        };
        const result = request(ctx);
        assert.strictEqual(result.operation, 'UpdateItem');
        assert.strictEqual(result.update.expression, 'SET #creatorMessage = :creatorMessage');
        assert.deepStrictEqual(result.update.expressionNames, { '#creatorMessage': 'creatorMessage' });
        assert.deepStrictEqual(result.update.expressionValues, { ':creatorMessage': 'New note' });
    });

    it('builds UpdateItem when description is null (allows clearing description)', () => {
        const ctx = {
            args: {
                input: {
                    sharedCampaignCode: 'SHARE123',
                    description: null,
                },
            },
            stash: {},
        };
        const result = request(ctx);
        assert.strictEqual(result.operation, 'UpdateItem');
        assert.strictEqual(result.update.expression, 'SET #description = :description');
        assert.deepStrictEqual(result.update.expressionNames, { '#description': 'description' });
        assert.deepStrictEqual(result.update.expressionValues, { ':description': null });
    });

    it('ignores null creatorMessage and null isActive', () => {
        const ctx = {
            args: {
                input: {
                    sharedCampaignCode: 'SHARE123',
                    creatorMessage: null,
                    isActive: null,
                },
            },
            stash: {},
        };
        const result = request(ctx);
        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { sharedCampaignCode: 'SHARE123' });
    });

    it('falls back to GetItem when no update fields are provided', () => {
        const ctx = {
            args: {
                input: {
                    sharedCampaignCode: 'SHARE456',
                },
            },
            stash: {},
        };
        const result = request(ctx);
        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { sharedCampaignCode: 'SHARE456' });
    });
});

describe('update_shared_campaign_fn response', () => {
    it('propagates DynamoDB errors', () => {
        const ctx = {
            error: { message: 'Item not found', type: 'DynamoDB:ResourceNotFoundException' },
        };
        assert.throws(
            () => response(ctx),
            /DynamoDB:ResourceNotFoundException: Item not found/
        );
    });

    it('strips ACCOUNT# prefix from createdBy in result', () => {
        const ctx = {
            result: {
                sharedCampaignCode: 'SHARE123',
                createdBy: 'ACCOUNT#user-uuid',
                creatorMessage: 'Hi',
            },
        };
        const res = response(ctx);
        assert.strictEqual(res.createdBy, 'user-uuid');
        assert.strictEqual(res.sharedCampaignCode, 'SHARE123');
    });

    it('preserves clean createdBy without prefix in result', () => {
        const ctx = {
            result: {
                sharedCampaignCode: 'SHARE123',
                createdBy: 'clean-user-uuid',
            },
        };
        const res = response(ctx);
        assert.strictEqual(res.createdBy, 'clean-user-uuid');
    });

    it('handles result without createdBy or null result gracefully', () => {
        assert.deepStrictEqual(response({ result: { sharedCampaignCode: 'S1' } }), { sharedCampaignCode: 'S1' });
        assert.strictEqual(response({ result: null }), null);
    });
});
