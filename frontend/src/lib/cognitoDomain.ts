/**
 * Cognito OAuth domain resolution.
 *
 * For app-initiated OAuth flows (such as social login with Google), the OAuth
 * domain must be Cognito's custom domain (e.g. login.dev.kernelworx.app in dev,
 * login.kernelworx.app in prod) or the Amazon Cognito prefix domain (in ephemeral
 * environments). If the OAuth flow were initiated on the bare site domain
 * (dev.kernelworx.app), Cognito's CSRF state cookie would be set on
 * dev.kernelworx.app, but external IdPs (Google) redirect back to the registered
 * IdP response endpoint on login.dev.kernelworx.app/oauth2/idpresponse. Browsers
 * do not send host-only cookies cross-subdomain, causing Cognito to fail CSRF
 * validation and redirect to /login with HTTP 401 (Unauthorized).
 *
 * When VITE_COGNITO_DOMAIN is unset (dev/prod builds), the domain is derived
 * by prepending 'login.' to the site host. Ephemeral environments and local
 * `vite dev` set VITE_COGNITO_DOMAIN explicitly.
 */
function getRedirectHost(): string {
  const redirectSignIn = import.meta.env.VITE_OAUTH_REDIRECT_SIGNIN;
  if (!redirectSignIn) {
    return '';
  }
  try {
    return new URL(redirectSignIn).host;
  } catch {
    return redirectSignIn;
  }
}

/* v8 ignore start -- SSR guard */
function getBrowserHost(): string {
  if (typeof window === 'undefined') {
    return '';
  }
  return window.location?.host || '';
}
/* v8 ignore stop */

function isLocalOrPrefixed(host: string): boolean {
  if (host.startsWith('login.')) {
    return true;
  }
  return host.includes('localhost') || host.includes('127.0.0.1') || host.includes(':');
}

export function getCognitoDomain(): string {
  if (import.meta.env.VITE_COGNITO_DOMAIN) {
    return import.meta.env.VITE_COGNITO_DOMAIN;
  }

  const host = getRedirectHost() || getBrowserHost();
  if (!host || isLocalOrPrefixed(host)) {
    return host;
  }

  return `login.${host}`;
}
