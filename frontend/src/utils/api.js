/**
 * One way to call the backend.
 *
 * Twenty-eight `fetch` calls with twenty-eight hand-written error handlers is
 * twenty-eight chances to handle one wrong, and two of them were: the document
 * panel never sent `org_id`, so every upload and query landed in whichever
 * realm the backend defaults to rather than the signed-in user's (F.28).
 *
 * Two things are structural here rather than left to each call site:
 *
 * **Tenancy.** `org_id` is attached to every request, and `project_id` to every
 * project-scoped one, from a context the shell sets once. The services keep
 * each organisation in its own PostgreSQL schema, so a call that omits the
 * organisation does not fail — it reads someone else's realm, or an empty one,
 * and looks like a system with no data in it (F.35).
 *
 * **Failure.** Everything that is not a 2xx throws an `ApiError`, so a caller
 * cannot accidentally treat a 502 as data. Being unable to reach the backend
 * and the backend returning nothing are different conditions and are
 * distinguishable here, because they mean opposite things to a user (F.38).
 */

/** The tenancy every request carries. Set by the shell after sign-in. */
let context = { orgId: null, projectId: null };

export function setApiContext(next) {
  context = { ...context, ...next };
}

export function getApiContext() {
  return { ...context };
}

/**
 * A failed request.
 *
 * `reachable` is the field worth reading: false means the backend could not be
 * contacted at all, which is a deployment problem, not an empty result.
 */
export class ApiError extends Error {
  constructor(message, { status = 0, url = '', detail = null, reachable = true } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.url = url;
    this.detail = detail;
    this.reachable = reachable;
  }

  /** A sentence worth showing a person: what failed, and where. */
  get userMessage() {
    if (!this.reachable) {
      return `Could not reach the backend (${this.url}). Check that the API is running.`;
    }
    const detail = typeof this.detail === 'string' ? this.detail : null;
    return detail || `Request failed (HTTP ${this.status}) — ${this.url}`;
  }
}

function withTenancy(params = {}, { scoped = true } = {}) {
  const merged = { ...params };
  if (merged.org_id === undefined && context.orgId) merged.org_id = context.orgId;
  if (scoped && merged.project_id === undefined && context.projectId) {
    merged.project_id = context.projectId;
  }
  return merged;
}

function buildUrl(path, params) {
  const query = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    query.append(key, value);
  });
  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

async function parse(res, url) {
  const text = await res.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    const detail = body && typeof body === 'object' ? body.detail ?? body.message : body;
    throw new ApiError(`HTTP ${res.status}`, {
      status: res.status, url, detail, reachable: true,
    });
  }
  return body;
}

async function send(path, { method = 'GET', params, body, form, scoped = true,
                            signal, timeoutMs = 120000 } = {}) {
  const url = buildUrl(path, withTenancy(params, { scoped }));

  // A request with no ceiling is a spinner that never stops. Uploads and
  // pipeline runs are slow, so the ceiling is generous rather than absent.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  if (signal) signal.addEventListener('abort', () => controller.abort());

  const init = { method, signal: controller.signal };
  if (form) {
    init.body = form;                       // the browser sets the boundary
  } else if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(withTenancyBody(body, { scoped }));
  }

  let res;
  try {
    res = await fetch(url, init);
  } catch (err) {
    throw new ApiError(err.name === 'AbortError'
      ? `Request timed out after ${Math.round(timeoutMs / 1000)}s`
      : err.message, { url, reachable: false });
  } finally {
    clearTimeout(timer);
  }
  return parse(res, url);
}

/** JSON bodies carry the tenancy too — several endpoints read it from there. */
function withTenancyBody(body, { scoped }) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return body;
  const merged = { ...body };
  if (merged.org_id === undefined && context.orgId) merged.org_id = context.orgId;
  if (scoped && merged.project_id === undefined && context.projectId) {
    merged.project_id = context.projectId;
  }
  return merged;
}

/**
 * A server-sent-event stream, with the tenancy attached like any other call.
 *
 * `EventSource` cannot POST and cannot carry a body, and a goal does not
 * belong in a query string, so this reads the response body itself and parses
 * the event framing. `onEvent(name, data)` is called as each event arrives —
 * which is the whole point: a trace delivered at the end is a log, not a live
 * view of work happening.
 *
 * Returns when the stream closes. Aborting the returned controller stops it.
 */
export async function stream(path, body, onEvent, { scoped = true, signal } = {}) {
  const url = buildUrl(path, withTenancy({}, { scoped }));
  let res;
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(withTenancyBody(body, { scoped })),
      signal,
    });
  } catch (err) {
    throw new ApiError(err.message, { url, reachable: false });
  }
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try { detail = JSON.parse(text).detail ?? text; } catch { /* plain text */ }
    throw new ApiError(`HTTP ${res.status}`, { status: res.status, url, detail });
  }
  if (!res.body) {
    throw new ApiError('This browser cannot read a streamed response.', { url });
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  // Events are separated by a blank line; a event may arrive split across
  // reads, so only complete blocks are parsed.
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let split;
    while ((split = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      let name = 'message';
      const data = [];
      for (const line of block.split('\n')) {
        if (line.startsWith(':')) continue;             // keepalive comment
        if (line.startsWith('event:')) name = line.slice(6).trim();
        else if (line.startsWith('data:')) data.push(line.slice(5).trim());
      }
      if (!data.length) continue;
      let payload = data.join('\n');
      try { payload = JSON.parse(payload); } catch { /* leave as text */ }
      onEvent(name, payload);
    }
  }
}

export const api = {
  get: (path, options) => send(path, { ...options, method: 'GET' }),
  post: (path, body, options) => send(path, { ...options, method: 'POST', body }),
  del: (path, options) => send(path, { ...options, method: 'DELETE' }),
  stream,

  /**
   * A multipart upload. `fields` are appended alongside the files, and the
   * tenancy goes in the query string, because FastAPI reads `Query` parameters
   * there even on a multipart route.
   */
  upload: (path, { files = [], fields = {}, params, timeoutMs = 600000 } = {}) => {
    const form = new FormData();
    Object.entries(fields).forEach(([key, value]) => form.append(key, value));
    files.forEach(({ name, file }) => form.append(name, file));
    return send(path, { method: 'POST', form, params, timeoutMs });
  },
};

/**
 * Run a request and hand back `{ data, error }` instead of throwing.
 *
 * For the common view shape: try to load, render either the data or the
 * failure. The error is an `ApiError`, so a view can tell "nothing here" from
 * "could not ask" (F.38).
 */
export async function attempt(promise) {
  try {
    return { data: await promise, error: null };
  } catch (error) {
    if (error instanceof ApiError) return { data: null, error };
    return { data: null, error: new ApiError(error.message, { reachable: false }) };
  }
}
