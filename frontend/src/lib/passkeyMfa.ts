/**
 * Per-user passkey MFA enablement.
 *
 * Registering a passkey credential (associateWebAuthnCredential) does NOT
 * enable passkey sign-in. The per-user "User verification with passkey"
 * MFA method — the one that makes WEB_AUTHN appear in the USER_AUTH
 * challenge menu — is the Cognito `SetUserMFAPreference` request field
 * `WebAuthnMfaSettings.Enabled`. The Cognito console's per-user toggle
 * sets exactly that flag; without it, passkey sign-in is refused with
 * "Password Challenge is Required to SignIn" even though the credential
 * shows as registered. Enabling it also requires the user pool's
 * WebAuthnConfiguration FactorConfiguration to be
 * MULTI_FACTOR_WITH_USER_VERIFICATION (applied out-of-band on every
 * environment, see tofu/application/modules/cognito/main.tf).
 *
 * The pinned aws-amplify 6.x line does not expose `WebAuthnMfaSettings`
 * on `updateMFAPreference` (its UpdateMFAPreferenceInput only has
 * sms/totp/email), and its Cognito IDP transfer handler sends unsigned
 * x-amz-target JSON-RPC POSTs, so we call the API directly with the
 * signed-in user's access token (scope `aws.cognito.signin.user.admin`,
 * already required by the TOTP/MFA APIs this app uses).
 *
 * Cognito rejects a SetUserMFAPreference request that enables WebAuthn
 * MFA without another MFA setting in the same request: "WebAuthn MFA
 * requires enabling an additional MFA setting." (And without an
 * applicable WebAuthn credential on the user it fails with "User does
 * not have applicable WebAuthn credentials to enable WebAuthn MFA." —
 * a different error, so the request shape itself is accepted.) The
 * console toggle works because it re-sends the user's existing
 * preferences alongside the WebAuthn flag, so this helper does the
 * same: it reads the currently enabled methods via fetchMFAPreference()
 * and re-sends each one enabled in the same request. If no other method
 * is enabled the call fails with the service error, which
 * passkeyMfaFailureMessage() surfaces verbatim instead of hiding it.
 */
import { fetchAuthSession, fetchMFAPreference } from 'aws-amplify/auth';

export const PASSKEY_MFA_ENABLE_FAILED_MESSAGE =
  'Passkey was registered, but passkey sign-in could not be enabled. Sign in with your other methods; contact support if passkey sign-in does not work.';

/** Maximum characters of the Cognito service message embedded in the failure message. */
const MAX_COGNITO_MESSAGE_LENGTH = 200;

/**
 * Cognito SetUserMFAPreference request field for each aws-amplify MFA type
 * (aws-amplify's `AuthMFAType` = 'SMS' | 'TOTP' | 'EMAIL'; the type itself
 * is not re-exported by the package).
 */
const MFA_SETTING_FIELDS: Record<'SMS' | 'TOTP' | 'EMAIL', string> = {
  TOTP: 'SoftwareTokenMfaSettings',
  EMAIL: 'EmailMfaSettings',
  SMS: 'SmsMfaSettings',
};

/**
 * Builds the user-visible passkey MFA enablement failure: the static
 * guidance plus the Cognito service message (e.g. "WebAuthn MFA requires
 * enabling an additional MFA setting."), truncated, so the actual
 * service rule is not hidden from the user.
 */
export function passkeyMfaFailureMessage(error: unknown): string {
  const detail = error instanceof Error ? error.message : typeof error === 'string' ? error : '';
  const trimmed =
    detail.length > MAX_COGNITO_MESSAGE_LENGTH ? `${detail.slice(0, MAX_COGNITO_MESSAGE_LENGTH - 1)}…` : detail;
  return trimmed ? `${PASSKEY_MFA_ENABLE_FAILED_MESSAGE} ${trimmed}` : PASSKEY_MFA_ENABLE_FAILED_MESSAGE;
}

/**
 * Resolves the Cognito IDP endpoint for the configured user pool by
 * deriving the region from the pool id prefix (`us-east-1_XXXXXXXX`).
 */
export function getCognitoIdpEndpoint(): string {
  const userPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID;
  if (!userPoolId || !userPoolId.includes('_')) {
    throw new Error('Cognito user pool id is not configured');
  }
  const region = userPoolId.split('_')[0];
  return `https://cognito-idp.${region}.amazonaws.com/`;
}

/**
 * Builds the SetUserMFAPreference request body: the access token, the
 * user's currently enabled MFA methods re-sent with Enabled=true
 * (Cognito requires at least one alongside WebAuthnMfaSettings), and
 * the WebAuthn flag itself.
 */
function buildMfaPreferenceBody(
  accessToken: string,
  enabled: ('SMS' | 'TOTP' | 'EMAIL')[] | undefined,
): Record<string, unknown> {
  const body: Record<string, unknown> = { AccessToken: accessToken };
  for (const mfaType of enabled ?? []) {
    body[MFA_SETTING_FIELDS[mfaType]] = { Enabled: true };
  }
  body.WebAuthnMfaSettings = { Enabled: true };
  return body;
}

/**
 * Enables the per-user "User verification with passkey" MFA method —
 * the same end state the Cognito console toggle produces. Cognito
 * requires the request to also carry another MFA setting, so the user's
 * currently enabled methods (read via fetchMFAPreference) are re-sent
 * with Enabled=true in the same request; methods that are not enabled
 * are omitted entirely and never disabled.
 */
export async function enablePasskeyMfa(): Promise<void> {
  const { tokens } = await fetchAuthSession();
  const accessToken = tokens?.accessToken;
  if (!accessToken) {
    throw new Error('No signed-in access token; cannot enable passkey MFA');
  }
  const { enabled } = await fetchMFAPreference();
  const body = buildMfaPreferenceBody(accessToken.toString(), enabled);
  const response = await fetch(getCognitoIdpEndpoint(), {
    method: 'POST',
    headers: {
      'content-type': 'application/x-amz-json-1.1',
      'x-amz-target': 'AWSCognitoIdentityProviderService.SetUserMFAPreference',
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await extractCognitoErrorMessage(response));
  }
}

/**
 * Reads the Cognito error `message` from an error response body,
 * falling back to the HTTP status when the body is not JSON.
 */
export async function extractCognitoErrorMessage(response: Response): Promise<string> {
  const fallback = `Cognito error (HTTP ${response.status})`;
  try {
    const body = (await response.json()) as { message?: string };
    return body.message ?? fallback;
  } catch {
    return fallback;
  }
}
