import { describe, test, expect } from 'vitest';
import { readFileSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';
import { renderVtlTemplate, VtlError } from './appsync_vtl_harness';

const __dirname = fileURLToPath(new URL('.', import.meta.url));

const TEMPLATES_DIR = join(
  __dirname,
  '..',
  '..',
  'tofu',
  'application',
  'appsync',
  'mapping-templates'
);

const RESPONSE_TEMPLATE = readFileSync(
  join(TEMPLATES_DIR, 'get_catalog_response.vtl'),
  'utf8'
);

const OWNER_SUB = '11111111-2222-3333-4444-555555555555';
const OTHER_SUB = '99999999-8888-7777-6666-555555555555';
const OWNER_ACCOUNT_ID = `ACCOUNT#${OWNER_SUB}`;

interface CatalogItem {
  catalogId: string;
  catalogName: string;
  catalogType: string;
  ownerAccountId: string;
  isPublic: boolean;
  products: unknown[];
}

function catalog(overrides: Partial<CatalogItem> = {}): CatalogItem {
  return {
    catalogId: 'CATALOG#abc123',
    catalogName: 'Troop fundraiser',
    catalogType: 'USER_CREATED',
    ownerAccountId: OWNER_ACCOUNT_ID,
    isPublic: false,
    products: [],
    ...overrides,
  };
}

function makeCtx(opts: {
  sub: string;
  result?: CatalogItem | null;
  error?: { message: string; type: string };
}): unknown {
  return {
    identity: { sub: opts.sub },
    result: opts.result,
    ...(opts.error ? { error: opts.error } : {}),
  };
}

function render(ctx: unknown): string {
  return renderVtlTemplate(RESPONSE_TEMPLATE, ctx).trim();
}

describe('get_catalog_response.vtl (#509 ownership enforcement)', () => {
  test('returns the catalog when the caller is the owner of a private catalog', () => {
    const item = catalog();
    expect(render(makeCtx({ sub: OWNER_SUB, result: item }))).toBe(
      JSON.stringify(item)
    );
  });

  test('refuses (returns null) when a different authenticated caller reads a private catalog', () => {
    const item = catalog();
    expect(render(makeCtx({ sub: OTHER_SUB, result: item }))).toBe('null');
  });

  test('returns a public catalog to a non-owner caller', () => {
    const item = catalog({ isPublic: true, ownerAccountId: OWNER_ACCOUNT_ID });
    expect(render(makeCtx({ sub: OTHER_SUB, result: item }))).toBe(
      JSON.stringify(item)
    );
  });

  test('returns an ADMIN_MANAGED catalog to a non-owner caller even when not public', () => {
    const item = catalog({
      catalogType: 'ADMIN_MANAGED',
      isPublic: false,
      ownerAccountId: 'ACCOUNT#admin-sub',
    });
    expect(render(makeCtx({ sub: OTHER_SUB, result: item }))).toBe(
      JSON.stringify(item)
    );
  });

  test('returns null when the catalog does not exist', () => {
    expect(render(makeCtx({ sub: OTHER_SUB, result: null }))).toBe('null');
  });

  test('propagates a datastore error instead of evaluating authorization', () => {
    expect(() =>
      render(
        makeCtx({
          sub: OTHER_SUB,
          result: null,
          error: { message: 'DynamoDB unavailable', type: 'INTERNAL_ERROR' },
        })
      )
    ).toThrowError(
      expect.objectContaining({
        name: 'VtlError',
        message: 'DynamoDB unavailable',
        errorType: 'INTERNAL_ERROR',
      }) as Error
    );
  });

  test('VtlError carries the datastore error type', () => {
    try {
      render(
        makeCtx({
          sub: OTHER_SUB,
          result: null,
          error: { message: 'throttled', type: 'RESOURCE_BUSY' },
        })
      );
      expect.unreachable('expected render to throw');
    } catch (error) {
      expect(error).toBeInstanceOf(VtlError);
      expect((error as VtlError).errorType).toBe('RESOURCE_BUSY');
    }
  });
});
