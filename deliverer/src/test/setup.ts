/**
 * Runs before every test file (vite.config.ts → test.setupFiles).
 *
 * Every test starts from a blank slate: a fresh Pinia (so stores rebuild
 * their state from an empty localStorage), no Tauri bridge, and no leftover
 * DOM classes or CSS variables from a previous theme test.
 */
import { createPinia, setActivePinia } from 'pinia';
import { setTauri } from './utils';

// <i18n-t> warns once per mount when the parent has no local i18n scope --
// expected here (the global scope is what we want) and only noise in a test run.
const warn = console.warn.bind(console);

console.warn = (...args: unknown[]) => {
  if (typeof args[0] === 'string' && args[0].startsWith('[intlify] Not found parent scope')) return;
  warn(...args);
};

beforeEach(() => {
  setActivePinia(createPinia());
});

afterEach(() => {
  setTauri(false);
  localStorage.clear();
  document.documentElement.removeAttribute('style');
  document.documentElement.removeAttribute('class');
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
