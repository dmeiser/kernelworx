import { vi, describe, test, expect, beforeEach } from 'vitest';

// Regression tests for kernelworx issue #706: private catalog authorization
// bypass (IDOR) and deletion DoS via createSharedCampaign, createCampaign,
// and updateCampaign. The fix enforces the same visibility rule as
// getCatalog (#509): a catalog may only be referenced when it is public,
// ADMIN_MANAGED, or owned by the caller.

const errors: Array<{ msg: string; type?: string }> = vi.hoisted(() => []);

vi.mock('@aws-appsync/utils', () => {
  return {
    util: {
      autoId: () => 'TESTID',
      time: { nowISO8601: () => '2025-01-01T00:00:00.000Z' },
      dynamodb: { toMapValues: (v: any) => v },
      error: (msg: string, type?: string) => {
        throw new Error(`${type || 'ERROR'}: ${msg}`);
      }
    }
  };
});

import * as getCatalogForSharedCampaign from '../../../tofu/application/appsync/js-resolvers/get_catalog_for_shared_campaign_fn.js';
import * as verifySharedCampaignCatalog from '../../../tofu/application/appsync/js-resolvers/verify_shared_campaign_catalog_fn.js';
import * as verifyUpdateCatalogAccess from '../../../tofu/application/appsync/js-resolvers/verify_update_catalog_access_fn.js';

const CALLER_SUB = 'caller-uuid-1';
const CALLER_ACCOUNT = 'ACCOUNT#caller-uuid-1';
const OTHER_ACCOUNT = 'ACCOUNT#victim-uuid-2';

function privateCatalog(overrides: Record<string, unknown> = {}) {
  return {
    catalogId: 'CATALOG#abc',
    catalogName: 'Private Catalog',
    catalogType: 'USER_CREATED',
    isPublic: false,
    ownerAccountId: OTHER_ACCOUNT,
    isDeleted: false,
    ...overrides
  };
}

function publicCatalog(overrides: Record<string, unknown> = {}) {
  return privateCatalog({ isPublic: true, ...overrides });
}

function adminCatalog(overrides: Record<string, unknown> = {}) {
  return privateCatalog({ catalogType: 'ADMIN_MANAGED', ...overrides });
}

function ownCatalog(overrides: Record<string, unknown> = {}) {
  return privateCatalog({ ownerAccountId: CALLER_ACCOUNT, ...overrides });
}

// ─── get_catalog_for_shared_campaign_fn (createSharedCampaign) ───────────────

describe('get_catalog_for_shared_campaign_fn: #706 catalog visibility', () => {
  test('rejects a private catalog owned by another user (IDOR)', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#abc' } },
      identity: { sub: CALLER_SUB },
      stash: {},
      result: privateCatalog()
    } as any;
    expect(() => getCatalogForSharedCampaign.response(ctx)).toThrow('NOT_FOUND');
  });

  test('accepts a public catalog', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#abc' } },
      identity: { sub: CALLER_SUB },
      stash: {},
      result: publicCatalog()
    } as any;
    const result = getCatalogForSharedCampaign.response(ctx);
    expect(result.catalogId).toBe('CATALOG#abc');
  });

  test('accepts an ADMIN_MANAGED catalog', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#abc' } },
      identity: { sub: CALLER_SUB },
      stash: {},
      result: adminCatalog()
    } as any;
    const result = getCatalogForSharedCampaign.response(ctx);
    expect(result.catalogId).toBe('CATALOG#abc');
  });

  test('accepts a catalog owned by the caller', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#abc' } },
      identity: { sub: CALLER_SUB },
      stash: {},
      result: ownCatalog()
    } as any;
    const result = getCatalogForSharedCampaign.response(ctx);
    expect(result.catalogId).toBe('CATALOG#abc');
  });

  test('still rejects soft-deleted catalogs', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#abc' } },
      identity: { sub: CALLER_SUB },
      stash: {},
      result: ownCatalog({ isDeleted: true })
    } as any;
    expect(() => getCatalogForSharedCampaign.response(ctx)).toThrow('NOT_FOUND');
  });
});

// ─── verify_shared_campaign_catalog_fn (createCampaign) ──────────────────────

describe('verify_shared_campaign_catalog_fn: #706 shared campaign path', () => {
  test('rejects when the catalog is no longer accessible to the shared campaign creator', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#abc' } },
      identity: { sub: CALLER_SUB },
      stash: {
        sharedCampaign: {
          sharedCampaignCode: 'BS123-TEST-XX-25-ABCDEF',
          catalogId: 'CATALOG#abc',
          createdBy: OTHER_ACCOUNT
        }
      },
      result: privateCatalog({ ownerAccountId: 'ACCOUNT#third-party' })
    } as any;
    expect(() => verifySharedCampaignCatalog.response(ctx)).toThrow('INVALID_INPUT');
  });

  test('accepts when the catalog is still owned by the shared campaign creator', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#abc' } },
      identity: { sub: CALLER_SUB },
      stash: {
        sharedCampaign: {
          sharedCampaignCode: 'BS123-TEST-XX-25-ABCDEF',
          catalogId: 'CATALOG#abc',
          createdBy: OTHER_ACCOUNT
        }
      },
      result: privateCatalog({ ownerAccountId: OTHER_ACCOUNT })
    } as any;
    const result = verifySharedCampaignCatalog.response(ctx);
    expect(result.catalogId).toBe('CATALOG#abc');
  });

  test('accepts a public catalog regardless of creator ownership', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#abc' } },
      identity: { sub: CALLER_SUB },
      stash: {
        sharedCampaign: {
          sharedCampaignCode: 'BS123-TEST-XX-25-ABCDEF',
          catalogId: 'CATALOG#abc',
          createdBy: OTHER_ACCOUNT
        }
      },
      result: publicCatalog()
    } as any;
    const result = verifySharedCampaignCatalog.response(ctx);
    expect(result.catalogId).toBe('CATALOG#abc');
  });
});

