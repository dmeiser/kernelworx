import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './confirm_qr_upload_fn.js';

describe('confirm_qr_upload_fn request', () => {
    it('invokes the confirm-qr-upload Lambda with arguments and identity', () => {
        const ctx = {
            args: { paymentMethodName: 'Venmo', s3Key: 'payment-qr-codes/account-123/venmo.png' },
            identity: { sub: 'account-123', username: 'user@example.com' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Invoke');
        assert.deepStrictEqual(result.payload, {
            arguments: { paymentMethodName: 'Venmo', s3Key: 'payment-qr-codes/account-123/venmo.png' },
            identity: { sub: 'account-123', username: 'user@example.com' },
        });
    });
});

describe('confirm_qr_upload_fn response', () => {
    it('returns the Lambda result (payment method with raw S3 key)', () => {
        const ctx = {
            result: { name: 'Venmo', qrCodeUrl: 'payment-qr-codes/account-123/venmo.png' },
        };

        assert.deepStrictEqual(response(ctx), { name: 'Venmo', qrCodeUrl: 'payment-qr-codes/account-123/venmo.png' });
    });

    it('surfaces Lambda errors instead of passing them through', () => {
        const ctx = { error: { message: 'S3 object not found', type: 'NotFound' } };

        assert.throws(() => response(ctx), /NotFound: S3 object not found/);
    });

    it('aborts the pipeline when the handler returns a structured error', () => {
        const ctx = {
            result: { __isError: true, errorCode: 'NOT_FOUND', message: 'S3 object not found' },
            error: null,
        };

        assert.throws(
            () => response(ctx),
            (err) => {
                assert.strictEqual(err.message, 'NOT_FOUND: S3 object not found');
                assert.deepStrictEqual(err.errorInfo, { errorCode: 'NOT_FOUND' });
                return true;
            }
        );
    });
});
