/**
 * OAuth 2.0 / OIDC Authentication Module
 *
 * Google: Google Identity Services (GIS) SDK with server-side token verification.
 *         Falls back to authorization code popup flow if GIS is unavailable.
 * Microsoft: OAuth2 Authorization Code + PKCE via popup with server-side code exchange.
 *
 * All tokens and codes are verified server-side via /api/auth/{provider}/verify.
 */

// `import.meta.env` is Vite's, and does not exist under plain Node — which made
// this module impossible to test at all. Reading it through a guard costs
// nothing in the bundle and makes the sign-in helpers reachable from tests.
const _env = (typeof import.meta !== 'undefined' && import.meta.env) || {};

export const GOOGLE_CLIENT_ID = _env.VITE_GOOGLE_CLIENT_ID || '';
export const MS_CLIENT_ID = _env.VITE_MS_CLIENT_ID || '';

// ─── JWT Parsing (display only — auth decisions use server-side verification) ─

export function parseJwtPayload(token) {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    );
    return JSON.parse(jsonPayload);
  } catch (e) {
    console.error('Failed to parse JWT payload:', e);
    return null;
  }
}

// ─── PKCE Helpers ──────────────────────────────────────────────────────────

function generateCodeVerifier() {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return Array.from(array, (b) => b.toString(16).padStart(2, '0')).join('');
}

async function generateCodeChallenge(verifier) {
  const data = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

// ─── Server-side Token/Code Verification ───────────────────────────────────

async function verifyWithBackend(provider, payload) {
  const endpoint = provider === 'google' ? '/api/auth/google/verify' : '/api/auth/ms/verify';
  const res = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `${provider} verification failed`);
  }
  return res.json();
}

// ─── Popup Callback (runs inside the OAuth redirect popup window) ──────────

/**
 * Call on app load. If this window is a popup redirected back from an OAuth
 * provider, extract the authorization code and post it to the opener.
 */
export function checkAndHandleOidcCallback() {
  if (!window.opener) return false;

  const params = new URLSearchParams(window.location.search);
  const error = params.get('error');

  if (error) {
    window.opener.postMessage(
      { type: 'OIDC_ERROR', error, description: params.get('error_description') || error },
      window.location.origin
    );
    window.close();
    return true;
  }

  const code = params.get('code');
  if (code) {
    window.opener.postMessage(
      { type: 'OIDC_CODE', code, state: params.get('state') || '' },
      window.location.origin
    );
    window.close();
    return true;
  }

  // Handle id_token in hash fragment (legacy / GIS redirect)
  const hashParams = new URLSearchParams(window.location.hash.substring(1));
  const idToken = hashParams.get('id_token');
  if (idToken) {
    window.opener.postMessage(
      { type: 'OIDC_TOKEN', id_token: idToken },
      window.location.origin
    );
    window.close();
    return true;
  }

  return false;
}

// ─── Google OIDC ───────────────────────────────────────────────────────────

/**
 * Triggers Google authentication.
 *
 * Primary path: Google Identity Services (GIS) SDK — shows One Tap or
 * account chooser, returns an id_token verified server-side.
 *
 * Fallback: Authorization code popup flow — opens Google consent screen,
 * captures the code, sends it to backend for exchange.
 *
 * @param {(session: {email, orgId, userId, verified, provider}) => void} onSuccess
 * @param {(error: string) => void} onError
 */
/**
 * What a `403` from Google actually means, said in a way that can be acted on.
 *
 * Google Identity Services requests `accounts.google.com/gsi/status` before it
 * will show anything, and answers `403 Forbidden` when the page's origin is not
 * an Authorized JavaScript origin for that client. Nothing in the page can fix
 * that, so the least this can do is name the two values that have to match —
 * the origin and the client — instead of leaving a 403 in the console and a
 * button that does nothing.
 */
