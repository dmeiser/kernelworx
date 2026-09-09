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
import { ApolloClient } from '@apollo/client';

// Make React globally available for JSX
globalThis.React = React;

// Apollo Client schedules an uncancellable 10-second devtools-suggestion timer
// (raw setTimeout) the first time a client connects to devtools under jsdom.
// Vitest deletes the jsdom globals between test files, so if that timer fires
// in the gap it throws `ReferenceError: window is not defined` and fails the
// whole run (flaky, timing-dependent). Devtools are useless in tests, so
// disable the connection for every client created during the run. Assigned
// directly (not vi.spyOn) so the afterEach restoreAllMocks() cannot undo it.
ApolloClient.prototype.connectToDevTools = () => {};

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
  const apolloClient = (globalThis as { apolloClient?: { clearStore: () => Promise<void> } }).apolloClient;
  if (apolloClient) {
    try {
      await apolloClient.clearStore();
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
