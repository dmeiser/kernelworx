import { defineWorkspace } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

const cwd = process.cwd();

export default defineWorkspace([
  {
    // Frontend tests with jsdom
    plugins: [react()],
    test: {
      include: ['frontend/tests/**/*.test.{ts,tsx}'],
      exclude: ['**/node_modules/**', '**/dist/**'],
      name: 'frontend',
      root: './frontend',
      environment: 'jsdom',
      globals: true,
      setupFiles: [path.resolve(cwd, './frontend/tests/setup.ts')],
      // Use threads pool for better jsdom compatibility
      pool: 'threads',
      poolOptions: {
        threads: {
          isolate: true,
        },
      },
      // Configure jsdom to handle window.location navigation
      environmentOptions: {
        jsdom: {
          navigationUrl: 'http://localhost/',
          beforeUnload: true,
        },
      },
      server: {
        deps: {
          inline: ['@mui/material', 'react-router', 'react-router-dom'],
        },
      },
    },
  },
  {
    // Integration tests
    extends: './tests/integration/vitest.config.ts',
    test: {
      include: ['tests/integration/**/*.test.{ts,tsx}'],
      name: 'integration',
      root: '.',
    },
  },
]);
