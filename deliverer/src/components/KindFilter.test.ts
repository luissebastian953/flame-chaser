import { flushPromises } from '@vue/test-utils';
import KindFilter from './KindFilter.vue';
import type { GalleryKinds, Job } from '@/lib/types';
import { mountWithPlugins } from '@/test/utils';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn() },
}));

function kinds(over: Partial<GalleryKinds['counts']> = {}, labeler = { available: true, models: true }) {
  return {
    counts: { illustration: 71, photo: 57, render: 30, screencap: 2, other: 40, unlabeled: 0, ...over },
    labeler,
  } satisfies GalleryKinds;
}

function job(state: Job['state'], over: Partial<Job> = {}): Job {
  return {
    id: 'j1',
    type: 'label',
    params: {},
    state,
    stage: 'label',
    done: 0,
    total: null,
    counters: {},
    error: null,
    created_at: '',
    started_at: null,
    finished_at: null,
    ...over,
  };
}

function mountFilter(k: GalleryKinds | null) {
  const w = mountWithPlugins(KindFilter, {
    props: { slug: 'kiana' },
    pinia: { initialState: { library: { kinds: k } } },
  });

  return { w, lib: useLibrary(), jobs: useJobs() };
}

const chip = (w: ReturnType<typeof mountFilter>['w'], text: string) =>
  w.findAll('button.chip').find((b) => b.text().startsWith(text))!;

/** Counts after the keep rule: nothing thrown-away is still stored. */
const clean = { photo: 0, render: 0, other: 0 };

describe('KindFilter chips', () => {
  it('shows only the kinds the archive keeps, with counts, all on by default', () => {
    const { w } = mountFilter(kinds(clean));

    expect(w.findAll('button.chip').map((b) => b.text())).toEqual(['Illustrations 71', 'Anime screencaps 2']);
    expect(chip(w, 'Illustrations').attributes('aria-pressed')).toBe('true');
    expect(chip(w, 'Anime screencaps').attributes('aria-pressed')).toBe('true');
    expect(w.text()).not.toContain('Photos');
  });

  it('adds "Not labeled yet" only while something is unlabeled', () => {
    const { w } = mountFilter(kinds({ ...clean, unlabeled: 12 }));

    expect(chip(w, 'Not labeled yet').text()).toBe('Not labeled yet 12');
  });

  it('switching a chip off reloads the grid without that kind', async () => {
    vi.mocked(api.get).mockResolvedValue({ items: [], next_cursor: null });
    const { w, lib } = mountFilter(kinds(clean));

    await chip(w, 'Anime screencaps').trigger('click');
    await flushPromises();

    expect(lib.show).toEqual(['illustration', 'photo', 'render', 'other', 'unlabeled']);
    expect(api.get).toHaveBeenLastCalledWith('/api/gallery/kiana?limit=120&kinds=illustration%2Cunlabeled');
  });

  it('will not switch off the last chip', async () => {
    const { w, lib } = mountFilter(kinds(clean));
    lib.show = ['illustration'];

    await chip(w, 'Illustrations').trigger('click');

    expect(lib.show).toEqual(['illustration']);
    expect(api.get).not.toHaveBeenCalled();
  });
});

describe('KindFilter with the filter off for a character', () => {
  it('has a chip for every kind it holds and nothing to remove', () => {
    const w = mountWithPlugins(KindFilter, {
      props: { slug: 'kiana' },
      pinia: {
        initialState: {
          library: {
            kinds: kinds({ photo: 5, render: 2, other: 1 }),
            watches: [{ slug: 'kiana', kind_filter: false, pixiv_tags: [] }],
          },
        },
      },
    });

    expect(w.findAll('button.chip').map((b) => b.text())).toEqual([
      'Illustrations 71',
      'Anime screencaps 2',
      'Photos & cosplay 5',
      '3D & figures 2',
      'Screenshots & other 1',
    ]);

    expect(w.findAll('button.btn')).toHaveLength(0); // no "Remove N images"
  });
});

describe('KindFilter cleanup', () => {
  const button = (w: ReturnType<typeof mountFilter>['w'], text: string) =>
    w.findAll('button').find((b) => b.text() === text);

  it('nothing to label or remove: no button', () => {
    const { w } = mountFilter(kinds(clean));

    expect(w.findAll('button.btn')).toHaveLength(0);
  });

  it('offers to label the backlog, states the rule, and warns about the first download', () => {
    const { w } = mountFilter(kinds({ ...clean, unlabeled: 3 }, { available: true, models: false }));

    expect(button(w, 'Label 3 images')).toBeTruthy();
    expect(w.text()).toContain('only illustrations and anime screencaps are kept');
    expect(w.text()).toContain('the first run downloads the classifier');
  });

  it('offers to remove photos, 3D and screenshots stored before the rule', () => {
    const { w } = mountFilter(kinds({ photo: 57, render: 30, other: 40 }));

    expect(button(w, 'Remove 127 images')).toBeTruthy();
    expect(w.text()).toContain('photos, cosplay, 3D, figures and screenshots are thrown away');
    expect(w.text()).not.toContain('first run downloads'); // models only matter for labeling
  });

  it('says how to install the classifier instead of offering a button that would fail', () => {
    const { w } = mountFilter(kinds({ unlabeled: 3 }, { available: false, models: false }));

    expect(w.text()).toContain("not installed (pip install 'reaver[classify]')");
    expect(w.findAll('button.btn')).toHaveLength(0);
  });

  it('submits a label job, shows progress, then recounts and redraws when it ends', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ job_id: 'j1' });

    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path.startsWith('/api/jobs')) return [job('running', { done: 1, total: 3 })];
      if (path.endsWith('/kinds')) return kinds(clean);

      return { items: [], next_cursor: null };
    });

    const { w, jobs, lib } = mountFilter(kinds({ unlabeled: 3 }));

    await button(w, 'Label 3 images')!.trigger('click');
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith('/api/jobs', { type: 'label', params: {} });
    expect(w.text()).toContain('Labeling… 1 / 3');

    jobs.jobs = [job('succeeded', { done: 3, total: 3 })];
    await flushPromises();

    expect(api.get).toHaveBeenCalledWith('/api/gallery/kiana/kinds');
    expect(lib.kinds?.counts.photo).toBe(0);
    expect(w.findAll('button.btn')).toHaveLength(0);
  });

  it('shows why a label job failed', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ job_id: 'j1' });

    vi.mocked(api.get).mockImplementation(async (path: string) =>
      path.startsWith('/api/jobs')
        ? [job('failed', { error: 'ModelError: download failed' })]
        : path.endsWith('/kinds')
          ? kinds({ unlabeled: 3 })
          : { items: [], next_cursor: null },
    );

    const { w } = mountFilter(kinds({ unlabeled: 3 }));

    await button(w, 'Label 3 images')!.trigger('click');
    await flushPromises();

    expect(w.text()).toContain('Labeling failed: ModelError: download failed');
  });
});

describe('KindFilter gender backlog', () => {
  it('offers to check images stored before the character had a gender filter', () => {
    const w = mountWithPlugins(KindFilter, {
      props: { slug: 'kiana' },
      pinia: {
        initialState: {
          library: { kinds: { ...kinds({ photo: 0, render: 0, other: 0 }), people: { pending: 5 } } },
        },
      },
    });

    expect(w.findAll('button.btn').map((b) => b.text())).toEqual(['Check 5 images for the gender filter']);
  });
});
