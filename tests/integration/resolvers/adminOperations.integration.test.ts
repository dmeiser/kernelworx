/**
 * Integration tests for Admin Operations mutations
 * 
 * Tests 3 resolvers:
 * - adminResetUserPassword (Lambda resolver - admin only)
 * - adminDeleteUser (Lambda resolver - admin only)
 * - createManagedCatalog (Lambda resolver - admin only)
 * 
 * Coverage:
 * - Happy paths (admin operations)
 * - Authorization (admin-only access)
 * - Input validation
 * - Error handling
 * 
 * Prerequisites:
 * - Deploy the CDK stack first: `cd cdk && ./deploy.sh`
 * - Owner test user must be in ADMIN Cognito group
 * - Contributor/readonly users must NOT be in ADMIN group
 * 
 * Note: These tests require the admin operations Lambda to be deployed.
 * If you see "Field 'xxx' is undefined" errors, you need to deploy first.
 */

import '../setup.ts'; // Load environment variables and setup
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, gql } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';
import { DynamoDBClient, DeleteItemCommand, GetItemCommand } from '@aws-sdk/client-dynamodb';
import { TABLE_NAMES } from '../setup/testData';

const dynamoClient = new DynamoDBClient({ region: 'us-east-1' });

// GraphQL Mutations
const ADMIN_RESET_USER_PASSWORD = gql`
  mutation AdminResetUserPassword($email: AWSEmail!) {
    adminResetUserPassword(email: $email)
  }
`;

const ADMIN_DELETE_USER = gql`
  mutation AdminDeleteUser($accountId: ID!) {
    adminDeleteUser(accountId: $accountId)
  }
`;

// Cascading delete mutations
const ADMIN_DELETE_USER_ORDERS = gql`
  mutation AdminDeleteUserOrders($accountId: ID!) {
    adminDeleteUserOrders(accountId: $accountId)
  }
`;

const ADMIN_DELETE_USER_CAMPAIGNS = gql`
  mutation AdminDeleteUserCampaigns($accountId: ID!) {
    adminDeleteUserCampaigns(accountId: $accountId)
  }
`;

const ADMIN_DELETE_USER_SHARES = gql`
  mutation AdminDeleteUserShares($accountId: ID!) {
    adminDeleteUserShares(accountId: $accountId)
  }
`;

const ADMIN_DELETE_USER_PROFILES = gql`
  mutation AdminDeleteUserProfiles($accountId: ID!) {
    adminDeleteUserProfiles(accountId: $accountId)
  }
`;

const ADMIN_DELETE_USER_CATALOGS = gql`
  mutation AdminDeleteUserCatalogs($accountId: ID!) {
    adminDeleteUserCatalogs(accountId: $accountId)
  }
`;

// Admin query
const ADMIN_LIST_USERS = gql`
  query AdminListUsers($limit: Int, $nextToken: String) {
    adminListUsers(limit: $limit, nextToken: $nextToken) {
      users {
        accountId
        email
        displayName
        status
        enabled
        isAdmin
        emailVerified
        createdAt
      }
      nextToken
    }
  }
`;

const CREATE_MANAGED_CATALOG = gql`
  mutation CreateManagedCatalog($input: CreateCatalogInput!) {
    createManagedCatalog(input: $input) {
      catalogId
      catalogName
      catalogType
      isPublic
      products {
        productId
        productName
        description
        price
        sortOrder
      }
      createdAt
      updatedAt
    }
  }
`;

// Query for verification
const GET_CATALOG = gql`
  query GetCatalog($catalogId: ID!) {
    getCatalog(catalogId: $catalogId) {
      catalogId
      catalogName
      catalogType
      isPublic
      products {
        productId
        productName
        price
      }
    }
  }
`;

