import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  test: {
    globalSetup: path.resolve(__dirname, './vitest.global.setup.ts'),
    // Note: globalTeardown removed - integration tests have their own teardown
    // in tests/integration/vitest.config.ts. Frontend tests don't need AWS cleanup.
  },
});
