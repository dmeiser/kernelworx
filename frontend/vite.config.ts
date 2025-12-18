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
      key: fs.readFileSync('.cert/key.pem'),
      cert: fs.readFileSync('.cert/cert.pem'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './tests/setup.ts',
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
      // 100% coverage threshold
      thresholds: {
        lines: 100,
        functions: 100,
        branches: 100,
        statements: 100,
      },
    },
  },
})
