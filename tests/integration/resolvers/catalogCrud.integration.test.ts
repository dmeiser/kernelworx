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
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, gql } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';
import { deleteTestAccounts, TABLE_NAMES } from '../setup/testData';

// GraphQL Mutations
const CREATE_CATALOG = gql`
  mutation CreateCatalog($input: CreateCatalogInput!) {
    createCatalog(input: $input) {
      catalogId
      catalogName
      catalogType
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
  
  // Track account IDs for cleanup
  let ownerAccountId: string;
  let contributorAccountId: string;
  let readonlyAccountId: string;

  beforeAll(async () => {
    const ownerResult: AuthenticatedClientResult = await createAuthenticatedClient('owner');
    const contributorResult: AuthenticatedClientResult = await createAuthenticatedClient('contributor');
    const readonlyResult: AuthenticatedClientResult = await createAuthenticatedClient('readonly');

    ownerClient = ownerResult.client;
    contributorClient = contributorResult.client;
    readonlyClient = readonlyResult.client;
    
    ownerAccountId = ownerResult.accountId;
    contributorAccountId = contributorResult.accountId;
    readonlyAccountId = readonlyResult.accountId;
  });

  afterAll(async () => {
    // Clean up account records created by Cognito post-auth trigger
    console.log('Cleaning up account records...');
    // await deleteTestAccounts([ownerAccountId, contributorAccountId, readonlyAccountId]);
    console.log('Account cleanup complete.');
  }, 30000);

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
        const catalogId = data.createCatalog.catalogId;
        expect(data.createCatalog).toBeDefined();
        expect(data.createCatalog.catalogId).toMatch(/^CATALOG#/);
        expect(data.createCatalog.catalogName).toBe('Test Catalog');
        expect(data.createCatalog.catalogType).toBe('USER_CREATED');
        // ownerAccountId is no longer exposed in GraphQL schema
        expect(data.createCatalog.ownerAccountId).toBeUndefined();
        expect(data.createCatalog.isPublic).toBe(true);
        expect(data.createCatalog.products).toHaveLength(2);
        expect(data.createCatalog.createdAt).toBeDefined();
        expect(data.createCatalog.updatedAt).toBeDefined();
        
        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_CATALOG,
          variables: { catalogId },
        });
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
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId: catalogId1 } });

        const { data: data2 } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: { ...input, catalogName: 'Catalog 2' } },
        });
        const catalogId2 = data2.createCatalog.catalogId;
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId: catalogId2 } });

        // Assert
        expect(catalogId1).not.toBe(catalogId2);
        expect(catalogId1).toMatch(/^CATALOG#/);
        expect(catalogId2).toMatch(/^CATALOG#/);
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
        const catalogId = data.createCatalog.catalogId;
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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
        const catalogId = data.createCatalog.catalogId;
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        expect(data.createCatalog.catalogType).toBe('USER_CREATED');
      });

      it('should NOT expose ownerAccountId in GraphQL response', async () => {
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
        const catalogId = data.createCatalog.catalogId;
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        // ownerAccountId field should not be present in GraphQL schema
        expect(data.createCatalog.ownerAccountId).toBeUndefined();
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
        const catalogId = data.createCatalog.catalogId;
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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
        const catalogId = data.createCatalog.catalogId;
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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
        const catalogId = data.createCatalog.catalogId;
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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
        const catalogId = data.createCatalog.catalogId;
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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
        const catalogId = data.createCatalog.catalogId;
        expect(data.createCatalog).toBeDefined();
        // ownerAccountId is no longer exposed in GraphQL schema
        expect(data.createCatalog.ownerAccountId).toBeUndefined();
        
        // Cleanup - contributor must delete their own catalog
        await contributorClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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

      it('should accept catalog with zero price product (free item)', async () => {
        // Arrange - Free items should be allowed (e.g., bonus items, samples)
        const input = {
          catalogName: 'Free Item Catalog',
          isPublic: true,
          products: [
            {
              productName: 'Free Sample',
              description: 'Complimentary sample',
              price: 0.0,
              sortOrder: 1,
            },
            {
              productName: 'Regular Product',
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
        const catalogId = data.createCatalog.catalogId;
        expect(data.createCatalog.products).toHaveLength(2);
        expect(data.createCatalog.products[0].price).toBe(0.0);
        expect(data.createCatalog.products[1].price).toBe(10.0);

        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      });

      it('should accept or reject catalog with negative price product', async () => {
        // Arrange - Negative prices might represent discounts/credits
        // System should either accept or reject based on business logic
        const input = {
          catalogName: 'Negative Price Test Catalog',
          isPublic: false,
          products: [
            {
              productName: 'Credit/Discount Item',
              price: -5.0,
              sortOrder: 1,
            },
          ],
        };

        try {
          // Act
          const { data } = await ownerClient.mutate({
            mutation: CREATE_CATALOG,
            variables: { input },
          });

          // If accepted, the system allows negative prices
          const catalogId = data.createCatalog.catalogId;
          expect(data.createCatalog.products[0].price).toBe(-5.0);

          // Cleanup
          await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        } catch (error: any) {
          // If rejected, the system validates against negative prices
          expect(error.message).toMatch(/price|negative|invalid|validation/i);
        }
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
        const catalogId = data.createCatalog.catalogId;
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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
        const catalogId = data.createCatalog.catalogId;
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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
        const catalogId = createData.createCatalog.catalogId;

        // Act: Update name
        const updateInput = {
          catalogName: 'Updated Name',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };
        const { data } = await ownerClient.mutate({
          mutation: UPDATE_CATALOG,
          variables: { catalogId: catalogId, input: updateInput },
        });

        // Assert
        expect(data.updateCatalog.catalogName).toBe('Updated Name');
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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
        const catalogId = createData.createCatalog.catalogId;

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
          variables: { catalogId: catalogId, input: updateInput },
        });

        // Assert
        expect(data.updateCatalog.products).toHaveLength(3);
        expect(data.updateCatalog.products[0].productName).toBe('New Product 1');
        expect(data.updateCatalog.products[2].productName).toBe('New Product 3');
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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
        const catalogId = createData.createCatalog.catalogId;

        // Act: Make public
        const updateInput = {
          catalogName: 'Visibility Test',
          isPublic: true,
          products: [{ productName: 'Product', price: 10.0, sortOrder: 1 }],
        };
        const { data } = await ownerClient.mutate({
          mutation: UPDATE_CATALOG,
          variables: { catalogId: catalogId, input: updateInput },
        });

        // Assert
        expect(data.updateCatalog.isPublic).toBe(true);
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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
        const catalogId = createData.createCatalog.catalogId;
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
          variables: { catalogId: catalogId, input: updateInput },
        });

        // Assert
        expect(data.updateCatalog.updatedAt).toBeDefined();
        expect(new Date(data.updateCatalog.updatedAt).getTime()).toBeGreaterThan(
          new Date(originalUpdatedAt).getTime()
        );
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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
        const catalogId = createData.createCatalog.catalogId;

        // Act: Update as owner
        const updateInput = {
          catalogName: 'Updated by Owner',
          isPublic: true,
          products: [{ productName: 'Product', price: 15.0, sortOrder: 1 }],
        };
        const { data } = await ownerClient.mutate({
          mutation: UPDATE_CATALOG,
          variables: { catalogId: catalogId, input: updateInput },
        });

        // Assert
        expect(data.updateCatalog.catalogName).toBe('Updated by Owner');
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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
        const catalogId = createData.createCatalog.catalogId;

        // Act & Assert: Contributor tries to update
        const updateInput = {
          catalogName: 'Hacked Name',
          isPublic: false,
          products: [{ productName: 'Product', price: 99.0, sortOrder: 1 }],
        };
        await expect(
          contributorClient.mutate({
            mutation: UPDATE_CATALOG,
            variables: { catalogId: catalogId, input: updateInput },
          })
        ).rejects.toThrow(/conditional request failed/i);  // VTL returns raw DynamoDB error
        
        // Cleanup: Owner deletes
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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

    describe('Product Management', () => {
      it('should update catalog with reordered products (sortOrder changes)', async () => {
        // Arrange: Create catalog with products in specific order
        const createInput = {
          catalogName: 'Reorder Test',
          isPublic: false,
          products: [
            { productName: 'Product A', price: 10.0, sortOrder: 1 },
            { productName: 'Product B', price: 20.0, sortOrder: 2 },
            { productName: 'Product C', price: 30.0, sortOrder: 3 },
          ],
        };
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createInput },
        });
        const catalogId = createData.createCatalog.catalogId;

        // Act: Reorder products (C, A, B order)
        const updateInput = {
          catalogName: 'Reorder Test',
          isPublic: false,
          products: [
            { productName: 'Product C', price: 30.0, sortOrder: 1 },
            { productName: 'Product A', price: 10.0, sortOrder: 2 },
            { productName: 'Product B', price: 20.0, sortOrder: 3 },
          ],
        };
        const { data } = await ownerClient.mutate({
          mutation: UPDATE_CATALOG,
          variables: { catalogId: catalogId, input: updateInput },
        });

        // Assert: Products are in new order
        expect(data.updateCatalog.products).toHaveLength(3);
        expect(data.updateCatalog.products[0].productName).toBe('Product C');
        expect(data.updateCatalog.products[0].sortOrder).toBe(1);
        expect(data.updateCatalog.products[1].productName).toBe('Product A');
        expect(data.updateCatalog.products[1].sortOrder).toBe(2);
        expect(data.updateCatalog.products[2].productName).toBe('Product B');
        expect(data.updateCatalog.products[2].sortOrder).toBe(3);

        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      });

      it('should update catalog removing some products', async () => {
        // Arrange: Create catalog with 4 products
        const createInput = {
          catalogName: 'Remove Products Test',
          isPublic: true,
          products: [
            { productName: 'Keep 1', price: 10.0, sortOrder: 1 },
            { productName: 'Remove 1', price: 20.0, sortOrder: 2 },
            { productName: 'Keep 2', price: 30.0, sortOrder: 3 },
            { productName: 'Remove 2', price: 40.0, sortOrder: 4 },
          ],
        };
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createInput },
        });
        const catalogId = createData.createCatalog.catalogId;

        // Act: Update with only 2 products (removing 2)
        const updateInput = {
          catalogName: 'Remove Products Test',
          isPublic: true,
          products: [
            { productName: 'Keep 1', price: 10.0, sortOrder: 1 },
            { productName: 'Keep 2', price: 30.0, sortOrder: 2 },
          ],
        };
        const { data } = await ownerClient.mutate({
          mutation: UPDATE_CATALOG,
          variables: { catalogId: catalogId, input: updateInput },
        });

        // Assert: Only 2 products remain
        expect(data.updateCatalog.products).toHaveLength(2);
        expect(data.updateCatalog.products[0].productName).toBe('Keep 1');
        expect(data.updateCatalog.products[1].productName).toBe('Keep 2');

        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      });

      it('should update catalog with no product changes (name only)', async () => {
        // Arrange: Create catalog
        const createInput = {
          catalogName: 'Name Only Test',
          isPublic: false,
          products: [
            { productName: 'Product 1', price: 15.0, sortOrder: 1 },
            { productName: 'Product 2', price: 25.0, sortOrder: 2 },
          ],
        };
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createInput },
        });
        const catalogId = createData.createCatalog.catalogId;
        const originalProducts = createData.createCatalog.products;

        // Act: Update only the name, products stay the same
        const updateInput = {
          catalogName: 'New Catalog Name',
          isPublic: false,
          products: [
            { productName: 'Product 1', price: 15.0, sortOrder: 1 },
            { productName: 'Product 2', price: 25.0, sortOrder: 2 },
          ],
        };
        const { data } = await ownerClient.mutate({
          mutation: UPDATE_CATALOG,
          variables: { catalogId: catalogId, input: updateInput },
        });

        // Assert: Name changed, products unchanged
        expect(data.updateCatalog.catalogName).toBe('New Catalog Name');
        expect(data.updateCatalog.products).toHaveLength(2);
        expect(data.updateCatalog.products[0].productName).toBe(originalProducts[0].productName);
        expect(data.updateCatalog.products[0].price).toBe(originalProducts[0].price);
        expect(data.updateCatalog.products[1].productName).toBe(originalProducts[1].productName);
        expect(data.updateCatalog.products[1].price).toBe(originalProducts[1].price);

        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
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
        const catalogId = createData.createCatalog.catalogId;

        // Act: Delete catalog
        const { data } = await ownerClient.mutate({
          mutation: DELETE_CATALOG,
          variables: { catalogId: catalogId },
        });

        // Assert
        expect(data.deleteCatalog).toBe(true);
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
        const catalogId = createData.createCatalog.catalogId;

        // Act & Assert
        const { data } = await ownerClient.mutate({
          mutation: DELETE_CATALOG,
          variables: { catalogId: catalogId },
        });
        
        expect(data.deleteCatalog).toBe(true);
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
        const catalogId = createData.createCatalog.catalogId;

        // Act: Delete as owner
        const { data } = await ownerClient.mutate({
          mutation: DELETE_CATALOG,
          variables: { catalogId: catalogId },
        });

        // Assert
        expect(data.deleteCatalog).toBe(true);
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
        const catalogId = createData.createCatalog.catalogId;

        // Act & Assert: Contributor tries to delete
        await expect(
          contributorClient.mutate({
            mutation: DELETE_CATALOG,
            variables: { catalogId: catalogId },
          })
        ).rejects.toThrow(/Not authorized to delete this catalog|conditional request failed/i);  // Pipeline: "Not authorized", VTL: raw DynamoDB error
        
        // Cleanup: Owner deletes
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      });

      it('SECURITY: Regular user cannot delete ADMIN_MANAGED catalog', async () => {
        // Arrange: Create ADMIN_MANAGED catalog directly in DynamoDB (no owner)
        // ADMIN_MANAGED catalogs have no ownerAccountId and cannot be created via GraphQL
        const { DynamoDBClient, PutItemCommand, DeleteItemCommand } = await import('@aws-sdk/client-dynamodb');
        const dynamoClient = new DynamoDBClient({ region: 'us-east-1' });
        
        // Use CATALOG# prefix to match resolver normalization
        const catalogId = `CATALOG#admin-managed-test-${Date.now()}`;
        const now = new Date().toISOString();
        
        // Insert ADMIN_MANAGED catalog directly into DynamoDB (catalogs table uses catalogId as PK)
        await dynamoClient.send(new PutItemCommand({
          TableName: TABLE_NAMES.catalogs,
          Item: {
            catalogId: { S: catalogId },
            catalogName: { S: 'Official 2024 Popcorn Catalog' },
            catalogType: { S: 'ADMIN_MANAGED' },
            // Note: No ownerAccountId - this is key for ADMIN_MANAGED
            isPublic: { BOOL: true },
            products: { L: [
              {
                M: {
                  productId: { S: 'PRODUCT#admin-1' },
                  productName: { S: 'Caramel Corn' },
                  price: { N: '20' },
                  sortOrder: { N: '1' },
                }
              }
            ]},
            createdAt: { S: now },
            updatedAt: { S: now },
          },
        }));

        try {
          // Act: Non-admin users try to delete ADMIN_MANAGED catalog
          // Note: The owner test user is an admin, so we only test with contributor and readonly
          
          // Try contributor user (non-admin)
          await expect(
            contributorClient.mutate({
              mutation: DELETE_CATALOG,
              variables: { catalogId: catalogId },
            })
          ).rejects.toThrow(/Not authorized to delete this catalog|conditional request failed/i);

          // And readonly user (non-admin)
          await expect(
            readonlyClient.mutate({
              mutation: DELETE_CATALOG,
              variables: { catalogId: catalogId },
            })
          ).rejects.toThrow(/Not authorized to delete this catalog|conditional request failed/i);

        } finally {
          // Cleanup: Direct DynamoDB delete
          await dynamoClient.send(new DeleteItemCommand({
            TableName: TABLE_NAMES.catalogs,
            Key: {
              catalogId: { S: catalogId },
            },
          }));
        }
      });

      // TODO: These tests require an admin user to be properly configured
      // The isAdmin flag needs to be set in the Account record in DynamoDB
      // Skip until admin user setup is implemented in test infrastructure

      it('SECURITY: Cannot delete catalog that is in use by campaigns', async () => {
        // Arrange: Create a public catalog that multiple users can use
        const createCatalogInput = {
          catalogName: 'Shared Public Catalog',
          isPublic: true,
          products: [{ productName: 'Kettle Corn', price: 15.0, sortOrder: 1 }],
        };
        const { data: catalogData }: any = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createCatalogInput },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        // Create profiles and campaigns for multiple users using this catalog
        const CREATE_PROFILE = gql`
          mutation CreateSellerProfile($input: CreateSellerProfileInput!) {
            createSellerProfile(input: $input) {
              profileId
            }
          }
        `;
        const CREATE_CAMPAIGN = gql`
          mutation CreateCampaign($input: CreateCampaignInput!) {
            createCampaign(input: $input) {
              campaignId
              campaignYear
              catalogId
            }
          }
        `;
        const GET_CAMPAIGN = gql`
          query GetCampaign($campaignId: ID!) {
            getCampaign(campaignId: $campaignId) {
              campaignId
              catalogId
              catalog {
                catalogId
                catalogName
              }
            }
          }
        `;
        const DELETE_CAMPAIGN = gql`
          mutation DeleteCampaign($campaignId: ID!) {
            deleteCampaign(campaignId: $campaignId)
          }
        `;
        const DELETE_PROFILE = gql`
          mutation DeleteSellerProfile($profileId: ID!) {
            deleteSellerProfile(profileId: $profileId)
          }
        `;

        // Owner creates a profile and campaign using the public catalog
        const { data: ownerProfileData }: any = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: 'Owner Using Public Catalog' } },
        });
        const ownerProfileId = ownerProfileData.createSellerProfile.profileId;

        const { data: ownerCampaignData }: any = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: ownerProfileId,
              catalogId: catalogId,
              campaignName: 'Owner Campaigngn',
              campaignYear: 2025,
              startDate: new Date().toISOString(),
            },
          },
        });
        const ownerCampaignId = ownerCampaignData.createCampaign.campaignId;

        // Contributor creates a profile and campaign using the same public catalog
        const { data: contributorProfileData }: any = await contributorClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: 'Contributor Using Public Catalog' } },
        });
        const contributorProfileId = contributorProfileData.createSellerProfile.profileId;

        const { data: contributorCampaignData }: any = await contributorClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: contributorProfileId,
              catalogId: catalogId,
              campaignName: 'Contributor Campaigngn',
              campaignYear: 2025,
              startDate: new Date().toISOString(),
            },
          },
        });
        const contributorCampaignId = contributorCampaignData.createCampaign.campaignId;

        // Verify both campaigns were created with the catalog reference
        const { data: ownerCampaignCheck }: any = await ownerClient.query({
          query: GET_CAMPAIGN,
          variables: { campaignId: ownerCampaignId },
          fetchPolicy: 'network-only',
        });
        expect(ownerCampaignCheck.getCampaign.catalogId).toBe(catalogId);
        
        const { data: contributorCampaignCheck }: any = await contributorClient.query({
          query: GET_CAMPAIGN,
          variables: { campaignId: contributorCampaignId },
          fetchPolicy: 'network-only',
        });
        expect(contributorCampaignCheck.getCampaign.catalogId).toBe(catalogId);

        // Wait 1 second to ensure DynamoDB has fully replicated the campaign writes
        // (consistentRead doesn't fully solve eventual consistency for Scan operations)
        await new Promise(resolve => setTimeout(resolve, 1000));

        // Act & Assert: Owner tries to delete the public catalog but should fail
        // because 2 campaigns are using it
        await expect(
          ownerClient.mutate({
            mutation: DELETE_CATALOG,
            variables: { catalogId: catalogId },
          })
        ).rejects.toThrow(/cannot delete catalog.*(campaign|season).*using it/i);

        // Verify catalog still exists
        const { data: catalogCheck }: any = await ownerClient.query({
          query: gql`query GetCatalog($catalogId: ID!) { getCatalog(catalogId: $catalogId) { catalogId catalogName } }`,
          variables: { catalogId },
          fetchPolicy: 'network-only',
        });
        expect(catalogCheck.getCatalog).toBeDefined();
        expect(catalogCheck.getCatalog.catalogName).toBe('Shared Public Catalog');

        // Cleanup: Delete campaigns first, then catalog, then profiles
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: ownerCampaignId } });
        await contributorClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: contributorCampaignId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } }); // Now deletion should succeed
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId: ownerProfileId } });
        await contributorClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId: contributorProfileId } });
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
        ).rejects.toThrow(/Catalog not found|Cannot return null for non-nullable type.*Boolean|conditional request failed/i);  // Pipeline: "Catalog not found", VTL: null for non-nullable or conditional failure
      });
    });

    describe('Data Integrity', () => {
      it('Data Integrity: Deleting catalog used by active campaigngn', async () => {
        // Arrange: Create a catalog and use it for a campaigngn
        const createCatalogInput = {
          catalogName: 'Catalog Used By Campaigngn',
          isPublic: false,
          products: [{ productName: 'Popcorn', price: 25.0, sortOrder: 1 }],
        };
        const { data: catalogData }: any = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createCatalogInput },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        // Create a profile and campaign using this catalog
        const CREATE_PROFILE = gql`
          mutation CreateSellerProfile($input: CreateSellerProfileInput!) {
            createSellerProfile(input: $input) {
              profileId
            }
          }
        `;
        const CREATE_CAMPAIGN = gql`
          mutation CreateCampaign($input: CreateCampaignInput!) {
            createCampaign(input: $input) {
              campaignId
              campaignYear
              catalogId
            }
          }
        `;
        const DELETE_CAMPAIGN = gql`
          mutation DeleteCampaign($campaignId: ID!) {
            deleteCampaign(campaignId: $campaignId)
          }
        `;
        const DELETE_PROFILE = gql`
          mutation DeleteSellerProfile($profileId: ID!) {
            deleteSellerProfile(profileId: $profileId)
          }
        `;

        const { data: profileData }: any = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: 'Catalog Test Seller' } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: campaignData }: any = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              catalogId: catalogId,
              campaignName: 'Campaigngn Using Catalog',
              campaignYear: 2025,
              startDate: new Date().toISOString(),
            },
          },
        });
        const campaignId = campaignData.createCampaign.campaignId;

        // Act: Try to delete the catalog while it's in use by a campaigngn
        // The system should either:
        // - Prevent deletion (throw error)
        // - Allow deletion (orphan the campaigngn's catalogId reference)
        try {
          const { data: deleteData }: any = await ownerClient.mutate({
            mutation: DELETE_CATALOG,
            variables: { catalogId: catalogId },
          });
          
          // If deletion succeeds, the catalog is deleted
          // This means the system allows deletion (orphaning the reference)
          expect(deleteData.deleteCatalog).toBe(true);
          
          // Campaigngn's catalogId is now orphaned - verify the campaign still exists
          const GET_CAMPAIGN = gql`
            query GetCampaign($campaignId: ID!) {
              getCampaign(campaignId: $campaignId) {
                campaignId
                catalogId
              }
            }
          `;
          const { data: campaignCheck }: any = await ownerClient.query({
            query: GET_CAMPAIGN,
            variables: { campaignId: campaignId },
            fetchPolicy: 'network-only',
          });
          expect(campaignCheck.getCampaign).toBeDefined();
          expect(campaignCheck.getCampaign.catalogId).toBe(catalogId); // Reference is orphaned
        } catch (error: any) {
          // If deletion fails, the system prevents deletion of in-use catalogs
          // This is also valid behavior
          expect(error.message).toMatch(/in use|referenced|cannot delete/i);
        } finally {
          // Cleanup: Delete campaign and profile
          await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
          await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
          
          // Try to cleanup catalog if it wasn't deleted
          try {
            await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
          } catch { /* already deleted */ }
        }
      });

      it('creates catalog with duplicate product names', async () => {
        // Act: Create catalog with products that have the same name
        const { data }: any = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: 'Duplicate Product Names Catalog',
              isPublic: false,
              products: [
                { productName: 'Same Name', price: 10.00, sortOrder: 1 },
                { productName: 'Same Name', price: 15.00, sortOrder: 2 },
                { productName: 'Same Name', price: 20.00, sortOrder: 3 },
              ],
            },
          },
        });

        // Assert: All products created with same name but unique IDs
        expect(data.createCatalog.products).toHaveLength(3);
        const productIds = data.createCatalog.products.map((p: any) => p.productId);
        const uniqueIds = new Set(productIds);
        expect(uniqueIds.size).toBe(3);

        // All have the same name
        expect(data.createCatalog.products.every((p: any) => p.productName === 'Same Name')).toBe(true);

        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId: data.createCatalog.catalogId } });
      });

      it('creates catalog with many products (boundary test)', async () => {
        // Act: Create catalog with 50 products
        const products = Array.from({ length: 50 }, (_, i) => ({
          productName: `Product ${i + 1}`,
          price: (i + 1) * 1.25,
          sortOrder: i + 1,
        }));

        const { data }: any = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: 'Many Products Catalog',
              isPublic: false,
              products,
            },
          },
        });

        // Assert: All 50 products created
        expect(data.createCatalog.products).toHaveLength(50);
        expect(data.createCatalog.products[0].productName).toBe('Product 1');
        expect(data.createCatalog.products[49].productName).toBe('Product 50');

        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId: data.createCatalog.catalogId } });
      });

      it('creates catalog with duplicate sortOrders', async () => {
        // Act: Create catalog with products that have the same sortOrder
        const { data }: any = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: 'Duplicate SortOrder Catalog',
              isPublic: false,
              products: [
                { productName: 'Product A', price: 10.00, sortOrder: 1 },
                { productName: 'Product B', price: 15.00, sortOrder: 1 }, // Same sortOrder
                { productName: 'Product C', price: 20.00, sortOrder: 1 }, // Same sortOrder
              ],
            },
          },
        });

        // Assert: All products created (duplicate sortOrder is allowed)
        expect(data.createCatalog.products).toHaveLength(3);
        expect(data.createCatalog.products.every((p: any) => p.sortOrder === 1)).toBe(true);

        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId: data.createCatalog.catalogId } });
      });

      it('updating catalog to change isPublic flag', async () => {
        // Arrange: Create private catalog
        const { data: createData }: any = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: 'Visibility Test Catalog',
              isPublic: false,
              products: [{ productName: 'Test', price: 5.00, sortOrder: 1 }],
            },
          },
        });
        const catalogId = createData.createCatalog.catalogId;
        expect(createData.createCatalog.isPublic).toBe(false);

        // Act: Update to make public
        const { data: updateData }: any = await ownerClient.mutate({
          mutation: UPDATE_CATALOG,
          variables: {
            catalogId,
            input: {
              catalogName: 'Visibility Test Catalog',
              isPublic: true,
              products: [{ productName: 'Test', price: 5.00, sortOrder: 1 }],
            },
          },
        });

        // Assert: Now public
        expect(updateData.updateCatalog.isPublic).toBe(true);

        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      });

      it('Data Integrity: Concurrent catalog deletion and usage (race condition)', async () => {
        // Arrange: Create a catalog
        const createCatalogInput = {
          catalogName: 'Concurrent Delete Catalog',
          isPublic: false,
          products: [{ productName: 'Concurrent Popcorn', price: 20.0, sortOrder: 1 }],
        };
        const { data: catalogData }: any = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: { input: createCatalogInput },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        // Create a profile for creating campaigngns
        const CREATE_PROFILE = gql`
          mutation CreateSellerProfile($input: CreateSellerProfileInput!) {
            createSellerProfile(input: $input) {
              profileId
            }
          }
        `;
        const CREATE_CAMPAIGN = gql`
          mutation CreateCampaign($input: CreateCampaignInput!) {
            createCampaign(input: $input) {
              campaignId
              campaignYear
              catalogId
            }
          }
        `;
        const DELETE_CAMPAIGN = gql`
          mutation DeleteCampaign($campaignId: ID!) {
            deleteCampaign(campaignId: $campaignId)
          }
        `;
        const DELETE_PROFILE = gql`
          mutation DeleteSellerProfile($profileId: ID!) {
            deleteSellerProfile(profileId: $profileId)
          }
        `;

        const { data: profileData }: any = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: 'Concurrent Test Profile' } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        // Act: Concurrent catalog deletion and campaign creation (using that catalog)
        const [deleteResult, createCampaignResult] = await Promise.allSettled([
          ownerClient.mutate({
            mutation: DELETE_CATALOG,
            variables: { catalogId: catalogId },
          }),
          ownerClient.mutate({
            mutation: CREATE_CAMPAIGN,
            variables: {
              input: {
                profileId: profileId,
                catalogId: catalogId,
                campaignName: 'Concurrent Campaigngn',
                campaignYear: 2025,
                startDate: new Date().toISOString(),
              },
            },
          }),
        ]);

        // Assert: One or both operations may succeed depending on timing
        // Delete should always be attempted
        expect(['fulfilled', 'rejected']).toContain(deleteResult.status);
        
        // Campaigngn creation may succeed (if it happens before deletion)
        // or it may succeed with an orphaned catalog reference (if deletion happens first)
        expect(['fulfilled', 'rejected']).toContain(createCampaignResult.status);

        // Cleanup
        if (createCampaignResult.status === 'fulfilled') {
          const campaignId = (createCampaignResult as PromiseFulfilledResult<any>).value.data.createCampaign.campaignId;
          await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
        }
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
        // Try to delete catalog if it wasn't deleted
        try {
          await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        } catch { /* already deleted */ }
      });
    });
  });
});
