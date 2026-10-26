/**
 * Localisation. One folder per locale, one JSON file per page/component
 * (src/locales/<locale>/<namespace>.json → t('<namespace>.key')). English is
 * complete and the fallback; other locales may be partial and fill in over
 * time. Missing keys fall back to English silently in production and warn in
 * dev, so a half-translated locale is usable, never broken.
 *
 * Adding a string: put it in src/locales/en/<page>.json first, then use
 * t('<page>.key') / $t(...) - never a literal in a template.
 */
import { createI18n } from 'vue-i18n';

// `native` is how the language names itself; `label` is its English name.
// `ready` flips on when src/locales/<code>/ exists with real coverage.
export const LOCALES = [
  { code: 'en', native: 'English', label: 'English (US)', ready: true },
  { code: 'ja', native: '日本語', label: 'Japanese', ready: true },
  { code: 'id', native: 'Bahasa Indonesia', label: 'Indonesian', ready: false },
  { code: 'zh', native: '简体中文', label: 'Simplified Chinese', ready: false },
  { code: 'fil', native: 'Filipino', label: 'Filipino', ready: false },
] as const;

export type LocaleCode = (typeof LOCALES)[number]['code'];

const KEY = 'curio.locale'; // a code, or 'system' = follow the OS/browser language

// src/locales/en/settings.json → messages.en.settings. vue-i18n's message
// tree type is recursive and JSON modules are `any`-shaped by nature.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Dict = Record<string, any>;

const files = import.meta.glob<{ default: Dict }>('./locales/*/*.json', { eager: true });
const messages: Record<string, Dict> = {};

for (const [path, mod] of Object.entries(files)) {
  const m = /\.\/locales\/([\w-]+)\/([\w-]+)\.json$/.exec(path);
  if (!m) continue;
  const [, locale, ns] = m;
  (messages[locale!] ??= {})[ns!] = mod.default;
}

/** The OS/browser language, mapped onto a locale we ship (ready or not). */
export function systemLocale(): LocaleCode {
  const nav = (navigator.language || 'en').toLowerCase();
  return LOCALES.find((l) => nav.startsWith(l.code))?.code ?? 'en';
}

/** Persisted choice: a locale code, or 'system' (the default). */
export function savedChoice(): LocaleCode | 'system' {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === 'system') return 'system';
    if (saved && LOCALES.some((l) => l.code === saved)) return saved as LocaleCode;
  } catch {
    /* no storage */
  }
  return 'system';
}

function resolve(choice: LocaleCode | 'system'): LocaleCode {
  const want = choice === 'system' ? systemLocale() : choice;
  return LOCALES.find((l) => l.code === want)?.ready ? want : 'en';
}

function initial(): LocaleCode {
  return resolve(savedChoice());
}

export const i18n = createI18n({
  legacy: false,
  locale: initial(),
  fallbackLocale: 'en',
  messages,
  missingWarn: import.meta.env.DEV,
  fallbackWarn: false,
});

export function setLocale(choice: LocaleCode | 'system') {
  const code = resolve(choice);
  i18n.global.locale.value = code;
  document.documentElement.lang = code;

  try {
    localStorage.setItem(KEY, choice);
  } catch {
    /* best effort */
  }
}

/**
 * Translation coverage per locale, counted from the bundled message files:
 * how many English keys have a counterpart. Shown in Settings › Language so
 * a half-done language is visibly half-done rather than silently English.
 */
export interface Coverage {
  code: LocaleCode;
  native: string;
  label: string;
  ready: boolean;
  total: number;
  translated: number;
  pct: number;
  pending: number;
}

function leaves(o: Dict, pre = ''): string[] {
  return Object.entries(o).flatMap(([k, v]) =>
    v && typeof v === 'object' ? leaves(v as Dict, `${pre}${k}.`) : [`${pre}${k}`],
  );
}

export function coverage(): Coverage[] {
  const enKeys = leaves(messages.en ?? {});
  const total = enKeys.length;

  return LOCALES.map((l) => {
    const have = new Set(leaves(messages[l.code] ?? {}));
    const translated = l.code === 'en' ? total : enKeys.filter((k) => have.has(k)).length;
    return {
      code: l.code,
      native: l.native,
      label: l.label,
      ready: l.ready,
      total,
      translated,
      pct: total ? Math.round((100 * translated) / total) : 0,
      pending: total - translated,
    };
  });
}

document.documentElement.lang = i18n.global.locale.value;
