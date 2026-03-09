/**
 * Vitest test setup file
 *
 * This file runs before all tests and sets up global test utilities.
 */

import React from 'react';
import { expect, afterEach, vi } from 'vitest';
import '@testing-library/jest-dom';
import { cleanup } from '@testing-library/react';
import * as matchers from '@testing-library/jest-dom/matchers';

// Make React globally available for JSX
globalThis.React = React;

// Extend Vitest matchers with testing-library matchers
expect.extend(matchers);

// Cleanup after each test
afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  vi.useRealTimers();
  vi.clearAllTimers();
  
  // Force clear any Apollo Client cache
  if (globalThis.apolloClient) {
    try {
      await globalThis.apolloClient.clearStore();
    } catch (_e) {
      // Ignore errors during cleanup
    }
  }
  
  // Clear any pending microtasks and force event loop drain
  await new Promise((resolve) => setTimeout(resolve, 0));
});

// Mock window.matchMedia for MUI responsive components
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {}, // deprecated
    removeListener: () => {}, // deprecated
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => true,
  }),
});
