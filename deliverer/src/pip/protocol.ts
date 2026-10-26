/**
 * What crosses between the main window and the mini window (pip.html).
 * The main window builds a `PipTick` from the jobs store and emits it to
 * the `pip` window at most twice a second; the mini window renders it and
 * answers with the `pip:*` events below. Nothing here touches the daemon:
 * the mini window has no token and never fetches.
 */
export type PipSide = 'left' | 'right';

export interface PipPlacement {
  side: PipSide;
  /** logical px from the top of the monitor's work area; null = bottom */
  y: number | null;
}

export interface PipRow {
  id: string;
  name: string;
  /** the lane word, already translated ("pixiv" / "X"); '' for a job on no source */
  source: string;
  /** a CSS colour: the worker's identity colour, or the dim one for a queued job */
  color: string;
  /** stage word or "queued", translated */
  stage: string;
  done: number;
  total: number | null;
  /** posts this run against the target (X) or new posts (pixiv) */
  posts: number;
  target: number | null;
  queued: boolean;
  /** the character run this row belongs to: its slug, or the row's own id for a
   *  job on no character. The X timelines sweep queued behind a crawl joins
   *  that crawl's group, so the panel can fold a run into one line */
  group: string;
  /** the group's label: the character's name */
  groupName: string;
}

/** every string the mini window shows, in the interface language */
export interface PipStrings {
  crawling: string;
  paused: string;
  /** the queue holds itself: no internet */
  offline: string;
  queued: string;
  /** "{n}+ more" */
  more: string;
  less: string;
  pauseAll: string;
  resumeAll: string;
  /** "+{n} new" */
  newToday: string;
  /** "{n} req/min" */
  rpm: string;
  open: string;
  hide: string;
  /** "done · +{n} new" */
  finished: string;
}

export interface PipTick {
  paused: boolean;
  /** paused by the daemon itself because the internet is unreachable; lifts on its own */
  offline: boolean;
  rows: PipRow[];
  /** the row shown alone while collapsed */
  focusedId: string | null;
  newToday: number;
  rpm: number;
  expanded: boolean;
  /** set once the queue has emptied: the panel shows it, then closes */
  finished: { posts: number } | null;
  strings: PipStrings;
  lang: string;
}

export const PIP_EVENTS = {
  /** main → pip */
  tick: 'pipeline:tick',
  /** pip → main */
  ready: 'pip:ready',
  focusMain: 'pip:focus-main',
  openLane: 'pip:open-lane',
  dismiss: 'pip:dismiss',
  expand: 'pip:expand',
  pauseAll: 'pip:pause-all',
  placed: 'pip:placed',
} as const;

/** rows shown when expanded before the list scrolls */
export const PIP_MAX_ROWS = 5;
