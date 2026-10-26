import { flushPromises } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import PipelineList from './PipelineList.vue';
import type { Job, PipelineState, Watch } from '@/lib/types';
import { mountWithPlugins } from '@/test/utils';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
  mediaUrl: (sha: string) => `/media/${sha}`,
  subscribe: vi.fn(() => vi.fn()),
}));

const ganyu = {
  slug: 'ganyu',
  label: 'Ganyu',
  pixiv_tags: ['甘雨'],
  match_terms: ['甘雨'],
  sources: ['pixiv', 'twitter'],
  cover_sha: 'c0ffee',
} as Watch;

function job(id: string, over: Partial<Job> = {}): Job {
  return {
    id,
    type: 'poll',
    params: {},
    state: 'queued',
    stage: null,
    done: 0,
    total: null,
    counters: {},
    error: null,
    created_at: '2026-10-14T00:00:00Z',
    started_at: null,
    finished_at: null,
    lane: 'pixiv',
    worker: null,
    position: 1,
    paused: false,
    req_per_min: 0,
    ...over,
  };
}

const running = job('r1', {
  state: 'running',
  worker: 'pixiv',
  stage: 'discover',
  params: { source: 'pixiv', watches: ['ganyu'] },
  counters: { posts: 27 },
  started_at: new Date().toISOString(),
  req_per_min: 28,
});

const queuedX = job('q1', {
  lane: 'twitter',
  params: { source: 'twitter', watches: ['ganyu'], target: 300 },
});

const timelines = job('q2', { type: 'timelines', lane: 'twitter', params: { accounts: 34 }, position: 2 });

const pipeline: PipelineState = {
  paused: false,
  pause_reason: null,
  online: true,
  workers: [
    { lane: 'pixiv', job_id: 'r1' },
    { lane: 'twitter', job_id: null },
  ],
  budgets: [
    { key: 'pixiv.search', label: 'pixiv · search', rate: 0.5, per_min: 12 },
    { key: 'gallery-dl', label: 'gallery-dl', rate: null, per_min: 0 },
  ],
  req_per_min: 48,
};

async function mountList(jobs: Job[] = [running, queuedX, timelines]) {
  vi.mocked(api.get).mockImplementation(async (path: string) =>
    path === '/api/pipeline' ? pipeline : path.startsWith('/api/jobs') ? jobs : [],
  );

  vi.mocked(api.post).mockResolvedValue(undefined);

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/pipeline', component: PipelineList },
      { path: '/pipeline/:lane', component: { template: '<div />' } },
    ],
  });

  router.push('/pipeline');
  await router.isReady();

  const wrapper = mountWithPlugins(PipelineList, {
    global: { plugins: [router] },
    pinia: { initialState: { library: { watches: [ganyu] } } },
  });

  await flushPromises();
  return { wrapper, router };
}

