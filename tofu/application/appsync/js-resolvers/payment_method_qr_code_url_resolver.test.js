import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './payment_method_qr_code_url_resolver.js';

describe('payment_method_qr_code_url_resolver request', () => {
    it('passes owner identity and no profileId for myPaymentMethods', () => {
        const ctx = {
            source: { name: 'Venmo', qrCodeUrl: 'payment-qr-codes/account-123/venmo.png' },
            identity: { sub: 'account-123' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Invoke');
        assert.strictEqual(result.payload.qrCodeUrl, 'payment-qr-codes/account-123/venmo.png');
        assert.strictEqual(result.payload.ownerAccountId, 'account-123');
        assert.strictEqual(result.payload.methodName, 'Venmo');
        assert.strictEqual(result.payload.s3Key, 'payment-qr-codes/account-123/venmo.png');
        assert.strictEqual(result.payload.profileId, null);
        assert.deepStrictEqual(result.payload.identity, { sub: 'account-123' });
    });

    it('passes ownerAccountId and profileId from source for shared profile', () => {
        const ctx = {
            source: {
                name: 'Venmo',
                qrCodeUrl: 'payment-qr-codes/account-123/venmo.png',
                ownerAccountId: 'ACCOUNT#account-123',
                profileId: 'profile-abc',
            },
            identity: { sub: 'account-456' },
        };

        const result = request(ctx);

        assert.strictEqual(result.payload.ownerAccountId, 'account-123');
        assert.strictEqual(result.payload.profileId, 'profile-abc');
        assert.strictEqual(result.payload.s3Key, 'payment-qr-codes/account-123/venmo.png');
    });

    it('extracts S3 key from a full presigned URL', () => {
        const ctx = {
            source: {
                name: 'Venmo',
                qrCodeUrl: 'https://bucket.s3.amazonaws.com/payment-qr-codes/account-123/venmo.png?X-Amz-Signature=abc',
                ownerAccountId: 'account-123',
            },
            identity: { sub: 'account-123' },
        };

        const result = request(ctx);

        assert.strictEqual(result.payload.s3Key, 'payment-qr-codes/account-123/venmo.png?X-Amz-Signature=abc');
    });
});

describe('payment_method_qr_code_url_resolver response', () => {
    it('returns the Lambda result', () => {
        const ctx = { result: 'https://presigned-url.example.com/qr.png' };

        const result = response(ctx);

        assert.strictEqual(result, 'https://presigned-url.example.com/qr.png');
    });
});
