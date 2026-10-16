/**
 * Webview-only theme. Persisted in localStorage (the Tauri webview keeps it
 * per app data dir); the daemon is never told.
 *
 * Two copies of the settings: `applied` is what the app wears and what is
 * saved; `draft` is what Settings › Theme edits and the Live preview draws.
 * `apply()` promotes the draft. `cssVars()` is the one place a theme becomes
 * CSS variables, so the preview and the app can never disagree.
 */
export type Corners = 'cut' | 'square' | 'round';

export type Glow = 'off' | 'soft' | 'neon';

/** a look: five colours and three finishes */
export interface ThemeSpec {
  name: string;
  /** the preset it started from (id) */
  basedOn: string;
  primary: string; // the one accent (buttons, selection, the ember tick)
  accent: string; // the cross-source link colour
  bg: string; // the canvas
  surface: string; // plates
  corners: Corners;
  glow: Glow;
  /** scanline strength on plates, 0..1 */
  scanlines: number;
}

/** how the window sits on the desktop */
export interface WindowSpec {
  /** the desktop shows through (a transparent Tauri window) */
  transparent: boolean;
  /** canvas + plate opacity while transparent, 0.3..1 */
  opacity: number;
  /** frost what is behind the window (an OS effect; desktop only) */
  blur: boolean;
  /** plate blur in px */
  blurPx: number;
}

export interface ThemeSettings {
  theme: ThemeSpec;
  window: WindowSpec;
  gridAlpha: number; // 0..0.15
}

export interface Preset extends ThemeSpec {
  id: string;
  tagline: string;
  builtIn: boolean;
}

const KEY = 'curio.theme.v3'; // v2 stored bg + plate knobs only; v1 the brighter first-pass palette
const KEY_V2 = 'curio.theme.v2';
const KEY_PRESETS = 'curio.theme.presets';

const preset = (
  id: string,
  name: string,
  tagline: string,
  primary: string,
  accent: string,
  bg: string,
  surface: string,
): Preset => ({
  id,
  name,
  tagline,
  primary,
  accent,
  bg,
  surface,
  corners: 'square',
  glow: 'soft',
  scanlines: 0.3,
  basedOn: id,
  builtIn: true,
});

/** the first is the board's default: the palette styles.css ships with */
export const BUILT_IN: readonly Preset[] = [
  preset('nightglass', 'Nightglass', 'magenta · cyan', '#e279de', '#5be3f0', '#080b16', '#11151f'),
  preset('bloodline', 'Bloodline', 'signal red · amber', '#ff4d5a', '#ffb02e', '#140708', '#1f0e10'),
  preset('phosphor', 'Phosphor', 'terminal green · lime', '#4ade80', '#d9f99d', '#061009', '#0d1a11'),
  preset('hanami', 'Hanami', 'blossom · lilac', '#f9a8d4', '#c4b5fd', '#140a12', '#1d1119'),
  preset('graphite', 'Graphite', 'mono · neutral', '#d4d4d8', '#a1a1aa', '#0b0b0d', '#151517'),
];

const DEFAULT_WINDOW: WindowSpec = { transparent: false, opacity: 0.85, blur: false, blurPx: 12 };

function spec(p: Preset): ThemeSpec {
  const { id: _id, tagline: _t, builtIn: _b, ...s } = p;
  return { ...s };
}

export function defaultSettings(): ThemeSettings {
  return { theme: spec(BUILT_IN[0]!), window: { ...DEFAULT_WINDOW }, gridAlpha: 0.035 };
}

const HEX = /^#[0-9a-f]{6}$/i;

/** luminance of a hex colour, 0..255 */
function luma(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  return 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255);
}

export function isLightColor(hex: string): boolean {
  return HEX.test(hex) && luma(hex) > 140;
}

const GLOWS: Record<Glow, (c: string) => string> = {
  off: () => 'none',
  soft: (c) =>
    `0 0 0 3px color-mix(in oklch, ${c} 22%, transparent), 0 0 14px color-mix(in oklch, ${c} 55%, transparent)`,
  neon: (c) =>
    `0 0 0 3px color-mix(in oklch, ${c} 35%, transparent), 0 0 24px color-mix(in oklch, ${c} 85%, transparent)`,
};

/**
 * A theme as the CSS variables styles.css reads. Neutrals come from the
 * canvas and the surface so one picker re-hues the ladder; text flips for
 * a light canvas ("paper"-like themes).
 */
