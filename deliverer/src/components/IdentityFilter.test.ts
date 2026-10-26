import { flushPromises } from '@vue/test-utils';
import IdentityFilter from './IdentityFilter.vue';
import type { GalleryCharacters, Job } from '@/lib/types';
import { mountWithPlugins } from '@/test/utils';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn() },
}));

function chars(
  over: Partial<GalleryCharacters['counts']> = {},
  characters: GalleryCharacters['characters'] = [
    { name: 'raiden_mei', label: 'Raiden Mei', count: 80 },
    { name: 'kiana_kaslana', label: 'Kiana Kaslana', count: 11 },
  ],
  identifier = { enabled: true, available: true, models: true },
) {
  return {
    counts: { identified: 91, unidentified: 6, pending: 0, ...over },
    characters,
    identifier,
  } satisfies GalleryCharacters;
}

function job(state: Job['state'], over: Partial<Job> = {}): Job {
  return {
    id: 'j1',
    type: 'label',
    params: {},
    state,
    stage: 'identify',
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

function mountFilter(c: GalleryCharacters | null) {
  const w = mountWithPlugins(IdentityFilter, {
    props: { slug: 'mei' },
    pinia: { initialState: { library: { characters: c } } },
  });

  return { w, lib: useLibrary(), jobs: useJobs() };
}

type W = ReturnType<typeof mountFilter>['w'];

const chip = (w: W, text: string) => w.findAll('button.chip').find((b) => b.text().startsWith(text))!;
const button = (w: W, text: string) => w.findAll('button').find((b) => b.text() === text);

describe('IdentityFilter chips', () => {
  it('shows identified and unidentified with counts, all on, and a chip per character', () => {
    const { w } = mountFilter(chars());

    expect(w.findAll('button.chip').map((b) => b.text())).toEqual([
      'Identified 91',
      'Unidentified 6',
      'Raiden Mei 80',
      'Kiana Kaslana 11',
    ]);

    expect(chip(w, 'Identified').attributes('aria-pressed')).toBe('true');
    expect(chip(w, 'Raiden Mei').attributes('aria-pressed')).toBe('false');
  });

  it('adds "Not identified yet" only while something is', () => {
    const { w } = mountFilter(chars({ pending: 4 }));

    expect(chip(w, 'Not identified yet').text()).toBe('Not identified yet 4');
  });

  it('switching "Identified" off reloads the grid with only the unidentified', async () => {
    vi.mocked(api.get).mockResolvedValue({ items: [], next_cursor: null });
    const { w, lib } = mountFilter(chars());

    await chip(w, 'Identified').trigger('click');
    await flushPromises();

    expect(lib.who).toEqual(['unidentified', 'pending']);

    expect(api.get).toHaveBeenLastCalledWith(
      expect.stringMatching(/^\/api\/gallery\/mei\?.*ident=unidentified%2Cpending/),
    );
  });

  it('will not switch off the last state', async () => {
    const { w, lib } = mountFilter(chars());
    lib.who = ['identified'];

    await chip(w, 'Identified').trigger('click');

    expect(lib.who).toEqual(['identified']);
    expect(api.get).not.toHaveBeenCalled();
  });

  it('a character chip narrows the grid to it; clicking again shows everyone', async () => {
    vi.mocked(api.get).mockResolvedValue({ items: [], next_cursor: null });
    const { w, lib } = mountFilter(chars());

    await chip(w, 'Kiana Kaslana').trigger('click');
    await flushPromises();

    expect(lib.character).toBe('kiana_kaslana');
    const url = vi.mocked(api.get).mock.lastCall![0] as string;
    expect(url).toContain('character=kiana_kaslana');
    expect(url).not.toContain('ident='); // the character replaces the state choice
    expect(chip(w, 'Kiana Kaslana').attributes('aria-pressed')).toBe('true');
    expect(chip(w, 'Identified').attributes('aria-pressed')).toBe('false');

    await chip(w, 'Kiana Kaslana').trigger('click');
    await flushPromises();
    expect(lib.character).toBeNull();
  });

  it('folds a long cast behind "+N more"', async () => {
    const many = Array.from({ length: 11 }, (_, i) => ({ name: `c${i}`, label: `C${i}`, count: 20 - i }));
    const { w } = mountFilter(chars({}, many));

    expect(w.findAll('button.chip')).toHaveLength(2 + 8);
    await button(w, '+3 more')!.trigger('click');
    expect(w.findAll('button.chip')).toHaveLength(2 + 11);
    expect(button(w, 'fewer')).toBeTruthy();
  });

  it('By tag shows the whole cast in place, the picked character marked where it stands', () => {
    const many = Array.from({ length: 10 }, (_, i) => ({ name: `c${i}`, label: `C${i}`, count: 20 - i }));

    const w = mountWithPlugins(IdentityFilter, {
      props: { slug: 'mei' },
      pinia: {
        initialState: {
          library: { characters: chars({}, many) },
          deletion: {
            mode: 'tag',
            terms: [{ key: 'character:c9', kind: 'character', value: 'c9', label: 'C9', shas: [] }],
          },
        },
      },
    });

    const cast = w.findAll('button.chip.pick').filter((b) => /^C\d/.test(b.text()));
    expect(cast).toHaveLength(10);
    expect(cast[0]!.text()).toMatch(/^C0/);
    expect(cast[0]!.classes()).not.toContain('sel');
    expect(cast[9]!.text()).toMatch(/^C9/);
    expect(cast[9]!.classes()).toContain('sel');
  });
});

describe('IdentityFilter backlog', () => {
  it('offers to identify images stored before names existed, and says nothing is removed', () => {
    const { w } = mountFilter(chars({ pending: 3 }, [], { enabled: true, available: true, models: false }));

    expect(button(w, 'Identify 3 images')).toBeTruthy();
    expect(w.text()).toContain('nothing is removed');
    expect(w.text()).toContain('downloads two character taggers');
  });

  it('points to Settings when names are switched off, instead of a button', () => {
    const { w } = mountFilter(chars({ pending: 3 }, [], { enabled: false, available: true, models: true }));

    expect(w.text()).toContain('Settings › Characters');
    expect(w.findAll('button.btn')).toHaveLength(0);
  });

  it('says how to install the classifier when it is missing', () => {
    const { w } = mountFilter(chars({ pending: 3 }, [], { enabled: true, available: false, models: false }));

    expect(w.text()).toContain("not installed (pip install 'reaver[classify]')");
    expect(w.findAll('button.btn')).toHaveLength(0);
  });

  it('submits the label job, shows progress, then recounts and redraws when it ends', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ job_id: 'j1' });

    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path.startsWith('/api/jobs')) return [job('running', { done: 2, total: 5 })];
      if (path.endsWith('/characters')) return chars();

      return { items: [], next_cursor: null };
    });

    const { w, jobs, lib } = mountFilter(chars({ pending: 5 }));

    await button(w, 'Identify 5 images')!.trigger('click');
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith('/api/jobs', { type: 'label', params: {} });
    expect(w.text()).toContain('Identifying… 2 / 5');

    jobs.jobs = [job('succeeded', { done: 5, total: 5 })];
    await flushPromises();

    expect(api.get).toHaveBeenCalledWith('/api/gallery/mei/characters');
    expect(lib.characters?.counts.pending).toBe(0);
    expect(w.findAll('button.btn')).toHaveLength(0);
  });
});
