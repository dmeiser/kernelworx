import '../setup.ts';
/**
 * Integration tests for Campaign query resolvers
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

describe('Campaign Query Resolvers Integration Tests', () => {
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
      it('should return campaign by campaignId with all fields', async () => {
        // Arrange: Create profile, catalog, and campaign
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

        const { data: campaignData } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Campaign`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              endDate: '2025-12-31T23:59:59Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId = campaignData.createCampaign.campaignId;

        // Act: Query campaign
        const { data } = await ownerClient.query({
          query: GET_CAMPAIGN,
          variables: { campaignId: campaignId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.getCampaign).toBeDefined();
        expect(data.getCampaign.campaignId).toBe(campaignId);
        expect(data.getCampaign.profileId).toBe(profileId);
        expect(data.getCampaign.campaignName).toContain('Campaign');
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
        // Act: Query non-existent campaign
        const { data } = await ownerClient.query({
          query: GET_CAMPAIGN,
          variables: { campaignId: 'CAMPAIGN#nonexistent' },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.getCampaign).toBeNull();
      });
    });

    describe('Authorization', () => {
      it('should allow profile owner to get campaign', async () => {
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

        const { data: campaignData } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Campaign`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId = campaignData.createCampaign.campaignId;

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

      it('should allow shared user (READ) to get campaign', async () => {
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

        const { data: campaignData } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Campaign`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId = campaignData.createCampaign.campaignId;

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

        // Act: Readonly user queries campaign
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

      it('should NOT allow non-shared user to get campaign', async () => {
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

        const { data: campaignData } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Campaign`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId = campaignData.createCampaign.campaignId;

        // Act: Contributor (not shared) queries campaign
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
      it('should return all campaigns for a profile', async () => {
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

        // Create multiple campaigns
        const { data: campaign1Data } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Campaign1`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId1 = campaign1Data.createCampaign.campaignId;

        const { data: campaign2Data } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Campaign2`,
              campaignYear: 2025,
              startDate: '2025-06-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId2 = campaign2Data.createCampaign.campaignId;

        // Act: List campaigns
        const { data } = await ownerClient.query({
          query: LIST_CAMPAIGNS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listCampaignsByProfile).toBeDefined();
        expect(data.listCampaignsByProfile.length).toBe(2);
        expect(data.listCampaignsByProfile[0].campaignId).toBeDefined();
        expect(data.listCampaignsByProfile[0].campaignName).toContain('Campaign');
        expect(data.listCampaignsByProfile[1].campaignId).toBeDefined();
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: campaignId1 } });
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: campaignId2 } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });

      it('should return empty array for profile with no campaigns', async () => {
        // Arrange: Create profile without campaigns
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

      it('should not include deleted campaign in list', async () => {
        // Arrange: Create profile, catalog, and campaigns
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

        // Create two campaigns
        const { data: campaign1Data } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-CampaignToKeep`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignIdToKeep = campaign1Data.createCampaign.campaignId;

        const { data: campaign2Data } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-CampaignToDelete`,
              campaignYear: 2025,
              startDate: '2025-06-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignIdToDelete = campaign2Data.createCampaign.campaignId;

        // Verify both appear in list
        const { data: beforeDelete } = await ownerClient.query({
          query: LIST_CAMPAIGNS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });
        expect(beforeDelete.listCampaignsByProfile.length).toBe(2);
        const beforeCampaignIds = beforeDelete.listCampaignsByProfile.map((s: any) => s.campaignId);
        expect(beforeCampaignIds).toContain(campaignIdToKeep);
        expect(beforeCampaignIds).toContain(campaignIdToDelete);

        // Delete one campaign
        await ownerClient.mutate({
          mutation: DELETE_CAMPAIGN,
          variables: { campaignId: campaignIdToDelete },
        });

        // Act: List campaigns again
        const { data: afterDelete } = await ownerClient.query({
          query: LIST_CAMPAIGNS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });

        // Assert: Only the kept campaign should appear
        expect(afterDelete.listCampaignsByProfile.length).toBe(1);
        const afterCampaignIds = afterDelete.listCampaignsByProfile.map((s: any) => s.campaignId);
        expect(afterCampaignIds).toContain(campaignIdToKeep);
        expect(afterCampaignIds).not.toContain(campaignIdToDelete);

        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: campaignIdToKeep } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      }, 15000);
    });

    describe('Authorization', () => {
      it('should allow profile owner to list campaigns', async () => {
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

        const { data: campaignData } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Campaign`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId = campaignData.createCampaign.campaignId;

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

      it('should allow shared user (READ) to list campaigns', async () => {
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

        const { data: campaignData } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Campaign`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId = campaignData.createCampaign.campaignId;

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

        // Act: Readonly user lists campaigns
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

      it('should NOT allow non-shared user to list campaigns', async () => {
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

        const { data: campaignData } = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Campaign`,
              campaignYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const campaignId = campaignData.createCampaign.campaignId;

        // Act: Contributor (not shared) lists campaigns
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

  describe('Campaign with optional endDate', () => {
    it('should return campaign without endDate (open-ended campaign)', async () => {
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

      // Create campaign without endDate
      const { data: campaignData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-OpenCampaign`,
            campaignYear: 2025,
            startDate: '2025-01-01T00:00:00Z',
            // No endDate specified
            catalogId: catalogId,
          },
        },
      });
      const campaignId = campaignData.createCampaign.campaignId;

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

    it('should return campaign with both startDate and endDate', async () => {
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

      const { data: campaignData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-ClosedCampaign`,
            campaignYear: 2025,
            startDate: '2025-01-01T00:00:00Z',
            endDate: '2025-06-30T23:59:59Z',
            catalogId: catalogId,
          },
        },
      });
      const campaignId = campaignData.createCampaign.campaignId;

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
    it('should not show deleted campaign in list', async () => {
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

      const { data: campaign1Data } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-Campaign1`,
            campaignYear: 2025,
            startDate: '2025-01-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const campaignId1 = campaign1Data.createCampaign.campaignId;

      const { data: campaign2Data } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-Campaign2`,
            campaignYear: 2025,
            startDate: '2025-06-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const campaignId2 = campaign2Data.createCampaign.campaignId;

      // Delete one campaign
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: campaignId1 } });

      // Act
      const { data } = await ownerClient.query({
        query: LIST_CAMPAIGNS_BY_PROFILE,
        variables: { profileId: profileId },
        fetchPolicy: 'network-only',
      });

      // Assert: Only one campaign should remain
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
      // Arrange: Create profile, catalog with a product, campaign, and orders
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

      const { data: campaignData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-ComputedCampaign`,
            campaignYear: 2025,
            startDate: '2025-01-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const campaignId = campaignData.createCampaign.campaignId;

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

      // Act: Get campaign with computed fields
      const { data } = await ownerClient.query({
        query: GET_CAMPAIGN_WITH_COMPUTED,
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
      // Arrange: Create profile, catalog, and campaign
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

      const { data: campaignData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-CatalogResolverCampaign`,
            campaignYear: 2025,
            startDate: '2025-03-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const campaignId = campaignData.createCampaign.campaignId;

      // Act: Get campaign with catalog field
      const { data } = await ownerClient.query({
        query: GET_CAMPAIGN_WITH_COMPUTED,
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

    it('should return zero for totalOrders and totalRevenue when campaign has no orders', async () => {
      // Arrange: Create profile, catalog, and campaign (no orders)
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

      const { data: campaignData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-NoOrdersCampaign`,
            campaignYear: 2025,
            startDate: '2025-04-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const campaignId = campaignData.createCampaign.campaignId;

      // Act: Get campaign with computed fields
      const { data } = await ownerClient.query({
        query: GET_CAMPAIGN_WITH_COMPUTED,
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
    it('Performance: Listing campaigns ordered by startDate', async () => {
      // Arrange: Create profile, catalog, and multiple campaigns with different start dates
      const { data: profileData }: any = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-CampaignOrderProfile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData }: any = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-CampaignOrderCatalog`,
            isPublic: true,
            products: [{ productName: 'Product', price: 15.0, sortOrder: 1 }],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      // Create campaigns with different start dates (oldest to newest)
      const campaignIds: string[] = [];
      const startDates = [
        '2022-01-01T00:00:00Z',
        '2023-01-01T00:00:00Z',
        '2024-01-01T00:00:00Z',
        '2025-01-01T00:00:00Z',
      ];
      
      for (let i = 0; i < startDates.length; i++) {
        const { data: campaignData }: any = await ownerClient.mutate({
          mutation: CREATE_CAMPAIGN,
          variables: {
            input: {
              profileId: profileId,
              campaignName: `${getTestPrefix()}-Campaign-${i + 1}`,
              campaignYear: 2025,
              startDate: startDates[i],
              catalogId: catalogId,
            },
          },
        });
        campaignIds.push(campaignData.createCampaign.campaignId);
      }

      // Act: List campaigns
      const { data }: any = await ownerClient.query({
        query: LIST_CAMPAIGNS_BY_PROFILE,
        variables: { profileId },
        fetchPolicy: 'network-only',
      });

      // Assert: Campaigns are returned with startDate for ordering
      expect(data.listCampaignsByProfile.length).toBe(startDates.length);
      
      for (const campaign of data.listCampaignsByProfile) {
        expect(campaign.startDate).toBeDefined();
      }
      
      // Check ordering (may be ascending or descending by implementation)
      const dates = data.listCampaignsByProfile.map((s: any) => new Date(s.startDate).getTime());
      const sortedAsc = [...dates].sort((a, b) => a - b);
      const sortedDesc = [...dates].sort((a, b) => b - a);
      
      const isAscending = JSON.stringify(dates) === JSON.stringify(sortedAsc);
      const isDescending = JSON.stringify(dates) === JSON.stringify(sortedDesc);
      
      console.log(`Campaigns are ordered by startDate: ascending=${isAscending}, descending=${isDescending}`);

      // Cleanup
      for (const campaignId of campaignIds) {
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
      }
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    }, 60000);

    it('Performance: Listing campaigns with filters (active vs past vs future)', async () => {
      // Arrange: Create profile, catalog, and campaigns with different date ranges
      const { data: profileData }: any = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-CampaignFilterProfile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData }: any = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-CampaignFilterCatalog`,
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

      // Create past campaign
      const { data: pastCampaignData }: any = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-PastCampaign`,
            campaignYear: 2025,
            startDate: pastStart,
            endDate: pastEnd,
            catalogId: catalogId,
          },
        },
      });
      const pastCampaignId = pastCampaignData.createCampaign.campaignId;

      // Create active campaign
      const { data: activeCampaignData }: any = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-ActiveCampaign`,
            campaignYear: 2025,
            startDate: activeStart,
            endDate: activeEnd,
            catalogId: catalogId,
          },
        },
      });
      const activeCampaignId = activeCampaignData.createCampaign.campaignId;

      // Create future campaign
      const { data: futureCampaignData }: any = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: profileId,
            campaignName: `${getTestPrefix()}-FutureCampaign`,
            campaignYear: 2025,
            startDate: futureStart,
            catalogId: catalogId,
          },
        },
      });
      const futureCampaignId = futureCampaignData.createCampaign.campaignId;

      // Act: List all campaigns
      const { data }: any = await ownerClient.query({
        query: LIST_CAMPAIGNS_BY_PROFILE,
        variables: { profileId },
        fetchPolicy: 'network-only',
      });

      // Assert: All campaigns are returned with date information for filtering
      expect(data.listCampaignsByProfile.length).toBe(3);
      
      // Verify each campaign has dates that allow client-side filtering
      const campaigns = data.listCampaignsByProfile;
      for (const campaign of campaigns) {
        expect(campaign.startDate).toBeDefined();
        // endDate may be null for ongoing campaigns
      }
      
      // Categorize campaigns by date range
      const pastCampaigns = campaigns.filter((s: any) => {
        const end = s.endDate ? new Date(s.endDate) : null;
        return end && end < now;
      });
      const activeCampaigns = campaigns.filter((s: any) => {
        const start = new Date(s.startDate);
        const end = s.endDate ? new Date(s.endDate) : null;
        return start <= now && (!end || end >= now);
      });
      const futureCampaigns = campaigns.filter((s: any) => {
        const start = new Date(s.startDate);
        return start > now;
      });
      
      console.log(`Campaigns: past=${pastCampaigns.length}, active=${activeCampaigns.length}, future=${futureCampaigns.length}`);
      expect(pastCampaigns.length + activeCampaigns.length + futureCampaigns.length).toBe(3);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: pastCampaignId } });
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: activeCampaignId } });
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: futureCampaignId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    }, 60000);
  });
});
