import { flushPromises } from '@vue/test-utils';
import LabelFilter from './LabelFilter.vue';
import type { GalleryArtist, GalleryCharacters, GalleryKinds, GalleryOrigins, Job } from '@/lib/types';
import { mountWithPlugins } from '@/test/utils';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn() },
}));

const PAGE = { items: [], next_cursor: null };

function kinds(unlabeled = 0, labeler = { available: true, models: true }): GalleryKinds {
  return { counts: { illustration: 71, photo: 0, render: 0, screencap: 2, other: 0, unlabeled }, labeler };
}

function chars(
  pending = 0,
  identifier = { enabled: true, available: true, models: true },
): GalleryCharacters {
  return { counts: { identified: 50, unidentified: 6, pending }, characters: [], identifier };
}

function origins(pending = 0, detector = { available: true, models: true }): GalleryOrigins {
  return { counts: { ai: 4, human: 60, pending }, detector };
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
    lane: 'any',
    worker: null,
    position: 1,
    paused: false,
    req_per_min: 0,
    ...over,
  };
}

function artist(n: number, source = 'pixiv'): GalleryArtist {
  return {
    source,
    artist_id: `id${n}`,
    name: `Artist ${n}`,
    handle: n % 2 ? `handle${n}` : '',
    count: 100 - n,
  };
}

const ARTISTS = [artist(1), artist(2, 'twitter'), artist(3)];

type Seed = {
  kinds?: GalleryKinds | null;
  characters?: GalleryCharacters | null;
  origins?: GalleryOrigins | null;
  artists?: GalleryArtist[];
  mode?: 'tag';
};

function mountRow(seed: Seed = {}) {
  const w = mountWithPlugins(LabelFilter, {
    props: { slug: 'mei' },
    pinia: {
      initialState: {
        library: {
          kinds: seed.kinds === undefined ? kinds() : seed.kinds,
          characters: seed.characters === undefined ? chars() : seed.characters,
          origins: seed.origins === undefined ? origins() : seed.origins,
          artists: seed.artists ?? ARTISTS,
        },
        deletion: seed.mode ? { slug: 'mei', mode: seed.mode } : {},
      },
    },
  });

  return { w, lib: useLibrary(), jobs: useJobs(), del: useDeletion() };
}

type W = ReturnType<typeof mountRow>['w'];

const button = (w: W, text: string) => w.findAll('button').find((b) => b.text() === text)!;
const radios = (w: W) => w.findAll('[role="radiogroup"] [role="radio"]');
const fold = (w: W) => w.findAll('button').find((b) => b.text().startsWith('View Artists Tags'));
const chips = (w: W) => w.findAll('.artists button.chip');

describe('LabelFilter row', () => {
  it('the source control (All / pixiv / X) sits left, the label radios right, Any label checked', () => {
    const { w } = mountRow();

    expect(w.findAll('[role="group"] button').map((b) => b.text())).toEqual(['All', 'pixiv', 'X']);
    expect(button(w, 'All').attributes('aria-pressed')).toBe('true');

    expect(radios(w).map((r) => r.text())).toEqual(['Any label', 'AI', 'Non-Illust', 'Unidentified']);
    expect(radios(w).map((r) => r.attributes('aria-checked'))).toEqual(['true', 'false', 'false', 'false']);
    expect(radios(w)[1]!.find('.sw.ai').exists()).toBe(true); // swatch before the name
    expect(radios(w)[0]!.find('.sw').exists()).toBe(false); // none on the default
  });

  it('a label narrows the grid to it, single select, ANDed with the source', async () => {
    vi.mocked(api.get).mockResolvedValue(PAGE);
    const { w, lib } = mountRow();

    await button(w, 'AI').trigger('click');
    await flushPromises();
    expect(lib.label).toBe('ai');

    expect(api.get).toHaveBeenLastCalledWith(
      '/api/gallery/mei?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled&label=ai',
    );

    expect(radios(w).map((r) => r.attributes('aria-checked'))).toEqual(['false', 'true', 'false', 'false']);

    await button(w, 'X').trigger('click');
    await flushPromises();

    expect(api.get).toHaveBeenLastCalledWith(
      '/api/gallery/mei?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled&label=ai&source=twitter',
    );

    await button(w, 'Unidentified').trigger('click');
    await flushPromises();
    expect(lib.label).toBe('unidentified'); // replaces, never adds
    expect(radios(w).map((r) => r.attributes('aria-checked'))).toEqual(['false', 'false', 'false', 'true']);

    await button(w, 'Any label').trigger('click');
    await flushPromises();
    expect(lib.label).toBeNull();

    expect(api.get).toHaveBeenLastCalledWith(
      '/api/gallery/mei?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled&source=twitter',
    );
  });

  it('clicking the label already on sends nothing', async () => {
    const { w } = mountRow();
    await button(w, 'Any label').trigger('click');
    expect(api.get).not.toHaveBeenCalled();
  });

  it('By tag: a label option is a chip selecting by sel_label, and Any label steps aside', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ shas: ['a', 'b'] });
    const { w, lib, del } = mountRow({ mode: 'tag' });

    expect(radios(w).map((r) => r.text())).toEqual(['AI', 'Non-Illust', 'Unidentified']);

    await button(w, 'Non-Illust').trigger('click');
    await flushPromises();

    expect(lib.label).toBeNull(); // the grid filter is untouched

    expect(vi.mocked(api.get).mock.lastCall?.[0]).toBe(
      '/api/gallery/mei/images?kinds=illustration%2Cscreencap%2Cunlabeled&sel_label=non_illust',
    );

    expect(del.isTerm('label', 'non_illust')).toBe(true);
    expect(del.terms[0]?.label).toBe('Non-Illust');
    expect(button(w, 'Non-Illust').classes()).toContain('sel');
    expect(button(w, 'Non-Illust').attributes('aria-checked')).toBe('true');
  });
});