export function cssVars(s: ThemeSettings): Record<string, string> {
  const { theme: t, window: w } = s;
  const light = isLightColor(t.bg);
  const ink = light ? 'black' : 'white';
  const alpha = w.transparent ? w.opacity : 1;
  return {
    '--color-bg': t.bg,
    '--color-rail': `color-mix(in oklch, ${t.bg} 80%, ${light ? 'white' : 'black'})`,
    '--color-surf': t.surface,
    '--color-surf2': `color-mix(in oklch, ${t.surface} 94%, ${ink})`,
    '--color-line-soft': `color-mix(in oklch, ${t.surface} 88%, ${ink})`,
    '--color-line': `color-mix(in oklch, ${t.surface} 80%, ${ink})`,
    '--color-tx': light ? '#0b0d14' : '#e5ebfb',
    '--color-mut': light ? '#4a5060' : '#9aa3b5',
    '--color-dim': light ? '#7b8190' : '#5f6572',
    '--color-ember': t.primary,
    '--color-ember-ink': isLightColor(t.primary) ? '#1a0c1a' : '#ffffff',
    '--color-cyan': t.accent,
    '--glow': GLOWS[t.glow](t.primary),
    '--scan-alpha': String(Math.round(t.scanlines * 0.08 * 1000) / 1000),
    '--window-alpha': String(alpha),
    '--plate-opacity': String(alpha),
    '--plate-blur': `${w.transparent ? w.blurPx : 0}px`,
    '--grid-alpha': String(s.gridAlpha),
  };
}

/** the html classes a theme turns on */
export function cssClasses(t: ThemeSpec): Record<string, boolean> {
  return {
    'corners-cut': t.corners === 'cut',
    'corners-round': t.corners === 'round',
    'no-scan': t.scanlines <= 0,
  };
}

function clone(s: ThemeSettings): ThemeSettings {
  return { theme: { ...s.theme }, window: { ...s.window }, gridAlpha: s.gridAlpha };
}

/** a value from storage or a paste: only the known keys, each type-checked */
export function coerceSpec(raw: unknown, base: ThemeSpec): ThemeSpec {
  const r = (raw ?? {}) as Record<string, unknown>;

  const hex = (k: 'primary' | 'accent' | 'bg' | 'surface') => {
    const v = r[k];
    return typeof v === 'string' && HEX.test(v) ? v.toLowerCase() : base[k];
  };

  const corners = ['cut', 'square', 'round'].includes(String(r.corners))
    ? (r.corners as Corners)
    : base.corners;

  const glow = ['off', 'soft', 'neon'].includes(String(r.glow)) ? (r.glow as Glow) : base.glow;
  const scan = typeof r.scanlines === 'number' ? Math.min(1, Math.max(0, r.scanlines)) : base.scanlines;
  return {
    name: typeof r.name === 'string' ? r.name.slice(0, 40) : base.name,
    basedOn: typeof r.basedOn === 'string' ? r.basedOn : base.basedOn,
    primary: hex('primary'),
    accent: hex('accent'),
    bg: hex('bg'),
    surface: hex('surface'),
    corners,
    glow,
    scanlines: scan,
  };
}

function coerceWindow(raw: unknown, base: WindowSpec): WindowSpec {
  const r = (raw ?? {}) as Record<string, unknown>;

  const num = (k: keyof WindowSpec, lo: number, hi: number) =>
    typeof r[k] === 'number' ? Math.min(hi, Math.max(lo, r[k])) : (base[k] as number);

  return {
    transparent: typeof r.transparent === 'boolean' ? r.transparent : base.transparent,
    opacity: num('opacity', 0.3, 1),
    blur: typeof r.blur === 'boolean' ? r.blur : base.blur,
    blurPx: num('blurPx', 0, 24),
  };
}

function load(): ThemeSettings {
  const d = defaultSettings();
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const r = JSON.parse(raw) as Partial<ThemeSettings>;
      return {
        theme: coerceSpec(r.theme, d.theme),
        window: coerceWindow(r.window, d.window),
        gridAlpha: typeof r.gridAlpha === 'number' ? r.gridAlpha : d.gridAlpha,
      };
    }
    // v2: a canvas colour and the plate knobs -- carried over as a custom theme
    const old = localStorage.getItem(KEY_V2);
    if (old) {
      const r = JSON.parse(old) as Record<string, unknown>;
      const bg = typeof r.bg === 'string' && HEX.test(r.bg) ? r.bg : d.theme.bg;
      const custom = bg.toLowerCase() !== d.theme.bg;
      return {
        theme: {
          ...d.theme,
          name: custom ? 'Custom' : d.theme.name,
          bg,
          surface: custom ? `#${bg.slice(1)}` : d.theme.surface,
          corners: r.corners === 'cut' ? 'cut' : 'square',
          scanlines: r.scanlines === false ? 0 : d.theme.scanlines,
        },
        window: {
          ...d.window,
          transparent: typeof r.plateOpacity === 'number' && r.plateOpacity < 1,
          opacity: typeof r.plateOpacity === 'number' ? Math.max(0.3, r.plateOpacity) : d.window.opacity,
          blurPx: typeof r.plateBlur === 'number' ? r.plateBlur : d.window.blurPx,
        },
        gridAlpha: typeof r.gridAlpha === 'number' ? r.gridAlpha : d.gridAlpha,
      };
    }
  } catch {
    /* private mode / blocked storage / corrupt value: defaults */
  }
  return d;
}

