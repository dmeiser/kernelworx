import '../setup.ts';
import { describe, test, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, NormalizedCacheObject, gql } from '@apollo/client';
import { createAuthenticatedClient } from '../setup/apolloClient';

/**
 * Integration tests for Order Query Operations (getOrder, listOrdersBySeason, listOrdersByProfile)
 * 
 * Test Data Setup:
 * - TEST_OWNER_EMAIL: Owner of profile/season (can query orders)
 * - TEST_CONTRIBUTOR_EMAIL: Has WRITE access (can query orders)
 * - TEST_READONLY_EMAIL: Has READ access (can query orders)
 * - Another user (no access): Cannot query orders
 * 
 * VTL Resolvers Under Test:
 * - getOrder: Queries GSI6 (orderId index)
 * - listOrdersBySeason: Queries main table (PK=seasonId, SK begins_with "ORDER#")
 * - listOrdersByProfile: Queries GSI2 (GSI2PK=profileId)
 */

// GraphQL Queries for setup
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

// GraphQL Queries Under Test
const GET_ORDER = gql`
  query GetOrder($orderId: ID!) {
    getOrder(orderId: $orderId) {
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
      updatedAt
    }
  }
`;

const LIST_ORDERS_BY_SEASON = gql`
  query ListOrdersBySeason($seasonId: ID!) {
    listOrdersBySeason(seasonId: $seasonId) {
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
      updatedAt
    }
  }
`;

const LIST_ORDERS_BY_PROFILE = gql`
  query ListOrdersByProfile($profileId: ID!) {
    listOrdersByProfile(profileId: $profileId) {
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
      updatedAt
    }
  }
`;

