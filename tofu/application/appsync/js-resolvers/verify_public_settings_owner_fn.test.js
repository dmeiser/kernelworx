import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_public_settings_owner_fn.js';

// KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1: the owner-only gate both campaign-level
// settings pipelines run after the two-phase write-access pair. Ownership is
// already decided by the pair's consistent base-table read, so this step makes
// no datastore call of its own.

describe('verify_public_settings_owner_fn request', () => {
    it('authorizes the profile owner without a datastore read', () => {
        assert.deepStrictEqual(request({ stash: { isOwner: true } }), { authorized: true });
    });

    it('refuses a WRITE-share collaborator with FORBIDDEN', () => {
        assert.throws(
            () => request({ stash: { isOwner: false, hasWritePermission: true } }),
            /FORBIDDEN: Only the profile owner can manage public order settings/
        );
    });

    it('refuses a stranger and an unresolvable profile identically, so the query is not an existence oracle', () => {
        assert.throws(() => request({ stash: {} }), /FORBIDDEN: Only the profile owner/);
        assert.throws(() => request({}), /FORBIDDEN: Only the profile owner/);
    });

    it('makes no datastore call of its own, on either branch', () => {
        // Ownership is already decided by the pair's strongly consistent
        // base-table read. A gate that re-derived it from a projection is the
        // #545 bug, so both branches must stay read-free.
        const hostile = new Proxy({}, {
            get: (target, prop) => {
                if (prop === 'error' || prop === 'unauthorized' || prop === 'quiet') {
                    return (message) => {
                        throw new Error(message);
                    };
                }
                throw new Error(`verify_public_settings_owner must not use util.${String(prop)}`);
            }
        });

        assert.deepStrictEqual(request({ stash: { isOwner: true }, util: hostile }), { authorized: true });
        assert.throws(() => request({ stash: { isOwner: false }, util: hostile }), /FORBIDDEN/);
    });
});

describe('verify_public_settings_owner_fn response', () => {
    it('passes the previous result through', () => {
        assert.deepStrictEqual(response({ prev: { result: { authorized: true } } }), {
            authorized: true
        });
    });

    it('propagates a pipeline error unchanged', () => {
        const ctx = { error: { message: 'Campaign not found', type: 'NOT_FOUND' } };

        assert.throws(() => response(ctx), /NOT_FOUND: Campaign not found/);
    });
});
