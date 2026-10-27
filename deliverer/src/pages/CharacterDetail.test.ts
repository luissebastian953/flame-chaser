import { flushPromises } from '@vue/test-utils';
import CharacterDetail from './CharacterDetail.vue';
import type { GalleryItem, PostDetail, TagStat, Watch } from '@/lib/types';
import { mountWithPlugins } from '@/test/utils';
import { createMemoryHistory, createRouter } from 'vue-router';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
  mediaUrl: (sha: string) => `/media/${sha}`,
}));

const ganyu: Watch = {
  slug: 'ganyu',
  label: 'Ganyu',
  pixiv_tags: ['甘雨'],
  match_terms: [],
  min_bookmarks: 0,
  include_r18: false,
  sources: ['pixiv', 'twitter'],
  target: 100,
  kind_filter: true,
  gender: 'any',
  gender_mode: 'full',
  post_count: 412,
  artist_count: 61,
};

function item(external_id: string, source: string): GalleryItem {
  return {
    sha256: `sha${external_id}`,
    source,
    external_id,
    idx: 0,
    width: 3,
    height: 4,
    posted_at: null,
    artist_name: 'a',
    title: 't',
    thumb_url: '',
    kind: 'illustration',
    identity: 'pending',
  };
}

function tag(tag_raw: string, state: TagStat['state'], share: number): TagStat {
  return {
    slug: 'ganyu',
    tag_norm: tag_raw,
    tag_raw,
    translated: null,
    posts: 1,
    share,
    characters: 1,
    score: 1,
    state,
  };
}

const detail: PostDetail = {
  source: 'twitter',
  external_id: '2',
  artist_id: 'a',
  artist_name: 'yuu_draws',
  artist_handle: 'yuu_draws',
  title: 'new year',
  caption: '',
  posted_at: '2026-08-21T10:00:00+00:00',
  permalink: 'https://x.com/yuu_draws/status/2',
  bookmark_count: 0,
  state: 'live',
  source_meta: '{}',
  media: [],
  tags: [],
  linked: [],
};

function respond(path: string) {
  if (path.startsWith('/api/gallery/ganyu?'))
    return { items: [item('1', 'pixiv'), item('2', 'twitter')], next_cursor: null };
  if (path === '/api/gallery/ganyu/tags')
    return [
      tag('甘雨', 'watched', 0.98),
      tag('甘雨(飛花逐月)', 'suggested', 0.23),
      tag('原神', 'ignored', 1),
    ];
  if (path === '/api/gallery/ganyu/kinds')
    return {
      counts: { illustration: 1200, screencap: 80, unlabeled: 4, photo: 9, render: 0, other: 0 },
      labeler: { available: true, models: true },
    };
  if (path === '/api/gallery/ganyu/characters')
    return {
      counts: { identified: 0, unidentified: 0, pending: 0 },
      characters: [],
      identifier: { enabled: true, available: true, models: true },
    };
  if (path.startsWith('/api/posts/')) return detail;
  if (path.startsWith('/api/gallery/ganyu/images?')) {
    // By tag: the daemon's list for one term, filtered like the grid
    return path.includes('tag=')
      ? { shas: ['sha2'], sources: { sha2: 'twitter' } }
      : { shas: ['sha1', 'sha2'], sources: { sha1: 'pixiv', sha2: 'twitter' } };
  }
  if (path === '/api/gallery/ganyu/artists')
    return [{ source: 'pixiv', artist_id: 'a', name: 'Alpha', handle: '', count: 2 }];
  if (path === '/api/trash') return { count: 0, bytes: 0, oldest: null, days: 30 };

  return [];
}

const preview = {
  images: 1,
  bytes: 2 * 1024 * 1024,
  by_source: { pixiv: 1 },
  posts: { touched: 1, keep_other: 0, forget: 1 },
  shared: 0,
  whole: false,
  forced_trash: false,
  trash: { count: 0, bytes: 0, oldest: null, days: 30 },
};

