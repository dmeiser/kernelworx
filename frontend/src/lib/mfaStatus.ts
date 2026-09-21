/**
 * Direct Cognito read of the signed-in user's MFA status.
 *
 * The pinned aws-amplify 6.x line does not know about the WebAuthn MFA
 * preference: `fetchMFAPreference`'s `preferred` only reflects
 * SMS/TOTP/EMAIL, so a user whose `PreferredMfaSetting` Cognito switched to
 * WEB_AUTHN_MFA (after enabling passkey MFA in-app via
 * enablePasskeyMfa() or via the Cognito console toggle) reads back as
 * `preferred === undefined` even though an MFA method is enabled. The
 * settings page then concludes "no MFA" and shows the forced TOTP QR setup
 * block to a user who already has MFA.
 *
 * This helper sidesteps the library gap with the same direct-API pattern as
 * passkeyMfa.ts: a Cognito `GetUser` call with the signed-in user's access
 * token (scope `aws.cognito.signin.user.admin`, already required by the
 * TOTP/MFA APIs this app uses), deriving the answer from the RAW response —
 * `UserMFASettingList` non-empty OR `PreferredMfaSetting` set/non-empty.
 * That is aws-amplify-version-independent and covers TOTP-only,
 * passkey-preferred, and both-enabled users.
 */
import { fetchAuthSession } from 'aws-amplify/auth';
import { extractCognitoErrorMessage, getCognitoIdpEndpoint } from './passkeyMfa';

/** MFA-relevant fields of the Cognito GetUser response. */
interface GetUserMfaFields {
  UserMFASettingList?: string[];
  PreferredMfaSetting?: string;
}

/**
 * Derives "any MFA enabled" from the RAW GetUser response: `UserMFASettingList`
 * non-empty OR `PreferredMfaSetting` set/non-empty. Covers TOTP-only,
 * passkey-preferred, and both-enabled users regardless of which method the
 * user prefers.
 */
const hasAnyMfaSetting = (body: GetUserMfaFields): boolean =>
  (body.UserMFASettingList?.length ?? 0) > 0 || Boolean(body.PreferredMfaSetting);

/**
 * Reads the signed-in user's MFA status directly from Cognito GetUser and
 * reports whether the user has any MFA method enabled. This is authoritative
 * for the settings-page MFA gate — it stays correct when the preference is
 * WEB_AUTHN_MFA, which the pinned aws-amplify `fetchMFAPreference` cannot
 * surface.
 */
export async function getMfaEnabledFromCognito(): Promise<boolean> {
  const { tokens } = await fetchAuthSession();
  const accessToken = tokens?.accessToken;
  if (!accessToken) {
    throw new Error('No signed-in access token; cannot read MFA status');
  }
  const response = await fetch(getCognitoIdpEndpoint(), {
    method: 'POST',
    headers: {
      'content-type': 'application/x-amz-json-1.1',
      'x-amz-target': 'AWSCognitoIdentityProviderService.GetUser',
    },
    body: JSON.stringify({ AccessToken: accessToken.toString() }),
  });
  if (!response.ok) {
    throw new Error(await extractCognitoErrorMessage(response));
  }
  const body = (await response.json()) as GetUserMfaFields;
  return hasAnyMfaSetting(body);
}
