import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './validate_payment_method_public_fn.js';

describe('validate_payment_method_public request', () => {
    it('refuses a missing or empty mapped payment method without naming it', () => {
        assert.throws(() => request({ stash: {} }), /INVALID_INPUT: Payment method is not available for this seller/);
        assert.throws(() => request({ stash: { publicOrder: { paymentMethod: '' } } }), /INVALID_INPUT: Payment method is not available for this seller/);
    });

    it('issues a NOOP read for the global pseudo-methods (cash/check)', () => {
        for (const method of ['Cash', 'check']) {
            const stash = { publicOrder: { paymentMethod: method } };
            const req = request({ stash });
            assert.strictEqual(stash.skipPaymentMethodValidation, true);
            assert.deepStrictEqual(req, { operation: 'GetItem', key: { accountId: 'NOOP' } });
        }
    });

    it('refuses a custom method when the owner account is missing', () => {
        assert.throws(() => request({ stash: { publicOrder: { paymentMethod: 'Venmo' } } }), /INVALID_INPUT: Payment method is not available for this seller/);
    });

    it('reads the owner account consistently for a custom method', () => {
        const req = request({ stash: { publicOrder: { paymentMethod: 'Venmo' }, ownerAccountId: 'o1' } });
        assert.deepStrictEqual(req, { operation: 'GetItem', key: { accountId: 'ACCOUNT#o1' }, consistentRead: true });
    });

    // Cap-burn guard: a caller-input rejection must abort this step (before
    // step 6's atomic ADD) so a rejected order never consumes the campaign's
    // order cap.
    it('rejects a soft-deleted catalog before any datastore call', () => {
        const stash = {
            catalog: { isDeleted: true, products: [{ productId: 'P1' }] },
            publicOrder: { paymentMethod: 'Cash', lineItems: [{ productId: 'P1', quantity: 1 }] },
        };
        assert.throws(() => request({ stash }), /INVALID_INPUT: Catalog is not available for this campaign/);
    });

    it('rejects an unknown productId before any datastore call, even for a global pseudo-method', () => {
        const stash = {
            catalog: { products: [{ productId: 'P1' }] },
            publicOrder: { paymentMethod: 'Cash', lineItems: [{ productId: 'P2', quantity: 1 }] },
        };
        assert.throws(() => request({ stash }), /INVALID_INPUT: Product P2 not found in catalog/);
    });

    it('passes a catalog-backed valid order through to the normal flow', () => {
        const stash = {
            catalog: { products: [{ productId: 'P1' }] },
            publicOrder: { paymentMethod: 'Cash', lineItems: [{ productId: 'P1', quantity: 2 }] },
        };
        const req = request({ stash });
        assert.strictEqual(stash.skipPaymentMethodValidation, true);
        assert.deepStrictEqual(req, { operation: 'GetItem', key: { accountId: 'NOOP' } });
    });
});

describe('validate_payment_method_public response', () => {
    it('passes prev.result through when validation was skipped', () => {
        const ctx = { stash: { skipPaymentMethodValidation: true }, prev: { result: { ok: 1 } } };
        assert.deepStrictEqual(response(ctx), { ok: 1 });
        assert.strictEqual(response({ stash: { skipPaymentMethodValidation: true } }), null);
    });

    it('propagates a datastore error', () => {
        assert.throws(() => response({ error: { message: 'boom', type: 'DynamoDB:InternalServerError' } }), /DynamoDB:InternalServerError: boom/);
    });

    it('passes prev.result through when the method is on the account (case-insensitive)', () => {
        const ctx = {
            stash: { publicOrder: { paymentMethod: 'Venmo' } },
            result: { preferences: { paymentMethods: [{ name: 'venmo' }] } },
            prev: { result: { ok: 2 } },
        };
        assert.deepStrictEqual(response(ctx), { ok: 2 });
    });

    it('refuses a gone account or an absent method with the enumeration-safe message', () => {
        const base = { stash: { publicOrder: { paymentMethod: 'Venmo' } } };
        assert.throws(() => response({ ...base, result: null }), /INVALID_INPUT: Payment method is not available for this seller/);
        assert.throws(() => response({ ...base, result: { preferences: { paymentMethods: [{ name: 'PayPal' }] } } }), /INVALID_INPUT: Payment method is not available for this seller/);
    });
});
