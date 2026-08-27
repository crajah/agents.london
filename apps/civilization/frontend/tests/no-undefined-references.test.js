/**
 * Nothing in the app may reference a name that does not exist.
 *
 * `getCasteColor is not defined` reached production. The discovery panel called
 * a helper that was defined in a different component's module scope, and the
 * moment it rendered an agent it threw. Nothing before the browser caught it:
 * `vite build` resolves imports and bundles modules, but a free identifier is
 * not a build error — it is a runtime error, and only on the code path that
 * touches it. The 15 unit tests covered the utility modules, and this was in a
 * view.
 *
 * So this walks every source file with Babel's own parser and scope analysis —
 * the same parser Vite uses — and fails on any identifier that resolves to
 * neither a binding in scope, an import, nor a browser or JS global. It is the
 * cheap half of a linter, aimed at exactly the mistake that got through, and it
 * needs no new dependency: @babel/parser and @babel/traverse are already here
 * via @vitejs/plugin-react.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import { parse } from '@babel/parser';
import traverseModule from '@babel/traverse';

const traverse = traverseModule.default || traverseModule;
const SRC = fileURLToPath(new URL('../src', import.meta.url));

/** Names that exist at runtime without being declared or imported. */
const GLOBALS = new Set([
  // JS
  'globalThis', 'console', 'Math', 'JSON', 'Object', 'Array', 'String', 'Number',
  'Boolean', 'Date', 'Error', 'TypeError', 'RangeError', 'Promise', 'Map', 'Set',
  'WeakMap', 'WeakSet', 'Symbol', 'RegExp', 'Intl', 'BigInt', 'Infinity', 'NaN',
  'undefined', 'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'encodeURIComponent',
  'decodeURIComponent', 'encodeURI', 'decodeURI', 'structuredClone', 'queueMicrotask',
  'ArrayBuffer', 'DataView', 'Uint8Array', 'Uint16Array', 'Uint32Array',
  'Uint8ClampedArray', 'Int8Array', 'Int16Array', 'Int32Array', 'Float32Array',
  'Float64Array', 'BigInt64Array', 'BigUint64Array', 'TextEncoder', 'TextDecoder',
  'Proxy', 'Reflect',
  // Browser
  'window', 'document', 'navigator', 'location', 'history', 'localStorage',
  'sessionStorage', 'fetch', 'Headers', 'Request', 'Response', 'FormData', 'Blob',
  'File', 'FileReader', 'URL', 'URLSearchParams', 'AbortController', 'WebSocket',
  'EventSource', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval',
  'requestAnimationFrame', 'cancelAnimationFrame', 'alert', 'confirm', 'prompt',
  'matchMedia', 'getComputedStyle', 'crypto', 'btoa', 'atob', 'CustomEvent',
  'Event', 'IntersectionObserver', 'ResizeObserver', 'MutationObserver', 'Image',
  'performance', 'screen', 'scrollTo', 'open', 'close', 'print',
  // Build-time
  'process', 'import',
]);

function sourceFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...sourceFiles(full));
    } else if (/\.(jsx?|mjs)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

function undefinedReferences(file) {
  const code = readFileSync(file, 'utf8');
  const ast = parse(code, {
    sourceType: 'module',
    plugins: ['jsx', 'classProperties', 'optionalChaining', 'nullishCoalescingOperator',
              'objectRestSpread', 'dynamicImport', 'topLevelAwait'],
  });

  const problems = [];
  traverse(ast, {
    ReferencedIdentifier(path) {
      const { name } = path.node;
      if (GLOBALS.has(name)) return;
      // JSX intrinsics (`<div>`, `<span>`) parse as identifiers but are strings.
      if (path.parentPath?.isJSXOpeningElement?.() || path.parentPath?.isJSXClosingElement?.()) {
        if (/^[a-z]/.test(name)) return;
      }
      if (path.scope.hasBinding(name, /* noGlobals */ true)) return;
      problems.push({ name, line: path.node.loc?.start.line });
    },
  });

  // One entry per name: a helper called in a loop is one mistake, not thirty.
  const seen = new Map();
  for (const problem of problems) {
    if (!seen.has(problem.name)) seen.set(problem.name, problem.line);
  }
  return [...seen].map(([name, line]) => ({ name, line }));
}

test('every referenced name is defined, imported or a known global', () => {
  const failures = [];
  for (const file of sourceFiles(SRC)) {
    for (const { name, line } of undefinedReferences(file)) {
      failures.push(`${relative(SRC, file)}:${line} — ${name} is not defined`);
    }
  }
  assert.deepEqual(failures, [], `\n${failures.join('\n')}\n`);
});

test('the check itself catches an undefined reference', () => {
  // A test that can only pass is not a test. This asserts the walker actually
  // reports the mistake it exists to report.
  const ast = parse('export const A = () => notDefinedAnywhere(1);', { sourceType: 'module' });
  const found = [];
  traverse(ast, {
    ReferencedIdentifier(path) {
      if (!path.scope.hasBinding(path.node.name, true) && !GLOBALS.has(path.node.name)) {
        found.push(path.node.name);
      }
    },
  });
  assert.deepEqual(found, ['notDefinedAnywhere']);
});
