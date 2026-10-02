import { util } from '@aws-appsync/utils';

export function request(ctx) {
  const input = ctx.args && ctx.args.input;

  // #506: distinguish "absent" from "explicitly null" by KEY PRESENCE.
  // Order.paymentMethod is non-nullable, so persisting an explicit null
  // corrupts the order; the client must omit the field to keep the current
  // value. The APPSYNC_JS runtime can surface an omitted nullable input
  // field with a null value, so a value check alone cannot tell the two
  // apart; Object.hasOwn (the documented `in` replacement) can.
  if (input && Object.hasOwn(input, 'paymentMethod') && input.paymentMethod === null) {
    util.error('paymentMethod cannot be null; omit the field to keep the current value', 'INVALID_INPUT');
  }

  const paymentMethod = (input && input.paymentMethod !== undefined)
    ? input.paymentMethod
    : null;

  if (paymentMethod === null) {
    ctx.stash.skipPaymentMethodValidation = true;
    return {
      operation: 'GetItem',
      key: util.dynamodb.toMapValues({ accountId: 'NOOP' })
    };
  }

  if (paymentMethod === '') {
    util.error('Payment method is required', 'INVALID_INPUT');
  }

  const methodLower = paymentMethod.toLowerCase();
  if (methodLower === 'cash' || methodLower === 'check') {
    ctx.stash.skipPaymentMethodValidation = true;
    return {
      operation: 'GetItem',
      key: util.dynamodb.toMapValues({ accountId: 'NOOP' })
    };
  }

  const rawOwner = ctx.stash.profileOwner ||
    (ctx.stash.profile && ctx.stash.profile.ownerAccountId) ||
    ctx.stash.ownerAccountId;

  if (!rawOwner) {
    util.error('Owner account ID not found in pipeline context', 'INVALID_INPUT');
  }

  const accountId = rawOwner.startsWith('ACCOUNT#') ? rawOwner : 'ACCOUNT#' + rawOwner;
  ctx.stash.paymentMethodToValidate = paymentMethod;

  return {
    operation: 'GetItem',
    key: util.dynamodb.toMapValues({ accountId: accountId }),
    consistentRead: true
  };
}

export function response(ctx) {
  if (ctx.stash && ctx.stash.skipPaymentMethodValidation) {
    return ctx.prev ? ctx.prev.result : null;
  }

  if (ctx.error) {
    util.error(ctx.error.message, ctx.error.type);
  }

  if (!ctx.result) {
    util.error('Owner account not found', 'NOT_FOUND');
  }

  const paymentMethods = (ctx.result.preferences && ctx.result.preferences.paymentMethods) || [];
  const target = ctx.stash.paymentMethodToValidate.toLowerCase();
  const found = paymentMethods.some(m => m.name && m.name.toLowerCase() === target);

  if (!found) {
    util.error("Payment method '" + ctx.stash.paymentMethodToValidate + "' does not exist for this account", 'INVALID_INPUT');
  }

  return ctx.prev ? ctx.prev.result : null;
}
