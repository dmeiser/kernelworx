/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import { execSync } from 'child_process'
import { fileURLToPath } from 'url'

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

// eslint-disable-next-line complexity -- Config branching for optional local certs
const resolveHttpsConfig = () => {
  const localKeyPath = '.cert/key-local.pem'
  const localCertPath = '.cert/cert-local.pem'
  const fallbackKeyPath = '.cert/key.pem'
  const fallbackCertPath = '.cert/cert.pem'

  const keyPath = fs.existsSync(localKeyPath)
    ? localKeyPath
    : (fs.existsSync(fallbackKeyPath) ? fallbackKeyPath : null)
  const certPath = fs.existsSync(localCertPath)
    ? localCertPath
    : (fs.existsSync(fallbackCertPath) ? fallbackCertPath : null)

  if (!keyPath || !certPath) {
    return undefined
  }

  return {
    key: fs.readFileSync(keyPath),
    cert: fs.readFileSync(certPath),
  }
}

const httpsConfig = resolveHttpsConfig()

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // AppSync JS resolvers live in the tofu tree and are executed in tests
      // against the shared runtime mock (same one the node --test resolver
      // suite uses via register-loader.mjs).
      '@aws-appsync/utils': fileURLToPath(
        new URL(
          '../tofu/application/appsync/js-resolvers/__mocks__/@aws-appsync/utils.js',
          import.meta.url,
        ),
      ),
    },
  },
  optimizeDeps: {
    include: ['react-router', 'react-router-dom'],
  },
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
    https: httpsConfig,
    hmr: {
      host: 'local.dev.appworx.app',
      protocol: 'wss',
      port: 5173,
    },
  },
  ssr: {
    noExternal: ['react-router', 'react-router-dom'],
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './tests/setup.ts',
    exclude: ['**/node_modules/**', '**/dist/**', '**/tests/e2e/**'],
    // Ensure tests timeout rather than hang
    testTimeout: 20000,
    hookTimeout: 20000,
    teardownTimeout: 20000,
    deps: {
      optimizer: {
        web: {
          include: ['react-router', 'react-router-dom'],
        },
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
      // Coverage thresholds - set to the current CI-achievable floor after the
      // coverage improvement pass. Local runs may report slightly higher numbers
      // because v8 ignore comments are handled more leniently; CI uses a stricter
      // v8 build. Known jsdom/MUI limitations mean some UI flow code (Select
      // onChange, dialog backdrop/ESC, certain Apollo callbacks) can only be
      // covered reliably with Playwright e2e tests. Do not lower these thresholds
      // without explicit approval.
      thresholds: {
        lines: 99,
        functions: 97,
        branches: 96,
        statements: 97,
      },
    },
  },
})
