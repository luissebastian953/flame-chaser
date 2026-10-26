import type { Gender, GenderMode } from '@/lib/types';

/**
 * What a new character's form starts with (Settings › Characters). A
 * per-viewer convenience like the theme: localStorage, never the daemon --
 * each character stores its own settings once saved.
 */
const KEY = 'curio.character.defaults';
const GENDERS: Gender[] = ['any', 'female', 'male'];
const MODES: GenderMode[] = ['full', 'partial'];

interface Defaults {
  gender: Gender;
  gender_mode: GenderMode;
  /** skip photos, cosplay, 3D and screenshots at ingest (coreflame/kinds.py) */
  kind_filter: boolean;
}

const FRESH: Defaults = { gender: 'any', gender_mode: 'full', kind_filter: true };

function load(): Defaults {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Record<string, unknown> | null;
    if (v && GENDERS.includes(v.gender as Gender) && MODES.includes(v.gender_mode as GenderMode)) {
      return {
        gender: v.gender as Gender,
        gender_mode: v.gender_mode as GenderMode,
        kind_filter: typeof v.kind_filter === 'boolean' ? v.kind_filter : true,
      };
    }
  } catch {
    /* blocked storage / bad JSON: defaults */
  }

  return { ...FRESH };
}

export const useCharacterDefaults = defineStore('characterDefaults', {
  state: load,
  actions: {
    set(patch: Partial<Defaults>) {
      Object.assign(this.$state, patch);
      try {
        localStorage.setItem(KEY, JSON.stringify(this.$state));
      } catch {
        /* best effort */
      }
    },
  },
});
