/**
 * In-app updates (desktop only). Checks once a day and on demand; downloads
 * are free and touch nothing; INSTALLING kills the sidecar and relaunches, so
 * it is gated on an idle job queue -- never over a running crawl.
 *
 * Phases: idle → checking → available → downloading → ready → (waiting) →
 * installing → relaunch. `unsupported` = not inside Tauri (browser mode).
 */
export type Phase =
  | 'idle'
  | 'checking'
  | 'available'
  | 'downloading'
  | 'ready'
  | 'waiting'
  | 'installing'
  | 'error'
  | 'unsupported';

const KEY = 'curio.updater.v1';
const DAY = 24 * 3600 * 1000;

interface Persisted {
  auto: boolean;
  lastChecked: number | null;
}

function load(): Persisted {
  try {
    return {
      auto: false,
      lastChecked: null,
      ...(JSON.parse(localStorage.getItem(KEY) ?? '{}') as Partial<Persisted>),
    };
  } catch {
    return { auto: false, lastChecked: null };
  }
}

type Update = import('@tauri-apps/plugin-updater').Update;

export const useUpdater = defineStore('updater', {
  state: () => ({
    phase: ('__TAURI_INTERNALS__' in window ? 'idle' : 'unsupported') as Phase,
    version: null as string | null,
    notes: '' as string,
    date: null as string | null,
    total: 0,
    done: 0,
    error: '' as string,
    ...load(),
    update: null as Update | null,
    timer: null as ReturnType<typeof setInterval> | null,
  }),
  getters: {
    current: () => __APP_VERSION__,
    build: () => __GIT_SHA__,
    progress: (s) => (s.total ? Math.min(100, Math.round((100 * s.done) / s.total)) : 0),
    mb: (s) => (s.total ? (s.total / 1048576).toFixed(0) : null),
    nextCheck: (s) => (s.lastChecked ? s.lastChecked + DAY : null),
    /** The failure the whole release procedure exists to prevent: shell updated, daemon didn't. */
    daemonMismatch(): boolean {
      const ep = useEndpoint();
      return !!ep.health && ep.health.version !== this.current;
    },
  },
  actions: {
    persist() {
      try {
        localStorage.setItem(KEY, JSON.stringify({ auto: this.auto, lastChecked: this.lastChecked }));
      } catch {
        /* best effort */
      }
    },
    /** Boot: check if the last check is older than a day, then daily. */
    schedule() {
      if (this.phase === 'unsupported') return;
      if (!this.lastChecked || Date.now() - this.lastChecked > DAY) void this.check();
      this.timer ??= setInterval(() => void this.check(), DAY);
    },
    async check() {
      if (this.phase === 'unsupported' || this.phase === 'downloading' || this.phase === 'installing') return;
      this.phase = 'checking';
      this.error = '';
      try {
        const { check } = await import('@tauri-apps/plugin-updater');
        const u = await check();
        this.lastChecked = Date.now();
        this.persist();
        if (!u) {
          this.phase = 'idle';
          this.update = null;
          this.version = null;
          return;
        }
        this.update = u;
        this.version = u.version;
        this.notes = u.body ?? '';
        this.date = u.date ?? null;
        this.phase = 'available';
        if (this.auto) await this.download();
      } catch (e) {
        // an unconfigured pubkey / endpoint in a dev build lands here; not fatal
        this.error = e instanceof Error ? e.message : String(e);
        this.phase = 'error';
      }
    },
    async download() {
      if (!this.update || this.phase === 'downloading') return;
      this.phase = 'downloading';
      this.done = 0;
      this.total = 0;
      try {
        await this.update.download((ev) => {
          if (ev.event === 'Started') this.total = ev.data.contentLength ?? 0;
          else if (ev.event === 'Progress') this.done += ev.data.chunkLength;
          else if (ev.event === 'Finished') this.done = this.total;
        });

        this.phase = 'ready';
        if (this.auto) await this.install();
      } catch (e) {
        this.error = e instanceof Error ? e.message : String(e);
        this.phase = 'error';
      }
    },
    /** Idle gate: with a job running, wait for it -- installing kills the daemon. */
    async install() {
      if (!this.update || (this.phase !== 'ready' && this.phase !== 'waiting')) return;
      const ep = useEndpoint();
      await ep.refresh().catch(() => undefined);
      if (ep.health && !ep.health.idle) {
        this.phase = 'waiting';

        const poll = setInterval(async () => {
          await ep.refresh().catch(() => undefined);
          if (ep.health?.idle) {
            clearInterval(poll);
            this.phase = 'ready';
            void this.install();
          }
        }, 5000);

        return;
      }
      this.phase = 'installing';
      try {
        await this.update.install(); // staged; the relaunch swaps it in
        const { relaunch } = await import('@tauri-apps/plugin-process');
        await relaunch(); // exit path stops the sidecar first (lib.rs)
      } catch (e) {
        this.error = e instanceof Error ? e.message : String(e);
        this.phase = 'error';
      }
    },
    setAuto(v: boolean) {
      this.auto = v;
      this.persist();
      if (v && this.phase === 'available') void this.download();
      if (v && this.phase === 'ready') void this.install();
    },
  },
});