function respondPost(path: string, body: unknown) {
  if (path.endsWith('/smart'))
    return {
      matches: [
        { sha256: 'sha2', reasons: [{ kind: 'score', score: 0.31 }] },
        { sha256: 'sha1', reasons: [{ kind: 'score', score: 0.4 }] },
      ],
      counts: { score: 2, other: 0, dupe: 0, unidentified: 0 },
      primary: 'ganyu',
      primary_label: 'Ganyu',
      characters: [],
      total: 2,
      cutoff: 0.5,
      rule: null,
      identifier: { enabled: true },
    };
  if (path.endsWith('/delete/preview')) {
    const shas = (body as { shas: string[] }).shas;
    return { ...preview, images: shas.length, whole: shas.length >= 2 };
  }
  if (path.endsWith('/delete'))
    return {
      batch_id: 'b1',
      images: (body as { shas: string[] }).shas.length,
      bytes: 1,
      forgotten: 1,
      permanent: false,
    };
  return {};
}

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:any(.*)*', component: { template: '<div />' } }],
  });

  await router.push('/gallery/ganyu');
  vi.mocked(api.get).mockImplementation(async (path: string) => respond(path));
  vi.mocked(api.post).mockImplementation(async (path: string, body?: unknown) => respondPost(path, body));
  vi.mocked(api.del).mockResolvedValue(undefined);

  const w = mountWithPlugins(CharacterDetail, {
    props: { slug: 'ganyu' },
    global: { plugins: [router] },
    pinia: { initialState: { library: { watches: [ganyu] } } },
  });

  await flushPromises();

  return { w, router };
}

type Page = Awaited<ReturnType<typeof mountPage>>['w'];

const button = (w: Page, text: string) => w.findAll('button').find((b) => b.text() === text)!;

describe('CharacterDetail header', () => {
  it('counts what the grid can hold (the kept kinds) and the posts', async () => {
    const { w } = await mountPage();

    // 1200 illustrations + 80 screencaps + 4 not labeled; photos are not kept
    expect(w.text()).toContain('1,284 images · 412 posts · 61 artists');
  });

  it('the source filter narrows the grid to one source and back', async () => {
    const { w } = await mountPage();

    await button(w, 'X').trigger('click');
    await flushPromises();
    expect(vi.mocked(api.get).mock.lastCall?.[0]).toMatch(/^\/api\/gallery\/ganyu\?.*&source=twitter$/);
    expect(button(w, 'X').attributes('aria-pressed')).toBe('true');

    await button(w, 'All').trigger('click');
    await flushPromises();
    expect(vi.mocked(api.get).mock.lastCall?.[0]).not.toContain('source=');
  });

  it('Delete character (in the more menu) asks twice, then deletes it and goes back to the gallery', async () => {
    const { w, router } = await mountPage();

    await w.find('[aria-label="More"]').trigger('click');
    await button(w, 'Delete character').trigger('click');
    expect(api.del).not.toHaveBeenCalled();

    await button(w, 'Click again to delete').trigger('click');
    await flushPromises();
    expect(api.del).toHaveBeenCalledWith('/api/watches/ganyu');
    expect(router.currentRoute.value.path).toBe('/gallery');
  });
});

describe('CharacterDetail observed tags', () => {
  it('watched tags say so, suggestions offer watch / ignore, ignored tags are marked', async () => {
    const { w } = await mountPage();
    const chips = w.findAll('.tags > span');

    // name · share · state, one chip per tag in that order
    expect(chips.map((c) => c.text().replace(/\s+/g, ''))).toEqual([
      '甘雨98%watching',
      '甘雨(飛花逐月)23%watchignore',
      '原神100%ignored',
    ]);

    expect(w.text()).toContain('what these 412 posts are actually tagged with');

    await button(w, 'watch').trigger('click');
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith('/api/watches/ganyu/tags', {
      tag: '甘雨(飛花逐月)',
      action: 'watch',
    });
  });
});

