import { flushPromises } from '@vue/test-utils';
import OriginFilter from './OriginFilter.vue';
import type { GalleryOrigins, Job } from '@/lib/types';
import { mountWithPlugins } from '@/test/utils';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn() },
}));

function origins(
  over: Partial<GalleryOrigins['counts']> = {},
  detector = { available: true, models: true },
): GalleryOrigins {
  return { counts: { ai: 7, human: 90, pending: 0, ...over }, detector };
}

function job(state: Job['state'], over: Partial<Job> = {}): Job {
  return {
    id: 'j1',
    type: 'label',
    params: {},
    state,
    stage: 'origin',
    done: 0,
    total: null,
    counters: {},
    error: null,
    created_at: '',
    started_at: null,
    finished_at: null,
    lane: 'any',
    worker: null,
    position: 1,
    paused: false,
    req_per_min: 0,
    ...over,
  };
}

function mountFilter(o: GalleryOrigins | null) {
  const w = mountWithPlugins(OriginFilter, {
    props: { slug: 'mei' },
    pinia: { initialState: { library: { origins: o } } },
  });

  return { w, lib: useLibrary(), jobs: useJobs() };
}

type W = ReturnType<typeof mountFilter>['w'];

const chip = (w: W, text: string) => w.findAll('button.chip').find((b) => b.text().startsWith(text))!;
const button = (w: W, text: string) => w.findAll('button').find((b) => b.text() === text);

describe('OriginFilter chips', () => {
  it('shows hand-drawn and AI-made with counts, all on, and hides "Not judged yet" at 0', () => {
    const { w } = mountFilter(origins());

    expect(w.findAll('button.chip').map((b) => b.text())).toEqual(['Hand-drawn 90', 'AI-made 7']);
    expect(chip(w, 'Hand-drawn').attributes('aria-pressed')).toBe('true');
    expect(chip(w, 'AI-made').attributes('aria-pressed')).toBe('true');
    expect(w.findAll('button.btn')).toHaveLength(0); // nothing to judge
  });

  it('adds "Not judged yet" only while something is', () => {
    const { w } = mountFilter(origins({ pending: 4 }));

    expect(chip(w, 'Not judged yet').text()).toBe('Not judged yet 4');
  });

  it('switching "AI-made" off reloads the grid with only the hand-drawn', async () => {
    vi.mocked(api.get).mockResolvedValue({ items: [], next_cursor: null });
    const { w, lib } = mountFilter(origins());

    await chip(w, 'AI-made').trigger('click');
    await flushPromises();

    expect(lib.made).toEqual(['human', 'pending']);

    expect(api.get).toHaveBeenLastCalledWith(
      expect.stringMatching(/^\/api\/gallery\/mei\?.*origin=human%2Cpending/),
    );

    expect(chip(w, 'AI-made').attributes('aria-pressed')).toBe('false');
  });

  it('will not switch off the last state', async () => {
    const { w, lib } = mountFilter(origins());
    lib.made = ['human'];

    await chip(w, 'Hand-drawn').trigger('click');

    expect(lib.made).toEqual(['human']);
    expect(api.get).not.toHaveBeenCalled();
  });

  it('leaves a chosen character alone: the origin is not who is in the picture', async () => {
    vi.mocked(api.get).mockResolvedValue({ items: [], next_cursor: null });
    const { w, lib } = mountFilter(origins());
    lib.character = 'raiden_mei';

    await chip(w, 'AI-made').trigger('click');
    await flushPromises();

    expect(lib.character).toBe('raiden_mei');
    const url = vi.mocked(api.get).mock.lastCall![0] as string;
    expect(url).toContain('character=raiden_mei');
    expect(url).toContain('origin=human');
  });

  it('By tag: a chip selects every image made that way instead of filtering', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ shas: ['a', 'b'] });

    const w = mountWithPlugins(OriginFilter, {
      props: { slug: 'mei' },
      pinia: { initialState: { library: { origins: origins() }, deletion: { slug: 'mei', mode: 'tag' } } },
    });

    const lib = useLibrary();
    await chip(w, 'AI-made').trigger('click');
    await flushPromises();

    expect(lib.made).toEqual(ORIGIN_STATES); // the grid filter is untouched
    expect(vi.mocked(api.get).mock.lastCall?.[0]).toMatch(/\/api\/gallery\/mei\/images\?.*sel_origin=ai$/);
    expect(useDeletion().isTerm('origin', 'ai')).toBe(true);
    expect(chip(w, 'AI-made').classes()).toContain('sel');
  });
});

describe('OriginFilter backlog', () => {
  it('offers to judge images stored before the detector existed, and says nothing is removed', () => {
    const { w } = mountFilter(origins({ pending: 3 }, { available: true, models: false }));

    expect(button(w, 'Judge 3 images')).toBeTruthy();
    expect(w.text()).toContain('nothing is removed');
    expect(w.text()).toContain('downloads the detector (~17 MB)');
  });

  it('skips the first-use hint once the detector is on disk', () => {
    const { w } = mountFilter(origins({ pending: 1 }, { available: true, models: true }));

    expect(button(w, 'Judge 1 image')).toBeTruthy();
    expect(w.text()).not.toContain('downloads the detector');
  });

  it('says how to install the classifier when it is missing', () => {
    const { w } = mountFilter(origins({ pending: 3 }, { available: false, models: false }));

    expect(w.text()).toContain("not installed (pip install 'reaver[classify]')");
    expect(w.findAll('button.btn')).toHaveLength(0);
  });

  it('submits the label job, shows progress, then recounts and redraws when it ends', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ job_id: 'j1' });

    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path.startsWith('/api/jobs')) return [job('running', { done: 2, total: 5 })];
      if (path.endsWith('/origins')) return origins();

      return { items: [], next_cursor: null };
    });

    const { w, jobs, lib } = mountFilter(origins({ pending: 5 }));

    await button(w, 'Judge 5 images')!.trigger('click');
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith('/api/jobs', { type: 'label', params: {} });
    expect(w.text()).toContain('Judging… 2 / 5');

    jobs.jobs = [job('succeeded', { done: 5, total: 5 })];
    await flushPromises();

    expect(api.get).toHaveBeenCalledWith('/api/gallery/mei/origins');
    expect(lib.origins?.counts.pending).toBe(0);
    expect(w.findAll('button.btn')).toHaveLength(0);
  });

  it('shows the error when the job failed', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ job_id: 'j1' });

    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path.startsWith('/api/jobs')) return [job('failed', { error: 'no model' })];
      if (path.endsWith('/origins')) return origins({ pending: 2 });

      return { items: [], next_cursor: null };
    });

    const { w } = mountFilter(origins({ pending: 2 }));
    await button(w, 'Judge 2 images')!.trigger('click');
    await flushPromises();

    expect(w.text()).toContain('Judging failed: no model');
  });
});
