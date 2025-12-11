/**
 * Integration tests for Catalog CRUD mutations
 * 
 * Tests 3 resolvers:
 * - createCatalog (VTL resolver)
 * - updateCatalog (VTL resolver with owner authorization)
 * - deleteCatalog (VTL resolver with owner authorization)
 * 
 * Coverage:
 * - Happy paths (CRUD operations)
 * - Authorization (owner-only for update/delete)
 * - Input validation
 * - Data integrity
 */

import '../setup.ts'; // Load environment variables and setup
import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import { ApolloClient, gql } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';
import { cleanupTestData } from '../setup/testData';

// GraphQL Mutations
const CREATE_CATALOG = gql`
  mutation CreateCatalog($input: CreateCatalogInput!) {
    createCatalog(input: $input) {
      catalogId
      catalogName
      catalogType
      ownerAccountId
      isPublic
      products {
        productId
        productName
        description
        price
        sortOrder
      }
      createdAt
      updatedAt
    }
  }
`;

const UPDATE_CATALOG = gql`
  mutation UpdateCatalog($catalogId: ID!, $input: CreateCatalogInput!) {
    updateCatalog(catalogId: $catalogId, input: $input) {
      catalogId
      catalogName
      isPublic
      products {
        productId
        productName
        description
        price
        sortOrder
      }
      updatedAt
    }
  }
`;

const DELETE_CATALOG = gql`
  mutation DeleteCatalog($catalogId: ID!) {
    deleteCatalog(catalogId: $catalogId)
  }
`;

