/**
 * Update payment method name in preferences.
 */
import { buildPaymentMethodWrite, mapPaymentMethodWriteError } from './lib/prefs_optimistic_lock.js';

export function request(ctx) {
    const accountId = ctx.stash.accountId;
    const currentName = ctx.stash.currentName;
    const newName = ctx.stash.newName;
    const methods = ctx.stash.existingMethods || [];
    const readPreferencesExisted = ctx.stash.readPreferencesExisted === true;
    const readPreferences = ctx.stash.readPreferences;

    // If no existing methods, this shouldn't happen (validation should catch it)
    const updated = methods.map(m => {
        if (m.name && m.name.toLowerCase() === currentName.toLowerCase()) {
            return { ...m, name: newName };
        }
        return m;
    });

    return buildPaymentMethodWrite(accountId, readPreferencesExisted, readPreferences, updated);
}

export function response(ctx) {
    mapPaymentMethodWriteError(ctx);
    return { name: ctx.stash.newName, qrCodeUrl: null };
}
