import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './validate_payment_method_public_fn.js';

// #679 write slice, spec §10.1: the public clone of the payment-method check.
// The oracle fix is the point - not-allowlisted and not-in-preferences must be
// indistinguishable, and the submitted name must never appear in a message.

function ctxWith(stash) {
    return {
        stash: {
            ownerAccountId: 'ACCOUNT#owner-1',
            publicOrder: { paymentMethod: 'Venmo' },
            ...(stash || {})
        },
        prev: { result: { authorized: true } },
        result: null,
        error: null
    };
}

function accountWith(methods) {
    return { accountId: 'ACCOUNT#owner-1', preferences: { paymentMethods: methods } };
}

describe('validate_payment_method_public_fn request', () => {
    it('GetItems the owner account for a stored method', () => {
        const result = request(ctxWith());

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#owner-1' });
        assert.strictEqual(result.consistentRead, true);
    });

    it('normalizes an owner id that lacks the account prefix', () => {
        const ctx = ctxWith({ ownerAccountId: 'owner-1' });
        assert.deepStrictEqual(request(ctx).key, { accountId: 'ACCOUNT#owner-1' });
    });

    it('issues the NOOP dummy GetItem for Cash', () => {
        const ctx = ctxWith({ publicOrder: { paymentMethod: 'Cash' } });
        const result = request(ctx);

        assert.deepStrictEqual(result.key, { accountId: 'NOOP' });
        assert.strictEqual(ctx.stash.skipPaymentMethodValidation, true);
    });

    it('issues the NOOP dummy GetItem for a case-variant of Check', () => {
        const ctx = ctxWith({ publicOrder: { paymentMethod: 'check' } });
        assert.deepStrictEqual(request(ctx).key, { accountId: 'NOOP' });
    });

    it('refuses to emit a malformed key when the stash has no method', () => {
        assert.throws(() => request(ctxWith({ publicOrder: null })), /INVALID_INPUT: Payment method is not available for this seller/);
    });

    it('refuses to emit a malformed key when the owner is unstashed', () => {
        assert.throws(() => request(ctxWith({ ownerAccountId: null })), /INVALID_INPUT: Payment method is not available for this seller/);
    });
});

describe('validate_payment_method_public_fn response', () => {
    it('passes through untouched for a global pseudo-method', () => {
        const ctx = ctxWith({ publicOrder: { paymentMethod: 'Cash' }, skipPaymentMethodValidation: true });
        assert.deepStrictEqual(response(ctx), { authorized: true });
    });

    it('accepts a stored method matched case-insensitively', () => {
        const ctx = ctxWith({ publicOrder: { paymentMethod: 'venmo' } });
        ctx.result = accountWith([{ name: 'Venmo', qrCodeUrl: 'key' }]);
        assert.deepStrictEqual(response(ctx), { authorized: true });
    });

    it('rejects a method absent from the account', () => {
        const ctx = ctxWith();
        ctx.result = accountWith([{ name: 'Zelle' }]);
        assert.throws(() => response(ctx), /INVALID_INPUT: Payment method is not available for this seller/);
    });

    it('rejects a missing account row with the identical message', () => {
        const ctx = ctxWith();
        ctx.result = null;
        assert.throws(() => response(ctx), /INVALID_INPUT: Payment method is not available for this seller/);
    });

    it('emits one indistinguishable message for both negative branches', () => {
        const messages = [];
        const cases = [
            () => {
                const ctx = ctxWith();
                ctx.result = accountWith([{ name: 'Zelle' }]);
                response(ctx);
            },
            () => {
                const ctx = ctxWith();
                ctx.result = null;
                response(ctx);
            },
            () => {
                const ctx = ctxWith();
                ctx.result = accountWith([]);
                response(ctx);
            }
        ];
        for (const run of cases) {
            try {
                run();
                assert.fail('expected INVALID_INPUT');
            } catch (error) {
                messages.push(error.message);
            }
        }
        assert.strictEqual(new Set(messages).size, 1);
    });

    it('never echoes the submitted method name', () => {
        const ctx = ctxWith({ publicOrder: { paymentMethod: 'PayPal' } });
        ctx.result = accountWith([{ name: 'Venmo' }]);
        try {
            response(ctx);
            assert.fail('expected INVALID_INPUT');
        } catch (error) {
            assert.ok(!String(error.message).includes('PayPal'));
        }
    });

    it('surfaces a datastore error unchanged', () => {
        const ctx = ctxWith();
        ctx.error = { type: 'DynamoDB:ThrottlingException', message: 'slow down' };
        assert.throws(() => response(ctx), /ThrottlingException/);
    });
});
