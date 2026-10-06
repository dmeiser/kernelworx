import { describe, it } from 'node:test';
import assert from 'node:assert';
import { util } from '@aws-appsync/utils';
import { request, response } from './write_public_order_settings_fn.js';
import { ACK_VERSION } from './lib/public_settings.js';

// #679 settings slice: the ProfilesDS write step. The token lifecycle and the
// omitted-vs-explicit-null argument semantics are the load-bearing parts, and
// the first-enable guard is the only concurrency control on the blob.

const STORED_BLOB = {
    enabled: true,
    token: 'token-abc123',
    campaignId: 'CAMPAIGN#c1',
    allowedPaymentMethods: ['Venmo', 'Cash'],
    acknowledgedAt: '2026-01-02T03:04:05Z',
    ackVersion: ACK_VERSION
};

function ctxFor(args, publicOrders) {
    return {
        stash: {
            isOwner: true,
            profileId: 'PROFILE#p1',
            profile: {
                ownerAccountId: 'ACCOUNT#owner-1',
                profileId: 'PROFILE#p1',
                publicOrders
            }
        },
        // A sub that is NOT the owner account: the write key must come from the
        // stashed profile, never from the caller's identity.
        identity: { sub: 'ACCOUNT#someone-else' },
        args
    };
}

function blobOf(result) {
    return result.update.expressionValues[':publicOrders'];
}

const ENABLE_ARGS = {
    profileId: 'PROFILE#p1',
    enabled: true,
    campaignId: 'CAMPAIGN#c1',
    allowedPaymentMethods: ['Venmo'],
    acknowledgementsAccepted: true
};

