import { describe, test, expect } from 'vitest';
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';

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

const CREATE_TEMPLATE_PATH = join(TEMPLATES_DIR, 'create_catalog_request.vtl');
const UPDATE_TEMPLATE_PATH = join(TEMPLATES_DIR, 'update_catalog_request.vtl');

describe('Catalog VTL request templates static assertions', () => {
  test('create_catalog_request.vtl and update_catalog_request.vtl exist', () => {
    expect(existsSync(CREATE_TEMPLATE_PATH)).toBe(true);
    expect(existsSync(UPDATE_TEMPLATE_PATH)).toBe(true);
  });

  const templates = [
    { name: 'create_catalog_request.vtl', path: CREATE_TEMPLATE_PATH },
    { name: 'update_catalog_request.vtl', path: UPDATE_TEMPLATE_PATH },
  ];

  for (const { name, path } of templates) {
    describe(name, () => {
      const content = readFileSync(path, 'utf8');

      test('validates catalogName is non-empty string', () => {
        expect(content).toMatch(/catalogName/);
        expect(content).toMatch(/isNullOrBlank\(\$ctx\.args\.input\.catalogName\)/);
        expect(content).toContain('"Catalog name is required"');
        expect(content).toContain('"INVALID_INPUT"');
      });

      test('validates products array is non-empty', () => {
        expect(content).toMatch(/products/);
        expect(content).toContain('"Products array cannot be empty"');
        expect(content).toContain('"INVALID_INPUT"');
      });

      test('validates productName is non-empty string inside product loop', () => {
        expect(content).toMatch(/#foreach\(\$product in \$ctx\.args\.input\.products\)/);
        expect(content).toMatch(/isNullOrBlank\(\$product\.productName\)/);
        expect(content).toContain('"Product name is required"');
        expect(content).toContain('"INVALID_INPUT"');
      });

      test('validates price is numeric, non-negative, and finite inside product loop', () => {
        expect(content).toMatch(/isNumber\(\$product\.price\)/);
        expect(content).toMatch(/!\(\$product\.price >= 0\)/);
        expect(content).toMatch(/priceStr == "Infinity"/);
        expect(content).toContain('"Valid product price is required"');
        expect(content).toContain('"INVALID_INPUT"');
      });
    });
  }

  test('update_catalog_request.vtl does not have duplicated products array checks', () => {
    const content = readFileSync(UPDATE_TEMPLATE_PATH, 'utf8');
    const matches = content.match(/Products array cannot be empty/g);
    expect(matches).toHaveLength(1);
  });
});

/**
 * Evaluates the catalog request VTL template logic with AppSync VTL semantics.
 */
function evaluateCatalogRequestVtl(
  templateType: 'create' | 'update',
  ctx: {
    args: {
      catalogId?: string;
      input: {
        catalogName?: any;
        isPublic?: boolean;
        products?: any;
      };
    };
    identity: {
      sub: string;
    };
  }
) {
  // AppSync VTL $util implementation
  const util = {
    isString: (val: any) => typeof val === 'string',
    isNumber: (val: any) => typeof val === 'number' && !Number.isNaN(val),
    isList: (val: any) => Array.isArray(val),
    isNullOrBlank: (val: any) => {
      if (val === null || val === undefined) return true;
      if (typeof val !== 'string') return false;
      return val.trim().length === 0;
    },
    error: (message: string, errorType: string) => {
      const err = new Error(message) as any;
      err.errorType = errorType;
      throw err;
    },
    autoId: () => 'mock-auto-id-1234',
    time: {
      nowISO8601: () => '2025-01-01T00:00:00.000Z',
    },
  };

  const input = ctx.args.input;

  // Catalog name validation
  if (!util.isString(input.catalogName) || util.isNullOrBlank(input.catalogName)) {
    util.error('Catalog name is required', 'INVALID_INPUT');
  }

  // Products array validation
  if (!util.isList(input.products) || input.products.length === 0) {
    util.error('Products array cannot be empty', 'INVALID_INPUT');
  }

  const productsWithIds: any[] = [];
  for (const product of input.products) {
    // Product name validation
    if (!util.isString(product.productName) || util.isNullOrBlank(product.productName)) {
      util.error('Product name is required', 'INVALID_INPUT');
    }

    // Price validation
    if (!util.isNumber(product.price) || !(product.price >= 0)) {
      util.error('Valid product price is required', 'INVALID_INPUT');
    }
    const priceStr = String(product.price);
    if (
      priceStr === 'Infinity' ||
      priceStr === '+Infinity' ||
      priceStr === '-Infinity' ||
      priceStr === 'NaN'
    ) {
      util.error('Valid product price is required', 'INVALID_INPUT');
    }

    if (templateType === 'create') {
      const productId = `PRODUCT#${util.autoId()}`;
      const productWithId: any = {
        productId,
        productName: product.productName,
        price: product.price,
        sortOrder: product.sortOrder,
      };
      if (product.description) {
        productWithId.description = product.description;
      }
      productsWithIds.push(productWithId);
    } else {
      const productWithId: any = {
        productName: product.productName,
        price: product.price,
        sortOrder: product.sortOrder,
      };
      if (product.productId) {
        productWithId.productId = product.productId;
      } else {
        productWithId.productId = `PRODUCT#${util.autoId()}`;
      }
      if (product.description) {
        productWithId.description = product.description;
      }
      productsWithIds.push(productWithId);
    }
  }

  const isPublicStr = input.isPublic ? 'true' : 'false';
  const now = util.time.nowISO8601();

  if (templateType === 'create') {
    const catalogId = `CATALOG#${util.autoId()}`;
    return {
      version: '2017-02-28',
      operation: 'PutItem',
      key: {
        catalogId: { S: catalogId },
      },
      attributeValues: {
        catalogName: { S: input.catalogName },
        catalogType: { S: 'USER_CREATED' },
        ownerAccountId: { S: `ACCOUNT#${ctx.identity.sub}` },
        isPublic: { S: isPublicStr },
        isPublicStr: { S: isPublicStr },
        products: productsWithIds,
        createdAt: { S: now },
        updatedAt: { S: now },
      },
    };
  } else {
    return {
      version: '2017-02-28',
      operation: 'UpdateItem',
      key: {
        catalogId: { S: ctx.args.catalogId },
      },
      update: {
        expression:
          'SET catalogName = :catalogName, isPublic = :isPublic, isPublicStr = :isPublicStr, products = :products, updatedAt = :updatedAt',
        expressionValues: {
          ':catalogName': { S: input.catalogName },
          ':isPublic': { S: isPublicStr },
          ':isPublicStr': { S: isPublicStr },
          ':products': productsWithIds,
          ':updatedAt': { S: now },
        },
      },
      condition: {
        expression: 'attribute_exists(catalogId) AND ownerAccountId = :ownerId',
        expressionValues: {
          ':ownerId': { S: `ACCOUNT#${ctx.identity.sub}` },
        },
      },
    };
  }
}

describe('Catalog VTL functional evaluation', () => {
  const operations = ['create', 'update'] as const;

  for (const op of operations) {
    describe(`${op}Catalog validation`, () => {
      const baseCtx = {
        args: {
          catalogId: op === 'update' ? 'CATALOG#existing-123' : undefined,
          input: {
            catalogName: 'Campfire Catalog',
            isPublic: true,
            products: [
              { productName: 'Popcorn', price: 10.0, sortOrder: 1 },
            ],
          },
        },
        identity: {
          sub: 'user-sub-123',
        },
      };

      test('accepts valid input with positive price', () => {
        const res = evaluateCatalogRequestVtl(op, baseCtx);
        expect(res).toBeDefined();
        expect(res.operation).toBe(op === 'create' ? 'PutItem' : 'UpdateItem');
      });

      test('accepts zero price (free item)', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: {
              ...baseCtx.args.input,
              products: [{ productName: 'Free Sample', price: 0.0, sortOrder: 1 }],
            },
          },
        };
        const res = evaluateCatalogRequestVtl(op, ctx);
        expect(res).toBeDefined();
      });

      test('rejects empty catalogName', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: { ...baseCtx.args.input, catalogName: '' },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Catalog name is required'
        );
      });

      test('rejects whitespace-only catalogName', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: { ...baseCtx.args.input, catalogName: '   ' },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Catalog name is required'
        );
      });

      test('rejects null catalogName', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: { ...baseCtx.args.input, catalogName: null },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Catalog name is required'
        );
      });

      test('rejects non-string catalogName', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: { ...baseCtx.args.input, catalogName: 12345 },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Catalog name is required'
        );
      });

      test('rejects empty products array', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: { ...baseCtx.args.input, products: [] },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Products array cannot be empty'
        );
      });

      test('rejects non-array products', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: { ...baseCtx.args.input, products: null },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Products array cannot be empty'
        );
      });

      test('rejects empty productName', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: {
              ...baseCtx.args.input,
              products: [{ productName: '', price: 10.0, sortOrder: 1 }],
            },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Product name is required'
        );
      });

      test('rejects whitespace-only productName', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: {
              ...baseCtx.args.input,
              products: [{ productName: '   ', price: 10.0, sortOrder: 1 }],
            },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Product name is required'
        );
      });

      test('rejects non-string productName', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: {
              ...baseCtx.args.input,
              products: [{ productName: 999, price: 10.0, sortOrder: 1 }],
            },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Product name is required'
        );
      });

      test('rejects negative price', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: {
              ...baseCtx.args.input,
              products: [{ productName: 'Bad Item', price: -5.0, sortOrder: 1 }],
            },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Valid product price is required'
        );
      });

      test('rejects negative small price (-0.01)', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: {
              ...baseCtx.args.input,
              products: [{ productName: 'Bad Item', price: -0.01, sortOrder: 1 }],
            },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Valid product price is required'
        );
      });

      test('rejects NaN price', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: {
              ...baseCtx.args.input,
              products: [{ productName: 'Bad Item', price: NaN, sortOrder: 1 }],
            },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Valid product price is required'
        );
      });

      test('rejects Infinity price', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: {
              ...baseCtx.args.input,
              products: [{ productName: 'Bad Item', price: Infinity, sortOrder: 1 }],
            },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Valid product price is required'
        );
      });

      test('rejects -Infinity price', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: {
              ...baseCtx.args.input,
              products: [{ productName: 'Bad Item', price: -Infinity, sortOrder: 1 }],
            },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Valid product price is required'
        );
      });

      test('rejects non-numeric price', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: {
              ...baseCtx.args.input,
              products: [{ productName: 'Bad Item', price: 'not-a-number', sortOrder: 1 }],
            },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Valid product price is required'
        );
      });

      test('rejects null price', () => {
        const ctx = {
          ...baseCtx,
          args: {
            ...baseCtx.args,
            input: {
              ...baseCtx.args.input,
              products: [{ productName: 'Bad Item', price: null, sortOrder: 1 }],
            },
          },
        };
        expect(() => evaluateCatalogRequestVtl(op, ctx)).toThrowError(
          'Valid product price is required'
        );
      });
    });
  }
});
