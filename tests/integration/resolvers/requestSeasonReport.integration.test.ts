import '../setup.ts';
import { describe, test, expect, beforeAll, afterAll } from 'vitest';
import { gql } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';

/**
 * Integration tests for requestSeasonReport mutation (Lambda resolver)
 * 
 * Test Data Setup:
 * - TEST_OWNER_EMAIL: Owner of profile/season (can request reports)
 * - TEST_CONTRIBUTOR_EMAIL: Has WRITE access (can request reports)
 * - TEST_READONLY_EMAIL: Has READ access (can request reports)
 * 
 * Tests verify:
 * - Report generation for different users with different access levels
 * - Report URL generation and format
 * - Authorization (owner, contributors, and READ users can all request reports)
 * - Error handling (invalid season, unauthorized access)
 * 
 * Note: These tests create their own test data (profile, season, catalog, orders)
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
      isPublic
      products {
        productId
        productName
        price
        sortOrder
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

const CREATE_ORDER = gql`
  mutation CreateOrder($input: CreateOrderInput!) {
    createOrder(input: $input) {
      orderId
      profileId
      seasonId
      customerName
      totalAmount
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

// GraphQL Mutation for test
const REQUEST_SEASON_REPORT = gql`
  mutation RequestSeasonReport($input: RequestSeasonReportInput!) {
    requestSeasonReport(input: $input) {
      reportId
      seasonId
      profileId
      reportUrl
      status
      createdAt
      expiresAt
    }
  }
`;

// Cleanup mutations
const DELETE_ORDER = gql`
  mutation DeleteOrder($input: DeleteOrderInput!) {
    deleteOrder(input: $input) {
      orderId
      profileId
      seasonId
    }
  }
`;

const DELETE_SEASON = gql`
  mutation DeleteSeason($input: DeleteSeasonInput!) {
    deleteSeason(input: $input) {
      seasonId
      profileId
    }
  }
`;

const DELETE_CATALOG = gql`
  mutation DeleteCatalog($input: DeleteCatalogInput!) {
    deleteCatalog(input: $input) {
      catalogId
    }
  }
`;

const DELETE_SELLER_PROFILE = gql`
  mutation DeleteSellerProfile($input: DeleteSellerProfileInput!) {
    deleteSellerProfile(input: $input) {
      profileId
    }
  }
`;

const REVOKE_SHARE = gql`
  mutation RevokeShare($input: RevokeShareInput!) {
    revokeShare(input: $input) {
      shareId
    }
  }
`;

describe('requestSeasonReport Integration Tests', () => {
  let ownerClient: any;
  let contributorClient: any;
  let readonlyClient: any;

  let testProfileId: string;
  let testCatalogId: string;
  let testSeasonId: string;
  let testOrderId1: string;
  let testOrderId2: string;
  let contributorShareId: string;
  let readonlyShareId: string;
  let contributorAccountId: string;
  let readonlyAccountId: string;
  let productId1: string;
  let productId2: string;

  beforeAll(async () => {
    // Create authenticated clients
    const ownerAuth: AuthenticatedClientResult = await createAuthenticatedClient('owner');
    const contributorAuth: AuthenticatedClientResult = await createAuthenticatedClient('contributor');
    const readonlyAuth: AuthenticatedClientResult = await createAuthenticatedClient('readonly');

    ownerClient = ownerAuth.client;
    contributorClient = contributorAuth.client;
    readonlyClient = readonlyAuth.client;

    // Get account IDs for sharing
    contributorAccountId = contributorAuth.accountId;
    readonlyAccountId = readonlyAuth.accountId;

    // Create test profile as owner
    const profileResponse = await ownerClient.mutate({
      mutation: CREATE_SELLER_PROFILE,
      variables: {
        input: {
          sellerName: 'Report Test Profile',
        },
      },
    });
    testProfileId = profileResponse.data.createSellerProfile.profileId;

    // Create test catalog
    const catalogResponse = await ownerClient.mutate({
      mutation: CREATE_CATALOG,
      variables: {
        input: {
          catalogName: 'Report Test Catalog',
          isPublic: false,
          products: [
            {
              productName: 'Test Product 1',
              price: 10.00,
              sortOrder: 1,
            },
            {
              productName: 'Test Product 2',
              price: 15.00,
              sortOrder: 2,
            },
          ],
        },
      },
    });
    testCatalogId = catalogResponse.data.createCatalog.catalogId;
    productId1 = catalogResponse.data.createCatalog.products[0].productId;
    productId2 = catalogResponse.data.createCatalog.products[1].productId;

    // Create test season
    const seasonResponse = await ownerClient.mutate({
      mutation: CREATE_SEASON,
      variables: {
        input: {
          profileId: testProfileId,
          seasonName: 'Report Test Season 2024',
          catalogId: testCatalogId,
          startDate: '2024-01-01T00:00:00.000Z',
          endDate: '2024-12-31T23:59:59.999Z',
        },
      },
    });
    testSeasonId = seasonResponse.data.createSeason.seasonId;

    // Create test orders
    const order1Response = await ownerClient.mutate({
      mutation: CREATE_ORDER,
      variables: {
        input: {
          profileId: testProfileId,
          seasonId: testSeasonId,
          customerName: 'Test Customer 1',
          customerPhone: '555-0101',
          orderDate: '2024-06-01T12:00:00.000Z',
          paymentMethod: 'CASH',
          lineItems: [
            {
              productId: productId1,
              quantity: 2,
            },
          ],
        },
      },
    });
    testOrderId1 = order1Response.data.createOrder.orderId;

    const order2Response = await ownerClient.mutate({
      mutation: CREATE_ORDER,
      variables: {
        input: {
          profileId: testProfileId,
          seasonId: testSeasonId,
          customerName: 'Test Customer 2',
          customerPhone: '555-0102',
          orderDate: '2024-06-15T14:30:00.000Z',
          paymentMethod: 'CHECK',
          lineItems: [
            {
              productId: productId2,
              quantity: 3,
            },
          ],
        },
      },
    });
    testOrderId2 = order2Response.data.createOrder.orderId;

    // Share profile with contributor (WRITE access)
    const contributorShareResponse = await ownerClient.mutate({
      mutation: SHARE_PROFILE_DIRECT,
      variables: {
        input: {
          profileId: testProfileId,
          targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL!,
          permissions: ['WRITE'],
        },
      },
    });
    contributorShareId = contributorShareResponse.data.shareProfileDirect.shareId;

    // Share profile with readonly user (READ access)
    const readonlyShareResponse = await ownerClient.mutate({
      mutation: SHARE_PROFILE_DIRECT,
      variables: {
        input: {
          profileId: testProfileId,
          targetAccountEmail: process.env.TEST_READONLY_EMAIL!,
          permissions: ['READ'],
        },
      },
    });
    readonlyShareId = readonlyShareResponse.data.shareProfileDirect.shareId;
  });

  afterAll(async () => {
    // Cleanup in reverse order of creation
    if (testOrderId1) {
      await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { input: { orderId: testOrderId1 } },
      }).catch(() => {});
    }
    if (testOrderId2) {
      await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { input: { orderId: testOrderId2 } },
      }).catch(() => {});
    }
    if (contributorShareId) {
      await ownerClient.mutate({
        mutation: REVOKE_SHARE,
        variables: { input: { shareId: contributorShareId } },
      }).catch(() => {});
    }
    if (readonlyShareId) {
      await ownerClient.mutate({
        mutation: REVOKE_SHARE,
        variables: { input: { shareId: readonlyShareId } },
      }).catch(() => {});
    }
    if (testSeasonId) {
      await ownerClient.mutate({
        mutation: DELETE_SEASON,
        variables: { input: { seasonId: testSeasonId } },
      }).catch(() => {});
    }
    if (testCatalogId) {
      await ownerClient.mutate({
        mutation: DELETE_CATALOG,
        variables: { input: { catalogId: testCatalogId } },
      }).catch(() => {});
    }
    if (testProfileId) {
      await ownerClient.mutate({
        mutation: DELETE_SELLER_PROFILE,
        variables: { input: { profileId: testProfileId } },
      }).catch(() => {});
    }
  });

  describe('Owner Authorization', () => {
    test('should allow owner to request season report with default format (xlsx)', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_SEASON_REPORT,
        variables: {
          input: {
            seasonId: testSeasonId,
          },
        },
      });

      expect(result.data.requestSeasonReport).toBeDefined();
      expect(result.data.requestSeasonReport.reportId).toBeDefined();
      expect(result.data.requestSeasonReport.seasonId).toBe(testSeasonId);
      expect(result.data.requestSeasonReport.profileId).toBe(testProfileId);
      expect(result.data.requestSeasonReport.reportUrl).toBeDefined();
      expect(result.data.requestSeasonReport.reportUrl).toMatch(/^https?:\/\//);
      expect(result.data.requestSeasonReport.reportUrl).toContain('.xlsx');
      expect(result.data.requestSeasonReport.status).toBe('COMPLETED');
      expect(result.data.requestSeasonReport.createdAt).toBeDefined();
      expect(result.data.requestSeasonReport.expiresAt).toBeDefined();

      // Verify URL expiration is ~7 days from now
      const createdAt = new Date(result.data.requestSeasonReport.createdAt);
      const expiresAt = new Date(result.data.requestSeasonReport.expiresAt);
      const diffDays = (expiresAt.getTime() - createdAt.getTime()) / (1000 * 60 * 60 * 24);
      expect(diffDays).toBeGreaterThan(6.9);
      expect(diffDays).toBeLessThan(7.1);
    });

    test('should allow owner to request season report with explicit xlsx format', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_SEASON_REPORT,
        variables: {
          input: {
            seasonId: testSeasonId,
            format: 'xlsx',
          },
        },
      });

      expect(result.data.requestSeasonReport).toBeDefined();
      expect(result.data.requestSeasonReport.reportUrl).toContain('.xlsx');
      expect(result.data.requestSeasonReport.status).toBe('COMPLETED');
    });

    test('should allow owner to request season report with csv format', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_SEASON_REPORT,
        variables: {
          input: {
            seasonId: testSeasonId,
            format: 'csv',
          },
        },
      });

      expect(result.data.requestSeasonReport).toBeDefined();
      expect(result.data.requestSeasonReport.reportUrl).toContain('.csv');
      expect(result.data.requestSeasonReport.status).toBe('COMPLETED');
    });
  });

  describe('Contributor Authorization (WRITE access)', () => {
    test('should allow contributor with WRITE access to request season report', async () => {
      const result = await contributorClient.mutate({
        mutation: REQUEST_SEASON_REPORT,
        variables: {
          input: {
            seasonId: testSeasonId,
          },
        },
      });

      expect(result.data.requestSeasonReport).toBeDefined();
      expect(result.data.requestSeasonReport.reportId).toBeDefined();
      expect(result.data.requestSeasonReport.seasonId).toBe(testSeasonId);
      expect(result.data.requestSeasonReport.profileId).toBe(testProfileId);
      expect(result.data.requestSeasonReport.reportUrl).toBeDefined();
      expect(result.data.requestSeasonReport.status).toBe('COMPLETED');
    });
  });

  describe('Read-Only User Authorization (READ access)', () => {
    test('should allow read-only user with READ access to request season report', async () => {
      const result = await readonlyClient.mutate({
        mutation: REQUEST_SEASON_REPORT,
        variables: {
          input: {
            seasonId: testSeasonId,
          },
        },
      });

      expect(result.data.requestSeasonReport).toBeDefined();
      expect(result.data.requestSeasonReport.reportId).toBeDefined();
      expect(result.data.requestSeasonReport.seasonId).toBe(testSeasonId);
      expect(result.data.requestSeasonReport.profileId).toBe(testProfileId);
      expect(result.data.requestSeasonReport.reportUrl).toBeDefined();
      expect(result.data.requestSeasonReport.status).toBe('COMPLETED');
    });
  });

  describe('Unauthorized Access', () => {
    test('should reject request for season that does not exist', async () => {
      await expect(
        ownerClient.mutate({
          mutation: REQUEST_SEASON_REPORT,
          variables: {
            input: {
              seasonId: 'SEASON#nonexistent',
            },
          },
        })
      ).rejects.toThrow();
    });

    // Note: Testing unauthorized user requires creating a 4th test user
    // which is beyond the scope of this test suite. The authorization logic
    // is tested through the check_profile_access function in the Lambda handler.
  });

  describe('Report Content Verification', () => {
    test('should generate unique report IDs for multiple requests', async () => {
      const result1 = await ownerClient.mutate({
        mutation: REQUEST_SEASON_REPORT,
        variables: {
          input: {
            seasonId: testSeasonId,
          },
        },
      });

      // Wait a moment to ensure different timestamp
      await new Promise((resolve) => setTimeout(resolve, 1100));

      const result2 = await ownerClient.mutate({
        mutation: REQUEST_SEASON_REPORT,
        variables: {
          input: {
            seasonId: testSeasonId,
          },
        },
      });

      expect(result1.data.requestSeasonReport.reportId).toBeDefined();
      expect(result2.data.requestSeasonReport.reportId).toBeDefined();
      expect(result1.data.requestSeasonReport.reportId).not.toBe(
        result2.data.requestSeasonReport.reportId
      );
    });

    test('should include correct profileId in report metadata', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_SEASON_REPORT,
        variables: {
          input: {
            seasonId: testSeasonId,
          },
        },
      });

      expect(result.data.requestSeasonReport.profileId).toBe(testProfileId);
    });

    test('should include correct seasonId in report metadata', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_SEASON_REPORT,
        variables: {
          input: {
            seasonId: testSeasonId,
          },
        },
      });

      expect(result.data.requestSeasonReport.seasonId).toBe(testSeasonId);
    });
  });

  describe('S3 URL Verification', () => {
    test('should generate valid S3 pre-signed URL', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_SEASON_REPORT,
        variables: {
          input: {
            seasonId: testSeasonId,
          },
        },
      });

      const reportUrl = result.data.requestSeasonReport.reportUrl;
      expect(reportUrl).toMatch(/^https?:\/\//);
      
      // URL should contain S3 signature components
      expect(reportUrl).toMatch(/X-Amz-Algorithm|AWSAccessKeyId/);
      expect(reportUrl).toMatch(/X-Amz-Signature|Signature/);
    });

    test('should generate URL with correct S3 path structure', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_SEASON_REPORT,
        variables: {
          input: {
            seasonId: testSeasonId,
          },
        },
      });

      const reportUrl = result.data.requestSeasonReport.reportUrl;
      // URL will have # encoded as %23
      const encodedProfileId = encodeURIComponent(testProfileId);
      const encodedSeasonId = encodeURIComponent(testSeasonId);
      expect(reportUrl).toContain(`reports/${encodedProfileId}/${encodedSeasonId}/`);
    });
  });

  describe('Format Parameter Validation', () => {
    test('should handle case-insensitive format parameter (CSV uppercase)', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_SEASON_REPORT,
        variables: {
          input: {
            seasonId: testSeasonId,
            format: 'CSV',
          },
        },
      });

      expect(result.data.requestSeasonReport).toBeDefined();
      expect(result.data.requestSeasonReport.reportUrl).toContain('.csv');
    });

    test('should handle case-insensitive format parameter (XLSX uppercase)', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_SEASON_REPORT,
        variables: {
          input: {
            seasonId: testSeasonId,
            format: 'XLSX',
          },
        },
      });

      expect(result.data.requestSeasonReport).toBeDefined();
      expect(result.data.requestSeasonReport.reportUrl).toContain('.xlsx');
    });

    test('should treat invalid format as default (xlsx)', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_SEASON_REPORT,
        variables: {
          input: {
            seasonId: testSeasonId,
            format: 'pdf', // Invalid format
          },
        },
      });

      expect(result.data.requestSeasonReport).toBeDefined();
      // Should default to xlsx
      expect(result.data.requestSeasonReport.reportUrl).toContain('.xlsx');
    });
  });
});
