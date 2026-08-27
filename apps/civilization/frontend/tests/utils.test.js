/**
 * The rules the browser must not get wrong.
 *
 * These cover the three modules that decide what every other component sends
 * and shows: which organisation a request lands in, what an unverified sign-in
 * is called, which models can be offered, and what the URL means. They run on
 * the Node test runner with a stubbed `fetch` and a stubbed `window`, so there
 * is no test dependency to install and no browser to start.
 *
 *     node --test frontend/tests/
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { api, ApiError, attempt, setApiContext, getApiContext } from '../src/utils/api.js';
import { toSession, looksLikeEmail } from '../src/utils/tenancy.js';
import { fetchModels, chatModels, resetModelCache, FALLBACK_DEFAULT_MODEL } from '../src/utils/models.js';
import { readRoute, writeRoute, VIEWS, DEFAULT_VIEW } from '../src/utils/route.js';

/** Records what the module actually put on the wire. */
function stubFetch(handler) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url, init });
    const result = handler ? await handler(url, init) : { status: 200, body: {} };
    const { status = 200, body = {} } = result;
    return {
      ok: status >= 200 && status < 300,
      status,
      text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
      json: async () => body,
    };
  };
  return calls;
}

// ------------------------------------------------------------------ tenancy

test('every request carries the organisation (F.28)', async () => {
  setApiContext({ orgId: 'org_acme', projectId: 'proj_one' });
  const calls = stubFetch();

  await api.get('/api/documents');

  const url = new URL(calls[0].url, 'http://localhost');
  assert.equal(url.searchParams.get('org_id'), 'org_acme');
  assert.equal(url.searchParams.get('project_id'), 'proj_one');
});

test('a JSON body carries the organisation too', async () => {
  setApiContext({ orgId: 'org_acme', projectId: 'proj_one' });
  const calls = stubFetch();

  await api.post('/api/conductor/compose', { goal: 'summarise contracts' });

  const sent = JSON.parse(calls[0].init.body);
  assert.equal(sent.org_id, 'org_acme');
  assert.equal(sent.project_id, 'proj_one');
  assert.equal(sent.goal, 'summarise contracts');
});

test('an unscoped call omits the project but keeps the organisation', async () => {
  setApiContext({ orgId: 'org_acme', projectId: 'proj_one' });
  const calls = stubFetch();

  await api.post('/api/auth/email/session', { email: 'a@b.com' }, { scoped: false });

  const sent = JSON.parse(calls[0].init.body);
  assert.equal(sent.project_id, undefined);
  assert.equal(sent.org_id, 'org_acme');
});

test('an explicit organisation is not overwritten by the context', async () => {
  setApiContext({ orgId: 'org_acme' });
  const calls = stubFetch();

  await api.get('/api/runs', { params: { org_id: 'org_other' } });

  const url = new URL(calls[0].url, 'http://localhost');
  assert.equal(url.searchParams.get('org_id'), 'org_other');
});

test('an upload puts the tenancy in the query string, where FastAPI reads it', async () => {
  setApiContext({ orgId: 'org_acme', projectId: 'proj_one' });
  const calls = stubFetch();

  await api.upload('/api/documents/upload', {
    files: [{ name: 'files', file: 'x' }],
    fields: { doc_key: 'k' },
  });

  const url = new URL(calls[0].url, 'http://localhost');
  assert.equal(url.searchParams.get('org_id'), 'org_acme');
  // The browser sets the multipart boundary; we must not set Content-Type.
  assert.equal(calls[0].init.headers, undefined);
});

// ------------------------------------------------------------------ failure

test('a non-2xx throws rather than returning something a view could render', async () => {
  setApiContext({ orgId: 'org_acme' });
  stubFetch(() => ({ status: 502, body: { detail: 'Tool registry unreachable' } }));

  const { data, error } = await attempt(api.get('/api/mcp/v1/tools'));

  assert.equal(data, null);
  assert.ok(error instanceof ApiError);
  assert.equal(error.status, 502);
  assert.equal(error.reachable, true);
  assert.match(error.userMessage, /Tool registry unreachable/);
});

test('unreachable and empty are distinguishable (F.38)', async () => {
  globalThis.fetch = async () => { throw new Error('connect ECONNREFUSED'); };

  const { error } = await attempt(api.get('/api/models'));

  assert.equal(error.reachable, false);
  assert.match(error.userMessage, /Could not reach the backend/);
});

// ------------------------------------------------------------------ session

test('the email route produces a session that says it is unverified (F.7)', () => {
  const session = toSession({
    email: 'someone@acme.com', org_id: 'org_acme', user_id: 'u1', verified: false,
  }, { method: 'email' });

  assert.equal(session.verified, false);
  assert.equal(session.method, 'email');
  assert.equal(session.orgId, 'org_acme');
});

