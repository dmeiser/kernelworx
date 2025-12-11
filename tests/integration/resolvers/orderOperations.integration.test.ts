import '../setup.ts';
import { describe, test, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, NormalizedCacheObject, gql } from '@apollo/client';
import { createAuthenticatedClient } from '../setup/apolloClient';

/**
 * Integration tests for Order Operations (createOrder, updateOrder, deleteOrder)
 * 
 * Test Data Setup:
 * - TEST_OWNER_EMAIL: Owner of profile/season (can create/update/delete orders)
 * - TEST_CONTRIBUTOR_EMAIL: Has WRITE access (can create/update/delete orders)
 * - TEST_READONLY_EMAIL: Has READ access (cannot modify orders)
 * 
 * Note: These tests create their own test data (profile, season, catalog)
 * and clean up after themselves.
 */

// GraphQL Mutations for setup
const CREATE_SELLER_PROFILE = gql`
  mutation CreateSellerProfile($input: CreateSellerProfileInput!) {
    createSellerProfile(input: $input) {
      profileId
      sellerName
      ownerAccountId
    }
  }
`;

const CREATE_CATALOG = gql`
  mutation CreateCatalog($input: CreateCatalogInput!) {
    createCatalog(input: $input) {
      catalogId
      catalogName
      products {
        productId
        productName
        price
      }
    }
  }
`;

const CREATE_SEASON = gql`
  mutation CreateSeason($input: CreateSeasonInput!) {
    createSeason(input: $input) {
      seasonId
      seasonName
      catalogId
      startDate
      endDate
    }
  }
`;

const GET_SEASON = gql`
  query GetSeason($seasonId: ID!) {
    getSeason(seasonId: $seasonId) {
      seasonId
      catalogId
      seasonName
    }
  }
`;


const SHARE_PROFILE_DIRECT = gql`
  mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
    shareProfileDirect(input: $input) {
      shareId
      profileId
      targetAccountId
      permissions
    }
  }
`;

// GraphQL Mutations for tests
const CREATE_ORDER = gql`
  mutation CreateOrder($input: CreateOrderInput!) {
    createOrder(input: $input) {
      orderId
      profileId
      seasonId
      customerName
      customerPhone
      orderDate
      paymentMethod
      lineItems {
        productId
        productName
        quantity
        pricePerUnit
        subtotal
      }
      totalAmount
      createdAt
    }
  }
`;

const UPDATE_ORDER = gql`
  mutation UpdateOrder($input: UpdateOrderInput!) {
    updateOrder(input: $input) {
      orderId
      customerName
      customerPhone
      paymentMethod
      lineItems {
        productId
        productName
        quantity
        pricePerUnit
        subtotal
      }
      totalAmount
      updatedAt
    }
  }
`;

const DELETE_ORDER = gql`
  mutation DeleteOrder($orderId: ID!) {
    deleteOrder(orderId: $orderId)
  }
`;

