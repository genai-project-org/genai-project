import {
  isBareSpecifier, esmUrl, resolveVfsPath, pickEntry, previewShell, errorShell, resolveTarget,
} from './bundleReact';

const FILES = ['src/main.jsx', 'src/App.jsx', 'src/components/Card.jsx'];
const has = (p) => FILES.includes(p);

describe('resolveTarget', () => {
  // regression: the entry arrives as "src/main.jsx" with no "./", which looks
  // exactly like a bare package specifier. Sending it to the CDN 404s.
  test('entry point resolves to the project, never the CDN', () => {
    expect(resolveTarget({ kind: 'entry-point', path: 'src/main.jsx' }, has))
      .toEqual({ namespace: 'vfs', path: 'src/main.jsx' });
    expect(isBareSpecifier('src/main.jsx')).toBe(true); // why the case is needed
  });

  test('missing entry is an error, not a fetch', () => {
    expect(resolveTarget({ kind: 'entry-point', path: 'src/nope.jsx' }, has).error).toMatch(/not in the project/);
  });

  test('bare imports go to the CDN', () => {
    expect(resolveTarget({ kind: 'import-statement', path: 'react', importer: 'src/main.jsx' }, has))
      .toEqual({ namespace: 'http', path: 'https://esm.sh/react' });
  });

  test('relative imports resolve inside the project', () => {
    expect(resolveTarget({ kind: 'import-statement', path: './App.jsx', importer: 'src/main.jsx' }, has))
      .toEqual({ namespace: 'vfs', path: 'src/App.jsx' });
  });

  test('extensionless relative import is a clear error', () => {
    const t = resolveTarget({ kind: 'import-statement', path: './App', importer: 'src/main.jsx' }, has);
    expect(t.error).toMatch(/must include the file extension/);
  });

  test('relative import inside a CDN module stays on the CDN', () => {
    const t = resolveTarget(
      { kind: 'import-statement', path: './chunk.mjs', importer: 'https://esm.sh/react@19/index.mjs', namespace: 'http' },
      has,
    );
    expect(t).toEqual({ namespace: 'http', path: 'https://esm.sh/react@19/chunk.mjs' });
  });
});

test('bare specifiers are distinguished from paths', () => {
  expect(isBareSpecifier('react')).toBe(true);
  expect(isBareSpecifier('react-dom/client')).toBe(true);
  expect(isBareSpecifier('./components/Card.jsx')).toBe(false);
  expect(isBareSpecifier('../hooks/useThing.js')).toBe(false);
  expect(isBareSpecifier('https://esm.sh/react')).toBe(false);
});

test('bare specifiers map onto the CDN with subpaths intact', () => {
  expect(esmUrl('react')).toBe('https://esm.sh/react');
  expect(esmUrl('react-dom/client')).toBe('https://esm.sh/react-dom/client');
});

test('relative imports resolve against the importer', () => {
  expect(resolveVfsPath('src/App.jsx', './components/Card.jsx')).toBe('src/components/Card.jsx');
  expect(resolveVfsPath('src/components/Card.jsx', '../App.jsx')).toBe('src/App.jsx');
  expect(resolveVfsPath('src/components/a/B.jsx', '../../hooks/use.js')).toBe('src/hooks/use.js');
  expect(resolveVfsPath('src/main.jsx', './App.jsx')).toBe('src/App.jsx');
  expect(resolveVfsPath('src/App.jsx', '/src/x.js')).toBe('src/x.js');
});

test('entry point preference order', () => {
  expect(pickEntry(['src/App.jsx', 'src/main.jsx'])).toBe('src/main.jsx');
  expect(pickEntry(['src/App.jsx', 'src/index.jsx'])).toBe('src/index.jsx');
  expect(pickEntry(['src/App.jsx'])).toBe('src/App.jsx');
  expect(pickEntry(['src/thing.jsx'])).toBe('src/thing.jsx');
  expect(() => pickEntry(['README.md'])).toThrow(/entry/i);
});

test('shells produce mountable / readable html', () => {
  expect(previewShell('console.log(1)')).toContain('<div id="root"></div>');
  expect(previewShell('console.log(1)')).toContain('console.log(1)');
  // an error message containing markup must not break out of the page
  expect(errorShell('<img onerror=x>')).not.toContain('<img');
});

// Every assertion here maps to a failure reproduced in a real sandboxed
// srcdoc iframe (opaque origin) via headless Chrome.
test('preview shell guards against the measured sandbox failures', () => {
  const html = previewShell('console.log(1)');
  // implicit form submit navigated the frame to about:srcdoc?
  expect(html).toMatch(/addEventListener\('submit'[\s\S]*preventDefault/);
  // React 19 empties the root on an uncaught error, showing nothing at all
  expect(html).toContain("addEventListener('error'");
  expect(html).toContain("addEventListener('unhandledrejection'");
  expect(html).toContain('data-preview-error');
  // storage + history throw SecurityError on an opaque origin
  expect(html).toContain('localStorage');
  expect(html).toContain('sessionStorage');
  expect(html).toContain('pushState');
  // the guard must run before the app module
  expect(html.indexOf('data-preview-error')).toBeLessThan(html.indexOf('type="module"'));
});

test('in-app hash navigation stays inside the preview', () => {
  const html = previewShell('');
  // <base target="_blank"> sent nav clicks to a blocked new tab — must not return
  expect(html).not.toContain('<base');
  // fragment clicks do not navigate in about:srcdoc, so the guard assigns the hash
  expect(html).toMatch(/location\.hash = href/);
  // ...and real links leave via a new tab rather than replacing the preview
  expect(html).toMatch(/window\.open\(a\.href, '_blank'/);
});
