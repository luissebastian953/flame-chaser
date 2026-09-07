/**
 * Formats are display-only state: they must round-trip through localStorage
 * and never throw on the empty/invalid values the API hands back.
 */
export {}; // module scope: theme.test.ts also declares a KEY

const KEY = 'curio.formats.v1';

describe('useFormats', () => {
  it('starts from ISO dates, 24h, binary sizes, system region', () => {
    const fm = useFormats();

    expect(fm.$state).toEqual({ region: 'auto', dateStyle: 'iso', hour12: false, sizeUnit: 'binary' });
    expect(fm.tag).toBe(navigator.language || 'en-US');
  });

  it('hydrates from localStorage, fills gaps, and survives junk', () => {
    localStorage.setItem(KEY, JSON.stringify({ region: 'ja-JP', hour12: true }));
    const fm = useFormats();

    expect(fm.region).toBe('ja-JP');
    expect(fm.hour12).toBe(true);
    expect(fm.sizeUnit).toBe('binary');

    localStorage.setItem(KEY, '{nope');
    setActivePinia(createPinia());
    expect(useFormats().region).toBe('auto');
  });

  it('persists and resets', () => {
    const fm = useFormats();

    fm.sizeUnit = 'decimal';
    fm.persist();
    expect(JSON.parse(localStorage.getItem(KEY)!).sizeUnit).toBe('decimal');
    fm.reset();
    expect(fm.sizeUnit).toBe('binary');
    expect(JSON.parse(localStorage.getItem(KEY)!).sizeUnit).toBe('binary');
  });

  it('formats bytes in the chosen unit and never throws on null', () => {
    const fm = useFormats();
    fm.region = 'en-US';

    expect(fm.bytes(null)).toBe('—');
    expect(fm.bytes(512)).toBe('512 B');
    expect(fm.bytes(1536 * 1024 * 1024)).toBe('1.5 GiB');
    fm.sizeUnit = 'decimal';
    expect(fm.bytes(1_500_000)).toBe('1.5 MB');
  });

  it('writes ISO dates regardless of region, regional ones on request', () => {
    const fm = useFormats();
    fm.region = 'en-US';
    const d = new Date(2026, 8, 7, 15, 4);

    expect(fm.date(d)).toBe('2026-09-07');
    expect(fm.date(d, true)).toBe('2026-09-07 15:04');
    fm.hour12 = true;
    expect(fm.date(d, true)).toMatch(/^2026-09-07 0?3:04 PM$/);
    fm.dateStyle = 'locale';
    expect(fm.date(d)).toBe('Sep 7, 2026');
    expect(fm.date('not a date')).toBe('—');
    expect(fm.date(null)).toBe('—');
  });

  it('groups numbers per region', () => {
    const fm = useFormats();

    fm.region = 'en-US';
    expect(fm.number(1234567)).toBe('1,234,567');
    fm.region = 'id-ID';
    expect(fm.number(1234567)).toBe('1.234.567');
  });
});
