/**
 * Create payment method in DynamoDB.
 *
 * Adds the new payment method to the user's preferences.paymentMethods array.
 */
import { buildPaymentMethodWrite, mapPaymentMethodWriteError } from './lib/prefs_optimistic_lock.js';

export function request(ctx) {
    const accountId = ctx.stash.accountId;
    const methodName = ctx.stash.paymentMethodName;
    const existingMethods = ctx.stash.existingPaymentMethods || [];
    const readPreferencesExisted = ctx.stash.readPreferencesExisted === true;
    const readPreferences = ctx.stash.readPreferences;

    // Create new payment method object and add it to the existing methods
    // array.
    const newMethod = {
        name: methodName,
        qrCodeUrl: null  // No QR code initially
    };
    const updatedMethods = [...existingMethods, newMethod];

    return buildPaymentMethodWrite(accountId, readPreferencesExisted, readPreferences, updatedMethods);
}

export function response(ctx) {
    mapPaymentMethodWriteError(ctx);

    // Return the created payment method
    return {
        name: ctx.stash.paymentMethodName,
        qrCodeUrl: null
    };
}