describe('CharacterDetail image aside', () => {
  it('a clicked tile is marked current and opens the aside; the backdrop closes it', async () => {
    const { w } = await mountPage();
    const tiles = () => w.findAll('.masonry button.tile');

    await tiles()[1]!.trigger('click');
    await flushPromises();
    expect(api.get).toHaveBeenCalledWith('/api/posts/twitter/2');
    expect(tiles().map((t) => t.attributes('aria-current'))).toEqual([undefined, 'true']);
    expect(w.text()).toContain('Image detail');

    await w.find('.scrim').trigger('click');
    expect(w.text()).not.toContain('Image detail');
    expect(tiles()[1]!.attributes('aria-current')).toBeUndefined();
  });

  it('Esc closes the aside', async () => {
    const { w } = await mountPage();

    await w.findAll('.masonry button.tile')[0]!.trigger('click');
    await flushPromises();
    expect(w.text()).toContain('Image detail');

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await flushPromises();
    expect(w.text()).not.toContain('Image detail');
  });
});

describe('CharacterDetail deleting images', () => {
  const tiles = (w: Page) => w.findAll('.masonry button.tile');

  async function pickMode(w: Page, title: string) {
    await button(w, 'Delete').trigger('click');
    expect(w.text()).toContain('pick how to choose them');

    await w
      .findAll('.picker button.row')
      .find((b) => b.text().includes(title))!
      .trigger('click');

    await flushPromises();
  }

  it('By image: the bar replaces the header, tiles mark on click, Delete opens the sheet, confirm posts the set and toasts Undo', async () => {
    const { w } = await mountPage();
    await pickMode(w, 'By image');

    // the header is gone, the bar and its hint are here
    expect(w.find('.selbar').exists()).toBe(true);
    expect(w.text()).toContain('0 selected');
    expect(w.text()).toContain('marks all visible');

    await tiles(w)[0]!.trigger('click');
    expect(api.get).not.toHaveBeenCalledWith('/api/posts/pixiv/1'); // no aside in select mode
    expect(tiles(w)[0]!.attributes('aria-pressed')).toBe('true');
    expect(w.text()).toContain('1 selected');
    expect(w.text()).not.toContain('marks all visible'); // the hint collapsed

    await button(w, 'Delete 1').trigger('click');
    await flushPromises();
    expect(api.post).toHaveBeenCalledWith('/api/gallery/ganyu/delete/preview', { shas: ['sha1'] });
    expect(w.text()).toContain('Delete 1 image');
    expect(w.text()).toContain('Ganyu · picked by hand · 2 MiB');
    expect(w.text()).toContain('Forget the post');

    await button(w, 'Move 1 to trash').trigger('click');
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith('/api/gallery/ganyu/delete', {
      shas: ['sha1'],
      mode: 'image',
      trash: true,
      forget: true,
      confirm: undefined,
    });

    // back to the header; the toast offers Undo
    expect(w.find('.selbar').exists()).toBe(false);
    const toasts = useToasts();
    expect(toasts.items.map((t) => t.kind)).toEqual(['delete']);
    const toast = toasts.items[0] as { batchId: string; undo: () => Promise<void> };
    expect(toast.batchId).toBe('b1');
    await toast.undo();
    expect(api.post).toHaveBeenCalledWith('/api/trash/b1/restore');
  });

  it('Esc leaves silently with nothing marked and asks for a second Esc with a selection', async () => {
    const { w } = await mountPage();
    await pickMode(w, 'By image');
    const clear = () => w.findAll('.selbar button').find((b) => b.text() === 'Clear')!;
    expect(clear().attributes('disabled')).toBeDefined(); // nothing to clear yet
    await tiles(w)[1]!.trigger('click');
    expect(w.text()).toContain('1 selected');
    expect(clear().attributes('disabled')).toBeUndefined();

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await flushPromises();
    expect(w.text()).toContain('Esc again');
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await flushPromises();
    expect(w.find('.selbar').exists()).toBe(false);

    await pickMode(w, 'By image');
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await flushPromises();
    expect(w.find('.selbar').exists()).toBe(false);
  });

  it('By tag: a chip marks every image carrying it through the daemon, the strip shows the arithmetic, a tile click drops one', async () => {
    const { w } = await mountPage();
    await pickMode(w, 'By tag');
    expect(api.get).toHaveBeenCalledWith('/api/gallery/ganyu/artists');
    expect(w.text()).toContain('Artists');

    await w
      .findAll('.tags button.chip')
      .find((b) => b.text().includes('原神'))!
      .trigger('click');

    await flushPromises();

    expect(vi.mocked(api.get).mock.lastCall?.[0]).toMatch(
      /^\/api\/gallery\/ganyu\/images\?kinds=.*&tag=%E5%8E%9F%E7%A5%9E$/,
    );

    expect(w.text()).toContain('1 selected');
    expect(w.text()).toContain('by 1 tag · pixiv 0 · X 1');
    expect(w.text()).toContain('原神 1 = 1 images · 0 overlap · −0 excluded');
    // the chip's images lead the grid; the chip itself stays where its row puts it
    expect(tiles(w)[0]!.attributes('data-sha')).toBe('sha2');
    expect(tiles(w)[0]!.attributes('aria-pressed')).toBe('true');
    expect(tiles(w)[1]!.attributes('data-sha')).toBe('sha1');
    expect(tiles(w)[1]!.classes()).toContain('ex'); // not a candidate
    expect(w.findAll('.tags button.chip')[0]!.text()).toContain('甘雨');
    expect(w.findAll('.tags button.chip')[2]!.text()).toContain('原神');

    await tiles(w)[0]!.trigger('click'); // kept back out
    expect(w.text()).toContain('0 selected');
    expect(w.text()).toContain('−1 excluded');

    // the Show / Who / Characters rows select too, instead of filtering
    const screencaps = w.findAll('button.chip').find((b) => b.text().includes('Anime screencaps'))!;
    await screencaps.trigger('click');
    await flushPromises();
    expect(vi.mocked(api.get).mock.lastCall?.[0]).toMatch(/\/images\?.*sel_kind=screencap$/);
    expect(screencaps.classes()).toContain('sel');
    expect(w.text()).toContain('2 − 1 = 1'); // two chips' images, one kept back out
  });

  it('All: everything is marked, the sheet needs the name typed, and forgetting posts is off by default', async () => {
    const { w } = await mountPage();
    await pickMode(w, 'All');
    expect(w.text()).toContain('2 selected');
    expect(w.text()).toContain('everything · pixiv 1 · X 1');

    await button(w, 'Delete 2').trigger('click');
    await flushPromises();
    expect(w.text()).toContain('Delete all 2 images');
    expect(w.text()).toContain('Ganyu stays watched');
    const go = button(w, 'Move 2 to trash');
    expect(go.attributes('disabled')).toBeDefined();

    await w.find('.sheet input').setValue('Ganyu');
    expect(button(w, 'Move 2 to trash').attributes('disabled')).toBeUndefined();
    await button(w, 'Move 2 to trash').trigger('click');
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith('/api/gallery/ganyu/delete', {
      shas: ['sha1', 'sha2'],
      mode: 'all',
      trash: true,
      forget: false,
      confirm: 'Ganyu',
    });
  });

  it('?delete=smart opens Smart with the criteria panel; matches are pre-checked with their score', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/:any(.*)*', component: { template: '<div />' } }],
    });

    await router.push('/gallery/ganyu?delete=smart');
    vi.mocked(api.get).mockImplementation(async (path: string) => respond(path));
    vi.mocked(api.post).mockImplementation(async (path: string, body?: unknown) => respondPost(path, body));

    const w = mountWithPlugins(CharacterDetail, {
      props: { slug: 'ganyu' },
      global: { plugins: [router] },
      pinia: { initialState: { library: { watches: [ganyu] } } },
    });

    await flushPromises();
    expect(w.text()).toContain('Criteria');
    expect(w.text()).toContain('Not Ganyu');
    expect(w.text()).toContain('Matches · 2');
    expect(w.text()).toContain('2 selected');
    const matches = () => w.findAll('.masonry.four .tile');
    expect(matches().map((m) => m.attributes('data-sha'))).toEqual(['sha2', 'sha1']); // lowest score first
    expect(matches()[0]!.find('.badge').text()).toBe('0.31');

    // a tile kept back out sinks to the end of the matches, the marked one leads
    await matches()[0]!.trigger('click');
    expect(w.text()).toContain('1 selected');
    expect(matches().map((m) => m.attributes('data-sha'))).toEqual(['sha1', 'sha2']);
  });
});
