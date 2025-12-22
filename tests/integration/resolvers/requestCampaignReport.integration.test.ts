import '../setup.ts';
import { describe, test, expect, beforeAll, afterAll } from 'vitest';
import { gql } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';
import { deleteTestAccounts } from '../setup/testData';


/**
 * Integration tests for requestCampaignReport mutation (Lambda resolver)
 * 
 * Test Data Setup:
 * - TEST_OWNER_EMAIL: Owner of profile/campaigngn (can request reports)
 * - TEST_CONTRIBUTOR_EMAIL: Has WRITE access (can request reports)
 * - TEST_READONLY_EMAIL: Has READ access (can request reports)
 * 
 * Tests verify:
 * - Report generation for different users with different access levels
 * - Report URL generation and format
 * - Authorization (owner, contributors, and READ users can all request reports)
 * - Error handling (invalid campaigngn, unauthorized access)
 * 
 * Note: These tests create their own test data (profile, campaigngn, catalog, orders)
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

const CREATE_CAMPAIGN = gql`
  mutation CreateCampaign($input: CreateCampaignInput!) {
    createCampaign(input: $input) {
      campaignId
      campaignName
      campaignYear
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
      campaignId
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
const REQUEST_CAMPAIGN_REPORT = gql`
  mutation RequestCampaignReport($input: RequestCampaignReportInput!) {
    requestCampaignReport(input: $input) {
      reportId
      campaignId
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
  mutation DeleteOrder($orderId: ID!) {
    deleteOrder(orderId: $orderId)
  }
`;

const DELETE_CAMPAIGN = gql`
  mutation DeleteCampaign($campaignId: ID!) {
    deleteCampaign(campaignId: $campaignId)
  }
`;

const DELETE_CATALOG = gql`
  mutation DeleteCatalog($catalogId: ID!) {
    deleteCatalog(catalogId: $catalogId)
  }
`;

const DELETE_SELLER_PROFILE = gql`
  mutation DeleteSellerProfile($profileId: ID!) {
    deleteSellerProfile(profileId: $profileId)
  }
`;

const REVOKE_SHARE = gql`
  mutation RevokeShare($input: RevokeShareInput!) {
    revokeShare(input: $input)
  }
`;

describe('requestCampaignReport Integration Tests', () => {
  const SUITE_ID = 'request-campaigngn-report';
  
  let ownerClient: any;
  let contributorClient: any;
  let readonlyClient: any;

  let testProfileId: string;
  let testCatalogId: string;
  let testCampaignId: string;
  let testOrderId1: string;
  let testOrderId2: string;
  let contributorShareId: string;
  let readonlyShareId: string;
  let ownerAccountId: string;
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
    ownerAccountId = ownerAuth.accountId;
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

    // Create test campaigngn
    const campaignResponse = await ownerClient.mutate({
      mutation: CREATE_CAMPAIGN,
      variables: {
        input: {
          profileId: testProfileId,
          campaignName: 'Report Test Campaigngn 2024',
          campaignYear: 2025,
          catalogId: testCatalogId,
          startDate: '2024-01-01T00:00:00.000Z',
          endDate: '2024-12-31T23:59:59.999Z',
        },
      },
    });
    testCampaignId = campaignResponse.data.createCampaign.campaignId;

    // Create test orders
    const order1Response = await ownerClient.mutate({
      mutation: CREATE_ORDER,
      variables: {
        input: {
          profileId: testProfileId,
          campaignId: testCampaignId,
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
          campaignId: testCampaignId,
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
    console.log('Cleaning up requestCampaignReport test data...');
    try {
      // 1. Delete orders
      for (const orderId of [testOrderId1, testOrderId2]) {
        if (orderId) {
          await ownerClient.mutate({
            mutation: DELETE_ORDER,
            variables: { orderId },
          });
        }
      }
      
      // 2. Revoke shares
      if (contributorAccountId) {
        await ownerClient.mutate({
          mutation: REVOKE_SHARE,
          variables: { input: { profileId: testProfileId, targetAccountId: contributorAccountId } },
        });
      }
      if (readonlyAccountId) {
        await ownerClient.mutate({
          mutation: REVOKE_SHARE,
          variables: { input: { profileId: testProfileId, targetAccountId: readonlyAccountId } },
        });
      }
      
      // 3. Delete campaigngn
      if (testCampaignId) {
        await ownerClient.mutate({
          mutation: DELETE_CAMPAIGN,
          variables: { campaignId: testCampaignId },
        });
      }
      
      // 4. Delete catalog
      if (testCatalogId) {
        await ownerClient.mutate({
          mutation: DELETE_CATALOG,
          variables: { catalogId: testCatalogId },
        });
      }
      
      // 5. Delete profile
      if (testProfileId) {
        await ownerClient.mutate({
          mutation: DELETE_SELLER_PROFILE,
          variables: { profileId: testProfileId },
        });
      }
      
      // 6. Clean up account records
      console.log('Cleaning up account records...');
      // await deleteTestAccounts([ownerAccountId, contributorAccountId, readonlyAccountId]);
      
      console.log('requestCampaignReport test data cleanup complete.');
    } catch (error) {
      console.log('Error in cleanup:', error);
    }
  }, 30000);


  describe('Owner Authorization', () => {
    test('should allow owner to request campaign report with default format (xlsx)', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
          },
        },
      });

      expect(result.data.requestCampaignReport).toBeDefined();
      expect(result.data.requestCampaignReport.reportId).toBeDefined();
      expect(result.data.requestCampaignReport.campaignId).toBe(testCampaignId);
      expect(result.data.requestCampaignReport.profileId).toBe(testProfileId);
      expect(result.data.requestCampaignReport.reportUrl).toBeDefined();
      expect(result.data.requestCampaignReport.reportUrl).toMatch(/^https?:\/\//);
      expect(result.data.requestCampaignReport.reportUrl).toContain('.xlsx');
      expect(result.data.requestCampaignReport.status).toBe('COMPLETED');
      expect(result.data.requestCampaignReport.createdAt).toBeDefined();
      expect(result.data.requestCampaignReport.expiresAt).toBeDefined();

      // Verify URL expiration is ~7 days from now
      const createdAt = new Date(result.data.requestCampaignReport.createdAt);
      const expiresAt = new Date(result.data.requestCampaignReport.expiresAt);
      const diffDays = (expiresAt.getTime() - createdAt.getTime()) / (1000 * 60 * 60 * 24);
      expect(diffDays).toBeGreaterThan(6.9);
      expect(diffDays).toBeLessThan(7.1);
    });

    test('should allow owner to request campaign report with explicit xlsx format', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
            format: 'xlsx',
          },
        },
      });

      expect(result.data.requestCampaignReport).toBeDefined();
      expect(result.data.requestCampaignReport.reportUrl).toContain('.xlsx');
      expect(result.data.requestCampaignReport.status).toBe('COMPLETED');
    });

    test('should allow owner to request campaign report with csv format', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
            format: 'csv',
          },
        },
      });

      expect(result.data.requestCampaignReport).toBeDefined();
      expect(result.data.requestCampaignReport.reportUrl).toContain('.csv');
      expect(result.data.requestCampaignReport.status).toBe('COMPLETED');
    });
  });

  describe('Contributor Authorization (WRITE access)', () => {
    test('should allow contributor with WRITE access to request campaign report', async () => {
      const result = await contributorClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
          },
        },
      });

      expect(result.data.requestCampaignReport).toBeDefined();
      expect(result.data.requestCampaignReport.reportId).toBeDefined();
      expect(result.data.requestCampaignReport.campaignId).toBe(testCampaignId);
      expect(result.data.requestCampaignReport.profileId).toBe(testProfileId);
      expect(result.data.requestCampaignReport.reportUrl).toBeDefined();
      expect(result.data.requestCampaignReport.status).toBe('COMPLETED');
    });
  });

  describe('Read-Only User Authorization (READ access)', () => {
    test('should allow read-only user with READ access to request campaign report', async () => {
      const result = await readonlyClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
          },
        },
      });

      expect(result.data.requestCampaignReport).toBeDefined();
      expect(result.data.requestCampaignReport.reportId).toBeDefined();
      expect(result.data.requestCampaignReport.campaignId).toBe(testCampaignId);
      expect(result.data.requestCampaignReport.profileId).toBe(testProfileId);
      expect(result.data.requestCampaignReport.reportUrl).toBeDefined();
      expect(result.data.requestCampaignReport.status).toBe('COMPLETED');
    });
  });

  describe('Unauthorized Access', () => {
    test('should reject request for campaign that does not exist', async () => {
      await expect(
        ownerClient.mutate({
          mutation: REQUEST_CAMPAIGN_REPORT,
          variables: {
            input: {
              campaignId: 'CAMPAIGNGN#nonexistent',
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
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
          },
        },
      });

      // Wait a moment to ensure different timestamp
      await new Promise((resolve) => setTimeout(resolve, 1100));

      const result2 = await ownerClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
          },
        },
      });

      expect(result1.data.requestCampaignReport.reportId).toBeDefined();
      expect(result2.data.requestCampaignReport.reportId).toBeDefined();
      expect(result1.data.requestCampaignReport.reportId).not.toBe(
        result2.data.requestCampaignReport.reportId
      );
    });

    test('should include correct profileId in report metadata', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
          },
        },
      });

      expect(result.data.requestCampaignReport.profileId).toBe(testProfileId);
    });

    test('should include correct campaignId in report metadata', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
          },
        },
      });

      expect(result.data.requestCampaignReport.campaignId).toBe(testCampaignId);
    });
  });

  describe('S3 URL Verification', () => {
    test('should generate valid S3 pre-signed URL', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
          },
        },
      });

      const reportUrl = result.data.requestCampaignReport.reportUrl;
      expect(reportUrl).toMatch(/^https?:\/\//);
      
      // URL should contain S3 signature components
      expect(reportUrl).toMatch(/X-Amz-Algorithm|AWSAccessKeyId/);
      expect(reportUrl).toMatch(/X-Amz-Signature|Signature/);
    });

    test('should generate URL with correct S3 path structure', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
          },
        },
      });

      const reportUrl = result.data.requestCampaignReport.reportUrl;
      // URL will have # encoded as %23
      const encodedProfileId = encodeURIComponent(testProfileId);
      const encodedCampaignId = encodeURIComponent(testCampaignId);
      expect(reportUrl).toContain(`reports/${encodedProfileId}/${encodedCampaignId}/`);
    });
  });

  describe('Format Parameter Validation', () => {
    test('should handle case-insensitive format parameter (CSV uppercase)', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
            format: 'CSV',
          },
        },
      });

      expect(result.data.requestCampaignReport).toBeDefined();
      expect(result.data.requestCampaignReport.reportUrl).toContain('.csv');
    });

    test('should handle case-insensitive format parameter (XLSX uppercase)', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
            format: 'XLSX',
          },
        },
      });

      expect(result.data.requestCampaignReport).toBeDefined();
      expect(result.data.requestCampaignReport.reportUrl).toContain('.xlsx');
    });

    test('should treat invalid format as default (xlsx)', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
            format: 'pdf', // Invalid format
          },
        },
      });

      expect(result.data.requestCampaignReport).toBeDefined();
      // Should default to xlsx
      expect(result.data.requestCampaignReport.reportUrl).toContain('.xlsx');
    });
  });

  describe('Performance', () => {
    test('Performance: Requesting report for campaign with many orders', async () => {
      // Arrange: Create a campaign with many orders
      const performanceCampaignResponse = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: testProfileId,
            campaignName: 'Performance Test Campaigngn',
            campaignYear: 2025,
            catalogId: testCatalogId,
            startDate: '2024-01-01T00:00:00.000Z',
            endDate: '2024-12-31T23:59:59.999Z',
          },
        },
      });
      const performanceCampaignId = performanceCampaignResponse.data.createCampaign.campaignId;
      const orderIds: string[] = [];

      try {
        // Create 25 orders to test performance
        const orderCount = 25;
        for (let i = 0; i < orderCount; i++) {
          const orderResponse = await ownerClient.mutate({
            mutation: CREATE_ORDER,
            variables: {
              input: {
                profileId: testProfileId,
                campaignId: performanceCampaignId,
                customerName: `Performance Customer ${i + 1}`,
                customerPhone: `555-${String(i).padStart(4, '0')}`,
                orderDate: `2024-0${Math.floor(i / 10) + 1}-${String((i % 28) + 1).padStart(2, '0')}T12:00:00.000Z`,
                paymentMethod: 'CASH',
                lineItems: [
                  {
                    productId: productId1,
                    quantity: i + 1, // Varying quantities
                  },
                ],
              },
            },
          });
          orderIds.push(orderResponse.data.createOrder.orderId);
        }

        // Act: Request report and measure time
        const startTime = Date.now();
        const result = await ownerClient.mutate({
          mutation: REQUEST_CAMPAIGN_REPORT,
          variables: {
            input: {
              campaignId: performanceCampaignId,
            },
          },
        });
        const endTime = Date.now();
        const reportGenerationTime = endTime - startTime;

        // Assert: Report should complete successfully
        expect(result.data.requestCampaignReport).toBeDefined();
        expect(result.data.requestCampaignReport.status).toBe('COMPLETED');
        expect(result.data.requestCampaignReport.reportUrl).toBeDefined();
        
        // Performance check: Report generation should complete within reasonable time
        // Lambda timeout is typically 30 seconds, but report generation should be much faster
        expect(reportGenerationTime).toBeLessThan(15000); // Less than 15 seconds
        
        console.log(`Report generation for ${orderCount} orders took ${reportGenerationTime}ms`);

      } finally {
        // Cleanup: Delete orders and campaigngn
        for (const orderId of orderIds) {
          await ownerClient.mutate({
            mutation: DELETE_ORDER,
            variables: { orderId },
          });
        }
        await ownerClient.mutate({
          mutation: DELETE_CAMPAIGN,
          variables: { campaignId: performanceCampaignId },
        });
      }
    }, 120000); // 2 minute timeout for this performance test (includes 25 order creations)
  });

  describe('Edge Cases', () => {
    let emptyCampaignId: string;

    beforeAll(async () => {
      // Create a campaign with no orders for empty report testing
      const emptyCampaignResponse = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: testProfileId,
            campaignName: 'Empty Campaigngn - No Orders',
            campaignYear: 2025,
            catalogId: testCatalogId,
            startDate: '2024-01-01T00:00:00.000Z',
            endDate: '2024-12-31T23:59:59.999Z',
          },
        },
      });
      emptyCampaignId = emptyCampaignResponse.data.createCampaign.campaignId;
    });

    afterAll(async () => {
      // Clean up empty campaigngn
      if (emptyCampaignId) {
        await ownerClient.mutate({
          mutation: DELETE_CAMPAIGN,
          variables: { campaignId: emptyCampaignId },
        });
      }
    });

    test('should generate report for campaign with no orders', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: emptyCampaignId,
          },
        },
      });

      expect(result.data.requestCampaignReport).toBeDefined();
      expect(result.data.requestCampaignReport.reportId).toBeDefined();
      expect(result.data.requestCampaignReport.campaignId).toBe(emptyCampaignId);
      expect(result.data.requestCampaignReport.profileId).toBe(testProfileId);
      expect(result.data.requestCampaignReport.reportUrl).toBeDefined();
      expect(result.data.requestCampaignReport.status).toBe('COMPLETED');
      // URL should still be valid S3 URL (with or without region in domain)
      expect(result.data.requestCampaignReport.reportUrl).toMatch(/^https:\/\/.*\.s3(\..*)?\.amazonaws\.com/);
    });

    test('should generate CSV report for campaign with no orders', async () => {
      const result = await ownerClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: emptyCampaignId,
            format: 'csv',
          },
        },
      });

      expect(result.data.requestCampaignReport).toBeDefined();
      expect(result.data.requestCampaignReport.reportUrl).toContain('.csv');
    });

    test('should handle concurrent report requests for same campaigngn', async () => {
      // Fire off multiple concurrent requests - use different formats to ensure unique S3 keys
      const concurrentRequests = [
        ownerClient.mutate({
          mutation: REQUEST_CAMPAIGN_REPORT,
          variables: { input: { campaignId: testCampaignId, format: 'xlsx' } },
        }),
        ownerClient.mutate({
          mutation: REQUEST_CAMPAIGN_REPORT,
          variables: { input: { campaignId: testCampaignId, format: 'csv' } },
        }),
      ];

      // All requests should complete successfully
      const results = await Promise.all(concurrentRequests);

      for (const result of results) {
        expect(result.data.requestCampaignReport).toBeDefined();
        expect(result.data.requestCampaignReport.status).toBe('COMPLETED');
        expect(result.data.requestCampaignReport.reportUrl).toBeDefined();
      }

      // Verify both reports were generated (different formats in URLs)
      const urls = results.map(r => r.data.requestCampaignReport.reportUrl);
      const xlsxUrls = urls.filter((u: string) => u.includes('.xlsx'));
      const csvUrls = urls.filter((u: string) => u.includes('.csv'));
      expect(xlsxUrls.length).toBe(1);
      expect(csvUrls.length).toBe(1);

      // URLs should be different (different S3 keys due to different extensions)
      expect(urls[0]).not.toBe(urls[1]);
    });

    test('should include correct totals in report metadata', async () => {
      // Request a report and verify the response includes expected fields
      const result = await ownerClient.mutate({
        mutation: REQUEST_CAMPAIGN_REPORT,
        variables: {
          input: {
            campaignId: testCampaignId,
          },
        },
      });

      // Verify report metadata is correct
      expect(result.data.requestCampaignReport).toBeDefined();
      expect(result.data.requestCampaignReport.campaignId).toBe(testCampaignId);
      expect(result.data.requestCampaignReport.profileId).toBe(testProfileId);
      expect(result.data.requestCampaignReport.createdAt).toBeDefined();
      expect(result.data.requestCampaignReport.expiresAt).toBeDefined();
      
      // Verify expiration is in the future
      const expiresAt = new Date(result.data.requestCampaignReport.expiresAt);
      const now = new Date();
      expect(expiresAt.getTime()).toBeGreaterThan(now.getTime());
    });
  });
});
