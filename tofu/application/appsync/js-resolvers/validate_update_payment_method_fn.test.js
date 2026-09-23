import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './validate_update_payment_method_fn.js';

function makeCtx(currentName, newName, methods) {
    const ctx = {
        identity: { sub: 'user-123' },
        args: { currentName, newName },
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

describe('validate_update_payment_method_fn stash handoff', () => {
    it('stashes the raw read preferences snapshot for the optimistic lock', () => {
        const ctx = makeCtx('Venmo', 'Zelle', [
            { name: 'Venmo', qrCodeUrl: null },
            { name: 'PayPal' },
        ]);

        response(ctx);

        assert.strictEqual(ctx.stash.readPreferencesExisted, true);
        assert.deepStrictEqual(ctx.stash.readPreferences, ctx.result.preferences);
        assert.deepStrictEqual(ctx.stash.existingMethods, [
            { name: 'Venmo', qrCodeUrl: null },
            { name: 'PayPal' },
        ]);
    });

    it('rejects a reserved new name in request', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            args: { currentName: 'PayPal', newName: 'Cash' },
            stash: {},
            result: {},
        };
        // Reserved new name is rejected in request.
        assert.throws(() => request(ctx), /INVALID_INPUT/);
    });
});