describe('write_public_order_settings_fn request', () => {
    it('mints a token on first enable and guards the mint', () => {
        const ctx = ctxFor(ENABLE_ARGS, undefined);

        const result = request(ctx);

        assert.strictEqual(result.operation, 'UpdateItem');
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'ACCOUNT#owner-1',
            profileId: 'PROFILE#p1'
        });
        const blob = blobOf(result);
        assert.strictEqual(blob.token, util.autoId());
        assert.strictEqual(blob.enabled, true);
        assert.strictEqual(blob.campaignId, 'CAMPAIGN#c1');
        assert.deepStrictEqual(blob.allowedPaymentMethods, ['Venmo']);
        // `token` is a DynamoDB reserved word: the condition must escape the
        // document path, or DynamoDB rejects the UpdateItem with a
        // ValidationException before the first-enable guard can evaluate.
        assert.strictEqual(
            result.condition.expression,
            'attribute_exists(ownerAccountId) AND attribute_not_exists(publicOrders.#token)'
        );
        assert.deepStrictEqual(result.condition.expressionNames, { '#token': 'token' });
    });

    it('keys the write off the stashed profile, not the caller identity', () => {
        const ctx = ctxFor(ENABLE_ARGS, undefined);
        const result = request(ctx);
        assert.strictEqual(result.key.ownerAccountId, 'ACCOUNT#owner-1');
    });

    it('always conditions on the profile existing', () => {
        const ctx = ctxFor({ profileId: 'PROFILE#p1', enabled: false }, STORED_BLOB);
        const result = request(ctx);
        assert.match(result.condition.expression, /attribute_exists\(ownerAccountId\)/);
        assert.strictEqual(
            result.condition.expression,
            'attribute_exists(ownerAccountId)',
            'a re-save must not carry the first-enable guard'
        );
        assert.strictEqual(
            result.condition.expressionNames,
            undefined,
            'only the minting guard needs a name substitution'
        );
    });

    it('keeps the stored token on a re-save', () => {
        const ctx = ctxFor(ENABLE_ARGS, STORED_BLOB);
        const blob = blobOf(request(ctx));
        assert.strictEqual(blob.token, 'token-abc123');
    });

    it('replaces the token when rotateToken is true', () => {
        const ctx = ctxFor({ ...ENABLE_ARGS, rotateToken: true }, STORED_BLOB);
        const blob = blobOf(request(ctx));

        assert.notStrictEqual(blob.token, 'token-abc123');
        assert.strictEqual(blob.token, util.autoId());
    });

    it('allows rotateToken while disabled', () => {
        const ctx = ctxFor({ profileId: 'PROFILE#p1', enabled: false, rotateToken: true }, STORED_BLOB);

        const blob = blobOf(request(ctx));

        assert.strictEqual(blob.enabled, false);
        assert.notStrictEqual(blob.token, 'token-abc123');
        assert.strictEqual(blob.token, util.autoId());
    });

    it('flips only enabled on a disable and preserves the rest of the blob', () => {
        const ctx = ctxFor({ profileId: 'PROFILE#p1', enabled: false }, STORED_BLOB);

        const blob = blobOf(request(ctx));

        assert.strictEqual(blob.enabled, false);
        assert.strictEqual(blob.token, 'token-abc123');
        assert.strictEqual(blob.campaignId, 'CAMPAIGN#c1');
        assert.deepStrictEqual(blob.allowedPaymentMethods, ['Venmo', 'Cash']);
        assert.strictEqual(blob.acknowledgedAt, '2026-01-02T03:04:05Z');
        assert.strictEqual(blob.ackVersion, ACK_VERSION);
    });

    it('keeps the same token across disable then re-enable (URL stability)', () => {
        const disabled = blobOf(request(ctxFor({ profileId: 'PROFILE#p1', enabled: false }, STORED_BLOB)));
        assert.strictEqual(disabled.enabled, false);
        assert.strictEqual(disabled.token, 'token-abc123');

        // campaignId and allowedPaymentMethods omitted: the stored values stand.
        const reEnabled = blobOf(
            request(ctxFor({ profileId: 'PROFILE#p1', enabled: true }, disabled))
        );

        assert.strictEqual(reEnabled.enabled, true);
        assert.strictEqual(reEnabled.token, 'token-abc123');
        assert.strictEqual(reEnabled.campaignId, 'CAMPAIGN#c1');
        assert.deepStrictEqual(reEnabled.allowedPaymentMethods, ['Venmo', 'Cash']);
    });

    it('persists the acknowledgement timestamp and version when accepted', () => {
        const ctx = ctxFor(ENABLE_ARGS, undefined);

        const blob = blobOf(request(ctx));

        assert.strictEqual(blob.acknowledgedAt, util.time.nowISO8601());
        assert.strictEqual(blob.ackVersion, ACK_VERSION);
    });

    it('requires the acknowledgement when the stored version is behind', () => {
        const behind = { ...STORED_BLOB, ackVersion: ACK_VERSION - 1 };
        const args = { ...ENABLE_ARGS };
        delete args.acknowledgementsAccepted;

        assert.throws(
            () => request(ctxFor(args, behind)),
            /INVALID_INPUT: The public order acknowledgements must be accepted to enable public orders/
        );
    });

    it('requires the acknowledgement when none was ever stored', () => {
        const args = { ...ENABLE_ARGS };
        delete args.acknowledgementsAccepted;

        assert.throws(
            () => request(ctxFor(args, { enabled: false, campaignId: 'CAMPAIGN#c1' })),
            /INVALID_INPUT: The public order acknowledgements must be accepted to enable public orders/
        );
    });

    it('does not require the acknowledgement when the stored version is current', () => {
        const args = { ...ENABLE_ARGS };
        delete args.acknowledgementsAccepted;
        const ctx = ctxFor(args, STORED_BLOB);

        const blob = blobOf(request(ctx));

        assert.strictEqual(blob.enabled, true);
        assert.strictEqual(blob.acknowledgedAt, '2026-01-02T03:04:05Z');
        assert.strictEqual(blob.ackVersion, ACK_VERSION);
    });

    it('keeps stored campaignId and methods when both arguments are omitted', () => {
        const args = { profileId: 'PROFILE#p1', enabled: true };
        const ctx = ctxFor(args, STORED_BLOB);

        const blob = blobOf(request(ctx));

        assert.strictEqual(blob.campaignId, 'CAMPAIGN#c1');
        assert.deepStrictEqual(blob.allowedPaymentMethods, ['Venmo', 'Cash']);
    });

    it('re-saving the same campaign writes nothing to the campaign counter', () => {
        // The counter lives on the campaign item and is only ever written by the
        // public write path; a settings re-save must not reset it.
        const ctx = ctxFor(ENABLE_ARGS, STORED_BLOB);
        const result = request(ctx);

        assert.strictEqual(result.operation, 'UpdateItem');
        assert.strictEqual(result.key.profileId, 'PROFILE#p1');
        assert.ok(!result.update.expression.includes('publicOrderCount'));
        assert.ok(!Object.keys(result.update.expressionValues).includes(':publicOrderCount'));
    });

    it('bumps updatedAt on the profile item', () => {
        const ctx = ctxFor({ profileId: 'PROFILE#p1', enabled: false }, STORED_BLOB);
        const result = request(ctx);

        assert.match(result.update.expression, /updatedAt = :updatedAt/);
        assert.strictEqual(result.update.expressionValues[':updatedAt'], util.time.nowISO8601());
    });

    it('rejects enabling with an empty method list', () => {
        const args = { ...ENABLE_ARGS, allowedPaymentMethods: [] };

        assert.throws(
            () => request(ctxFor(args, undefined)),
            /INVALID_INPUT: At least one payment method must be allowed to enable public orders/
        );
    });

    it('rejects a method list holding a blank name', () => {
        const args = { ...ENABLE_ARGS, allowedPaymentMethods: ['Venmo', '  '] };

        assert.throws(
            () => request(ctxFor(args, undefined)),
            /INVALID_INPUT: allowedPaymentMethods must be a list of non-empty names/
        );
    });

    it('rejects an explicit null allowedPaymentMethods', () => {
        const args = { ...ENABLE_ARGS, allowedPaymentMethods: null };

        assert.throws(
            () => request(ctxFor(args, STORED_BLOB)),
            /INVALID_INPUT: allowedPaymentMethods cannot be null; omit the field to keep the current list/
        );
    });

    it('rejects an explicit null campaignId even when one is stored', () => {
        const args = { ...ENABLE_ARGS, campaignId: null };

        assert.throws(
            () => request(ctxFor(args, STORED_BLOB)),
            /INVALID_INPUT: campaignId cannot be null; omit the field to keep the current campaign/
        );
    });

    it('rejects enabling with no campaignId at all', () => {
        const args = { profileId: 'PROFILE#p1', enabled: true, allowedPaymentMethods: ['Cash'] };

        assert.throws(
            () => request(ctxFor(args, undefined)),
            /INVALID_INPUT: campaignId is required to enable public orders/
        );
    });

    it('never interpolates the share token into a rejection message', () => {
        // Error messages are logged, so a token in one is a capability leak.
        // Exact strings, because a message that grew to echo the offending
        // value would pass a looser assertion.
        const branches = [
            {
                args: { profileId: 'PROFILE#p1', enabled: true, allowedPaymentMethods: [] },
                stored: STORED_BLOB,
                message: 'INVALID_INPUT: At least one payment method must be allowed to enable public orders'
            },
            {
                args: { profileId: 'PROFILE#p1', enabled: true, allowedPaymentMethods: null },
                stored: STORED_BLOB,
                message: 'INVALID_INPUT: allowedPaymentMethods cannot be null; omit the field to keep the current list'
            },
            {
                args: { profileId: 'PROFILE#p1', enabled: true, campaignId: null },
                stored: STORED_BLOB,
                message: 'INVALID_INPUT: campaignId cannot be null; omit the field to keep the current campaign'
            },
            {
                args: { profileId: 'PROFILE#p1', enabled: true },
                stored: { ...STORED_BLOB, campaignId: undefined, ackVersion: 0 },
                message: 'INVALID_INPUT: campaignId is required to enable public orders'
            },
            {
                args: { profileId: 'PROFILE#p1', enabled: true, allowedPaymentMethods: ['x'], campaignId: 'CAMPAIGN#c1' },
                stored: { ...STORED_BLOB, ackVersion: 0 },
                message: 'INVALID_INPUT: The public order acknowledgements must be accepted to enable public orders'
            }
        ];

        for (const branch of branches) {
            assert.throws(
                () => request(ctxFor(branch.args, branch.stored)),
                (error) => {
                    assert.strictEqual(error.message, branch.message);
                    assert.ok(!error.message.includes('token-abc123'), error.message);
                    return true;
                }
            );
        }
    });
});

describe('write_public_order_settings_fn response', () => {
    it('maps a failed first-enable guard to CONFLICT with no overwrite', () => {
        const ctx = {
            error: {
                type: 'DynamoDB:ConditionalCheckFailedException',
                message: 'The conditional request failed'
            },
            result: null
        };

        assert.throws(() => response(ctx), /CONFLICT: Public order settings were already saved; try again/);
    });

    it('maps a ConditionalCheckFailed message the same way', () => {
        const ctx = { error: { type: 'DynamoDBException', message: 'ConditionalCheckFailed' } };

        assert.throws(() => response(ctx), /CONFLICT/);
    });

    it('re-raises any other datasource error unchanged', () => {
        const ctx = { error: { message: 'boom', type: 'DynamoDBException' } };

        assert.throws(() => response(ctx), /DynamoDBException: boom/);
    });

    it('returns the updated item on success', () => {
        const item = { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'PROFILE#p1', publicOrders: STORED_BLOB };
        const ctx = { result: item };

        assert.strictEqual(response(ctx), item);
    });
});
