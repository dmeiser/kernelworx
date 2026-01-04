/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import { execSync } from 'child_process'

// Get build info
const getBuildInfo = () => {
  try {
    const gitCommit = execSync('git rev-parse --short HEAD').toString().trim()
    const gitBranch = execSync('git rev-parse --abbrev-ref HEAD').toString().trim()
    return { gitCommit, gitBranch }
  } catch {
    return { gitCommit: 'unknown', gitBranch: 'unknown' }
  }
}

const buildInfo = getBuildInfo()

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    __BUILD_TIME__: JSON.stringify(new Date().toISOString()),
    __GIT_COMMIT__: JSON.stringify(buildInfo.gitCommit),
    __GIT_BRANCH__: JSON.stringify(buildInfo.gitBranch),
    __APP_VERSION__: JSON.stringify(process.env.npm_package_version || '0.0.0'),
  },
  server: {
    host: '0.0.0.0', // Listen on all interfaces
    port: 5173,
    strictPort: true,
    https: {
      // Use local certificate if it exists, otherwise fall back to dev certificate
      key: fs.existsSync('.cert/key-local.pem') 
        ? fs.readFileSync('.cert/key-local.pem')
        : fs.readFileSync('.cert/key.pem'),
      cert: fs.existsSync('.cert/cert-local.pem')
        ? fs.readFileSync('.cert/cert-local.pem')
        : fs.readFileSync('.cert/cert.pem'),
    },
    hmr: {
      host: 'local.dev.appworx.app',
      protocol: 'wss',
      port: 5173,
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './tests/setup.ts',
    exclude: ['**/node_modules/**', '**/dist/**', '**/tests/e2e/**'],
    server: {
      deps: {
        inline: ['@mui/material'],
      },
    },
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: [
        'node_modules/',
        'tests/',
        '**/*.d.ts',
        '**/*.config.*',
        '**/mockData',
        'dist/',
      ],
      // Coverage thresholds - set to current achievable levels given jsdom/MUI limitations
      // Known untestable code patterns (require Playwright e2e tests for 100%):
      // - MUI Select/Switch/Accordion onChange handlers don't fire in jsdom
      // - Complex Apollo useLazyQuery + useApolloClient patterns require integration tests
      // - Dialog backdrop click/ESC events cannot be simulated
      // - Async handlers requiring confirmation dialogs + GraphQL mocking
      // - Mutation onCompleted callbacks with refetch()
      // - Button click navigation in deeply nested MUI components
      // See: https://github.com/testing-library/user-event/issues/1020
      // Note: v8 ignore comments don't work reliably inside function bodies/JSX
      thresholds: {
        lines: 94,
        functions: 88,
        branches: 85,
        statements: 93,
      },
    },
  },
})
