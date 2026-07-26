/**
 * KernelWorx Auth Shim
 * Manages Cognito JWT tokens in sessionStorage, injects Authorization headers on HTMX
 * requests, and handles Google / Cognito Hosted UI OAuth code exchange with PKCE.
 */

/**
 * Read Cognito configuration rendered by the server on the <body> element.
 */
function getAuthConfig() {
  const body = document.body;
  return {
    siteDomain: body.dataset.siteDomain || window.location.host || '',
    cognitoDomain: body.dataset.cognitoDomain || '',
    clientId: body.dataset.cognitoClientId || '',
  };
}

function redirectUri() {
  const { siteDomain } = getAuthConfig();
  const host = siteDomain || window.location.host;
  return `${window.location.protocol}//${host}`;
}

/**
 * Inject Authorization header on every HTMX request.
 */
document.addEventListener('htmx:configRequest', (event) => {
  const tokens = JSON.parse(sessionStorage.getItem('kw_tokens') || 'null');
  if (tokens && tokens.access_token) {
    event.detail.headers['Authorization'] = 'Bearer ' + tokens.access_token;
  }
});

/**
 * Redirect on 401 Unauthorized.
 */
document.addEventListener('htmx:responseError', (event) => {
  if (event.detail.xhr.status === 401) {
    logout();
  }
});

/**
 * Logout helper.
 */
function logout() {
  sessionStorage.removeItem('kw_tokens');
  sessionStorage.removeItem('kw_pkce_verifier');
  window.location.href = '/login';
}

function storeTokens(tokens) {
  if (tokens && tokens.id_token) {
    sessionStorage.setItem('kw_tokens', JSON.stringify(tokens));
  }
}

function finishSignIn(tokens) {
  if (!tokens || !tokens.access_token) {
    showAuthError('Unable to create session: missing access token.');
    return;
  }
  fetch('/api/auth/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ access_token: tokens.access_token }),
  })
    .then(async (response) => {
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(body.error || 'Failed to create session.');
      }
      window.location.href = '/scouts';
    })
    .catch((error) => {
      showAuthError(error.message);
    });
}

function showAuthError(message) {
  const errorDiv = document.getElementById('login-error') || document.getElementById('signup-error');
  if (errorDiv) {
    errorDiv.textContent = message;
    errorDiv.style.display = 'block';
  } else {
    // Fallback: redirect to login with the error in the URL hash
    sessionStorage.removeItem('kw_pkce_verifier');
    window.location.href = '/login#auth-error=' + encodeURIComponent(message);
  }
}

/**
 * PKCE helpers.
 */
function generateCodeVerifier() {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~';
  const array = new Uint8Array(128);
  crypto.getRandomValues(array);
  let verifier = '';
  for (let i = 0; i < array.length; i++) {
    verifier += chars[array[i] % chars.length];
  }
  return verifier;
}

