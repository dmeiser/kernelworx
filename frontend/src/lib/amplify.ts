/**
 * AWS Amplify configuration for Cognito authentication
 */

import { Amplify } from 'aws-amplify';
import { getCognitoDomain } from './cognitoDomain';

function cleanUrl(url?: string): string {
  if (!url) {
    return '';
  }
  return url.replace(/\/+$/, '');
}

/* v8 ignore start -- SSR guard */
function getBrowserOrigin(): string {
  if (typeof window === 'undefined') {
    return '';
  }
  return cleanUrl(window.location?.origin);
}
/* v8 ignore stop */

/**
 * Resolves redirect URLs for Amplify OAuth configuration.
 * Trims trailing slashes to align with standard Cognito callback URL format,
 * and falls back to window.location.origin if unset.
 */
export function getOAuthRedirectUrls(envUrl?: string): string[] {
  const origin = getBrowserOrigin();
  const primary = cleanUrl(envUrl) || origin || 'http://localhost:5173';
  const urls = [primary];
  if (origin && origin !== primary) {
    urls.push(origin);
  }
  return urls;
}

// Configure Amplify with Cognito settings
Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
      userPoolClientId: import.meta.env.VITE_COGNITO_USER_POOL_CLIENT_ID,
      loginWith: {
        oauth: {
          domain: getCognitoDomain(),
          scopes: ['openid', 'email', 'profile'],
          redirectSignIn: getOAuthRedirectUrls(import.meta.env.VITE_OAUTH_REDIRECT_SIGNIN),
          redirectSignOut: getOAuthRedirectUrls(import.meta.env.VITE_OAUTH_REDIRECT_SIGNOUT),
          responseType: 'code',
        },
      },
    },
  },
});

export default Amplify;
