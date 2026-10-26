import type { Job, Watch } from '@/lib/types';
import { runsOf } from '@/lib/pipeline';

function job(over: Partial<Job> = {}): Job {
  return {
    id: 'j',
    type: 'poll',
    params: {},
    state: 'running',
    stage: null,
    done: 0,
    total: null,
    counters: {},
    error: null,
    created_at: '',
    started_at: null,
    finished_at: null,
    lane: 'pixiv',
    worker: 'pixiv',
    position: 1,
    paused: false,
    req_per_min: 0,
    ...over,
  };
}

describe('runsOf', () => {
  it("folds a character's per-source jobs into one row and drops everything else", () => {
    const t0 = '2026-10-25T10:48:54.000Z';

    const px = job({
      id: 'px',
      params: { watches: ['mahiru'], source: 'pixiv' },
      state: 'failed',
      error: 'pixiv: not signed in',
      created_at: t0,
      finished_at: '2026-10-25T10:48:55Z',
      counters: { new_posts: 2, downloaded: 1, rejected: 0 },
    });

    const tw = job({
      id: 'tw',
      lane: 'twitter',
      params: { watches: ['mahiru'], source: 'twitter' },
      state: 'succeeded',
      created_at: '2026-10-25T10:48:54.400Z',
      finished_at: '2026-10-25T10:49:29Z',
      counters: { new: 164, downloaded: 146, rejected: 114 },
    });

    const sweep = job({
      id: 'tl',
      type: 'timelines',
      lane: 'twitter',
      params: { accounts: 3 },
      state: 'succeeded',
      created_at: '2026-10-25T10:48:54.600Z',
      finished_at: '2026-10-25T10:49:40Z',
      counters: { downloaded: 1 },
    });

    const label = job({
      id: 'lb',
      type: 'label',
      lane: 'any',
      params: {},
      state: 'succeeded',
      created_at: t0,
      finished_at: '2026-10-25T10:50:00Z',
    });

    const later = job({
      id: 'px2',
      params: { watches: ['mahiru'], source: 'pixiv' },
      state: 'succeeded',
      created_at: '2026-10-25T12:00:00Z',
      finished_at: '2026-10-25T12:00:10Z',
      counters: { new_posts: 5 },
    });

    const runs = runsOf([label, later, sweep, tw, px]);

    expect(runs.map((r) => r.id)).toEqual(['px2', 'px']);
    expect(runs[1]!.parts.map((j) => j.id)).toEqual(['px', 'tw', 'tl']); // the sweep of the same request is a part
    expect(runs[0]!.parts.map((j) => j.id)).toEqual(['px2']); // newest first; the sweep and the label make no row

    expect(runs[1]).toMatchObject({
      slug: 'mahiru',
      state: 'failed',
      error: 'pixiv: not signed in',
      finished_at: '2026-10-25T10:49:29Z',
      counters: { new: 166, kept: 147, dropped: 114 },
    });

    expect(runs[1]!.jobs.map((j) => j.id)).toEqual(['px', 'tw']);
    expect(runs[0]!.counters).toEqual({ new: 5, kept: 0, dropped: 0 });
  });

  it('interrupted outranks failed outranks cancelled as the row state', () => {
    const at = (s: string) => `2026-10-25T10:00:0${s}Z`;

    const mk = (id: string, state: Job['state']) =>
      job({ id, params: { watches: ['a'] }, state, created_at: at('0'), finished_at: at('1') });

    expect(runsOf([mk('1', 'cancelled'), mk('2', 'interrupted'), mk('3', 'failed')])[0]!.state).toBe(
      'interrupted',
    );

    expect(runsOf([mk('1', 'succeeded'), mk('2', 'cancelled')])[0]!.state).toBe('cancelled');
  });
});

const ganyu = {
  slug: 'ganyu',
  label: 'Ganyu',
  pixiv_tags: ['甘雨', '甘雨(原神)'],
  match_terms: ['甘雨'],
  sources: ['pixiv', 'twitter'],
  cover_sha: 'abc',
} as Watch;

