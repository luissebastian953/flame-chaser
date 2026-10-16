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

  return [];
}

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:any(.*)*', component: { template: '<div />' } }],
  });

  await router.push('/gallery/ganyu');
  vi.mocked(api.get).mockImplementation(async (path: string) => respond(path));
  vi.mocked(api.post).mockResolvedValue({});
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

  it('Delete asks twice, then deletes the character and goes back to the gallery', async () => {
    const { w, router } = await mountPage();

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
    const tiles = () => w.findAll('.masonry > button');

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

    await w.findAll('.masonry > button')[0]!.trigger('click');
    await flushPromises();
    expect(w.text()).toContain('Image detail');

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await flushPromises();
    expect(w.text()).not.toContain('Image detail');
  });
});
