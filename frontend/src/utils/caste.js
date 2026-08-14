/**
 * How a caste is coloured, in one place.
 *
 * The mapping lived inside the registry view as a local function. The
 * discovery view called it too — and there it was simply undefined, so the
 * panel threw `getCasteColor is not defined` the moment it rendered an agent.
 * The build did not catch it: bundling resolves imports, not free identifiers,
 * so an undefined name is a runtime error in production and nothing earlier.
 *
 * Shared rather than copied: two colour maps that disagree mean the same agent
 * is a different colour depending on which panel you found it in.
 */

/** A MUI palette key for a caste. Unknown castes are grey rather than absent. */
export function casteColor(caste) {
  switch (caste) {
    case 'genesis': return 'secondary';
    case 'archivist': return 'info';
    case 'architect': return 'primary';
    case 'auditor': return 'success';
    case 'pipeline': return 'warning';
    default: return 'default';
  }
}

/** The four castes the architecture declares, plus what a pipeline is filed as. */
export const CASTES = ['genesis', 'archivist', 'architect', 'auditor'];
