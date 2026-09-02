import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './mark_invite_used_fn.js';

describe('mark_invite_used_fn request', () => {
  it('returns conditional DeleteItem with inviteCode', () => {
    const ctx = {
      stash: {
        invite: {
          inviteCode: 'INVITE#test-code',
          profileId: 'PROFILE#test-profile',
        },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'DeleteItem');
    assert.strictEqual(result.key.inviteCode, 'INVITE#test-code');
    assert.strictEqual(result.condition.expression, 'attribute_exists(inviteCode)');
  });
});

describe('mark_invite_used_fn response', () => {
  it('passes through previous result on success', () => {
    const ctx = {
      prev: {
        result: { some: 'value' },
      },
      error: null,
    };

    const result = response(ctx);
    assert.deepStrictEqual(result, { some: 'value' });
  });

  it('throws ConflictException on ConditionalCheckFailedException', () => {
    const ctx = {
      error: {
        type: 'DynamoDB:ConditionalCheckFailedException',
        message: 'Conditional check failed',
      },
      prev: { result: null },
    };

    assert.throws(
      () => response(ctx),
      /ConflictException: Invite has already been used/
    );
  });

  it('throws generic error on other errors', () => {
    const ctx = {
      error: {
        type: 'DynamoDB:InternalServerError',
        message: 'Internal error',
      },
      prev: { result: null },
    };

    assert.throws(
      () => response(ctx),
      /DynamoDB:InternalServerError: Internal error/
    );
  });
});
