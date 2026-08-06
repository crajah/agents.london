/**
 * OAuth 2.0 / OIDC Authentication Module
 *
 * Google: Google Identity Services (GIS) SDK with server-side token verification.
 *         Falls back to authorization code popup flow if GIS is unavailable.
 * Microsoft: OAuth2 Authorization Code + PKCE via popup with server-side code exchange.
 *
 * All tokens and codes are verified server-side via /api/auth/{provider}/verify.
 */

export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';
export const MS_CLIENT_ID = import.meta.env.VITE_MS_CLIENT_ID || '';

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
export function triggerGoogleOIDC(onSuccess, onError) {
  const clientId = GOOGLE_CLIENT_ID;
  if (!clientId) {
    onError('Google Client ID not configured. Set VITE_GOOGLE_CLIENT_ID in .env');
    return;
  }

  // Primary: Google Identity Services SDK
  if (window.google?.accounts?.id) {
    try {
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: async (response) => {
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
        },
      });
      window.google.accounts.id.prompt((notification) => {
        if (notification.isNotDisplayed() || notification.isSkippedMoment()) {
          // One Tap suppressed (cooldown, browser settings, etc.) — use popup
          _googleAuthCodePopup(clientId, onSuccess, onError);
        }
      });
      return;
    } catch (err) {
      console.warn('GIS SDK error, falling back to popup:', err);
    }
  }

  // Fallback: authorization code popup
  _googleAuthCodePopup(clientId, onSuccess, onError);
}

function _googleAuthCodePopup(clientId, onSuccess, onError) {
  const redirectUri = window.location.origin;
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
  const redirectUri = window.location.origin;

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
            onError('Authentication window was closed');
          }
        }, 1000);
      }
    } catch (e) {
      // Cross-Origin-Opener-Policy blocks popup.closed access on some providers.
      // Auth still works via postMessage — this check is just a fallback.
    }
  }, 500);
}
