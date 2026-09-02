/**
 * Cognito OAuth domain resolution.
 *
 * Dev/prod serve auth same-origin: the site's CloudFront distribution proxies
 * Cognito's custom domain at root paths (/login, /logout, /oauth2/*,
 * /.well-known/*), so no dedicated login domain is configured and the OAuth
 * domain is the site host itself. Ephemeral environments and local `vite dev`
 * keep setting VITE_COGNITO_DOMAIN explicitly (ephemeral has no CloudFront).
 */
export function getCognitoDomain(): string {
  if (import.meta.env.VITE_COGNITO_DOMAIN) {
    return import.meta.env.VITE_COGNITO_DOMAIN;
  }

  const redirectSignIn = import.meta.env.VITE_OAUTH_REDIRECT_SIGNIN;
  if (redirectSignIn) {
    return new URL(redirectSignIn).host;
  }

  return window.location.host;
}
