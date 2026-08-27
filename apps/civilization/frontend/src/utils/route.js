/**
 * The view and the project, in the URL.
 *
 * There is no router: the active panel is a value in component state. That is
 * fine for switching, and not fine for everything else — a person could not
 * send a colleague a link to what they were looking at, and a refresh always
 * returned them to the chatbot (F.4).
 *
 * The address is `#/{view}/{project}`. A hash rather than a path because the
 * app is served as static assets behind a proxy that does not rewrite unknown
 * paths to `index.html`; a real path would 404 on refresh, which is the
 * problem this is meant to solve.
 */

export const VIEWS = [
  'chatbot', 'playground', 'discovery', 'civilization',
  'agents', 'tools', 'documents', 'sessions', 'guardrails',
];

export const DEFAULT_VIEW = 'chatbot';

/** What the current URL says. Unknown views fall back rather than blanking. */
export function readRoute(hash = window.location.hash) {
  const [, view, project] = (hash || '').replace(/^#\/?/, '/').split('/');
  return {
    view: VIEWS.includes(view) ? view : DEFAULT_VIEW,
    project: project ? decodeURIComponent(project) : null,
  };
}

/**
 * Point the URL at what is on screen.
 *
 * `replaceState`, not `pushState`: switching panels is not navigation, and a
 * back button that walks through every tab someone glanced at is worse than
 * no history at all. The address stays shareable either way.
 */
export function writeRoute({ view, project }) {
  const next = `#/${view || DEFAULT_VIEW}` +
    (project ? `/${encodeURIComponent(project)}` : '');
  if (window.location.hash !== next) {
    window.history.replaceState(null, '', next);
  }
}
