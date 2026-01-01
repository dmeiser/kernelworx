import '../setup.ts';
import { test } from 'vitest';
import { gql } from '@apollo/client';
import { createAuthenticatedClient } from '../setup/apolloClient';

// Test: run the user's payload as several test users and log results
test('run payload as users', async () => {
  const payload = {
    profileId: 'PROFILE#dd69b3bd-5978-419e-9e55-f7c85817e020',
    campaignId: 'CAMPAIGN#6fdf925c-f700-4134-8199-419c19ea1fe8',
    customerName: 'Repro Test',
    orderDate: new Date().toISOString(),
    paymentMethod: 'CASH',
    lineItems: [
      // Simulate client bug: productName set to empty object
      { productId: 'PRODUCT#17bf118c-cca6-464c-92bc-80bfeb982b0a', quantity: 1, productName: {} },
    ],
  };

  const CREATE_ORDER = gql`
    mutation CreateOrder($input: CreateOrderInput!) {
      createOrder(input: $input) {
        orderId
        campaignId
      }
    }
  `;

  // Helper to run mutation for a user type
  async function runAs(userType: 'owner' | 'contributor' | 'readonly') {
    const { client, email } = await createAuthenticatedClient(userType);
    console.log(`Running CreateOrder as ${userType} (${email})`);
    try {
      const { data, errors } = await client.mutate({ mutation: CREATE_ORDER, variables: { input: payload } });
      console.log(`${userType} -> data:`, JSON.stringify(data || null));
      if (errors) console.log(`${userType} -> errors:`, JSON.stringify(errors, null, 2));
    } catch (err: unknown) {
      console.log(`${userType} -> thrown error:`, err);
    }
  }

  await runAs('owner');
  await runAs('contributor');
  await runAs('readonly');
}, 20000);