describe('LabelFilter status line', () => {
  it('is absent while nothing is pending', () => {
    const { w } = mountRow();

    expect(w.find('.status').exists()).toBe(false);
    expect(w.findAll('button.btn.sm').map((b) => b.text())).not.toContain('Label now');
  });

  it('sums what the three classifiers still owe and offers Label now', () => {
    const { w } = mountRow({ kinds: kinds(3), characters: chars(4), origins: origins(5) });

    expect(w.find('.status').text()).toContain('12 images not fully labeled yet');
    expect(button(w, 'Label now')).toBeTruthy();
    expect(w.text()).not.toContain('first run downloads');
  });

  it('one image pending reads in the singular', () => {
    const { w } = mountRow({ kinds: kinds(0), characters: chars(1), origins: origins(0) });
    expect(w.find('.status').text()).toContain('1 image not fully labeled yet');
  });

  it('warns about the first download when a classifier with work to do has no model yet', () => {
    const { w } = mountRow({ characters: chars(2, { enabled: true, available: true, models: false }) });
    expect(w.text()).toContain('the first run downloads the classifiers');
  });

  it('says how to install the classifier when none of the three is available', () => {
    const { w } = mountRow({
      kinds: kinds(3, { available: false, models: false }),
      characters: chars(0, { enabled: true, available: false, models: false }),
      origins: origins(0, { available: false, models: false }),
    });

    expect(w.text()).toContain("not installed (pip install 'reaver[classify]')");
    expect(w.findAll('button').map((b) => b.text())).not.toContain('Label now');
  });

  it('submits one label job for all three, shows progress, then recounts and redraws when it ends', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ job_id: 'j1' });

    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path.startsWith('/api/jobs')) return [job('running', { done: 2, total: 9 })];
      if (path.endsWith('/kinds')) return kinds(0);
      if (path.endsWith('/characters')) return chars(0);
      if (path.endsWith('/origins')) return origins(0);

      return PAGE;
    });

    const { w, jobs, lib } = mountRow({ kinds: kinds(3), characters: chars(4), origins: origins(2) });

    await button(w, 'Label now').trigger('click');
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith('/api/jobs', { type: 'label', params: {} });
    expect(w.text()).toContain('Labeling… 2 / 9');

    jobs.jobs = [job('succeeded', { done: 9, total: 9 })];
    await flushPromises();

    expect(api.get).toHaveBeenCalledWith('/api/gallery/mei/kinds');
    expect(api.get).toHaveBeenCalledWith('/api/gallery/mei/characters');
    expect(api.get).toHaveBeenCalledWith('/api/gallery/mei/origins');

    expect(api.get).toHaveBeenCalledWith(
      '/api/gallery/mei?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled',
    );

    expect(lib.kinds?.counts.unlabeled).toBe(0);
    expect(w.find('.status').exists()).toBe(false); // nothing pending any more
  });

  it('shows why the job failed', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ job_id: 'j1' });

    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path.startsWith('/api/jobs')) return [job('failed', { error: 'ModelError: download failed' })];
      if (path.endsWith('/kinds')) return kinds(3);
      if (path.endsWith('/characters')) return chars(0);
      if (path.endsWith('/origins')) return origins(0);

      return PAGE;
    });

    const { w } = mountRow({ kinds: kinds(3) });
    await button(w, 'Label now').trigger('click');
    await flushPromises();

    expect(w.text()).toContain('Labeling failed: ModelError: download failed');
  });
});

