/**
 * Global teardown for vitest workspace
 * Cleans up test data from integration tests
 */

import globalTeardown from './tests/integration/globalTeardown.ts';

export default async function () {
  console.log('🧹 Running global workspace teardown...');
  await globalTeardown();
}
