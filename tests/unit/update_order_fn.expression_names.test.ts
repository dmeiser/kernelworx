import { vi, describe, test, expect } from 'vitest';

// Regression test for #543: update_order_fn.js carried a dead `exprNames`
// object that was never populated, emitted as
// `expressionNames: Object.keys(exprNames).length > 0 ? exprNames : undefined`.
// The emitted UpdateItem request therefore always carried an own
// `expressionNames` property whose value was `undefined`, which reads as
// "reserved-word handling is handled here" to anyone adding a
// DynamoDB-reserved-word field to the order update. The field must be absent
// from the emitted request, and a future reserved-word field must not be
// added without populating the matching expression names.
//
// These assertions run the real request() and inspect the request object it
// emits - they are not source-text greps.

vi.mock('@aws-appsync/utils', () => {
  return {
    util: {
      time: { nowISO8601: () => '2025-01-01T00:00:00.000Z' },
      dynamodb: { toMapValues: (v: any) => v },
      error: (msg: string, type?: string) => {
        throw new Error(msg);
      }
    }
  };
});

import * as updateOrderFn from '../../tofu/application/appsync/js-resolvers/update_order_fn.js';

function validCtx(input?: any) {
  return {
    args: { input: input || {} },
    stash: {
      order: {
        campaignId: 'CAMPAIGN#xyz',
        orderId: 'ORDER#123'
      }
    }
  };
}

function updateRequest(input: any) {
  return updateOrderFn.request(validCtx(input) as any) as any;
}

// Every `#name` placeholder in an update expression is a DynamoDB
// reserved-word substitution and MUST have a matching entry in
// `expressionNames`, or DynamoDB rejects the request with a
// ValidationException. Returns the placeholders that are missing a name.
function missingExpressionNames(update: any): string[] {
  const expression: string = update?.expression ?? '';
  const names: Record<string, string> = update?.expressionNames ?? {};
  const placeholders = expression.match(/#[A-Za-z0-9_]+/g) ?? [];
  return placeholders.filter((placeholder) => names[placeholder] === undefined);
}

describe('update_order_fn UpdateItem request expression names', () => {
  test('no dead expressionNames placeholder is emitted on the request', () => {
    const req = updateRequest({ customerName: 'Ada Lovelace', orderDate: '2025-12-31T00:00:00Z' });
    expect(req.operation).toBe('UpdateItem');
    expect('expressionNames' in req.update).toBe(false);
    expect(req.update.expressionNames).toBeUndefined();
  });

  test('the emitted request stays self-consistent for every updatable field', () => {
    // Drive every branch that builds an update expression, so a reserved-word
    // field added later is covered by the same consistency rule.
    const inputs: any[] = [
      { customerName: 'Ada Lovelace' },
      { customerPhone: '5551234567' },
      { customerAddress: { street: '1 Main St', city: 'Austin', state: 'TX', zipCode: '78701' } },
      { paymentMethod: 'CASH' },
      { orderDate: '2025-12-31T00:00:00Z' },
      { notes: 'Leave at door' }
    ];
    for (const input of inputs) {
      const req = updateRequest(input);
      expect(req.operation).toBe('UpdateItem');
      expect(missingExpressionNames(req.update)).toEqual([]);
    }
  });
});