export function googleOriginHelp(clientId) {
  const origin = window.location.origin;
  // The whole client id, not a prefix. It is public — it ships in the bundle —
  // and a project with several OAuth clients has several that share a prefix,
  // so a truncated one cannot be matched against the console, which is the one
  // thing this message exists to let someone do.
  const id = clientId || '(none — VITE_GOOGLE_CLIENT_ID was empty at build time)';
  return (
    `Google rejected this origin. Add ${origin} to the OAuth client's ` +
    `"Authorized JavaScript origins" (and to "Authorized redirect URIs" for the ` +
    `popup fallback) in the Google Cloud console, for client ${id}. ` +
    `A 403 from accounts.google.com means the origin and the client do not match.`
  );
}

export function triggerGoogleOIDC(onSuccess, onError) {
  const clientId = GOOGLE_CLIENT_ID;
  if (!clientId) {
    onError('Google sign-in is not configured: VITE_GOOGLE_CLIENT_ID was empty '
            + 'when this bundle was built. It is a build-time value, so setting '
            + 'it now requires a rebuild.');
    return;
  }

  const onCredential = async (response) => {
    try {
      const data = await verifyWithBackend('google', { id_token: response.credential });
      onSuccess({
        email: data.email,
        orgId: data.org_id,
        userId: data.user_id,
        verified: true,
        provider: 'google',
      });
    } catch (err) {
      onError(err.message);
    }
  };

  // Only one fallback, however many ways the attempt fails.
  let handedOff = false;
  const fallback = (why) => {
    if (handedOff) return;
    handedOff = true;
    if (why) console.warn('Google One Tap unavailable:', why);
    _googleAuthCodePopup(clientId, onSuccess, onError);
  };

  if (!window.google?.accounts?.id) {
    // The GIS script is loaded async in index.html and may not have arrived,
    // or may be blocked by an extension or a content blocker.
    fallback('the Google Identity script has not loaded');
    return;
  }

  try {
    window.google.accounts.id.initialize({
      client_id: clientId,
      callback: onCredential,
      // GIS reports origin and configuration failures here rather than
      // throwing. Without it, a rejected origin is a console 403 and a button
      // that does nothing at all.
      error_callback: (err) => {
        const kind = err?.type || err?.message || 'unknown';
        if (String(kind).includes('origin') || String(kind).includes('unregistered')) {
          handedOff = true;
          onError(googleOriginHelp(clientId));
          return;
        }
        fallback(kind);
      },
    });

    window.google.accounts.id.prompt((notification) => {
      // `isNotDisplayed()` and `isSkippedMoment()` are deprecated, and throw
      // once FedCM is on — which is the default. They used to be called
      // unguarded from inside this callback, so the exception escaped the try
      // block around `prompt()` entirely: One Tap silently did nothing and the
      // popup fallback never ran. Anything other than a displayed prompt is
      // treated as "use the popup".
      let displayed = false;
      try {
        displayed = typeof notification?.isDisplayed === 'function'
          ? notification.isDisplayed()
          : false;
      } catch {
        displayed = false;
      }
      if (!displayed) fallback('One Tap was not displayed');
    });
  } catch (err) {
    fallback(err?.message || err);
  }
}

function _googleAuthCodePopup(clientId, onSuccess, onError) {
  const redirectUri = window.location.origin + (import.meta.env.BASE_URL || '/');  // subpath-aware: the popup must return INTO the app, not onto the landing page
  const url = new URL('https://accounts.google.com/o/oauth2/v2/auth');
  url.searchParams.set('client_id', clientId);
  url.searchParams.set('redirect_uri', redirectUri);
  url.searchParams.set('response_type', 'code');
  url.searchParams.set('scope', 'openid email profile');
  url.searchParams.set('state', 'google');
  url.searchParams.set('prompt', 'select_account');

  _openOAuthPopup(url.toString(), 'google', redirectUri, onSuccess, onError);
}

// ─── Microsoft OIDC ────────────────────────────────────────────────────────

/**
 * Triggers Microsoft authentication via OAuth2 Authorization Code + PKCE.
 *
 * Opens a popup to the Microsoft login page, captures the authorization code,
 * and sends it along with the PKCE code_verifier to the backend for exchange.
 *
 * @param {(session: {email, orgId, userId, verified, provider}) => void} onSuccess
 * @param {(error: string) => void} onError
 */
