import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_invite_item_fn.js';

describe('delete_invite_item_fn request', () => {
    it('deletes by inviteCode and guards with the verified profileId from stash', () => {
        const ctx = {
            stash: { inviteCode: 'INV-789', profileId: 'PROFILE#prof-456' }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'DeleteItem');
        assert.deepStrictEqual(result.key, { inviteCode: 'INV-789' });
        assert.deepStrictEqual(result.condition, {
            expression: 'profileId = :profileId',
            expressionAttributeValues: { ':profileId': 'PROFILE#prof-456' }
        });
    });
});

describe('delete_invite_item_fn response', () => {
    it('returns true on a successful delete', () => {
        const ctx = { stash: {}, result: null };

        const result = response(ctx);

        assert.strictEqual(result, true);
    });

    it('rejects a cross-profile deletion attempt with FORBIDDEN', () => {
        const ctx = {
            stash: {},
            error: {
                message: 'The conditional request failed',
                type: 'DynamoDB:ConditionalCheckFailedException'
            }
        };

        assert.throws(
            () => response(ctx),
            /FORBIDDEN: Invite does not belong to this profile/
        );
    });

    it('propagates other DynamoDB errors', () => {
        const ctx = {
            stash: {},
            error: { message: 'Throttling', type: 'DynamoDB:ProvisionedThroughputExceededException' }
        };

        assert.throws(
            () => response(ctx),
            /DynamoDB:ProvisionedThroughputExceededException: Throttling/
        );
    });
});
