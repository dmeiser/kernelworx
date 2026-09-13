/**
 * RFC 6238 TOTP (Time-Based One-Time Password) generation.
 *
 * Used to answer Cognito SOFTWARE_TOKEN_MFA challenges for the admin owner
 * test user, whose TOTP device is provisioned by
 * `scripts/create-ephemeral-test-users.sh` (ephemeral CI) or
 * `scripts/create-test-users.sh` (dev) and provided as
 * TEST_OWNER_TOTP_SECRET.
 *
 * Implemented with node:crypto only (HMAC-SHA1, 30-second
 * step, 6 digits), matching the Cognito software-token MFA profile.
 *
 * Cognito rejects reuse of a TOTP code within the same 30-second window
 * (ExpiredCodeException: "software token has already been used once"). The
 * integration suite signs the admin owner in from many test files, and
 * vitest re-instantiates modules per file, so the window a secret last
 * consumed is persisted to a state file under tmpdir instead of module
 * memory: a live generation waits out the rest of a window that secret
 * already consumed. A mkdir-based lock serializes the read-wait-write so
 * parallel workers (if the suite ever gains file parallelism) cannot both
 * pick the same window (#336).
 */

import { createHash, createHmac } from 'node:crypto';
import {
  mkdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

const TOTP_PERIOD_SECONDS = 30;
const TOTP_DIGITS = 6;

const BASE32_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

const LOCK_TIMEOUT_MS = 120_000;
const LOCK_STALE_MS = 60_000;
const LOCK_RETRY_MIN_MS = 50;
const LOCK_RETRY_JITTER_MS = 100;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Per-secret state directory. Keyed by a hash of the secret so different
 * users never share window state or locks, and no secret material lands in
 * a file path.
 */
function stateDirFor(secret: string): string {
  const hash = createHash('sha256').update(secret).digest('hex').slice(0, 16);
  return path.join(os.tmpdir(), 'kernelworx-totp', hash);
}

function readLastWindow(secret: string): number | undefined {
  try {
    const raw = readFileSync(path.join(stateDirFor(secret), 'last-window'), 'utf8');
    const parsed = Number(raw.trim());
    return Number.isFinite(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

function writeLastWindow(secret: string, window: number): void {
  mkdirSync(stateDirFor(secret), { recursive: true });
  writeFileSync(path.join(stateDirFor(secret), 'last-window'), String(window));
}

/**
 * Delete the persisted window state for a secret (test isolation helper).
 */
export function resetTotpWindowTracking(secret: string): void {
  try {
    rmSync(stateDirFor(secret), { recursive: true, force: true });
  } catch {
    // best effort
  }
}

async function acquireWindowLock(secret: string): Promise<void> {
  const lockDir = path.join(stateDirFor(secret), 'lock');
  mkdirSync(stateDirFor(secret), { recursive: true });
  const deadline = Date.now() + LOCK_TIMEOUT_MS;
  for (;;) {
    try {
      mkdirSync(lockDir);
      return;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'EEXIST') {
        throw error;
      }
      let stale = false;
      try {
        stale = Date.now() - statSync(lockDir).mtimeMs > LOCK_STALE_MS;
      } catch {
        // The lock was just released; retry mkdir immediately.
      }
      if (stale) {
        rmSync(lockDir, { recursive: true, force: true });
        continue;
      }
      if (Date.now() > deadline) {
        throw new Error('Timed out waiting for the TOTP window lock');
      }
      await sleep(LOCK_RETRY_MIN_MS + Math.random() * LOCK_RETRY_JITTER_MS);
    }
  }
}

function releaseWindowLock(secret: string): void {
  try {
    rmSync(path.join(stateDirFor(secret), 'lock'), { recursive: true, force: true });
  } catch {
    // best effort
  }
}

/**
 * Decode a base32 (RFC 4648) encoded string, ignoring padding.
 */
function base32Decode(secret: string): Buffer {
  let bits = 0;
  let value = 0;
  const bytes: number[] = [];
  for (const char of secret.toUpperCase().replace(/=+$/, '')) {
    const index = BASE32_ALPHABET.indexOf(char);
    if (index === -1) {
      continue;
    }
    value = (value << 5) | index;
    bits += 5;
    if (bits >= 8) {
      bytes.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }
  return Buffer.from(bytes);
}

function counterForMs(ms: number): number {
  return Math.floor(ms / 1000 / TOTP_PERIOD_SECONDS);
}

/**
 * Milliseconds to wait before a code may be generated: the time remaining in
 * the window when `lastWindow` (the window this secret last answered a
 * challenge in) is the window containing `nowMs`; zero otherwise.
 */
export function totpReuseWaitMs(lastWindow: number | undefined, nowMs: number): number {
  if (lastWindow === undefined) {
    return 0;
  }
  const currentWindow = counterForMs(nowMs);
  if (lastWindow !== currentWindow) {
    return 0;
  }
  return (currentWindow + 1) * TOTP_PERIOD_SECONDS * 1000 - nowMs;
}

/**
 * Generate a 6-digit TOTP code for the given base32 secret.
 *
 * Live generations (no timestamp) persist the consumed window to a state
 * file under tmpdir and wait out a reused 30-second window, so the returned
 * code has not already been consumed by Cognito (#336).
 *
 * @param secret - Base32-encoded TOTP secret (as issued by Cognito)
 * @param timestampMs - Reference time in milliseconds (defaults to now)
 * @returns Zero-padded 6-digit TOTP code
 */
export async function generateTotp(secret: string, timestampMs?: number): Promise<string> {
  if (timestampMs === undefined) {
    await acquireWindowLock(secret);
    try {
      const lastWindow = readLastWindow(secret);
      let now = Date.now();
      while (totpReuseWaitMs(lastWindow, now) > 0) {
        await sleep(totpReuseWaitMs(lastWindow, now));
        now = Date.now();
      }
      writeLastWindow(secret, counterForMs(now));
      timestampMs = now;
    } finally {
      releaseWindowLock(secret);
    }
  }
  const counter = counterForMs(timestampMs);
  const message = Buffer.alloc(8);
  message.writeBigUInt64BE(BigInt(counter));
  const hmac = createHmac('sha1', base32Decode(secret)).update(message).digest();
  const offset = hmac[hmac.length - 1] & 0x0f;
  const binary =
    ((hmac[offset] & 0x7f) << 24) |
    (hmac[offset + 1] << 16) |
    (hmac[offset + 2] << 8) |
    hmac[offset + 3];
  return String(binary % 10 ** TOTP_DIGITS).padStart(TOTP_DIGITS, '0');
}
