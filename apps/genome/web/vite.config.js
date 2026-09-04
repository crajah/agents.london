// base comes from the environment, never from forwarded CLI args: with a
// compound build script (`vite build && node check-budget.mjs`), npm's
// `--` forwarding appends flags to the LAST command -- which silently
// handed --base=/genome/ to the budget checker and shipped a root-based
// bundle that 404ed behind the /genome/ ingress (2026-09-04).
export default {
  base: process.env.VITE_BASE || "/",
};
