/**
 * The background controller's rules, pinned on the pure helpers: which rows
 * the mini window shows and in what order, which row is focused, when the
 * window wants to exist, what the tray tooltip says, and the one
 * notification of notifications mode.
 */
import { i18n } from '@/i18n';
import type { Job, Watch } from '@/lib/types';
import { buildTick, finishedNotice, newSince, pipRows, shouldOpen, tooltipFor } from './background';

// vue-i18n's overloads make a direct call to `t` with a loose key blow the type checker up
const g = i18n.global as unknown as {
  t: (key: string, params?: Record<string, unknown>) => string;
  te: (key: string) => boolean;
};

const t = (key: string, params?: Record<string, unknown>) => g.t(key, params);
const te = (key: string) => g.te(key);

function job(p: Partial<Job> & { id: string }): Job {
  return {
    type: 'poll',
    params: {},
    state: 'running',
    stage: 'download',
    done: 19,
    total: 27,
    counters: {},
    error: null,
    created_at: '2026-10-25T01:00:00Z',
    started_at: '2026-10-25T01:00:00Z',
    finished_at: null,
    lane: 'pixiv',
    worker: 'pixiv',
    position: 0,
    paused: false,
    req_per_min: 12,
    ...p,
  };
}

const watches: Watch[] = [
  {
    slug: 'ganyu',
    label: 'Ganyu',
    pixiv_tags: ['甘雨'],
    match_terms: [],
    min_bookmarks: 0,
    include_r18: false,
    sources: ['pixiv', 'twitter'],
    target: 300,
    kind_filter: true,
    gender: 'any',
    gender_mode: 'full',
  },
  {
    slug: 'kafka',
    label: 'Kafka',
    pixiv_tags: ['カフカ'],
    match_terms: [],
    min_bookmarks: 0,
    include_r18: false,
    sources: ['pixiv'],
    target: 300,
    kind_filter: true,
    gender: 'any',
    gender_mode: 'full',
  },
];

const ganyuPixiv = job({
  id: 'a',
  params: { watches: ['ganyu'], source: 'pixiv', target: 300 },
  counters: { posts: 184 },
});

const ganyuX = job({
  id: 'b',
  params: { watches: ['ganyu'], source: 'twitter', target: 300 },
  lane: 'twitter',
  worker: 'twitter',
  stage: 'discover',
  done: 7,
  total: null,
  counters: { posts: 92 },
});

const kafkaQueued = job({
  id: 'c',
  state: 'queued',
  stage: null,
  params: { watches: ['kafka'], source: 'pixiv', target: 300 },
  worker: null,
  started_at: null,
  position: 1,
});

const lanes = ['pixiv', 'twitter'] as const;

describe('pipRows', () => {
  it('lists the running lanes in worker order, then the queue', () => {
    const rows = pipRows(
      [
        { lane: 'pixiv', job: ganyuPixiv },
        { lane: 'twitter', job: ganyuX },
      ],
      [kafkaQueued],
      lanes,
      watches,
      t,
      te,
    );

    expect(rows.map((r) => [r.id, r.name, r.source, r.stage, r.queued])).toEqual([
      ['a', 'Ganyu', 'pixiv', 'download', false],
      ['b', 'Ganyu', 'X', 'discover', false],
      ['c', 'Kafka', 'pixiv', 'queued', true],
    ]);

    expect(rows[0]).toMatchObject({ done: 19, total: 27, posts: 184, target: 300, color: 'var(--ember)' });
    expect(rows[1]!.color).toBe('var(--moss)');
    expect(rows[2]!.color).toBe('var(--ember)'); // its lane's colour, dimmed by the row style
    expect(rows.map((r) => r.group)).toEqual(['ganyu', 'ganyu', 'kafka']);
  });

  it("the timelines sweep queued behind a crawl joins that character's group", () => {
    const at = (s: number) => new Date(Date.UTC(2026, 9, 25, 10, 0, s)).toISOString();

    const marin = job({
      id: 'm',
      params: { watches: ['ganyu'], source: 'twitter' },
      lane: 'twitter',
      worker: 'twitter',
      created_at: at(0),
    });

    const sweep = job({
      id: 'tl',
      type: 'timelines',
      params: { accounts: 3 },
      lane: 'twitter',
      created_at: at(1),
    });

    const later = job({
      id: 'tl2',
      type: 'timelines',
      params: { accounts: 3 },
      lane: 'twitter',
      created_at: at(40),
    });

    const rows = pipRows([{ lane: 'twitter', job: marin }], [sweep, later], lanes, watches, t, te);

    expect(rows.map((r) => [r.id, r.group, r.groupName])).toEqual([
      ['m', 'ganyu', 'Ganyu'],
      ['tl', 'ganyu', 'Ganyu'], // same request: a part of Ganyu's run
      ['tl2', 'tl2', 'X · followed timelines'], // another request: its own line
    ]);
  });

  it('skips idle lanes and names a job that is not about one character', () => {
    const timelines = job({ id: 'd', type: 'timelines', params: {}, lane: 'twitter', worker: 'twitter' });

    const rows = pipRows(
      [
        { lane: 'pixiv', job: null },
        { lane: 'twitter', job: timelines },
      ],
      [],
      lanes,
      watches,
      t,
      te,
    );

    expect(rows).toHaveLength(1);
    expect(rows[0]!.name).toBe('X · followed timelines');
  });
});

