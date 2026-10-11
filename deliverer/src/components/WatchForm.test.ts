import { flushPromises } from '@vue/test-utils';
import WatchForm from './WatchForm.vue';
import type { CharacterNames, NameSuggestion, Watch } from '@/lib/types';
import { mountWithPlugins } from '@/test/utils';
import { createMemoryHistory, createRouter } from 'vue-router';

// the form only needs useRouter() to resolve; "connect" pushes /settings in browser mode
const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/:any(.*)*', component: { template: '<div />' } }],
});

// the probe would hit the daemon on every tag change; nothing here is about it
vi.mock('@/lib/api', () => ({
  api: { post: vi.fn(async () => ({ tags: [], suggestions: [], preview: [] })) },
}));

function blank(over: Partial<Watch> = {}): Watch {
  return {
    slug: '',
    label: 'Kiana',
    pixiv_tags: ['キアナ'],
    match_terms: [],
    min_bookmarks: 0,
    include_r18: false,
    sources: ['pixiv', 'twitter'],
    target: 100,
    kind_filter: true,
    gender: 'any',
    gender_mode: 'full',
    ...over,
  };
}

function mountForm(watch = blank(), isNew = true) {
  return mountWithPlugins(WatchForm, {
    props: { watch, isNew },
    pinia: { stubActions: true },
    global: { plugins: [router] },
  });
}

const box = (w: ReturnType<typeof mountForm>, id: string) => w.find(`#${id}`);

const saveBtn = (w: ReturnType<typeof mountForm>) =>
  w.findAll('button').find((b) => b.text() === 'Save only')!;

describe('WatchForm sources', () => {
  it('starts with both sources ticked and their editors shown', () => {
    const w = mountForm();

    expect(box(w, 'src-pixiv').attributes('data-state')).toBe('checked');
    expect(box(w, 'src-twitter').attributes('data-state')).toBe('checked');
    expect(w.find('.rows').exists()).toBe(true);
    expect(w.find('.chips').exists()).toBe(true);
  });

  it('unticking X hides its editor and saves sources without it', async () => {
    const w = mountForm();

    await box(w, 'src-twitter').trigger('click');
    expect(w.find('.chips').exists()).toBe(false);
    expect(w.findAll('.sec.off')).toHaveLength(1);
    await saveBtn(w).trigger('click');
    await flushPromises();
    const [saved] = w.emitted('save')![0] as [Watch, boolean];

    expect(saved.sources).toEqual(['pixiv']);
  });

  it('refuses to save with no source ticked', async () => {
    const w = mountForm();

    await box(w, 'src-pixiv').trigger('click');
    await box(w, 'src-twitter').trigger('click');
    await saveBtn(w).trigger('click');
    expect(w.emitted('save')).toBeUndefined();
    expect(w.text()).toContain('tick at least one source');
  });

  it('X-only: pixiv tags are not required, but a match term is', async () => {
    const w = mountForm(blank({ pixiv_tags: [] }));

    await box(w, 'src-pixiv').trigger('click');
    await saveBtn(w).trigger('click');
    expect(w.emitted('save')).toBeUndefined();
    expect(w.text()).toContain('X needs at least one term');

    const w2 = mountForm(blank({ pixiv_tags: [], match_terms: ['kiana'], sources: ['twitter'] }));

    await saveBtn(w2).trigger('click');
    const [saved] = w2.emitted('save')![0] as [Watch, boolean];

    expect(saved.sources).toEqual(['twitter']);
    expect(saved.pixiv_tags).toEqual([]);
  });
});

describe('WatchForm minimum bookmarks', () => {
  it('says what it does in plain words, with a "?" for the details', () => {
    const w = mountForm();

    expect(w.text()).toContain(
      'Skip pixiv artworks saved by fewer people than this. 0 downloads everything.',
    );

    expect(w.find('button[aria-label="What does minimum bookmarks do?"]').exists()).toBe(true);
    // the label names the input, so clicking it focuses the number field
    expect(w.find('label[for="min-bookmarks"]').exists()).toBe(true);
    expect(w.find('input#min-bookmarks').exists()).toBe(true);
  });

  it('says it has no effect while pixiv is off for the character', async () => {
    const w = mountForm();

    await box(w, 'src-pixiv').trigger('click');

    expect(w.text()).toContain('pixiv is off for this character, so this has no effect.');
    expect(w.text()).not.toContain('Skip pixiv artworks saved by fewer people');
  });
});