function loadPresets(): Preset[] {
  try {
    const raw = localStorage.getItem(KEY_PRESETS);
    if (!raw) return [];
    const list = JSON.parse(raw);
    if (!Array.isArray(list)) return [];
    return list.map((p, i) => {
      const s = coerceSpec(p, spec(BUILT_IN[0]!));
      return { ...s, id: typeof p?.id === 'string' ? p.id : `user-${i}`, tagline: '', builtIn: false };
    });
  } catch {
    return [];
  }
}

export const useTheme = defineStore('theme', {
  state: () => {
    const applied = load();
    return { applied, draft: clone(applied), userPresets: loadPresets() };
  },
  getters: {
    presets: (s): Preset[] => [...BUILT_IN, ...s.userPresets],
    /** the draft differs from what the app wears */
    dirty: (s) => JSON.stringify(s.draft) !== JSON.stringify(s.applied),
    /** the draft's own CSS variables, for the Live preview */
    draftVars: (s) => cssVars(s.draft),
    draftClasses: (s) => cssClasses(s.draft.theme),
    /** the preset the draft is based on, when it still exists */
    basePreset(): Preset | null {
      return this.presets.find((p) => p.id === this.draft.theme.basedOn) ?? null;
    },
    /** a light canvas (text flips dark) -- the app's, not the draft's */
    isLight: (s) => isLightColor(s.applied.theme.bg),
  },
  actions: {
    /** write the applied settings onto <html> (and the window, on desktop) */
    apply() {
      const el = document.documentElement;
      for (const [k, v] of Object.entries(cssVars(this.applied))) el.style.setProperty(k, v);
      for (const [k, on] of Object.entries(cssClasses(this.applied.theme))) el.classList.toggle(k, on);
      try {
        localStorage.setItem(KEY, JSON.stringify(this.applied));
      } catch {
        /* best effort */
      }
      void this.applyWindow();
    },
    /** the OS side of transparency: a blur behind a see-through window */
    async applyWindow() {
      if (!('__TAURI_INTERNALS__' in window)) return;
      try {
        const { getCurrentWindow } = await import('@tauri-apps/api/window');
        const w = getCurrentWindow();
        const { transparent, blur } = this.applied.window;
        if (transparent && blur) {
          // hudWindow is macOS vibrancy; acrylic is Windows 10+; Linux has no effect
          await w.setEffects({ effects: ['hudWindow', 'acrylic'] as never });
        } else {
          await w.clearEffects();
        }
      } catch {
        /* browser build, or a platform without effects */
      }
    },
    /** promote the draft */
    commit() {
      this.applied = clone(this.draft);
      this.apply();
    },
    /** drop the draft */
    revert() {
      this.draft = clone(this.applied);
    },
    /** the board defaults, drafted and applied */
    reset() {
      this.draft = defaultSettings();
      this.commit();
    },
    /** start the draft from a preset (keeps the window settings) */
    pick(id: string) {
      const p = this.presets.find((x) => x.id === id);
      if (!p) return;
      this.draft.theme = { ...spec(p), basedOn: p.id, name: p.builtIn ? p.name : p.name };
    },
    /** the draft's theme as a user preset; returns its id */
    saveAsPreset(): string {
      const name = this.draft.theme.name.trim() || `Custom ${this.userPresets.length + 1}`;
      const id = `user-${Date.now().toString(36)}`;
      this.userPresets.push({ ...this.draft.theme, name, id, tagline: '', builtIn: false });
      this.draft.theme.name = name;
      this.draft.theme.basedOn = id;
      this.persistPresets();
      return id;
    },
    removePreset(id: string) {
      this.userPresets = this.userPresets.filter((p) => p.id !== id);
      this.persistPresets();
    },
    persistPresets() {
      try {
        localStorage.setItem(KEY_PRESETS, JSON.stringify(this.userPresets));
      } catch {
        /* best effort */
      }
    },
    /** the draft's theme as JSON (what Export copies) */
    exportJson(): string {
      return JSON.stringify(this.draft.theme, null, 2);
    },
    /** a pasted theme into the draft; false when it is not a theme */
    importJson(text: string): boolean {
      try {
        const raw = JSON.parse(text);
        if (!raw || typeof raw !== 'object') return false;
        this.draft.theme = coerceSpec(raw, this.draft.theme);
        return true;
      } catch {
        return false;
      }
    },
  },
});
