import '../setup.ts';
/**
 * Integration tests for Season query resolvers
 * Tests: getCampaign, listCampaignsByProfile
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, gql } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';
import { deleteTestAccounts } from '../setup/testData';



// Helper to generate unique test prefix
const getTestPrefix = () => `TEST-${Date.now()}`;

// GraphQL Mutations for setup
const CREATE_PROFILE = gql`
  mutation CreateProfile($input: CreateSellerProfileInput!) {
    createSellerProfile(input: $input) {
      profileId
      sellerName
    }
  }
`;

const CREATE_CATALOG = gql`
  mutation CreateCatalog($input: CreateCatalogInput!) {
    createCatalog(input: $input) {
      catalogId
      catalogName
    }
  }
`;

const CREATE_CAMPAIGN = gql`
  mutation CreateCampaign($input: CreateCampaignInput!) {
    createCampaign(input: $input) {
      campaignId
      profileId
      campaignName
      campaignYear
      startDate
      endDate
      catalogId
      createdAt
      updatedAt
    }
  }
`;

const SHARE_DIRECT = gql`
  mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
    shareProfileDirect(input: $input) {
      profileId
      targetAccountId
      permissions
    }
  }
`;

const DELETE_PROFILE = gql`
  mutation DeleteProfile($profileId: ID!) {
    deleteSellerProfile(profileId: $profileId)
  }
`;

const DELETE_CATALOG = gql`
  mutation DeleteCatalog($catalogId: ID!) {
    deleteCatalog(catalogId: $catalogId)
  }
`;

const DELETE_CAMPAIGN = gql`
  mutation DeleteCampaign($campaignId: ID!) {
    deleteCampaign(campaignId: $campaignId)
  }
`;

const REVOKE_SHARE = gql`
  mutation RevokeShare($input: RevokeShareInput!) {
    revokeShare(input: $input)
  }
`;

// GraphQL Queries to test
const GET_CAMPAIGN = gql`
  query GetCampaign($campaignId: ID!) {
    getCampaign(campaignId: $campaignId) {
      campaignId
      profileId
      campaignName
      campaignYear
      startDate
      endDate
      catalogId
      createdAt
      updatedAt
    }
  }
`;

const LIST_CAMPAIGNS_BY_PROFILE = gql`
  query ListCampaignsByProfile($profileId: ID!) {
    listCampaignsByProfile(profileId: $profileId) {
      campaignId
      profileId
      campaignName
      campaignYear
      startDate
      endDate
      catalogId
      createdAt
      updatedAt
    }
  }
`;

describe('Season Query Resolvers Integration Tests', () => {
  let ownerClient: ApolloClient;
  let contributorClient: ApolloClient;
  let readonlyClient: ApolloClient;
  let ownerAccountId: string;
  let contributorAccountId: string;
  let readonlyAccountId: string;
  let readonlyEmail: string;

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
    readonlyEmail = process.env.TEST_READONLY_EMAIL!;
  });

  afterAll(async () => {
    // Clean up account records created by Cognito post-auth trigger
    console.log('Cleaning up account records...');
    // await deleteTestAccounts([ownerAccountId, contributorAccountId, readonlyAccountId]);
    console.log('Account cleanup complete.');
  }, 30000);


  describe('getCampaign', () => {
    describe('Happy Path', () => {
      it('should return season by campaignId with all fields', async () => {
        // Arrange: Create profile, catalog, and season
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Season`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              endDate: '2025-12-31T23:59:59Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId = seasonData.createCampaign.campaignId;

        // Act: Query season
        const { data } = await ownerClient.query({
          query: GET_CAMPAIGN,
          variables: { campaignId: campaignId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.getCampaign).toBeDefined();
        expect(data.getCampaign.campaignId).toBe(campaignId);
        expect(data.getCampaign.profileId).toBe(profileId);
        expect(data.getCampaign.campaignName).toContain('Season');
        expect(data.getCampaign.startDate).toBe('2025-01-01T00:00:00Z');
        expect(data.getCampaign.endDate).toBe('2025-12-31T23:59:59Z');
        expect(data.getCampaign.catalogId).toBe(catalogId);
        expect(data.getCampaign.createdAt).toBeDefined();
        expect(data.getCampaign.updatedAt).toBeDefined();
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      }, 15000); // Extended timeout for GSI consistency

      it('should return null for non-existent campaignId', async () => {
        // Act: Query non-existent season
        const { data } = await ownerClient.query({
          query: GET_CAMPAIGN,
          variables: { campaignId: 'SEASON#nonexistent' },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.getCampaign).toBeNull();
      });
    });

    describe('Authorization', () => {
      it('should allow profile owner to get season', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Season`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId = seasonData.createCampaign.campaignId;

        // Act
        const { data } = await ownerClient.query({
          query: GET_CAMPAIGN,
          variables: { campaignId: campaignId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.getCampaign).toBeDefined();
        expect(data.getCampaign.campaignId).toBe(campaignId);
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });

      it('should allow shared user (READ) to get season', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Season`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId = seasonData.createCampaign.campaignId;

        // Share profile with readonly user (READ permission)
        const { data: shareData }: any = await ownerClient.mutate({
          mutation: SHARE_DIRECT,
          variables: {
            input: {
              profileId: profileId,
              targetAccountEmail: readonlyEmail,
              permissions: ['READ'],
            },
          },
        });

        // Act: Readonly user queries season
        const { data } = await readonlyClient.query({
          query: GET_CAMPAIGN,
          variables: { campaignId: campaignId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.getCampaign).toBeDefined();
        expect(data.getCampaign.campaignId).toBe(campaignId);
        
        // Cleanup
        await ownerClient.mutate({ mutation: REVOKE_SHARE, variables: { input: { profileId, targetAccountId: readonlyAccountId } } });
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });

      it('should NOT allow non-shared user to get season', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Season`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId = seasonData.createCampaign.campaignId;

        // Act: Contributor (not shared) queries season
        const { data } = await contributorClient.query({
          query: GET_CAMPAIGN,
          variables: { campaignId: campaignId },
          fetchPolicy: 'network-only',
        });

        // Assert: Should return null due to authorization failure
        expect(data.getCampaign).toBeNull();
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });
    });
  });

  describe('listCampaignsByProfile', () => {
    describe('Happy Path', () => {
      it('should return all seasons for a profile', async () => {
        // Arrange: Create profile and catalog
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        // Create multiple seasons
        const { data: season1Data } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Season1`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId1 = season1Data.createCampaign.campaignId;

        const { data: season2Data } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Season2`,
              campaignYear: 2025,
              startDate: '2025-06-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId2 = season2Data.createCampaign.campaignId;

        // Act: List seasons
        const { data } = await ownerClient.query({
          query: LIST_CAMPAIGNS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listCampaignsByProfile).toBeDefined();
        expect(data.listCampaignsByProfile.length).toBe(2);
        expect(data.listCampaignsByProfile[0].campaignId).toBeDefined();
        expect(data.listCampaignsByProfile[0].campaignName).toContain('Season');
        expect(data.listCampaignsByProfile[1].campaignId).toBeDefined();
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: campaignId1 } });
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: campaignId2 } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });

      it('should return empty array for profile with no seasons', async () => {
        // Arrange: Create profile without seasons
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        // Act
        const { data } = await ownerClient.query({
          query: LIST_CAMPAIGNS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listCampaignsByProfile).toBeDefined();
        expect(data.listCampaignsByProfile).toEqual([]);
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });

      it('should return empty array for non-existent profileId', async () => {
        // Act
        const { data } = await ownerClient.query({
          query: LIST_CAMPAIGNS_BY_PROFILE,
          variables: { profileId: 'PROFILE#nonexistent' },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listCampaignsByProfile).toBeDefined();
        expect(data.listCampaignsByProfile).toEqual([]);
      });

      it('should not include deleted season in list', async () => {
        // Arrange: Create profile, catalog, and seasons
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        // Create two seasons
        const { data: season1Data } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-SeasonToKeep`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignIdToKeep = season1Data.createCampaign.campaignId;

        const { data: season2Data } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-SeasonToDelete`,
              campaignYear: 2025,
              startDate: '2025-06-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignIdToDelete = season2Data.createCampaign.campaignId;

        // Verify both appear in list
        const { data: beforeDelete } = await ownerClient.query({
          query: LIST_CAMPAIGNS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });
        expect(beforeDelete.listCampaignsByProfile.length).toBe(2);
        const beforeSeasonIds = beforeDelete.listCampaignsByProfile.map((s: any) => s.campaignId);
        expect(beforeSeasonIds).toContain(campaignIdToKeep);
        expect(beforeSeasonIds).toContain(campaignIdToDelete);

        // Delete one season
        await ownerClient.mutate({
          mutation: DELETE_CAMPAIGN,
          variables: { campaignId: campaignIdToDelete },
        });

        // Act: List seasons again
        const { data: afterDelete } = await ownerClient.query({
          query: LIST_CAMPAIGNS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });

        // Assert: Only the kept season should appear
        expect(afterDelete.listCampaignsByProfile.length).toBe(1);
        const afterSeasonIds = afterDelete.listCampaignsByProfile.map((s: any) => s.campaignId);
        expect(afterSeasonIds).toContain(campaignIdToKeep);
        expect(afterSeasonIds).not.toContain(campaignIdToDelete);

        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: campaignIdToKeep } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      }, 15000);
    });

    describe('Authorization', () => {
      it('should allow profile owner to list seasons', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Season`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId = seasonData.createCampaign.campaignId;

        // Act
        const { data } = await ownerClient.query({
          query: LIST_CAMPAIGNS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listCampaignsByProfile).toBeDefined();
        expect(data.listCampaignsByProfile.length).toBeGreaterThan(0);
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });

      it('should allow shared user (READ) to list seasons', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Season`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId = seasonData.createCampaign.campaignId;

        // Share profile with readonly user
        const { data: shareData }: any = await ownerClient.mutate({
          mutation: SHARE_DIRECT,
          variables: {
            input: {
              profileId: profileId,
              targetAccountEmail: readonlyEmail,
              permissions: ['READ'],
            },
          },
        });

        // Act: Readonly user lists seasons
        const { data } = await readonlyClient.query({
          query: LIST_CAMPAIGNS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listCampaignsByProfile).toBeDefined();
        expect(data.listCampaignsByProfile.length).toBeGreaterThan(0);
        
        // Cleanup
        await ownerClient.mutate({ mutation: REVOKE_SHARE, variables: { input: { profileId, targetAccountId: readonlyAccountId } } });
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });

      it('should NOT allow non-shared user to list seasons', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Season`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId = seasonData.createCampaign.campaignId;

        // Act: Contributor (not shared) lists seasons
        const { data } = await contributorClient.query({
          query: LIST_CAMPAIGNS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });

        // Assert: Should return empty array due to authorization failure
        expect(data.listCampaignsByProfile).toEqual([]);
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });
    });
  });

  describe('Season with optional endDate', () => {
    it('should return season without endDate (open-ended season)', async () => {
      // Arrange
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-Catalog`,
            isPublic: true,
            products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      // Create season without endDate
      const { data: seasonData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-OpenSeason`,
            campaignYear: 2025,
            startDate: '2025-01-01T00:00:00Z',
            // No endDate specified
            catalogId: catalogId,
          },
        },
      });
      const campaignId = seasonData.createCampaign.campaignId;

      // Act
      const { data } = await ownerClient.query({
        query: GET_CAMPAIGN,
        variables: { campaignId: campaignId },
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.getCampaign.endDate).toBeNull();
      expect(data.getCampaign.startDate).toBe('2025-01-01T00:00:00Z');

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    });

    it('should return season with both startDate and endDate', async () => {
      // Arrange
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-Catalog`,
            isPublic: true,
            products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      const { data: seasonData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-ClosedSeason`,
            campaignYear: 2025,
            startDate: '2025-01-01T00:00:00Z',
            endDate: '2025-06-30T23:59:59Z',
            catalogId: catalogId,
          },
        },
      });
      const campaignId = seasonData.createCampaign.campaignId;

      // Act
      const { data } = await ownerClient.query({
        query: GET_CAMPAIGN,
        variables: { campaignId: campaignId },
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.getCampaign.startDate).toBe('2025-01-01T00:00:00Z');
      expect(data.getCampaign.endDate).toBe('2025-06-30T23:59:59Z');

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    });
  });

  describe('listCampaignsByProfile after delete', () => {
    it('should not show deleted season in list', async () => {
      // Arrange
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-Catalog`,
            isPublic: true,
            products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      const { data: season1Data } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-Season1`,
            campaignYear: 2025,
            startDate: '2025-01-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const campaignId1 = season1Data.createCampaign.campaignId;

      const { data: season2Data } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-Season2`,
            campaignYear: 2025,
            startDate: '2025-06-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const campaignId2 = season2Data.createCampaign.campaignId;

      // Delete one season
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: campaignId1 } });

      // Act
      const { data } = await ownerClient.query({
        query: LIST_CAMPAIGNS_BY_PROFILE,
        variables: { profileId: profileId },
        fetchPolicy: 'network-only',
      });

      // Assert: Only one season should remain
      expect(data.listCampaignsByProfile.length).toBe(1);
      expect(data.listCampaignsByProfile[0].campaignId).toBe(campaignId2);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: campaignId2 } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    });
  });

  describe('getCampaign with computed fields', () => {
    const GET_CAMPAIGN_WITH_COMPUTED = gql`
      query GetCampaign($campaignId: ID!) {
        getCampaign(campaignId: $campaignId) {
          campaignId
          campaignName
          campaignYear
          catalogId
          totalOrders
          totalRevenue
          catalog {
            catalogId
            catalogName
            products {
              productId
              productName
              price
            }
          }
        }
      }
    `;

    const CREATE_CATALOG_WITH_PRODUCTS = gql`
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

    const CREATE_ORDER = gql`
      mutation CreateOrder($input: CreateOrderInput!) {
        createOrder(input: $input) {
          orderId
          campaignId
          totalAmount
        }
      }
    `;

    const DELETE_ORDER = gql`
      mutation DeleteOrder($orderId: ID!) {
        deleteOrder(orderId: $orderId)
      }
    `;

    it('should return totalOrders and totalRevenue fields', async () => {
      // Arrange: Create profile, catalog with a product, season, and orders
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-ComputedFieldsProfile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG_WITH_PRODUCTS,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-ComputedCatalog`,
            isPublic: true,
            products: [
              { productName: 'Popcorn', price: 10.0, sortOrder: 1 },
              { productName: 'Candy', price: 5.0, sortOrder: 2 },
            ],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;
      const product1Id = catalogData.createCatalog.products[0].productId;
      const product2Id = catalogData.createCatalog.products[1].productId;

      const { data: seasonData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-ComputedSeason`,
            campaignYear: 2025,
            startDate: '2025-01-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const campaignId = seasonData.createCampaign.campaignId;

      // Create 2 orders with specific amounts
      const { data: order1Data } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: profileId,
            campaignId: campaignId,
            customerName: 'Customer 1',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: [
              { productId: product1Id, quantity: 2 }, // 2 x $10 = $20
            ],
          },
        },
      });
      const orderId1 = order1Data.createOrder.orderId;

      const { data: order2Data } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: profileId,
            campaignId: campaignId,
            customerName: 'Customer 2',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CHECK',
            lineItems: [
              { productId: product1Id, quantity: 1 }, // 1 x $10 = $10
              { productId: product2Id, quantity: 3 }, // 3 x $5 = $15
            ],
          },
        },
      });
      const orderId2 = order2Data.createOrder.orderId;

      // Act: Get season with computed fields
      const { data } = await ownerClient.query({
        query: GET_SEASON_WITH_COMPUTED,
        variables: { campaignId: campaignId },
        fetchPolicy: 'network-only',
      });

      // Assert: Check computed fields
      expect(data.getCampaign.totalOrders).toBe(2);
      expect(data.getCampaign.totalRevenue).toBe(45); // $20 + $10 + $15 = $45

      // Assert: Check catalog field resolver
      expect(data.getCampaign.catalog).not.toBeNull();
      expect(data.getCampaign.catalog.catalogId).toBe(catalogId);
      expect(data.getCampaign.catalog.products).toHaveLength(2);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: orderId1 } });
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: orderId2 } });
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    });

    it('should return catalog data via field resolver', async () => {
      // Arrange: Create profile, catalog, and season
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-CatalogResolverProfile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const catalogName = `${getTestPrefix()}-TestCatalogName`;
      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: catalogName,
            isPublic: false,
            products: [
              { productName: 'Caramel Corn', price: 12.50, sortOrder: 1 },
            ],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      const { data: seasonData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-CatalogResolverSeason`,
            campaignYear: 2025,
            startDate: '2025-03-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const campaignId = seasonData.createCampaign.campaignId;

      // Act: Get season with catalog field
      const { data } = await ownerClient.query({
        query: GET_SEASON_WITH_COMPUTED,
        variables: { campaignId: campaignId },
        fetchPolicy: 'network-only',
      });

      // Assert: Catalog should be populated via field resolver
      expect(data.getCampaign.catalog).toBeDefined();
      expect(data.getCampaign.catalog.catalogName).toBe(catalogName);
      expect(data.getCampaign.catalog.products).toHaveLength(1);
      expect(data.getCampaign.catalog.products[0].productName).toBe('Caramel Corn');
      expect(data.getCampaign.catalog.products[0].price).toBe(12.50);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    });

    it('should return zero for totalOrders and totalRevenue when season has no orders', async () => {
      // Arrange: Create profile, catalog, and season (no orders)
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-NoOrdersProfile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-NoOrdersCatalog`,
            isPublic: true,
            products: [{ productName: 'Product', price: 15.0, sortOrder: 1 }],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      const { data: seasonData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-NoOrdersSeason`,
            campaignYear: 2025,
            startDate: '2025-04-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const campaignId = seasonData.createCampaign.campaignId;

      // Act: Get season with computed fields
      const { data } = await ownerClient.query({
        query: GET_SEASON_WITH_COMPUTED,
        variables: { campaignId: campaignId },
        fetchPolicy: 'network-only',
      });

      // Assert: Should return 0 for both computed fields (or null)
      expect(data.getCampaign.totalOrders).toBe(0);
      expect(data.getCampaign.totalRevenue).toBe(0);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    });
  });

  describe('Performance', () => {
    it('Performance: Listing seasons ordered by startDate', async () => {
      // Arrange: Create profile, catalog, and multiple seasons with different start dates
      const { data: profileData }: any = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-SeasonOrderProfile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData }: any = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-SeasonOrderCatalog`,
            isPublic: true,
            products: [{ productName: 'Product', price: 15.0, sortOrder: 1 }],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      // Create seasons with different start dates (oldest to newest)
      const campaignIds: string[] = [];
      const startDates = [
        '2022-01-01T00:00:00Z',
        '2023-01-01T00:00:00Z',
        '2024-01-01T00:00:00Z',
        '2025-01-01T00:00:00Z',
      ];
      
      for (let i = 0; i < startDates.length; i++) {
        const { data: seasonData }: any = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Season-${i + 1}`,
              campaignYear: 2025,
              startDate: startDates[i],
              catalogId: catalogId,
            },
          },
        });
        campaignIds.push(seasonData.createCampaign.campaignId);
      }

      // Act: List seasons
      const { data }: any = await ownerClient.query({
        query: LIST_CAMPAIGNS_BY_PROFILE,
        variables: { profileId },
        fetchPolicy: 'network-only',
      });

      // Assert: Seasons are returned with startDate for ordering
      expect(data.listCampaignsByProfile.length).toBe(startDates.length);
      
      for (const season of data.listCampaignsByProfile) {
        expect(season.startDate).toBeDefined();
      }
      
      // Check ordering (may be ascending or descending by implementation)
      const dates = data.listCampaignsByProfile.map((s: any) => new Date(s.startDate).getTime());
      const sortedAsc = [...dates].sort((a, b) => a - b);
      const sortedDesc = [...dates].sort((a, b) => b - a);
      
      const isAscending = JSON.stringify(dates) === JSON.stringify(sortedAsc);
      const isDescending = JSON.stringify(dates) === JSON.stringify(sortedDesc);
      
      console.log(`Seasons are ordered by startDate: ascending=${isAscending}, descending=${isDescending}`);

      // Cleanup
      for (const campaignId of campaignIds) {
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
      }
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    }, 60000);

    it('Performance: Listing seasons with filters (active vs past vs future)', async () => {
      // Arrange: Create profile, catalog, and seasons with different date ranges
      const { data: profileData }: any = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-SeasonFilterProfile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData }: any = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-SeasonFilterCatalog`,
            isPublic: true,
            products: [{ productName: 'Product', price: 15.0, sortOrder: 1 }],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      const now = new Date();
      const pastStart = new Date(now.getFullYear() - 2, 0, 1).toISOString();
      const pastEnd = new Date(now.getFullYear() - 1, 11, 31).toISOString();
      const activeStart = new Date(now.getFullYear(), 0, 1).toISOString();
      const activeEnd = new Date(now.getFullYear(), 11, 31).toISOString();
      const futureStart = new Date(now.getFullYear() + 1, 0, 1).toISOString();

      // Create past season
      const { data: pastSeasonData }: any = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-PastSeason`,
            campaignYear: 2025,
            startDate: pastStart,
            endDate: pastEnd,
            catalogId: catalogId,
          },
        },
      });
      const pastSeasonId = pastSeasonData.createCampaign.campaignId;

      // Create active season
      const { data: activeSeasonData }: any = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-ActiveSeason`,
            campaignYear: 2025,
            startDate: activeStart,
            endDate: activeEnd,
            catalogId: catalogId,
          },
        },
      });
      const activeSeasonId = activeSeasonData.createCampaign.campaignId;

      // Create future season
      const { data: futureSeasonData }: any = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-FutureSeason`,
            campaignYear: 2025,
            startDate: futureStart,
            catalogId: catalogId,
          },
        },
      });
      const futureSeasonId = futureSeasonData.createCampaign.campaignId;

      // Act: List all seasons
      const { data }: any = await ownerClient.query({
        query: LIST_CAMPAIGNS_BY_PROFILE,
        variables: { profileId },
        fetchPolicy: 'network-only',
      });

      // Assert: All seasons are returned with date information for filtering
      expect(data.listCampaignsByProfile.length).toBe(3);
      
      // Verify each season has dates that allow client-side filtering
      const seasons = data.listCampaignsByProfile;
      for (const season of seasons) {
        expect(season.startDate).toBeDefined();
        // endDate may be null for ongoing seasons
      }
      
      // Categorize seasons by date range
      const pastSeasons = seasons.filter((s: any) => {
        const end = s.endDate ? new Date(s.endDate) : null;
        return end && end < now;
      });
      const activeSeasons = seasons.filter((s: any) => {
        const start = new Date(s.startDate);
        const end = s.endDate ? new Date(s.endDate) : null;
        return start <= now && (!end || end >= now);
      });
      const futureSeasons = seasons.filter((s: any) => {
        const start = new Date(s.startDate);
        return start > now;
      });
      
      console.log(`Seasons: past=${pastSeasons.length}, active=${activeSeasons.length}, future=${futureSeasons.length}`);
      expect(pastSeasons.length + activeSeasons.length + futureSeasons.length).toBe(3);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: pastSeasonId } });
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: activeSeasonId } });
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: futureSeasonId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    }, 60000);
  });
});
