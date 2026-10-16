/**
 * The theme store is the one piece of state that never reaches the daemon:
 * it lives in localStorage and is expressed as CSS variables + classes on
 * <html>. These tests cover that contract: draft vs applied, presets,
 * import/export, and the migration from the v2 key.
 */
import { BUILT_IN, coerceSpec, cssClasses, cssVars, defaultSettings } from '@/stores/theme';

const KEY = 'curio.theme.v3';
const root = () => document.documentElement;

describe('useTheme', () => {
  it('starts from the Nightglass defaults, draft equal to applied', () => {
    const theme = useTheme();

    expect(theme.applied.theme.basedOn).toBe('nightglass');
    expect(theme.applied.theme.primary).toBe('#e279de');
    expect(theme.applied.window.transparent).toBe(false);
    expect(theme.dirty).toBe(false);

    expect(theme.presets.map((p) => p.id)).toEqual([
      'nightglass',
      'bloodline',
      'phosphor',
      'hanami',
      'graphite',
    ]);
  });

  it('hydrates from localStorage, filling gaps and refusing bad values', () => {
    localStorage.setItem(
      KEY,
      JSON.stringify({
        theme: { primary: '#ff4d5a', corners: 'round', glow: 'loud', bg: 'red' },
        window: { opacity: 2 },
      }),
    );

    const theme = useTheme();

    expect(theme.applied.theme.primary).toBe('#ff4d5a');
    expect(theme.applied.theme.corners).toBe('round');
    expect(theme.applied.theme.glow).toBe('soft'); // unknown → default
    expect(theme.applied.theme.bg).toBe('#080b16'); // not a hex → default
    expect(theme.applied.window.opacity).toBe(1); // clamped
  });

  it('migrates the v2 key: canvas colour, cut corners, plate opacity', () => {
    localStorage.setItem(
      'curio.theme.v2',
      JSON.stringify({ bg: '#12060f', corners: 'cut', plateOpacity: 0.7 }),
    );

    const theme = useTheme();

    expect(theme.applied.theme.bg).toBe('#12060f');
    expect(theme.applied.theme.name).toBe('Custom');
    expect(theme.applied.theme.corners).toBe('cut');
    expect(theme.applied.window).toMatchObject({ transparent: true, opacity: 0.7 });
  });

  it('ignores a corrupt localStorage value', () => {
    localStorage.setItem(KEY, '{not json');

    expect(useTheme().applied.theme.bg).toBe('#080b16');
  });

  it('edits stay in the draft until commit(); revert() drops them', () => {
    const theme = useTheme();
    theme.draft.theme.primary = '#4ade80';

    expect(theme.dirty).toBe(true);
    expect(root().style.getPropertyValue('--color-ember')).not.toBe('#4ade80');
    theme.revert();
    expect(theme.dirty).toBe(false);

    theme.draft.theme.primary = '#4ade80';
    theme.commit();
    expect(root().style.getPropertyValue('--color-ember')).toBe('#4ade80');
    expect(JSON.parse(localStorage.getItem(KEY)!).theme.primary).toBe('#4ade80');
  });

  it('apply() writes the runtime CSS variables and toggles the html classes', () => {
    const theme = useTheme();
    theme.draft.theme = { ...theme.draft.theme, bg: '#12060f', corners: 'cut', scanlines: 0, glow: 'off' };
    theme.draft.window = { transparent: true, opacity: 0.68, blur: true, blurPx: 12 };
    theme.commit();

    const st = root().style;
    expect(st.getPropertyValue('--color-bg')).toBe('#12060f');
    expect(st.getPropertyValue('--color-tx')).toBe('#e5ebfb');
    expect(st.getPropertyValue('--window-alpha')).toBe('0.68');
    expect(st.getPropertyValue('--plate-blur')).toBe('12px');
    expect(st.getPropertyValue('--glow')).toBe('none');
    expect(root().classList.contains('corners-cut')).toBe(true);
    expect(root().classList.contains('no-scan')).toBe(true);
  });

  it('a light canvas flips the text dark; a light primary gets dark ink', () => {
    const s = defaultSettings();
    s.theme.bg = '#e5ebfb';
    s.theme.primary = '#d9f99d';
    const v = cssVars(s);

    expect(v['--color-tx']).toBe('#0b0d14');
    expect(v['--color-ember-ink']).toBe('#1a0c1a');

    expect(cssClasses({ ...s.theme, corners: 'round' })).toMatchObject({
      'corners-round': true,
      'corners-cut': false,
    });
  });

  it('pick() drafts a preset; reset() drafts and applies the defaults', () => {
    const theme = useTheme();
    theme.pick('phosphor');

    expect(theme.draft.theme).toMatchObject({ basedOn: 'phosphor', primary: '#4ade80', name: 'Phosphor' });
    expect(theme.applied.theme.basedOn).toBe('nightglass');
    theme.commit();
    theme.reset();
    expect(theme.applied.theme.basedOn).toBe('nightglass');
    expect(theme.dirty).toBe(false);
  });

  it('saves the draft as a user preset, persisted and removable', () => {
    const theme = useTheme();
    theme.draft.theme.name = 'Midnight ember';
    theme.draft.theme.primary = '#ff4d5a';
    const id = theme.saveAsPreset();

    expect(theme.presets.at(-1)).toMatchObject({
      id,
      name: 'Midnight ember',
      primary: '#ff4d5a',
      builtIn: false,
    });

    expect(theme.draft.theme.basedOn).toBe(id);
    expect(JSON.parse(localStorage.getItem('curio.theme.presets')!)).toHaveLength(1);
    theme.removePreset(id);
    expect(theme.presets).toHaveLength(BUILT_IN.length);
  });

  it('exports the draft theme as JSON and imports only a valid theme', () => {
    const theme = useTheme();
    theme.draft.theme.accent = '#ffb02e';
    const json = theme.exportJson();

    expect(JSON.parse(json).accent).toBe('#ffb02e');
    expect(theme.importJson('nope')).toBe(false);
    expect(theme.importJson(JSON.stringify({ primary: '#4ade80', glow: 'neon' }))).toBe(true);
    expect(theme.draft.theme).toMatchObject({ primary: '#4ade80', glow: 'neon', accent: '#ffb02e' });
    expect(coerceSpec({ scanlines: 7 }, theme.draft.theme).scanlines).toBe(1);
  });
});
