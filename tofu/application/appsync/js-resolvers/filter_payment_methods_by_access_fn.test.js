import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './filter_payment_methods_by_access_fn.js';

describe('filter_payment_methods_by_access_fn request', () => {
    it('returns an empty pass-through operation', () => {
        const result = request({});
        assert.deepStrictEqual(result, {});
    });
});

describe('filter_payment_methods_by_access_fn response', () => {
    it('annotates custom methods with ownerAccountId and profileId for WRITE access', () => {
        const ctx = {
            prev: {
                result: [
                    { name: 'Venmo', qrCodeUrl: 'payment-qr-codes/account-123/venmo.png' },
                ],
            },
            stash: {
                canSeeQR: true,
                ownerAccountId: 'ACCOUNT#account-123',
                profileId: 'profile-abc',
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.length, 3);
        const venmo = result.find(m => m.name === 'Venmo');
        assert.ok(venmo);
        assert.strictEqual(venmo.qrCodeUrl, 'payment-qr-codes/account-123/venmo.png');
        assert.strictEqual(venmo.ownerAccountId, 'ACCOUNT#account-123');
        assert.strictEqual(venmo.profileId, 'profile-abc');
    });

    it('strips QR URLs for READ access but keeps owner metadata', () => {
        const ctx = {
            prev: {
                result: [
                    { name: 'Venmo', qrCodeUrl: 'payment-qr-codes/account-123/venmo.png' },
                ],
            },
            stash: {
                canSeeQR: false,
                ownerAccountId: 'ACCOUNT#account-123',
                profileId: 'profile-abc',
            },
        };

        const result = response(ctx);

        const venmo = result.find(m => m.name === 'Venmo');
        assert.strictEqual(venmo.qrCodeUrl, null);
        assert.strictEqual(venmo.ownerAccountId, 'ACCOUNT#account-123');
        assert.strictEqual(venmo.profileId, 'profile-abc');
    });

    it('sorts methods alphabetically', () => {
        const ctx = {
            prev: {
                result: [
                    { name: 'Zelle', qrCodeUrl: null },
                    { name: 'Venmo', qrCodeUrl: null },
                ],
            },
            stash: {
                canSeeQR: true,
                ownerAccountId: 'ACCOUNT#account-123',
                profileId: 'profile-abc',
            },
        };

        const result = response(ctx);

        const names = result.map(m => m.name);
        assert.deepStrictEqual(names, ['Cash', 'Check', 'Venmo', 'Zelle']);
    });
});