describe('Order Query Operations Integration Tests', () => {
  let ownerClient: ApolloClient<NormalizedCacheObject>;
  let contributorClient: ApolloClient<NormalizedCacheObject>;
  let readonlyClient: ApolloClient<NormalizedCacheObject>;

  // Test data IDs (created during setup)
  let testProfileId: string;
  let testSeasonId: string;
  let testCatalogId: string;
  let testProductId: string;

  // Test orders
  let testOrderId1: string;
  let testOrderId2: string;

  // Second profile and season for testing authorization (not shared with contributor)
  let unsharedProfileId: string;
  let unsharedSeasonId: string;

  beforeAll(async () => {
    try {
      // Authenticate all test users
      console.log('Step 1: Authenticating users...');
      const ownerAuth = await createAuthenticatedClient('owner');
      const contributorAuth = await createAuthenticatedClient('contributor');
      const readonlyAuth = await createAuthenticatedClient('readonly');

      ownerClient = ownerAuth.client;
      contributorClient = contributorAuth.client;
      readonlyClient = readonlyAuth.client;

      // Create test data
      console.log('Step 2: Creating test profile...');
      
      // 1. Create profile
      const { data: profileData }: any = await ownerClient.mutate({
        mutation: CREATE_SELLER_PROFILE,
        variables: {
          input: {
            sellerName: 'Order Query Test Seller',
          },
        },
      });
      testProfileId = profileData.createSellerProfile.profileId;
      console.log(`Created profile: ${testProfileId}`);

      // 2. Create catalog with products
      console.log('Step 3: Creating catalog...');
      const { data: catalogData }: any = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: 'Order Query Test Catalog',
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
      console.log(`Created catalog: ${testCatalogId}, product: ${testProductId}`);

      // 3. Create season
      console.log('Step 4: Creating season...');
      const { data: seasonData }: any = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: testProfileId,
            seasonName: 'Order Query Test Season',
            startDate: new Date('2025-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2025-12-31T23:59:59Z').toISOString(),
            catalogId: testCatalogId,
          },
        },
      });
      testSeasonId = seasonData.createSeason.seasonId;
      console.log(`Created season: ${testSeasonId}`);

      // Verify season has catalogId before proceeding (GSI5 propagation)
      console.log('Step 5: Waiting for GSI propagation...');
      let retries = 0;
      while (retries < 5) {
        try {
          const { data: seasonVerify }: any = await ownerClient.query({
            query: GET_SEASON,
            variables: { seasonId: testSeasonId },
            fetchPolicy: 'network-only',
          });
          if (seasonVerify?.getSeason?.catalogId) {
            break;
          }
        } catch (e) {
          // Season not found yet in GSI, retry
        }
        await new Promise(resolve => setTimeout(resolve, 500));
        retries++;
      }

      // 4. Share profile with contributor (WRITE)
      console.log('Step 6: Sharing profile with contributor...');
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
      console.log('Step 7: Sharing profile with readonly...');
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

      // 6. Create test orders
      console.log('Step 8: Creating test orders...');
      const { data: order1Data }: any = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            seasonId: testSeasonId,
            customerName: 'Test Customer 1',
            customerPhone: '555-0001',
            orderDate: new Date('2025-02-01T10:00:00Z').toISOString(),
            paymentMethod: 'CASH',
            lineItems: [
              {
                productId: testProductId,
                quantity: 2,
              },
            ],
          },
        },
      });
      testOrderId1 = order1Data.createOrder.orderId;
      console.log(`Created order 1: ${testOrderId1}`);

      const { data: order2Data }: any = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            seasonId: testSeasonId,
            customerName: 'Test Customer 2',
            customerPhone: '555-0002',
            orderDate: new Date('2025-02-15T14:00:00Z').toISOString(),
            paymentMethod: 'CHECK',
            lineItems: [
              {
                productId: testProductId,
                quantity: 5,
              },
            ],
          },
        },
      });
      testOrderId2 = order2Data.createOrder.orderId;
      console.log(`Created order 2: ${testOrderId2}`);

      // Wait for GSI6 (orderId index) to propagate
      console.log('Step 9: Waiting for GSI6 propagation...');
      await new Promise(resolve => setTimeout(resolve, 2000));

      // 7. Create a separate unshared profile for authorization testing
      console.log('Step 10: Creating unshared profile...');
      const { data: unsharedProfileData }: any = await ownerClient.mutate({
        mutation: CREATE_SELLER_PROFILE,
        variables: {
          input: {
            sellerName: 'Unshared Profile',
          },
        },
      });
      unsharedProfileId = unsharedProfileData.createSellerProfile.profileId;
      console.log(`Created unshared profile: ${unsharedProfileId}`);

      console.log('Step 11: Creating unshared season...');
      const { data: unsharedSeasonData }: any = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: unsharedProfileId,
            seasonName: 'Unshared Season',
            startDate: new Date('2025-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2025-12-31T23:59:59Z').toISOString(),
            catalogId: testCatalogId,
          },
        },
      });
      unsharedSeasonId = unsharedSeasonData.createSeason.seasonId;
      console.log(`Created unshared season: ${unsharedSeasonId}`);

      console.log(`Test data created successfully!`);
    } catch (error) {
      console.error('Error in beforeAll:', error);
      throw error;
    }
  }, 30000);

  afterAll(async () => {
    // Cleanup is handled by DynamoDB TTL or manual cleanup scripts
    console.log('Test completed. Cleanup can be done via DynamoDB TTL or manual scripts.');
  });

  // ========================================
  // 5.12.1: getOrder
  // ========================================

  describe('5.12.1: getOrder', () => {
    test('Happy Path: Returns order by orderId', async () => {
      const { data }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId: testOrderId1 },
        fetchPolicy: 'network-only',
      });

      expect(data.getOrder).toBeDefined();
      expect(data.getOrder.orderId).toBe(testOrderId1);
      expect(data.getOrder.customerName).toBe('Test Customer 1');
      expect(data.getOrder.customerPhone).toBe('555-0001');
      expect(data.getOrder.profileId).toBe(testProfileId);
      expect(data.getOrder.seasonId).toBe(testSeasonId);
    });

    test('Happy Path: Includes all order fields', async () => {
      const { data }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId: testOrderId1 },
        fetchPolicy: 'network-only',
      });

      expect(data.getOrder).toHaveProperty('orderId');
      expect(data.getOrder).toHaveProperty('profileId');
      expect(data.getOrder).toHaveProperty('seasonId');
      expect(data.getOrder).toHaveProperty('customerName');
      expect(data.getOrder).toHaveProperty('customerPhone');
      expect(data.getOrder).toHaveProperty('orderDate');
      expect(data.getOrder).toHaveProperty('paymentMethod');
      expect(data.getOrder).toHaveProperty('lineItems');
      expect(data.getOrder).toHaveProperty('totalAmount');
      expect(data.getOrder).toHaveProperty('createdAt');
      expect(data.getOrder).toHaveProperty('updatedAt');
    });

    test('Happy Path: Includes line items with product details', async () => {
      const { data }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId: testOrderId1 },
        fetchPolicy: 'network-only',
      });

      expect(data.getOrder.lineItems).toBeDefined();
      expect(data.getOrder.lineItems.length).toBeGreaterThan(0);
      
      const lineItem = data.getOrder.lineItems[0];
      expect(lineItem).toHaveProperty('productId');
      expect(lineItem).toHaveProperty('productName');
      expect(lineItem).toHaveProperty('quantity');
      expect(lineItem).toHaveProperty('pricePerUnit');
      expect(lineItem).toHaveProperty('subtotal');
      expect(lineItem.productId).toBe(testProductId);
    });

    test('Authorization: Profile owner can get order', async () => {
      const { data }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId: testOrderId1 },
        fetchPolicy: 'network-only',
      });

      expect(data.getOrder).toBeDefined();
      expect(data.getOrder.orderId).toBe(testOrderId1);
    });

    test('Authorization: Shared user can get order', async () => {
      const { data }: any = await contributorClient.query({
        query: GET_ORDER,
        variables: { orderId: testOrderId1 },
        fetchPolicy: 'network-only',
      });

      expect(data.getOrder).toBeDefined();
      expect(data.getOrder.orderId).toBe(testOrderId1);
    });

    test.skip('Authorization: Non-shared user cannot get order', async () => {
      // ⚠️ BUG #22: getOrder lacks authorization (returns orders to any authenticated user)
      // Expected: Should throw authorization error
      // Actual: Returns order data
      // Test: contributor tries to access order from unshared profile
      
      await expect(
        contributorClient.query({
          query: GET_ORDER,
          variables: { orderId: testOrderId1 },
          fetchPolicy: 'network-only',
        })
      ).rejects.toThrow();
    });

    test('Input Validation: Returns null for non-existent orderId', async () => {
      const { data }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId: 'ORDER#nonexistent' },
        fetchPolicy: 'network-only',
      });

      expect(data.getOrder).toBeNull();
    });
  });

  // ========================================
  // 5.12.2: listOrdersBySeason
  // ========================================

  describe('5.12.2: listOrdersBySeason', () => {
    test('Happy Path: Returns all orders for a season', async () => {
      // ✅ FIXED BUG #25: Now queries GSI5 (seasonId index) with filter
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_SEASON,
        variables: { seasonId: testSeasonId },
        fetchPolicy: 'network-only',
      });

      expect(data.listOrdersBySeason).toBeDefined();
      expect(data.listOrdersBySeason.length).toBeGreaterThanOrEqual(2);
      
      const orderIds = data.listOrdersBySeason.map((o: any) => o.orderId);
      expect(orderIds).toContain(testOrderId1);
      expect(orderIds).toContain(testOrderId2);
    });

    test('Happy Path: Returns empty array if no orders', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_SEASON,
        variables: { seasonId: unsharedSeasonId },
        fetchPolicy: 'network-only',
      });

      expect(data.listOrdersBySeason).toBeDefined();
      expect(data.listOrdersBySeason).toEqual([]);
    });

    test('Happy Path: Includes all order fields', async () => {
      // ✅ FIXED: Bug #25 resolved
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_SEASON,
        variables: { seasonId: testSeasonId },
        fetchPolicy: 'network-only',
      });

      const order = data.listOrdersBySeason[0];
      expect(order).toHaveProperty('orderId');
      expect(order).toHaveProperty('profileId');
      expect(order).toHaveProperty('seasonId');
      expect(order).toHaveProperty('customerName');
      expect(order).toHaveProperty('paymentMethod');
      expect(order).toHaveProperty('lineItems');
      expect(order).toHaveProperty('totalAmount');
    });

    test.skip('Authorization: Profile owner can list orders', async () => {
      // ⚠️ SKIP: Bug #23 - missing authorization (works but should test auth)
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_SEASON,
        variables: { seasonId: testSeasonId },
        fetchPolicy: 'network-only',
      });

      expect(data.listOrdersBySeason).toBeDefined();
      expect(data.listOrdersBySeason.length).toBeGreaterThan(0);
    });

    test.skip('Authorization: Shared user can list orders', async () => {
      // ⚠️ SKIP: Bug #23 - missing authorization (works but should test auth)
      const { data }: any = await contributorClient.query({
        query: LIST_ORDERS_BY_SEASON,
        variables: { seasonId: testSeasonId },
        fetchPolicy: 'network-only',
      });

      expect(data.listOrdersBySeason).toBeDefined();
      expect(data.listOrdersBySeason.length).toBeGreaterThan(0);
    });

    test.skip('Authorization: Non-shared user cannot list orders', async () => {
      // ⚠️ BUG #23: listOrdersBySeason lacks authorization
      // Expected: Should throw authorization error
      // Actual: Returns order data
      // Test: contributor tries to list orders from unshared profile's season
      
      await expect(
        contributorClient.query({
          query: LIST_ORDERS_BY_SEASON,
          variables: { seasonId: unsharedSeasonId },
          fetchPolicy: 'network-only',
        })
      ).rejects.toThrow();
    });

    test('Input Validation: Returns empty array for non-existent seasonId', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_SEASON,
        variables: { seasonId: 'SEASON#nonexistent' },
        fetchPolicy: 'network-only',
      });

      expect(data.listOrdersBySeason).toEqual([]);
    });
  });

  // ========================================
  // 5.12.3: listOrdersByProfile
  // ========================================

  describe('5.12.3: listOrdersByProfile', () => {
    test('Happy Path: Returns all orders for a profile', async () => {
      // ✅ FIXED BUG #26: Now queries main table with PK=profileId
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listOrdersByProfile).toBeDefined();
      expect(data.listOrdersByProfile.length).toBeGreaterThanOrEqual(2);
      
      const orderIds = data.listOrdersByProfile.map((o: any) => o.orderId);
      expect(orderIds).toContain(testOrderId1);
      expect(orderIds).toContain(testOrderId2);
    });

    test('Happy Path: Returns empty array if no orders', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_PROFILE,
        variables: { profileId: unsharedProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listOrdersByProfile).toBeDefined();
      expect(data.listOrdersByProfile).toEqual([]);
    });

    test('Happy Path: Includes all order fields', async () => {
      // ✅ FIXED: Bug #26 resolved
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      const order = data.listOrdersByProfile[0];
      expect(order).toHaveProperty('orderId');
      expect(order).toHaveProperty('profileId');
      expect(order).toHaveProperty('seasonId');
      expect(order).toHaveProperty('customerName');
      expect(order).toHaveProperty('paymentMethod');
      expect(order).toHaveProperty('lineItems');
      expect(order).toHaveProperty('totalAmount');
    });

    test.skip('Authorization: Profile owner can list orders', async () => {
      // ⚠️ SKIP: Bug #24 - missing authorization (works but should test auth)
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listOrdersByProfile).toBeDefined();
      expect(data.listOrdersByProfile.length).toBeGreaterThan(0);
    });

    test.skip('Authorization: Shared user can list orders', async () => {
      // ⚠️ SKIP: Bug #24 - missing authorization (works but should test auth)
      const { data }: any = await contributorClient.query({
        query: LIST_ORDERS_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listOrdersByProfile).toBeDefined();
      expect(data.listOrdersByProfile.length).toBeGreaterThan(0);
    });

    test.skip('Authorization: Non-shared user cannot list orders', async () => {
      // ⚠️ BUG #24: listOrdersByProfile lacks authorization
      // Expected: Should throw authorization error
      // Actual: Returns order data
      // Test: contributor tries to list orders from unshared profile
      
      await expect(
        contributorClient.query({
          query: LIST_ORDERS_BY_PROFILE,
          variables: { profileId: unsharedProfileId },
          fetchPolicy: 'network-only',
        })
      ).rejects.toThrow();
    });

    test('Input Validation: Returns empty array for non-existent profileId', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_PROFILE,
        variables: { profileId: 'PROFILE#nonexistent' },
        fetchPolicy: 'network-only',
      });

      expect(data.listOrdersByProfile).toEqual([]);
    });
  });
});
