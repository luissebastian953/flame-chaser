/**
 * The background controller: what Curio does while it crawls and another
 * app is in front. Runs once, in App.vue, desktop only.
 *
 * - Mini window: 1.5 s after the main window loses focus with a worker
 *   running, ask the shell for the `pip` window; feed it a `PipTick` at
 *   most twice a second; close it when the main window is focused again,
 *   when × is pressed, or 2 s after the queue empties ("done · +N new").
 * - Tray: the tooltip follows the focused job; the menu's Pause / Resume,
 *   Show mini window and Quit come back as `tray:*` events.
 * - Notifications mode: one system notification per finished run, and
 *   nothing else.
 *
 * The pure helpers below are what the tests pin; the composable only wires
 * them to the stores, the shell and the clock.
 */
import type { DaemonEvent } from '@/lib/api';
import { characterOf, jobTitle, postsOf, sourceOf, targetOf, workerColor } from '@/lib/pipeline';
import type { Job, Lane, Watch } from '@/lib/types';
import type { WorkerJob } from '@/stores/jobs';
import { PIP_EVENTS, type PipPlacement, type PipRow, type PipStrings, type PipTick } from '@/pip/protocol';

/** ms after the main window blurs before the mini window appears */
export const PIP_DELAY = 1500;

/** ms the "done" state stays before the mini window closes */
export const PIP_LINGER = 2000;

/** the tick cadence: at most twice a second */
export const TICK_MS = 500;

/** the panel's height per expand state, for the first open (it then asks for its own) */
export const PIP_HEIGHT = { collapsed: 150, expanded: 300 } as const;

export interface Translate {
  (key: string, params?: Record<string, unknown>): string;
}

export interface Exists {
  (key: string): boolean;
}

const LANE_KEY: Record<Lane, string> = { pixiv: 'pipeline.lane.pixiv', twitter: 'pipeline.lane.twitter' };

function laneOf(job: Job): Lane | null {
  const l = job.worker ?? job.lane;
  return l === 'any' ? null : l;
}

function nameOf(job: Job, watches: readonly Watch[], t: Translate): string {
  const ch = characterOf(job, watches);
  if (ch) return ch.name;
  const tt = jobTitle(job);
  return t(tt.key, tt.params);
}

function stageWord(job: Job, t: Translate, te: Exists): string {
  const s = job.stage ?? '';
  return s && te(`pipeline.stage.${s}`) ? t(`pipeline.stage.${s}`) : s;
}

/** jobs the planner made in one request land within this of each other */
const RUN_WINDOW_MS = 5_000;

/**
 * Rows: the running lanes in worker order, then the queue in its order. Each
 * row names the character run it belongs to (`group`): a crawl's pixiv and X
 * halves share it, and the X timelines sweep the same request queued behind
 * them joins it too, so the panel shows one line per character that unfolds.
 */
export function pipRows(
  slots: readonly WorkerJob[],
  queued: readonly Job[],
  lanes: readonly Lane[],
  watches: readonly Watch[],
  t: Translate,
  te: Exists,
): PipRow[] {
  const entries: { job: Job; row: PipRow }[] = [];
  for (const [index, s] of slots.entries()) {
    if (!s.job) continue;
    const src = sourceOf(s.job);
    const name = nameOf(s.job, watches, t);

    entries.push({
      job: s.job,
      row: {
        id: s.job.id,
        name,
        source: src ? t(LANE_KEY[src]) : '',
        color: workerColor(index),
        stage: stageWord(s.job, t, te),
        done: s.job.done,
        total: s.job.total,
        posts: postsOf(s.job),
        target: targetOf(s.job),
        queued: false,
        group: characterOf(s.job, watches)?.slug ?? s.job.id,
        groupName: name,
      },
    });
  }
  for (const j of queued) {
    const src = sourceOf(j);
    const lane = laneOf(j);
    const name = nameOf(j, watches, t);

    entries.push({
      job: j,
      row: {
        id: j.id,
        name,
        source: src ? t(LANE_KEY[src]) : '',
        color: lane ? workerColor(Math.max(0, lanes.indexOf(lane))) : 'var(--dim)',
        stage: t('pip.queued'),
        done: 0,
        total: null,
        posts: 0,
        target: targetOf(j),
        queued: true,
        group: characterOf(j, watches)?.slug ?? j.id,
        groupName: name,
      },
    });
  }
  // the sweep behind a crawl: the character job of the same request hosts it
  for (const e of entries) {
    if (e.job.type !== 'timelines') continue;
    const at = Date.parse(e.job.created_at);

    const host = entries.find(
      (x) => characterOf(x.job, watches) && Math.abs(Date.parse(x.job.created_at) - at) <= RUN_WINDOW_MS,
    );

    if (host) {
      e.row.group = host.row.group;
      e.row.groupName = host.row.groupName;
    }
  }
  return entries.map((e) => e.row);
}

