/**
 * Redirect validation utilities
 */

/**
 * Validates that a redirect target is a same-origin relative path.
 * Only accepts strings that start with a single '/' and do not include a host.
 */
export function isSafeRedirect(path: string): boolean {
  if (typeof path !== 'string') return false;
  if (!path.startsWith('/') || path.startsWith('//')) return false;

  return true;
}

/**
 * Returns a safe redirect path, or the fallback if the input is not valid.
 */
export function getSafeRedirect(path: string | null | undefined, fallback: string): string {
  if (path && isSafeRedirect(path)) {
    return path;
  }
  return fallback;
}
