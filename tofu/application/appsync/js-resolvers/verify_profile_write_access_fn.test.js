import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_profile_write_access_fn.js';
import * as checkWritePermission from './check_write_permission_fn.js';
import * as queryShares from './query_shares_fn.js';
import * as queryInvites from './query_invites_fn.js';

// Shared ctx helpers. Step 1 has stash.isOwner === undefined; step 2 has it
// set to true/false by the step-1 response.
function baseCtx(extra = {}) {
    return {
        identity: { sub: 'user-123' },
        info: { fieldName: 'createOrder' },
        args: { input: { profileId: 'prof-456' } },
        stash: {},
        ...extra
    };
}

describe('verify_profile_write_access_fn request (step 1: owner GetItem)', () => {
    it('issues a strongly consistent base-table GetItem keyed on the caller account + profileId', () => {
        const result = request(baseCtx());

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-456'
        });
        assert.strictEqual(result.consistentRead, true);
    });

    it('preserves an already-prefixed profileId', () => {
        const ctx = baseCtx({ args: { input: { profileId: 'PROFILE#prof-456' } } });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.profileId, 'PROFILE#prof-456');
        assert.strictEqual(result.key.ownerAccountId, 'ACCOUNT#user-123');
    });

    it('normalizes a sub that already carries the ACCOUNT# prefix', () => {
        const ctx = baseCtx({ identity: { sub: 'ACCOUNT#user-123' } });
        const result = request(ctx);

        assert.strictEqual(result.key.ownerAccountId, 'ACCOUNT#user-123');
    });

    it('derives profileId from stash.order when input is absent', () => {
        const ctx = baseCtx({
            args: { input: {} },
            stash: { order: { profileId: 'ord-prof' } }
        });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.profileId, 'PROFILE#ord-prof');
    });

    it('derives profileId from stash.campaign when input and order are absent', () => {
        const ctx = baseCtx({
            args: { input: {} },
            stash: { campaign: { profileId: 'cmp-prof' } }
        });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.profileId, 'PROFILE#cmp-prof');
    });

    it('throws clean INVALID_INPUT error without leaking stash keys when profileId is missing', () => {
        const errorLogs = [];
        const originalConsoleError = console.error;
        console.error = (...args) => {
            errorLogs.push(args.join(' '));
        };

        const ctx = {
            identity: { sub: 'user-123' },
            info: { fieldName: 'updateOrder' },
            args: { input: {} },
            stash: {
                order: {
                    campaignId: 'CAMPAIGN#c1',
                    orderId: 'ORDER#o1',
                },
                campaign: {
                    campaignId: 'CAMPAIGN#c1',
                },
            },
        };

        try {
            assert.throws(
                () => request(ctx),
                (err) => {
                    assert.strictEqual(err.message, 'INVALID_INPUT: Profile ID is required');
                    // Must not leak internal stash keys or pipeline structure to the client-facing error
                    assert.ok(!err.message.includes('orderKeys'), 'must not contain orderKeys');
                    assert.ok(!err.message.includes('hasInput'), 'must not contain hasInput');
                    assert.ok(!err.message.includes('hasOrder'), 'must not contain hasOrder');
                    assert.ok(!err.message.includes('hasCampaign'), 'must not contain hasCampaign');
                    assert.ok(!err.message.includes('debugging:'), 'must not contain debugging');
                    assert.ok(!err.message.includes('{'), 'must not contain json structure');
                    assert.ok(!err.message.includes('stash'), 'must not contain stash reference');
                    return true;
                }
            );

            // Verify diagnostic details were logged server-side only
            assert.strictEqual(errorLogs.length, 1);
            assert.ok(errorLogs[0].includes('Profile ID not found in request or stash'));
            assert.ok(errorLogs[0].includes('hasInput'));
            assert.ok(errorLogs[0].includes('hasOrder'));
            assert.ok(errorLogs[0].includes('orderKeys'));
        } finally {
            console.error = originalConsoleError;
        }
    });

    it('skips auth (no-op GetItem) for idempotent deleteOrder with a null stash.order', () => {
        const ctx = baseCtx({
            info: { fieldName: 'deleteOrder' },
            args: { input: {} },
            stash: { order: null }
        });

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { ownerAccountId: 'NOOP', profileId: 'NOOP' });
        assert.strictEqual(ctx.stash.skipAuth, true);
    });

    it('skips auth for idempotent deleteCampaign with a null stash.campaign', () => {
        const ctx = baseCtx({
            info: { fieldName: 'deleteCampaign' },
            args: { input: {} },
            stash: { campaign: null }
        });

        const result = request(ctx);

        assert.deepStrictEqual(result.key, { ownerAccountId: 'NOOP', profileId: 'NOOP' });
        assert.strictEqual(ctx.stash.skipAuth, true);
    });

    it('does NOT treat a non-null delete item as idempotent', () => {
        const ctx = baseCtx({
            info: { fieldName: 'deleteOrder' },
            args: { input: {} },
            stash: { order: { profileId: 'x' } }
        });

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.profileId, 'PROFILE#x');
        assert.strictEqual(ctx.stash.skipAuth, undefined);
    });
});