export function pipStrings(t: Translate): PipStrings {
  return {
    crawling: t('pip.crawling'),
    paused: t('pip.paused'),
    offline: t('pip.offline'),
    queued: t('pip.queued'),
    // the mini window fills {n} itself, so the placeholder survives interpolation
    more: t('pip.more', { n: '{n}' }),
    less: t('pip.less'),
    pauseAll: t('pip.pauseAll'),
    resumeAll: t('pip.resumeAll'),
    newToday: t('pip.newToday', { n: '{n}' }),
    rpm: t('pip.rpm', { n: '{n}' }),
    open: t('pip.open'),
    hide: t('pip.hide'),
    finished: t('pip.finished', { n: '{n}' }),
  };
}

export interface TickInput {
  slots: readonly WorkerJob[];
  queued: readonly Job[];
  lanes: readonly Lane[];
  watches: readonly Watch[];
  /** the lane the user last opened in detail; its job is the focused row */
  focus: Lane | null;
  paused: boolean;
  /** the daemon holds the queue for a lost connection (reads "paused · no internet") */
  offline?: boolean;
  newToday: number;
  rpm: number;
  expanded: boolean;
  finished: { posts: number } | null;
  locale: string;
}

export function buildTick(input: TickInput, t: Translate, te: Exists): PipTick {
  const rows = pipRows(input.slots, input.queued, input.lanes, input.watches, t, te);
  const onFocus = input.focus ? input.slots.find((s) => s.lane === input.focus)?.job : null;
  const focusedId = onFocus?.id ?? rows.find((r) => !r.queued)?.id ?? rows[0]?.id ?? null;
  return {
    paused: input.paused,
    offline: !!input.offline,
    rows,
    focusedId,
    newToday: input.newToday,
    rpm: input.rpm,
    expanded: input.expanded,
    finished: input.finished,
    strings: pipStrings(t),
    lang: input.locale,
  };
}

/** the tray tooltip: the focused job's progress, else idle */
export function tooltipFor(tick: PipTick, t: Translate): string {
  const r = tick.rows.find((x) => x.id === tick.focusedId) ?? tick.rows.find((x) => !x.queued);
  if (!r) return t('pip.tray.idle');

  const progress =
    r.target !== null
      ? `${r.posts}/${r.target}`
      : r.total !== null
        ? `${r.done}/${r.total}`
        : String(r.posts);

  return t('pip.tray.tooltip', { name: r.name, progress, new: tick.newToday });
}

export interface OpenInput {
  mode: 'mini' | 'notify' | 'none';
  focused: boolean;
  running: number;
  dismissed: boolean;
}

/** the mini window wants to exist: mini mode, main unfocused, a worker busy, not hidden with × */
export function shouldOpen(i: OpenInput): boolean {
  return i.mode === 'mini' && !i.focused && i.running > 0 && !i.dismissed;
}

export interface Notice {
  title: string;
  body: string;
}

/**
 * The one notification of notifications mode: a crawl (one character on
 * one source, or the followed X timelines) finished -- however it ended.
 * Other job kinds (labels, tags, links) are housekeeping and stay quiet.
 */
export function finishedNotice(
  ev: DaemonEvent,
  jobs: readonly Job[],
  watches: readonly Watch[],
  t: Translate,
): Notice | null {
  if (ev.type !== 'job.finished') return null;
  const job = jobs.find((j) => j.id === ev.data.job_id);
  if (!job || (job.type !== 'poll' && job.type !== 'timelines')) return null;
  const state = String(ev.data.state ?? job.state);
  const counters = (ev.data.counters as Record<string, number> | undefined) ?? job.counters ?? {};
  const name = nameOf(job, watches, t);
  const src = sourceOf(job);
  const source = src ? t(LANE_KEY[src]) : '';
  const n = counters.downloaded ?? counters.new_posts ?? counters.new ?? 0;

  const body =
    state === 'succeeded'
      ? t('pip.notify.finished', { name, source, n })
      : t('pip.notify.ended', { name, source, state: t(`pipeline.state.${state}`) });

  return { title: t('pip.notify.title'), body };
}

