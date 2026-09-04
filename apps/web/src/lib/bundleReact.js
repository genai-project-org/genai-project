/**
 * Bundle a multi-file React project in the browser (Dynamic Builder preview).
 *
 * The generated project never hits a server: esbuild-wasm compiles JSX and
 * resolves imports against an in-memory file map, and bare specifiers are
 * rewritten to esm.sh. Output is a self-contained srcDoc string.
 *
 * ponytail: bare imports resolve through esm.sh at preview time, so an offline
 * browser or an esm.sh outage breaks the preview (never the saved files). Vendor
 * the allowlisted packages locally if that becomes a problem.
 */
const ESBUILD_VERSION = '0.25.12';
const CDN = 'https://esm.sh';

// Bare specifiers the generator is allowed to import (see REACT_GEN_SYSTEM_PROMPT).
export const ALLOWED_PACKAGES = ['react', 'react-dom', 'lucide-react', 'recharts'];

const LOADERS = {
  jsx: 'jsx', js: 'jsx', // .js may contain JSX in generated projects
  ts: 'ts', tsx: 'tsx', json: 'json', css: 'css',
};

/** True for package imports ("react", "react-dom/client") vs paths ("./x.jsx"). */
export function isBareSpecifier(spec) {
  return !spec.startsWith('.') && !spec.startsWith('/') && !/^https?:\/\//.test(spec);
}

/** Map a bare specifier onto the CDN, preserving subpaths and pinning React. */
export function esmUrl(spec) {
  // react-dom/client must resolve to the same react instance as react itself
  if (spec === 'react' || spec.startsWith('react/')) return `${CDN}/${spec}`;
  return `${CDN}/${spec}`;
}

/** Resolve a relative import against its importer, returning a project-root path. */
export function resolveVfsPath(importerPath, spec) {
  if (spec.startsWith('/')) return spec.replace(/^\/+/, '');
  const dir = importerPath.includes('/')
    ? importerPath.slice(0, importerPath.lastIndexOf('/'))
    : '';
  const parts = (dir ? `${dir}/${spec}` : spec).split('/');
  const out = [];
  for (const part of parts) {
    if (part === '.' || part === '') continue;
    if (part === '..') out.pop();
    else out.push(part);
  }
  return out.join('/');
}

/** Pick the project entry point. Throws when the project has no usable entry. */
export function pickEntry(paths) {
  for (const candidate of ['src/main.jsx', 'src/index.jsx', 'src/main.js', 'src/index.js', 'src/App.jsx']) {
    if (paths.includes(candidate)) return candidate;
  }
  const anyJsx = paths.find((p) => p.endsWith('.jsx') || p.endsWith('.js'));
  if (!anyJsx) throw new Error('No JavaScript entry file found (expected src/main.jsx).');
  return anyJsx;
}

function loaderFor(path) {
  return LOADERS[path.split('.').pop()] || 'text';
}

/**
 * The whole resolve decision, as a pure function so it can be tested.
 * `has(path)` reports membership in the project file map.
 *
 * Note the entry-point case: esbuild passes the entry as a bare-looking path
 * ("src/main.jsx" — no leading "./"), so it MUST be matched before the
 * bare-specifier branch or the entry gets sent to the CDN as a package.
 */
