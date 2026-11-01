import { vi, describe, test, expect } from 'vitest';

// Regression test for kernelworx issue #511: shares created before ownerAccountId
// was added carry no owner attribute, and DynamoDB evaluates `ownerAccountId = :caller`
// against a missing attribute as false — so a legacy share could never be revoked.
// The delete condition must tolerate the legacy shape while still requiring the
// recorded owner to match the caller when the attribute is present. Profile-level
// ownership authorization lives in verify_profile_owner_for_revoke_fn.js.

vi.mock('@aws-appsync/utils', () => {
  return {
    util: {
      dynamodb: { toMapValues: (v: any) => v },
      error: (msg: string, type?: string) => {
        throw new Error(`${type || 'ERROR'}: ${msg}`);
      }
    }
  };
});

import * as deleteShareFn from '../../../tofu/application/appsync/js-resolvers/delete_share_fn.js';

function makeCtx(callerSub = 'ACCOUNT#owner-1') {
  return {
    args: { input: { profileId: 'PROFILE#p1', targetAccountId: 'ACCOUNT#target-1' } },
    identity: { sub: callerSub }
  } as any;
}

describe('delete_share_fn condition (issue #511)', () => {
  test('legacy share with no ownerAccountId is revocable: condition tolerates the missing attribute', () => {
    const req: any = deleteShareFn.request(makeCtx());
    expect(req.condition.expression).toContain('attribute_not_exists(ownerAccountId)');
    expect(req.condition.expressionValues[':caller']).toBe('ACCOUNT#owner-1');
  });

  test('ordinary share is not weakened: recorded owner must still match the caller', () => {
    const req: any = deleteShareFn.request(makeCtx());
    // The OR branch keeps the strict check for shares that carry ownerAccountId.
    expect(req.condition.expression).toBe(
      'attribute_not_exists(ownerAccountId) OR ownerAccountId = :caller'
    );
    expect(req.condition.expressionValues[':caller']).toBe('ACCOUNT#owner-1');
  });

  test('caller sub without prefix is normalized before the owner comparison', () => {
    const req: any = deleteShareFn.request(makeCtx('owner-1'));
    expect(req.condition.expressionValues[':caller']).toBe('ACCOUNT#owner-1');
  });

  test('delete key keeps normalized prefixes', () => {
    const ctx = makeCtx();
    ctx.args.input.profileId = 'p1';
    ctx.args.input.targetAccountId = 'target-1';
    const req: any = deleteShareFn.request(ctx);
    expect(req.key).toEqual({ profileId: 'PROFILE#p1', targetAccountId: 'ACCOUNT#target-1' });
  });
});

describe('delete_share_fn response', () => {
  test('conditional check failure surfaces as FORBIDDEN, not a session error', () => {
    expect(() =>
      deleteShareFn.response({ error: { type: 'DynamoDB:ConditionalCheckFailedException', message: 'The condition failed' } } as any)
    ).toThrow('FORBIDDEN');
  });

  test('successful delete returns true', () => {
    expect(deleteShareFn.response({} as any)).toBe(true);
  });
});