describe('Order Operations Integration Tests', () => {
  let ownerClient: ApolloClient<NormalizedCacheObject>;
  let contributorClient: ApolloClient<NormalizedCacheObject>;
  let readonlyClient: ApolloClient<NormalizedCacheObject>;

  // Test data IDs (created during setup)
  let testProfileId: string;
  let testSeasonId: string;
  let testCatalogId: string;
  let testProductId: string;

  let createdOrderIds: string[] = [];

  beforeAll(async () => {
    // Authenticate all test users
    const ownerAuth = await createAuthenticatedClient('owner');
    const contributorAuth = await createAuthenticatedClient('contributor');
    const readonlyAuth = await createAuthenticatedClient('readonly');

    ownerClient = ownerAuth.client;
    contributorClient = contributorAuth.client;
    readonlyClient = readonlyAuth.client;

    // Create test data
    console.log('Creating test profile, catalog, and season...');
    
    // 1. Create profile
    const { data: profileData } = await ownerClient.mutate({
      mutation: CREATE_SELLER_PROFILE,
      variables: {
        input: {
          sellerName: 'Order Test Seller',
        },
      },
    });
    testProfileId = profileData.createSellerProfile.profileId;

    // 2. Create catalog with products
    const { data: catalogData } = await ownerClient.mutate({
      mutation: CREATE_CATALOG,
      variables: {
        input: {
          catalogName: 'Order Test Catalog',
          isPublic: false,
          products: [
            {
              productName: 'Test Popcorn',
              description: 'Test product for integration tests',
              price: 10.00,
              sortOrder: 1,
            },
          ],
        },
      },
    });
    testCatalogId = catalogData.createCatalog.catalogId;
    testProductId = catalogData.createCatalog.products[0].productId;

    // 3. Create season
    const { data: seasonData } = await ownerClient.mutate({
      mutation: CREATE_SEASON,
      variables: {
        input: {
          profileId: testProfileId,
          seasonName: 'Order Test Season',
          startDate: new Date('2025-01-01T00:00:00Z').toISOString(),
          endDate: new Date('2025-12-31T23:59:59Z').toISOString(),
          catalogId: testCatalogId,
        },
      },
    });
    testSeasonId = seasonData.createSeason.seasonId;

    // Verify season has catalogId before proceeding (GSI5 propagation)
    let retries = 0;
    while (retries < 5) {
      try {
        const { data: seasonVerify } = await ownerClient.query({
          query: GET_SEASON,
          variables: { seasonId: testSeasonId },
          fetchPolicy: 'network-only', // Bypass cache
        });
        if (seasonVerify?.getSeason?.catalogId) {
          break; // Season has catalogId, proceed
        }
      } catch (e) {
        // Season not found yet in GSI, retry
      }
      await new Promise(resolve => setTimeout(resolve, 500)); // Wait 500ms
      retries++;
    }

    // 4. Share profile with contributor (WRITE)
    await ownerClient.mutate({
      mutation: SHARE_PROFILE_DIRECT,
      variables: {
        input: {
          profileId: testProfileId,
          targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL!,
          permissions: ['READ', 'WRITE'],
        },
      },
    });

    // 5. Share profile with readonly (READ)
    await ownerClient.mutate({
      mutation: SHARE_PROFILE_DIRECT,
      variables: {
        input: {
          profileId: testProfileId,
          targetAccountEmail: process.env.TEST_READONLY_EMAIL!,
          permissions: ['READ'],
        },
      },
    });

    console.log(`Test data created: Profile=${testProfileId}, Season=${testSeasonId}, Product=${testProductId}`);
  }, 30000);

  afterAll(async () => {
    // Cleanup: Delete all test orders
    for (const orderId of createdOrderIds) {
      try {
        await ownerClient.mutate({
          mutation: DELETE_ORDER,
          variables: { orderId },
        });
      } catch (error) {
        console.error(`Failed to delete order ${orderId}:`, error);
      }
    }
    console.log(`Cleaned up ${createdOrderIds.length} test orders`);
  });

  describe('createOrder', () => {
    test('creates order with valid line items', async () => {
      const input = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'John Doe',
        customerPhone: '+15551234567',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 2,
          },
        ],
        notes: 'Test order from integration test',
      };

      const { data } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input },
      });

      expect(data.createOrder).toBeDefined();
      expect(data.createOrder.orderId).toBeDefined();
      expect(data.createOrder.customerName).toBe('John Doe');
      expect(data.createOrder.paymentMethod).toBe('CASH');
      expect(data.createOrder.lineItems).toHaveLength(1);
      expect(data.createOrder.lineItems[0].quantity).toBe(2);
      expect(data.createOrder.lineItems[0].productName).toBe('Test Popcorn');
      expect(data.createOrder.lineItems[0].pricePerUnit).toBe(10.00);
      expect(data.createOrder.totalAmount).toBe(20.00);

      // Save for cleanup
      createdOrderIds.push(data.createOrder.orderId);
    }, 10000);

    test('contributor with WRITE access can create order', async () => {
      const input = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'Jane Smith',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CHECK',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data } = await contributorClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input },
      });

      expect(data.createOrder).toBeDefined();
      expect(data.createOrder.customerName).toBe('Jane Smith');

      // Save for cleanup
      createdOrderIds.push(data.createOrder.orderId);
    }, 10000);

    test('rejects order with non-existent product', async () => {
      const input = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'Test Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: 'PRODUCT#non-existent-product',
            quantity: 1,
          },
        ],
      };

      await expect(
        ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: { input },
        })
      ).rejects.toThrow(/not found|does not exist/i);
    }, 10000);

    test('rejects order with invalid season', async () => {
      const input = {
        profileId: testProfileId,
        seasonId: 'SEASON#non-existent-season',
        customerName: 'Test Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      await expect(
        ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: { input },
        })
      ).rejects.toThrow(/not found|does not exist|invalid/i);
    }, 10000);
  });

  describe('updateOrder', () => {
    test('updates order customer name', async () => {
      // First create an order
      const createInput = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'Original Name',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;
      createdOrderIds.push(orderId);

      // Now update it
      const updateInput = {
        orderId,
        customerName: 'Updated Name',
      };

      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_ORDER,
        variables: { input: updateInput },
      });

      expect(updateData.updateOrder.customerName).toBe('Updated Name');
      expect(updateData.updateOrder.orderId).toBe(orderId);
    }, 10000);

    test('contributor with WRITE access can update order', async () => {
      // Owner creates order
      const createInput = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'Original Name',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;
      createdOrderIds.push(orderId);

      // Contributor updates it
      const updateInput = {
        orderId,
        customerName: 'Updated by Contributor',
      };

      const { data: updateData } = await contributorClient.mutate({
        mutation: UPDATE_ORDER,
        variables: { input: updateInput },
      });

      expect(updateData.updateOrder.customerName).toBe('Updated by Contributor');
    }, 10000);

    test('rejects update with non-existent orderId', async () => {
      const updateInput = {
        orderId: 'ORDER#non-existent-order',
        customerName: 'Updated Name',
      };

      await expect(
        ownerClient.mutate({
          mutation: UPDATE_ORDER,
          variables: { input: updateInput },
        })
      ).rejects.toThrow(/not found|does not exist/i);
    }, 10000);
  });

  describe('deleteOrder', () => {
    test('deletes existing order', async () => {
      // Create an order first
      const createInput = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'To Be Deleted',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;

      // Delete it
      const { data: deleteData } = await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId },
      });

      expect(deleteData.deleteOrder).toBe(true);
      
      // Don't add to cleanup list since it's already deleted
    }, 10000);

    test('contributor with WRITE access can delete order', async () => {
      // Owner creates order
      const createInput = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'To Be Deleted by Contributor',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;

      // Contributor deletes it
      const { data: deleteData } = await contributorClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId },
      });

      expect(deleteData.deleteOrder).toBe(true);
    }, 10000);

    test('returns true for non-existent order (idempotent)', async () => {
      const { data } = await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId: 'ORDER#non-existent-order' },
      });

      expect(data.deleteOrder).toBe(true);
    }, 10000);
  });

  /**
   * Authorization Tests - Bug #13
   * 
   * Status: FIXED - VerifyProfileWriteAccessFn now properly blocks readonly users
   */
  describe('createOrder authorization', () => {
    test('readonly user cannot create order', async () => {
      const input = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'Read Only Test',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      await expect(
        readonlyClient.mutate({
          mutation: CREATE_ORDER,
          variables: { input },
        })
      ).rejects.toThrow(/forbidden|not authorized|unauthorized/i);
    }, 10000);
  });

  describe('updateOrder authorization', () => {
    test('readonly user cannot update order', async () => {
      // Owner creates order
      const createInput = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'Original Name',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;
      createdOrderIds.push(orderId);

      // Readonly tries to update
      await expect(
        readonlyClient.mutate({
          mutation: UPDATE_ORDER,
          variables: {
            input: {
              orderId,
              customerName: 'Readonly Update Attempt',
            },
          },
        })
      ).rejects.toThrow(/forbidden|not authorized|unauthorized/i);
    }, 10000);
  });

  describe('deleteOrder authorization', () => {
    test('readonly user cannot delete order', async () => {
      // Owner creates order
      const createInput = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'To Be Protected',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;
      createdOrderIds.push(orderId);

      // Readonly tries to delete
      await expect(
        readonlyClient.mutate({
          mutation: DELETE_ORDER,
          variables: { orderId },
        })
      ).rejects.toThrow(/forbidden|not authorized|unauthorized/i);
    }, 10000);
  });

  /**
   * Input Validation Tests - Bug #15
   * 
   * KNOWN BUG: createOrder accepts invalid quantities.
   * Empty line items, zero, and negative quantities are all allowed.
   * 
   * Status: FIXED - Input validation added to CreateOrderFn
   */
  describe('createOrder input validation', () => {
    test('rejects order with empty line items', async () => {
      const input = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'Test Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [],
      };

      await expect(
        ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: { input },
        })
      ).rejects.toThrow();
    }, 10000);

    test('rejects order with zero quantity', async () => {
      const input = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'Test Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 0,
          },
        ],
      };

      await expect(
        ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: { input },
        })
      ).rejects.toThrow();
    }, 10000);

    test('rejects order with negative quantity', async () => {
      const input = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'Test Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: -5,
          },
        ],
      };

      await expect(
        ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: { input },
        })
      ).rejects.toThrow();
    }, 10000);
  });

  /**
   * updateOrder Input Validation Tests - Bug #16
   * 
   * Status: FIXED - Conditional catalog lookup added to UpdateOrder pipeline
   */
  describe('updateOrder input validation', () => {
    test('updates order with new line items', async () => {
      // Create an order first
      const createInput = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'Original Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;
      createdOrderIds.push(orderId);

      // Update with increased quantity
      const updateInput = {
        orderId,
        lineItems: [
          {
            productId: testProductId,
            quantity: 5,
          },
        ],
      };

      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_ORDER,
        variables: { input: updateInput },
      });

      expect(updateData.updateOrder.lineItems[0].quantity).toBe(5);
      expect(updateData.updateOrder.totalAmount).toBe(50.00); // 5 * 10.00
    }, 10000);

    test('updates order payment method', async () => {
      // Create an order first
      const createInput = {
        profileId: testProfileId,
        seasonId: testSeasonId,
        customerName: 'Payment Test',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;
      createdOrderIds.push(orderId);

      // Update payment method
      const updateInput = {
        orderId,
        paymentMethod: 'CREDIT_CARD',
      };

      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_ORDER,
        variables: { input: updateInput },
      });

      expect(updateData.updateOrder.paymentMethod).toBe('CREDIT_CARD');
    }, 10000);
  });
});
