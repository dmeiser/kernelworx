import { defineWorkspace } from 'vitest/config';

export default defineWorkspace([
  {
    extends: './frontend/vite.config.ts',
    test: {
      include: ['frontend/tests/**/*.test.{ts,tsx}'],
      name: 'frontend',
      root: './frontend',
    },
  },
  {
    extends: './tests/integration/vitest.config.ts',
    test: {
      include: ['tests/integration/**/*.test.{ts,tsx}'],
      name: 'integration',
      root: '.',
    },
  },
]);