describe('LabelFilter artists row', () => {
  const GRID = '/api/gallery/mei?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled';

  it('"View Artists Tags" with the count sits after the two controls, folded by default', () => {
    const { w } = mountRow();
    const f = fold(w)!;

    expect(f).toBeTruthy();
    expect(f.find('em').text()).toBe('3');
    expect(f.attributes('aria-expanded')).toBe('false');
    expect(f.attributes('aria-controls')).toBe('artists-mei');
    expect(w.find('#artists-mei').exists()).toBe(false);
    expect(chips(w)).toHaveLength(0);
  });

  it('is absent while the gallery has no artists', () => {
    const { w } = mountRow({ artists: [] });
    expect(fold(w)).toBeUndefined();
  });

  it('opens to one chip per artist with its count, named by its handle, and remembers being open', async () => {
    const { w } = mountRow();
    await fold(w)!.trigger('click');

    expect(fold(w)!.attributes('aria-expanded')).toBe('true');
    expect(w.find('#artists-mei').exists()).toBe(true);
    expect(chips(w).map((c) => c.find('.jp').text())).toEqual(['Artist 1', 'Artist 2', 'Artist 3']);
    expect(chips(w).map((c) => c.find('em').text())).toEqual(['99', '98', '97']);
    expect(chips(w)[0]!.attributes('title')).toBe('handle1');
    expect(chips(w)[1]!.attributes('title')).toBe('id2'); // no handle: the id
    expect(chips(w).every((c) => c.attributes('aria-pressed') === 'false')).toBe(true);
    expect(localStorage.getItem('curio.gallery.artists.open')).toBe('true');

    await fold(w)!.trigger('click');
    expect(chips(w)).toHaveLength(0);
    expect(localStorage.getItem('curio.gallery.artists.open')).toBe('false');
  });

  it('comes back open for a viewer who left it open', () => {
    localStorage.setItem('curio.gallery.artists.open', 'true');
    const { w } = mountRow();

    expect(fold(w)!.attributes('aria-expanded')).toBe('true');
    expect(chips(w)).toHaveLength(3);
  });

  it('a chip narrows the grid to that artist, ANDed with the source and label; the active chip again clears it', async () => {
    localStorage.setItem('curio.gallery.artists.open', 'true');
    vi.mocked(api.get).mockResolvedValue(PAGE);
    const { w, lib } = mountRow();

    await chips(w)[1]!.trigger('click');
    await flushPromises();

    expect(lib.artist).toBe('twitter:id2');
    expect(api.get).toHaveBeenLastCalledWith(`${GRID}&artist=twitter%3Aid2`);
    expect(chips(w)[1]!.classes()).toContain('on');
    expect(chips(w)[1]!.attributes('aria-pressed')).toBe('true');
    expect(chips(w)[0]!.classes()).not.toContain('on');

    await button(w, 'X').trigger('click');
    await button(w, 'AI').trigger('click');
    await flushPromises();

    expect(api.get).toHaveBeenLastCalledWith(`${GRID}&label=ai&source=twitter&artist=twitter%3Aid2`);

    await chips(w)[0]!.trigger('click'); // another artist replaces, never adds
    await flushPromises();
    expect(lib.artist).toBe('pixiv:id1');
    expect(chips(w).map((c) => c.classes().includes('on'))).toEqual([true, false, false]);

    await chips(w)[0]!.trigger('click');
    await flushPromises();

    expect(lib.artist).toBeNull();
    expect(api.get).toHaveBeenLastCalledWith(`${GRID}&label=ai&source=twitter`);
    expect(chips(w).every((c) => c.attributes('aria-pressed') === 'false')).toBe(true);
  });

  it('shows the first 30, then "see all" unfolds the rest and "fewer" folds them back', async () => {
    localStorage.setItem('curio.gallery.artists.open', 'true');
    const many = Array.from({ length: 35 }, (_, i) => artist(i + 1));
    const { w } = mountRow({ artists: many });

    expect(chips(w)).toHaveLength(30);
    expect(fold(w)!.find('em').text()).toBe('35');
    expect(button(w, 'see all 35')).toBeTruthy();

    await button(w, 'see all 35').trigger('click');
    expect(chips(w)).toHaveLength(35);

    await button(w, 'fewer').trigger('click');
    expect(chips(w)).toHaveLength(30);
  });

  it('a short list has no "see all"', () => {
    localStorage.setItem('curio.gallery.artists.open', 'true');
    const { w } = mountRow();
    expect(w.findAll('button').map((b) => b.text())).not.toContain('see all 3');
  });

  it("By tag hides the toggle and the chips: the page's own Artists row selects there", () => {
    localStorage.setItem('curio.gallery.artists.open', 'true');
    const { w } = mountRow({ mode: 'tag' });

    expect(fold(w)).toBeUndefined();
    expect(chips(w)).toHaveLength(0);
  });
});