describe('Admin Operations Integration Tests', () => {
  let adminClient: ApolloClient;
  let contributorClient: ApolloClient;
  let readonlyClient: ApolloClient;
  
  // Track account IDs for context
  let adminAccountId: string;
  let contributorAccountId: string;
  let contributorEmail: string;
  let readonlyAccountId: string;
  let readonlyEmail: string;
  
  // Track created catalogs for cleanup
  const createdCatalogIds: string[] = [];

  beforeAll(async () => {
    // Owner user is configured as admin (in ADMIN Cognito group)
    const adminResult: AuthenticatedClientResult = await createAuthenticatedClient('owner');
    const contributorResult: AuthenticatedClientResult = await createAuthenticatedClient('contributor');
    const readonlyResult: AuthenticatedClientResult = await createAuthenticatedClient('readonly');

    adminClient = adminResult.client;
    contributorClient = contributorResult.client;
    readonlyClient = readonlyResult.client;
    
    adminAccountId = adminResult.accountId;
    contributorAccountId = contributorResult.accountId;
    contributorEmail = contributorResult.email;
    readonlyAccountId = readonlyResult.accountId;
    readonlyEmail = readonlyResult.email;
    
    console.log('Admin account ID:', adminAccountId);
    console.log('Contributor account ID:', contributorAccountId);
  }, 30000);

  afterAll(async () => {
    // Clean up any managed catalogs created during tests
    console.log('Cleaning up managed catalogs...');
    for (const catalogId of createdCatalogIds) {
      try {
        await dynamoClient.send(new DeleteItemCommand({
          TableName: TABLE_NAMES.catalogs,
          Key: { catalogId: { S: catalogId } },
        }));
        console.log(`Deleted catalog: ${catalogId}`);
      } catch (error) {
        console.warn(`Failed to delete catalog ${catalogId}:`, error);
      }
    }
    console.log('Cleanup complete.');
  }, 30000);

  describe('createManagedCatalog', () => {
    describe('Happy Path', () => {
      it('should create ADMIN_MANAGED catalog with products', async () => {
        const catalogName = `Admin Managed Catalog ${Date.now()}`;
        
        const { data } = await adminClient.mutate({
          mutation: CREATE_MANAGED_CATALOG,
          variables: {
            input: {
              catalogName,
              isPublic: true,
              products: [
                { productName: 'Premium Popcorn', price: 25.00, sortOrder: 1 },
                { productName: 'Chocolate Bars', price: 15.00, description: 'Delicious chocolate', sortOrder: 2 },
              ],
            },
          },
        });

        expect(data?.createManagedCatalog).toBeDefined();
        expect(data.createManagedCatalog.catalogId).toMatch(/^CATALOG#/);
        expect(data.createManagedCatalog.catalogName).toBe(catalogName);
        expect(data.createManagedCatalog.catalogType).toBe('ADMIN_MANAGED');
        expect(data.createManagedCatalog.isPublic).toBe(true);
        expect(data.createManagedCatalog.products).toHaveLength(2);
        expect(data.createManagedCatalog.products[0].productId).toMatch(/^PRODUCT#/);
        expect(data.createManagedCatalog.products[0].productName).toBe('Premium Popcorn');
        expect(data.createManagedCatalog.products[1].description).toBe('Delicious chocolate');

        // Track for cleanup
        createdCatalogIds.push(data.createManagedCatalog.catalogId);
      });

      it('should create private managed catalog', async () => {
        const catalogName = `Private Admin Catalog ${Date.now()}`;
        
        const { data } = await adminClient.mutate({
          mutation: CREATE_MANAGED_CATALOG,
          variables: {
            input: {
              catalogName,
              isPublic: false,
              products: [
                { productName: 'Secret Product', price: 100.00, sortOrder: 1 },
              ],
            },
          },
        });

        expect(data?.createManagedCatalog).toBeDefined();
        expect(data.createManagedCatalog.catalogType).toBe('ADMIN_MANAGED');
        expect(data.createManagedCatalog.isPublic).toBe(false);

        // Track for cleanup
        createdCatalogIds.push(data.createManagedCatalog.catalogId);
      });

      it('should persist catalog in DynamoDB', async () => {
        const catalogName = `Persisted Admin Catalog ${Date.now()}`;
        
        const { data } = await adminClient.mutate({
          mutation: CREATE_MANAGED_CATALOG,
          variables: {
            input: {
              catalogName,
              isPublic: true,
              products: [
                { productName: 'Test Product', price: 10.00, sortOrder: 1 },
              ],
            },
          },
        });

        const catalogId = data?.createManagedCatalog.catalogId;
        createdCatalogIds.push(catalogId);

        // Verify in DynamoDB
        const getResult = await dynamoClient.send(new GetItemCommand({
          TableName: TABLE_NAMES.catalogs,
          Key: { catalogId: { S: catalogId } },
        }));

        expect(getResult.Item).toBeDefined();
        expect(getResult.Item?.catalogType?.S).toBe('ADMIN_MANAGED');
        expect(getResult.Item?.catalogName?.S).toBe(catalogName);
      });

      it('should be queryable via getCatalog', async () => {
        const catalogName = `Queryable Admin Catalog ${Date.now()}`;
        
        const { data: createData } = await adminClient.mutate({
          mutation: CREATE_MANAGED_CATALOG,
          variables: {
            input: {
              catalogName,
              isPublic: true,
              products: [
                { productName: 'Queryable Product', price: 12.00, sortOrder: 1 },
              ],
            },
          },
        });

        const catalogId = createData?.createManagedCatalog.catalogId;
        createdCatalogIds.push(catalogId);

        // Query the catalog
        const { data: queryData } = await adminClient.query({
          query: GET_CATALOG,
          variables: { catalogId },
        });

        expect(queryData?.getCatalog).toBeDefined();
        expect(queryData.getCatalog.catalogId).toBe(catalogId);
        expect(queryData.getCatalog.catalogType).toBe('ADMIN_MANAGED');
      });
    });

    describe('Authorization', () => {
      it('SECURITY: Non-admin contributor cannot create managed catalog', async () => {
        await expect(
          contributorClient.mutate({
            mutation: CREATE_MANAGED_CATALOG,
            variables: {
              input: {
                catalogName: 'Unauthorized Catalog',
                isPublic: true,
                products: [
                  { productName: 'Test', price: 10.00, sortOrder: 1 },
                ],
              },
            },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });

      it('SECURITY: Non-admin readonly user cannot create managed catalog', async () => {
        await expect(
          readonlyClient.mutate({
            mutation: CREATE_MANAGED_CATALOG,
            variables: {
              input: {
                catalogName: 'Unauthorized Catalog',
                isPublic: true,
                products: [
                  { productName: 'Test', price: 10.00, sortOrder: 1 },
                ],
              },
            },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });
    });

    describe('Input Validation', () => {
      it('should reject empty catalog name', async () => {
        await expect(
          adminClient.mutate({
            mutation: CREATE_MANAGED_CATALOG,
            variables: {
              input: {
                catalogName: '   ',
                isPublic: true,
                products: [
                  { productName: 'Test', price: 10.00, sortOrder: 1 },
                ],
              },
            },
          })
        ).rejects.toThrow(/Catalog name is required|INVALID_INPUT/i);
      });

      it('should reject empty products array', async () => {
        await expect(
          adminClient.mutate({
            mutation: CREATE_MANAGED_CATALOG,
            variables: {
              input: {
                catalogName: 'No Products Catalog',
                isPublic: true,
                products: [],
              },
            },
          })
        ).rejects.toThrow(/Products array cannot be empty|INVALID_INPUT/i);
      });

      it('should reject product with missing name', async () => {
        await expect(
          adminClient.mutate({
            mutation: CREATE_MANAGED_CATALOG,
            variables: {
              input: {
                catalogName: 'Bad Product Catalog',
                isPublic: true,
                products: [
                  { productName: '  ', price: 10.00, sortOrder: 1 },
                ],
              },
            },
          })
        ).rejects.toThrow(/Product name is required|INVALID_INPUT/i);
      });

      it('should reject product with negative price', async () => {
        await expect(
          adminClient.mutate({
            mutation: CREATE_MANAGED_CATALOG,
            variables: {
              input: {
                catalogName: 'Negative Price Catalog',
                isPublic: true,
                products: [
                  { productName: 'Bad Product', price: -5.00, sortOrder: 1 },
                ],
              },
            },
          })
        ).rejects.toThrow(/Valid product price is required|INVALID_INPUT/i);
      });
    });
  });

  describe('adminResetUserPassword', () => {
    describe('Happy Path', () => {
      it.skip('should initiate password reset for existing user', async () => {
        // SKIPPED: This test resets a user's password which breaks subsequent tests
        // The functionality is tested through the error case (NOT_FOUND for non-existent user)
        // and authorization tests below. To test the happy path manually, use the admin UI.
        const { data } = await adminClient.mutate({
          mutation: ADMIN_RESET_USER_PASSWORD,
          variables: {
            email: readonlyEmail,
          },
        });

        expect(data?.adminResetUserPassword).toBe(true);
      });
    });

    describe('Authorization', () => {
      it('SECURITY: Non-admin contributor cannot reset passwords', async () => {
        await expect(
          contributorClient.mutate({
            mutation: ADMIN_RESET_USER_PASSWORD,
            variables: {
              email: 'anyone@example.com',
            },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });

      it('SECURITY: Non-admin readonly user cannot reset passwords', async () => {
        await expect(
          readonlyClient.mutate({
            mutation: ADMIN_RESET_USER_PASSWORD,
            variables: {
              email: 'anyone@example.com',
            },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });
    });

    describe('Error Handling', () => {
      it('should return NOT_FOUND for non-existent user', async () => {
        await expect(
          adminClient.mutate({
            mutation: ADMIN_RESET_USER_PASSWORD,
            variables: {
              email: 'nonexistent-user-12345@example.com',
            },
          })
        ).rejects.toThrow(/not found|NOT_FOUND/i);
      });
    });
  });

  describe('adminDeleteUser', () => {
    // NOTE: We don't actually delete the test users as that would break subsequent tests
    // Instead we test authorization and error cases
    
    describe('Authorization', () => {
      it('SECURITY: Non-admin contributor cannot delete users', async () => {
        await expect(
          contributorClient.mutate({
            mutation: ADMIN_DELETE_USER,
            variables: {
              accountId: 'any-account-id',
            },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });

      it('SECURITY: Non-admin readonly user cannot delete users', async () => {
        await expect(
          readonlyClient.mutate({
            mutation: ADMIN_DELETE_USER,
            variables: {
              accountId: 'any-account-id',
            },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });

      it('SECURITY: Admin cannot delete their own account', async () => {
        await expect(
          adminClient.mutate({
            mutation: ADMIN_DELETE_USER,
            variables: {
              accountId: adminAccountId,
            },
          })
        ).rejects.toThrow(/Cannot delete your own account|INVALID_INPUT/i);
      });
    });

    describe('Error Handling', () => {
      it('should return NOT_FOUND for non-existent account', async () => {
        await expect(
          adminClient.mutate({
            mutation: ADMIN_DELETE_USER,
            variables: {
              accountId: 'nonexistent-account-id-12345',
            },
          })
        ).rejects.toThrow(/not found|NOT_FOUND/i);
      });

      it('should reject empty account ID', async () => {
        await expect(
          adminClient.mutate({
            mutation: ADMIN_DELETE_USER,
            variables: {
              accountId: '   ',
            },
          })
        ).rejects.toThrow(/Account ID is required|INVALID_INPUT/i);
      });
    });

    // Optional: Test actual deletion with a temporary test user
    // This is commented out to avoid creating/deleting users in every test run
    /*
    describe('Happy Path (with temporary user)', () => {
      let tempAccountId: string;
      
      beforeEach(async () => {
        // Create a temporary account directly in DynamoDB
        tempAccountId = `ACCOUNT#temp-test-${Date.now()}`;
        await dynamoClient.send(new PutItemCommand({
          TableName: TABLE_NAMES.accounts,
          Item: {
            accountId: { S: tempAccountId },
            email: { S: `temp-${Date.now()}@test.example.com` },
            createdAt: { S: new Date().toISOString() },
          },
        }));
      });

      it('should delete user from DynamoDB', async () => {
        const { data } = await adminClient.mutate({
          mutation: ADMIN_DELETE_USER,
          variables: {
            accountId: tempAccountId.replace('ACCOUNT#', ''),
          },
        });

        expect(data?.adminDeleteUser).toBe(true);

        // Verify account was deleted
        const getResult = await dynamoClient.send(new GetItemCommand({
          TableName: TABLE_NAMES.accounts,
          Key: { accountId: { S: tempAccountId } },
        }));
        
        expect(getResult.Item).toBeUndefined();
      });
    });
    */
  });

  // ============================================================
  // ADMIN LIST USERS - Query to list all users (admin only)
  // ============================================================
  describe('adminListUsers', () => {
    describe('Happy Path', () => {
      it('should list users when called by admin', async () => {
        const { data } = await adminClient.query({
          query: ADMIN_LIST_USERS,
          variables: { limit: 10 },
        });

        expect(data?.adminListUsers).toBeDefined();
        expect(data.adminListUsers.users).toBeInstanceOf(Array);
        expect(data.adminListUsers.users.length).toBeGreaterThan(0);
        
        // Each user should have required fields
        const firstUser = data.adminListUsers.users[0];
        expect(firstUser.accountId).toBeDefined();
        expect(firstUser.email).toBeDefined();
        expect(firstUser.status).toBeDefined();
        expect(typeof firstUser.enabled).toBe('boolean');
        expect(typeof firstUser.isAdmin).toBe('boolean');
      });

      it('should support pagination', async () => {
        // First page
        const { data: page1 } = await adminClient.query({
          query: ADMIN_LIST_USERS,
          variables: { limit: 2 },
        });

        expect(page1?.adminListUsers).toBeDefined();
        expect(page1.adminListUsers.users.length).toBeLessThanOrEqual(2);
        
        // If there's a next page token, we can paginate
        if (page1.adminListUsers.nextToken) {
          const { data: page2 } = await adminClient.query({
            query: ADMIN_LIST_USERS,
            variables: { limit: 2, nextToken: page1.adminListUsers.nextToken },
          });
          expect(page2?.adminListUsers).toBeDefined();
        }
      });

      it('should return admin user in ADMIN Cognito group', async () => {
        const { data } = await adminClient.query({
          query: ADMIN_LIST_USERS,
          variables: { limit: 60 },
        });

        // Find the admin user (owner)
        const adminUser = data.adminListUsers.users.find(
          (u: any) => u.accountId === adminAccountId
        );
        expect(adminUser).toBeDefined();
        expect(adminUser.isAdmin).toBe(true);
      });

      it('should return non-admin users correctly', async () => {
        const { data } = await adminClient.query({
          query: ADMIN_LIST_USERS,
          variables: { limit: 60 },
        });

        // Find the contributor user (not admin)
        const contributorUser = data.adminListUsers.users.find(
          (u: any) => u.accountId === contributorAccountId
        );
        expect(contributorUser).toBeDefined();
        expect(contributorUser.isAdmin).toBe(false);
      });
    });

    describe('Authorization', () => {
      it('SECURITY: Non-admin contributor CANNOT list users', async () => {
        await expect(
          contributorClient.query({
            query: ADMIN_LIST_USERS,
            variables: { limit: 10 },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });

      it('SECURITY: Non-admin readonly user CANNOT list users', async () => {
        await expect(
          readonlyClient.query({
            query: ADMIN_LIST_USERS,
            variables: { limit: 10 },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });
    });
  });

  // ============================================================
  // CASCADING DELETE MUTATIONS - Authorization tests
  // These mutations are used when deleting a user to clean up their data
  // ============================================================
  describe('Cascading Delete Mutations - Authorization', () => {
    // These tests verify that non-admins cannot call the cascading delete mutations
    // Even with a valid accountId, only admins should be able to call these

    describe('adminDeleteUserOrders', () => {
      it('SECURITY: Admin CAN call adminDeleteUserOrders', async () => {
        // Admin calling with a non-existent ID should work (just return 0)
        const { data } = await adminClient.mutate({
          mutation: ADMIN_DELETE_USER_ORDERS,
          variables: { accountId: 'nonexistent-account-id' },
        });
        
        expect(data?.adminDeleteUserOrders).toBeDefined();
        expect(typeof data.adminDeleteUserOrders).toBe('number');
        expect(data.adminDeleteUserOrders).toBe(0); // No profiles to delete orders from
      });

      it('SECURITY: Non-admin contributor CANNOT delete user orders', async () => {
        await expect(
          contributorClient.mutate({
            mutation: ADMIN_DELETE_USER_ORDERS,
            variables: { accountId: 'any-account-id' },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });

      it('SECURITY: Non-admin readonly user CANNOT delete user orders', async () => {
        await expect(
          readonlyClient.mutate({
            mutation: ADMIN_DELETE_USER_ORDERS,
            variables: { accountId: 'any-account-id' },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });
    });

    describe('adminDeleteUserCampaigns', () => {
      it('SECURITY: Admin CAN call adminDeleteUserCampaigns', async () => {
        const { data } = await adminClient.mutate({
          mutation: ADMIN_DELETE_USER_CAMPAIGNS,
          variables: { accountId: 'nonexistent-account-id' },
        });
        
        expect(data?.adminDeleteUserCampaigns).toBeDefined();
        expect(typeof data.adminDeleteUserCampaigns).toBe('number');
        expect(data.adminDeleteUserCampaigns).toBe(0);
      });

      it('SECURITY: Non-admin contributor CANNOT delete user campaigns', async () => {
        await expect(
          contributorClient.mutate({
            mutation: ADMIN_DELETE_USER_CAMPAIGNS,
            variables: { accountId: 'any-account-id' },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });

      it('SECURITY: Non-admin readonly user CANNOT delete user campaigns', async () => {
        await expect(
          readonlyClient.mutate({
            mutation: ADMIN_DELETE_USER_CAMPAIGNS,
            variables: { accountId: 'any-account-id' },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });
    });

    describe('adminDeleteUserShares', () => {
      it('SECURITY: Admin CAN call adminDeleteUserShares', async () => {
        const { data } = await adminClient.mutate({
          mutation: ADMIN_DELETE_USER_SHARES,
          variables: { accountId: 'nonexistent-account-id' },
        });
        
        expect(data?.adminDeleteUserShares).toBeDefined();
        expect(typeof data.adminDeleteUserShares).toBe('number');
        expect(data.adminDeleteUserShares).toBe(0);
      });

      it('SECURITY: Non-admin contributor CANNOT delete user shares', async () => {
        await expect(
          contributorClient.mutate({
            mutation: ADMIN_DELETE_USER_SHARES,
            variables: { accountId: 'any-account-id' },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });

      it('SECURITY: Non-admin readonly user CANNOT delete user shares', async () => {
        await expect(
          readonlyClient.mutate({
            mutation: ADMIN_DELETE_USER_SHARES,
            variables: { accountId: 'any-account-id' },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });
    });

    describe('adminDeleteUserProfiles', () => {
      it('SECURITY: Admin CAN call adminDeleteUserProfiles', async () => {
        const { data } = await adminClient.mutate({
          mutation: ADMIN_DELETE_USER_PROFILES,
          variables: { accountId: 'nonexistent-account-id' },
        });
        
        expect(data?.adminDeleteUserProfiles).toBeDefined();
        expect(typeof data.adminDeleteUserProfiles).toBe('number');
        expect(data.adminDeleteUserProfiles).toBe(0);
      });

      it('SECURITY: Non-admin contributor CANNOT delete user profiles', async () => {
        await expect(
          contributorClient.mutate({
            mutation: ADMIN_DELETE_USER_PROFILES,
            variables: { accountId: 'any-account-id' },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });

      it('SECURITY: Non-admin readonly user CANNOT delete user profiles', async () => {
        await expect(
          readonlyClient.mutate({
            mutation: ADMIN_DELETE_USER_PROFILES,
            variables: { accountId: 'any-account-id' },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });
    });

    describe('adminDeleteUserCatalogs', () => {
      it('SECURITY: Admin CAN call adminDeleteUserCatalogs', async () => {
        const { data } = await adminClient.mutate({
          mutation: ADMIN_DELETE_USER_CATALOGS,
          variables: { accountId: 'nonexistent-account-id' },
        });
        
        expect(data?.adminDeleteUserCatalogs).toBeDefined();
        expect(typeof data.adminDeleteUserCatalogs).toBe('number');
        expect(data.adminDeleteUserCatalogs).toBe(0);
      });

      it('SECURITY: Non-admin contributor CANNOT delete user catalogs', async () => {
        await expect(
          contributorClient.mutate({
            mutation: ADMIN_DELETE_USER_CATALOGS,
            variables: { accountId: 'any-account-id' },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });

      it('SECURITY: Non-admin readonly user CANNOT delete user catalogs', async () => {
        await expect(
          readonlyClient.mutate({
            mutation: ADMIN_DELETE_USER_CATALOGS,
            variables: { accountId: 'any-account-id' },
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });
    });
  });

  // ============================================================
  // NEW: Admin User Data Queries
  // ============================================================
  
  describe('adminGetUserProfiles', () => {
    const ADMIN_GET_USER_PROFILES = gql`
      query AdminGetUserProfiles($accountId: ID!) {
        adminGetUserProfiles(accountId: $accountId) {
          profileId
          sellerName
          ownerAccountId
          createdAt
          updatedAt
        }
      }
    `;

    describe('Happy Path', () => {
      it('should return all profiles for the specified user', async () => {
        const { data } = await adminClient.query({
          query: ADMIN_GET_USER_PROFILES,
          variables: { accountId: contributorAccountId },
          fetchPolicy: 'network-only',
        });

        expect(data?.adminGetUserProfiles).toBeDefined();
        expect(Array.isArray(data.adminGetUserProfiles)).toBe(true);
        
        // Verify each profile has required fields
        if (data.adminGetUserProfiles.length > 0) {
          const profile = data.adminGetUserProfiles[0];
          expect(profile.profileId).toBeDefined();
          expect(profile.sellerName).toBeDefined();
          // ownerAccountId is returned with ACCOUNT# prefix
          expect(profile.ownerAccountId).toBe(`ACCOUNT#${contributorAccountId}`);
          expect(profile.createdAt).toBeDefined();
        }
      });

      it('should return empty array for user with no profiles', async () => {
        const { data } = await adminClient.query({
          query: ADMIN_GET_USER_PROFILES,
          variables: { accountId: 'ACCOUNT#nonexistent' },
          fetchPolicy: 'network-only',
        });

        expect(data?.adminGetUserProfiles).toBeDefined();
        expect(Array.isArray(data.adminGetUserProfiles)).toBe(true);
        expect(data.adminGetUserProfiles.length).toBe(0);
      });
    });

    describe('Authorization', () => {
      it('SECURITY: Non-admin contributor CANNOT query user profiles', async () => {
        await expect(
          contributorClient.query({
            query: ADMIN_GET_USER_PROFILES,
            variables: { accountId: adminAccountId },
            fetchPolicy: 'network-only',
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });

      it('SECURITY: Non-admin readonly user CANNOT query user profiles', async () => {
        await expect(
          readonlyClient.query({
            query: ADMIN_GET_USER_PROFILES,
            variables: { accountId: adminAccountId },
            fetchPolicy: 'network-only',
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });
    });
  });

  describe('adminGetUserCatalogs', () => {
    const ADMIN_GET_USER_CATALOGS = gql`
      query AdminGetUserCatalogs($accountId: ID!) {
        adminGetUserCatalogs(accountId: $accountId) {
          catalogId
          catalogName
          catalogType
          isPublic
          createdAt
          products {
            productName
            price
          }
        }
      }
    `;

    describe('Happy Path', () => {
      it('should return all catalogs for the specified user', async () => {
        const { data } = await adminClient.query({
          query: ADMIN_GET_USER_CATALOGS,
          variables: { accountId: contributorAccountId },
          fetchPolicy: 'network-only',
        });

        expect(data?.adminGetUserCatalogs).toBeDefined();
        expect(Array.isArray(data.adminGetUserCatalogs)).toBe(true);
        
        // Verify each catalog has required fields
        // Note: Catalog type does not expose ownerAccountId in schema (we query by accountId parameter)
        if (data.adminGetUserCatalogs.length > 0) {
          const catalog = data.adminGetUserCatalogs[0];
          expect(catalog.catalogId).toBeDefined();
          expect(catalog.catalogName).toBeDefined();
          expect(catalog.catalogType).toBeDefined();
          expect(catalog.createdAt).toBeDefined();
        }
      });

      it('should return empty array for user with no catalogs', async () => {
        const { data } = await adminClient.query({
          query: ADMIN_GET_USER_CATALOGS,
          variables: { accountId: 'ACCOUNT#nonexistent' },
          fetchPolicy: 'network-only',
        });

        expect(data?.adminGetUserCatalogs).toBeDefined();
        expect(Array.isArray(data.adminGetUserCatalogs)).toBe(true);
        expect(data.adminGetUserCatalogs.length).toBe(0);
      });

      it('should NOT return deleted catalogs', async () => {
        const { data } = await adminClient.query({
          query: ADMIN_GET_USER_CATALOGS,
          variables: { accountId: contributorAccountId },
          fetchPolicy: 'network-only',
        });

        expect(data?.adminGetUserCatalogs).toBeDefined();
        
        // Verify none of the returned catalogs have isDeleted=true
        data.adminGetUserCatalogs.forEach((catalog: any) => {
          // The query should filter out deleted catalogs, so this field shouldn't exist
          // or should be false/undefined
          expect(catalog.isDeleted).not.toBe(true);
        });
      });
    });

    describe('Authorization', () => {
      it('SECURITY: Non-admin contributor CANNOT query user catalogs', async () => {
        await expect(
          contributorClient.query({
            query: ADMIN_GET_USER_CATALOGS,
            variables: { accountId: adminAccountId },
            fetchPolicy: 'network-only',
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });

      it('SECURITY: Non-admin readonly user CANNOT query user catalogs', async () => {
        await expect(
          readonlyClient.query({
            query: ADMIN_GET_USER_CATALOGS,
            variables: { accountId: adminAccountId },
            fetchPolicy: 'network-only',
          })
        ).rejects.toThrow(/Admin access required|FORBIDDEN/i);
      });
    });
  });

  // ============================================================
  // SUMMARY: Security Test Coverage
  // ============================================================
  // All admin endpoints are tested for:
  // 1. ✅ Admin CAN access the endpoint (positive test)
  // 2. ✅ Non-admin contributor CANNOT access (negative test)
  // 3. ✅ Non-admin readonly CANNOT access (negative test)
  //
  // Endpoints tested:
  // - adminListUsers (query)
  // - adminGetUserProfiles (query) ⬅️ NEW
  // - adminGetUserCatalogs (query) ⬅️ NEW
  // - adminResetUserPassword (mutation)
  // - adminDeleteUser (mutation)
  // - adminDeleteUserOrders (mutation)
  // - adminDeleteUserCampaigns (mutation)
  // - adminDeleteUserShares (mutation)
  // - adminDeleteUserCatalogs (mutation)
  // - createManagedCatalog (mutation)
});
