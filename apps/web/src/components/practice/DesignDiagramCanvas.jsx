import { useCallback, useEffect, useRef, useState } from 'react';
import { Excalidraw, exportToBlob } from '@excalidraw/excalidraw';
import '@excalidraw/excalidraw/index.css';

// Converts a Blob to a BARE base64 string (no `data:image/png;base64,`
// prefix) — matches every other image-input call site in the backend (see
// `services.llm_client.ImageContent` / `_sniff_media_type`, which expect the
// raw payload and sniff the media type themselves from the decoded bytes).
// No blob->base64 helper already existed anywhere in this codebase (the only
// existing base64 handling, in the Mock Interview pages, goes the other way
// — base64 audio -> a playable `data:` URL) — `FileReader.readAsDataURL` is
// the standard browser-side way to do this without pulling in a dependency.
function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = typeof reader.result === 'string' ? reader.result : '';
      const commaIdx = result.indexOf(',');
      resolve(commaIdx >= 0 ? result.slice(commaIdx + 1) : result);
    };
    reader.onerror = () => reject(reader.error || new Error('Failed to read the exported diagram image'));
    reader.readAsDataURL(blob);
  });
}

// Renders whatever scene `onChange` below last handed back to a real PNG and
// base64-encodes it for the backend — the image IS the diagram now; there's
// no structured node/edge graph to serialize instead (the old
// `serialize_diagram_for_grading` was built for React Flow's node/edge JSON
// and no longer applies). Also hands back the raw Excalidraw element list so
// the backend can derive an OPTIONAL best-effort text hint (see
// `practice_ai_service.summarize_excalidraw_elements`) — the image stays the
// primary, authoritative signal there regardless.
//
// Exported (not just used internally) so `Practice.jsx` can call it at
// submit time with whatever scene state it last captured via `onChange`,
// without needing to import `@excalidraw/excalidraw` itself.
export async function exportDiagramForSubmit(scene) {
  const elements = scene?.elements || [];
  // An empty/never-touched canvas still exports a valid (blank) PNG rather
  // than throwing — the grader already treats a missing/blank diagram as
  // "score the diagram-tagged criteria low", it doesn't need this call to
  // reject instead.
  const blob = await exportToBlob({
    elements,
    appState: scene?.appState || {},
    files: scene?.files || {},
    mimeType: 'image/png',
    exportPadding: 16,
  });
  const image_base64 = await blobToBase64(blob);
  return { image_base64, elements };
}

// Mirrors ThemeProvider.jsx's own dark-mode detection (the `dark` class it
// toggles on <html>) via a MutationObserver, rather than reaching into the
// Redux store directly for `state.ui.theme` — keeps this component
// droppable anywhere without it needing to know the app's store shape, same
// as before this rewrite (the old version needed no app state at all either).
function useIsDarkMode() {
  const [isDark, setIsDark] = useState(
    () => typeof document !== 'undefined' && document.documentElement.classList.contains('dark')
  );
  useEffect(() => {
    const root = document.documentElement;
    const sync = () => setIsDark(root.classList.contains('dark'));
    const observer = new MutationObserver(sync);
    observer.observe(root, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);
  return isDark;
}

export default function DesignDiagramCanvas({ initialDiagram, onChange }) {
  const isDark = useIsDarkMode();

  // Excalidraw only reads `initialData` on mount — it explicitly does NOT
  // react to subsequent prop changes. Captured once in a ref so a parent
  // re-render (e.g. `onChange` firing and handing back a new `initialDiagram`
  // object identity) never resets the live scene out from under the user.
  // `Practice.jsx` forces a genuine reset (switching to a different problem)
  // by remounting this component entirely via `key={problem?.id}`, rather
  // than relying on this prop to change mid-session.
  const initialDataRef = useRef({ elements: initialDiagram?.elements || [] });

  const handleChange = useCallback(
    (elements, appState, files) => onChange?.({ elements, appState, files }),
    [onChange]
  );

  return (
    <div className="space-y-2">
      <span className="text-sm font-medium">Architecture diagram</span>
      <p className="text-xs text-muted-foreground">
        Draw your architecture with the toolbar — rectangles, arrows, text labels, and a
        freehand pen are all available, just like a real whiteboard.
      </p>
      <div
        className="h-[480px] rounded-lg border border-border overflow-hidden"
        data-testid="diagram-canvas"
      >
        <Excalidraw
          initialData={initialDataRef.current}
          onChange={handleChange}
          theme={isDark ? 'dark' : 'light'}
        />
      </div>
    </div>
  );
}
