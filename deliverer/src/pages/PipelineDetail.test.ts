import { flushPromises } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import PipelineDetail from './PipelineDetail.vue';
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
  sources: ['pixiv'],
  cover_sha: 'c0ffee',
} as Watch;

function job(over: Partial<Job> = {}): Job {
  return {
    id: 'r1',
    type: 'poll',
    params: { source: 'pixiv', watches: ['ganyu'] },
    state: 'running',
    stage: 'discover',
    done: 19,
    total: 27,
    counters: { listed: 184, gated: 157, new: 27, stored: 14, rejected: 5, posts: 27 },
    error: null,
    created_at: '2026-10-14T00:00:00Z',
    started_at: new Date(Date.now() - 105_000).toISOString(),
    finished_at: null,
    lane: 'pixiv',
    worker: 'pixiv',
    position: 1,
    paused: false,
    req_per_min: 28,
    ...over,
  };
}

const pipeline: PipelineState = {
  paused: false,
  workers: [
    { lane: 'pixiv', job_id: 'r1' },
    { lane: 'twitter', job_id: null },
  ],
  budgets: [],
  req_per_min: 28,
};

async function mountDetail(j: Job | null = job(), lane: 'pixiv' | 'twitter' = 'pixiv') {
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === '/api/pipeline') return pipeline;
    if (path === '/api/jobs/r1') {
      return {
        ...j,
        log: [
          {
            seq: 1,
            at: '2026-10-14T11:42:07Z',
            level: 'info',
            kind: 'item',
            message: '甘雨 · 128994201 · 2p',
            data: { source: 'pixiv', action: 'new' },
          },
          { seq: 2, at: '2026-10-14T11:42:08Z', level: 'info', kind: 'progress', message: '19/27', data: {} },
        ],
      };
    }
    return j ? [j] : [];
  });

  vi.mocked(api.post).mockResolvedValue(undefined);

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/pipeline', component: { template: '<div />' } },
      { path: '/pipeline/:lane', component: PipelineDetail, props: true },
    ],
  });

  router.push(`/pipeline/${lane}`);
  await router.isReady();

  const wrapper = mountWithPlugins(PipelineDetail, {
    props: { lane },
    global: { plugins: [router] },
    pinia: { initialState: { library: { watches: [ganyu] } } },
  });

  await flushPromises();
  return { wrapper, router };
}

describe('PipelineDetail', () => {
  it("shows the worker's job: name, stages, the visited split and its counters", async () => {
    const { wrapper } = await mountDetail();
    const text = wrapper.text();

    expect(text).toContain('Ganyu');
    expect(text).toContain('worker 1');
    expect(text).toContain('tag 甘雨');
    expect(text).toContain('started');
    expect(text).toContain('1m 4'); // elapsed, ticking
    expect(text).toContain('157 skipped — already visited, no request spent');
    expect(text).toContain('27 new');
    expect(text).toContain('discover · 19 / 27');
    expect(text).toContain('kept 14');
    expect(text).toContain('dropped 5');
    for (const s of ['discover', 'tags', 'link', 'download']) expect(text).toContain(s);
  });

  it('shows its own log, without progress lines', async () => {
    const { wrapper } = await mountDetail();
    expect(api.get).toHaveBeenCalledWith('/api/jobs/r1');
    expect(wrapper.find('.lines').text()).toContain('128994201');
    expect(wrapper.find('.lines').text()).not.toContain('19/27');
  });

  it('pauses and cancels this worker only', async () => {
    const { wrapper } = await mountDetail();

    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Pause worker'))!
      .trigger('click');

    expect(api.post).toHaveBeenCalledWith('/api/jobs/r1/pause', { paused: true });

    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Cancel job'))!
      .trigger('click');

    expect(api.post).toHaveBeenCalledWith('/api/jobs/r1/cancel');
  });

  it('counts an X crawl against its target', async () => {
    const x = job({
      lane: 'twitter',
      worker: 'twitter',
      params: { source: 'twitter', watches: ['ganyu'], target: 300 },
      counters: { posts: 184 },
    });

    pipeline.workers = [
      { lane: 'pixiv', job_id: null },
      { lane: 'twitter', job_id: 'r1' },
    ];

    const { wrapper } = await mountDetail(x, 'twitter');

    pipeline.workers = [
      { lane: 'pixiv', job_id: 'r1' },
      { lane: 'twitter', job_id: null },
    ];

    expect(wrapper.text()).toContain('184');
    expect(wrapper.text()).toContain('/ 300');
    expect(wrapper.text()).toContain('posts this run · 116 left');
  });

  it('goes back to the list', async () => {
    const { wrapper, router } = await mountDetail();
    await wrapper.find('button[aria-label="Back to the pipeline"]').trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.path).toBe('/pipeline');
  });

  it('says so when the worker has run nothing', async () => {
    const { wrapper } = await mountDetail(null);
    expect(wrapper.text()).toContain('This worker has not run anything yet');
  });
});
