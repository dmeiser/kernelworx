import { vi, describe, test, expect, beforeEach } from 'vitest';

// #449: validatePermissions in create_invite_fn.js / create_share_fn.js must
// reject the input when ANY element of the permissions array is not a valid
// permission string (READ/WRITE, case-insensitive), not merely require one
// valid element to be present. Garbage values would otherwise be persisted to
// DynamoDB and returned via GraphQL.
const errors: Array<{ msg: string; type?: string }> = vi.hoisted(() => []);

vi.mock('@aws-appsync/utils', () => {
  return {
    util: {
      autoId: () => 'TESTID1234',
      time: {
        nowEpochSeconds: () => 1700000000,
        nowISO8601: () => '2025-01-01T00:00:00.000Z',
        epochMilliSecondsToISO8601: () => '2025-01-15T00:00:00.000Z'
      },
      dynamodb: { toMapValues: (v: any) => v },
      // Deliberately does NOT throw; assertions inspect the recorded errors.
      error: (msg: string, type?: string) => {
        errors.push({ msg, type });
      }
    }
  };
});

import * as createInviteFn from '../../../tofu/application/appsync/js-resolvers/create_invite_fn.js';
import * as createShareFn from '../../../tofu/application/appsync/js-resolvers/create_share_fn.js';

function inviteCtx(permissions: any) {
  return {
    args: { input: { profileId: 'PROFILE#abc', permissions } },
    identity: { sub: 'caller-sub' },
    stash: { profile: { ownerAccountId: 'ACCOUNT#owner' } }
  };
}

function shareCtx(permissions: any) {
  return {
    args: { input: { profileId: 'PROFILE#abc', permissions } },
    identity: { sub: 'caller-sub' },
    stash: { targetAccountId: 'ACCOUNT#target', profile: { ownerAccountId: 'ACCOUNT#owner' } }
  };
}

beforeEach(() => {
  errors.length = 0;
});

describe('#449 permissions validation (create_invite_fn)', () => {
  test('mixed valid + garbage permissions are rejected', () => {
    createInviteFn.request(inviteCtx(['READ', 'ADMIN']) as any);
    expect(errors).toContainEqual({
      msg: 'permissions must contain only supported permissions (READ or WRITE)',
      type: 'INVALID_INPUT'
    });
  });

  test('pure garbage permissions are rejected', () => {
    createInviteFn.request(inviteCtx(['ADMIN', 'OWNER']) as any);
    expect(errors).toContainEqual({
      msg: 'permissions must contain only supported permissions (READ or WRITE)',
      type: 'INVALID_INPUT'
    });
  });

  test('non-string permissions are rejected', () => {
    createInviteFn.request(inviteCtx(['READ', 42]) as any);
    expect(errors.some(e => e.type === 'INVALID_INPUT')).toBe(true);
  });

  test('valid permissions pass without error', () => {
    const req: any = createInviteFn.request(inviteCtx(['READ', 'WRITE']) as any);
    expect(errors).toEqual([]);
    expect(req.operation).toBe('PutItem');
    expect(req.attributeValues.permissions).toEqual(['READ', 'WRITE']);
  });

  test('lowercase valid permissions pass (case-insensitive)', () => {
    createInviteFn.request(inviteCtx(['read']) as any);
    expect(errors).toEqual([]);
  });
});

describe('#449 permissions validation (create_share_fn)', () => {
  test('mixed valid + garbage permissions are rejected', () => {
    createShareFn.request(shareCtx(['WRITE', 'DELETE']) as any);
    expect(errors).toContainEqual({
      msg: 'permissions must contain only supported permissions (READ or WRITE)',
      type: 'INVALID_INPUT'
    });
  });

  test('pure garbage permissions are rejected', () => {
    createShareFn.request(shareCtx(['ADMIN']) as any);
    expect(errors).toContainEqual({
      msg: 'permissions must contain only supported permissions (READ or WRITE)',
      type: 'INVALID_INPUT'
    });
  });

  test('valid permissions pass without error', () => {
    const req: any = createShareFn.request(shareCtx(['READ']) as any);
    expect(errors).toEqual([]);
    expect(req.operation).toBe('PutItem');
  });
});
