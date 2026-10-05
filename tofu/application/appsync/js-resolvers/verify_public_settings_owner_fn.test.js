import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_public_settings_owner_fn.js';

// #679 settings slice, decision D8: public-order settings are owner-only on
// both read and write. A WRITE-share collaborator runs the order operations but
// must not be able to publish QR codes, read the share token, or rotate it.

const OWNER_PROFILE = {
    ownerAccountId: 'ACCOUNT#owner-1',
    profileId: 'PROFILE#p1',
    sellerName: 'Troop 158',
    publicOrders: {
        enabled: true,
        token: 'token-abc123',
        campaignId: 'CAMPAIGN#c1',
        allowedPaymentMethods: ['Venmo']
    }
};

describe('verify_public_settings_owner_fn request', () => {
    it('passes the owner through with no datastore call', () => {
        const ctx = {
            stash: { isOwner: true, profile: OWNER_PROFILE, profileId: 'PROFILE#p1' },
            args: { profileId: 'PROFILE#p1' },
            identity: { sub: 'user-1' }
        };

        const result = request(ctx);

        assert.deepStrictEqual(result, { authorized: true });
    });

    it('refuses a WRITE-share collaborator with FORBIDDEN', () => {
        const ctx = {
            stash: {
                isOwner: false,
                hasWritePermission: true,
                profile: OWNER_PROFILE,
                profileId: 'PROFILE#p1'
            },
            args: { profileId: 'PROFILE#p1' },
            identity: { sub: 'collaborator-1' }
        };

        assert.throws(
            () => request(ctx),
            /FORBIDDEN: Only the profile owner can manage public order settings/
        );
    });

    it('refuses a READ-share collaborator with FORBIDDEN', () => {
        const ctx = {
            stash: {
                isOwner: false,
                hasWritePermission: false,
                profile: OWNER_PROFILE,
                profileId: 'PROFILE#p1'
            },
            args: { profileId: 'PROFILE#p1' },
            identity: { sub: 'collaborator-2' }
        };

        assert.throws(
            () => request(ctx),
            /FORBIDDEN: Only the profile owner can manage public order settings/
        );
    });

    it('refuses a stranger the pair left with an empty stash', () => {
        // The pair's Query silent-deny branch (#547) sets skipGetItem and
        // returns null: no profile is stashed at all.
        const ctx = {
            stash: { isOwner: false, hasWritePermission: false, skipGetItem: true },
            args: { profileId: 'PROFILE#nobody' },
            identity: { sub: 'stranger-1' }
        };

        assert.throws(
            () => request(ctx),
            /FORBIDDEN: Only the profile owner can manage public order settings/
        );
    });

    it('answers a stranger and a nonexistent profile identically', () => {
        // No profile-existence oracle: the pair's silent-deny branch means the
        // gate cannot tell the two apart, and must not try to.
        const stranger = {
            stash: { isOwner: false, hasWritePermission: false, profile: OWNER_PROFILE }
        };
        const missing = { stash: { isOwner: false, hasWritePermission: false } };

        let strangerMessage = null;
        let missingMessage = null;
        try {
            request(stranger);
        } catch (error) {
            strangerMessage = error.message;
        }
        try {
            request(missing);
        } catch (error) {
            missingMessage = error.message;
        }

        assert.strictEqual(strangerMessage, missingMessage);
    });

    it('never mentions the share token in the refusal', () => {
        // util.error messages are logged, so a message that interpolated the
        // token would leak the capability into the field logs.
        const ctx = {
            stash: { isOwner: false, hasWritePermission: true, profile: OWNER_PROFILE }
        };

        assert.throws(() => request(ctx), (error) => {
            assert.ok(!error.message.includes('token-abc123'));
            return true;
        });
    });

    it('does not read ctx.identity at all', () => {
        // The gate decides off the pair's stash only; a caller with no identity
        // claims is still refused the same way.
        const ctx = { stash: { isOwner: false } };
        assert.throws(() => request(ctx), /FORBIDDEN/);
    });
});

describe('verify_public_settings_owner_fn response', () => {
    it('passes the early-returned authorization through if the runtime calls it', () => {
        const ctx = { prev: { result: { authorized: true } } };
        assert.deepStrictEqual(response(ctx), { authorized: true });
    });

    it('re-raises a datasource error', () => {
        const ctx = { error: { message: 'boom', type: 'DynamoDBException' } };
        assert.throws(() => response(ctx), /DynamoDBException: boom/);
    });
});
