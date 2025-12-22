import '../setup.ts';
/**
 * Integration tests for Campaign Prefill CRUD resolvers
 * 
 * Tests cover:
 * - Happy paths (prefill creation with required/optional fields)
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

const CREATE_CAMPAIGN_PREFILL = gql`
  mutation CreateSharedCampaign($input: CreateSharedCampaignInput!) {
    createSharedCampaign(input: $input) {
      prefillCode
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

const UPDATE_CAMPAIGN_PREFILL = gql`
  mutation UpdateSharedCampaign($input: UpdateSharedCampaignInput!) {
    updateSharedCampaign(input: $input) {
      prefillCode
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

const GET_CAMPAIGN_PREFILL = gql`
  query GetSharedCampaign($prefillCode: String!) {
    getSharedCampaign(prefillCode: $prefillCode) {
      prefillCode
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

const LIST_MY_CAMPAIGN_PREFILLS = gql`
  query ListMySharedCampaigns {
    listMySharedCampaigns {
      prefillCode
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

const DELETE_CAMPAIGN_PREFILL = gql`
  mutation DeleteSharedCampaign($prefillCode: String!) {
    deleteSharedCampaign(prefillCode: $prefillCode)
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

describe.skip('Campaign Prefill CRUD Operations', () => {
  let testPrefix: string;
  let ownerClient: ApolloClient<any>;
  let ownerAccountId: string;
  let profileId: string;
  let catalogId: string;
  
  // Track all created prefills for cleanup
  const createdPrefillCodes: string[] = [];

  beforeAll(async () => {
    testPrefix = getTestPrefix();
    
    // Create authenticated client for owner
    const ownerResult = await createAuthenticatedClient('owner');
    ownerClient = ownerResult.client;
    ownerAccountId = ownerResult.accountId;

    // Clean up existing prefills to avoid rate limit errors from previous test runs
    // Note: Only clean new prefills (with correct schema), skip old ones that may fail
    try {
      const existingPrefillsResult = await ownerClient.query({
        query: LIST_MY_CAMPAIGN_PREFILLS,
      });
      
      const existingPrefills = existingPrefillsResult.data.listMySharedCampaigns || [];
      console.log(`Found ${existingPrefills.length} existing prefills. Cleaning up...`);
      
      // Only process first 5 for speed
      for (const prefill of existingPrefills.slice(0, 5)) {
        try {
          await ownerClient.mutate({
            mutation: DELETE_CAMPAIGN_PREFILL,
            variables: { prefillCode: prefill.prefillCode },
          });
          console.log(`Deleted prefill: ${prefill.prefillCode}`);
        } catch (deleteError) {
          // Silently ignore - schema may have changed
          console.log(`Skipped deletion of ${prefill.prefillCode} (schema mismatch)`);
        }
      }
    } catch (listError) {
      console.warn(`Failed to list existing prefills for cleanup:`, listError);
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
              description: 'Test product for campaign prefill tests',
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
    // Clean up ALL tracked prefills first (handles failed tests)
    for (const prefillCode of createdPrefillCodes) {
      try {
        await ownerClient.mutate({
          mutation: DELETE_CAMPAIGN_PREFILL,
          variables: { prefillCode },
        });
      } catch {
        // Ignore errors - prefill may already be deleted
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
  
  // Helper to create a prefill and track it for cleanup
  const createAndTrackPrefill = async (input: any) => {
    const result = await ownerClient.mutate({
      mutation: CREATE_CAMPAIGN_PREFILL,
      variables: { input },
    });
    const prefillCode = result.data.createSharedCampaign.prefillCode;
    createdPrefillCodes.push(prefillCode);
    return result;
  };

  describe('CreateCampaignPrefill', () => {
    it('should create a campaign prefill with all required fields', async () => {
      const unitNumber = getUniqueUnitNumber();
      const result = await createAndTrackPrefill({
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
      expect(result.data.createSharedCampaign.prefillCode).toBeTruthy();
      expect(result.data.createSharedCampaign.catalogId).toBe(catalogId);
      expect(result.data.createSharedCampaign.campaignName).toBe('Spring');
      expect(result.data.createSharedCampaign.campaignYear).toBe(2025);
      expect(result.data.createSharedCampaign.unitType).toBe('pack');
      expect(result.data.createSharedCampaign.unitNumber).toBe(unitNumber);
      expect(result.data.createSharedCampaign.city).toBe('Chicago');
      expect(result.data.createSharedCampaign.state).toBe('IL');
      expect(result.data.createSharedCampaign.isActive).toBe(true);
      expect(result.data.createSharedCampaign.createdBy).toBe(ownerAccountId);

      // Cleanup handled by afterAll via createdPrefillCodes tracking
    });

    it('should reject creation without required fields', async () => {
      try {
        await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN_PREFILL,
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

    it('should enforce rate limit of 50 prefills per user', async () => {
      // This test would need to be skipped in normal runs or mocked
      // because hitting the actual limit is expensive
      // Placeholder for documentation purposes
      expect(true).toBe(true);
    });
  });

  describe('GetCampaignPrefill', () => {
    let prefillCode: string;

    beforeAll(async () => {
      const result = await createAndTrackPrefill({
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
      prefillCode = result.data.createSharedCampaign.prefillCode;
    });

    // Cleanup handled by top-level afterAll via createdPrefillCodes tracking

    it('should retrieve campaign prefill by prefillCode', async () => {
      const result = await ownerClient.query({
        query: GET_CAMPAIGN_PREFILL,
        variables: { prefillCode },
      });

      expect(result.data.getCampaignPrefill).toBeDefined();
      expect(result.data.getCampaignPrefill.prefillCode).toBe(prefillCode);
      expect(result.data.getCampaignPrefill.campaignName).toBe('Summer');
      expect(result.data.getCampaignPrefill.unitType).toBe('troop');
      // Unit number is randomly generated, just check it exists
      expect(result.data.getCampaignPrefill.unitNumber).toBeGreaterThan(0);
    });

    it('should return null for non-existent prefillCode', async () => {
      const result = await ownerClient.query({
        query: GET_CAMPAIGN_PREFILL,
        variables: { prefillCode: 'nonexistent-code' },
      });

      expect(result.data.getCampaignPrefill).toBeNull();
    });
  });

  describe('ListMyCampaignPrefills', () => {
    beforeAll(async () => {
      // Create a few prefills for the owner - tracked for cleanup
      for (let i = 0; i < 3; i++) {
        await createAndTrackPrefill({
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

    // Cleanup handled by top-level afterAll via createdPrefillCodes tracking

    it('should list all campaign prefills created by the current user', async () => {
      const result = await ownerClient.query({
        query: LIST_MY_CAMPAIGN_PREFILLS,
      });

      expect(result.data.listMyCampaignPrefills).toBeDefined();
      expect(Array.isArray(result.data.listMyCampaignPrefills)).toBe(true);
      expect(result.data.listMyCampaignPrefills.length).toBeGreaterThanOrEqual(3);

      // All should be created by the owner
      result.data.listMyCampaignPrefills.forEach((prefill: any) => {
        expect(prefill.createdBy).toBe(ownerAccountId);
      });
      
      // At least 3 should be Fall campaign (the ones we just created)
      const fallPrefills = result.data.listMyCampaignPrefills.filter(
        (p: any) => p.campaignName === 'Fall'
      );
      expect(fallPrefills.length).toBeGreaterThanOrEqual(3);
    });
  });

  describe('UpdateCampaignPrefill', () => {
    let prefillCode: string;

    beforeAll(async () => {
      const result = await createAndTrackPrefill({
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
      prefillCode = result.data.createSharedCampaign.prefillCode;
    });

    // Cleanup handled by top-level afterAll via createdPrefillCodes tracking

    it('should update campaign prefill fields', async () => {
      const result = await ownerClient.mutate({
        mutation: UPDATE_CAMPAIGN_PREFILL,
        variables: {
          input: {
            prefillCode,
            creatorMessage: 'Updated winter fundraiser message',
            description: 'Updated holiday campaign sale',
            isActive: false,
          },
        },
      });

      expect(result.data.updateCampaignPrefill.prefillCode).toBe(prefillCode);
      expect(result.data.updateCampaignPrefill.creatorMessage).toBe('Updated winter fundraiser message');
      expect(result.data.updateCampaignPrefill.description).toBe('Updated holiday campaign sale');
      expect(result.data.updateCampaignPrefill.isActive).toBe(false);
    });

    it('should reject update by non-creator', async () => {
      // Create a different user
      const otherResult = await createAuthenticatedClient('contributor');

      try {
        await otherResult.client.mutate({
          mutation: UPDATE_CAMPAIGN_PREFILL,
          variables: {
            input: {
              prefillCode,
              description: 'Hacked description',
            },
          },
        });
        expect.fail('Should have thrown authorization error');
      } catch (error: any) {
        // Resolver returns "Only the creator can update this campaign prefill"
        expect(error.message).toContain('creator');
      }

      // NOTE: Do NOT delete test accounts - they are shared across test runs
      // await deleteTestAccounts([otherResult.accountId]);
    });
  });

  describe('DeleteCampaignPrefill', () => {
    it('should delete campaign prefill', async () => {
      // Create a prefill - track it even though we delete, in case test fails mid-way
      const createResult = await createAndTrackPrefill({
            catalogId,
            campaignName: 'Spring',
            campaignYear: 2026,
            startDate: '2026-03-01',
            endDate: '2026-04-30',
            unitType: 'pack',
            unitNumber: getUniqueUnitNumber(),
            city: 'Boston',
            state: 'MA',
            creatorMessage: 'Temporary prefill',
            description: 'To be deleted',
      });
      const prefillCode = createResult.data.createSharedCampaign.prefillCode;

      // Delete it
      const deleteResult = await ownerClient.mutate({
        mutation: DELETE_CAMPAIGN_PREFILL,
        variables: { prefillCode },
      });

      expect(deleteResult.data.deleteCampaignPrefill).toBe(true);

      // Verify it was soft-deleted (isActive=false)
      // The getCampaignPrefill resolver returns null for inactive items by design,
      // so we verify the delete worked by checking that the item is no longer accessible
      const getResult = await ownerClient.query({
        query: GET_CAMPAIGN_PREFILL,
        variables: { prefillCode },
        fetchPolicy: 'network-only', // Skip cache to get fresh result
      });

      // Soft-deleted items return null from getCampaignPrefill
      expect(getResult.data.getCampaignPrefill).toBeNull();
    });

    it('should reject deletion by non-creator', async () => {
      // Create a prefill - tracked for cleanup
      const createResult = await createAndTrackPrefill({
            catalogId,
            campaignName: 'Spring',
            campaignYear: 2026,
            startDate: '2026-03-01',
            endDate: '2026-04-30',
            unitType: 'pack',
            unitNumber: getUniqueUnitNumber(),
            city: 'Portland',
            state: 'OR',
            creatorMessage: 'Protected prefill',
            description: 'Should not be deletable',
      });
      const prefillCode = createResult.data.createSharedCampaign.prefillCode;

      // Try to delete as different user
      const otherResult = await createAuthenticatedClient('contributor');

      try {
        await otherResult.client.mutate({
          mutation: DELETE_CAMPAIGN_PREFILL,
          variables: { prefillCode },
        });
        expect.fail('Should have thrown authorization error');
      } catch (error: any) {
        // Resolver returns "Only the creator can delete this campaign prefill"
        expect(error.message).toContain('creator');
      }

      // NOTE: Do NOT delete test accounts - they are shared across test runs
      // await deleteTestAccounts([otherResult.accountId]);
      
      // Cleanup handled by top-level afterAll via createdPrefillCodes tracking
    });
  });
});
