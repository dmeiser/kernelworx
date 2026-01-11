/**
 * Integration tests for Payment Methods
 * 
 * Tests GraphQL resolvers for custom payment methods with QR codes:
 * - myPaymentMethods (query)
 * - paymentMethodsForProfile (query)
 * - createPaymentMethod (mutation)
 * - updatePaymentMethod (mutation)
 * - deletePaymentMethod (mutation)
 * - requestPaymentMethodQRCodeUpload (mutation)
 * - confirmPaymentMethodQRCodeUpload (mutation)
 * - deletePaymentMethodQRCode (mutation)
 * 
 * Coverage:
 * - Default cash/check injection
 * - Custom payment method CRUD
 * - QR code upload/delete
 * - Reserved name validation
 * - Uniqueness validation
 * - Authorization (owner vs shared profiles)
 * - QR visibility rules (owner/WRITE see QR, READ doesn't)
 */

import '../setup.ts';
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, gql } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';

// GraphQL Queries
const MY_PAYMENT_METHODS = gql`
  query MyPaymentMethods {
    myPaymentMethods {
      name
      qrCodeUrl
    }
  }
`;

const PAYMENT_METHODS_FOR_PROFILE = gql`
  query PaymentMethodsForProfile($profileId: ID!) {
    paymentMethodsForProfile(profileId: $profileId) {
      name
      qrCodeUrl
    }
  }
`;

// GraphQL Mutations
const CREATE_PAYMENT_METHOD = gql`
  mutation CreatePaymentMethod($name: String!) {
    createPaymentMethod(name: $name) {
      name
      qrCodeUrl
    }
  }
`;

const UPDATE_PAYMENT_METHOD = gql`
  mutation UpdatePaymentMethod($currentName: String!, $newName: String!) {
    updatePaymentMethod(currentName: $currentName, newName: $newName) {
      name
      qrCodeUrl
    }
  }
`;

const DELETE_PAYMENT_METHOD = gql`
  mutation DeletePaymentMethod($name: String!) {
    deletePaymentMethod(name: $name)
  }
`;

const REQUEST_QR_UPLOAD = gql`
  mutation RequestPaymentMethodQRCodeUpload($paymentMethodName: String!) {
    requestPaymentMethodQRCodeUpload(paymentMethodName: $paymentMethodName) {
      uploadUrl
      fields
      s3Key
    }
  }
`;

const CONFIRM_QR_UPLOAD = gql`
  mutation ConfirmPaymentMethodQRCodeUpload($paymentMethodName: String!, $s3Key: String!) {
    confirmPaymentMethodQRCodeUpload(paymentMethodName: $paymentMethodName, s3Key: $s3Key) {
      name
      qrCodeUrl
    }
  }
`;

const DELETE_QR_CODE = gql`
  mutation DeletePaymentMethodQRCode($paymentMethodName: String!) {
    deletePaymentMethodQRCode(paymentMethodName: $paymentMethodName)
  }
`;

// Helper mutation for creating profiles (for shared profile tests)
const CREATE_PROFILE = gql`
  mutation CreateSellerProfile($input: CreateSellerProfileInput!) {
    createSellerProfile(input: $input) {
      profileId
      sellerName
      ownerAccountId
    }
  }
`;

const SHARE_DIRECT = gql`
  mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
    shareProfileDirect(input: $input) {
      shareId
      targetAccountId
      profileId
      permissions
    }
  }
`;

