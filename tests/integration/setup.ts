/**
 * Setup file for integration tests.
 * Loads environment variables and validates required config.
 */

import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';
import { beforeAll } from 'vitest';
import {
  resolveAppSyncEndpoint,
  resolveUserPoolClientId,
  resolveUserPoolId,
} from './setup/lookupInfrastructure.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Load .env from project root
dotenv.config({ path: path.resolve(__dirname, '../../.env') });

// Run async setup in beforeAll hook
beforeAll(async () => {
  // Dynamically resolve infrastructure values (with fallback to explicit env vars)
  const appSyncEndpoint = await resolveAppSyncEndpoint();
  const userPoolClientId = await resolveUserPoolClientId();
  const userPoolId = await resolveUserPoolId();

  // Inject resolved values back into process.env for test code to use
  if (appSyncEndpoint) {
    process.env.TEST_APPSYNC_ENDPOINT = appSyncEndpoint;
  }
  if (userPoolClientId) {
    process.env.TEST_USER_POOL_CLIENT_ID = userPoolClientId;
  }
  if (userPoolId) {
    process.env.TEST_USER_POOL_ID = userPoolId;
  }

  // Validate required environment variables (after dynamic resolution)
  const requiredEnvVars = [
    'TEST_USER_POOL_ID',
    'TEST_USER_POOL_CLIENT_ID',
    'TEST_APPSYNC_ENDPOINT',
    'TEST_OWNER_EMAIL',
    'TEST_OWNER_PASSWORD',
    'TEST_CONTRIBUTOR_EMAIL',
    'TEST_CONTRIBUTOR_PASSWORD',
    'TEST_READONLY_EMAIL',
    'TEST_READONLY_PASSWORD',
  ];

  const missing = requiredEnvVars.filter((varName) => !process.env[varName]);

  if (missing.length > 0) {
    console.error('❌ Missing required environment variables:');
    missing.forEach((varName) => console.error(`   - ${varName}`));
    console.error('\nCould not resolve from AWS or .env file.');
    console.error('Ensure:');
    console.error('  - E2E_BASE_URL is set (e.g. https://dev.kernelworx.app)');
    console.error('  - AWS credentials are configured (aws configure / AWS_PROFILE)');
    console.error('  - Infrastructure is deployed: cd tofu/environments/dev && tofu apply');
    console.error('  - Or set explicit values in .env file');
    process.exit(1);
  }

  console.log('✅ Integration test environment configured');
  console.log(`   AppSync: ${process.env.TEST_APPSYNC_ENDPOINT}`);
  console.log(`   User Pool: ${process.env.TEST_USER_POOL_ID}`);
}, 180000); // 180 seconds timeout for AWS API lookups
