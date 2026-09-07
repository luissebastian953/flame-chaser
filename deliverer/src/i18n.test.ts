/**
 * The locale files are data, not code, so the compiler cannot catch a
 * missing namespace or a broken JSON tree. These tests do.
 */
import { i18n, setLocale, LOCALES } from '@/i18n';

// same glob shape as src/i18n.ts, narrowed to English
const enFiles = import.meta.glob('./locales/en/*.json');

describe('i18n messages', () => {
  it('loads every English namespace with at least one key', () => {
    const namespaces = Object.keys(enFiles).map((p) => /\/([\w-]+)\.json$/.exec(p)![1]!);
    const en = i18n.global.getLocaleMessage('en') as Record<string, Record<string, unknown>>;

    expect(namespaces.length).toBeGreaterThan(0);
    for (const ns of namespaces) {
      expect(en[ns], `namespace ${ns}`).toBeTypeOf('object');
      expect(Object.keys(en[ns]!).length, `namespace ${ns}`).toBeGreaterThan(0);
    }
  });

  it('resolves keys with interpolation', () => {
    expect(i18n.global.t('auth.badge.on')).toBe('Authenticated');
    expect(i18n.global.t('updates.banner.ready', { version: '0.2.0' })).toBe('0.2.0 ready');
  });

  it('falls back to the key path for a missing key instead of throwing', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const missing = 'nope.not.a.key';
    // the typed overloads of te()/t() recurse over the whole message tree; a
    // deliberately unknown key needs the plain string signature
    const g = i18n.global as unknown as { te(key: string): boolean; t(key: string): string };

    expect(g.te(missing)).toBe(false);
    expect(g.t(missing)).toBe(missing);
    warn.mockRestore();
  });

  it('only marks English as ready for now', () => {
    expect(LOCALES.find((l) => l.code === 'en')?.ready).toBe(true);
    expect(LOCALES.filter((l) => l.ready).map((l) => l.code)).toEqual(['en']);
  });
});

describe('setLocale', () => {
  it('switches the active locale, the <html lang> and persists the choice', () => {
    setLocale('en');

    expect(i18n.global.locale.value).toBe('en');
    expect(document.documentElement.lang).toBe('en');
    expect(localStorage.getItem('curio.locale')).toBe('en');
  });
});
