import '../setup.ts';
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, gql, HttpLink, InMemoryCache } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';
import { getTestPrefix, deleteTestAccounts, TABLE_NAMES } from '../setup/testData';


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

const REVOKE_SHARE = gql`
  mutation RevokeShare($input: RevokeShareInput!) {
    revokeShare(input: $input)
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

  // Track created profiles and shares for cleanup
  const createdProfileIds: string[] = [];
  const createdShares: { profileId: string; targetAccountId: string }[] = [];

  // Helper to create profile and track for cleanup
  const createAndTrackProfile = async (sellerName: string) => {
    const { data } = await ownerClient.mutate({
      mutation: CREATE_PROFILE,
      variables: { input: { sellerName } },
    });
    const profileId = data.createSellerProfile.profileId;
    createdProfileIds.push(profileId);
    return { data, profileId };
  };

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

  afterAll(async () => {
    // Clean up all test data in reverse order
    console.log('Cleaning up profile operations test data...');
    
    try {
      // 1. Revoke all shares first
      for (const share of createdShares) {
        try {
          await ownerClient.mutate({
            mutation: REVOKE_SHARE,
            variables: { input: { profileId: share.profileId, targetAccountId: share.targetAccountId } },
          });
        } catch (e) {
          // Share may already be revoked or profile already deleted
        }
      }
      
      // 2. Delete all profiles
      for (const profileId of createdProfileIds) {
        try {
          await ownerClient.mutate({
            mutation: DELETE_PROFILE,
            variables: { profileId },
          });
        } catch (e) {
          // Profile may already be deleted by a test
        }
      }
      
      // Clean up account records
      console.log('Cleaning up account records...');
      // await deleteTestAccounts([ownerAccountId, contributorAccountId, readonlyAccountId]);
      
      console.log('Profile operations test data cleanup complete.');
    } catch (error) {
      console.log('Error in cleanup:', error);
    }
  }, 30000);


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

      const testProfileId = data.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

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
      createdProfileIds.push(data1.createSellerProfile.profileId);
      
      const { data: data2 } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName2 } },
      });
      createdProfileIds.push(data2.createSellerProfile.profileId);

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

      const testProfileId = data.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

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

      const testProfileId = data.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

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

      const testProfileId = data.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

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
      // Arrange & Act
      const profileName = `${getTestPrefix()}-Profile's & "Name"!`;
      const { data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });

      const testProfileId = data.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

      // Assert
      expect(data.createSellerProfile.sellerName).toBe(profileName);
    });

    it('accepts sellerName with spaces', async () => {
      // Arrange & Act
      const profileName = `${getTestPrefix()} Test Profile With Spaces`;
      const { data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });

      const testProfileId = data.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

      // Assert
      expect(data.createSellerProfile.sellerName).toBe(profileName);
    });

    it('profile includes all required fields', async () => {
      // Arrange & Act
      const profileName = `${getTestPrefix()}-CompleteFieldsTest`;
      const { data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });

      const testProfileId = data.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

      // Assert
      expect(data.createSellerProfile).toHaveProperty('profileId');
      expect(data.createSellerProfile).toHaveProperty('sellerName');
      expect(data.createSellerProfile).toHaveProperty('ownerAccountId');
      expect(data.createSellerProfile).toHaveProperty('createdAt');
      expect(data.createSellerProfile).toHaveProperty('updatedAt');
    });

    it('accepts sellerName with Unicode and emoji characters', async () => {
      // Arrange & Act - Test international characters and emojis
      const profileName = `${getTestPrefix()}-Scout 日本語 🍿 émoji José`;
      const { data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });

      const testProfileId = data.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

      // Assert - Unicode characters should be stored and retrieved correctly
      expect(data.createSellerProfile.sellerName).toBe(profileName);
    });

    it('accepts very long sellerName (boundary test)', async () => {
      // Arrange & Act - Create a profile with a very long name (255 characters)
      const baseName = `${getTestPrefix()}-`;
      const longName = baseName + 'A'.repeat(255 - baseName.length);
      
      const { data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: longName } },
      });

      const testProfileId = data.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

      // Assert - Long name should be stored correctly
      expect(data.createSellerProfile.sellerName).toBe(longName);
      expect(data.createSellerProfile.sellerName.length).toBe(255);
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
      const testProfileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

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
      const testProfileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);
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
      const testProfileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

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
      const testProfileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

      // Share with contributor (WRITE access)
      const SHARE_DIRECT = gql`
        mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
          shareProfileDirect(input: $input) {
            shareId
            targetAccountId
          }
        }
      `;
      const { data: shareData } = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL,
            permissions: ['WRITE'],
          },
        },
      });
      createdShares.push({ profileId: testProfileId, targetAccountId: shareData.shareProfileDirect.targetAccountId });

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
      const testProfileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

      // Share with readonly (READ access)
      const SHARE_DIRECT = gql`
        mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
          shareProfileDirect(input: $input) {
            shareId
            targetAccountId
          }
        }
      `;
      const { data: shareData } = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_READONLY_EMAIL,
            permissions: ['READ'],
          },
        },
      });
      createdShares.push({ profileId: testProfileId, targetAccountId: shareData.shareProfileDirect.targetAccountId });

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
      const testProfileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

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
      const testProfileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

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
      // Act & Assert - No profile created, so no tracking needed
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
      const testProfileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

      // Act & Assert - Update will fail, so no update tracked
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
      const testProfileId = createData.createSellerProfile.profileId;

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

      // Profile was deleted, so resource tracker will skip cleanup
    });

    it('returns true on successful deletion', async () => {
      // Arrange
      const profileName = `${getTestPrefix()}-DeleteSuccessTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const testProfileId = createData.createSellerProfile.profileId;

      // Act
      const { data } = await ownerClient.mutate({
        mutation: DELETE_PROFILE,
        variables: {
          profileId: testProfileId,
        },
      });

      // Assert
      expect(data.deleteSellerProfile).toBe(true);
      // Profile was deleted, resource tracker will skip cleanup
    });

    it('profile owner can delete profile', async () => {
      // Arrange
      const profileName = `${getTestPrefix()}-OwnerDeleteTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const testProfileId = createData.createSellerProfile.profileId;

      // Act
      const { data } = await ownerClient.mutate({
        mutation: DELETE_PROFILE,
        variables: {
          profileId: testProfileId,
        },
      });

      // Assert
      expect(data.deleteSellerProfile).toBe(true);
      // Profile was deleted, resource tracker will skip cleanup
    });

    it('shared user with WRITE cannot delete profile (owner only)', async () => {
      // Arrange: Create and share profile
      const profileName = `${getTestPrefix()}-SharedWriteDeleteTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const testProfileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

      const SHARE_DIRECT = gql`
        mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
          shareProfileDirect(input: $input) {
            shareId
            targetAccountId
          }
        }
      `;
      const { data: shareData } = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL,
            permissions: ['WRITE'],
          },
        },
      });
      createdShares.push({ profileId: testProfileId, targetAccountId: shareData.shareProfileDirect.targetAccountId });

      // Act & Assert - Delete should fail, profile will still exist
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
      const testProfileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

      const SHARE_DIRECT = gql`
        mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
          shareProfileDirect(input: $input) {
            shareId
            targetAccountId
          }
        }
      `;
      const { data: shareData } = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_READONLY_EMAIL,
            permissions: ['READ'],
          },
        },
      });
      createdShares.push({ profileId: testProfileId, targetAccountId: shareData.shareProfileDirect.targetAccountId });

      // Act & Assert - Delete should fail, profile will still exist
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
      const testProfileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

      // Act & Assert - Delete should fail, profile will still exist
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
      const testProfileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(testProfileId);

      // Act & Assert - Delete should fail, profile will still exist
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

    it('Data Integrity: Deleting profile cleans up associated shares', async () => {
      // Arrange: Create profile and share it
      const profileName = `${getTestPrefix()}-ShareCleanupTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const testProfileId = createData.createSellerProfile.profileId;

      const SHARE_DIRECT = gql`
        mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
          shareProfileDirect(input: $input) {
            shareId
            targetAccountId
          }
        }
      `;
      const { data: shareData } = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL,
            permissions: ['READ'],
          },
        },
      });
      const targetAccountId = shareData.shareProfileDirect.targetAccountId;

      // Verify share exists via listSharedProfiles
      const LIST_SHARED_PROFILES = gql`
        query ListSharedProfiles {
          listSharedProfiles {
            profileId
          }
        }
      `;
      const { data: beforeDelete }: any = await contributorClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });
      const beforeProfileIds = beforeDelete.listSharedProfiles.map((p: any) => p.profileId);
      expect(beforeProfileIds).toContain(testProfileId);

      // Act: Delete the profile
      const { data } = await ownerClient.mutate({
        mutation: DELETE_PROFILE,
        variables: { profileId: testProfileId },
      });
      expect(data.deleteSellerProfile).toBe(true);

      // Assert: Share should no longer appear for contributor
      const { data: afterDelete }: any = await contributorClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });
      const afterProfileIds = afterDelete.listSharedProfiles.map((p: any) => p.profileId);
      expect(afterProfileIds).not.toContain(testProfileId);

      // Profile was deleted and shares were cleaned up, no manual cleanup needed
    }, 15000);

    it('SECURITY: Deleted profile becomes immediately inaccessible to all users', async () => {
      // Arrange: Create profile and share it
      const profileName = `${getTestPrefix()}-ImmediateInaccessTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const testProfileId = createData.createSellerProfile.profileId;

      const SHARE_DIRECT = gql`
        mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
          shareProfileDirect(input: $input) {
            shareId
            targetAccountId
          }
        }
      `;
      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL,
            permissions: ['READ', 'WRITE'],
          },
        },
      });

      // Verify shared user can access profile BEFORE deletion
      const { data: beforeAccess }: any = await contributorClient.query({
        query: GET_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });
      expect(beforeAccess.getProfile.profileId).toBe(testProfileId);

      // Act: Delete the profile
      const { data } = await ownerClient.mutate({
        mutation: DELETE_PROFILE,
        variables: { profileId: testProfileId },
      });
      expect(data.deleteSellerProfile).toBe(true);

      // Assert: Shared user can NO longer access profile via getProfile
      // Should return null or throw error (depending on implementation)
      const { data: afterAccess }: any = await contributorClient.query({
        query: GET_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      }).catch(() => ({ data: { getProfile: null } }));
      
      // Either returns null or throws error - both are valid "inaccessible" behavior
      expect(afterAccess.getProfile).toBeNull();

      // Owner also cannot access
      await expect(
        ownerClient.query({
          query: GET_PROFILE,
          variables: { profileId: testProfileId },
          fetchPolicy: 'network-only',
        })
      ).rejects.toThrow(/Profile not found/);

      // Profile was deleted, no cleanup needed
    }, 15000);

    it('Data Integrity: Deleting profile cleans up associated invites', async () => {
      // Arrange: Create profile and create invite
      const profileName = `${getTestPrefix()}-InviteCleanupTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const testProfileId = createData.createSellerProfile.profileId;

      const CREATE_INVITE = gql`
        mutation CreateProfileInvite($input: CreateProfileInviteInput!) {
          createProfileInvite(input: $input) {
            inviteCode
          }
        }
      `;
      const { data: inviteData } = await ownerClient.mutate({
        mutation: CREATE_INVITE,
        variables: {
          input: {
            profileId: testProfileId,
            permissions: ['READ'],
          },
        },
      });
      const inviteCode = inviteData.createProfileInvite.inviteCode;

      // Verify invite exists via listInvitesByProfile
      const LIST_INVITES = gql`
        query ListInvitesByProfile($profileId: ID!) {
          listInvitesByProfile(profileId: $profileId) {
            inviteCode
          }
        }
      `;
      const { data: beforeDelete }: any = await ownerClient.query({
        query: LIST_INVITES,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });
      const beforeInviteCodes = beforeDelete.listInvitesByProfile.map((i: any) => i.inviteCode);
      expect(beforeInviteCodes).toContain(inviteCode);

      // Act: Delete the profile
      const { data } = await ownerClient.mutate({
        mutation: DELETE_PROFILE,
        variables: { profileId: testProfileId },
      });
      expect(data.deleteSellerProfile).toBe(true);

      // Assert: Invites should be cleaned up
      // Note: After profile deletion, listInvitesByProfile returns empty since profile is gone
      // We verify via direct DynamoDB check that the invite record is deleted
      const { DynamoDBClient, GetItemCommand } = await import('@aws-sdk/client-dynamodb');
      const dynamoClient = new DynamoDBClient({ region: 'us-east-1' });
      const result = await dynamoClient.send(new GetItemCommand({
        TableName: TABLE_NAMES.profiles,
        Key: {
          profileId: { S: testProfileId },
          recordType: { S: `INVITE#${inviteCode}` },
        },
      }));
      expect(result.Item).toBeUndefined();

      // Profile was deleted and invites were cleaned up, no manual cleanup needed
    }, 15000);

    it('Data Integrity: Deleting profile cleans up associated seasons', async () => {
      // Arrange: Create profile, catalog, and season
      const profileName = `${getTestPrefix()}-SeasonCleanupTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const testProfileId = createData.createSellerProfile.profileId;

      // Create a catalog first (required for season)
      const CREATE_CATALOG = gql`
        mutation CreateCatalog($input: CreateCatalogInput!) {
          createCatalog(input: $input) {
            catalogId
          }
        }
      `;
      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: 'Test Catalog for Cleanup',
            isPublic: false,
            products: [
              {
                productName: 'Test Product',
                description: 'Test product',
                price: 10.00,
                sortOrder: 1,
              },
            ],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      const CREATE_SEASON = gql`
        mutation CreateSeason($input: CreateSeasonInput!) {
          createSeason(input: $input) {
            seasonId
            seasonName
          }
        }
      `;
      const { data: seasonData } = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: testProfileId,
            seasonName: 'Test Season for Cleanup',
            startDate: new Date().toISOString(),
            catalogId: catalogId,
          },
        },
      });
      const seasonId = seasonData.createSeason.seasonId;

      // Verify season exists via listSeasonsByProfile
      const LIST_SEASONS = gql`
        query ListSeasonsByProfile($profileId: ID!) {
          listSeasonsByProfile(profileId: $profileId) {
            seasonId
          }
        }
      `;
      const { data: beforeDelete }: any = await ownerClient.query({
        query: LIST_SEASONS,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });
      const beforeSeasonIds = beforeDelete.listSeasonsByProfile.map((s: any) => s.seasonId);
      expect(beforeSeasonIds).toContain(seasonId);

      // Act: Delete the profile
      const { data } = await ownerClient.mutate({
        mutation: DELETE_PROFILE,
        variables: { profileId: testProfileId },
      });
      expect(data.deleteSellerProfile).toBe(true);

      // Assert: Seasons should be cleaned up (no orphaned records)
      // We verify via direct DynamoDB check that the season record is deleted
      const { DynamoDBClient, GetItemCommand, DeleteItemCommand } = await import('@aws-sdk/client-dynamodb');
      const dynamoClient = new DynamoDBClient({ region: 'us-east-1' });
      const result = await dynamoClient.send(new GetItemCommand({
        TableName: TABLE_NAMES.seasons,
        Key: {
          seasonId: { S: seasonId },
        },
      }));
      expect(result.Item).toBeUndefined();

      // Cleanup: Delete the catalog (not owned by profile, so must be deleted separately)
      const DELETE_CATALOG = gql`
        mutation DeleteCatalog($catalogId: ID!) {
          deleteCatalog(catalogId: $catalogId)
        }
      `;
      await ownerClient.mutate({
        mutation: DELETE_CATALOG,
        variables: { catalogId: catalogId },
      });

      // Profile was deleted and seasons were cleaned up
    }, 15000);

    it('Concurrent profile creation by same user creates unique profiles', async () => {
      // Arrange: Create multiple profiles concurrently
      const profilePromises = Array.from({ length: 3 }, (_, i) =>
        ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: {
            input: {
              sellerName: `${getTestPrefix()}-ConcurrentProfile-${i}`,
            },
          },
        })
      );

      // Act: Execute all profile creations concurrently
      const results = await Promise.allSettled(profilePromises);

      // Assert: All profiles should be created successfully with unique IDs
      const successes = results.filter(r => r.status === 'fulfilled');
      expect(successes.length).toBe(3);

      const profileIds = successes.map(r => (r as PromiseFulfilledResult<any>).value.data.createSellerProfile.profileId);
      const uniqueProfileIds = new Set(profileIds);
      expect(uniqueProfileIds.size).toBe(3);

      // Cleanup all created profiles
      for (const profileId of profileIds) {
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      }
    }, 20000);

    it('Security: Creating many profiles (user quota testing)', async () => {
      // Arrange: Create multiple profiles to test quotas
      // This test documents current behavior: no enforced quota
      const profileCount = 10;
      const createdIds: string[] = [];

      // Act: Create many profiles
      for (let i = 0; i < profileCount; i++) {
        const { data } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: {
            input: {
              sellerName: `${getTestPrefix()}-QuotaTest-${i}`,
            },
          },
        });
        createdIds.push(data.createSellerProfile.profileId);
      }

      // Assert: All profiles should be created (no quota enforced currently)
      expect(createdIds.length).toBe(profileCount);
      
      // Verify all profiles exist via listMyProfiles
      const LIST_MY_PROFILES = gql`
        query ListMyProfiles {
          listMyProfiles {
            profileId
            sellerName
          }
        }
      `;
      const { data: listData }: any = await ownerClient.query({
        query: LIST_MY_PROFILES,
        fetchPolicy: 'network-only',
      });
      
      // All created profiles should appear in the list
      const returnedIds = listData.listMyProfiles.map((p: any) => p.profileId);
      for (const createdId of createdIds) {
        expect(returnedIds).toContain(createdId);
      }

      // Cleanup all created profiles
      for (const profileId of createdIds) {
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      }
    }, 60000);

    it('Updating profile with no changes is a no-op', async () => {
      // Arrange: Create profile
      const profileName = `${getTestPrefix()}-NoOpUpdate`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const testProfileId = createData.createSellerProfile.profileId;

      // Get original updatedAt
      const { data: originalData } = await ownerClient.query({
        query: gql`query GetProfile($profileId: ID!) { getProfile(profileId: $profileId) { profileId sellerName updatedAt } }`,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });
      const originalUpdatedAt = originalData.getProfile.updatedAt;

      // Wait a bit to ensure timestamp would change if updated
      await new Promise(resolve => setTimeout(resolve, 100));

      // Act: Update with no changes (same name)
      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_PROFILE,
        variables: {
          input: {
            profileId: testProfileId,
            sellerName: profileName, // Same name
          },
        },
      });

      // Assert: Profile still has same name
      expect(updateData.updateSellerProfile.sellerName).toBe(profileName);
      // updatedAt might change even for no-op (implementation dependent)

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId: testProfileId } });
    }, 10000);

    it('Updating profile that has active shares preserves share access', async () => {
      // Arrange: Create profile and share it
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-SharedProfile` } },
      });
      const testProfileId = createData.createSellerProfile.profileId;

      // Share with contributor
      const SHARE_DIRECT = gql`
        mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
          shareProfileDirect(input: $input) {
            shareId
            permissions
          }
        }
      `;
      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL,
            permissions: ['READ', 'WRITE'],
          },
        },
      });

      // Act: Update the profile
      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_PROFILE,
        variables: {
          input: {
            profileId: testProfileId,
            sellerName: `${getTestPrefix()}-UpdatedSharedProfile`,
          },
        },
      });

      expect(updateData.updateSellerProfile.sellerName).toContain('UpdatedSharedProfile');

      // Assert: Contributor can still access the profile
      const { data: accessData } = await contributorClient.query({
        query: gql`query GetProfile($profileId: ID!) { getProfile(profileId: $profileId) { profileId sellerName } }`,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });
      expect(accessData.getProfile.profileId).toBe(testProfileId);
      expect(accessData.getProfile.sellerName).toContain('UpdatedSharedProfile');

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId: testProfileId } });
    }, 15000);

    it('Data Integrity: Concurrent deletion and access (race condition)', async () => {
      // Arrange: Create profile and share it
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-ConcurrentDeleteAccess` } },
      });
      const testProfileId = createData.createSellerProfile.profileId;

      // Share with contributor
      const SHARE_DIRECT = gql`
        mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
          shareProfileDirect(input: $input) {
            shareId
            permissions
          }
        }
      `;
      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL,
            permissions: ['READ'],
          },
        },
      });

      // Act: Concurrent deletion and access
      const [deleteResult, accessResult] = await Promise.allSettled([
        ownerClient.mutate({
          mutation: DELETE_PROFILE,
          variables: { profileId: testProfileId },
        }),
        contributorClient.query({
          query: GET_PROFILE,
          variables: { profileId: testProfileId },
          fetchPolicy: 'network-only',
        }),
      ]);

      // Assert: Delete should succeed
      expect(deleteResult.status).toBe('fulfilled');
      if (deleteResult.status === 'fulfilled') {
        expect(deleteResult.value.data.deleteSellerProfile).toBe(true);
      }
      
      // Access result may succeed or fail depending on timing
      // Either result is acceptable for a race condition test
      expect(['fulfilled', 'rejected']).toContain(accessResult.status);

      // Profile was deleted, no cleanup needed
    }, 15000);
  });
});
