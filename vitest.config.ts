import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  test: {
    globalSetup: path.resolve(__dirname, './vitest.global.setup.ts'),
    globalTeardown: path.resolve(__dirname, './vitest.global.teardown.ts'),
  },
});
