import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './batch_qr_urls_fn.js';

describe('batch_qr_urls_fn request', () => {
    it('sends all S3 keys in a single invocation for myPaymentMethods', () => {
        const ctx = {
            prev: {
                result: [
                    { name: 'Cash', qrCodeUrl: null },
                    { name: 'Venmo', qrCodeUrl: 'payment-qr-codes/account-123/venmo.png' },
                    { name: 'Zelle', qrCodeUrl: 'payment-qr-codes/account-123/zelle.png' },
                ],
            },
            stash: { ownerAccountId: 'account-123' },
            identity: { sub: 'account-123' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Invoke');
        assert.deepStrictEqual(result.payload.s3Keys, [
            'payment-qr-codes/account-123/venmo.png',
            'payment-qr-codes/account-123/zelle.png',
        ]);
        assert.strictEqual(result.payload.ownerAccountId, 'account-123');
        assert.strictEqual(result.payload.profileId, null);
        assert.deepStrictEqual(result.payload.identity, { sub: 'account-123' });
    });

    it('strips the ACCOUNT# prefix and passes profileId for paymentMethodsForProfile', () => {
        const ctx = {
            prev: {
                result: [
                    { name: 'Venmo', qrCodeUrl: 'payment-qr-codes/account-123/venmo.png', ownerAccountId: 'ACCOUNT#account-123' },
                ],
            },
            stash: { ownerAccountId: 'ACCOUNT#account-123', profileId: 'profile-abc' },
            identity: { sub: 'account-456' },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.payload.s3Keys, ['payment-qr-codes/account-123/venmo.png']);
        assert.strictEqual(result.payload.ownerAccountId, 'account-123');
        assert.strictEqual(result.payload.profileId, 'profile-abc');
    });

    it('extracts S3 keys from full stored presigned URLs', () => {
        const ctx = {
            prev: {
                result: [
                    { name: 'Venmo', qrCodeUrl: 'https://bucket.s3.amazonaws.com/payment-qr-codes/account-123/venmo.png?X-Amz-Signature=abc' },
                ],
            },
            stash: {},
            identity: { sub: 'account-123' },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.payload.s3Keys, [
            'payment-qr-codes/account-123/venmo.png?X-Amz-Signature=abc',
        ]);
    });

    it('falls back to the caller identity when stash has no ownerAccountId', () => {
        const ctx = {
            prev: {
                result: [{ name: 'Venmo', qrCodeUrl: 'payment-qr-codes/account-123/venmo.png' }],
            },
            stash: {},
            identity: { sub: 'account-123' },
        };

        const result = request(ctx);

        assert.strictEqual(result.payload.ownerAccountId, 'account-123');
    });

    it('skips the Lambda invocation entirely when there are no QR keys', () => {
        const ctx = {
            prev: {
                result: [
                    { name: 'Cash', qrCodeUrl: null },
                    { name: 'Check', qrCodeUrl: null },
                ],
            },
            stash: { ownerAccountId: 'account-123' },
            identity: { sub: 'account-123' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, undefined);
        assert.deepStrictEqual(result, ctx.prev.result);
    });

    it('returns early with an empty array for an empty method list', () => {
        const ctx = {
            prev: { result: [] },
            stash: {},
            identity: { sub: 'account-123' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, undefined);
        assert.deepStrictEqual(result, []);
    });
});

describe('batch_qr_urls_fn response', () => {
    it('maps each method to its presigned URL from the batch result', () => {
        const ctx = {
            prev: {
                result: [
                    { name: 'Cash', qrCodeUrl: null },
                    { name: 'Venmo', qrCodeUrl: 'payment-qr-codes/account-123/venmo.png' },
                    { name: 'Zelle', qrCodeUrl: 'payment-qr-codes/account-123/zelle.png' },
                ],
            },
            result: {
                'payment-qr-codes/account-123/venmo.png': 'https://presigned.example.com/venmo',
                'payment-qr-codes/account-123/zelle.png': 'https://presigned.example.com/zelle',
            },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, [
            { name: 'Cash', qrCodeUrl: null },
            { name: 'Venmo', qrCodeUrl: 'https://presigned.example.com/venmo' },
            { name: 'Zelle', qrCodeUrl: 'https://presigned.example.com/zelle' },
        ]);
    });

    it('returns null for methods missing from the URL map', () => {
        const ctx = {
            prev: {
                result: [{ name: 'Venmo', qrCodeUrl: 'payment-qr-codes/account-123/venmo.png' }],
            },
            result: {},
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, [{ name: 'Venmo', qrCodeUrl: null }]);
    });

    it('passes methods through unchanged when the response handler runs after an early return', () => {
        const methods = [{ name: 'Cash', qrCodeUrl: null }, { name: 'Check', qrCodeUrl: null }];
        const ctx = {
            prev: { result: methods },
            result: methods,
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, methods);
    });

    it('re-signs stored full URLs via their extracted key', () => {
        const stored = 'https://bucket.s3.amazonaws.com/payment-qr-codes/account-123/venmo.png?X-Amz-Signature=abc';
        const ctx = {
            prev: { result: [{ name: 'Venmo', qrCodeUrl: stored }] },
            result: { [stored.substring(stored.indexOf('/', 8) + 1)]: 'https://presigned.example.com/venmo' },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, [{ name: 'Venmo', qrCodeUrl: 'https://presigned.example.com/venmo' }]);
    });
});
