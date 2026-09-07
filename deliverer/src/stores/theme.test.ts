/**
 * The theme store is the one piece of state that never reaches the daemon:
 * it lives in localStorage and is expressed as CSS variables + classes on
 * <html>. These tests cover that contract, not the colour maths.
 */
const KEY = 'curio.theme.v2';
const root = () => document.documentElement;

describe('useTheme', () => {
  it('starts from the board defaults', () => {
    const theme = useTheme();

    expect(theme.bg).toBe('#080b16');
    expect(theme.corners).toBe('square');
    expect(theme.scanlines).toBe(true);
    expect(theme.plateOpacity).toBe(1);
    expect(theme.presets.map((p) => p.name)).toContain('paper');
  });

  it('hydrates from localStorage and fills gaps with defaults', () => {
    localStorage.setItem(KEY, JSON.stringify({ bg: '#12060f', corners: 'cut' }));
    const theme = useTheme();

    expect(theme.bg).toBe('#12060f');
    expect(theme.corners).toBe('cut');
    expect(theme.scanlines).toBe(true); // not in storage → default
  });

  it('ignores a corrupt localStorage value', () => {
    localStorage.setItem(KEY, '{not json');

    expect(useTheme().bg).toBe('#080b16');
  });

  it('isLight flips for the paper preset only', () => {
    const theme = useTheme();

    expect(theme.isLight).toBe(false);
    theme.bg = '#e5ebfb';
    expect(theme.isLight).toBe(true);
    theme.bg = '#04040a';
    expect(theme.isLight).toBe(false);
  });

  it('apply() writes the runtime CSS variables and toggles the html classes', () => {
    const theme = useTheme();
    theme.bg = '#12060f';
    theme.corners = 'cut';
    theme.scanlines = false;
    theme.plateBlur = 4;
    theme.apply();

    const st = root().style;

    expect(st.getPropertyValue('--color-bg')).toBe('#12060f');
    expect(st.getPropertyValue('--color-surf')).toContain('#12060f');
    expect(st.getPropertyValue('--color-tx')).toBe('#e5ebfb');
    expect(st.getPropertyValue('--plate-blur')).toBe('4px');
    expect(root().classList.contains('corners-cut')).toBe(true);
    expect(root().classList.contains('no-scan')).toBe(true);

    theme.corners = 'square';
    theme.scanlines = true;
    theme.apply();

    expect(root().classList.contains('corners-cut')).toBe(false);
    expect(root().classList.contains('no-scan')).toBe(false);
  });

  it('apply() flips the ink for a light canvas', () => {
    const theme = useTheme();
    theme.bg = '#e5ebfb';
    theme.apply();

    expect(root().style.getPropertyValue('--color-tx')).toBe('#0b0d14');
  });

  it('apply() persists the whole state under curio.theme.v2', () => {
    const theme = useTheme();
    theme.bg = '#05110c';
    theme.gridAlpha = 0.1;
    theme.apply();

    expect(JSON.parse(localStorage.getItem(KEY)!)).toMatchObject({
      bg: '#05110c',
      gridAlpha: 0.1,
      corners: 'square',
    });
  });

  it('reset() restores the defaults and re-applies them', () => {
    const theme = useTheme();
    theme.bg = '#e5ebfb';
    theme.corners = 'cut';
    theme.apply();
    theme.reset();

    expect(theme.bg).toBe('#080b16');
    expect(theme.corners).toBe('square');
    expect(root().style.getPropertyValue('--color-bg')).toBe('#080b16');
    expect(root().classList.contains('corners-cut')).toBe(false);
    expect(JSON.parse(localStorage.getItem(KEY)!).bg).toBe('#080b16');
  });
});
