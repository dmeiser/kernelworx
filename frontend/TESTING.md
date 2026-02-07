# Frontend Testing

## Running Tests

```bash
npm test           # Run all unit tests
npm run test:coverage  # Run tests with coverage report
npm run test:watch    # Run tests in watch mode
npm run test:ui       # Run tests with UI
```

## Known Issue: Vitest + jsdom Hanging

### Problem
Vitest with jsdom environment has a known issue where the test process doesn't exit cleanly after all tests complete. This causes tests to "hang" in CI environments, leading to timeouts.

### Solution
We use a wrapper script (`run-tests.js`) that:
1. Runs vitest with the appropriate pool configuration
2. Monitors test output in real-time
3. Detects when output stops for 30 seconds (indicating tests have hung)
4. Forcibly terminates the process with the correct exit code

This ensures tests complete and CI jobs don't timeout.

### Technical Details
- **Pool**: Uses `vmThreads` pool with `isolate: false` for better jsdom compatibility
- **Timeout**: 30 seconds of no output triggers forced exit
- **Safety**: 10-minute absolute timeout as failsafe
- **Exit code**: Preserves the original test exit code (0 for success, non-zero for failure)

### Configuration Files
- `run-tests.js` - Wrapper script that monitors and controls test execution
- `vite.config.ts` - Contains vmThreads pool configuration
- `package.json` - Test scripts use the wrapper

## Pre-existing Test Failures

There are 2 known test failures in `AuthContext.test.tsx`:
1. "handles logout failure with fallback redirect"
2. "redirects to saved URL on OAuth completion"

These failures are NOT related to the hanging issue and existed before the fix.