describe('verify_profile_write_access_fn request (step 2: branch on isOwner)', () => {
    it('issues a no-op GetItem when the owner was confirmed in step 1', () => {
        const ctx = baseCtx({ stash: { isOwner: true } });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { ownerAccountId: 'NOOP', profileId: 'NOOP' });
    });

    it('issues the profileId-index GSI Query when the caller is a non-owner', () => {
        const ctx = baseCtx({ stash: { isOwner: false } });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'profileId-index');
        assert.deepStrictEqual(result.query, {
            expression: 'profileId = :profileId',
            expressionValues: { ':profileId': 'PROFILE#prof-456' }
        });
    });

    it('honors an already-set skipAuth flag in step 2', () => {
        const ctx = baseCtx({ stash: { skipAuth: true } });
        const result = request(ctx);

        assert.deepStrictEqual(result.key, { ownerAccountId: 'NOOP', profileId: 'NOOP' });
    });
});

describe('verify_profile_write_access_fn response (step 1)', () => {
    it('confirms ownership when the consistent GetItem returns an item under the caller key', () => {
        const profile = {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-456',
            sellerName: 'Scout'
        };
        const ctx = baseCtx({ result: profile });

        const out = response(ctx);

        assert.strictEqual(ctx.stash.isOwner, true);
        assert.deepStrictEqual(ctx.stash.profile, profile);
        assert.strictEqual(ctx.stash.profileOwner, 'ACCOUNT#user-123');
        assert.deepStrictEqual(out, profile);
    });

    it('treats a null result as non-owner and moves to the GSI step', () => {
        const ctx = baseCtx({ result: null });

        const out = response(ctx);

        assert.strictEqual(ctx.stash.isOwner, false);
        assert.strictEqual(out, null);
    });

    it('does NOT require ownerAccountId to match sub: existence under the caller key is authoritative', () => {
        // Simulate the stale-GSI race: an item present under the caller key is
        // authoritative regardless of any attribute value.
        const profile = { ownerAccountId: 'UNRELATED-OWNER', profileId: 'PROFILE#prof-456' };
        const ctx = baseCtx({ result: profile });

        response(ctx);

        assert.strictEqual(ctx.stash.isOwner, true);
        assert.deepStrictEqual(ctx.stash.profile, profile);
    });
});

