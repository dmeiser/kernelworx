/**
 * Shared helpers for the Show & Sell Unit management surfaces.
 *
 * The generated display name mirrors the backend's `generated_display_name`
 * (data model §5.1): `Type Number - City, State`. It is only a client preview;
 * the server is authoritative and fills the same value when `displayName` is
 * omitted on `createUnit`/`updateUnit`.
 */

/** Build the generated display name from unit metadata when the caller omits one. */
export const generatedUnitDisplayName = (
  unitType: string,
  unitNumber: string | number,
  city: string,
  state: string,
): string => {
  const type = unitType.trim();
  const num = String(unitNumber).trim();
  const cityName = city.trim();
  const stateName = state.trim();
  return `${type} ${num} - ${cityName}, ${stateName}`.replace(/\s+/g, ' ');
};

/**
 * A fresh idempotency key for a unit mutation. Each idempotency key is scoped
 * to one normalized request: reusing a key with different content returns
 * INVALID_INPUT (IDEM-02), so a retry after a duplicate confirmation must mint
 * a new key.
 */
export const newUnitIdempotencyKey = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `unit-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
};
