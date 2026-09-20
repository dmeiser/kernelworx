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
 */
import { fetchAuthSession } from 'aws-amplify/auth';

export const PASSKEY_MFA_ENABLE_FAILED_MESSAGE =
  'Passkey was registered, but passkey sign-in could not be enabled. Sign in with your other methods; contact support if passkey sign-in does not work.';

/**
 * Resolves the Cognito IDP endpoint for the configured user pool by
 * deriving the region from the pool id prefix (`us-east-1_XXXXXXXX`).
 */
function getCognitoIdpEndpoint(): string {
  const userPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID;
  if (!userPoolId || !userPoolId.includes('_')) {
    throw new Error('Cognito user pool id is not configured');
  }
  const region = userPoolId.split('_')[0];
  return `https://cognito-idp.${region}.amazonaws.com/`;
}

/**
 * Enables the per-user "User verification with passkey" MFA method —
 * the same end state the Cognito console toggle produces. Only updates
 * the WebAuthnMfaSettings field, so other methods (TOTP, SMS, email)
 * are left untouched.
 */
export async function enablePasskeyMfa(): Promise<void> {
  const { tokens } = await fetchAuthSession();
  const accessToken = tokens?.accessToken;
  if (!accessToken) {
    throw new Error('No signed-in access token; cannot enable passkey MFA');
  }
  const response = await fetch(getCognitoIdpEndpoint(), {
    method: 'POST',
    headers: {
      'content-type': 'application/x-amz-json-1.1',
      'x-amz-target': 'AWSCognitoIdentityProviderService.SetUserMFAPreference',
    },
    body: JSON.stringify({
      AccessToken: accessToken.toString(),
      WebAuthnMfaSettings: { Enabled: true },
    }),
  });
  if (!response.ok) {
    throw new Error(await extractCognitoErrorMessage(response));
  }
}

/**
 * Reads the Cognito error `message` from an error response body,
 * falling back to the HTTP status when the body is not JSON.
 */
async function extractCognitoErrorMessage(response: Response): Promise<string> {
  const fallback = `Cognito error (HTTP ${response.status})`;
  try {
    const body = (await response.json()) as { message?: string };
    return body.message ?? fallback;
  } catch {
    return fallback;
  }
}
