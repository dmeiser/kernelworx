import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_payment_method_for_delete_fn.js';

function makeCtx(name, methods) {
    const ctx = {
        identity: { sub: 'user-123' },
        args: { name },
        stash: {},
        result: {
            preferences: {
                paymentMethods: methods,
            },
        },
    };
    request(ctx);
    return ctx;
}

describe('get_payment_method_for_delete_fn response', () => {
    it('stashes the canonical stored name when argument casing differs', () => {
        const ctx = makeCtx('venmo', [{ name: 'Venmo', qrCodeUrl: 's3://bucket/qr.png' }]);

        response(ctx);

        assert.strictEqual(ctx.stash.paymentMethodName, 'Venmo');
        assert.strictEqual(ctx.stash.hasQR, true);
        assert.deepStrictEqual(ctx.stash.existingMethods, [{ name: 'Venmo', qrCodeUrl: 's3://bucket/qr.png' }]);
    });

    it('stashes the stored name and hasQR=false when the method has no QR code', () => {
        const ctx = makeCtx('Cash App', [{ name: 'Cash App' }]);

        response(ctx);

        assert.strictEqual(ctx.stash.paymentMethodName, 'Cash App');
        assert.strictEqual(ctx.stash.hasQR, false);
    });

    it('errors when no method matches case-insensitively', () => {
        const ctx = makeCtx('venmo', [{ name: 'PayPal' }]);

        assert.throws(() => response(ctx), /NOT_FOUND/);
    });
});