describe('buildTick', () => {
  const input = {
    slots: [
      { lane: 'pixiv' as const, job: ganyuPixiv },
      { lane: 'twitter' as const, job: ganyuX },
    ],
    queued: [kafkaQueued],
    lanes,
    watches,
    focus: null,
    paused: false,
    newToday: 57,
    rpm: 48,
    expanded: false,
    finished: null,
    locale: 'en',
  };

  it('focuses the first running row unless a lane was opened in detail', () => {
    expect(buildTick(input, t, te).focusedId).toBe('a');
    expect(buildTick({ ...input, focus: 'twitter' }, t, te).focusedId).toBe('b');
    // a focused lane that is idle falls back to the first running row
    expect(buildTick({ ...input, slots: [input.slots[0]!], focus: 'twitter' }, t, te).focusedId).toBe('a');
  });

  it('carries the strings in the interface language', () => {
    const tick = buildTick(input, t, te);

    expect(tick.strings.pauseAll).toBe('Pause all');
    expect(tick.strings.more).toBe('{n}+ more');
    expect(tick.lang).toBe('en');
    expect(tick.newToday).toBe(57);
  });
});

describe('tooltipFor', () => {
  it('names the focused job with its progress, else says idle', () => {
    const tick = buildTick(
      {
        slots: [{ lane: 'pixiv', job: ganyuPixiv }],
        queued: [],
        lanes,
        watches,
        focus: null,
        paused: false,
        newToday: 38,
        rpm: 0,
        expanded: false,
        finished: null,
        locale: 'en',
      },
      t,
      te,
    );

    expect(tooltipFor(tick, t)).toBe('Curio · Ganyu · 184/300 · +38 new');
    expect(tooltipFor({ ...tick, rows: [], focusedId: null }, t)).toBe('Curio · idle');
  });
});

describe('shouldOpen', () => {
  it('wants the window only in mini mode, unfocused, with a worker busy and not hidden', () => {
    const base = { mode: 'mini' as const, focused: false, running: 1, dismissed: false };

    expect(shouldOpen(base)).toBe(true);
    expect(shouldOpen({ ...base, focused: true })).toBe(false);
    expect(shouldOpen({ ...base, running: 0 })).toBe(false);
    expect(shouldOpen({ ...base, dismissed: true })).toBe(false);
    expect(shouldOpen({ ...base, mode: 'notify' })).toBe(false);
    expect(shouldOpen({ ...base, mode: 'none' })).toBe(false);
  });
});

describe('finishedNotice', () => {
  const finished = (data: Record<string, unknown>) => ({ id: 1, type: 'job.finished', data });

  it('is one line per finished crawl, with the new count', () => {
    const n = finishedNotice(
      finished({ job_id: 'a', state: 'succeeded', counters: { downloaded: 38 } }),
      [ganyuPixiv],
      watches,
      t,
    );

    expect(n).toEqual({ title: 'Run finished', body: 'Ganyu · pixiv · +38 new' });
  });

  it('says how a run ended when it did not succeed', () => {
    const n = finishedNotice(
      finished({ job_id: 'a', state: 'failed', counters: {} }),
      [ganyuPixiv],
      watches,
      t,
    );

    expect(n?.body).toBe('Ganyu · pixiv · failed');
  });

  it('stays quiet for housekeeping jobs and other events', () => {
    const label = job({ id: 'l', type: 'label', params: {}, lane: 'any', worker: null });

    expect(finishedNotice(finished({ job_id: 'l', state: 'succeeded' }), [label], watches, t)).toBeNull();

    expect(
      finishedNotice({ id: 2, type: 'job.started', data: { job_id: 'a' } }, [ganyuPixiv], watches, t),
    ).toBeNull();

    expect(finishedNotice(finished({ job_id: 'zz' }), [ganyuPixiv], watches, t)).toBeNull();
  });
});

describe('newSince', () => {
  it('sums the new images of the jobs finished after a moment', () => {
    const since = new Date('2026-10-25T02:00:00Z').getTime();

    const done = [
      job({ id: '1', state: 'succeeded', finished_at: '2026-10-25T02:05:00Z', counters: { downloaded: 20 } }),
      job({ id: '2', state: 'succeeded', finished_at: '2026-10-25T02:06:00Z', counters: { new: 18 } }),
      job({ id: '3', state: 'succeeded', finished_at: '2026-10-25T01:00:00Z', counters: { downloaded: 99 } }),
      ganyuPixiv,
    ];

    expect(newSince(done, since)).toBe(38);
  });
});
