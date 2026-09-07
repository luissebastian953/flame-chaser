/**
 * Webview-only theme. Persisted in localStorage (the Tauri webview keeps it
 * per app data dir); the daemon is never told. `apply()` writes the runtime
 * CSS variables that styles.css reads — the palette itself is derived in CSS
 * from --color-bg so one picker re-hues every neutral.
 */
const KEY = 'curio.theme.v2'; // v1 stored the brighter first-pass palette

export interface ThemeState {
  bg: string; // hex, from <input type=color>
  plateOpacity: number; // 0.3..1
  plateBlur: number; // px
  gridAlpha: number; // 0..0.15
  scanlines: boolean;
  corners: 'square' | 'cut'; // panel silhouette
}

const DEFAULTS: ThemeState = {
  bg: '#080b16',
  plateOpacity: 1,
  plateBlur: 0,
  gridAlpha: 0.035,
  scanlines: true,
  corners: 'square',
};

const PRESETS = [
  { name: 'ice', bg: '#080b16' },
  { name: 'void', bg: '#04040a' },
  { name: 'ember', bg: '#12060f' },
  { name: 'moss', bg: '#05110c' },
  { name: 'wine', bg: '#120612' },
  { name: 'paper', bg: '#e5ebfb' },
];

function load(): ThemeState {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return { ...DEFAULTS, ...(JSON.parse(raw) as Partial<ThemeState>) };
  } catch {
    /* private mode / blocked storage: fall through to defaults */
  }
  return { ...DEFAULTS };
}

export const useTheme = defineStore('theme', {
  state: (): ThemeState => load(),
  getters: {
    presets: () => PRESETS,
    /** Perceived luminance of the picked bg; decides whether text flips dark. */
    isLight: (s) => {
      const n = parseInt(s.bg.slice(1), 16);
      const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
      return 0.2126 * r + 0.7152 * g + 0.0722 * b > 140;
    },
  },
  actions: {
    apply() {
      const r = document.documentElement.style;
      // Re-hue the neutral ladder from the picked colour; lightness steps stay fixed.
      r.setProperty('--color-bg', this.bg);
      // Ratios reproduce the board's ladder from its #080b16 canvas: plates
      // sit ~4% above the canvas, hairlines ~9%, so the UI stays deep.
      const ink = this.isLight ? 'black' : 'white';

      r.setProperty(
        '--color-rail',
        `color-mix(in oklch, ${this.bg} 80%, ${this.isLight ? 'white' : 'black'})`,
      );

      r.setProperty('--color-surf', `color-mix(in oklch, ${this.bg} 96%, ${ink})`);
      r.setProperty('--color-surf2', `color-mix(in oklch, ${this.bg} 93%, ${ink})`);
      r.setProperty('--color-line-soft', `color-mix(in oklch, ${this.bg} 90%, ${ink})`);
      r.setProperty('--color-line', `color-mix(in oklch, ${this.bg} 85%, ${ink})`);
      // text flips for a light canvas ("paper")
      r.setProperty('--color-tx', this.isLight ? '#0b0d14' : '#e5ebfb');
      r.setProperty('--color-mut', this.isLight ? '#4a5060' : '#9aa3b5');
      r.setProperty('--color-dim', this.isLight ? '#7b8190' : '#5f6572');
      r.setProperty('--plate-opacity', String(this.plateOpacity));
      r.setProperty('--plate-blur', `${this.plateBlur}px`);
      r.setProperty('--grid-alpha', String(this.gridAlpha));
      document.documentElement.classList.toggle('no-scan', !this.scanlines);
      document.documentElement.classList.toggle('corners-cut', this.corners === 'cut');
      try {
        localStorage.setItem(KEY, JSON.stringify(this.$state));
      } catch {
        /* best effort */
      }
    },
    reset() {
      Object.assign(this, DEFAULTS);
      this.apply();
    },
  },
});
