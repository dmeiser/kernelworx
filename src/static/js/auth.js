/**
 * KernelWorx Auth Shim
 * Manages Cognito JWT tokens in sessionStorage and injects Authorization headers on HTMX requests.
 */

// Inject Authorization header on every HTMX request
document.addEventListener('htmx:configRequest', (event) => {
  const tokens = JSON.parse(sessionStorage.getItem('kw_tokens') || 'null');
  if (tokens && tokens.id_token) {
    event.detail.headers['Authorization'] = 'Bearer ' + tokens.id_token;
  }
});

// Handle OAuth Code Redirect on return from Google / Cognito Hosted Auth
(function checkOAuthCode() {
  const urlParams = new URLSearchParams(window.location.search);
  const code = urlParams.get('code');
  if (code) {
    // Clean up code parameter from URL
    window.history.replaceState({}, document.title, window.location.pathname);
  }
})();

// Logout helper
function logout() {
  sessionStorage.removeItem('kw_tokens');
  window.location.href = '/login';
}

// Redirect on 401 Unauthorized
document.addEventListener('htmx:responseError', (event) => {
  if (event.detail.xhr.status === 401) {
    logout();
  }
});
