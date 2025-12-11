import '../setup.ts';
import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import { ApolloClient, gql, HttpLink, InMemoryCache } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';
import { cleanupTestData, getTestPrefix } from '../setup/testData';

// GraphQL Mutations
const CREATE_PROFILE = gql`
  mutation CreateSellerProfile($input: CreateSellerProfileInput!) {
    createSellerProfile(input: $input) {
      profileId
      sellerName
      ownerAccountId
      createdAt
      updatedAt
    }
  }
`;

const UPDATE_PROFILE = gql`
  mutation UpdateSellerProfile($input: UpdateSellerProfileInput!) {
    updateSellerProfile(input: $input) {
      profileId
      sellerName
      ownerAccountId
      updatedAt
    }
  }
`;

const DELETE_PROFILE = gql`
  mutation DeleteSellerProfile($profileId: ID!) {
    deleteSellerProfile(profileId: $profileId)
  }
`;

// GraphQL Queries
const GET_PROFILE = gql`
  query GetProfile($profileId: ID!) {
    getProfile(profileId: $profileId) {
      profileId
      sellerName
      ownerAccountId
      createdAt
      updatedAt
    }
  }
`;

const LIST_MY_PROFILES = gql`
  query ListMyProfiles {
    listMyProfiles {
      profileId
      sellerName
      ownerAccountId
      createdAt
      updatedAt
    }
  }
`;