describe('pipeline helpers', () => {
  it('give each worker its identity colour, in order', () => {
    expect(workerColor(0)).toBe('var(--ember)');
    expect(workerColor(1)).toBe('var(--moss)');
    expect(workerColor(3)).toBe('oklch(0.8 0.15 75)');
    expect(workerIndex('twitter', ['pixiv', 'twitter'])).toBe(1);
  });

  it('track the engine stages per kind of job', () => {
    const px = job({ params: { source: 'pixiv' }, stage: 'link' });
    expect(stagesOf(px)).toEqual(['discover', 'tags', 'link', 'download']);
    expect(stageIndex(px)).toBe(2);
    const x = job({ params: { source: 'twitter' }, lane: 'twitter', stage: 'discover' });
    expect(stagesOf(x)).toEqual(['discover', 'download']);
    expect(stageIndex(job({ state: 'queued' }))).toBe(-1);

    expect(stagesOf(job({ type: 'export', lane: 'any', stage: 'verify' }))).toEqual([
      'snapshot',
      'images',
      'thumbs',
      'verify',
    ]);

    expect(stageIndex(job({ state: 'succeeded', params: { source: 'pixiv' } }))).toBe(4);
  });

  it('name the character a job crawls, with its first pixiv tag', () => {
    expect(characterOf(job({ params: { watches: ['ganyu'] } }), [ganyu])).toEqual({
      slug: 'ganyu',
      name: 'Ganyu',
      jp: '甘雨',
      cover: 'abc',
    });

    expect(characterOf(job({ type: 'timelines' }), [ganyu])).toBeNull();

    // an X-only character: its match term, unless that is just the name again
    const firefly = {
      ...ganyu,
      slug: 'firefly',
      label: 'Firefly',
      pixiv_tags: [],
      match_terms: ['流蛍'],
    } as Watch;

    expect(characterOf(job({ params: { watches: ['firefly'] } }), [firefly])?.jp).toBe('流蛍');
    const again = { ...firefly, match_terms: ['Firefly (Honkai: Star Rail)'] } as Watch;
    expect(characterOf(job({ params: { watches: ['firefly'] } }), [again])?.jp).toBeNull();
    expect(jobTitle(job({ type: 'timelines', lane: 'twitter' })).key).toBe('pipeline.job.timelines');
  });

  it('count posts and the X target honestly', () => {
    expect(postsOf(job({ counters: { posts: 7, new: 9 } }))).toBe(7);
    expect(postsOf(job({ counters: { new: 9 } }))).toBe(9);
    expect(targetOf(job({ params: { target: 300 } }))).toBe(300);
    expect(targetOf(job())).toBeNull(); // pixiv walks to its watermark, no target
  });

  it('describe a queued job by what it will do', () => {
    expect(queueMeta(job({ type: 'timelines', params: { accounts: 34 } }), [])).toEqual({
      key: 'pipeline.meta.accounts',
      n: 34,
    });

    expect(
      queueMeta(job({ params: { source: 'twitter', target: 100, watches: ['ganyu'] } }), [ganyu]),
    ).toEqual({
      key: 'pipeline.meta.target',
      n: 100,
    });

    expect(queueMeta(job({ params: { source: 'pixiv', watches: ['ganyu'] } }), [ganyu])).toEqual({
      key: 'pipeline.meta.tags',
      n: 2,
    });
  });

  it('format elapsed and eta', () => {
    const t0 = Date.parse('2026-10-14T11:40:22Z');
    expect(elapsed('2026-10-14T11:40:22Z', t0 + 105_000)).toBe('1m 45s');
    expect(elapsed('2026-10-14T11:40:22Z', t0 + 12_000)).toBe('12s');
    expect(elapsed(null)).toBe('-');
    expect(etaSeconds(19, 27, 38)).toBe(16);
    expect(etaSeconds(5, null, 10)).toBeNull();
  });

  it('sort activity into kinds', () => {
    expect(activityKind({ type: 'job.item', data: { action: 'stored' } })).toBe('new');
    expect(activityKind({ type: 'job.item', data: { action: 'dupe' } })).toBe('dupe');
    expect(activityKind({ type: 'job.log', data: { level: 'info' } })).toBe('sys');
    expect(activityKind({ type: 'job.log', data: { level: 'warning' } })).toBe('warn');
  });
});
