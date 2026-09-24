import { describe, it } from 'node:test';
import assert from 'node:assert';

// End-to-end pipeline harness for #453. Executes the REAL pipeline functions in
// the same order as the deployed `redeemProfileInvite` pipeline
// (tofu/application/modules/appsync/resolvers_mutations.tf):
//   lookup_invite -> verify_invite_owner_current -> check_existing_share
//   -> create_share -> mark_invite_used
// against an in-memory DynamoDB, so the tests exercise observable state
// changes (rejection, share stamped with which owner, invite deleted or not)
// rather than implementation text.
import * as lookupInvite from './lookup_invite_fn.js';
import * as verifyInviteOwnerCurrent from './verify_invite_owner_current_fn.js';
import * as checkExistingShare from './check_existing_share_fn.js';
import * as createShare from './create_share_fn.js';
import * as markInviteUsed from './mark_invite_used_fn.js';
import * as createInvite from './create_invite_fn.js';

const NOW_EPOCH_SECONDS = 1704067200; // matches the @aws-appsync/utils mock clock
const DAY = 24 * 60 * 60;

// The deployed pipeline: [module, dynamo table] per function, in order.
const REDEEM_PIPELINE = [
    [lookupInvite, 'invites'],
    [verifyInviteOwnerCurrent, 'profiles'],
    [checkExistingShare, 'shares'],
    [createShare, 'shares'],
    [markInviteUsed, 'invites'],
];

function makeDb({ invites = [], profiles = [], shares = [] } = {}) {
    const keyOf = (key) => JSON.stringify(key);
    return {
        invites: new Map(invites.map((i) => [keyOf({ inviteCode: i.inviteCode }), i])),
        profiles: new Map(profiles.map((p) => [keyOf({ ownerAccountId: p.ownerAccountId, profileId: p.profileId }), p])),
        shares: new Map(shares.map((s) => [keyOf({ profileId: s.profileId, targetAccountId: s.targetAccountId }), s])),
    };
}

// Executes one AppSync pipeline function: request -> DynamoDB -> response.
// Returns the function's output (which becomes ctx.prev.result for the next
// function). Throws whatever util.error raises, exactly like AppSync aborting
// the pipeline.
function runFunction(db, tableName, fn, ctx) {
    const req = fn.request(ctx);
    const table = db[tableName];
    const key = JSON.stringify(req.key);
    if (req.operation === 'GetItem') {
        ctx.result = table.get(key) ?? null;
    } else if (req.operation === 'PutItem') {
        ctx.result = req.attributeValues;
        table.set(key, req.attributeValues);
    } else if (req.operation === 'DeleteItem') {
        ctx.result = table.get(key) ?? null;
        table.delete(key);
    } else {
        throw new Error(`unsupported operation ${req.operation}`);
    }
    const out = fn.response(ctx);
    ctx.prev = { result: out };
    return out;
}

function runPipeline(db, ctx, pipeline = REDEEM_PIPELINE) {
    for (const [fn, tableName] of pipeline) {
        runFunction(db, tableName, fn, ctx);
    }
    return ctx.prev.result;
}

function redemptionCtx(inviteCode, redeemerSub = 'user2') {
    return {
        args: { input: { inviteCode } },
        identity: { sub: redeemerSub },
        stash: {},
    };
}

