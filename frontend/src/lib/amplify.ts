/**
 * AWS Amplify configuration for Cognito authentication
 */

import { Amplify } from "aws-amplify";

// Configure Amplify with Cognito settings
Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
      userPoolClientId: import.meta.env.VITE_COGNITO_USER_POOL_CLIENT_ID,
      loginWith: {
        oauth: {
          domain: import.meta.env.VITE_COGNITO_DOMAIN,
          scopes: ["openid", "email", "profile"],
          redirectSignIn: [import.meta.env.VITE_OAUTH_REDIRECT_SIGNIN],
          redirectSignOut: [import.meta.env.VITE_OAUTH_REDIRECT_SIGNOUT],
          responseType: "code",
        },
        // WebAuthn configuration
        // The RP ID must match the application domain, not the Cognito auth domain
        webAuthn: {
          // For localhost: use 'localhost' (WebAuthn RP ID can't include port)
          // For production: use the app domain (dev.kernelworx.app, not login.dev.kernelworx.app)
          rpId:
            window.location.hostname === "localhost" ||
            window.location.hostname === "127.0.0.1"
              ? "localhost"
              : window.location.hostname,
        },
      },
    },
  },
});

export default Amplify;