describe('PipelineList', () => {
  afterEach(() => vi.useRealTimers());

  it('shows one card per busy worker and an idle slot for the free one', async () => {
    const { wrapper } = await mountList();
    const text = wrapper.text();

    expect(text).toContain('1 of 2 workers busy');
    expect(text).toContain('2 queued');
    expect(text).toContain('Ganyu');
    expect(text).toContain('甘雨');
    expect(text).toContain('27 new'); // a pixiv crawl has no target: new posts so far
    expect(text).toContain('28 req/min');
    expect(text).toContain('48 req/min');
    expect(text).toContain('idle X worker');
    expect(wrapper.find('[data-pipeline-running="true"]').exists()).toBe(true);
  });

  it('lists the queue with what each job will do, and runs one now', async () => {
    const { wrapper } = await mountList();
    expect(wrapper.text()).toContain('300 posts');
    expect(wrapper.text()).toContain('34 accounts');
    expect(wrapper.text()).toContain('X · followed timelines');

    const runNow = wrapper.findAll('button').filter((b) => b.text() === 'Run now');
    await runNow[1]!.trigger('click');
    expect(api.post).toHaveBeenCalledWith('/api/jobs/q2/run-now');
  });

  it('reorders by drag and drop', async () => {
    const { wrapper } = await mountList();
    const rows = wrapper.findAll('.qrow');
    await rows[1]!.trigger('dragstart');
    await rows[0]!.trigger('drop');

    expect(api.post).toHaveBeenCalledWith('/api/jobs/reorder', { ids: ['q2', 'q1'] });
  });

  it('pauses the queue, and cancel all needs a second click', async () => {
    const { wrapper } = await mountList();

    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Pause queue'))!
      .trigger('click');

    expect(api.post).toHaveBeenCalledWith('/api/pipeline/pause', { paused: true });

    const cancel = () => wrapper.findAll('button').find((b) => /Cancel all|Click again/.test(b.text()))!;
    await cancel().trigger('click');
    expect(api.post).not.toHaveBeenCalledWith('/api/jobs/r1/cancel');
    expect(cancel().text()).toContain('Click again to cancel all');
    await cancel().trigger('click');
    await flushPromises();
    expect(api.post).toHaveBeenCalledWith('/api/jobs/r1/cancel');
    expect(api.post).toHaveBeenCalledWith('/api/jobs/q1/cancel');
  });

  it('opens a worker in detail', async () => {
    const { wrapper, router } = await mountList();

    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Open')!
      .trigger('click');

    await flushPromises();

    expect(router.currentRoute.value.path).toBe('/pipeline/pixiv');
  });

  it('still shows a running job that names no worker', async () => {
    const orphan = { ...running, id: 'o1', worker: null, lane: 'any' as const };
    pipeline.workers[0]!.job_id = null;
    const { wrapper } = await mountList([orphan]);
    pipeline.workers[0]!.job_id = 'r1';

    expect(wrapper.text()).toContain('1 of 2 workers busy');
    expect(wrapper.text()).toContain('Ganyu');
  });

  it('Completed today is one row per character run, unfolding into its pixiv, X and timelines parts', async () => {
    const today = new Date().toISOString();

    const px = job('d1', {
      state: 'failed',
      error: 'pixiv: not signed in',
      worker: 'pixiv',
      params: { source: 'pixiv', watches: ['ganyu'] },
      created_at: today,
      finished_at: today,
      counters: { new_posts: 2, downloaded: 1 },
    });

    const tw = job('d2', {
      state: 'succeeded',
      lane: 'twitter',
      worker: 'twitter',
      params: { source: 'twitter', watches: ['ganyu'] },
      created_at: today,
      finished_at: today,
      counters: { new: 5, downloaded: 4, rejected: 1 },
    });

    const tl = job('d3', {
      type: 'timelines',
      state: 'succeeded',
      lane: 'twitter',
      worker: 'twitter',
      params: { accounts: 3 },
      created_at: today,
      finished_at: today,
      counters: { downloaded: 1 },
    });

    const { wrapper } = await mountList([running, px, tw, tl]);

    const rows = wrapper.findAll('.drow');
    expect(rows).toHaveLength(1);
    expect(rows[0]!.text()).toContain('Ganyu');
    expect(rows[0]!.text()).toContain('failed');
    expect(rows[0]!.text()).toContain('+7 new · 5 kept · 1 dropped');
    expect(wrapper.text()).not.toContain('followed timelines');

    await rows[0]!.trigger('click');
    const parts = wrapper.findAll('.prow');
    expect(parts.map((p) => p.find('.pn').text())).toEqual(['pixiv', 'X', 'X · followed timelines']);
    expect(parts[0]!.text()).toContain('failed');
    expect(parts[2]!.text()).toContain('+0 new · 1 kept · 0 dropped');

    await rows[0]!.trigger('click');
    expect(wrapper.findAll('.prow')).toHaveLength(0);
  });

  it('says so when nothing runs: idle pill, no embers, empty queue, Pause queue greyed out', async () => {
    pipeline.workers[0]!.job_id = null;
    const { wrapper } = await mountList([]);
    pipeline.workers[0]!.job_id = 'r1';

    const pause = wrapper.findAll('button').find((b) => b.text().includes('Pause queue'))!;
    expect(pause.attributes('disabled')).toBeDefined();
    expect(wrapper.text()).toContain('idle');
    expect(wrapper.text()).toContain('queue empty');
    expect(wrapper.find('[data-pipeline-running="false"]').exists()).toBe(true);
    expect(wrapper.find('.embers').exists()).toBe(false);
  });

  it('a hold for a lost connection reads as paused with no internet, and Resume queue stays available', async () => {
    Object.assign(pipeline, { paused: true, pause_reason: 'offline', online: false });
    const { wrapper } = await mountList();
    Object.assign(pipeline, { paused: false, pause_reason: null, online: true });

    expect(wrapper.text()).toContain('paused · no internet');
    expect(wrapper.text()).toContain('the pipeline paused itself');
    expect(wrapper.findAll('button').some((b) => b.text().includes('Resume queue'))).toBe(true);
  });

  it('shows the rate budgets and what each sent', async () => {
    const { wrapper } = await mountList();
    expect(wrapper.text()).toContain('pixiv · search');
    expect(wrapper.text()).toContain('0.5/s');
    expect(wrapper.text()).toContain('gallery-dl');
  });
});
