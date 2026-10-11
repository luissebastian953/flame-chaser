import type { Gender, GenderMode } from '@/lib/types';

/**
 * What a new character's form starts with (Settings › Characters). A
 * per-viewer convenience like the theme: localStorage, never the daemon --
 * each character stores its own settings once saved.
 */
const KEY = 'curio.character.defaults';
const GENDERS: Gender[] = ['any', 'female', 'male'];
const MODES: GenderMode[] = ['full', 'partial'];

function load(): { gender: Gender; gender_mode: GenderMode } {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Record<string, unknown> | null;
    if (v && GENDERS.includes(v.gender as Gender) && MODES.includes(v.gender_mode as GenderMode)) {
      return { gender: v.gender as Gender, gender_mode: v.gender_mode as GenderMode };
    }
  } catch {
    /* blocked storage / bad JSON: defaults */
  }

  return { gender: 'any', gender_mode: 'full' };
}

export const useCharacterDefaults = defineStore('characterDefaults', {
  state: load,
  actions: {
    set(gender: Gender, gender_mode: GenderMode) {
      this.gender = gender;
      this.gender_mode = gender_mode;
      try {
        localStorage.setItem(KEY, JSON.stringify({ gender, gender_mode }));
      } catch {
        /* best effort */
      }
    },
  },
});
