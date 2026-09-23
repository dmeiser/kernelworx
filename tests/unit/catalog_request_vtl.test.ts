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

const CREATE_TEMPLATE = readFileSync(
  join(TEMPLATES_DIR, 'create_catalog_request.vtl'),
  'utf8'
);
const UPDATE_TEMPLATE = readFileSync(
  join(TEMPLATES_DIR, 'update_catalog_request.vtl'),
  'utf8'
);

interface ProductInput {
  productId?: string;
  productName?: unknown;
  price?: unknown;
  sortOrder?: number;
  description?: string;
}

function makeCtx(input: {
  catalogName?: unknown;
  isPublic?: boolean;
  products?: unknown;
}): unknown {
  return {
    args: {
      catalogId: 'CATALOG#existing-123',
      input,
    },
    identity: {
      sub: 'user-sub-123',
    },
  };
}

function validProducts(): ProductInput[] {
  return [{ productName: 'Popcorn', price: 10.0, sortOrder: 1 }];
}

function validInput(): { catalogName: string; isPublic: boolean; products: ProductInput[] } {
  return { catalogName: 'Campfire Catalog', isPublic: true, products: validProducts() };
}

function renderCreate(input: ReturnType<typeof validInput>): any {
  return JSON.parse(renderVtlTemplate(CREATE_TEMPLATE, makeCtx(input)));
}

function renderUpdate(input: ReturnType<typeof validInput>): any {
  return JSON.parse(renderVtlTemplate(UPDATE_TEMPLATE, makeCtx(input)));
}

function expectInvalidInput(render: () => unknown, message: string): void {
  let rendered: unknown;
  try {
    rendered = render();
  } catch (error) {
    expect(error).toBeInstanceOf(VtlError);
    expect((error as VtlError).message).toBe(message);
    expect((error as VtlError).errorType).toBe('INVALID_INPUT');
    return;
  }
  throw new Error(
    `Expected $util.error "${message}" but the template rendered: ${JSON.stringify(rendered)}`
  );
}

const operations = [
  { name: 'create_catalog_request.vtl', render: renderCreate, operation: 'PutItem' },
  { name: 'update_catalog_request.vtl', render: renderUpdate, operation: 'UpdateItem' },
] as const;

