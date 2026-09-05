/**
 * Which organisation a person belongs to, and how sure we are.
 *
 * The rule was written twice in the browser — once in the lock screen, once in
 * the app shell — and a third time in the backend. Three copies of a tenancy
 * rule that can disagree is a way to land in a different organisation
 * depending on which door you came through (F.5).
 *
 * There is now one authority: the backend. Every route asks it, and the answer
 * carries whether the identity behind it was actually verified.
 */

import { api } from './api.js';   // extension included so these modules run under `node --test` too

/**
 * A session.
 *
 * `verified` is the field that matters. The Google and Microsoft routes return
 * true — the token was exchanged and checked server-side. The email route
 * returns false, because nothing about it proves the address belongs to
 * whoever typed it (F.7). An interface that treats the two identically is
 * claiming something the system does not know.
 */
export function toSession(body, { method } = {}) {
  return {
    email: body.email,
    orgId: body.org_id,
    userId: body.user_id,
    isGeneric: Boolean(body.is_generic),
    verified: Boolean(body.verified),
    method: body.method || method || 'unknown',
    notice: body.notice || null,
  };
}
