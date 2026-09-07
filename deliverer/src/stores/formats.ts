import { defineStore } from 'pinia';

/**
 * How dates, numbers and sizes are written. Independent of the interface
 * language on purpose: a Japanese reader may still want ISO dates and MiB.
 * Persisted per install; `useFormats()` helpers are what pages call.
 */
const KEY = 'curio.formats.v1';

export type DateStyle = 'iso' | 'locale';

export type SizeUnit = 'binary' | 'decimal';

export interface FormatsState {
  region: string; // BCP-47 tag or 'auto' (navigator.language)
  dateStyle: DateStyle;
  hour12: boolean;
  sizeUnit: SizeUnit;
}

const DEFAULTS: FormatsState = { region: 'auto', dateStyle: 'iso', hour12: false, sizeUnit: 'binary' };

/** Regions offered in Settings (labels: settings.language.formats.regions.*); anything else works via 'auto'. */
export const REGIONS = ['auto', 'en-US', 'en-GB', 'id-ID', 'ja-JP', 'zh-CN', 'fil-PH'] as const;

function load(): FormatsState {
  try {
    return { ...DEFAULTS, ...(JSON.parse(localStorage.getItem(KEY) ?? '{}') as Partial<FormatsState>) };
  } catch {
    return { ...DEFAULTS };
  }
}

export const useFormats = defineStore('formats', {
  state: (): FormatsState => load(),
  getters: {
    tag: (s) => (s.region === 'auto' ? navigator.language || 'en-US' : s.region),
  },
  actions: {
    persist() {
      try {
        localStorage.setItem(KEY, JSON.stringify(this.$state));
      } catch {
        /* best effort */
      }
    },
    reset() {
      Object.assign(this, DEFAULTS);
      this.persist();
    },
    number(n: number): string {
      return new Intl.NumberFormat(this.tag).format(n);
    },
    date(iso: string | Date | null | undefined, withTime = false): string {
      if (!iso) return '—';
      const d = typeof iso === 'string' ? new Date(iso) : iso;
      if (Number.isNaN(d.getTime())) return '—';
      let day: string;
      if (this.dateStyle === 'iso') {
        const p = (n: number) => String(n).padStart(2, '0');
        day = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
      } else {
        day = new Intl.DateTimeFormat(this.tag, { dateStyle: 'medium' }).format(d);
      }
      if (!withTime) return day;

      const time = new Intl.DateTimeFormat(this.tag, {
        hour: '2-digit',
        minute: '2-digit',
        hour12: this.hour12,
      }).format(d);

      return `${day} ${time}`;
    },
    bytes(n: number | null | undefined): string {
      if (n == null) return '—';
      const base = this.sizeUnit === 'binary' ? 1024 : 1000;

      const units =
        this.sizeUnit === 'binary' ? ['B', 'KiB', 'MiB', 'GiB', 'TiB'] : ['B', 'kB', 'MB', 'GB', 'TB'];

      let v = n;
      let i = 0;
      while (v >= base && i < units.length - 1) {
        v /= base;
        i++;
      }
      return `${i === 0 ? v : new Intl.NumberFormat(this.tag, { maximumFractionDigits: 1 }).format(v)} ${units[i]}`;
    },
  },
});