export async function triggerMicrosoftOIDC(onSuccess, onError) {
  const clientId = MS_CLIENT_ID;
  if (!clientId) {
    onError('Microsoft Client ID not configured. Set VITE_MS_CLIENT_ID in .env');
    return;
  }

  const codeVerifier = generateCodeVerifier();
  const codeChallenge = await generateCodeChallenge(codeVerifier);
  const redirectUri = window.location.origin + (import.meta.env.BASE_URL || '/');  // subpath-aware: the popup must return INTO the app, not onto the landing page

  const url = new URL('https://login.microsoftonline.com/common/oauth2/v2.0/authorize');
  url.searchParams.set('client_id', clientId);
  url.searchParams.set('response_type', 'code');
  url.searchParams.set('redirect_uri', redirectUri);
  url.searchParams.set('scope', 'openid email profile');
  url.searchParams.set('response_mode', 'query');
  url.searchParams.set('state', 'microsoft');
  url.searchParams.set('code_challenge', codeChallenge);
  url.searchParams.set('code_challenge_method', 'S256');
  url.searchParams.set('prompt', 'select_account');

  _openOAuthPopup(url.toString(), 'microsoft', redirectUri, onSuccess, onError, codeVerifier);
}

// ─── Shared Popup Logic ────────────────────────────────────────────────────

function _openOAuthPopup(authUrl, provider, redirectUri, onSuccess, onError, codeVerifier) {
  const popup = window.open(authUrl, `${provider}OAuth`, 'width=520,height=620');
  if (!popup) {
    onError('Popup blocked by browser. Please allow popups for this site.');
    return;
  }

  let resolved = false;

  function cleanup() {
    resolved = true;
    clearInterval(checkClosedTimer);
    window.removeEventListener('message', messageHandler);
  }

  const messageHandler = async (event) => {
    if (event.origin !== window.location.origin) return;
    if (resolved) return;

    if (event.data?.type === 'OIDC_ERROR') {
      cleanup();
      onError(event.data.description || event.data.error);
      return;
    }

    if (event.data?.type === 'OIDC_CODE') {
      cleanup();
      try {
        const payload = { code: event.data.code, redirect_uri: redirectUri };
        if (codeVerifier) payload.code_verifier = codeVerifier;
        const data = await verifyWithBackend(provider, payload);
        onSuccess({
          email: data.email,
          orgId: data.org_id,
          userId: data.user_id,
          verified: true,
          provider,
        });
      } catch (err) {
        onError(err.message);
      }
      return;
    }

    if (event.data?.type === 'OIDC_TOKEN') {
      cleanup();
      try {
        const data = await verifyWithBackend(provider, { id_token: event.data.id_token });
        onSuccess({
          email: data.email,
          orgId: data.org_id,
          userId: data.user_id,
          verified: true,
          provider,
        });
      } catch (err) {
        onError(err.message);
      }
    }
  };

  window.addEventListener('message', messageHandler);

  const checkClosedTimer = setInterval(() => {
    try {
      if (popup.closed) {
        clearInterval(checkClosedTimer);
        setTimeout(() => {
          if (!resolved) {
            window.removeEventListener('message', messageHandler);
            // A closed window with no result is usually someone changing their
            // mind — but it is also what a rejected origin looks like, because
            // the provider shows its own error page and the person closes it.
            // Naming the second possibility costs nothing and saves the search
            // through a console for a 403 nobody was looking for.
            onError(
              provider === 'google'
                ? `Authentication window closed before sign-in finished. `
                  + `If it showed an error rather than a sign-in prompt: `
                  + googleOriginHelp(GOOGLE_CLIENT_ID)
                : 'Authentication window was closed');
          }
        }, 1000);
      }
    } catch {
      // Cross-Origin-Opener-Policy blocks popup.closed access on some providers.
      // Auth still works via postMessage — this check is just a fallback.
    }
  }, 500);
}