export function resolveTarget({ kind, path, importer = '', namespace }, has) {
  if (kind === 'entry-point') {
    if (!has(path)) return { error: `Entry file "${path}" is not in the project.` };
    return { namespace: 'vfs', path };
  }
  if (/^https?:\/\//.test(path)) return { namespace: 'http', path };
  if (isBareSpecifier(path)) return { namespace: 'http', path: esmUrl(path) };
  // a relative import inside a CDN module stays on the CDN
  if (namespace === 'http') return { namespace: 'http', path: new URL(path, importer).href };
  const resolved = resolveVfsPath(importer, path);
  if (!has(resolved)) {
    return { error: `Cannot find "${path}" (resolved to "${resolved}"). Relative imports must include the file extension.` };
  }
  return { namespace: 'vfs', path: resolved };
}

// esbuild.initialize() throws if called twice, and React strict-mode double-renders,
// so the promise is memoised at module scope.
let initPromise = null;
let esbuild = null;

async function getEsbuild() {
  if (!initPromise) {
    initPromise = (async () => {
      esbuild = await import('esbuild-wasm');
      await esbuild.initialize({
        wasmURL: `https://unpkg.com/esbuild-wasm@${ESBUILD_VERSION}/esbuild.wasm`,
        worker: true,
      });
      return esbuild;
    })().catch((e) => {
      initPromise = null; // let a later attempt retry a transient CDN failure
      throw e;
    });
  }
  return initPromise;
}

function projectPlugin(fileMap, httpCache) {
  return {
    name: 'iema-project',
    setup(build) {
      const has = (p) => p in fileMap;
      build.onResolve({ filter: /.*/ }, (args) => {
        const t = resolveTarget(args, has);
        return t.error ? { errors: [{ text: t.error }] } : { path: t.path, namespace: t.namespace };
      });

      build.onLoad({ filter: /.*/, namespace: 'vfs' }, (args) => ({
        contents: fileMap[args.path],
        loader: loaderFor(args.path),
        resolveDir: args.path.includes('/') ? args.path.slice(0, args.path.lastIndexOf('/')) : '',
      }));

      build.onLoad({ filter: /.*/, namespace: 'http' }, async (args) => {
        if (httpCache.has(args.path)) return { contents: httpCache.get(args.path), loader: 'js' };
        const res = await fetch(args.path);
        if (!res.ok) throw new Error(`Failed to fetch ${args.path} (${res.status})`);
        const contents = await res.text();
        httpCache.set(args.path, contents);
        return { contents, loader: 'js' };
      });
    },
  };
}

const httpCache = new Map();

/**
 * Runs before the app. Everything here is a workaround for something measured
 * failing inside a real sandboxed srcdoc iframe (opaque origin):
 *
 * 1. A <button> with no type="button" inside a <form> implicitly submits, which
 *    navigates the frame to "about:srcdoc?" — the app reloads and loses state,
 *    which reads as "clicking anything blanks the preview".
 * 2. Only link clicks that would LEAVE the preview are intercepted. In-app
 *    "#route" links are left alone: location.hash assignment and hashchange
 *    both work in the sandbox, so hash routing must keep working in place.
 * 3. localStorage / sessionStorage / history.pushState / document.cookie all
 *    throw SecurityError on an opaque origin. Generated apps use them freely,
 *    so they are shimmed — in-memory, per preview session, not persisted.
 * 4. React 19 unmounts the root on an uncaught render error, leaving an EMPTY
 *    container and no explanation. Showing the error beats showing nothing.
 */
export const PREVIEW_GUARD = `
(function () {
  // -- 1. implicit form submit would navigate the preview away
  document.addEventListener('submit', function (e) { e.preventDefault(); }, true);

  // -- 2. keep in-app navigation inside the preview
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey) return;
    var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!a) return;
    var href = a.getAttribute('href') || '';
    if (href === '') return;
    if (href.charAt(0) === '#') {
      // Clicking a fragment link does NOT navigate in about:srcdoc, but assigning
      // location.hash does (and fires hashchange). Do it by hand so in-app hash
      // routing works inside the preview instead of silently doing nothing.
      e.preventDefault();
      try { window.location.hash = href; } catch (_) {}
      return;
    }
    if (/^(https?:)?\\/\\//i.test(href) || /^(mailto:|tel:)/i.test(href)) {
      e.preventDefault();                                 // real link -> new tab
      try { window.open(a.href, '_blank', 'noopener'); } catch (_) {}
      return;
    }
    e.preventDefault();  // a path like "/tasks" would blank the preview
  }, true);

  // -- 3. shim the storage/history APIs the sandbox denies
  function memStorage() {
    var m = Object.create(null);
    var keys = function () { return Object.keys(m); };
    return {
      getItem: function (k) { k = String(k); return k in m ? m[k] : null; },
      setItem: function (k, v) { m[String(k)] = String(v); },
      removeItem: function (k) { delete m[String(k)]; },
      clear: function () { m = Object.create(null); },
      key: function (i) { var ks = keys(); return i < ks.length ? ks[i] : null; },
      get length() { return keys().length; }
    };
  }
  ['localStorage', 'sessionStorage'].forEach(function (name) {
    var broken = false;
    try { window[name].getItem('probe'); } catch (_) { broken = true; }
    if (!broken) return;
    try {
      Object.defineProperty(window, name, { value: memStorage(), configurable: true, writable: true });
    } catch (_) {}
  });
  ['pushState', 'replaceState'].forEach(function (m) {
    var orig = window.history[m];
    try {
      window.history[m] = function () {
        try { return orig.apply(window.history, arguments); }
        catch (_) { /* opaque origin denies it; keep the app alive */ }
      };
    } catch (_) {}
  });

  // -- 4. surface runtime errors instead of an empty page
  var shown = false;
  function show(title, msg) {
    if (shown) return;
    shown = true;
    var el = document.createElement('pre');
    el.setAttribute('data-preview-error', '1');
    el.style.cssText = 'margin:0;padding:16px;font:13px/1.6 ui-monospace,Menlo,monospace;' +
      'background:#1a1a1a;color:#ff9c9c;white-space:pre-wrap';
    el.textContent = title + '\\n\\n' + msg;
    document.body.appendChild(el);
  }
  window.addEventListener('error', function (e) {
    show('Runtime error', (e.error && e.error.stack) || e.message || String(e.error));
  });
  window.addEventListener('unhandledrejection', function (e) {
    var r = e.reason;
    show('Unhandled promise rejection', (r && (r.stack || r.message)) || String(r));
  });
})();`;

/** Wrap compiled ESM in a runnable page. Tailwind comes from CDN, as in Static Builder. */
export function previewShell(js) {
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<script src="https://cdn.tailwindcss.com"></script>
<script>${PREVIEW_GUARD}</script>
</head>
<body>
<div id="root"></div>
<script type="module">
${js}
</script>
</body>
</html>`;
}

/** Render a build failure as a readable page instead of a blank iframe. */
export function errorShell(message) {
  const safe = String(message).replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
  return `<!doctype html><html><body style="margin:0;font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;background:#1a1a1a;color:#ff9c9c;padding:16px;white-space:pre-wrap">${safe}</body></html>`;
}

/**
 * Bundle `files` ([{path, content}]) for preview.
 * Returns {ok, html, error}. A failed build still yields renderable html (an
 * error page) because compile errors are the normal state while editing — but
 * `ok` lets callers refuse to publish a broken bundle.
 */
export default async function bundleReact(files) {
  const fileMap = {};
  for (const f of files || []) {
    if (f && f.path) fileMap[f.path] = f.content || '';
  }
  try {
    const entry = pickEntry(Object.keys(fileMap));
    const build = await getEsbuild();
    const result = await build.build({
      entryPoints: [entry],
      bundle: true,
      write: false,
      format: 'esm',
      target: 'es2020',
      jsx: 'automatic',
      logLevel: 'silent',
      plugins: [projectPlugin(fileMap, httpCache)],
    });
    return { ok: true, html: previewShell(result.outputFiles[0].text) };
  } catch (e) {
    const detail = (e.errors || []).map((x) => x.text).join('\n') || e.message || String(e);
    return { ok: false, html: errorShell(`Build failed\n\n${detail}`), error: detail };
  }
}
