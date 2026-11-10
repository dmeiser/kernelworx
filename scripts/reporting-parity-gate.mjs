#!/usr/bin/env node
/**
 * Reporting parity gate — the executable retirement precondition for the
 * legacy getUnitReport surface (integration plan step 7).
 *
 * Runs the parity gate suite (frontend/src/lib/reporting/parity-gate.test.ts)
 * via vitest. Exit code is non-zero whenever reconcileAgainstLegacy
 * reports any violation on the production-shaped fixtures — including the
 * negative controls that keep this gate honest — so a PR can never retire
 * the legacy report on an unverified promise.
 *
 * CI runs this on every PR to main; the retirement-block assertion step
 * in ci.yml names the coupling explicitly when a diff removes getUnitReport
 * surface.
 */

import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..');
const frontendDir = path.join(repoRoot, 'frontend');

try {
  execFileSync('npx', ['vitest', 'run', 'src/lib/reporting/parity-gate.test.ts'], {
    cwd: frontendDir,
    stdio: 'inherit',
  });
  console.log('REPORTING PARITY GATE: PASS — legacy parity holds; retirement precondition satisfied.');
} catch (error) {
  const code = error && typeof error === 'object' && 'status' in error ? error.status : 1;
  console.error('REPORTING PARITY GATE: FAIL — reconcileAgainstLegacy reported violations.');
  console.error('The legacy report cannot be retired until parity holds. See the vitest output above.');
  process.exit(typeof code === 'number' && code !== 0 ? code : 1);
}
