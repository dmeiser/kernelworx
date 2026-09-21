import {
  CognitoIdentityProviderClient,
  InitiateAuthCommand,
  RespondToAuthChallengeCommand,
  AuthFlowType,
  type InitiateAuthResponse,
  type RespondToAuthChallengeResponse,
} from '@aws-sdk/client-cognito-identity-provider';
import { getAwsConfig } from './awsConfig';
import { generateTotp } from './totp';

export interface CognitoTokens {
  accessToken: string;
  idToken: string;
  refreshToken: string;
}

export interface DecodedToken {
  sub: string;
  email: string;
}

export interface AuthResult {
  tokens: CognitoTokens;
  accountId: string;
  email: string;
}

/**
 * Retry budget for ``ResourceNotFoundException`` during sign-in only.
 *
 * Freshly created or updated ephemeral stacks race Cognito's control/data
 * plane propagation: ``InitiateAuth`` can fail with
 * ``User pool client ... does not exist`` seconds after the stack reported
 * creation complete. That is propagation lag, not a missing client, so it is
 * retried with exponential backoff. Every other error still raises on the
 * first attempt.
 */
const CLIENT_PROPAGATION_MAX_ATTEMPTS = 6;
const CLIENT_PROPAGATION_BACKOFF_BASE_MS = 1000;
const CLIENT_PROPAGATION_BACKOFF_CAP_MS = 10000;

function clientPropagationBackoffMs(attempt: number): number {
  return Math.min(
    CLIENT_PROPAGATION_BACKOFF_CAP_MS,
    CLIENT_PROPAGATION_BACKOFF_BASE_MS * 2 ** attempt,
  );
}

function isResourceNotFound(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'name' in error &&
    (error as { name?: string }).name === 'ResourceNotFoundException'
  );
}

/**
 * Answer a Cognito SOFTWARE_TOKEN_MFA challenge.
 *
 * The admin owner test user has a provisioned TOTP device (#336), so its
 * password auth returns an MFA challenge instead of tokens.
 */
async function respondToSoftwareTokenMfa(
  client: CognitoIdentityProviderClient,
  clientId: string,
  email: string,
  session: string | undefined,
  totpSecret: string | undefined,
): Promise<RespondToAuthChallengeResponse> {
  if (!session) {
    throw new Error('Cognito returned a SOFTWARE_TOKEN_MFA challenge without a session');
  }
  if (!totpSecret) {
    throw new Error(
      'Cognito returned a SOFTWARE_TOKEN_MFA challenge but no TOTP secret was provided. ' +
        'Set TEST_OWNER_TOTP_SECRET (provisioned by scripts/create-test-users.sh or exported by ephemeral CI).',
    );
  }
  return client.send(
    new RespondToAuthChallengeCommand({
      ClientId: clientId,
      ChallengeName: 'SOFTWARE_TOKEN_MFA',
      Session: session,
      ChallengeResponses: {
        USERNAME: email,
        SOFTWARE_TOKEN_MFA_CODE: await generateTotp(totpSecret),
      },
    }),
  );
}

/**
 * Sign in a user and return Cognito tokens with account ID.
 *
 * @param email - User email address
 * @param password - User password
 * @param totpSecret - Base32 TOTP secret for users with a provisioned MFA
 *   device (the admin owner). Required when Cognito answers the password
 *   auth with a SOFTWARE_TOKEN_MFA challenge.
 */
export async function signInUser(
  email: string,
  password: string,
  totpSecret?: string,
): Promise<AuthResult> {
  // Get config dynamically from AWS
  const config = await getAwsConfig();
  const { userPoolId, userPoolClientId, region } = config;

  const client = new CognitoIdentityProviderClient({ region });

  let response: InitiateAuthResponse | RespondToAuthChallengeResponse;
  for (let attempt = 0; ; attempt++) {
    try {
      response = await client.send(
        new InitiateAuthCommand({
          AuthFlow: AuthFlowType.USER_PASSWORD_AUTH,
          ClientId: userPoolClientId,
          AuthParameters: {
            USERNAME: email,
            PASSWORD: password,
          },
        }),
      );
      break;
    } catch (error) {
      if (
        !isResourceNotFound(error) ||
        attempt >= CLIENT_PROPAGATION_MAX_ATTEMPTS - 1
      ) {
        throw error;
      }
      console.warn(
        `⏳ Cognito client ${userPoolClientId} not visible yet (attempt ${
          attempt + 1
        }/${CLIENT_PROPAGATION_MAX_ATTEMPTS}), retrying in ${clientPropagationBackoffMs(
          attempt,
        )}ms`,
      );
      await new Promise((resolve) =>
        setTimeout(resolve, clientPropagationBackoffMs(attempt)),
      );
    }
  }

  try {
    if (response.ChallengeName === 'SOFTWARE_TOKEN_MFA') {
      response = await respondToSoftwareTokenMfa(
        client,
        userPoolClientId,
        email,
        response.Session,
        totpSecret,
      );
    }

    if (!response.AuthenticationResult) {
      throw new Error('Authentication failed - no tokens returned');
    }

    const tokens: CognitoTokens = {
      accessToken: response.AuthenticationResult.AccessToken!,
      idToken: response.AuthenticationResult.IdToken!,
      refreshToken: response.AuthenticationResult.RefreshToken!,
    };

    // Decode token to extract account ID
    const decoded = decodeToken(tokens.idToken);

    return {
      tokens,
      accountId: decoded.sub,
      email: decoded.email,
    };
  } catch (error) {
    console.error('Cognito sign-in error:', error);
    throw new Error(`Failed to sign in user ${email}: ${error}`);
  }
}

/**
 * Helper to get account ID from token (for test assertions).
 */
export function decodeToken(token: string): { sub: string; email: string } {
  const payload = token.split('.')[1];
  const decoded = JSON.parse(Buffer.from(payload, 'base64').toString());
  return {
    sub: decoded.sub,
    email: decoded.email,
  };
}
