/**
 * The webview's own state (theme, presets, language, formats, notification
 * mode, character defaults, gallery chips): every `curio.*` key in
 * localStorage. A backup carries it as one opaque object the daemon never
 * reads, and an import that takes the bundle's settings writes it back.
 * Everything that hydrates from localStorage does so at store creation, so
 * the caller reloads the window after `applyUiState`.
 */
const PREFIX = 'curio.';

export function collectUiState(): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith(PREFIX)) continue;
      const raw = localStorage.getItem(key);
      if (raw === null) continue;
      try {
        out[key] = JSON.parse(raw);
      } catch {
        out[key] = raw; // a bare string such as the locale code
      }
    }
  } catch {
    /* private mode / blocked storage: nothing to carry */
  }
  return out;
}

/** Writes the keys back; returns how many landed. Unknown keys are kept as data. */
export function applyUiState(state: Record<string, unknown>): number {
  let n = 0;
  for (const [key, value] of Object.entries(state)) {
    if (!key.startsWith(PREFIX)) continue;
    try {
      localStorage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value));
      n++;
    } catch {
      /* storage blocked: the daemon-side import still happened */
    }
  }
  return n;
}
