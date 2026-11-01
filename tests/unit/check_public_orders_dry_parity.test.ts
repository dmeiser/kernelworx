import { describe, test, expect } from 'vitest';
import { readFileSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const root = (...p: string[]) => join(__dirname, '..', '..', ...p);

function read(p: string) { return readFileSync(p, 'utf8'); }

describe('public-orders constant parity (DRY-5)', () => {
  test('cap is 500 in JS source of truth', () => {
    const src = read(root('tofu', 'application', 'appsync', 'js-resolvers', 'lib', 'public_order.js'));
    const m = src.match(/export const PUBLIC_ORDER_CAP = (\d+)/);
    expect(m).not.toBeNull();
    expect(Number(m![1])).toBe(500);
  });

  test('ack version is 1 in JS source of truth', () => {
    const src = read(root('tofu', 'application', 'appsync', 'js-resolvers', 'lib', 'public_settings.js'));
    const m = src.match(/export const ACK_VERSION = (\d+)/);
    expect(m).not.toBeNull();
    expect(Number(m![1])).toBe(1);
  });

  test('BE quantity limit (999) is >= FE quantity limit (99)', () => {
    const beSrc = read(root('tofu', 'application', 'appsync', 'js-resolvers', 'lib', 'public_order.js'));
    const beM = beSrc.match(/export const MAX_QUANTITY = (\d+)/);
    expect(beM).not.toBeNull();
    const be = Number(beM![1]);

    const feSrc = read(root('frontend', 'src', 'lib', 'publicOrderValidation.ts'));
    const feM = feSrc.match(/export const MAX_PUBLIC_QUANTITY = (\d+)/);
    expect(feM).not.toBeNull();
    const fe = Number(feM![1]);

    // FE stays stricter than BE so a browser cap never exceeds the server cap.
    expect(fe).toBe(99);
    expect(be).toBe(999);
    expect(fe).toBeLessThanOrEqual(be);
  });
});
