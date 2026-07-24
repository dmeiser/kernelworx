/**
 * Redirect validation utilities
 */

/**
 * Validates that a redirect target is a same-origin relative path.
 * Only accepts strings that start with a single '/' and do not include a host.
 */
export function isSafeRedirect(path: string): boolean {
  if (typeof path !== 'string') return false;
  // Reject empty, non-relative, protocol-relative, and backslash-authority paths
  return path.startsWith('/') && !path.startsWith('//') && !(path.length > 1 && path[1] === '\\') && !path.includes('\\');
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