async function generateCodeChallenge(verifier) {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest('SHA-256', data);
  const bytes = new Uint8Array(digest);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function buildAuthorizeUrl(config, challenge) {
  const params = new URLSearchParams({
    client_id: config.clientId,
    response_type: 'code',
    scope: 'email openid profile',
    redirect_uri: redirectUri(),
    identity_provider: 'Google',
    code_challenge_method: 'S256',
    code_challenge: challenge,
  });
  return `https://${config.cognitoDomain}/oauth2/authorize?${params.toString()}`;
}

/**
 * Handle "Continue with Google" click: generate PKCE pair, store verifier, and
 * navigate to the Cognito Hosted UI.
 */
async function handleGoogleLogin(event) {
  event.preventDefault();
  const config = getAuthConfig();
  if (!config.cognitoDomain || !config.clientId) {
    showAuthError('Google sign-in is not configured.');
    return;
  }
  try {
    const verifier = generateCodeVerifier();
    const challenge = await generateCodeChallenge(verifier);
    sessionStorage.setItem('kw_pkce_verifier', verifier);
    window.location.href = buildAuthorizeUrl(config, challenge);
  } catch (error) {
    showAuthError('Unable to start Google sign-in: ' + error.message);
  }
}

/**
 * Exchange an authorization code for tokens using the PKCE verifier.
 */
async function exchangeCodeForTokens(code, verifier, config) {
  const params = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: config.clientId,
    code: code,
    redirect_uri: redirectUri(),
    code_verifier: verifier,
  });

  const response = await fetch(`https://${config.cognitoDomain}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: params.toString(),
  });

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error_description || body.error || 'Google sign-in failed.');
  }
  return {
    id_token: body.id_token,
    access_token: body.access_token,
    refresh_token: body.refresh_token,
  };
}

/**
 * On page load, if the URL contains a Cognito authorization code, exchange it
 * for tokens and redirect to the authenticated app entry point.
 */
(function checkOAuthCode() {
  const urlParams = new URLSearchParams(window.location.search);
  const code = urlParams.get('code');
  if (!code) return;

  const config = getAuthConfig();
  const verifier = sessionStorage.getItem('kw_pkce_verifier');
  if (!config.cognitoDomain || !config.clientId || !verifier) {
    showAuthError('Unable to complete Google sign-in. Please try again.');
    return;
  }

  // Remove the code from the URL immediately to avoid replays.
  window.history.replaceState({}, document.title, window.location.pathname);

  exchangeCodeForTokens(code, verifier, config)
    .then((tokens) => {
      sessionStorage.removeItem('kw_pkce_verifier');
      storeTokens(tokens);
      finishSignIn(tokens);
    })
    .catch((error) => {
      sessionStorage.removeItem('kw_pkce_verifier');
      showAuthError(error.message);
    });
})();

/**
 * Password sign-in handler (login form submits JSON to /api/auth/login).
 */
function handleLoginSubmit(event) {
  event.preventDefault();
  const form = event.target;
  const errorDiv = document.getElementById('login-error');
  if (errorDiv) {
    errorDiv.style.display = 'none';
    errorDiv.textContent = '';
  }

  const data = {
    email: form.email.value,
    password: form.password.value,
  };

  fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
    .then(async (response) => {
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(body.error || 'Sign in failed. Please check your email and password.');
      }
      if (body.mfaRequired) {
        throw new Error('Multi-factor authentication is not supported in this flow yet.');
      }
      if (body.tokens) {
        storeTokens(body.tokens);
        finishSignIn(body.tokens);
      } else {
        throw new Error('Unexpected response from the server.');
      }
    })
    .catch((error) => {
      if (errorDiv) {
        errorDiv.textContent = error.message;
        errorDiv.style.display = 'block';
      }
    });
}

/**
 * Password sign-up handler (signup form submits JSON to /api/auth/signup).
 */
function handleSignupSubmit(event) {
  event.preventDefault();
  const form = event.target;
  const errorDiv = document.getElementById('signup-error');
  const successDiv = document.getElementById('signup-success');
  if (errorDiv) {
    errorDiv.style.display = 'none';
    errorDiv.textContent = '';
  }
  if (successDiv) {
    successDiv.style.display = 'none';
    successDiv.textContent = '';
  }

  if (form.password.value !== form.confirmPassword.value) {
    if (errorDiv) {
      errorDiv.textContent = 'Passwords do not match.';
      errorDiv.style.display = 'block';
    }
    return;
  }

  const data = {
    email: form.email.value,
    password: form.password.value,
  };

  fetch('/api/auth/signup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
    .then(async (response) => {
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(body.error || 'Sign up failed. Please try again.');
      }
      if (successDiv) {
        successDiv.textContent = 'Account created! Redirecting to sign in...';
        successDiv.style.display = 'block';
      }
      if (errorDiv) errorDiv.style.display = 'none';
      setTimeout(() => {
        window.location.href = '/login';
      }, 1500);
    })
    .catch((error) => {
      if (errorDiv) {
        errorDiv.textContent = error.message;
        errorDiv.style.display = 'block';
      }
      if (successDiv) successDiv.style.display = 'none';
    });
}

/**
 * Placeholder until passkey support is implemented.
 */
function passkeyLogin(event) {
  event.preventDefault();
  alert('Passkey sign-in is not enabled yet.');
}