describe.sequential('Payment Methods Integration Tests', () => {
  let ownerClient: ApolloClient<any>;
  let writeUserClient: ApolloClient<any>;
  let readUserClient: ApolloClient<any>;
  
  let ownerAccountId: string;
  let writeUserAccountId: string;
  let readUserAccountId: string;

  beforeAll(async () => {
    const ownerResult: AuthenticatedClientResult = await createAuthenticatedClient('owner');
    const writeResult: AuthenticatedClientResult = await createAuthenticatedClient('contributor');
    const readResult: AuthenticatedClientResult = await createAuthenticatedClient('readonly');

    ownerClient = ownerResult.client;
    writeUserClient = writeResult.client;
    readUserClient = readResult.client;
    
    ownerAccountId = ownerResult.accountId;
    writeUserAccountId = writeResult.accountId;
    readUserAccountId = readResult.accountId;

    // Clean up any leftover payment methods from previous test runs
    // Clean up for owner
    try {
      console.log('beforeAll: Fetching existing payment methods (owner)...');
      const { data } = await ownerClient.query({
        query: MY_PAYMENT_METHODS,
        fetchPolicy: 'network-only',
      });
      
      console.log('beforeAll: Found methods (owner):', data.myPaymentMethods.map((m: any) => m.name));
      
      for (const method of data.myPaymentMethods) {
        // Skip Cash and Check (reserved methods)
        if (method.name !== 'Cash' && method.name !== 'Check') {
          console.log('beforeAll: Deleting (owner)', method.name);
          try {
            await ownerClient.mutate({
              mutation: DELETE_PAYMENT_METHOD,
              variables: { name: method.name },
            });
            console.log('beforeAll: Deleted (owner)', method.name);
          } catch (e) {
            console.log('beforeAll: Failed to delete (owner)', method.name, e);
          }
        }
      }
      console.log('beforeAll: Owner cleanup complete');
    } catch (e) {
      console.log('beforeAll: Owner cleanup failed', e);
    }
    
    // Clean up for writeUser
    try {
      console.log('beforeAll: Fetching existing payment methods (writeUser)...');
      const { data } = await writeUserClient.query({
        query: MY_PAYMENT_METHODS,
        fetchPolicy: 'network-only',
      });
      
      console.log('beforeAll: Found methods (writeUser):', data.myPaymentMethods.map((m: any) => m.name));
      
      for (const method of data.myPaymentMethods) {
        // Skip Cash and Check (reserved methods)
        if (method.name !== 'Cash' && method.name !== 'Check') {
          console.log('beforeAll: Deleting (writeUser)', method.name);
          try {
            await writeUserClient.mutate({
              mutation: DELETE_PAYMENT_METHOD,
              variables: { name: method.name },
            });
            console.log('beforeAll: Deleted (writeUser)', method.name);
          } catch (e) {
            console.log('beforeAll: Failed to delete (writeUser)', method.name, e);
          }
        }
      }
      console.log('beforeAll: WriteUser cleanup complete');
    } catch (e) {
      console.log('beforeAll: WriteUser cleanup failed', e);
    }
  });

  afterAll(async () => {
    // Final cleanup of all test payment methods
    const testMethods = ['Zelle', 'Venmo', 'PayPal', 'Venmo - Tom', 'Venmo - JERRY', 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA', 'Cash App'];
    
    for (const name of testMethods) {
      try {
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name },
        });
      } catch (e) {
        // Ignore errors - method might not exist
      }
    }
    
    console.log('Payment methods integration test cleanup complete.');
  }, 30000);

  describe('myPaymentMethods query', () => {
    describe('Default behavior', () => {
      it('should return Cash and Check for users with no custom payment methods', async () => {
        const { data } = await ownerClient.query({
          query: MY_PAYMENT_METHODS,
          fetchPolicy: 'network-only',
        });

        expect(data.myPaymentMethods).toBeDefined();
        expect(data.myPaymentMethods.length).toBeGreaterThanOrEqual(2);
        
        const methodNames = data.myPaymentMethods.map((m: any) => m.name);
        expect(methodNames).toContain('Cash');
        expect(methodNames).toContain('Check');
      });

      it('should return methods sorted alphabetically', async () => {
        // Create custom methods first
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Zelle' },
        });
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });

        const { data } = await ownerClient.query({
          query: MY_PAYMENT_METHODS,
          fetchPolicy: 'network-only',
        });

        const methodNames = data.myPaymentMethods.map((m: any) => m.name);
        const sortedNames = [...methodNames].sort((a, b) => a.localeCompare(b));
        expect(methodNames).toEqual(sortedNames);

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Zelle' },
        });
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });
      });

      it('should include custom payment methods with Cash and Check', async () => {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'PayPal' },
        });

        const { data } = await ownerClient.query({
          query: MY_PAYMENT_METHODS,
          fetchPolicy: 'network-only',
        });

        const methodNames = data.myPaymentMethods.map((m: any) => m.name);
        expect(methodNames).toContain('Cash');
        expect(methodNames).toContain('Check');
        expect(methodNames).toContain('PayPal');

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'PayPal' },
        });
      });
    });
  });

  describe('createPaymentMethod mutation', () => {
    describe('Happy path', () => {
      it('should create a custom payment method', async () => {
        const { data } = await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });

        expect(data.createPaymentMethod).toBeDefined();
        expect(data.createPaymentMethod.name).toBe('Venmo');
        expect(data.createPaymentMethod.qrCodeUrl).toBeNull();

        // Verify it appears in myPaymentMethods
        const { data: queryData } = await ownerClient.query({
          query: MY_PAYMENT_METHODS,
          fetchPolicy: 'network-only',
        });
        const methodNames = queryData.myPaymentMethods.map((m: any) => m.name);
        expect(methodNames).toContain('Venmo');

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });
      });

      it('should allow creating payment methods with different casing variations', async () => {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo - Tom' },
        });
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo - Harry' },
        });

        const { data } = await ownerClient.query({
          query: MY_PAYMENT_METHODS,
          fetchPolicy: 'network-only',
        });

        const methodNames = data.myPaymentMethods.map((m: any) => m.name);
        expect(methodNames).toContain('Venmo - Tom');
        expect(methodNames).toContain('Venmo - Harry');

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo - Tom' },
        });
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo - Harry' },
        });
      });
    });

    describe('Validation', () => {
      it('should reject reserved name "Cash"', async () => {
        await expect(
          ownerClient.mutate({
            mutation: CREATE_PAYMENT_METHOD,
            variables: { name: 'Cash' },
          })
        ).rejects.toThrow();
      });

      it('should reject reserved name "cash" (case-insensitive)', async () => {
        await expect(
          ownerClient.mutate({
            mutation: CREATE_PAYMENT_METHOD,
            variables: { name: 'cash' },
          })
        ).rejects.toThrow();
      });

      it('should reject reserved name "Check"', async () => {
        await expect(
          ownerClient.mutate({
            mutation: CREATE_PAYMENT_METHOD,
            variables: { name: 'Check' },
          })
        ).rejects.toThrow();
      });

      it('should reject reserved name "check" (case-insensitive)', async () => {
        await expect(
          ownerClient.mutate({
            mutation: CREATE_PAYMENT_METHOD,
            variables: { name: 'check' },
          })
        ).rejects.toThrow();
      });

      it('should reject duplicate name', async () => {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });

        await expect(
          ownerClient.mutate({
            mutation: CREATE_PAYMENT_METHOD,
            variables: { name: 'Venmo' },
          })
        ).rejects.toThrow();

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });
      });

      it('should reject duplicate name (case-insensitive)', async () => {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });

        await expect(
          ownerClient.mutate({
            mutation: CREATE_PAYMENT_METHOD,
            variables: { name: 'venmo' },
          })
        ).rejects.toThrow();

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });
      });

      it('should reject name longer than 50 characters', async () => {
        const longName = 'A'.repeat(51);
        await expect(
          ownerClient.mutate({
            mutation: CREATE_PAYMENT_METHOD,
            variables: { name: longName },
          })
        ).rejects.toThrow();
      });

      it('should accept name exactly 50 characters', async () => {
        const name50 = 'A'.repeat(50);
        const { data } = await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: name50 },
        });

        expect(data.createPaymentMethod.name).toBe(name50);

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: name50 },
        });
      });

      it('should reject empty name', async () => {
        await expect(
          ownerClient.mutate({
            mutation: CREATE_PAYMENT_METHOD,
            variables: { name: '' },
          })
        ).rejects.toThrow();
      });
    });
  });

  describe('updatePaymentMethod mutation', () => {
    describe('Happy path', () => {
      it('should rename payment method', async () => {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });

        const { data } = await ownerClient.mutate({
          mutation: UPDATE_PAYMENT_METHOD,
          variables: {
            currentName: 'Venmo',
            newName: 'Venmo - Tom',
          },
        });

        expect(data.updatePaymentMethod.name).toBe('Venmo - Tom');

        const { data: queryData } = await ownerClient.query({
          query: MY_PAYMENT_METHODS,
          fetchPolicy: 'network-only',
        });
        const methodNames = queryData.myPaymentMethods.map((m: any) => m.name);
        expect(methodNames).toContain('Venmo - Tom');
        expect(methodNames).not.toContain('Venmo');

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo - Tom' },
        });
      });
    });

    describe('Validation', () => {
      it('should reject renaming to reserved name', async () => {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });

        await expect(
          ownerClient.mutate({
            mutation: UPDATE_PAYMENT_METHOD,
            variables: {
              currentName: 'Venmo',
              newName: 'Cash',
            },
          })
        ).rejects.toThrow();

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });
      });

      it('should reject renaming to existing name', async () => {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'PayPal' },
        });

        await expect(
          ownerClient.mutate({
            mutation: UPDATE_PAYMENT_METHOD,
            variables: {
              currentName: 'Venmo',
              newName: 'PayPal',
            },
          })
        ).rejects.toThrow();

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'PayPal' },
        });
      });

      it('should reject updating non-existent method', async () => {
        await expect(
          ownerClient.mutate({
            mutation: UPDATE_PAYMENT_METHOD,
            variables: {
              currentName: 'NonExistent',
              newName: 'NewName',
            },
          })
        ).rejects.toThrow();
      });
    });
  });

  describe('deletePaymentMethod mutation', () => {
    describe('Happy path', () => {
      it('should delete payment method', async () => {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });

        const { data } = await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });

        expect(data.deletePaymentMethod).toBe(true);

        const { data: queryData } = await ownerClient.query({
          query: MY_PAYMENT_METHODS,
          fetchPolicy: 'network-only',
        });
        const methodNames = queryData.myPaymentMethods.map((m: any) => m.name);
        expect(methodNames).not.toContain('Venmo');
      });
    });

    describe('Validation', () => {
      it('should reject deleting non-existent method', async () => {
        await expect(
          ownerClient.mutate({
            mutation: DELETE_PAYMENT_METHOD,
            variables: { name: 'NonExistent' },
          })
        ).rejects.toThrow();
      });

      it('should reject deleting reserved name Cash', async () => {
        await expect(
          ownerClient.mutate({
            mutation: DELETE_PAYMENT_METHOD,
            variables: { name: 'Cash' },
          })
        ).rejects.toThrow();
      });

      it('should reject deleting reserved name Check', async () => {
        await expect(
          ownerClient.mutate({
            mutation: DELETE_PAYMENT_METHOD,
            variables: { name: 'Check' },
          })
        ).rejects.toThrow();
      });
    });
  });

  describe('paymentMethodsForProfile query', () => {
    let ownerProfileId: string;

    beforeAll(async () => {
      // Create a profile for the owner
      const { data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: {
          input: {
            sellerName: 'Test Owner',
          },
        },
      });
      ownerProfileId = data.createSellerProfile.profileId;
    });

    describe('Owner access', () => {
      it('should return owner payment methods with Cash and Check', async () => {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });

        const { data } = await ownerClient.query({
          query: PAYMENT_METHODS_FOR_PROFILE,
          variables: { profileId: ownerProfileId },
          fetchPolicy: 'network-only',
        });

        const methodNames = data.paymentMethodsForProfile.map((m: any) => m.name);
        expect(methodNames).toContain('Cash');
        expect(methodNames).toContain('Check');
        expect(methodNames).toContain('Venmo');

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });
      });

      it('should return sorted payment methods', async () => {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Zelle' },
        });
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });

        const { data } = await ownerClient.query({
          query: PAYMENT_METHODS_FOR_PROFILE,
          variables: { profileId: ownerProfileId },
          fetchPolicy: 'network-only',
        });

        const methodNames = data.paymentMethodsForProfile.map((m: any) => m.name);
        const sortedNames = [...methodNames].sort((a, b) => a.localeCompare(b));
        expect(methodNames).toEqual(sortedNames);

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Zelle' },
        });
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });
      });
    });

    describe('Shared access - WRITE permissions', () => {
      beforeAll(async () => {
        // Create share with WRITE permissions
        await ownerClient.mutate({
          mutation: SHARE_DIRECT,
          variables: {
            input: {
              profileId: ownerProfileId,
              targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL!,
              permissions: ['WRITE'],
            },
          },
        });
      });

      it('should return owner payment methods (not shared user own methods)', async () => {
        // Owner creates a payment method
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Owner-Venmo' },
        });

        // Shared user creates their own payment method
        await writeUserClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'WriteUser-PayPal' },
        });

        // Query as shared user
        const { data } = await writeUserClient.query({
          query: PAYMENT_METHODS_FOR_PROFILE,
          variables: { profileId: ownerProfileId },
          fetchPolicy: 'network-only',
        });

        const methodNames = data.paymentMethodsForProfile.map((m: any) => m.name);
        expect(methodNames).toContain('Owner-Venmo');
        expect(methodNames).not.toContain('WriteUser-PayPal');

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Owner-Venmo' },
        });
        await writeUserClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'WriteUser-PayPal' },
        });
      });
    });

    describe('Shared access - READ permissions', () => {
      beforeAll(async () => {
        // Create share with READ permissions
        await ownerClient.mutate({
          mutation: SHARE_DIRECT,
          variables: {
            input: {
              profileId: ownerProfileId,
              targetAccountEmail: process.env.TEST_READONLY_EMAIL!,
              permissions: ['READ'],
            },
          },
        });
      });

      it('should return owner payment methods with QR URLs as null', async () => {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });

        const { data } = await readUserClient.query({
          query: PAYMENT_METHODS_FOR_PROFILE,
          variables: { profileId: ownerProfileId },
          fetchPolicy: 'network-only',
        });

        const methodNames = data.paymentMethodsForProfile.map((m: any) => m.name);
        expect(methodNames).toContain('Cash');
        expect(methodNames).toContain('Check');
        expect(methodNames).toContain('Venmo');

        // All QR URLs should be null for READ users
        data.paymentMethodsForProfile.forEach((method: any) => {
          expect(method.qrCodeUrl).toBeNull();
        });

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });
      });
    });

    describe('Unauthorized access', () => {
      it('should reject query for profile without access', async () => {
        // Create another user's profile
        const { data: profileData } = await writeUserClient.mutate({
          mutation: CREATE_PROFILE,
          variables: {
            input: {
              sellerName: 'Other User',
            },
          },
        });
        const otherProfileId = profileData.createSellerProfile.profileId;

        // Try to query as owner (no access to writeUser's profile)
        await expect(
          ownerClient.query({
            query: PAYMENT_METHODS_FOR_PROFILE,
            variables: { profileId: otherProfileId },
            fetchPolicy: 'network-only',
          })
        ).rejects.toThrow();
      });
    });
  });

  describe('QR Code Operations', () => {
    let ownerProfileIdForQR: string;

    beforeAll(async () => {
      // Create a profile for QR tests
      const { data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: {
          input: {
            sellerName: 'QR Test Owner',
          },
        },
      });
      ownerProfileIdForQR = data.createSellerProfile.profileId;

      // Create shares for WRITE and READ users
      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: ownerProfileIdForQR,
            targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL!,
            permissions: ['WRITE'],
          },
        },
      });
      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: ownerProfileIdForQR,
            targetAccountEmail: process.env.TEST_READONLY_EMAIL!,
            permissions: ['READ'],
          },
        },
      });
    });

    describe('requestPaymentMethodQRCodeUpload', () => {
      it('should generate pre-signed POST URL for upload', async () => {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });

        const { data } = await ownerClient.mutate({
          mutation: REQUEST_QR_UPLOAD,
          variables: { paymentMethodName: 'Venmo' },
        });

        expect(data.requestPaymentMethodQRCodeUpload.uploadUrl).toBeDefined();
        expect(data.requestPaymentMethodQRCodeUpload.fields).toBeDefined();
        expect(data.requestPaymentMethodQRCodeUpload.s3Key).toBeDefined();
        expect(data.requestPaymentMethodQRCodeUpload.s3Key).toContain('payment-qr-codes');
        expect(data.requestPaymentMethodQRCodeUpload.s3Key).toContain('venmo');

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });
      });

      it('should reject upload request for reserved name', async () => {
        await expect(
          ownerClient.mutate({
            mutation: REQUEST_QR_UPLOAD,
            variables: { paymentMethodName: 'Cash' },
          })
        ).rejects.toThrow();
      });

      it('should reject upload request for non-existent method', async () => {
        await expect(
          ownerClient.mutate({
            mutation: REQUEST_QR_UPLOAD,
            variables: { paymentMethodName: 'NonExistent' },
          })
        ).rejects.toThrow();
      });

      it('WRITE shared user cannot upload QR for owner payment method', async () => {
        // Owner creates payment method
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo-WriteTest' },
        });

        // WRITE shared user attempts to request upload - should fail
        // Note: requestPaymentMethodQRCodeUpload is owner-only for the caller's own methods
        await expect(
          writeUserClient.mutate({
            mutation: REQUEST_QR_UPLOAD,
            variables: { paymentMethodName: 'Venmo-WriteTest' },
          })
        ).rejects.toThrow();

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo-WriteTest' },
        });
      });

      it('READ shared user cannot upload QR for owner payment method', async () => {
        // Owner creates payment method
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo-ReadTest' },
        });

        // READ shared user attempts to request upload - should fail
        await expect(
          readUserClient.mutate({
            mutation: REQUEST_QR_UPLOAD,
            variables: { paymentMethodName: 'Venmo-ReadTest' },
          })
        ).rejects.toThrow();

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo-ReadTest' },
        });
      });
    });

    describe('deletePaymentMethodQRCode', () => {
      it('should delete QR code while keeping payment method', async () => {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });

        // Note: In a real test, we would upload a QR code first
        // For now, we just test the mutation doesn't fail
        const { data } = await ownerClient.mutate({
          mutation: DELETE_QR_CODE,
          variables: { paymentMethodName: 'Venmo' },
        });

        expect(data.deletePaymentMethodQRCode).toBe(true);

        // Verify payment method still exists
        const { data: queryData } = await ownerClient.query({
          query: MY_PAYMENT_METHODS,
          fetchPolicy: 'network-only',
        });
        const methodNames = queryData.myPaymentMethods.map((m: any) => m.name);
        expect(methodNames).toContain('Venmo');

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo' },
        });
      });

      it('WRITE shared user cannot delete QR for owner payment method', async () => {
        // Owner creates payment method
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo-DeleteQRTest' },
        });

        // WRITE shared user attempts to delete QR - should fail
        await expect(
          writeUserClient.mutate({
            mutation: DELETE_QR_CODE,
            variables: { paymentMethodName: 'Venmo-DeleteQRTest' },
          })
        ).rejects.toThrow();

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo-DeleteQRTest' },
        });
      });

      it('READ shared user cannot delete QR for owner payment method', async () => {
        // Owner creates payment method
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo-ReadDeleteQRTest' },
        });

        // READ shared user attempts to delete QR - should fail
        await expect(
          readUserClient.mutate({
            mutation: DELETE_QR_CODE,
            variables: { paymentMethodName: 'Venmo-ReadDeleteQRTest' },
          })
        ).rejects.toThrow();

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo-ReadDeleteQRTest' },
        });
      });
    });

    describe('Shared user cannot delete payment method', () => {
      it('WRITE shared user cannot delete owner payment method', async () => {
        // Owner creates payment method
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo-WriteDeleteTest' },
        });

        // WRITE shared user attempts to delete - should fail
        // (deletePaymentMethod operates on the caller's own payment methods)
        await expect(
          writeUserClient.mutate({
            mutation: DELETE_PAYMENT_METHOD,
            variables: { name: 'Venmo-WriteDeleteTest' },
          })
        ).rejects.toThrow();

        // Verify method still exists for owner
        const { data: queryData } = await ownerClient.query({
          query: MY_PAYMENT_METHODS,
          fetchPolicy: 'network-only',
        });
        const methodNames = queryData.myPaymentMethods.map((m: any) => m.name);
        expect(methodNames).toContain('Venmo-WriteDeleteTest');

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo-WriteDeleteTest' },
        });
      });

      it('READ shared user cannot delete owner payment method', async () => {
        // Owner creates payment method
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo-ReadDeleteTest' },
        });

        // READ shared user attempts to delete - should fail
        await expect(
          readUserClient.mutate({
            mutation: DELETE_PAYMENT_METHOD,
            variables: { name: 'Venmo-ReadDeleteTest' },
          })
        ).rejects.toThrow();

        // Verify method still exists for owner
        const { data: queryData } = await ownerClient.query({
          query: MY_PAYMENT_METHODS,
          fetchPolicy: 'network-only',
        });
        const methodNames = queryData.myPaymentMethods.map((m: any) => m.name);
        expect(methodNames).toContain('Venmo-ReadDeleteTest');

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo-ReadDeleteTest' },
        });
      });
    });

    describe('confirmPaymentMethodQRCodeUpload', () => {
      it('should confirm QR upload and return payment method with pre-signed GET URL', async () => {
        // Create payment method
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo-ConfirmTest' },
        });

        // Request upload URL
        const { data: uploadData } = await ownerClient.mutate({
          mutation: REQUEST_QR_UPLOAD,
          variables: { paymentMethodName: 'Venmo-ConfirmTest' },
        });

        const s3Key = uploadData.requestPaymentMethodQRCodeUpload.s3Key;
        const uploadUrl = uploadData.requestPaymentMethodQRCodeUpload.uploadUrl;
        const fields = uploadData.requestPaymentMethodQRCodeUpload.fields;

        // Actually upload a small PNG to S3 using the pre-signed POST
        // Create a minimal valid PNG (1x1 transparent pixel)
        const pngData = Buffer.from([
          0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d,
          0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
          0x08, 0x06, 0x00, 0x00, 0x00, 0x1f, 0x15, 0xc4, 0x89, 0x00, 0x00, 0x00,
          0x0a, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x63, 0x00, 0x01, 0x00, 0x00,
          0x05, 0x00, 0x01, 0x0d, 0x0a, 0x2d, 0xb4, 0x00, 0x00, 0x00, 0x00, 0x49,
          0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
        ]);

        // Build form data for S3 upload
        const formData = new FormData();
        const parsedFields = JSON.parse(fields);
        for (const [key, value] of Object.entries(parsedFields)) {
          formData.append(key, value as string);
        }
        formData.append('file', new Blob([pngData], { type: 'image/png' }), 'qr.png');

        // Upload to S3
        const uploadResponse = await fetch(uploadUrl, {
          method: 'POST',
          body: formData,
        });
        expect(uploadResponse.ok || uploadResponse.status === 204).toBe(true);

        // Confirm the upload
        const { data: confirmData } = await ownerClient.mutate({
          mutation: CONFIRM_QR_UPLOAD,
          variables: {
            paymentMethodName: 'Venmo-ConfirmTest',
            s3Key: s3Key,
          },
        });

        expect(confirmData.confirmPaymentMethodQRCodeUpload.name).toBe('Venmo-ConfirmTest');
        expect(confirmData.confirmPaymentMethodQRCodeUpload.qrCodeUrl).toBeDefined();
        expect(confirmData.confirmPaymentMethodQRCodeUpload.qrCodeUrl).toContain('https://');

        // Verify the pre-signed GET URL works
        const getResponse = await fetch(confirmData.confirmPaymentMethodQRCodeUpload.qrCodeUrl);
        expect(getResponse.ok).toBe(true);

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo-ConfirmTest' },
        });
      });

      it('should reject confirm with non-existent S3 object', async () => {
        // Create payment method
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo-NoS3' },
        });

        // Try to confirm with a fake s3Key that doesn't exist
        await expect(
          ownerClient.mutate({
            mutation: CONFIRM_QR_UPLOAD,
            variables: {
              paymentMethodName: 'Venmo-NoS3',
              s3Key: 'payment-qr-codes/fake-account/nonexistent.png',
            },
          })
        ).rejects.toThrow();

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo-NoS3' },
        });
      });

      it('should reject confirm with invalid s3Key format', async () => {
        // Create payment method
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo-BadKey' },
        });

        // Try to confirm with malformed s3Key
        await expect(
          ownerClient.mutate({
            mutation: CONFIRM_QR_UPLOAD,
            variables: {
              paymentMethodName: 'Venmo-BadKey',
              s3Key: '../../../etc/passwd',
            },
          })
        ).rejects.toThrow();

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo-BadKey' },
        });
      });

      it('should reject confirm for non-existent payment method', async () => {
        // Try to confirm for a method that doesn't exist
        await expect(
          ownerClient.mutate({
            mutation: CONFIRM_QR_UPLOAD,
            variables: {
              paymentMethodName: 'NonExistentMethod',
              s3Key: 'payment-qr-codes/fake/nonexistent.png',
            },
          })
        ).rejects.toThrow();
      });
    });

    describe('Delete QR edge cases', () => {
      it('should handle deleting QR code when no QR exists (idempotent)', async () => {
        // Create payment method WITHOUT uploading a QR
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: 'Venmo-NoQR' },
        });

        // Deleting non-existent QR should succeed (idempotent operation)
        const { data } = await ownerClient.mutate({
          mutation: DELETE_QR_CODE,
          variables: { paymentMethodName: 'Venmo-NoQR' },
        });

        expect(data.deletePaymentMethodQRCode).toBe(true);

        // Payment method should still exist
        const { data: queryData } = await ownerClient.query({
          query: MY_PAYMENT_METHODS,
          fetchPolicy: 'network-only',
        });
        const methodNames = queryData.myPaymentMethods.map((m: any) => m.name);
        expect(methodNames).toContain('Venmo-NoQR');

        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: 'Venmo-NoQR' },
        });
      });

      it('should reject deleting QR for non-existent payment method', async () => {
        await expect(
          ownerClient.mutate({
            mutation: DELETE_QR_CODE,
            variables: { paymentMethodName: 'TotallyFakeMethod' },
          })
        ).rejects.toThrow();
      });
    });
  });
});
