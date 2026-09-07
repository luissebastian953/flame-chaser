/**
 * Localisation. One folder per locale, one JSON file per page/component
 * (src/locales/<locale>/<namespace>.json → t('<namespace>.key')). English is
 * complete and the fallback; other locales may be partial and fill in over
 * time. Missing keys fall back to English silently in production and warn in
 * dev, so a half-translated locale is usable, never broken.
 *
 * Adding a string: put it in src/locales/en/<page>.json first, then use
 * t('<page>.key') / $t(...) — never a literal in a template.
 */
import { createI18n } from 'vue-i18n';

export const LOCALES = [
  { code: 'en', label: 'English', ready: true },
  { code: 'ja', label: '日本語', ready: false },
  { code: 'id', label: 'Bahasa Indonesia', ready: false },
  { code: 'zh', label: '中文', ready: false },
  { code: 'fil', label: 'Filipino', ready: false },
] as const;

export type LocaleCode = (typeof LOCALES)[number]['code'];

const KEY = 'curio.locale';

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

function initial(): LocaleCode {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved && LOCALES.some((l) => l.code === saved && l.ready)) return saved as LocaleCode;
  } catch {
    /* no storage */
  }

  const nav = (navigator.language || 'en').toLowerCase();
  const hit = LOCALES.find((l) => l.ready && nav.startsWith(l.code));

  return hit?.code ?? 'en';
}

export const i18n = createI18n({
  legacy: false,
  locale: initial(),
  fallbackLocale: 'en',
  messages,
  missingWarn: import.meta.env.DEV,
  fallbackWarn: false,
});

export function setLocale(code: LocaleCode) {
  i18n.global.locale.value = code;
  document.documentElement.lang = code;

  try {
    localStorage.setItem(KEY, code);
  } catch {
    /* best effort */
  }
}

document.documentElement.lang = i18n.global.locale.value;
