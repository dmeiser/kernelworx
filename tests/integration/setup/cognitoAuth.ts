import { CognitoIdentityProviderClient, InitiateAuthCommand, AuthFlowType } from '@aws-sdk/client-cognito-identity-provider';
import { getAwsConfig } from './awsConfig';

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
 * Sign in a user and return Cognito tokens with account ID.
 */
export async function signInUser(email: string, password: string): Promise<AuthResult> {
  // Get config dynamically from AWS
  const config = await getAwsConfig();
  const { userPoolId, userPoolClientId, region } = config;

  const client = new CognitoIdentityProviderClient({ region });

  try {
    const command = new InitiateAuthCommand({
      AuthFlow: AuthFlowType.USER_PASSWORD_AUTH,
      ClientId: userPoolClientId,
      AuthParameters: {
        USERNAME: email,
        PASSWORD: password,
      },
    });

    const response = await client.send(command);

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
