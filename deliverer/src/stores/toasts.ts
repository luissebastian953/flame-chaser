import type { Lane } from '@/lib/types';

/**
 * The "run started" toasts (bottom-right of the content area, `RunToasts`).
 * A toast holds identity only -- which character, which jobs -- and the
 * component reads the live state off the jobs store, so a toast raised as
 * "queued" turns into "crawling" with its stage word on its own. The store
 * owns the stack rules: at most three, a fourth evicts the oldest one that
 * is counting down, else the oldest error; hover on the stack pauses every
 * timer; a sticky toast (queue paused, error) has no timer at all.
 */

/** one character's run: tracks the crawl jobs the daemon planned for it */
export interface RunToast {
  kind: 'run';
  id: number;
  slug: string;
  label: string;
  sources: Lane[];
  jobIds: string[];
  retry: () => Promise<void>;
}

/** the run could not be submitted */
export interface ErrorToast {
  kind: 'error';
  id: number;
  slug: string | null;
  label: string;
  sources: Lane[];
  /** X match terms the character has (the sub-line of "no character matches") */
  terms: number;
  /** the daemon's error code, or `unreachable` when no answer came at all */
  code: string;
  message: string;
  retry: () => Promise<void>;
}

/** images went to trash (or away): Undo while it shows */
export interface DeleteToast {
  kind: 'delete';
  id: number;
  slug: string;
  label: string;
  images: number;
  bytes: number;
  forgotten: number;
  permanent: boolean;
  /** the trash batch to restore; null when the deletion was permanent */
  batchId: string | null;
  undo: () => Promise<void>;
}

export type Toast = RunToast | ErrorToast | DeleteToast;

/** a deletion toast stays ten seconds, then goes on its own */
export const DELETE_TTL = 10000;

export const TOAST_MAX = 3;

export const TOAST_TTL = 6000;

interface Countdown {
  remaining: number;
  startedAt: number;
  handle: ReturnType<typeof setTimeout> | null;
}

// timers live outside the reactive state: nothing renders them
const countdowns = new Map<number, Countdown>();
let seq = 0;

export const useToasts = defineStore('toasts', {
  state: () => ({
    items: [] as Toast[],
    /** the pointer is over the stack: every countdown is held */
    held: false,
  }),
  actions: {
    run(t: Omit<RunToast, 'kind' | 'id'>): RunToast {
      const toast: RunToast = { kind: 'run', id: ++seq, ...t };
      this.push(toast);
      return toast;
    },
    error(t: Omit<ErrorToast, 'kind' | 'id'>): ErrorToast {
      const toast: ErrorToast = { kind: 'error', id: ++seq, ...t };
      this.push(toast);
      return toast;
    },
    /** one deletion; a newer one retires the older (its Undo window is over) */
    deleted(t: Omit<DeleteToast, 'kind' | 'id'>): DeleteToast {
      for (const old of this.items) if (old.kind === 'delete') this.dismiss(old.id);
      const toast: DeleteToast = { kind: 'delete', id: ++seq, ...t };
      this.push(toast);
      return toast;
    },
    push(toast: Toast) {
      while (this.items.length >= TOAST_MAX) {
        const victim =
          this.items.find((t) => countdowns.has(t.id)) ??
          this.items.find((t) => t.kind === 'error') ??
          this.items[0];

        if (!victim) break;
        this.dismiss(victim.id);
      }
      this.items.push(toast);
    },
    dismiss(id: number) {
      this.hold(id);
      this.items = this.items.filter((t) => t.id !== id);
    },
    /** start the countdown (no-op while one is running); the hover hold applies */
    arm(id: number, ms = TOAST_TTL) {
      if (countdowns.has(id) || !this.items.some((t) => t.id === id)) return;
      const c: Countdown = { remaining: ms, startedAt: Date.now(), handle: null };
      countdowns.set(id, c);
      if (!this.held) c.handle = setTimeout(() => this.dismiss(id), ms);
    },
    /** stop the countdown: the toast stays until dismissed or re-armed */
    hold(id: number) {
      const c = countdowns.get(id);
      if (!c) return;
      if (c.handle) clearTimeout(c.handle);
      countdowns.delete(id);
    },
    armed(id: number): boolean {
      return countdowns.has(id);
    },
    pauseTimers() {
      this.held = true;
      const now = Date.now();
      for (const c of countdowns.values()) {
        if (!c.handle) continue;
        clearTimeout(c.handle);
        c.handle = null;
        c.remaining = Math.max(0, c.remaining - (now - c.startedAt));
      }
    },
    resumeTimers() {
      this.held = false;
      for (const [id, c] of countdowns) {
        if (c.handle) continue;
        c.startedAt = Date.now();
        c.handle = setTimeout(() => this.dismiss(id), c.remaining);
      }
    },
    clear() {
      for (const t of this.items) this.hold(t.id);
      this.items = [];
      this.held = false;
    },
  },
});