describe('WatchForm crawl target', () => {
  const button = (w: ReturnType<typeof mountForm>, text: string) =>
    w.findAll('button').find((b) => b.text() === text)!;

  it('a preset sets posts per run, and the save button says how many it will crawl', async () => {
    const w = mountForm();

    expect(button(w, '100').attributes('aria-pressed')).toBe('true');
    await button(w, '300').trigger('click');

    expect((w.get('#posts-per-run').element as HTMLInputElement).value).toBe('300');
    expect(button(w, '300').attributes('aria-pressed')).toBe('true');
    expect(w.text()).toContain('Save & crawl 300');
  });

  it('keeps posts per run within 1–1000 and saves it with the recognition filter', async () => {
    const w = mountForm();

    await w.get('#posts-per-run').setValue('5000');
    await w.get('#posts-per-run').trigger('change');
    await box(w, 'kind-filter').trigger('click');
    expect(w.text()).toContain('off — keep every image');

    await saveBtn(w).trigger('click');
    const [saved] = w.emitted('save')![0] as [Watch, boolean];
    expect(saved.target).toBe(1000);
    expect(saved.kind_filter).toBe(false);
  });

  it('the run cycle continues after the posts a character already has', () => {
    const w = mountForm(blank({ slug: 'mei', target: 300, post_count: 36 }), false);

    const rows = w.findAll('.run-row').map((r) =>
      r
        .findAll('span')
        .map((c) => c.text())
        .join(' '),
    );

    expect(rows).toEqual([
      'run 1 posts 37–336 on save',
      'run 2 next 300 new skips run 1',
      'run 3 next 300 new skips 1–2',
    ]);

    expect(w.text()).toContain('Images per run vary — one post can hold several pages.');
  });

  it('X-only: no total to count down from, and the footer says only what is known', async () => {
    const w = mountForm(blank({ sources: ['twitter'], match_terms: ['raiden mei'], target: 300 }));

    expect(w.text()).toContain("left: X doesn't report totals");
    expect(w.text()).toContain('This run: next 300 new posts');
    expect(w.text()).not.toContain('matching');
  });

  it('with pixiv totals: what is left after this run, and how long it takes', async () => {
    vi.mocked(api.post).mockResolvedValue({
      tags: [],
      suggestions: [],
      preview: [],
      estimate: { artworks: 14509, seconds: 14509 },
    });

    const w = mountForm(blank({ target: 300 }));
    await new Promise((r) => setTimeout(r, 400)); // the probe is debounced
    await flushPromises();

    expect(w.text()).toContain('left 14,209');

    expect(w.text().replace(/\s+/g, ' ')).toContain(
      'This run: next 300 new posts of 14,509 matching · about 5 min',
    );
  });
});

