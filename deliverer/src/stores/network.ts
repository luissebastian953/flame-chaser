import type { NetworkSpeed } from '@/lib/types';

/**
 * The rail's network signal. The daemon measures (its path is the one pixiv
 * and X take, through the configured resolver and proxy); this store keeps
 * the last answer, asks again every 30 s while the app is up, and while the
 * detail modal is open polls the daemon's sample tape once a second so the
 * chart streams during a test.
 */
export const REFRESH_MS = 30_000;

export const POLL_MS = 1_000;

/** while the modal is open: a short probe this often, so the chart grows while it is watched */
export const OPEN_REFRESH_MS = 5_000;

export type Quality = 'offline' | 'poor' | 'fair' | 'good' | 'excellent';

/** what the card reads: before the first answer · no interface · interface but no route · slow or laggy · fine */
export type Phase = 'checking' | 'disconnected' | 'noInternet' | 'degraded' | 'ok';

/** a round trip this long reads as degraded whatever the bandwidth */
export const SLOW_MS = 300;

/** download Mbps → bars: <5 one, <25 two, <100 three, else four; nothing → none */
export function barsFor(download: number | null): number {
  if (download == null) return 0;
  if (download < 5) return 1;
  if (download < 25) return 2;
  if (download < 100) return 3;
  return 4;
}

export const QUALITY: Quality[] = ['offline', 'poor', 'fair', 'good', 'excellent'];

export const useNetwork = defineStore('network', {
  state: () => ({
    speed: null as NetworkSpeed | null,
    testing: false, // our probe request is out
    unreachable: false, // the daemon did not answer the last probe: shown as offline
    open: false, // the detail modal
    nextAt: null as number | null, // when the scheduled probe fires next (ms); the card's "retrying N s"
    lostAt: null as number | null, // when the line was last seen going down (ms); the modal's "lost HH:MM:SS"
    clock: Date.now(), // ticks once a second while started, so countdowns are reactive
    ticker: null as ReturnType<typeof setInterval> | null,
    timer: null as ReturnType<typeof setInterval> | null,
    poller: null as ReturnType<typeof setInterval> | null,
  }),
  getters: {
    online: (s) => !s.unreachable && !!s.speed?.online,
    download(): number | null {
      return this.online ? (this.speed?.download_mbps ?? null) : null;
    },
    bars(): number {
      return barsFor(this.download);
    },
    quality(): Quality {
      return QUALITY[this.bars] ?? 'offline';
    },
    /** seconds until the scheduled probe fires */
    retryIn(): number {
      return this.nextAt ? Math.max(0, Math.ceil((this.nextAt - this.clock) / 1000)) : 0;
    },
    /** seconds since the line went down, or null while it is up */
    lostAgo(): number | null {
      return this.lostAt ? Math.max(0, Math.round((this.clock - this.lostAt) / 1000)) : null;
    },
    phase(): Phase {
      const sp = this.speed;
      if (!sp) return 'checking';
      if (!this.online) return sp.connection.interface ? 'noInternet' : 'disconnected';
      if (this.bars <= 1 || (sp.latency_ms ?? 0) >= SLOW_MS) return 'degraded';
      return 'ok';
    },
  },
  actions: {
    /** Measure now. `full` adds the upload leg (the modal; ~5 s instead of ~2). */
    async measure(full = false) {
      this.testing = true;
      try {
        this.speed = await api.post<NetworkSpeed>('/api/net/speed', { full });
        this.unreachable = false;
      } catch {
        this.unreachable = true;
      } finally {
        this.testing = false;
        this.clock = Date.now();
        if (this.online) this.lostAt = null;
        else if (this.lostAt === null) this.lostAt = this.clock;
      }
    },
    /** The last answer and the sample tape as it grows; no measurement. */
    async refresh() {
      try {
        this.speed = await api.get<NetworkSpeed>('/api/net/speed');
      } catch {
        /* the next probe says offline if it is */
      }
    },
    start() {
      if (this.timer) return;

      const fire = () => {
        this.nextAt = Date.now() + REFRESH_MS;
        void this.measure();
      };

      fire();
      this.timer = setInterval(fire, REFRESH_MS);
      this.ticker = setInterval(() => (this.clock = Date.now()), 1000);
    },
    stop() {
      if (this.timer) clearInterval(this.timer);
      if (this.ticker) clearInterval(this.ticker);
      this.timer = this.ticker = null;
      this.nextAt = null;
      this.hide();
    },
    show() {
      if (this.open) return;
      this.open = true;
      let tick = 0;

      this.poller = setInterval(() => {
        tick += POLL_MS;
        if (tick % OPEN_REFRESH_MS === 0 && !this.testing) void this.measure();
        else void this.refresh();
      }, POLL_MS);

      void this.measure(true);
    },
    hide() {
      this.open = false;
      if (this.poller) clearInterval(this.poller);
      this.poller = null;
    },
  },
});
