import { flushPromises } from '@vue/test-utils';
import RunToast from './RunToast.vue';
import type { Job, PipelineState } from '@/lib/types';
import type { RunToast as RunToastItem, Toast } from '@/stores/toasts';
import { mountWithPlugins } from '@/test/utils';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn() },
}));

const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/:any(.*)*', component: { template: '<div />' } }],
});

function job(id: string, state: Job['state'], over: Partial<Job> = {}): Job {
  return {
    id,
    type: 'poll',
    params: { watches: ['firefly'], source: 'twitter' },
    state,
    stage: null,
    done: 0,
    total: null,
    counters: {},
    error: null,
    created_at: '2026-10-19T00:00:00Z',
    started_at: null,
    finished_at: null,
    lane: 'twitter',
    worker: null,
    position: 1,
    paused: false,
    req_per_min: 0,
    ...over,
  };
}

const pipeline = (paused = false): PipelineState => ({
  paused,
  workers: [
    { lane: 'pixiv', job_id: null },
    { lane: 'twitter', job_id: null },
  ],
  budgets: [],
  req_per_min: 0,
});

const runToast = (jobIds: string[], over: Partial<RunToastItem> = {}): RunToastItem => ({
  kind: 'run',
  id: 1,
  slug: 'firefly',
  label: 'Firefly',
  sources: ['twitter'],
  jobIds,
  retry: vi.fn(async () => {}),
  ...over,
});

async function mountToast(toast: Toast, jobs: Job[], paused = false) {
  const w = mountWithPlugins(RunToast, {
    props: { toast },
    global: { plugins: [router] },
    pinia: {
      initialState: { jobs: { jobs, pipeline: pipeline(paused) }, toasts: { items: [toast], held: false } },
    },
  });

  await flushPromises();

  return w;
}

const squash = (s: string) => s.replace(/\s+/g, ' ').trim();

type Mounted = Awaited<ReturnType<typeof mountToast>>;

const button = (w: Mounted, text: string) => w.findAll('button').find((b) => b.text() === text);

describe('RunToast', () => {
  afterEach(() => useToasts().clear());

  it('queued behind a busy worker: "queued on X · behind 1 job", with Open pipeline', async () => {
    const w = await mountToast(runToast(['mine']), [
      job('other', 'running', { params: { watches: ['kiana'], source: 'twitter' }, worker: 'twitter' }),
      job('mine', 'queued'),
    ]);

    expect(squash(w.text())).toContain('Firefly queued on X');
    expect(squash(w.text())).toContain('behind 1 job');
    expect(button(w, 'Open pipeline')).toBeTruthy();
    expect(w.find('.timer').exists()).toBe(true);
    expect(useToasts().armed(1)).toBe(true);
  });

  it('queued with a free worker says it starts next', async () => {
    const w = await mountToast(runToast(['mine']), [job('mine', 'queued')]);

    expect(squash(w.text())).toContain('starting next');
  });

  it('started: "crawling on X" with the live stage word', async () => {
    const w = await mountToast(runToast(['mine']), [
      job('mine', 'running', { worker: 'twitter', stage: 'download' }),
    ]);

    expect(squash(w.text())).toContain('Firefly crawling on X');
    expect(w.find('.stage').text()).toBe('download');
  });

  it('both sources: one toast, a chip per source with its own state', async () => {
    const w = await mountToast(runToast(['px', 'tw'], { sources: ['pixiv', 'twitter'] }), [
      job('busy', 'running', {
        params: { watches: ['kiana'], source: 'pixiv' },
        lane: 'pixiv',
        worker: 'pixiv',
      }),
      job('px', 'queued', { params: { watches: ['firefly'], source: 'pixiv' }, lane: 'pixiv' }),
      job('tw', 'running', { worker: 'twitter', stage: 'discover' }),
    ]);

    expect(squash(w.text())).toContain('Firefly running on 2 sources');
    const chips = w.findAll('.src').map((c) => squash(c.text()));
    expect(chips).toEqual(['pixiv queued · 1', 'X discover']);
  });

  it('queue paused: amber, sticky, position in the queue, Resume queue resumes it', async () => {
    vi.mocked(api.post).mockResolvedValue(undefined);
    vi.mocked(api.get).mockResolvedValue(pipeline(false));

    const w = await mountToast(
      runToast(['mine']),
      [
        job('first', 'queued', { params: { watches: ['kiana'] }, position: 0 }),
        job('mine', 'queued', { position: 1 }),
      ],
      true,
    );

    expect(w.find('.toast').classes()).toContain('warn');
    expect(squash(w.text())).toContain('Queue is paused — Firefly will wait');
    expect(squash(w.text())).toContain('queued on X · position 2');
    expect(w.find('.timer').exists()).toBe(false);
    expect(useToasts().armed(1)).toBe(false);

    await w.find('button.act').trigger('click');
    expect(api.post).toHaveBeenCalledWith('/api/pipeline/pause', { paused: false });
  });

  it('no character matches: rose, sticky, the character and its sources, Retry runs it again', async () => {
    const retry = vi.fn(async () => {});

    const w = await mountToast(
      {
        kind: 'error',
        id: 1,
        slug: 'firefly',
        label: 'Firefly',
        sources: ['twitter'],
        terms: 0,
        code: 'nothing_to_run',
        message: 'no character matches',
        retry,
      },
      [],
    );

    expect(w.find('.toast').classes()).toContain('err');
    expect(squash(w.text())).toContain("Couldn't start: no character matches");
    expect(squash(w.text())).toContain('Firefly · X · 0 match terms');
    expect(w.find('.timer').exists()).toBe(false);

    await w.find('button.act').trigger('click');
    expect(retry).toHaveBeenCalled();
    expect(useToasts().items).toHaveLength(0);
  });

  it('daemon unreachable: its own title, the raw error underneath', async () => {
    const w = await mountToast(
      {
        kind: 'error',
        id: 1,
        slug: 'firefly',
        label: 'Firefly',
        sources: ['twitter'],
        terms: 3,
        code: 'unreachable',
        message: 'Failed to fetch',
        retry: vi.fn(async () => {}),
      },
      [],
    );

    expect(squash(w.text())).toContain("Couldn't start: daemon unreachable");
    expect(squash(w.text())).toContain('Failed to fetch');
  });

  it('Open pipeline goes to the worker for one source, the list for two, and dismisses', async () => {
    const one = await mountToast(runToast(['mine']), [job('mine', 'queued')]);
    await button(one, 'Open pipeline')!.trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.path).toBe('/pipeline/twitter');
    expect(useToasts().items).toHaveLength(0);

    const two = await mountToast(runToast(['px', 'tw'], { id: 2, sources: ['pixiv', 'twitter'] }), [
      job('px', 'queued', { params: { watches: ['firefly'], source: 'pixiv' }, lane: 'pixiv' }),
      job('tw', 'queued'),
    ]);

    await button(two, 'Open pipeline')!.trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.path).toBe('/pipeline');
  });

  it('the close glyph dismisses', async () => {
    const w = await mountToast(runToast(['mine']), [job('mine', 'queued')]);
    await w.find('button.x').trigger('click');

    expect(useToasts().items).toHaveLength(0);
  });
});