test('a verified route is not downgraded, and tenancy is never re-derived here', () => {
  const session = toSession({
    email: 'someone@acme.com', org_id: 'org_from_backend', verified: true, method: 'google',
  });

  assert.equal(session.verified, true);
  // The backend is the only authority on which realm this is (F.5).
  assert.equal(session.orgId, 'org_from_backend');
});

test('an address is checked before it is sent anywhere', () => {
  assert.equal(looksLikeEmail('a@b.com'), true);
  assert.equal(looksLikeEmail('a@b'), false);
  assert.equal(looksLikeEmail('nope'), false);
  assert.equal(looksLikeEmail(''), false);
  assert.equal(looksLikeEmail('a b@c.com'), false);
});

// ------------------------------------------------------------------- models

test('the catalogue comes from the backend, and embeddings are not offered as chat models', async () => {
  resetModelCache();
  stubFetch(() => ({
    status: 200,
    body: {
      models: [
        { id: 'gemini-3.5-flash-lite', role: 'chat' },
        { id: 'gemini-embedding-001', role: 'embedding' },
      ],
      default_model: 'gemini-3.5-flash-lite',
      embedding_model: 'gemini-embedding-001',
      embedding_dim: 1536,
      source: 'router',
    },
  }));

  const catalogue = await fetchModels();

  assert.equal(catalogue.defaultModel, 'gemini-3.5-flash-lite');
  assert.equal(catalogue.embeddingDim, 1536);
  assert.deepEqual(chatModels(catalogue).map((m) => m.id), ['gemini-3.5-flash-lite']);
});

test('an unreachable router still yields the configured default, and is not cached', async () => {
  resetModelCache();
  globalThis.fetch = async () => { throw new Error('down'); };

  const first = await fetchModels();
  assert.equal(first.defaultModel, FALLBACK_DEFAULT_MODEL);
  assert.equal(first.source, 'unreachable');
  assert.match(first.warning, /Could not reach/);

  // A transient failure must not pin the session to the fallback.
  stubFetch(() => ({ status: 200, body: { models: [{ id: 'x', role: 'chat' }], default_model: 'x' } }));
  const second = await fetchModels();
  assert.equal(second.defaultModel, 'x');
});

// -------------------------------------------------------------------- route

test('the URL names the view and the project, and unknown views fall back (F.4)', () => {
  assert.deepEqual(readRoute('#/documents/proj_alpha'),
                   { view: 'documents', project: 'proj_alpha' });
  assert.deepEqual(readRoute('#/nonsense/proj_alpha'),
                   { view: DEFAULT_VIEW, project: 'proj_alpha' });
  assert.deepEqual(readRoute(''), { view: DEFAULT_VIEW, project: null });
  assert.ok(VIEWS.includes('sessions'));
});

test('switching panels replaces history rather than stacking it', () => {
  const replaced = [];
  globalThis.window = {
    location: { hash: '#/chatbot' },
    history: { replaceState: (_s, _t, url) => { replaced.push(url); globalThis.window.location.hash = url; } },
  };

  writeRoute({ view: 'tools', project: 'proj beta' });
  writeRoute({ view: 'tools', project: 'proj beta' });   // idempotent

  assert.deepEqual(replaced, ['#/tools/proj%20beta']);
  assert.equal(readRoute(globalThis.window.location.hash).project, 'proj beta');
  delete globalThis.window;
});

// ------------------------------------------------------------------ context

test('the context is readable, so the shell can prove what it set', () => {
  setApiContext({ orgId: 'org_z', projectId: 'proj_z' });
  assert.deepEqual(getApiContext(), { orgId: 'org_z', projectId: 'proj_z' });
});

// ------------------------------------------------------------------- sign-in

test('a rejected Google origin is explained, not left as a console 403', async () => {
  globalThis.window = { location: { origin: 'https://agents.london' } };
  const { googleOriginHelp } = await import('../src/utils/oidc.js');

  const help = googleOriginHelp('976346242948-poehj19t44aff.apps.googleusercontent.com');

  // The two values that have to match, both named.
  assert.match(help, /https:\/\/agents\.london/);
  assert.match(help, /976346242948-poehj19t44aff\.apps\.googleusercontent\.com/);
  assert.match(help, /Authorized JavaScript origins/);
  delete globalThis.window;
});

test('the help text survives a missing client id', async () => {
  globalThis.window = { location: { origin: 'http://localhost:3000' } };
  const { googleOriginHelp } = await import('../src/utils/oidc.js');
  assert.match(googleOriginHelp(''), /VITE_GOOGLE_CLIENT_ID was empty/);
  delete globalThis.window;
});