describe('verify_profile_write_access_fn response (step 2)', () => {
    it('passes the confirmed profile through for the owner path', () => {
        const profile = { ownerAccountId: 'ACCOUNT#user-123', profileId: 'PROFILE#prof-456' };
        const ctx = baseCtx({ stash: { isOwner: true, profile } });

        assert.deepStrictEqual(response(ctx), profile);
    });

    it('stores the profile and flags non-owner from the GSI Query items for the share step', () => {
        const profile = { ownerAccountId: 'ACCOUNT#original-owner', profileId: 'PROFILE#prof-456' };
        const ctx = baseCtx({ stash: { isOwner: false }, result: { items: [profile] } });

        const out = response(ctx);

        assert.strictEqual(ctx.stash.isOwner, false);
        assert.deepStrictEqual(ctx.stash.profile, profile);
        assert.strictEqual(ctx.stash.profileOwner, 'ACCOUNT#original-owner');
        assert.deepStrictEqual(out, profile);
    });

    it('raises NOT_FOUND when the GSI Query returns no items', () => {
        const ctx = baseCtx({ stash: { isOwner: false }, result: { items: [] } });

        assert.throws(
            () => response(ctx),
            /NOT_FOUND: Profile not found/
        );
    });
});

describe('verify_profile_write_access_fn response (cross-cutting)', () => {
    it('returns authorized for the idempotent-delete skip path', () => {
        const ctx = baseCtx({ stash: { skipAuth: true } });
        assert.deepStrictEqual(response(ctx), { authorized: true });
    });

    it('propagates a data-source error', () => {
        const ctx = baseCtx({
            error: { message: 'DynamoDB: boom', type: 'DynamoDBException' },
            stash: { isOwner: undefined }
        });

        assert.throws(
            () => response(ctx),
            /DynamoDBException: DynamoDB: boom/
        );
    });
});