describe('WatchForm name suggestions (Danbooru + Wikidata)', () => {
  const nm = (text: string, over: Partial<NameSuggestion> = {}): NameSuggestion => ({
    text,
    kind: 'name',
    lang: 'en',
    sources: ['danbooru'],
    posts: null,
    form: null,
    risky: false,
    ...over,
  });

  const MEI: CharacterNames = {
    danbooru_tag: 'raiden_mei',
    wikidata_id: 'Q136681265',
    label: 'Raiden Mei',
    suggestions: [
      nm('Raiden Mei', { sources: ['danbooru', 'wikidata'], posts: 5833 }),
      nm('雷電芽衣', { lang: 'ja', sources: ['danbooru', 'wikidata'] }),
      nm('라이덴 메이', { lang: 'ko', sources: ['wikidata'] }),
      nm('芽衣', { lang: 'cjk', risky: true }),
      ...['Thunder', 'APHO', 'Origin', 'Bladestrike', 'Crescent', 'Fulminata', 'Empress'].map((f, i) =>
        nm(`Herrscher ${f}`, { kind: 'form', posts: 1600 - i * 100, form: f }),
      ),
    ],
    errors: {},
  };

  async function mountWith(watch: Watch, names: CharacterNames = MEI, probe: object = {}) {
    vi.mocked(api.post).mockImplementation(async (path: string) =>
      path === '/api/names' ? names : { tags: [], suggestions: [], preview: [], ...probe },
    );

    const w = mountForm(watch);
    await new Promise((r) => setTimeout(r, 700)); // both lookups are debounced
    await flushPromises();

    return w;
  }

  const xOnly = () =>
    blank({ label: 'Raiden Mei', pixiv_tags: [], sources: ['twitter'], match_terms: ['raiden mei'] });

  it('works without pixiv: asks with the name first, lists names in every language', async () => {
    const w = await mountWith(xOnly());

    expect(api.post).toHaveBeenCalledWith('/api/names', { queries: ['Raiden Mei', 'raiden mei'] });
    const panel = w.get('.side-col').text();
    expect(panel).toContain('라이덴 메이');
    expect(panel).toContain('KO');
    expect(panel).toContain('雷電芽衣');
    expect(panel).toContain('short — loose as an X term'); // 芽衣
    // "Raiden Mei" is already a term (case-insensitive): not suggested again
    expect(w.findAll('.nm-row .jp').map((x) => x.text())).not.toContain('Raiden Mei');
  });

  it('offers only the sources the character uses, and adds to the right list', async () => {
    const w = await mountWith(xOnly());

    expect(w.find('button[aria-label="Add 라이덴 메이 as a pixiv tag"]').exists()).toBe(false);
    await w.get('button[aria-label="Add 라이덴 메이 as an X search term"]').trigger('click');

    expect(w.findAll('.chips .chip').map((c) => c.text().replace('✕', '').trim())).toContain('라이덴 메이');
    expect(w.findAll('.nm-row .jp').map((x) => x.text())).not.toContain('라이덴 메이');
  });

  it('forms come ranked with post counts, six at a time', async () => {
    const w = await mountWith(xOnly());
    const forms = () => w.findAll('.nm-group')[1]!.findAll('.nm-row');

    expect(forms()).toHaveLength(6);
    expect(forms()[0]!.text()).toContain('1,600 posts');
    await w.get('button.more:not(:disabled)').trigger('click');
    expect(forms()).toHaveLength(7);
  });

  it('says which source did not answer, and still shows the rest', async () => {
    const w = await mountWith(xOnly(), { ...MEI, errors: { danbooru: 'ConnectError: blocked' } });

    expect(w.text()).toContain("danbooru didn't answer — showing the rest");
    expect(w.text()).toContain('라이덴 메이');
  });

  it('with pixiv signed in, its co-occurring tags join as their own group', async () => {
    const w = await mountWith(blank({ label: 'Raiden Mei', pixiv_tags: ['雷電芽衣'] }), MEI, {
      suggestions: [
        { tag_raw: '雷電芽衣(雷の律者)', tag_norm: 'x', posts: 9, share: 0.4, characters: 1, score: 0.8 },
      ],
    });

    expect(w.text()).toContain('Co-occurring on pixiv');
    expect(w.text()).toContain('雷電芽衣(雷の律者)');
    expect(w.text()).toContain('Names');
    expect(w.find('button[aria-label="Add 라이덴 메이 as a pixiv tag"]').exists()).toBe(true);
  });
});

describe('WatchForm gender filter', () => {
  it('is saved with the character', async () => {
    const w = mountForm();

    const click = (text: string) =>
      w
        .findAll('.gender button')
        .find((b) => b.text() === text)!
        .trigger('click');

    await click('Female');
    await click('Partial');
    await saveBtn(w).trigger('click');

    const [saved] = w.emitted('save')![0] as [Watch, boolean];
    expect([saved.gender, saved.gender_mode]).toEqual(['female', 'partial']);
  });
});
