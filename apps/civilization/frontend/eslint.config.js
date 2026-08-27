/**
 * What the linter is here to catch.
 *
 * `getCasteColor is not defined` shipped to a browser. A bundler could not have
 * caught it — bundling resolves imports, not free identifiers — and the unit
 * tests covered the utility modules while the mistake was in a view. The
 * hand-written scope walker in `tests/no-undefined-references.test.js` closed
 * that specific hole; this closes the rest of the class, and adds the two
 * checks that matter most in a React codebase of this shape:
 *
 * - **`react-hooks/exhaustive-deps`.** Several panels fetch in an effect keyed
 *   on the project and organisation. An effect that reads a value it does not
 *   depend on keeps serving the previous tenant's data after a switch, which
 *   in a multi-tenant system is the worst-looking bug available.
 * - **`react/jsx-key`.** A list rendered without keys reorders wrongly and
 *   silently, and the lists here are agents and runs.
 *
 * Rules are errors, not warnings. A warning in a project with no CI gate is a
 * message nobody reads twice.
 */

import js from '@eslint/js';
import globals from 'globals';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';

export default [
  { ignores: ['dist/**', 'node_modules/**'] },

  // The application: browser globals, JSX, hooks.
  {
    files: ['src/**/*.{js,jsx}'],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    settings: { react: { version: 'detect' } },
    plugins: {
      react,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...js.configs.recommended.rules,
      ...react.configs.flat.recommended.rules,
      ...reactHooks.configs['recommended-latest'].rules,

      // This project uses the automatic JSX runtime, so React need not be in
      // scope and prop types are not declared.
      'react/react-in-jsx-scope': 'off',
      'react/prop-types': 'off',

      // The one that shipped a crash.
      'no-undef': 'error',

      // Effects that read what they do not depend on: stale data across a
      // tenant switch, which is exactly the failure this app must not have.
      'react-hooks/exhaustive-deps': 'error',

      // Off, deliberately. Every panel here loads server state in an effect and
      // sets a loading flag as it starts — which is precisely the shape this
      // rule reports. The cost it warns about is one extra render on mount; the
      // cost of satisfying it would be reshaping every data-fetching panel
      // around a pattern this app does not use. A rule nobody can satisfy gets
      // disabled eventually, and disabling it deliberately with a reason is
      // better than leaving it to be switched off in a hurry.
      'react-hooks/set-state-in-effect': 'off',

      // Lists here are agents, runs and revisions. Reordering them wrongly is
      // silent, and looks like the data changed.
      'react/jsx-key': 'error',

      // An unused variable after a refactor is usually a line that was meant
      // to be deleted with the code that used it. Arguments are exempt:
      // dropping an unused callback parameter changes the signature.
      'no-unused-vars': ['error', {
        args: 'none',
        varsIgnorePattern: '^_',
        ignoreRestSiblings: true,
      }],

      // Fast refresh only works when a module exports components and nothing
      // else; a violation costs a full reload, so it is a warning, not a bug.
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },

  // The tests: Node, not a browser.
  {
    files: ['tests/**/*.js'],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.node },
    },
    rules: {
      ...js.configs.recommended.rules,
      'no-unused-vars': ['error', { args: 'none' }],
    },
  },

  // This file and any other config: Node module scope.
  {
    files: ['*.config.js', 'vite.config.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.node },
    },
  },
];
