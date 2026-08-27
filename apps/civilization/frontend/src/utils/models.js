/**
 * The model catalogue, fetched from the backend rather than hardcoded.
 *
 * Three views used to carry their own list of models — and all three drifted.
 * They offered DeepSeek V3.1 and V3.2 long after that provider stopped
 * answering, so a user could select a model that no agent could call, and the
 * failure surfaced much later as a run that would not start.
 *
 * `GET /api/models` asks the real router what it serves and reports the
 * deployment's configured defaults alongside. This module is the one place the
 * frontend reads that, cached for the session because the answer does not
 * change between page views.
 */

/** Used only until the first fetch resolves, and if the backend is unreachable. */
export const FALLBACK_DEFAULT_MODEL = 'gemini-3.5-flash-lite';
export const FALLBACK_EMBEDDING_MODEL = 'gemini-embedding-001';

let cache = null;
let inFlight = null;

/**
 * The catalogue: `{ models, defaultModel, embeddingModel, source, warning }`.
 *
 * Never rejects. A view that cannot reach the backend still renders with the
 * configured default rather than an empty dropdown, and `warning` says why the
 * list is short.
 */
export async function fetchModels() {
  if (cache) return cache;
  if (inFlight) return inFlight;

  inFlight = (async () => {
    try {
      const res = await fetch('/api/models');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      cache = {
        models: Array.isArray(body.models) ? body.models : [],
        defaultModel: body.default_model || FALLBACK_DEFAULT_MODEL,
        embeddingModel: body.embedding_model || FALLBACK_EMBEDDING_MODEL,
        embeddingDim: body.embedding_dim || 1536,
        source: body.source || 'unknown',
        warning: body.warning || null,
      };
      return cache;
    } catch (err) {
      // Not cached: a transient failure must not pin the UI to the fallback
      // for the rest of the session.
      return {
        models: [
          { id: FALLBACK_DEFAULT_MODEL, name: FALLBACK_DEFAULT_MODEL,
            provider: 'configured default', status: 'unverified', role: 'chat' },
        ],
        defaultModel: FALLBACK_DEFAULT_MODEL,
        embeddingModel: FALLBACK_EMBEDDING_MODEL,
        embeddingDim: 1536,
        source: 'unreachable',
        warning: `Could not reach the backend model catalogue: ${err.message}`,
      };
    } finally {
      inFlight = null;
    }
  })();

  return inFlight;
}

/** Chat models only — an embedding model is not something an agent can be assigned. */
export function chatModels(catalogue) {
  const models = catalogue?.models || [];
  return models.filter(
    (m) => m.role !== 'embedding' && !/embedding/i.test(m.id || ''),
  );
}

/** Clears the cache. For tests, and for a settings change that alters the router. */
export function resetModelCache() {
  cache = null;
  inFlight = null;
}
