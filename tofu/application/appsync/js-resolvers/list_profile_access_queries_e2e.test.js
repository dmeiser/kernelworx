import { describe, it } from 'node:test';
import assert from 'node:assert';

// End-to-end pipeline harness for the two sibling profile-access queries.
// Executes the REAL pipeline functions in the deployed order
// (tofu/application/modules/appsync/resolvers_queries.tf):
//   listSharesByProfile / listInvitesByProfile
//     -> verify_profile_write_or_owner -> check_write_permission -> query_shares / query_invites
// against an in-memory DynamoDB, so the tests assert what a caller actually
// receives from both queries rather than asserting on any one function in
// isolation. schema.graphql documents both with the SAME contract ("The caller
// must have write access to the profile") and ScoutManagementPage fetches them
// together, so any divergence between them is a bug.
import * as verifyWriteOrOwner from './verify_profile_write_access_or_owner_fn.js';
import * as checkWritePermission from './check_write_permission_fn.js';
import * as queryShares from './query_shares_fn.js';
import * as queryInvites from './query_invites_fn.js';

const INVITE = {
    inviteCode: 'INV-1',
    profileId: 'PROFILE#prof-1',
    permissions: ['WRITE'],
    createdBy: 'ACCOUNT#owner-1',
    createdAt: '2026-01-01T00:00:00.000Z',
    expiresAt: 4102444800
};

const PROFILE = { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'PROFILE#prof-1' };

function share(overrides = {}) {
    return {
        profileId: 'PROFILE#prof-1',
        targetAccountId: 'ACCOUNT#user-123',
        ownerAccountId: 'ACCOUNT#owner-1',
        permissions: ['WRITE'],
        ...overrides,
    };
}

function makeDb({ profiles = [PROFILE], shares = [] } = {}) {
    const keyOf = (key) => JSON.stringify(key);
    return {
        profiles: new Map(profiles.map((p) => [keyOf({ profileId: p.profileId }), p])),
        shares: new Map(
            shares.map((s) => [keyOf({ profileId: s.profileId, targetAccountId: s.targetAccountId }), s])
        ),
        invites: new Map([[keyOf({ inviteCode: INVITE.inviteCode }), INVITE]]),
    };
}

// NOOP / NONEXISTENT are the "unauthorized, match nothing" sentinels the
// resolvers substitute for a real key, so a match against them is always empty.
function matchesNothing(key) {
    return key === 'NOOP' || key === 'NONEXISTENT';
}

// Drives one of the two queries end to end and returns what the client receives.
function runQuery(db, terminalFn, terminalTable, { sub, profileIdArg }) {
    const ctx = { args: { profileId: profileIdArg }, identity: { sub }, stash: {} };

    // 1. verify_profile_write_or_owner: Query the profileId-index GSI.
    const verifyReq = verifyWriteOrOwner.request(ctx);
    const profileKey = verifyReq.query.expressionValues[':profileId'];
    const profile = db.profiles.get(JSON.stringify({ profileId: profileKey }));
    ctx.result = { items: matchesNothing(profileKey) || !profile ? [] : [profile] };
    verifyWriteOrOwner.response(ctx);

    // 2. check_write_permission: strongly consistent GetItem on the shares table.
    const checkReq = checkWritePermission.request(ctx);
    ctx.result = db.shares.get(JSON.stringify(checkReq.key)) ?? null;
    checkWritePermission.response(ctx);

    // 3. The terminal query, then its response mapping.
    const queryReq = terminalFn.request(ctx);
    const queryKey = queryReq.query.expressionValues[':profileId'];
    const rows = [...db[terminalTable].values()];
    ctx.result = { items: matchesNothing(queryKey) ? [] : rows };
    return terminalFn.response(ctx);
}

function runBothQueries(db, caller) {
    return {
        shares: runQuery(db, queryShares, 'shares', caller),
        invites: runQuery(db, queryInvites, 'invites', caller)
    };
}

// The three denials the grant path must not undo, run through BOTH queries.
const DENIAL_CASES = [
    {
        name: 'a stranger who holds no share',
        sub: 'stranger-9',
        shares: []
    },
    {
        name: 'a READ-only share holder',
        sub: 'user-123',
        shares: [share({ permissions: ['READ'] })]
    },
    {
        // Stamped by the previous owner and left behind by a transfer (#432).
        name: 'a stale WRITE share stamped by the previous owner',
        sub: 'user-123',
        shares: [share({ ownerAccountId: 'ACCOUNT#old-owner' })]
    }
];

const PREFIXED = 'PROFILE#prof-1';
const BARE = 'prof-1';

describe('listSharesByProfile / listInvitesByProfile agree on write access', () => {
    it('grants both queries to the profile owner', () => {
        const db = makeDb();
        const { shares, invites } = runBothQueries(db, { sub: 'owner-1', profileIdArg: PREFIXED });

        assert.strictEqual(shares.length, 0);
        assert.deepStrictEqual(invites.map((i) => i.inviteCode), ['INV-1']);
    });

    it('grants both queries to a current WRITE share holder on a bare profileId', () => {
        const db = makeDb({ shares: [share()] });
        const { shares, invites } = runBothQueries(db, { sub: 'user-123', profileIdArg: BARE });

        assert.strictEqual(shares.length, 1);
        assert.strictEqual(shares[0].targetAccountId, 'user-123');
        assert.deepStrictEqual(invites.map((i) => i.inviteCode), ['INV-1']);
    });

    for (const profileIdArg of [PREFIXED, BARE]) {
        const form = profileIdArg === PREFIXED ? 'a prefixed' : 'a bare';

        for (const denial of DENIAL_CASES) {
            it(`denies both queries on ${form} profileId to ${denial.name}`, () => {
                const db = makeDb({ shares: denial.shares });
                const { shares, invites } = runBothQueries(db, { sub: denial.sub, profileIdArg });

                assert.deepStrictEqual(shares, []);
                assert.deepStrictEqual(invites, []);
            });
        }
    }

    // A legacy share row predating the ownerAccountId attribute is the one
    // grant that rests on no ownership proof. It is accepted deliberately - it
    // mirrors src/utils/auth.py::_is_share_valid and
    // check_share_permissions_fn.js - so it is pinned here rather than left to
    // drift: the caller must still present a real WRITE share row keyed to
    // them, and both queries must treat it identically.
    it('treats a legacy WRITE share without ownerAccountId identically in both queries', () => {
        const db = makeDb({ shares: [share({ ownerAccountId: undefined })] });
        const { shares, invites } = runBothQueries(db, { sub: 'user-123', profileIdArg: BARE });

        assert.strictEqual(shares.length, 1);
        assert.deepStrictEqual(invites.map((i) => i.inviteCode), ['INV-1']);
    });
});
