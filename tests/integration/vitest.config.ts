import { defineConfig } from 'vitest/config';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Load .env from project root
dotenv.config({ path: path.resolve(__dirname, '../../.env') });

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    testTimeout: 240000, // 240 seconds (4 minutes) for API calls with GSI retry logic (extremely slow GSI with thousands of test items)
    hookTimeout: 240000, // 240 seconds (4 minutes) for beforeAll with GSI retry logic (very slow GSI propagation)
    setupFiles: [path.resolve(__dirname, 'setup.ts')],
    // Only include integration tests from this folder
    include: [path.resolve(__dirname, '**/*.integration.test.ts')],
    // Run tests sequentially to avoid GSI eventual consistency issues (Bug #21)
    // When tests run in parallel, newly created items may not appear in GSI queries
    // Sequential execution ensures each test's setup completes before next test starts
    fileParallelism: false, // Run test files sequentially (no parallel file execution)
    poolOptions: {
      threads: {
        singleThread: true,
      },
    },
    // NOTE: No global teardown - each test is responsible for cleaning up its own data
    // Account records created by Cognito login are exempt (infrastructure, not test data)
  },
});
