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
      // Use forks pool with single fork to prevent worker hanging issues
      pool: 'forks',
      poolOptions: {
        forks: {
          singleFork: true, // Run all tests in single process
        },
      },
      // Add explicit test timeout to prevent hangs
      testTimeout: 30000, // 30 seconds per test
      hookTimeout: 10000, // 10 seconds for hooks
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
