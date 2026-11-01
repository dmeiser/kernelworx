import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './inject_global_payment_methods_fn.js';

describe('inject_global_payment_methods_fn request', () => {
    it('returns an empty pass-through operation', () => {
        const result = request({});
        assert.deepStrictEqual(result, {});
    });
});

describe('inject_global_payment_methods_fn response', () => {
    it('injects global methods and sorts custom methods alphabetically', () => {
        const ctx = {
            prev: {
                result: [
                    { name: 'Zelle', qrCodeUrl: null },
                    { name: 'Venmo', qrCodeUrl: 'payment-qr-codes/account-123/venmo.png' },
                ],
            },
            stash: {},
        };

        const result = response(ctx);

        const names = result.map(m => m.name);
        assert.deepStrictEqual(names, ['Cash', 'Check', 'Venmo', 'Zelle']);
        const venmo = result.find(m => m.name === 'Venmo');
        assert.ok(venmo);
        assert.strictEqual(venmo.qrCodeUrl, 'payment-qr-codes/account-123/venmo.png');
    });

    it('does not duplicate entries when sort keys collide (#540)', () => {
        const ctx = {
            prev: {
                result: [
                    { name: 'Venmo', qrCodeUrl: 'url1' },
                    { name: 'venmo', qrCodeUrl: 'url2' },
                ],
            },
            stash: {},
        };

        const result = response(ctx);

        const names = result.map(m => m.name);
        const uniqueNames = new Set(names);
        assert.strictEqual(names.length, uniqueNames.size);
    });
});