// #547: listSharesByProfile / listInvitesByProfile run this two-phase pair but
// pass profileId as a top-level argument (ctx.args.profileId), not under
// ctx.args.input, and their downstream check_write_permission step reads the
// normalized id off ctx.stash.profileId.
describe('verify_profile_write_access_fn for the share/invite query resolvers (#547)', () => {
    function queryCtx(extra = {}) {
        return {
            identity: { sub: 'user-123' },
            info: { fieldName: 'listSharesByProfile', parentTypeName: 'Query' },
            args: { profileId: 'prof-456' },
            stash: {},
            ...extra
        };
    }

    it('step 1 decides ownership with the strongly consistent GetItem off the top-level profileId', () => {
        const result = request(queryCtx());

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-456'
        });
    });

    it('step 1 stashes the normalized profileId for the downstream check_write_permission step', () => {
        const ctx = queryCtx();
        request(ctx);

        assert.strictEqual(ctx.stash.profileId, 'PROFILE#prof-456');
    });

    it('step 1 preserves an already-prefixed top-level profileId', () => {
        const result = request(queryCtx({ args: { profileId: 'PROFILE#prof-456' } }));

        assert.strictEqual(result.key.profileId, 'PROFILE#prof-456');
    });

    it('step 2 locates the profile via the GSI for a non-owner, using the top-level profileId', () => {
        const ctx = queryCtx({ stash: { isOwner: false } });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'profileId-index');
        assert.deepStrictEqual(result.query, {
            expression: 'profileId = :profileId',
            expressionValues: { ':profileId': 'PROFILE#prof-456' }
        });
    });

    it('step 1 turns a consistent GetItem miss into a non-owner verdict', () => {
        const ctx = queryCtx();
        request(ctx); // step 1
        const out = response({ ...ctx, result: null }); // consistent GetItem found nothing
        assert.strictEqual(ctx.stash.isOwner, false);
        assert.strictEqual(out, null);
    });

    // Drives the whole read pipeline: verifier step 1 (consistent ownership GetItem) ->
    // verifier step 2 (GSI locator) -> check_write_permission -> the list step.
    function runQueryPipeline(verifierCtx, finalField, step2Result, finalResult) {
        const final = finalField === 'listInvitesByProfile' ? queryInvites : queryShares;
        const stash = verifierCtx.stash;

        request(verifierCtx);
        response({ ...verifierCtx, result: null });
        request(verifierCtx);
        response({ ...verifierCtx, result: step2Result });
        checkWritePermission.request({ ...verifierCtx, stash });
        checkWritePermission.response({ ...verifierCtx, stash, result: null });
        final.request({ ...verifierCtx, stash });
        return final.response({ ...verifierCtx, stash, result: finalResult });
    }

    // A profile that does not exist (or is not yet projected on the GSI) must keep
    // answering with an empty list, as these queries did before #547, instead of a
    // NOT_FOUND GraphQL error on two non-nullable list fields.
    for (const fieldName of ['listSharesByProfile', 'listInvitesByProfile']) {
        it(`${fieldName} answers with an empty list when the profile does not exist`, () => {
            const ctx = queryCtx({ info: { fieldName, parentTypeName: 'Query' } });

            assert.deepStrictEqual(runQueryPipeline(ctx, fieldName, { items: [] }, { items: [] }), []);
        });
    }

    // S1: a blank or otherwise unresolvable profileId must take the same silent-deny
    // branch as the not-found case, not surface INVALID_INPUT, so neither query turns
    // a malformed id into a GraphQL error or a profile-existence oracle. The retired
    // verifier returned `{ authorized: false }` for this input and both queries must
    // keep that contract.
    for (const fieldName of ['listSharesByProfile', 'listInvitesByProfile']) {
        it(`${fieldName} answers with an empty list when the profileId is blank`, () => {
            const ctx = queryCtx({
                info: { fieldName, parentTypeName: 'Query' },
                args: { profileId: '' }
            });

            // Step 1 must not issue a live read for an id it cannot resolve.
            const step1 = request(ctx);
            assert.strictEqual(step1.operation, 'GetItem');
            assert.deepStrictEqual(step1.key, { ownerAccountId: 'NOOP', profileId: 'NOOP' });

            assert.deepStrictEqual(runQueryPipeline(ctx, fieldName, { items: [] }, { items: [] }), []);
            assert.strictEqual(ctx.stash.isOwner, false);
            assert.strictEqual(ctx.stash.hasWritePermission, false);
            assert.strictEqual(ctx.stash.skipGetItem, true);
        });
    }

    // S1: the INVALID_INPUT raise stays on the mutation path, where a missing id is a
    // genuine client error rather than a silent empty list.
    it('still raises INVALID_INPUT for a missing profileId on a mutation', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            info: { fieldName: 'createOrder', parentTypeName: 'Mutation' },
            args: { input: {} },
            stash: {}
        };

        assert.throws(() => request(ctx), /INVALID_INPUT: Profile ID is required/);
    });

    // The reported #547 sequence: transferProfileOwnership moves the profile item into
    // the new owner's partition, so the caller's strongly consistent base-table GetItem
    // misses, while the eventually-consistent profileId-index GSI can still project the
    // caller as owner. The pre-#547 verifier decided ownership from that GSI item's
    // ownerAccountId, which let a former owner read the new owner's owner-only invite
    // codes. Ownership comes from the step 1 read alone, so the GSI row must not flip it.
    it('a stale GSI row still naming the caller as owner does not restore ownership', () => {
        const ctx = queryCtx({ info: { fieldName: 'listInvitesByProfile', parentTypeName: 'Query' } });
        const unexpiredInvite = {
            inviteCode: 'abc123',
            profileId: 'PROFILE#prof-456',
            permissions: ['WRITE'],
            expiresAt: 1704067200 + 3600,
            createdBy: 'ACCOUNT#new-owner'
        };

        const invites = runQueryPipeline(
            ctx,
            'listInvitesByProfile',
            { items: [{ profileId: 'PROFILE#prof-456', ownerAccountId: 'ACCOUNT#user-123' }] },
            { items: [unexpiredInvite] }
        );

        assert.strictEqual(ctx.stash.isOwner, false, 'the GSI item must not make the caller the owner');
        assert.strictEqual(ctx.stash.profileOwner, 'ACCOUNT#user-123');
        assert.deepStrictEqual(invites, [], 'a former owner must not read the new owner invites');
    });

    // The write-permission half of the contract, driven end to end on an
    // UNPREFIXED profileId (the #534/#636 case): normalization is owned by
    // lib/ids.js inside verify_profile_write_access, so the share lookup must
    // see the same PROFILE# form the owner check used. Each case states who is
    // denied and who is allowed.
    function runWritePipeline(step2Items, shareResult) {
        const ctx = queryCtx({ info: { fieldName: 'listSharesByProfile', parentTypeName: 'Query' } });
        const stash = ctx.stash;

        request(ctx); // step 1: consistent owner GetItem (miss for a non-owner)
        response({ ...ctx, result: null });
        request(ctx); // step 2: GSI locator
        response({ ...ctx, result: { items: step2Items } });
        checkWritePermission.request({ ...ctx, stash });
        checkWritePermission.response({ ...ctx, stash, result: shareResult });
        // The final list step keys off the verdict: a denial issues the
        // NONEXISTENT query, so the datastore answers with an empty page.
        queryShares.request({ ...ctx, stash });
        const finalItems = stash.hasWritePermission && shareResult ? [shareResult] : [];
        const shares = queryShares.response({ ...ctx, stash, result: { items: finalItems } });
        return { ctx, shares };
    }

    it('grants a non-owner holding a WRITE share through the whole pipeline on an unprefixed profileId', () => {
        const share = {
            profileId: 'PROFILE#prof-456',
            targetAccountId: 'ACCOUNT#user-123',
            permissions: ['WRITE'],
            ownerAccountId: 'ACCOUNT#original-owner'
        };

        const { ctx, shares } = runWritePipeline(
            [{ profileId: 'PROFILE#prof-456', ownerAccountId: 'ACCOUNT#original-owner' }],
            share
        );

        assert.strictEqual(ctx.stash.hasWritePermission, true);
        assert.deepStrictEqual(shares, [{ ...share, targetAccountId: 'user-123' }]);
    });

    it('denies a caller with no share at all on an unprefixed profileId', () => {
        const { ctx, shares } = runWritePipeline(
            [{ profileId: 'PROFILE#prof-456', ownerAccountId: 'ACCOUNT#original-owner' }],
            null
        );

        assert.strictEqual(ctx.stash.hasWritePermission, false);
        assert.deepStrictEqual(shares, []);
    });

    it('denies a READ-only share holder on an unprefixed profileId', () => {
        const { ctx, shares } = runWritePipeline(
            [{ profileId: 'PROFILE#prof-456', ownerAccountId: 'ACCOUNT#original-owner' }],
            {
                profileId: 'PROFILE#prof-456',
                targetAccountId: 'ACCOUNT#user-123',
                permissions: ['READ'],
                ownerAccountId: 'ACCOUNT#original-owner'
            }
        );

        assert.strictEqual(ctx.stash.hasWritePermission, false);
        assert.deepStrictEqual(shares, []);
    });

    it('denies a WRITE share stamped by a previous owner after an ownership transfer (#432)', () => {
        // The share still says the former owner granted it; the GSI-located
        // profile names the new owner, so the share is stale and must not grant.
        const { ctx, shares } = runWritePipeline(
            [{ profileId: 'PROFILE#prof-456', ownerAccountId: 'ACCOUNT#new-owner' }],
            {
                profileId: 'PROFILE#prof-456',
                targetAccountId: 'ACCOUNT#user-123',
                permissions: ['WRITE'],
                ownerAccountId: 'ACCOUNT#former-owner'
            }
        );

        assert.strictEqual(ctx.stash.hasWritePermission, false);
        assert.deepStrictEqual(shares, []);
    });

    it('keeps NOT_FOUND on the write path, where the profile must exist to mutate it', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            info: { fieldName: 'updateOrder', parentTypeName: 'Mutation' },
            args: { input: { profileId: 'prof-456' } },
            stash: { isOwner: false },
            result: { items: [] }
        };

        assert.throws(() => response(ctx), /NOT_FOUND: Profile not found/);
    });
});
