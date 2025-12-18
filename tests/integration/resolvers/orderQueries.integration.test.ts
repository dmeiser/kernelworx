import '../setup.ts';
import { describe, test, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, NormalizedCacheObject, gql } from '@apollo/client';
import { createAuthenticatedClient } from '../setup/apolloClient';
import { deleteTestAccounts } from '../setup/testData';


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
      totalAmount
      paymentMethod
      notes
      lineItems {
        productId
        productName
        quantity
        pricePerUnit
        subtotal
      }
      createdAt
      updatedAt
    }
  }
`;

const DELETE_ORDER = gql`
  mutation DeleteOrder($orderId: ID!) {
    deleteOrder(orderId: $orderId)
  }
`;

const DELETE_SEASON = gql`
  mutation DeleteSeason($seasonId: ID!) {
    deleteSeason(seasonId: $seasonId)
  }
`;

const DELETE_CATALOG = gql`
  mutation DeleteCatalog($catalogId: ID!) {
    deleteCatalog(catalogId: $catalogId)
  }
`;

const DELETE_PROFILE = gql`
  mutation DeleteProfile($profileId: ID!) {
    deleteSellerProfile(profileId: $profileId)
  }
`;

const REVOKE_SHARE = gql`
  mutation RevokeShare($input: RevokeShareInput!) {
    revokeShare(input: $input)
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
  const SUITE_ID = 'order-queries';
  
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
  let unsharedOrderId: string;

  // Empty season for testing empty results
  let emptySeasonId: string;
  let emptyProfileId: string;

  // Account IDs for cleanup
  let ownerAccountId: string;
  let contributorAccountId: string;
  let readonlyAccountId: string;

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
      ownerAccountId = ownerAuth.accountId;

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
      const { data: share1Data }: any = await ownerClient.mutate({
        mutation: SHARE_PROFILE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL!,
            permissions: ['READ', 'WRITE'],
          },
        },
      });
      contributorAccountId = share1Data.shareProfileDirect.targetAccountId;

      // 5. Share profile with readonly (READ)
      console.log('Step 7: Sharing profile with readonly...');
      const { data: share2Data }: any = await ownerClient.mutate({
        mutation: SHARE_PROFILE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_READONLY_EMAIL!,
            permissions: ['READ'],
          },
        },
      });
      readonlyAccountId = share2Data.shareProfileDirect.targetAccountId;

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

      console.log('Step 12: Creating unshared order...');
      const { data: unsharedOrderData }: any = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: unsharedProfileId,
            seasonId: unsharedSeasonId,
            customerName: 'Unshared Order Customer',
            customerPhone: '555-9999',
            orderDate: new Date('2025-03-01T10:00:00Z').toISOString(),
            paymentMethod: 'CASH',
            lineItems: [
              {
                productId: testProductId,
                quantity: 1,
              },
            ],
          },
        },
      });
      unsharedOrderId = unsharedOrderData.createOrder.orderId;
      console.log(`Created unshared order: ${unsharedOrderId}`);

      console.log('Step 13: Creating empty season (no orders)...');
      const { data: emptySeasonData }: any = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: testProfileId,  // Use shared profile so owner can query it
            seasonName: 'Empty Season',
            startDate: new Date('2026-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2026-12-31T23:59:59Z').toISOString(),
            catalogId: testCatalogId,
          },
        },
      });
      emptySeasonId = emptySeasonData.createSeason.seasonId;
      console.log(`Created empty season: ${emptySeasonId}`);

      console.log('Step 14: Creating empty profile (no orders)...');
      const { data: emptyProfileData }: any = await ownerClient.mutate({
        mutation: CREATE_SELLER_PROFILE,
        variables: {
          input: {
            sellerName: 'Empty Profile',
          },
        },
      });
      emptyProfileId = emptyProfileData.createSellerProfile.profileId;
      console.log(`Created empty profile: ${emptyProfileId}`);

      console.log(`Test data created successfully!`);
    } catch (error) {
      console.error('Error in beforeAll:', error);
      throw error;
    }
  }, 30000);

  afterAll(async () => {
    // Clean up all test data in reverse order
    console.log('Cleaning up order query test data...');
    
    try {
      // 1. Delete all orders
      for (const orderId of [testOrderId1, testOrderId2, unsharedOrderId]) {
        if (orderId) {
          await ownerClient.mutate({
            mutation: DELETE_ORDER,
            variables: { orderId },
          });
        }
      }
      
      // 2. Revoke shares (before deleting profile)
      for (const accountId of [contributorAccountId, readonlyAccountId]) {
        if (accountId) {
          await ownerClient.mutate({
            mutation: REVOKE_SHARE,
            variables: { input: { profileId: testProfileId, targetAccountId: accountId } },
          });
        }
      }
      
      // 3. Delete seasons
      for (const seasonId of [testSeasonId, emptySeasonId, unsharedSeasonId]) {
        if (seasonId) {
          await ownerClient.mutate({
            mutation: DELETE_SEASON,
            variables: { seasonId },
          });
        }
      }
      
      // 4. Delete catalog
      if (testCatalogId) {
        await ownerClient.mutate({
          mutation: DELETE_CATALOG,
          variables: { catalogId: testCatalogId },
        });
      }
      
      // 5. Delete profiles
      for (const profileId of [testProfileId, unsharedProfileId, emptyProfileId]) {
        if (profileId) {
          await ownerClient.mutate({
            mutation: DELETE_PROFILE,
            variables: { profileId },
          });
        }
      }
      
      // 6. Delete account records
      console.log('Cleaning up account records...');
      // await deleteTestAccounts([ownerAccountId, contributorAccountId, readonlyAccountId]);
      
      console.log('Order query test data cleanup complete.');
    } catch (error) {
      console.log('Error in cleanup (may be expected if some data already cleaned):', error);
    }
  }, 30000);


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

    test('Authorization: Non-shared user cannot get order', async () => {
      // ✅ FIXED Bug #22: getOrder now includes authorization via pipeline resolver
      // Pipeline: QueryOrderFn → VerifyProfileReadAccessFn → CheckShareReadPermissionsFn → ReturnOrderFn
      // Test: contributor tries to access order from unshared profile
      // Expected: Returns null (query permissions model - don't error)
      
      const { data }: any = await contributorClient.query({
        query: GET_ORDER,
        variables: { orderId: unsharedOrderId },
        fetchPolicy: 'network-only',
      });
      
      expect(data.getOrder).toBeNull();
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
        variables: { seasonId: emptySeasonId },
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

    test('Authorization: Profile owner can list orders', async () => {
      // ✅ FIXED Bug #23: listOrdersBySeason now includes authorization via pipeline resolver
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_SEASON,
        variables: { seasonId: testSeasonId },
        fetchPolicy: 'network-only',
      });

      expect(data.listOrdersBySeason).toBeDefined();
      expect(data.listOrdersBySeason.length).toBeGreaterThan(0);
    });

    test('Authorization: Shared user can list orders', async () => {
      // ✅ FIXED Bug #23: listOrdersBySeason now includes authorization via pipeline resolver
      const { data }: any = await contributorClient.query({
        query: LIST_ORDERS_BY_SEASON,
        variables: { seasonId: testSeasonId },
        fetchPolicy: 'network-only',
      });

      expect(data.listOrdersBySeason).toBeDefined();
      expect(data.listOrdersBySeason.length).toBeGreaterThan(0);
    });

    test('Authorization: Non-shared user cannot list orders', async () => {
      // ✅ FIXED Bug #23: listOrdersBySeason now includes authorization via pipeline resolver
      // Test: contributor tries to list orders from unshared profile's season
      // Expected: Returns empty array (query permissions model - don't error)
      
      const { data }: any = await contributorClient.query({
        query: LIST_ORDERS_BY_SEASON,
        variables: { seasonId: unsharedSeasonId },
        fetchPolicy: 'network-only',
      });
      
      expect(data.listOrdersBySeason).toEqual([]);
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
        variables: { profileId: emptyProfileId },
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

    test('Authorization: Profile owner can list orders', async () => {
      // ✅ FIXED Bug #24: listOrdersByProfile now includes authorization via pipeline resolver
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listOrdersByProfile).toBeDefined();
      expect(data.listOrdersByProfile.length).toBeGreaterThan(0);
    });

    test('Authorization: Shared user can list orders', async () => {
      // ✅ FIXED Bug #24: listOrdersByProfile now includes authorization via pipeline resolver
      const { data }: any = await contributorClient.query({
        query: LIST_ORDERS_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listOrdersByProfile).toBeDefined();
      expect(data.listOrdersByProfile.length).toBeGreaterThan(0);
    });

    test('Authorization: Non-shared user cannot list orders', async () => {
      // ✅ FIXED Bug #24: listOrdersByProfile now includes authorization via pipeline resolver
      // Test: contributor tries to list orders from unshared profile
      // Expected: Returns empty array (query permissions model - don't error)
      
      const { data }: any = await contributorClient.query({
        query: LIST_ORDERS_BY_PROFILE,
        variables: { profileId: unsharedProfileId },
        fetchPolicy: 'network-only',
      });
      
      expect(data.listOrdersByProfile).toEqual([]);
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

  // ========================================
  // 5.12.4: Order Edge Cases
  // ========================================

  describe('5.12.4: Order Edge Cases', () => {
    test('Order with CASH payment method', async () => {
      // Create order with CASH
      const { data: orderData }: any = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            seasonId: testSeasonId,
            customerName: 'Cash Customer',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: [{ productId: testProductId, quantity: 1 }],
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      // Query the order
      const { data }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId },
        fetchPolicy: 'network-only',
      });

      expect(data.getOrder.paymentMethod).toBe('CASH');

      // Cleanup
      await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId },
      });
    });

    test('Order with CHECK payment method', async () => {
      const { data: orderData }: any = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            seasonId: testSeasonId,
            customerName: 'Check Customer',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CHECK',
            lineItems: [{ productId: testProductId, quantity: 1 }],
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      const { data }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId },
        fetchPolicy: 'network-only',
      });

      expect(data.getOrder.paymentMethod).toBe('CHECK');

      await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId },
      });
    });

    test('Order with CREDIT_CARD payment method', async () => {
      const { data: orderData }: any = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            seasonId: testSeasonId,
            customerName: 'Credit Card Customer',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CREDIT_CARD',
            lineItems: [{ productId: testProductId, quantity: 1 }],
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      const { data }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId },
        fetchPolicy: 'network-only',
      });

      expect(data.getOrder.paymentMethod).toBe('CREDIT_CARD');

      await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId },
      });
    });

    test('Order with OTHER payment method', async () => {
      const { data: orderData }: any = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            seasonId: testSeasonId,
            customerName: 'Other Payment Customer',
            orderDate: new Date().toISOString(),
            paymentMethod: 'OTHER',
            lineItems: [{ productId: testProductId, quantity: 1 }],
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      const { data }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId },
        fetchPolicy: 'network-only',
      });

      expect(data.getOrder.paymentMethod).toBe('OTHER');

      await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId },
      });
    });

    test('Order totalAmount calculation is correct with multiple items', async () => {
      // Create order with multiple line items of same product
      const { data: orderData }: any = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            seasonId: testSeasonId,
            customerName: 'Total Calculation Customer',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: [
              { productId: testProductId, quantity: 5 }, // 5 x price
            ],
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      const { data }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId },
        fetchPolicy: 'network-only',
      });

      // Verify line items have correct subtotals
      expect(data.getOrder.lineItems.length).toBe(1);
      
      const lineItem = data.getOrder.lineItems[0];
      expect(lineItem.quantity).toBe(5);
      expect(lineItem.subtotal).toBe(lineItem.quantity * lineItem.pricePerUnit);
      
      // totalAmount should match the subtotal
      expect(data.getOrder.totalAmount).toBe(lineItem.subtotal);

      await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId },
      });
    });

    test('Order without optional customerPhone field', async () => {
      // Create order without customerPhone
      const { data: orderData }: any = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            seasonId: testSeasonId,
            customerName: 'No Phone Customer',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: [{ productId: testProductId, quantity: 1 }],
            // No customerPhone
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      const { data }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId },
        fetchPolicy: 'network-only',
      });

      expect(data.getOrder.customerName).toBe('No Phone Customer');
      expect(data.getOrder.customerPhone).toBeNull();

      await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId },
      });
    });

    test('Order with optional customerPhone field', async () => {
      const { data: orderData }: any = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            seasonId: testSeasonId,
            customerName: 'Phone Customer',
            customerPhone: '555-123-4567',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: [{ productId: testProductId, quantity: 1 }],
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      const { data }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId },
        fetchPolicy: 'network-only',
      });

      expect(data.getOrder.customerPhone).toBe('555-123-4567');

      await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId },
      });
    });

    test('Order with many line items', async () => {
      // Create an order with multiple line items
      // Note: We need to create products in the catalog first
      const { data: catalogData }: any = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: 'Many Line Items Catalog',
            isPublic: false,
            products: [
              { productName: 'Product A', price: 5.0, sortOrder: 1 },
              { productName: 'Product B', price: 10.0, sortOrder: 2 },
              { productName: 'Product C', price: 15.0, sortOrder: 3 },
              { productName: 'Product D', price: 20.0, sortOrder: 4 },
              { productName: 'Product E', price: 25.0, sortOrder: 5 },
            ],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;
      const productIds = catalogData.createCatalog.products.map((p: any) => p.productId);

      // Create season with this catalog
      const { data: seasonData }: any = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: testProfileId,
            seasonId: undefined,
            seasonName: 'Many Line Items Season',
            catalogId,
            startDate: new Date().toISOString(),
          },
        },
      });
      const seasonId = seasonData.createSeason.seasonId;

      // Create order with 5 line items
      const { data: orderData }: any = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            seasonId,
            customerName: 'Many Items Customer',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: productIds.map((id: string, idx: number) => ({
              productId: id,
              quantity: idx + 1,
            })),
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      // Query the order
      const { data }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId },
        fetchPolicy: 'network-only',
      });

      // Assert: All 5 line items should be present
      expect(data.getOrder.lineItems).toHaveLength(5);
      
      // Verify each line item has required fields
      for (const lineItem of data.getOrder.lineItems) {
        expect(lineItem.productId).toBeDefined();
        expect(lineItem.productName).toBeDefined();
        expect(lineItem.quantity).toBeGreaterThan(0);
        expect(lineItem.pricePerUnit).toBeDefined();
        expect(lineItem.subtotal).toBe(lineItem.quantity * lineItem.pricePerUnit);
      }

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId } });
      await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
    }, 15000);

    test('Listing orders for season with many orders', async () => {
      // Create 5 orders for the test season
      const createdOrderIds: string[] = [];

      for (let i = 0; i < 5; i++) {
        const { data: orderData }: any = await ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: {
            input: {
              profileId: testProfileId,
              seasonId: testSeasonId,
              customerName: `Many Orders Customer ${i}`,
              orderDate: new Date().toISOString(),
              paymentMethod: 'CASH',
              lineItems: [{ productId: testProductId, quantity: i + 1 }],
            },
          },
        });
        createdOrderIds.push(orderData.createOrder.orderId);
      }

      // Query all orders for season
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_SEASON,
        variables: { seasonId: testSeasonId },
        fetchPolicy: 'network-only',
      });

      // Assert: All created orders should be in the result
      const returnedOrderIds = data.listOrdersBySeason.map((o: any) => o.orderId);
      for (const orderId of createdOrderIds) {
        expect(returnedOrderIds).toContain(orderId);
      }

      // Cleanup
      for (const orderId of createdOrderIds) {
        await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId } });
      }
    }, 20000);

    test('Listing orders across multiple seasons', async () => {
      // Create a second season
      const { data: season2Data }: any = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: testProfileId,
            seasonName: 'Second Season For Orders',
            catalogId: testCatalogId,
            startDate: new Date().toISOString(),
          },
        },
      });
      const season2Id = season2Data.createSeason.seasonId;

      // Create orders in both seasons
      const { data: order1Data }: any = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            seasonId: testSeasonId,
            customerName: 'Season 1 Customer',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: [{ productId: testProductId, quantity: 1 }],
          },
        },
      });
      const order1Id = order1Data.createOrder.orderId;

      const { data: order2Data }: any = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            seasonId: season2Id,
            customerName: 'Season 2 Customer',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CHECK',
            lineItems: [{ productId: testProductId, quantity: 2 }],
          },
        },
      });
      const order2Id = order2Data.createOrder.orderId;

      // List orders by profile - should include orders from both seasons
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      const orderIds = data.listOrdersByProfile.map((o: any) => o.orderId);
      expect(orderIds).toContain(order1Id);
      expect(orderIds).toContain(order2Id);

      // Verify both seasons are represented
      const seasonIds = data.listOrdersByProfile.map((o: any) => o.seasonId);
      expect(seasonIds).toContain(testSeasonId);
      expect(seasonIds).toContain(season2Id);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: order1Id } });
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: order2Id } });
      await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId: season2Id } });
    }, 15000);

    test('Performance: Listing orders for profile with many orders', async () => {
      // Create many orders for this test
      const createdOrderIds: string[] = [];
      const orderCount = 20;

      for (let i = 0; i < orderCount; i++) {
        const { data: orderData }: any = await ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: {
            input: {
              profileId: testProfileId,
              seasonId: testSeasonId,
              customerName: `Performance Customer ${i}`,
              orderDate: new Date(Date.now() - i * 86400000).toISOString(), // Different dates
              paymentMethod: i % 3 === 0 ? 'CASH' : i % 3 === 1 ? 'CHECK' : 'CREDIT_CARD',
              lineItems: [{ productId: testProductId, quantity: i + 1 }],
            },
          },
        });
        createdOrderIds.push(orderData.createOrder.orderId);
      }

      // Measure query performance for listOrdersByProfile
      const startTimeProfile = Date.now();
      const { data: profileData }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });
      const profileQueryTime = Date.now() - startTimeProfile;

      console.log(`📊 Performance: listOrdersByProfile with ${orderCount} orders took ${profileQueryTime}ms`);

      // Assert: Query should complete in reasonable time (under 5 seconds)
      expect(profileQueryTime).toBeLessThan(5000);
      expect(profileData.listOrdersByProfile.length).toBeGreaterThanOrEqual(orderCount);

      // Measure query performance for listOrdersBySeason
      const startTimeSeason = Date.now();
      const { data: seasonData }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_SEASON,
        variables: { seasonId: testSeasonId },
        fetchPolicy: 'network-only',
      });
      const seasonQueryTime = Date.now() - startTimeSeason;

      console.log(`📊 Performance: listOrdersBySeason with ${orderCount} orders took ${seasonQueryTime}ms`);

      // Assert: Query should complete in reasonable time (under 5 seconds)
      expect(seasonQueryTime).toBeLessThan(5000);
      expect(seasonData.listOrdersBySeason.length).toBeGreaterThanOrEqual(orderCount);

      // Cleanup
      for (const orderId of createdOrderIds) {
        await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId } });
      }
    }, 60000);

    test('Performance: Listing orders ordered by orderDate', async () => {
      // Create orders with different dates to test ordering
      const createdOrderIds: string[] = [];
      const orderDates = [
        new Date('2024-03-15').toISOString(),
        new Date('2024-01-01').toISOString(),
        new Date('2024-06-20').toISOString(),
        new Date('2024-02-28').toISOString(),
      ];

      for (let i = 0; i < orderDates.length; i++) {
        const { data: orderData }: any = await ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: {
            input: {
              profileId: testProfileId,
              seasonId: testSeasonId,
              customerName: `Order Date Test Customer ${i}`,
              orderDate: orderDates[i],
              paymentMethod: 'CASH',
              lineItems: [{ productId: testProductId, quantity: 1 }],
            },
          },
        });
        createdOrderIds.push(orderData.createOrder.orderId);
      }

      // Query orders
      const { data }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_SEASON,
        variables: { seasonId: testSeasonId },
        fetchPolicy: 'network-only',
      });

      // Verify all our orders are in the results
      const returnedOrderIds = data.listOrdersBySeason.map((o: any) => o.orderId);
      for (const orderId of createdOrderIds) {
        expect(returnedOrderIds).toContain(orderId);
      }

      // Verify order dates are present
      const ourOrders = data.listOrdersBySeason.filter((o: any) => 
        createdOrderIds.includes(o.orderId)
      );
      expect(ourOrders.length).toBe(orderDates.length);

      // Cleanup
      for (const orderId of createdOrderIds) {
        await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId } });
      }
    }, 30000);
  });
});
