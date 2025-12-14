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
      },
    },
  },
});

export default Amplify;
