/**
 * Constants for the public order feature, mirrored from the resolver side.
 *
 * `PUBLIC_ORDER_ACK_VERSION` mirrors `ACK_VERSION` in
 * `tofu/application/appsync/js-resolvers/lib/public_settings.js`. The server
 * stamps the accepted version on the settings blob, and a save that enables the
 * feature is rejected with INVALID_INPUT while the stored version lags this
 * constant — so the settings UI must re-prompt rather than assume the earlier
 * acceptance still covers the current wording.
 */

/** Version of the acknowledgement text the owner must accept. */
export const PUBLIC_ORDER_ACK_VERSION = 1;

/** Lifetime public-order cap per campaign (enforced server-side). */
export const PUBLIC_ORDER_CAP = 500;

/** The two mandatory enable-time acknowledgements, verbatim. */
export const PUBLIC_ORDER_ACKNOWLEDGEMENTS: readonly string[] = [
  'KernelWorx does not collect payment. You are responsible for verifying that the buyer has actually paid before fulfilling the order.',
  "Buyers will see the QR image you uploaded for any enabled payment method. Public buyers' name, contact details, and email become visible to people you share this profile with and appear in unit reports/exports.",
];

/**
 * True when the stored acknowledgement is missing or predates the current
 * wording, in which case enabling must re-collect both acknowledgements.
 */
export function acknowledgementIsBehind(storedVersion: number | null | undefined): boolean {
  return typeof storedVersion !== 'number' || storedVersion < PUBLIC_ORDER_ACK_VERSION;
}
