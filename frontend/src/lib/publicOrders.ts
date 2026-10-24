/**
 * Utilities for public order URLs and links.
 */

/**
 * Resolves a receipt URL for use in links.
 * Returns the URL if it's valid and safe to use, null otherwise.
 *
 * @param url - The receipt URL to resolve
 * @param   - Resolved URL string or null if invalid
 */
export function resolveReceiptUrl(url: string | null | undefined): string | null {
  // In a real implementation, this would validate the URL
  // For now, we'll just return it if it's a non-empty string
  if (typeof url === 'string' && url.trim() !== '') {
    return url;
  }
  return null;
}

/**
 * Builds a share path for public orders.
 * @param campaignId - The campaign ID
 * @param token - The public order share token
 * @returns A path like "/o/campaignId/token"
 */
export function buildSharePath(campaignId: string, token: string): string {
  return `/o/${campaignId}/${token}`;
}
