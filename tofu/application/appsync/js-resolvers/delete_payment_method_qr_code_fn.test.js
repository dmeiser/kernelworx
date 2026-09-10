import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_payment_method_qr_code_fn.js';

describe('delete_payment_method_qr_code_fn request', () => {
    it('invokes the Lambda with the payment method name and caller identity', () => {
        const ctx = {
            stash: {
                hasQR: true,
                paymentMethodName: 'Venmo',
                accountId: 'user-123',
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Invoke');
        assert.strictEqual(result.payload.arguments.paymentMethodName, 'Venmo');
        assert.strictEqual(result.payload.identity.sub, 'user-123');
    });

    it('early-returns when the payment method has no QR code', () => {
        const ctx = {
            stash: {
                hasQR: false,
                paymentMethodName: 'Venmo',
                accountId: 'user-123',
            },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result, { qrDeleted: false });
    });
});

describe('delete_payment_method_qr_code_fn response', () => {
    it('continues the pipeline when QR deletion fails', () => {
        const ctx = {
            stash: {
                paymentMethodName: 'Venmo',
            },
            error: {
                message: 'Failed to delete QR code',
                type: 'InternalError',
            },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { qrDeleted: false });
        assert.strictEqual(ctx.stash.qrCleanupError, 'Failed to delete QR code');
        assert.strictEqual(ctx.stash.qrDeleted, undefined);
    });

    it('marks the QR code as deleted on success', () => {
        const ctx = {
            stash: {
                paymentMethodName: 'Venmo',
            },
            error: null,
            result: true,
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { qrDeleted: true });
        assert.strictEqual(ctx.stash.qrDeleted, true);
        assert.strictEqual(ctx.stash.qrCleanupError, undefined);
    });
});
