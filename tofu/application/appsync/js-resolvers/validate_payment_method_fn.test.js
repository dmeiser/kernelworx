import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './validate_payment_method_fn.js';

describe('validate_payment_method_fn request', () => {
  it('skips validation when paymentMethod is null', () => {
    const ctx = {
      args: { input: { paymentMethod: null } },
      stash: {}
    };
    const req = request(ctx);
    assert.strictEqual(ctx.stash.skipPaymentMethodValidation, true);
    assert.deepStrictEqual(req, {
      operation: 'GetItem',
      key: { accountId: 'NOOP' }
    });
  });

  it('skips validation when paymentMethod is undefined', () => {
    const ctx = {
      args: { input: {} },
      stash: {}
    };
    const req = request(ctx);
    assert.strictEqual(ctx.stash.skipPaymentMethodValidation, true);
    assert.deepStrictEqual(req, {
      operation: 'GetItem',
      key: { accountId: 'NOOP' }
    });
  });

  it('skips validation when input object is missing', () => {
    const ctx = {
      args: {},
      stash: {}
    };
    const req = request(ctx);
    assert.strictEqual(ctx.stash.skipPaymentMethodValidation, true);
    assert.deepStrictEqual(req, {
      operation: 'GetItem',
      key: { accountId: 'NOOP' }
    });
  });

  it('throws BadRequest when paymentMethod is empty string', () => {
    const ctx = {
      args: { input: { paymentMethod: '' } },
      stash: {}
    };
    assert.throws(
      () => request(ctx),
      /BadRequest: Payment method is required/
    );
  });

  it('skips DynamoDB query when paymentMethod is Cash (case-insensitive)', () => {
    for (const val of ['Cash', 'cash', 'CASH', 'CaSh']) {
      const ctx = {
        args: { input: { paymentMethod: val } },
        stash: {}
      };
      const req = request(ctx);
      assert.strictEqual(ctx.stash.skipPaymentMethodValidation, true);
      assert.deepStrictEqual(req, {
        operation: 'GetItem',
        key: { accountId: 'NOOP' }
      });
    }
  });

  it('skips DynamoDB query when paymentMethod is Check (case-insensitive)', () => {
    for (const val of ['Check', 'check', 'CHECK', 'cHeCk']) {
      const ctx = {
        args: { input: { paymentMethod: val } },
        stash: {}
      };
      const req = request(ctx);
      assert.strictEqual(ctx.stash.skipPaymentMethodValidation, true);
      assert.deepStrictEqual(req, {
        operation: 'GetItem',
        key: { accountId: 'NOOP' }
      });
    }
  });

  it('generates DynamoDB GetItem request with ACCOUNT# prefix for custom payment method using profileOwner', () => {
    const ctx = {
      args: { input: { paymentMethod: 'Venmo' } },
      stash: { profileOwner: 'user-123' }
    };
    const req = request(ctx);
    assert.strictEqual(ctx.stash.paymentMethodToValidate, 'Venmo');
    assert.deepStrictEqual(req, {
      operation: 'GetItem',
      key: { accountId: 'ACCOUNT#user-123' },
      consistentRead: true
    });
  });

  it('preserves existing ACCOUNT# prefix on profileOwner', () => {
    const ctx = {
      args: { input: { paymentMethod: 'Venmo' } },
      stash: { profileOwner: 'ACCOUNT#user-123' }
    };
    const req = request(ctx);
    assert.deepStrictEqual(req, {
      operation: 'GetItem',
      key: { accountId: 'ACCOUNT#user-123' },
      consistentRead: true
    });
  });

  it('extracts owner from profile.ownerAccountId in stash', () => {
    const ctx = {
      args: { input: { paymentMethod: 'Venmo' } },
      stash: { profile: { ownerAccountId: 'user-456' } }
    };
    const req = request(ctx);
    assert.deepStrictEqual(req, {
      operation: 'GetItem',
      key: { accountId: 'ACCOUNT#user-456' },
      consistentRead: true
    });
  });

  it('extracts owner from ownerAccountId directly in stash', () => {
    const ctx = {
      args: { input: { paymentMethod: 'Venmo' } },
      stash: { ownerAccountId: 'user-789' }
    };
    const req = request(ctx);
    assert.deepStrictEqual(req, {
      operation: 'GetItem',
      key: { accountId: 'ACCOUNT#user-789' },
      consistentRead: true
    });
  });

  it('throws BadRequest when owner account ID is missing from stash', () => {
    const ctx = {
      args: { input: { paymentMethod: 'Venmo' } },
      stash: {}
    };
    assert.throws(
      () => request(ctx),
      /BadRequest: Owner account ID not found in pipeline context/
    );
  });
});

describe('validate_payment_method_fn response', () => {
  it('returns prev.result when validation was skipped', () => {
    const ctx = {
      stash: { skipPaymentMethodValidation: true },
      prev: { result: { orderId: 'ord-123', status: 'CONFIRMED' } }
    };
    const res = response(ctx);
    assert.deepStrictEqual(res, { orderId: 'ord-123', status: 'CONFIRMED' });
  });

  it('throws error when ctx.error is present', () => {
    const ctx = {
      error: { message: 'Internal error', type: 'DynamoDB:InternalServerError' }
    };
    assert.throws(
      () => response(ctx),
      /DynamoDB:InternalServerError: Internal error/
    );
  });

  it('throws NotFound when owner account is not found in DynamoDB', () => {
    const ctx = {
      stash: { paymentMethodToValidate: 'Venmo' },
      result: null
    };
    assert.throws(
      () => response(ctx),
      /NotFound: Owner account not found/
    );
  });

  it('returns prev.result when custom payment method exists in preferences (case-insensitive match)', () => {
    const ctx = {
      stash: { paymentMethodToValidate: 'Venmo' },
      result: {
        preferences: {
          paymentMethods: [
            { name: 'paypal' },
            { name: 'VENMO' },
            { name: 'zelle' }
          ]
        }
      },
      prev: { result: { orderId: 'ord-456' } }
    };
    const res = response(ctx);
    assert.deepStrictEqual(res, { orderId: 'ord-456' });
  });

  it('throws BadRequest when custom payment method does not exist in preferences', () => {
    const ctx = {
      stash: { paymentMethodToValidate: 'ApplePay' },
      result: {
        preferences: {
          paymentMethods: [
            { name: 'Venmo' }
          ]
        }
      },
      prev: { result: { orderId: 'ord-456' } }
    };
    assert.throws(
      () => response(ctx),
      /BadRequest: Payment method 'ApplePay' does not exist for this account/
    );
  });

  it('throws BadRequest when preferences has no paymentMethods array', () => {
    const ctx = {
      stash: { paymentMethodToValidate: 'Venmo' },
      result: {
        preferences: {}
      }
    };
    assert.throws(
      () => response(ctx),
      /BadRequest: Payment method 'Venmo' does not exist for this account/
    );
  });

  it('throws BadRequest when account has no preferences object', () => {
    const ctx = {
      stash: { paymentMethodToValidate: 'Venmo' },
      result: {}
    };
    assert.throws(
      () => response(ctx),
      /BadRequest: Payment method 'Venmo' does not exist for this account/
    );
  });
});