describe('Catalog CRUD Integration Tests', () => {
  let ownerClient: ApolloClient;
  let contributorClient: ApolloClient;
  let readonlyClient: ApolloClient;
  let testCatalogId: string | null = null;

  beforeAll(async () => {
    const ownerResult: AuthenticatedClientResult = await createAuthenticatedClient('owner');
    const contributorResult: AuthenticatedClientResult = await createAuthenticatedClient('contributor');
    const readonlyResult: AuthenticatedClientResult = await createAuthenticatedClient('readonly');

    ownerClient = ownerResult.client;
    contributorClient = contributorResult.client;
    readonlyClient = readonlyResult.client;
  });

  // Cleanup after each test
  afterEach(async () => {
    await cleanupTestData({
      catalogIds: testCatalogId ? [testCatalogId] : [],
    });
    testCatalogId = null;
  });

  describe('createCatalog', () => {
    describe('Happy Path', () => {
      it('should create catalog with products', async () => {
        // Arrange
        const input = {
          catalogName: 'Test Catalog',
          isPublic: true,
          products: [
            {
              productName: 'Product 1',
              description: 'First product',
              price: 10.99,
              sortOrder: 1,
            },
            {
              productName: 'Product 2',
              price: 20.50,
              sortOrder: 2,
            },
          ],
        };

        // Act
        const { data } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input },
        });

        // Assert
        testCatalogId = data.createCatalog.catalogId;
        expect(data.createCatalog).toBeDefined();
        expect(data.createCatalog.catalogId).toMatch(/^CATALOG#/);
        expect(data.createCatalog.catalogName).toBe('Test Catalog');
        expect(data.createCatalog.catalogType).toBe('USER_CREATED');
        expect(data.createCatalog.ownerAccountId).toBeDefined();
        expect(data.createCatalog.isPublic).toBe(true);
        expect(data.createCatalog.products).toHaveLength(2);
        expect(data.createCatalog.createdAt).toBeDefined();
        expect(data.createCatalog.updatedAt).toBeDefined();
      });

      it('should auto-generate unique catalogId', async () => {
        // Arrange
        const input = {
          catalogName: 'Catalog 1',
          isPublic: false,
          products: [{ productName: 'Product', price: 5.0, sortOrder: 1 }],
        };

        // Act
        const { data: data1 } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input },
        });
        const catalogId1 = data1.createCatalog.catalogId;

        const { data: data2 } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: { ...input, catalogName: 'Catalog 2' } },
        });
        const catalogId2 = data2.createCatalog.catalogId;

        // Assert
        expect(catalogId1).not.toBe(catalogId2);
        expect(catalogId1).toMatch(/^CATALOG#/);
        expect(catalogId2).toMatch(/^CATALOG#/);

        // Cleanup both
        await cleanupTestData({
          catalogIds: [catalogId1, catalogId2],
        });
      });

      it('should auto-generate productId for each product', async () => {
        // Arrange
        const input = {
          catalogName: 'Test Catalog',
          isPublic: true,
          products: [
            { productName: 'Product 1', price: 10.0, sortOrder: 1 },
            { productName: 'Product 2', price: 20.0, sortOrder: 2 },
            { productName: 'Product 3', price: 30.0, sortOrder: 3 },
          ],
        };

        // Act
        const { data } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input },
        });

        // Assert
        testCatalogId = data.createCatalog.catalogId;
        const products = data.createCatalog.products;
        expect(products).toHaveLength(3);
        
        const productIds = products.map((p: any) => p.productId);
        expect(productIds.every((id: string) => id.startsWith('PRODUCT#'))).toBe(true);
        
        // All product IDs should be unique
        const uniqueIds = new Set(productIds);
        expect(uniqueIds.size).toBe(3);
      });

      it('should set catalogType to USER_CREATED', async () => {
        // Arrange
        const input = {
          catalogName: 'User Catalog',
          isPublic: false,
          products: [{ productName: 'Product', price: 15.0, sortOrder: 1 }],
        };

        // Act
        const { data } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input },
        });

        // Assert
        testCatalogId = data.createCatalog.catalogId;
        expect(data.createCatalog.catalogType).toBe('USER_CREATED');
      });

      it('should set ownerAccountId to current user', async () => {
        // Arrange
        const input = {
          catalogName: 'My Catalog',
          isPublic: true,
          products: [{ productName: 'Product', price: 25.0, sortOrder: 1 }],
        };

        // Act
        const { data } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input },
        });

        // Assert
        testCatalogId = data.createCatalog.catalogId;
        expect(data.createCatalog.ownerAccountId).toBeDefined();
        expect(typeof data.createCatalog.ownerAccountId).toBe('string');
      });

      it('should create public catalog (isPublic=true)', async () => {
        // Arrange
        const input = {
          catalogName: 'Public Catalog',
          isPublic: true,
          products: [{ productName: 'Public Product', price: 12.0, sortOrder: 1 }],
        };

        // Act
        const { data } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input },
        });

        // Assert
        testCatalogId = data.createCatalog.catalogId;
        expect(data.createCatalog.isPublic).toBe(true);
      });

      it('should create private catalog (isPublic=false)', async () => {
        // Arrange
        const input = {
          catalogName: 'Private Catalog',
          isPublic: false,
          products: [{ productName: 'Private Product', price: 8.0, sortOrder: 1 }],
        };

        // Act
        const { data } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input },
        });

        // Assert
        testCatalogId = data.createCatalog.catalogId;
        expect(data.createCatalog.isPublic).toBe(false);
      });

      it('should accept product with optional description', async () => {
        // Arrange
        const input = {
          catalogName: 'Catalog with Descriptions',
          isPublic: true,
          products: [
            {
              productName: 'Product with description',
              description: 'This is a detailed description',
              price: 15.0,
              sortOrder: 1,
            },
            {
              productName: 'Product without description',
              price: 10.0,
              sortOrder: 2,
            },
          ],
        };

        // Act
        const { data } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input },
        });

        // Assert
        testCatalogId = data.createCatalog.catalogId;
        const products = data.createCatalog.products;
        expect(products[0].description).toBe('This is a detailed description');
        expect(products[1].description).toBeNull(); // GraphQL returns null for omitted optional fields
      });
    });

    describe('Authorization', () => {
      it('should allow authenticated user to create catalogs', async () => {
        // Arrange
        const input = {
          catalogName: 'Owner Catalog',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };

        // Act
        const { data } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input },
        });

        // Assert
        testCatalogId = data.createCatalog.catalogId;
        expect(data.createCatalog).toBeDefined();
      });

      it('should allow contributor to create their own catalogs', async () => {
        // Arrange
        const input = {
          catalogName: 'Contributor Catalog',
          isPublic: false,
          products: [{ productName: 'Product', price: 20.0, sortOrder: 1 }],
        };

        // Act
        const { data } = await contributorClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input },
        });

        // Assert
        testCatalogId = data.createCatalog.catalogId;
        expect(data.createCatalog).toBeDefined();
        expect(data.createCatalog.ownerAccountId).toBeDefined();
      });
    });

    describe('Input Validation', () => {
      it('should reject empty products array', async () => {
        // Arrange
        const input = {
          catalogName: 'Empty Catalog',
          isPublic: true,
          products: [],
        };

        // Act & Assert
        await expect(
          ownerClient.mutate({
            mutation: CREATE_CATALOG,
            variables: { input },
          })
        ).rejects.toThrow();
      });
    });

    describe('Data Integrity', () => {
      it('should set timestamps (createdAt, updatedAt)', async () => {
        // Arrange
        const input = {
          catalogName: 'Timestamped Catalog',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };

        // Act
        const { data } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input },
        });

        // Assert
        testCatalogId = data.createCatalog.catalogId;
        expect(data.createCatalog.createdAt).toBeDefined();
        expect(data.createCatalog.updatedAt).toBeDefined();
        
        // Both should be ISO8601 datetime strings
        expect(new Date(data.createCatalog.createdAt).toISOString()).toBe(
          data.createCatalog.createdAt
        );
        expect(new Date(data.createCatalog.updatedAt).toISOString()).toBe(
          data.createCatalog.updatedAt
        );
      });

      it('should store products with all fields', async () => {
        // Arrange
        const input = {
          catalogName: 'Complete Product Catalog',
          isPublic: true,
          products: [
            {
              productName: 'Complete Product',
              description: 'Full description',
              price: 29.99,
              sortOrder: 1,
            },
          ],
        };

        // Act
        const { data } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input },
        });

        // Assert
        testCatalogId = data.createCatalog.catalogId;
        const product = data.createCatalog.products[0];
        expect(product.productId).toBeDefined();
        expect(product.productName).toBe('Complete Product');
        expect(product.description).toBe('Full description');
        expect(product.price).toBe(29.99);
        expect(product.sortOrder).toBe(1);
      });
    });
  });

  describe('updateCatalog', () => {
    describe('Happy Path', () => {
      it('should update catalog name', async () => {
        // Arrange: Create catalog first
        const createInput = {
          catalogName: 'Original Name',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createInput },
        });
        testCatalogId = createData.createCatalog.catalogId;

        // Act: Update name
        const updateInput = {
          catalogName: 'Updated Name',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };
        const { data } = await ownerClient.mutate({
          mutation: UPDATE_CATALOG,
          variables: { catalogId: testCatalogId, input: updateInput },
        });

        // Assert
        expect(data.updateCatalog.catalogName).toBe('Updated Name');
      });

      it('should update catalog products', async () => {
        // Arrange: Create catalog
        const createInput = {
          catalogName: 'Product Update Test',
          isPublic: false,
          products: [
            { productName: 'Old Product 1', price: 5.0, sortOrder: 1 },
            { productName: 'Old Product 2', price: 10.0, sortOrder: 2 },
          ],
        };
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createInput },
        });
        testCatalogId = createData.createCatalog.catalogId;

        // Act: Update products
        const updateInput = {
          catalogName: 'Product Update Test',
          isPublic: false,
          products: [
            { productName: 'New Product 1', price: 15.0, sortOrder: 1 },
            { productName: 'New Product 2', price: 20.0, sortOrder: 2 },
            { productName: 'New Product 3', price: 25.0, sortOrder: 3 },
          ],
        };
        const { data } = await ownerClient.mutate({
          mutation: UPDATE_CATALOG,
          variables: { catalogId: testCatalogId, input: updateInput },
        });

        // Assert
        expect(data.updateCatalog.products).toHaveLength(3);
        expect(data.updateCatalog.products[0].productName).toBe('New Product 1');
        expect(data.updateCatalog.products[2].productName).toBe('New Product 3');
      });

      it('should update isPublic flag', async () => {
        // Arrange: Create private catalog
        const createInput = {
          catalogName: 'Visibility Test',
          isPublic: false,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createInput },
        });
        testCatalogId = createData.createCatalog.catalogId;

        // Act: Make public
        const updateInput = {
          catalogName: 'Visibility Test',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };
        const { data } = await ownerClient.mutate({
          mutation: UPDATE_CATALOG,
          variables: { catalogId: testCatalogId, input: updateInput },
        });

        // Assert
        expect(data.updateCatalog.isPublic).toBe(true);
      });

      it('should update timestamp (updatedAt)', async () => {
        // Arrange: Create catalog
        const createInput = {
          catalogName: 'Timestamp Test',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createInput },
        });
        testCatalogId = createData.createCatalog.catalogId;
        const originalUpdatedAt = createData.createCatalog.updatedAt;

        // Wait a moment to ensure timestamp difference
        await new Promise((resolve) => setTimeout(resolve, 1000));

        // Act: Update catalog
        const updateInput = {
          catalogName: 'Timestamp Test Updated',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };
        const { data } = await ownerClient.mutate({
          mutation: UPDATE_CATALOG,
          variables: { catalogId: testCatalogId, input: updateInput },
        });

        // Assert
        expect(data.updateCatalog.updatedAt).toBeDefined();
        expect(new Date(data.updateCatalog.updatedAt).getTime()).toBeGreaterThan(
          new Date(originalUpdatedAt).getTime()
        );
      });
    });

    describe('Authorization', () => {
      it('should allow catalog owner to update catalog', async () => {
        // Arrange: Create catalog
        const createInput = {
          catalogName: 'Owner Update Test',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createInput },
        });
        testCatalogId = createData.createCatalog.catalogId;

        // Act: Update as owner
        const updateInput = {
          catalogName: 'Updated by Owner',
          isPublic: true,
          products: [{ productName: 'Product', price: 15.0, sortOrder: 1 }],
        };
        const { data } = await ownerClient.mutate({
          mutation: UPDATE_CATALOG,
          variables: { catalogId: testCatalogId, input: updateInput },
        });

        // Assert
        expect(data.updateCatalog.catalogName).toBe('Updated by Owner');
      });

      it('should reject non-owner updating catalog', async () => {
        // Arrange: Owner creates catalog
        const createInput = {
          catalogName: 'Owner Only Catalog',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createInput },
        });
        testCatalogId = createData.createCatalog.catalogId;

        // Act & Assert: Contributor tries to update
        const updateInput = {
          catalogName: 'Hacked Name',
          isPublic: false,
          products: [{ productName: 'Product', price: 99.0, sortOrder: 1 }],
        };
        await expect(
          contributorClient.mutate({
            mutation: UPDATE_CATALOG,
            variables: { catalogId: testCatalogId, input: updateInput },
          })
        ).rejects.toThrow(/conditional request failed/i);  // VTL returns raw DynamoDB error
      });
    });

    describe('Input Validation', () => {
      it('should reject update with non-existent catalogId', async () => {
        // Arrange
        const updateInput = {
          catalogName: 'Ghost Catalog',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };

        // Act & Assert
        await expect(
          ownerClient.mutate({
            mutation: UPDATE_CATALOG,
            variables: { catalogId: 'CATALOG#nonexistent', input: updateInput },
          })
        ).rejects.toThrow(/conditional request failed/i);  // VTL returns raw DynamoDB error
      });
    });
  });

  describe('deleteCatalog', () => {
    describe('Happy Path', () => {
      it('should delete existing catalog', async () => {
        // Arrange: Create catalog
        const createInput = {
          catalogName: 'Catalog to Delete',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createInput },
        });
        testCatalogId = createData.createCatalog.catalogId;

        // Act: Delete catalog
        const { data } = await ownerClient.mutate({
          mutation: DELETE_CATALOG,
          variables: { catalogId: testCatalogId },
        });

        // Assert
        expect(data.deleteCatalog).toBe(true);
        testCatalogId = null; // Prevent cleanup double-delete
      });

      it('should return true on successful deletion', async () => {
        // Arrange: Create catalog
        const createInput = {
          catalogName: 'Success Test',
          isPublic: false,
          products: [{ productName: 'Product', price: 5.0, sortOrder: 1 }],
        };
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createInput },
        });
        testCatalogId = createData.createCatalog.catalogId;

        // Act & Assert
        const { data } = await ownerClient.mutate({
          mutation: DELETE_CATALOG,
          variables: { catalogId: testCatalogId },
        });
        
        expect(data.deleteCatalog).toBe(true);
        testCatalogId = null;
      });
    });

    describe('Authorization', () => {
      it('should allow catalog owner to delete catalog', async () => {
        // Arrange: Create catalog
        const createInput = {
          catalogName: 'Owner Delete Test',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createInput },
        });
        testCatalogId = createData.createCatalog.catalogId;

        // Act: Delete as owner
        const { data } = await ownerClient.mutate({
          mutation: DELETE_CATALOG,
          variables: { catalogId: testCatalogId },
        });

        // Assert
        expect(data.deleteCatalog).toBe(true);
        testCatalogId = null;
      });

      it('should reject non-owner deleting catalog', async () => {
        // Arrange: Owner creates catalog
        const createInput = {
          catalogName: 'Protected Catalog',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createInput },
        });
        testCatalogId = createData.createCatalog.catalogId;

        // Act & Assert: Contributor tries to delete
        await expect(
          contributorClient.mutate({
            mutation: DELETE_CATALOG,
            variables: { catalogId: testCatalogId },
          })
        ).rejects.toThrow(/conditional request failed/i);  // VTL returns raw DynamoDB error
      });
    });

    describe('Idempotency', () => {
      it('should reject deletion of non-existent catalog', async () => {
        // Act & Assert
        await expect(
          ownerClient.mutate({
            mutation: DELETE_CATALOG,
            variables: { catalogId: 'CATALOG#nonexistent' },
          })
        ).rejects.toThrow(/Cannot return null for non-nullable type.*Boolean|conditional request failed/i);  // VTL: null for non-nullable or conditional failure
      });
    });
  });
});
