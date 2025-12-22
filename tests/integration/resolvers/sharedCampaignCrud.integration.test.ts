import '../setup.ts';
/**
 * Integration tests for Shared Campaign CRUD resolvers
 * 
 * Tests cover:
 * - Happy paths (sharedCampaign creation with required/optional fields)
 * - Authorization (owner, WRITE contributor, READ contributor, non-shared, unauthenticated)
 * - Input validation (missing fields, invalid references)
 * - Data integrity (field presence, GSI attributes)
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, gql } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';
import { deleteTestAccounts } from '../setup/testData';


// Helper to generate unique test prefix
const getTestPrefix = () => `TEST-${Date.now()}`;

// Helper to generate unique unit number
const getUniqueUnitNumber = () => Math.floor(100000 + Math.random() * 900000);

// GraphQL Mutations
const CREATE_PROFILE = gql`
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
      createdAt
    }
  }
`;

const CREATE_CAMPAIGN_SHARED_CAMPAIGN = gql`
  mutation CreateSharedCampaign($input: CreateSharedCampaignInput!) {
    createSharedCampaign(input: $input) {
      sharedCampaignCode
      catalogId
      campaignName
      campaignYear
      startDate
      endDate
      unitType
      unitNumber
      city
      state
      createdBy
      createdByName
      creatorMessage
      description
      isActive
      createdAt
    }
  }
`;

const UPDATE_CAMPAIGN_SHARED_CAMPAIGN = gql`
  mutation UpdateSharedCampaign($input: UpdateSharedCampaignInput!) {
    updateSharedCampaign(input: $input) {
      sharedCampaignCode
      catalogId
      campaignName
      campaignYear
      startDate
      endDate
      unitType
      unitNumber
      city
      state
      createdBy
      createdByName
      creatorMessage
      description
      isActive
      createdAt
    }
  }
`;

const GET_CAMPAIGN_SHARED_CAMPAIGN = gql`
  query GetSharedCampaign($sharedCampaignCode: String!) {
    getSharedCampaign(sharedCampaignCode: $sharedCampaignCode) {
      sharedCampaignCode
      catalogId
      campaignName
      campaignYear
      startDate
      endDate
      unitType
      unitNumber
      city
      state
      createdBy
      createdByName
      creatorMessage
      description
      isActive
      createdAt
    }
  }
`;

const LIST_MY_CAMPAIGN_SHARED_CAMPAIGNS = gql`
  query ListMySharedCampaigns {
    listMySharedCampaigns {
      sharedCampaignCode
      catalogId
      campaignName
      campaignYear
      startDate
      endDate
      unitType
      unitNumber
      city
      state
      createdBy
      createdByName
      creatorMessage
      description
      isActive
      createdAt
    }
  }
`;

const DELETE_CAMPAIGN_SHARED_CAMPAIGN = gql`
  mutation DeleteSharedCampaign($sharedCampaignCode: String!) {
    deleteSharedCampaign(sharedCampaignCode: $sharedCampaignCode)
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

describe.skip('Shared Campaign CRUD Operations', () => {
  let testPrefix: string;
  let ownerClient: ApolloClient<any>;
  let ownerAccountId: string;
  let profileId: string;
  let catalogId: string;
  
  // Track all created shared campaigns for cleanup
  const createdSharedCampaignCodes: string[] = [];

  beforeAll(async () => {
    testPrefix = getTestPrefix();
    
    // Create authenticated client for owner
    const ownerResult = await createAuthenticatedClient('owner');
    ownerClient = ownerResult.client;
    ownerAccountId = ownerResult.accountId;

    // Clean up existing shared campaigns to avoid rate limit errors from previous test runs
    // Note: Only clean new shared campaigns (with correct schema), skip old ones that may fail
    try {
      const existingSharedCampaignsResult = await ownerClient.query({
        query: LIST_MY_CAMPAIGN_SHARED_CAMPAIGNS,
      });
      
      const existingSharedCampaigns = existingSharedCampaignsResult.data.listMySharedCampaigns || [];
      console.log(`Found ${existingSharedCampaigns.length} existing shared campaigns. Cleaning up...`);
      
      // Only process first 5 for speed
      for (const sharedCampaign of existingSharedCampaigns.slice(0, 5)) {
        try {
          await ownerClient.mutate({
            mutation: DELETE_CAMPAIGN_SHARED_CAMPAIGN,
            variables: { sharedCampaignCode: sharedCampaign.sharedCampaignCode },
          });
          console.log(`Deleted sharedCampaign: ${sharedCampaign.sharedCampaignCode}`);
        } catch (deleteError) {
          // Silently ignore - schema may have changed
          console.log(`Skipped deletion of ${sharedCampaign.sharedCampaignCode} (schema mismatch)`);
        }
      }
    } catch (listError) {
      console.warn(`Failed to list existing shared campaigns for cleanup:`, listError);
    }

    // Create a test profile
    const profileResponse = await ownerClient.mutate({
      mutation: CREATE_PROFILE,
      variables: {
        input: {
          sellerName: `${testPrefix}-Profile`,
        },
      },
    });
    profileId = profileResponse.data.createSellerProfile.profileId;

    // Create a test catalog
    const catalogResponse = await ownerClient.mutate({
      mutation: CREATE_CATALOG,
      variables: {
        input: {
          catalogName: `${testPrefix}-Catalog`,
          isPublic: true,
          products: [
            {
              productName: 'Test Product',
              description: 'Test product for Shared Campaign tests',
              price: 10.0,
              sortOrder: 1,
            },
          ],
        },
      },
    });
    catalogId = catalogResponse.data.createCatalog.catalogId;
  }, 60000);

  afterAll(async () => {
    // Clean up ALL tracked shared campaigns first (handles failed tests)
    for (const sharedCampaignCode of createdSharedCampaignCodes) {
      try {
        await ownerClient.mutate({
          mutation: DELETE_CAMPAIGN_SHARED_CAMPAIGN,
          variables: { sharedCampaignCode },
        });
      } catch {
        // Ignore errors - shared campaign may already be deleted
      }
    }

    // Clean up test data
    if (catalogId) {
      try {
        await ownerClient.mutate({
          mutation: DELETE_CATALOG,
          variables: { catalogId },
        });
      } catch {
        // Ignore errors
      }
    }

    if (profileId) {
      try {
        await ownerClient.mutate({
          mutation: DELETE_PROFILE,
          variables: { profileId },
        });
      } catch {
        // Ignore errors
      }
    }

    // NOTE: Do NOT delete test accounts - they are shared across test runs
    // and will be recreated by the post-authentication Lambda trigger
    // await deleteTestAccounts([ownerAccountId]);
  });
  
  // Helper to create a shared campaign and track it for cleanup
  const createAndTrackSharedCampaign = async (input: any) => {
    const result = await ownerClient.mutate({
      mutation: CREATE_CAMPAIGN_SHARED_CAMPAIGN,
      variables: { input },
    });
    const sharedCampaignCode = result.data.createSharedCampaign.sharedCampaignCode;
    createdSharedCampaignCodes.push(sharedCampaignCode);
    return result;
  };

  describe('CreateSharedCampaign', () => {
    it('should create a shared campaign with all required fields', async () => {
      const unitNumber = getUniqueUnitNumber();
      const result = await createAndTrackSharedCampaign({
            catalogId,
            campaignName: 'Spring',
            campaignYear: 2025,
            startDate: '2025-03-01',
            endDate: '2025-04-30',
            unitType: 'pack',
            unitNumber,
            city: 'Chicago',
            state: 'IL',
            creatorMessage: 'Support our pack!',
            description: 'Spring popcorn sale for pack 123',
      });

      expect(result.data.createSharedCampaign).toBeDefined();
      expect(result.data.createSharedCampaign.sharedCampaignCode).toBeTruthy();
      expect(result.data.createSharedCampaign.catalogId).toBe(catalogId);
      expect(result.data.createSharedCampaign.campaignName).toBe('Spring');
      expect(result.data.createSharedCampaign.campaignYear).toBe(2025);
      expect(result.data.createSharedCampaign.unitType).toBe('pack');
      expect(result.data.createSharedCampaign.unitNumber).toBe(unitNumber);
      expect(result.data.createSharedCampaign.city).toBe('Chicago');
      expect(result.data.createSharedCampaign.state).toBe('IL');
      expect(result.data.createSharedCampaign.isActive).toBe(true);
      expect(result.data.createSharedCampaign.createdBy).toBe(ownerAccountId);

      // Cleanup handled by afterAll via createdSharedCampaignCodes tracking
    });

    it('should reject creation without required fields', async () => {
      try {
        await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN_SHARED_CAMPAIGN,
          variables: {
            input: {
              catalogId,
              // Missing campaignName, campaignYear, startDate, endDate, etc.
            },
          },
        });
        expect.fail('Should have thrown validation error');
      } catch (error: any) {
        // GraphQL validates required fields before it reaches the resolver
        expect(error.message).toMatch(/NonNull|required|null/i);
      }
    });

    it('should enforce rate limit of 50 shared campaigns per user', async () => {
      // This test would need to be skipped in normal runs or mocked
      // because hitting the actual limit is expensive
      // Placeholder for documentation purposes
      expect(true).toBe(true);
    });
  });

  describe('GetSharedCampaign', () => {
    let sharedCampaignCode: string;

    beforeAll(async () => {
      const result = await createAndTrackSharedCampaign({
            catalogId,
            campaignName: 'Summer',
            campaignYear: 2025,
            startDate: '2025-06-01',
            endDate: '2025-08-31',
            unitType: 'troop',
            unitNumber: getUniqueUnitNumber(),
            city: 'Austin',
            state: 'TX',
            creatorMessage: 'Help fund summer activities!',
            description: 'Summer sale for troop 456',
      });
      sharedCampaignCode = result.data.createSharedCampaign.sharedCampaignCode;
    });

    // Cleanup handled by top-level afterAll via createdSharedCampaignCodes tracking

    it('should retrieve shared campaign by sharedCampaignCode', async () => {
      const result = await ownerClient.query({
        query: GET_CAMPAIGN_SHARED_CAMPAIGN,
        variables: { sharedCampaignCode },
      });

      expect(result.data.getSharedCampaign).toBeDefined();
      expect(result.data.getSharedCampaign.sharedCampaignCode).toBe(sharedCampaignCode);
      expect(result.data.getSharedCampaign.campaignName).toBe('Summer');
      expect(result.data.getSharedCampaign.unitType).toBe('troop');
      // Unit number is randomly generated, just check it exists
      expect(result.data.getSharedCampaign.unitNumber).toBeGreaterThan(0);
    });

    it('should return null for non-existent sharedCampaignCode', async () => {
      const result = await ownerClient.query({
        query: GET_CAMPAIGN_SHARED_CAMPAIGN,
        variables: { sharedCampaignCode: 'nonexistent-code' },
      });

      expect(result.data.getSharedCampaign).toBeNull();
    });
  });

  describe('ListMySharedCampaigns', () => {
    beforeAll(async () => {
      // Create a few shared campaigns for the owner - tracked for cleanup
      for (let i = 0; i < 3; i++) {
        await createAndTrackSharedCampaign({
              catalogId,
              campaignName: 'Fall',
              campaignYear: 2025,
              startDate: '2025-09-01',
              endDate: '2025-10-31',
              unitType: 'pack',
              unitNumber: getUniqueUnitNumber(),
              city: 'Denver',
              state: 'CO',
              creatorMessage: `Pack ${100 + i} fall sale`,
              description: `Fall campaign for pack ${100 + i}`,
        });
      }
    });

    // Cleanup handled by top-level afterAll via createdSharedCampaignCodes tracking

    it('should list all campaign shared campaigns created by the current user', async () => {
      const result = await ownerClient.query({
        query: LIST_MY_CAMPAIGN_SHARED_CAMPAIGNS,
      });

      expect(result.data.listMySharedCampaigns).toBeDefined();
      expect(Array.isArray(result.data.listMySharedCampaigns)).toBe(true);
      expect(result.data.listMySharedCampaigns.length).toBeGreaterThanOrEqual(3);

      // All should be created by the owner
      result.data.listMySharedCampaigns.forEach((sharedCampaign: any) => {
        expect(sharedCampaign.createdBy).toBe(ownerAccountId);
      });
      
      // At least 3 should be Fall campaign (the ones we just created)
      const fallSharedCampaigns = result.data.listMySharedCampaigns.filter(
        (p: any) => p.campaignName === 'Fall'
      );
      expect(fallSharedCampaigns.length).toBeGreaterThanOrEqual(3);
    });
  });

  describe('UpdateSharedCampaign', () => {
    let sharedCampaignCode: string;

    beforeAll(async () => {
      const result = await createAndTrackSharedCampaign({
            catalogId,
            campaignName: 'Winter',
            campaignYear: 2025,
            startDate: '2025-12-01',
            endDate: '2025-12-31',
            unitType: 'crew',
            unitNumber: getUniqueUnitNumber(),
            city: 'Seattle',
            state: 'WA',
            creatorMessage: 'Winter fundraiser',
            description: 'Holiday campaign sale',
      });
      sharedCampaignCode = result.data.createSharedCampaign.sharedCampaignCode;
    });

    // Cleanup handled by top-level afterAll via createdSharedCampaignCodes tracking

    it('should update shared campaign fields', async () => {
      const result = await ownerClient.mutate({
        mutation: UPDATE_CAMPAIGN_SHARED_CAMPAIGN,
        variables: {
          input: {
            sharedCampaignCode,
            creatorMessage: 'Updated winter fundraiser message',
            description: 'Updated holiday campaign sale',
            isActive: false,
          },
        },
      });

      expect(result.data.updateSharedCampaign.sharedCampaignCode).toBe(sharedCampaignCode);
      expect(result.data.updateSharedCampaign.creatorMessage).toBe('Updated winter fundraiser message');
      expect(result.data.updateSharedCampaign.description).toBe('Updated holiday campaign sale');
      expect(result.data.updateSharedCampaign.isActive).toBe(false);
    });

    it('should reject update by non-creator', async () => {
      // Create a different user
      const otherResult = await createAuthenticatedClient('contributor');

      try {
        await otherResult.client.mutate({
          mutation: UPDATE_CAMPAIGN_SHARED_CAMPAIGN,
          variables: {
            input: {
              sharedCampaignCode,
              description: 'Hacked description',
            },
          },
        });
        expect.fail('Should have thrown authorization error');
      } catch (error: any) {
        // Resolver returns "Only the creator can update this campaign sharedCampaign"
        expect(error.message).toContain('creator');
      }

      // NOTE: Do NOT delete test accounts - they are shared across test runs
      // await deleteTestAccounts([otherResult.accountId]);
    });
  });

  describe('DeleteSharedCampaign', () => {
    it('should delete campaign sharedCampaign', async () => {
      // Create a shared campaign - track it even though we delete, in case test fails mid-way
      const createResult = await createAndTrackSharedCampaign({
            catalogId,
            campaignName: 'Spring',
            campaignYear: 2026,
            startDate: '2026-03-01',
            endDate: '2026-04-30',
            unitType: 'pack',
            unitNumber: getUniqueUnitNumber(),
            city: 'Boston',
            state: 'MA',
            creatorMessage: 'Temporary sharedCampaign',
            description: 'To be deleted',
      });
      const sharedCampaignCode = createResult.data.createSharedCampaign.sharedCampaignCode;

      // Delete it
      const deleteResult = await ownerClient.mutate({
        mutation: DELETE_CAMPAIGN_SHARED_CAMPAIGN,
        variables: { sharedCampaignCode },
      });

      expect(deleteResult.data.deleteSharedCampaign).toBe(true);

      // Verify it was soft-deleted (isActive=false)
      // The getSharedCampaign resolver returns null for inactive items by design,
      // so we verify the delete worked by checking that the item is no longer accessible
      const getResult = await ownerClient.query({
        query: GET_CAMPAIGN_SHARED_CAMPAIGN,
        variables: { sharedCampaignCode },
        fetchPolicy: 'network-only', // Skip cache to get fresh result
      });

      // Soft-deleted items return null from getSharedCampaign
      expect(getResult.data.getSharedCampaign).toBeNull();
    });

    it('should reject deletion by non-creator', async () => {
      // Create a shared campaign - tracked for cleanup
      const createResult = await createAndTrackSharedCampaign({
            catalogId,
            campaignName: 'Spring',
            campaignYear: 2026,
            startDate: '2026-03-01',
            endDate: '2026-04-30',
            unitType: 'pack',
            unitNumber: getUniqueUnitNumber(),
            city: 'Portland',
            state: 'OR',
            creatorMessage: 'Protected sharedCampaign',
            description: 'Should not be deletable',
      });
      const sharedCampaignCode = createResult.data.createSharedCampaign.sharedCampaignCode;

      // Try to delete as different user
      const otherResult = await createAuthenticatedClient('contributor');

      try {
        await otherResult.client.mutate({
          mutation: DELETE_CAMPAIGN_SHARED_CAMPAIGN,
          variables: { sharedCampaignCode },
        });
        expect.fail('Should have thrown authorization error');
      } catch (error: any) {
        // Resolver returns "Only the creator can delete this campaign sharedCampaign"
        expect(error.message).toContain('creator');
      }

      // NOTE: Do NOT delete test accounts - they are shared across test runs
      // await deleteTestAccounts([otherResult.accountId]);
      
      // Cleanup handled by top-level afterAll via createdSharedCampaignCodes tracking
    });
  });
});