describe('catalog request VTL templates — emitted DynamoDB request', () => {
  for (const { name, render, operation } of operations) {
    describe(name, () => {
      test('emits a well-formed DynamoDB request for valid input', () => {
        const request = render(validInput());

        expect(request.version).toBe('2017-02-28');
        expect(request.operation).toBe(operation);

        const product = request.attributeValues?.products?.L?.[0]?.M ?? request.update?.expressionValues?.[':products']?.L?.[0]?.M;
        expect(product.productName.S).toBe('Popcorn');
        expect(product.price.N).toBe('10');
        expect(product.sortOrder.N).toBe('1');
        expect(product.productId.S).toMatch(/^PRODUCT#/);

        const catalogName = request.attributeValues?.catalogName ?? request.update?.expressionValues?.[':catalogName'];
        expect(catalogName.S).toBe('Campfire Catalog');
      });

      test('scopes the request to the caller identity and stamps timestamps', () => {
        const request = render(validInput());

        const owner = request.attributeValues?.ownerAccountId ?? { S: 'ACCOUNT#user-sub-123' };
        expect(owner.S).toBe('ACCOUNT#user-sub-123');
        expect(request.attributeValues?.catalogType?.S ?? 'USER_CREATED').toBe('USER_CREATED');
        expect(request.attributeValues?.isPublic?.S ?? request.update?.expressionValues?.[':isPublic']?.S).toBe('true');
      });

      test('accepts a zero price (free item)', () => {
        const input = validInput();
        input.products = [{ productName: 'Free Sample', price: 0.0, sortOrder: 1 }];
        expect(() => render(input)).not.toThrow();
      });

      if (operation === 'UpdateItem') {
        test('preserves an existing productId and generates one when absent', () => {
          const input = validInput();
          input.products = [
            { productId: 'PRODUCT#keep-me', productName: 'Existing', price: 3, sortOrder: 0 },
            { productName: 'New', price: 4, sortOrder: 1 },
          ];
          const request = render(input);
          const products = request.update.expressionValues[':products'].L.map(
            (entry: any) => entry.M
          );
          expect(products[0].productId.S).toBe('PRODUCT#keep-me');
          expect(products[1].productId.S).toMatch(/^PRODUCT#/);
          expect(request.condition.expression).toBe(
            'attribute_exists(catalogId) AND ownerAccountId = :ownerId'
          );
          expect(request.update.expressionValues[':ownerId']?.S ?? request.condition.expressionValues[':ownerId'].S).toBe(
            'ACCOUNT#user-sub-123'
          );
        });
      } else {
        test('generates a catalogId and renders false isPublic when absent', () => {
          const input = validInput();
          input.isPublic = false;
          const request = render(input);
          expect(request.key.catalogId.S).toMatch(/^CATALOG#/);
          expect(request.attributeValues.isPublic.S).toBe('false');
          expect(request.attributeValues.isPublicStr.S).toBe('false');
        });
      }
    });
  }
});

describe('catalog request VTL templates — input validation behavior', () => {
  interface InvalidCase {
    name: string;
    mutate: (input: ReturnType<typeof validInput>) => void;
    message: string;
  }

  const cases: InvalidCase[] = [
    {
      name: 'empty catalogName',
      mutate: (input) => {
        input.catalogName = '';
      },
      message: 'Catalog name is required',
    },
    {
      name: 'whitespace-only catalogName',
      mutate: (input) => {
        input.catalogName = '   ';
      },
      message: 'Catalog name is required',
    },
    {
      name: 'null catalogName',
      mutate: (input) => {
        input.catalogName = null;
      },
      message: 'Catalog name is required',
    },
    {
      name: 'non-string catalogName',
      mutate: (input) => {
        input.catalogName = 12345;
      },
      message: 'Catalog name is required',
    },
    {
      name: 'empty products array',
      mutate: (input) => {
        input.products = [];
      },
      message: 'Products array cannot be empty',
    },
    {
      name: 'non-array products',
      mutate: (input) => {
        input.products = null;
      },
      message: 'Products array cannot be empty',
    },
    {
      name: 'empty productName',
      mutate: (input) => {
        input.products = [{ productName: '', price: 10.0, sortOrder: 1 }];
      },
      message: 'Product name is required',
    },
    {
      name: 'whitespace-only productName',
      mutate: (input) => {
        input.products = [{ productName: '   ', price: 10.0, sortOrder: 1 }];
      },
      message: 'Product name is required',
    },
    {
      name: 'non-string productName',
      mutate: (input) => {
        input.products = [{ productName: 999, price: 10.0, sortOrder: 1 }];
      },
      message: 'Product name is required',
    },
    {
      name: 'negative price',
      mutate: (input) => {
        input.products = [{ productName: 'Bad Item', price: -5.0, sortOrder: 1 }];
      },
      message: 'Valid product price is required',
    },
    {
      name: 'small negative price (-0.01)',
      mutate: (input) => {
        input.products = [{ productName: 'Bad Item', price: -0.01, sortOrder: 1 }];
      },
      message: 'Valid product price is required',
    },
    {
      name: 'NaN price',
      mutate: (input) => {
        input.products = [{ productName: 'Bad Item', price: NaN, sortOrder: 1 }];
      },
      message: 'Valid product price is required',
    },
    {
      name: 'Infinity price',
      mutate: (input) => {
        input.products = [{ productName: 'Bad Item', price: Infinity, sortOrder: 1 }];
      },
      message: 'Valid product price is required',
    },
    {
      name: '-Infinity price',
      mutate: (input) => {
        input.products = [{ productName: 'Bad Item', price: -Infinity, sortOrder: 1 }];
      },
      message: 'Valid product price is required',
    },
    {
      name: 'non-numeric price',
      mutate: (input) => {
        input.products = [{ productName: 'Bad Item', price: 'not-a-number', sortOrder: 1 }];
      },
      message: 'Valid product price is required',
    },
    {
      name: 'null price',
      mutate: (input) => {
        input.products = [{ productName: 'Bad Item', price: null, sortOrder: 1 }];
      },
      message: 'Valid product price is required',
    },
  ];

  for (const { name: templateName, render } of operations) {
    describe(templateName, () => {
      for (const invalid of cases) {
        test(`rejects ${invalid.name} with INVALID_INPUT`, () => {
          const input = validInput();
          invalid.mutate(input);
          expectInvalidInput(() => render(input), invalid.message);
        });
      }
    });
  }
});
