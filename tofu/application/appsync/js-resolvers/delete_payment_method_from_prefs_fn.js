/**
 * Remove payment method from preferences array.
 */
import { buildPaymentMethodWrite, mapPaymentMethodWriteError } from './lib/prefs_optimistic_lock.js';

export function request(ctx) {
    const accountId = ctx.stash.accountId;
    const nameLower = ctx.stash.nameLower;
    const methods = ctx.stash.existingMethods || [];
    const readPreferencesExisted = ctx.stash.readPreferencesExisted === true;
    const readPreferences = ctx.stash.readPreferences;

    const updated = methods.filter(m => !m.name || m.name.toLowerCase() !== nameLower);

    return buildPaymentMethodWrite(accountId, readPreferencesExisted, readPreferences, updated);
}

export function response(ctx) {
    mapPaymentMethodWriteError(ctx);
    return true;
}