describe('Profile Operations Integration Tests', () => {
  let ownerClient: ApolloClient<any>;
  let contributorClient: ApolloClient<any>;
  let readonlyClient: ApolloClient<any>;
  let ownerAccountId: string;
  let contributorAccountId: string;
  let readonlyAccountId: string;
  let testProfileId: string;

  // Helper to create unauthenticated client
  const createUnauthenticatedClient = () => {
    return new ApolloClient({
      link: new HttpLink({
        uri: process.env.VITE_APPSYNC_ENDPOINT,
      }),
      cache: new InMemoryCache(),
    });
  };

  beforeAll(async () => {
    // Create authenticated clients and get account IDs
    const ownerAuth: AuthenticatedClientResult = await createAuthenticatedClient('owner');
    const contributorAuth: AuthenticatedClientResult = await createAuthenticatedClient('contributor');
    const readonlyAuth: AuthenticatedClientResult = await createAuthenticatedClient('readonly');
    
    ownerClient = ownerAuth.client;
    contributorClient = contributorAuth.client;
    readonlyClient = readonlyAuth.client;
    ownerAccountId = ownerAuth.accountId;
    contributorAccountId = contributorAuth.accountId;
    readonlyAccountId = readonlyAuth.accountId;
  });

  afterEach(async () => {
    // Clean up test data after each test
    if (testProfileId) {
      await cleanupTestData({
        profileId: testProfileId,
      });
      testProfileId = '';
    }
  });

  describe('createSellerProfile (Lambda Resolver)', () => {
    it('creates profile with valid sellerName', async () => {
      // Act
      const profileName = `${getTestPrefix()}-TestProfile`;
      const { data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: {
          input: { sellerName: profileName },
        },
      });

      testProfileId = data.createSellerProfile.profileId;

      // Assert
      expect(data.createSellerProfile.profileId).toMatch(/^PROFILE#/);
      expect(data.createSellerProfile.sellerName).toBe(profileName);
      expect(data.createSellerProfile.ownerAccountId).toBe(ownerAccountId);
      expect(data.createSellerProfile.createdAt).toBeDefined();
      expect(data.createSellerProfile.updatedAt).toBeDefined();
    });

    it('auto-generates unique profileId', async () => {
      // Act
      const profileName1 = `${getTestPrefix()}-Profile1`;
      const profileName2 = `${getTestPrefix()}-Profile2`;
      
      const { data: data1 } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName1 } },
      });
      
      const { data: data2 } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName2 } },
      });

      // Clean up second profile
      await cleanupTestData({ profileId: data2.createSellerProfile.profileId });
      
      testProfileId = data1.createSellerProfile.profileId;

      // Assert
      expect(data1.createSellerProfile.profileId).not.toBe(data2.createSellerProfile.profileId);
    });

    it('sets ownerAccountId to current user', async () => {
      // Act
      const profileName = `${getTestPrefix()}-OwnershipTest`;
      const { data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });

      testProfileId = data.createSellerProfile.profileId;

      // Assert
      expect(data.createSellerProfile.ownerAccountId).toBe(ownerAccountId);
    });

    it('sets timestamps (createdAt, updatedAt)', async () => {
      // Act
      const profileName = `${getTestPrefix()}-TimestampTest`;
      const { data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });

      testProfileId = data.createSellerProfile.profileId;

      // Assert
      expect(data.createSellerProfile.createdAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
      expect(data.createSellerProfile.updatedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
      expect(data.createSellerProfile.createdAt).toBe(data.createSellerProfile.updatedAt);
    });

    it('authenticated user can create profile', async () => {
      // Act
      const profileName = `${getTestPrefix()}-AuthTest`;
      const { data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });

      testProfileId = data.createSellerProfile.profileId;

      // Assert
      expect(data.createSellerProfile).toBeDefined();
      expect(data.createSellerProfile.profileId).toBeTruthy();
    });

    it('unauthenticated user cannot create profile', async () => {
      // Arrange
      const unauthClient = createUnauthenticatedClient();
      const profileName = `${getTestPrefix()}-UnauthTest`;

      // Act & Assert
      await expect(
        unauthClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: profileName } },
        })
      ).rejects.toThrow();
    });

    it('rejects missing sellerName', async () => {
      // Act & Assert
      await expect(
        ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: {} },
        })
      ).rejects.toThrow();
    });

    it('accepts sellerName with special characters', async () => {
      // Act
      const profileName = `${getTestPrefix()}-Profile's & "Name"!`;
      const { data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });

      testProfileId = data.createSellerProfile.profileId;

      // Assert
      expect(data.createSellerProfile.sellerName).toBe(profileName);
    });

    it('accepts sellerName with spaces', async () => {
      // Act
      const profileName = `${getTestPrefix()} Test Profile With Spaces`;
      const { data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });

      testProfileId = data.createSellerProfile.profileId;

      // Assert
      expect(data.createSellerProfile.sellerName).toBe(profileName);
    });

    it('profile includes all required fields', async () => {
      // Act
      const profileName = `${getTestPrefix()}-CompleteFieldsTest`;
      const { data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });

      testProfileId = data.createSellerProfile.profileId;

      // Assert
      expect(data.createSellerProfile).toHaveProperty('profileId');
      expect(data.createSellerProfile).toHaveProperty('sellerName');
      expect(data.createSellerProfile).toHaveProperty('ownerAccountId');
      expect(data.createSellerProfile).toHaveProperty('createdAt');
      expect(data.createSellerProfile).toHaveProperty('updatedAt');
    });
  });

  describe('updateSellerProfile (VTL Resolver)', () => {
    it('updates profile sellerName', async () => {
      // Arrange: Create profile first
      const profileName = `${getTestPrefix()}-OriginalName`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act: Update profile
      const newName = `${getTestPrefix()}-UpdatedName`;
      const { data } = await ownerClient.mutate({
        mutation: UPDATE_PROFILE,
        variables: {
          input: {
            profileId: testProfileId,
            sellerName: newName,
          },
        },
      });

      // Assert
      expect(data.updateSellerProfile.sellerName).toBe(newName);
      expect(data.updateSellerProfile.profileId).toBe(testProfileId);
    });

    it('updates timestamp (updatedAt)', async () => {
      // Arrange: Create profile
      const profileName = `${getTestPrefix()}-TimestampTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;
      const originalUpdatedAt = createData.createSellerProfile.updatedAt;

      // Wait a moment to ensure timestamp differs
      await new Promise(resolve => setTimeout(resolve, 100));

      // Act: Update profile
      const newName = `${getTestPrefix()}-UpdatedForTimestamp`;
      const { data } = await ownerClient.mutate({
        mutation: UPDATE_PROFILE,
        variables: {
          input: {
            profileId: testProfileId,
            sellerName: newName,
          },
        },
      });

      // Assert
      expect(data.updateSellerProfile.updatedAt).toBeDefined();
      expect(data.updateSellerProfile.updatedAt).not.toBe(originalUpdatedAt);
    });

    it('profile owner can update profile', async () => {
      // Arrange
      const profileName = `${getTestPrefix()}-OwnerUpdateTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act
      const newName = `${getTestPrefix()}-OwnerUpdated`;
      const { data } = await ownerClient.mutate({
        mutation: UPDATE_PROFILE,
        variables: {
          input: {
            profileId: testProfileId,
            sellerName: newName,
          },
        },
      });

      // Assert
      expect(data.updateSellerProfile.sellerName).toBe(newName);
    });

    it('shared user with WRITE cannot update profile (owner only)', async () => {
      // Arrange: Create profile as owner
      const profileName = `${getTestPrefix()}-SharedWriteTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Share with contributor (WRITE access)
      const SHARE_DIRECT = gql`
        mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
          shareProfileDirect(input: $input) {
            shareId
          }
        }
      `;
      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL,
            permissions: ['WRITE'],
          },
        },
      });

      // Act & Assert: Contributor tries to update
      const newName = `${getTestPrefix()}-AttemptedUpdate`;
      await expect(
        contributorClient.mutate({
          mutation: UPDATE_PROFILE,
          variables: {
            input: {
              profileId: testProfileId,
              sellerName: newName,
            },
          },
        })
      ).rejects.toThrow();
    });

    it('shared user with READ cannot update profile', async () => {
      // Arrange: Create profile as owner
      const profileName = `${getTestPrefix()}-SharedReadTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Share with readonly (READ access)
      const SHARE_DIRECT = gql`
        mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
          shareProfileDirect(input: $input) {
            shareId
          }
        }
      `;
      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_READONLY_EMAIL,
            permissions: ['READ'],
          },
        },
      });

      // Act & Assert: Readonly tries to update
      const newName = `${getTestPrefix()}-AttemptedUpdate`;
      await expect(
        readonlyClient.mutate({
          mutation: UPDATE_PROFILE,
          variables: {
            input: {
              profileId: testProfileId,
              sellerName: newName,
            },
          },
        })
      ).rejects.toThrow();
    });

    it('non-shared user cannot update profile', async () => {
      // Arrange: Create profile as owner (don't share)
      const profileName = `${getTestPrefix()}-NotSharedTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act & Assert: Contributor (not shared) tries to update
      const newName = `${getTestPrefix()}-AttemptedUpdate`;
      await expect(
        contributorClient.mutate({
          mutation: UPDATE_PROFILE,
          variables: {
            input: {
              profileId: testProfileId,
              sellerName: newName,
            },
          },
        })
      ).rejects.toThrow();
    });

    it('unauthenticated user cannot update profile', async () => {
      // Arrange: Create profile
      const profileName = `${getTestPrefix()}-UnauthUpdateTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act & Assert
      const unauthClient = createUnauthenticatedClient();
      const newName = `${getTestPrefix()}-AttemptedUpdate`;
      await expect(
        unauthClient.mutate({
          mutation: UPDATE_PROFILE,
          variables: {
            input: {
              profileId: testProfileId,
              sellerName: newName,
            },
          },
        })
      ).rejects.toThrow();
    });

    it('rejects update with non-existent profileId', async () => {
      // Act & Assert
      const fakeProfileId = 'PROFILE#00000000-0000-0000-0000-000000000000';
      const newName = `${getTestPrefix()}-NonExistent`;
      await expect(
        ownerClient.mutate({
          mutation: UPDATE_PROFILE,
          variables: {
            input: {
              profileId: fakeProfileId,
              sellerName: newName,
            },
          },
        })
      ).rejects.toThrow();
    });

    it('rejects missing sellerName', async () => {
      // Arrange: Create profile
      const profileName = `${getTestPrefix()}-MissingNameTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act & Assert
      await expect(
        ownerClient.mutate({
          mutation: UPDATE_PROFILE,
          variables: {
          profileId: testProfileId,
        },
        })
      ).rejects.toThrow();
    });
  });

  describe('deleteSellerProfile (VTL Resolver)', () => {
    it('deletes existing profile', async () => {
      // Arrange: Create profile
      const profileName = `${getTestPrefix()}-DeleteTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act
      const { data } = await ownerClient.mutate({
        mutation: DELETE_PROFILE,
        variables: {
          profileId: testProfileId,
        },
      });

      // Assert
      expect(data.deleteSellerProfile).toBe(true);
      
      // Verify deletion via query - getProfile throws error for missing profiles
      await expect(
        ownerClient.query({
          query: GET_PROFILE,
          variables: { profileId: testProfileId },
          fetchPolicy: 'network-only',
        })
      ).rejects.toThrow(/Profile not found/);

      testProfileId = ''; // Clear so cleanup doesn't fail
    });

    it('returns true on successful deletion', async () => {
      // Arrange
      const profileName = `${getTestPrefix()}-DeleteSuccessTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act
      const { data } = await ownerClient.mutate({
        mutation: DELETE_PROFILE,
        variables: {
          profileId: testProfileId,
        },
      });

      // Assert
      expect(data.deleteSellerProfile).toBe(true);
      testProfileId = '';
    });

    it('profile owner can delete profile', async () => {
      // Arrange
      const profileName = `${getTestPrefix()}-OwnerDeleteTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act
      const { data } = await ownerClient.mutate({
        mutation: DELETE_PROFILE,
        variables: {
          profileId: testProfileId,
        },
      });

      // Assert
      expect(data.deleteSellerProfile).toBe(true);
      testProfileId = '';
    });

    it('shared user with WRITE cannot delete profile (owner only)', async () => {
      // Arrange: Create and share profile
      const profileName = `${getTestPrefix()}-SharedWriteDeleteTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      const SHARE_DIRECT = gql`
        mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
          shareProfileDirect(input: $input) {
            shareId
          }
        }
      `;
      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL,
            permissions: ['WRITE'],
          },
        },
      });

      // Act & Assert
      await expect(
        contributorClient.mutate({
          mutation: DELETE_PROFILE,
          variables: {
            profileId: testProfileId,
          },
        })
      ).rejects.toThrow();
    });

    it('shared user with READ cannot delete profile', async () => {
      // Arrange: Create and share profile
      const profileName = `${getTestPrefix()}-SharedReadDeleteTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      const SHARE_DIRECT = gql`
        mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
          shareProfileDirect(input: $input) {
            shareId
          }
        }
      `;
      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_READONLY_EMAIL,
            permissions: ['READ'],
          },
        },
      });

      // Act & Assert
      await expect(
        readonlyClient.mutate({
          mutation: DELETE_PROFILE,
          variables: {
            profileId: testProfileId,
          },
        })
      ).rejects.toThrow();
    });

    it('non-shared user cannot delete profile', async () => {
      // Arrange: Create profile (don't share)
      const profileName = `${getTestPrefix()}-NotSharedDeleteTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act & Assert
      await expect(
        contributorClient.mutate({
          mutation: DELETE_PROFILE,
          variables: {
            profileId: testProfileId,
          },
        })
      ).rejects.toThrow();
    });

    it('unauthenticated user cannot delete profile', async () => {
      // Arrange: Create profile
      const profileName = `${getTestPrefix()}-UnauthDeleteTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act & Assert
      const unauthClient = createUnauthenticatedClient();
      await expect(
        unauthClient.mutate({
          mutation: DELETE_PROFILE,
          variables: {
            profileId: testProfileId,
          },
        })
      ).rejects.toThrow();
    });
  });
});
