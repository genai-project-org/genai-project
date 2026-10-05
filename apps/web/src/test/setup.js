// Global Vitest setup, wired via vite.config.js's test.setupFiles.
//
// - @testing-library/jest-dom adds DOM-oriented matchers (toBeInTheDocument,
//   toHaveTextContent, etc.) to Vitest's `expect`.
// - jsdom (the configured `test.environment`) doesn't implement
//   window.matchMedia, ResizeObserver, or scrollIntoView — several Radix UI
//   primitives (dropdown-menu, select, tooltip, dialog, ...) and our own
//   ThemeProvider call these, so components using them throw in jsdom
//   without a stub. Polyfill the ones components in this repo actually hit.
import '@testing-library/jest-dom/vitest';

if (typeof window !== 'undefined') {
  if (!window.matchMedia) {
    window.matchMedia = (query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    });
  }

  if (!window.ResizeObserver) {
    window.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }

  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => {};
  }

  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = () => false;
  }
  if (!Element.prototype.releasePointerCapture) {
    Element.prototype.releasePointerCapture = () => {};
  }
  if (!Element.prototype.setPointerCapture) {
    Element.prototype.setPointerCapture = () => {};
  }

  // jsdom has no PointerEvent constructor at all, which Radix UI's Popper-based
  // primitives (dropdown-menu, select, tooltip, popover, ...) require for their
  // pointerdown/pointerup handling — without this, interactions on those
  // components (e.g. opening a DropdownMenu) never fire and tests hang/timeout.
  if (!window.PointerEvent) {
    class PointerEvent extends MouseEvent {
      constructor(type, props = {}) {
        super(type, props);
        this.pointerId = props.pointerId ?? 1;
        this.pointerType = props.pointerType ?? 'mouse';
        this.isPrimary = props.isPrimary ?? true;
        this.width = props.width ?? 1;
        this.height = props.height ?? 1;
      }
    }
    window.PointerEvent = PointerEvent;
  }
}