describe('#453 end-to-end: createProfileInvite expiry bound', () => {
    function createInviteCtx(expiresInDays) {
        return {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    permissions: ['READ'],
                    ...(expiresInDays !== undefined ? { expiresInDays } : {}),
                },
            },
            identity: { sub: 'owner1' },
            stash: { profile: { ownerAccountId: 'ACCOUNT#owner1', profileId: 'PROFILE#p1' } },
        };
    }

    it('rejects a years-long expiry (365 days) with the standard validation error', () => {
        assert.throws(
            () => createInvite.request(createInviteCtx(365)),
            /INVALID_INPUT: expiresInDays must be an integer between 1 and 14/
        );
    });

    it('rejects 91 days, non-integer, and non-positive values', () => {
        for (const bad of [91, 0, -5, 1.5, '30']) {
            assert.throws(
                () => createInvite.request(createInviteCtx(bad)),
                /INVALID_INPUT: expiresInDays must be an integer between 1 and 14/,
                `expected expiresInDays=${bad} to be rejected`
            );
        }
    });

    it('accepts the 14-day maximum and stamps expiresAt accordingly', () => {
        const op = createInvite.request(createInviteCtx(14));
        assert.strictEqual(op.attributeValues.expiresAt, NOW_EPOCH_SECONDS + 14 * DAY);
    });

    it('defaults to 14 days when expiresInDays is omitted', () => {
        const op = createInvite.request(createInviteCtx(undefined));
        assert.strictEqual(op.attributeValues.expiresAt, NOW_EPOCH_SECONDS + 14 * DAY);
    });
});

describe('#453 end-to-end: redeemProfileInvite ownership verification', () => {
    const invite = {
        inviteCode: 'ABC123',
        profileId: 'PROFILE#p1',
        ownerAccountId: 'ACCOUNT#old-owner', // stamped at invite creation
        permissions: ['READ'],
        createdBy: 'old-owner',
        createdAt: '2024-01-01T00:00:00Z',
        expiresAt: NOW_EPOCH_SECONDS + 14 * DAY,
        used: false,
    };

    it('rejects redemption when the profile was transferred to a new owner, and creates no share', () => {
        // Transfer moved the profile item into the new owner's partition; a
        // GetItem under the invite's stamped owner key finds nothing.
        const db = makeDb({
            invites: [invite],
            profiles: [{ ownerAccountId: 'ACCOUNT#new-owner', profileId: 'PROFILE#p1' }],
        });

        assert.throws(
            () => runPipeline(db, redemptionCtx('ABC123')),
            /ConflictException: Invite is no longer valid: profile ownership has changed/
        );
        assert.strictEqual(db.shares.size, 0, 'no share may be stamped from a stale invite');
        assert.strictEqual(db.invites.size, 1, 'invite must not be consumed by a failed redemption');
    });

    it('redeems successfully and stamps the current owner when ownership is unchanged', () => {
        const db = makeDb({
            invites: [invite],
            profiles: [{ ownerAccountId: 'ACCOUNT#old-owner', profileId: 'PROFILE#p1' }],
        });

        const result = runPipeline(db, redemptionCtx('ABC123'));

        assert.strictEqual(db.invites.size, 0, 'invite is deleted after successful redemption');
        assert.strictEqual(db.shares.size, 1);
        const share = db.shares.values().next().value;
        assert.strictEqual(share.ownerAccountId, 'ACCOUNT#old-owner');
        assert.strictEqual(share.profileId, 'PROFILE#p1');
        assert.strictEqual(share.targetAccountId, 'ACCOUNT#user2');
        assert.deepStrictEqual(share.permissions, ['READ']);
        assert.strictEqual(result.targetAccountId, 'user2');
    });

    it('pre-fix pipeline (without verify_invite_owner_current) stamped the stale owner — proves the guard is load-bearing', () => {
        // Same transferred-profile scenario, but running the OLD pipeline order
        // (no verify_invite_owner_current). Before #453 this succeeded and
        // stamped the share with the invite's stale ownerAccountId.
        const preFixPipeline = REDEEM_PIPELINE.filter(([fn]) => fn !== verifyInviteOwnerCurrent);
        const db = makeDb({
            invites: [invite],
            profiles: [{ ownerAccountId: 'ACCOUNT#new-owner', profileId: 'PROFILE#p1' }],
        });

        runPipeline(db, redemptionCtx('ABC123'), preFixPipeline);

        const share = db.shares.values().next().value;
        assert.strictEqual(
            share.ownerAccountId,
            'ACCOUNT#old-owner',
            'without the verify step the share is stamped with the stale invite owner'
        );
    });
});
