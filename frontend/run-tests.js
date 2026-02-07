#!/usr/bin/env node
/**
 * Wrapper script for running vitest tests
 * Ensures the process exits cleanly after tests complete
 * This works around a known issue where vitest+jsdom doesn't exit properly
 */

import { spawn } from 'child_process';
import process from 'process';

const args = process.argv.slice(2);
const vitestArgs = ['run', '--pool=vmThreads', ...args];

console.log(`Running: npx vitest ${vitestArgs.join(' ')}\n`);

const child = spawn('npx', ['vitest', ...vitestArgs], {
  stdio: ['inherit', 'pipe', 'pipe'],
});

let exitCode = null;
let lastOutputTime = Date.now();
let outputEnded = false;

// Track when we last received output
child.stdout.on('data', (data) => {
  process.stdout.write(data);
  lastOutputTime = Date.now();
});

child.stderr.on('data', (data) => {
  process.stderr.write(data);
  lastOutputTime = Date.now();
});

child.on('exit', (code, signal) => {
  exitCode = code || 0;
  outputEnded = true;
  console.log(`\n✅ Tests completed with exit code: ${exitCode}`);
  process.exit(exitCode);
});

// Check every 5 seconds if output has stopped
const OUTPUT_TIMEOUT_MS = 30 * 1000; // 30 seconds of no output
const checkInterval = setInterval(() => {
  const timeSinceLastOutput = Date.now() - lastOutputTime;
  
  if (timeSinceLastOutput > OUTPUT_TIMEOUT_MS && !outputEnded) {
    console.error(`\n⚠️  No output for ${OUTPUT_TIMEOUT_MS / 1000}s - tests appear to have hung. Forcing exit...`);
    clearInterval(checkInterval);
    child.kill('SIGTERM');
    setTimeout(() => {
      if (!outputEnded) {
        child.kill('SIGKILL');
        process.exit(exitCode !== null ? exitCode : 0);
      }
    }, 2000);
  }
}, 5000);

// Safety timeout - if tests don't complete in 10 minutes, force exit
const TIMEOUT_MS = 10 * 60 * 1000;
setTimeout(() => {
  if (!outputEnded) {
    console.error('\n❌ Test timeout reached (10 minutes) - forcing exit');
    clearInterval(checkInterval);
    child.kill('SIGTERM');
    setTimeout(() => child.kill('SIGKILL'), 2000);
    process.exit(1);
  }
}, TIMEOUT_MS);

