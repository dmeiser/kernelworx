import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './share_target_account_resolver.js';

describe('share_target_account_resolver request', () => {
    it('normalizes an unprefixed targetAccountId to ACCOUNT# form', () => {
        const ctx = { source: { targetAccountId: 'u1' } };
        const req = request(ctx);
        assert.strictEqual(req.operation, 'GetItem');
        assert.deepStrictEqual(req.key, { accountId: 'ACCOUNT#u1' });
    });

    it('keeps an already-prefixed targetAccountId unchanged', () => {
        const ctx = { source: { targetAccountId: 'ACCOUNT#u2' } };
        const req = request(ctx);
        assert.deepStrictEqual(req.key, { accountId: 'ACCOUNT#u2' });
    });
});

describe('share_target_account_resolver response (#455)', () => {
    const fullAccountItem = {
        accountId: 'ACCOUNT#u1',
        email: 'target@example.com',
        givenName: 'Target',
        familyName: 'User',
        city: 'Springfield',
        state: 'IL',
        unitType: 'Troop',
        unitNumber: 123,
        preferences: JSON.stringify({ theme: 'dark', privateNotes: 'secret' }),
        createdAt: '2024-01-01T00:00:00Z',
        updatedAt: '2024-06-01T00:00:00Z',
    };

    it('strips the private preferences blob from the collaborator-visible account', () => {
        const result = response({ result: fullAccountItem });
        assert.ok(result);
        assert.strictEqual(result.accountId, 'ACCOUNT#u1');
        assert.strictEqual(result.email, 'target@example.com');
        assert.strictEqual(result.givenName, 'Target');
        assert.strictEqual(result.familyName, 'User');
        assert.ok(!('preferences' in result), 'preferences must not leak');
    });

    it('exposes only whitelisted display fields', () => {
        const result = response({ result: fullAccountItem });
        assert.deepStrictEqual(Object.keys(result).sort(), [
            'accountId',
            'city',
            'createdAt',
            'email',
            'familyName',
            'givenName',
            'state',
            'unitNumber',
            'unitType',
            'updatedAt',
        ]);
    });

    it('omits absent optional fields instead of emitting undefined', () => {
        const result = response({
            result: {
                accountId: 'ACCOUNT#u3',
                email: 'bare@example.com',
                createdAt: '2024-01-01T00:00:00Z',
                updatedAt: '2024-01-01T00:00:00Z',
            },
        });
        assert.deepStrictEqual(result, {
            accountId: 'ACCOUNT#u3',
            email: 'bare@example.com',
            createdAt: '2024-01-01T00:00:00Z',
            updatedAt: '2024-01-01T00:00:00Z',
        });
    });

    it('returns null on resolver error', () => {
        assert.strictEqual(response({ error: { message: 'boom' } }), null);
    });

    it('returns null when the account item is missing', () => {
        assert.strictEqual(response({ result: null }), null);
    });
});