/** new images from the jobs that finished since `since` (ms epoch) */
export function newSince(jobs: readonly Job[], since: number): number {
  let n = 0;
  for (const j of jobs) {
    if (!j.finished_at || new Date(j.finished_at).getTime() < since) continue;
    const c = j.counters ?? {};
    n += c.downloaded ?? c.new_posts ?? c.new ?? 0;
  }
  return n;
}

/**
 * Wires the helpers to the stores and the shell. A no-op outside the
 * desktop app. Everything Tauri is imported lazily so the browser build
 * never loads it.
 */
export function useBackgroundController() {
  const bg = useBackground();
  const jobs = useJobs();
  const lib = useLibrary();
  const router = useRouter();
  const { t, te, locale } = useI18n();

  if (!bg.inTauri) return;

  let focused = true;
  let pipOpen = false;
  let openedAt = 0;
  let lingering = false;
  let openTimer: ReturnType<typeof setTimeout> | undefined;
  let lingerTimer: ReturnType<typeof setTimeout> | undefined;
  let ticker: ReturnType<typeof setInterval> | undefined;
  let lastTick = '';
  let lastTooltip = '';
  let seenEvents = 0;
  const unlisten: (() => void)[] = [];

  const core = () => import('@tauri-apps/api/core');
  const event = () => import('@tauri-apps/api/event');

  const tick = (finished: { posts: number } | null = null): PipTick =>
    buildTick(
      {
        slots: jobs.slots,
        queued: jobs.queued,
        lanes: jobs.lanes,
        watches: lib.watches,
        focus: jobs.focus,
        paused: !!jobs.pipeline?.paused,
        offline: jobs.offline,
        newToday: jobs.session.images,
        rpm: jobs.pipeline?.req_per_min ?? 0,
        expanded: bg.expanded,
        finished,
        locale: locale.value,
      },
      t,
      te,
    );

  async function send(payload: PipTick) {
    const { emitTo } = await event();
    await emitTo('pip', PIP_EVENTS.tick, payload).catch(() => {});
  }

  async function open() {
    const { invoke } = await core();
    const placement: PipPlacement = { side: bg.side, y: bg.y };
    const height = bg.expanded ? PIP_HEIGHT.expanded : PIP_HEIGHT.collapsed;
    try {
      await invoke('pip_open', { placement, height });
      pipOpen = true;
      openedAt = Date.now();
      lastTick = '';
    } catch {
      pipOpen = false;
    }
  }

  async function close() {
    pipOpen = false;
    lingering = false;
    clearTimeout(lingerTimer);
    const { invoke } = await core();
    await invoke('pip_close').catch(() => {});
  }

  /** Runs on every tick and on every focus change, so it must only *arm* the
   *  open delay, never restart it: clearing it on each call left a timer that
   *  was reset every 500 ms and fired never (the first build's missing panel). */
  function decide() {
    const want = shouldOpen({
      mode: bg.effectiveMode,
      focused,
      running: jobs.running.length,
      dismissed: bg.dismissed,
    });

    if (want) {
      if (!pipOpen && openTimer === undefined) {
        openTimer = setTimeout(() => {
          openTimer = undefined;
          void open();
        }, PIP_DELAY);
      }
      return;
    }

    clearTimeout(openTimer);
    openTimer = undefined;
    if (pipOpen && !lingering) {
      // the queue emptied while the panel was up: say so, then go
      if (!focused && jobs.running.length === 0 && bg.effectiveMode === 'mini') {
        lingering = true;
        void send(tick({ posts: newSince(jobs.jobs, openedAt) }));
        lingerTimer = setTimeout(() => void close(), PIP_LINGER);
      } else {
        void close();
      }
    }
    if (jobs.running.length === 0 && jobs.queued.length === 0) bg.dismissed = false;
  }

  async function tray(payload: PipTick) {
    const mode = bg.effectiveMode;
    const live = mode !== 'none' && (!bg.dismissed || bg.trayKeepsProgress);
    const tooltip = live ? tooltipFor(payload, t) : 'Curio';
    const { invoke } = await core();
    if (tooltip === lastTooltip) {
      await invoke('tray_update', { tooltip: null, paused: payload.paused, labels: null }).catch(() => {});
      return;
    }
    lastTooltip = tooltip;
    await invoke('tray_update', { tooltip, paused: payload.paused, labels: null }).catch(() => {});
  }

  async function labels() {
    const { invoke } = await core();

    await invoke('tray_update', {
      tooltip: null,
      paused: !!jobs.pipeline?.paused,
      labels: {
        pause: t('pip.tray.pause'),
        resume: t('pip.tray.resume'),
        show_pip: t('pip.tray.showPip'),
        quit: t('pip.tray.quit'),
      },
    }).catch(() => {});
  }

  function onTick() {
    decide();
    const payload = tick();
    const key = JSON.stringify(payload);
    if (key === lastTick) return;
    lastTick = key;
    if (pipOpen && !lingering) void send(payload);
    void tray(payload);
  }

  async function notify(n: Notice) {
    const { isPermissionGranted, requestPermission, sendNotification } =
      await import('@tauri-apps/plugin-notification');

    let ok = await isPermissionGranted();
    if (!ok) ok = (await requestPermission()) === 'granted';
    if (ok) sendNotification({ title: n.title, body: n.body });
  }

  function onEvents() {
    const fresh = jobs.events.slice(seenEvents);
    seenEvents = jobs.events.length;
    if (bg.effectiveMode !== 'notify') return;
    for (const ev of fresh) {
      const n = finishedNotice(ev, jobs.jobs, lib.watches, t);
      if (n) void notify(n);
    }
  }

  async function showMain() {
    const { invoke } = await core();
    await invoke('show_main').catch(() => {});
  }

  async function start() {
    await bg.probe();
    const { listen } = await event();
    const { getCurrentWindow } = await import('@tauri-apps/api/window');
    const win = getCurrentWindow();
    focused = await win.isFocused().catch(() => true);

    unlisten.push(
      await win.onFocusChanged(({ payload }) => {
        focused = payload;
        decide();
      }),
    );

    unlisten.push(
      await listen(PIP_EVENTS.ready, () => {
        lastTick = '';
        void send(tick());
      }),
      await listen(PIP_EVENTS.focusMain, async () => {
        await showMain();
        await router.push('/pipeline');
      }),
      await listen<string>(PIP_EVENTS.openLane, async (ev) => {
        const job = jobs.jobs.find((j) => j.id === ev.payload);
        const lane = job ? laneOf(job) : null;
        if (lane) jobs.focus = lane;
        await showMain();
        await router.push(lane ? `/pipeline/${lane}` : '/pipeline');
      }),
      await listen(PIP_EVENTS.dismiss, () => {
        bg.dismissed = true;
        void close();
      }),
      await listen<boolean>(PIP_EVENTS.expand, (ev) => {
        bg.set({ expanded: ev.payload });
        lastTick = '';
        void send(tick());
      }),
      await listen(PIP_EVENTS.pauseAll, () => {
        jobs.pauseQueue(!jobs.pipeline?.paused).catch(() => {});
      }),
      await listen<PipPlacement>(PIP_EVENTS.placed, (ev) => {
        bg.set({ side: ev.payload.side, y: ev.payload.y });
      }),
      await listen('tray:pause', () => {
        jobs.pauseQueue(!jobs.pipeline?.paused).catch(() => {});
      }),
      await listen('tray:show-pip', () => {
        bg.dismissed = false;
        if (bg.effectiveMode === 'mini' && !pipOpen) void open();
      }),
    );

    await labels();
    ticker = setInterval(onTick, TICK_MS);
  }

  watch(
    () => jobs.events.length,
    () => onEvents(),
  );

  watch(locale, () => void labels());

  // switching the mode while a panel is open closes it at once; "mini" opens on the next blur
  watch(
    () => bg.mode,
    () => decide(),
  );

  // the first open follows the Settings default; after that the panel's own toggle wins
  watch(
    () => bg.startExpanded,
    (v) => bg.set({ expanded: v }),
  );

  onMounted(() => void start());

  onBeforeUnmount(() => {
    clearInterval(ticker);
    clearTimeout(openTimer);
    clearTimeout(lingerTimer);
    for (const u of unlisten) u();
  });
}