describe('verify_shared_campaign_catalog_fn: #706 direct path (no shared campaign)', () => {
  test('request fetches the catalog from input.catalogId when no shared campaign', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#abc' } },
      identity: { sub: CALLER_SUB },
      stash: {}
    } as any;
    const req: any = verifySharedCampaignCatalog.request(ctx);
    expect(req.operation).toBe('GetItem');
    expect(req.key.catalogId).toBe('CATALOG#abc');
  });

  test('request is NOOP when no catalogId in input', () => {
    const ctx = {
      args: { input: {} },
      identity: { sub: CALLER_SUB },
      stash: {}
    } as any;
    const req: any = verifySharedCampaignCatalog.request(ctx);
    expect(req.key.catalogId).toBe('NOOP');
  });

  test('response rejects a private catalog not owned by the caller (IDOR)', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#abc' } },
      identity: { sub: CALLER_SUB },
      stash: {},
      result: privateCatalog()
    } as any;
    expect(() => verifySharedCampaignCatalog.response(ctx)).toThrow('NOT_FOUND');
  });

  test('response accepts a catalog owned by the caller', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#abc' } },
      identity: { sub: CALLER_SUB },
      stash: {},
      result: ownCatalog()
    } as any;
    const result = verifySharedCampaignCatalog.response(ctx);
    expect(result.catalogId).toBe('CATALOG#abc');
  });

  test('response accepts a public catalog', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#abc' } },
      identity: { sub: CALLER_SUB },
      stash: {},
      result: publicCatalog()
    } as any;
    const result = verifySharedCampaignCatalog.response(ctx);
    expect(result.catalogId).toBe('CATALOG#abc');
  });

  test('response rejects a soft-deleted catalog', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#abc' } },
      identity: { sub: CALLER_SUB },
      stash: {},
      result: ownCatalog({ isDeleted: true })
    } as any;
    expect(() => verifySharedCampaignCatalog.response(ctx)).toThrow('NOT_FOUND');
  });

  test('response returns null when no catalogId (NOOP path)', () => {
    const ctx = {
      args: { input: {} },
      identity: { sub: CALLER_SUB },
      stash: {},
      result: null
    } as any;
    expect(verifySharedCampaignCatalog.response(ctx)).toBeNull();
  });
});

// ─── verify_update_catalog_access_fn (updateCampaign) ────────────────────────

describe('verify_update_catalog_access_fn: #706 updateCampaign catalog validation', () => {
  test('request fetches the catalog when input.catalogId is present', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#xyz' } },
      identity: { sub: CALLER_SUB }
    } as any;
    const req: any = verifyUpdateCatalogAccess.request(ctx);
    expect(req.operation).toBe('GetItem');
    expect(req.key.catalogId).toBe('CATALOG#xyz');
  });

  test('request is NOOP when catalogId is absent', () => {
    const ctx = {
      args: { input: { campaignName: 'New Name' } },
      identity: { sub: CALLER_SUB }
    } as any;
    const req: any = verifyUpdateCatalogAccess.request(ctx);
    expect(req.key.catalogId).toBe('NOOP');
  });

  test('response rejects a private catalog not owned by the caller (IDOR)', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#xyz' } },
      identity: { sub: CALLER_SUB },
      result: privateCatalog({ catalogId: 'CATALOG#xyz' })
    } as any;
    expect(() => verifyUpdateCatalogAccess.response(ctx)).toThrow('NOT_FOUND');
  });

  test('response accepts a catalog owned by the caller', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#xyz' } },
      identity: { sub: CALLER_SUB },
      result: ownCatalog({ catalogId: 'CATALOG#xyz' })
    } as any;
    const result = verifyUpdateCatalogAccess.response(ctx);
    expect(result.catalogId).toBe('CATALOG#xyz');
  });

  test('response accepts a public catalog', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#xyz' } },
      identity: { sub: CALLER_SUB },
      result: publicCatalog({ catalogId: 'CATALOG#xyz' })
    } as any;
    const result = verifyUpdateCatalogAccess.response(ctx);
    expect(result.catalogId).toBe('CATALOG#xyz');
  });

  test('response accepts an ADMIN_MANAGED catalog', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#xyz' } },
      identity: { sub: CALLER_SUB },
      result: adminCatalog({ catalogId: 'CATALOG#xyz' })
    } as any;
    const result = verifyUpdateCatalogAccess.response(ctx);
    expect(result.catalogId).toBe('CATALOG#xyz');
  });

  test('response rejects a soft-deleted catalog', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#xyz' } },
      identity: { sub: CALLER_SUB },
      result: ownCatalog({ catalogId: 'CATALOG#xyz', isDeleted: true })
    } as any;
    expect(() => verifyUpdateCatalogAccess.response(ctx)).toThrow('NOT_FOUND');
  });

  test('response returns null when catalogId is absent (NOOP path)', () => {
    const ctx = {
      args: { input: { campaignName: 'New Name' } },
      identity: { sub: CALLER_SUB },
      result: null
    } as any;
    expect(verifyUpdateCatalogAccess.response(ctx)).toBeNull();
  });

  test('response rejects a missing catalog (not found in DynamoDB)', () => {
    const ctx = {
      args: { input: { catalogId: 'CATALOG#xyz' } },
      identity: { sub: CALLER_SUB },
      result: null
    } as any;
    expect(() => verifyUpdateCatalogAccess.response(ctx)).toThrow('NOT_FOUND');
  });
});
