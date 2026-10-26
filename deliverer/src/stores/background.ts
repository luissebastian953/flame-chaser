import type { PipSide } from '@/pip/protocol';

/**
 * What Curio shows while it crawls and another app is in front: a floating
 * mini window, one system notification per finished run, or nothing. Per
 * install, localStorage -- the daemon has no business knowing. The mini
 * window's placement (side, height, expanded) lives here too so it comes
 * back where it was left. `probe()` asks the shell whether a floating
 * window can exist at all (not on Linux Wayland, not in the browser) and
 * coerces a saved "mini" to notifications when it cannot.
 */
const KEY = 'curio.background.v1';

export type BackgroundMode = 'mini' | 'notify' | 'none';

export const MODES: readonly BackgroundMode[] = ['mini', 'notify', 'none'];

export interface BackgroundState {
  mode: BackgroundMode;
  /** the mini window opens with every row, not just the focused one */
  startExpanded: boolean;
  /** after the mini window is hidden with ×, the tray tooltip keeps the progress */
  trayKeepsProgress: boolean;
  side: PipSide;
  /** logical px from the top of the work area; null = bottom */
  y: number | null;
  /** the mini window's last expand state */
  expanded: boolean;
}

const DEFAULTS: BackgroundState = {
  mode: 'mini',
  startExpanded: false,
  trayKeepsProgress: true,
  side: 'right',
  y: null,
  expanded: false,
};

function load(): BackgroundState {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? '{}') as Partial<BackgroundState>;
    const out = { ...DEFAULTS, ...saved };
    if (!MODES.includes(out.mode)) out.mode = DEFAULTS.mode;
    if (out.side !== 'left' && out.side !== 'right') out.side = DEFAULTS.side;
    return out;
  } catch {
    return { ...DEFAULTS };
  }
}

export const useBackground = defineStore('background', {
  state: () => ({
    ...load(),
    /** null until probed; false in the browser and on Wayland */
    supported: null as boolean | null,
    reason: null as 'wayland' | 'browser' | null,
    /** a saved "mini" was turned into notifications on this system */
    coerced: false,
    /** × was pressed on the mini window this run; resets when the queue empties */
    dismissed: false,
  }),
  getters: {
    inTauri: () => '__TAURI_INTERNALS__' in window,
    /** the mode that actually applies here */
    effectiveMode(): BackgroundMode {
      return this.mode === 'mini' && this.supported === false ? 'notify' : this.mode;
    },
  },
  actions: {
    persist() {
      const { mode, startExpanded, trayKeepsProgress, side, y, expanded } = this;
      try {
        localStorage.setItem(
          KEY,
          JSON.stringify({ mode, startExpanded, trayKeepsProgress, side, y, expanded }),
        );
      } catch {
        /* best effort */
      }
    },
    set(patch: Partial<BackgroundState>) {
      Object.assign(this, patch);
      this.persist();
    },
    reset() {
      Object.assign(this, DEFAULTS);
      this.coerced = false;
      this.persist();
    },
    /** Ask the shell whether a floating window can exist; coerce the mode if not. */
    async probe() {
      if (!this.inTauri) {
        this.supported = false;
        this.reason = 'browser';
      } else {
        try {
          const { invoke } = await import('@tauri-apps/api/core');
          const r = await invoke<{ supported: boolean; reason: 'wayland' | null }>('pip_supported');
          this.supported = r.supported;
          this.reason = r.reason;
        } catch {
          this.supported = false;
          this.reason = null;
        }
      }
      if (!this.supported && this.mode === 'mini') {
        this.coerced = true;
        this.set({ mode: 'notify' });
      }
    },
  },
});
