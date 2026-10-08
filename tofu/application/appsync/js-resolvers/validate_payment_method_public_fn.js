import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';
import { GLOBAL_PAYMENT_METHODS, PUBLIC_METHOD_UNAVAILABLE } from './lib/public_order.js';

// Step 5 of the publicCreateOrder pipeline (#679 write slice, spec §5.3): a
// CLONE of validate_payment_method_fn.js, not a reuse.
//
// The authenticated original cannot be reused unchanged because its
// not-in-preferences rejection embeds the submitted method name ("Payment
// method 'X' does not exist for this account"), and a pipeline cannot catch and
// rewrite a reused function's util.error. Iterating publicCreateOrder would then
// enumerate the owner's real stored method names - including stale names the
// offer deliberately filters out of the buyer's view. Both rejections here are
// the identical message, and the submitted name never appears in one.
//
// Allowlist membership was already decided in step 2; this step answers only
// "does this method still exist on the owner's account". Cash and Check are
// global pseudo-methods that never live in preferences, so they take the same
// NOOP dummy GetItem the original issues (one billed AccountsDS call per
// Cash/Check order - the datasource budget the spec states).
export function request(ctx) {
    const mapped = ctx.stash ? ctx.stash.publicOrder : null;
    const paymentMethod = mapped ? mapped.paymentMethod : null;

    if (typeof paymentMethod !== 'string' || paymentMethod === '') {
        // Step 2 already required a non-empty method; a miss here is wiring.
        util.error(PUBLIC_METHOD_UNAVAILABLE, 'INVALID_INPUT');
        return null;
    }

    if (GLOBAL_PAYMENT_METHODS.includes(paymentMethod.toLowerCase())) {
        ctx.stash.skipPaymentMethodValidation = true;
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ accountId: 'NOOP' })
        };
    }

    const ownerAccountId = ctx.stash ? ctx.stash.ownerAccountId : null;
    if (!ownerAccountId) {
        util.error(PUBLIC_METHOD_UNAVAILABLE, 'INVALID_INPUT');
        return null;
    }

    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ accountId: normalizeIdOrPrefix(ownerAccountId, 'ACCOUNT#') }),
        consistentRead: true
    };
}

export function response(ctx) {
    if (ctx.stash && ctx.stash.skipPaymentMethodValidation) {
        return ctx.prev ? ctx.prev.result : null;
    }

    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
        return null;
    }

    const account = ctx.result;
    const preferences = account && account.preferences ? account.preferences : null;
    const stored = preferences && Array.isArray(preferences.paymentMethods) ? preferences.paymentMethods : [];
    const mapped = ctx.stash.publicOrder;
    const target = mapped.paymentMethod.toLowerCase();

    let found = false;
    for (const method of stored) {
        if (method && typeof method.name === 'string' && method.name.toLowerCase() === target) {
            found = true;
        }
    }

    // One message for "the account row is gone" and "the method is not on the
    // account": neither may name the method.
    if (!found) {
        util.error(PUBLIC_METHOD_UNAVAILABLE, 'INVALID_INPUT');
        return null;
    }

    return ctx.prev ? ctx.prev.result : null;
}
