import { flushPromises } from '@vue/test-utils';
import DetailAside from './DetailAside.vue';
import { mountWithPlugins, setTauri } from '@/test/utils';
import { useViewer } from '@/stores/viewer';
import type { PostDetail, PostMedia } from '@/lib/types';

const opener = { openUrl: vi.fn(async () => {}), revealItemInDir: vi.fn(async () => {}) };
vi.mock('@tauri-apps/plugin-opener', () => opener);

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  mediaUrl: (sha: string, kind = 'thumb') => `http://d/${sha}/${kind}`,
}));

function media(over: Partial<PostMedia> & { idx: number }): PostMedia {
  return {
    sha256: `sha${over.idx}`,
    state: 'stored',
    dupe_of: null,
    width: 2894,
    height: 4093,
    bytes: 8_640_000,
    ext: 'png',
    path: `/lib/blobs/69/9a/sha${over.idx}.png`,
    source_variant: 'original',
    identity: null,
    ...over,
  };
}

function post(over: Partial<PostDetail> = {}): PostDetail {
  return {
    source: 'pixiv',
    external_id: '128994201',
    artist_id: '77',
    artist_name: 'yuu_draws',
    artist_handle: 'yuu_draws',
    title: '甘雨 - 新年のご挨拶',
    caption: '',
    posted_at: '2026-08-21T10:00:00+00:00',
    permalink: 'https://www.pixiv.net/artworks/128994201',
    bookmark_count: 4182,
    state: 'live',
    source_meta: '{}',
    media: [media({ idx: 0 }), media({ idx: 1 })],
    tags: [{ tag_raw: '甘雨', tag_norm: '甘雨', translated: 'Ganyu' }],
    linked: [
      {
        source: 'twitter',
        external_id: '1958871220337',
        artist_handle: 'yuu_draws',
        artist_name: 'yuu',
        title: 'new year',
        permalink: 'https://x.com/yuu_draws/status/1958871220337',
        posted_at: '2026-08-21T11:00:00+00:00',
        reason: 'phash d=2',
        media: [
          media({ idx: 0, state: 'dupe', sha256: 'xcopy', dupe_of: 'sha0', path: null, ext: 'jpg' }),
          media({ idx: 1, sha256: 'x1', ext: 'jpg', source_variant: 'orig', width: 1536, height: 2048 }),
          media({ idx: 2, sha256: 'x2', ext: 'jpg', source_variant: 'orig' }),
        ],
      },
    ],
    ...over,
  };
}

function mountAside(p = post()) {
  return mountWithPlugins(DetailAside, { props: { post: p }, attachTo: document.body });
}

function key(k: string) {
  window.dispatchEvent(new KeyboardEvent('keydown', { key: k, cancelable: true }));
}

describe('DetailAside', () => {
  it('shows the first page with its counter and size, the pages then the X thread in the strip', () => {
    const w = mountAside();
    expect(w.find('.art img').attributes('src')).toBe('http://d/sha0/thumb');
    expect(w.find('.badge.pages').text()).toBe('1 / 2');
    expect(w.find('.badge.dims').text()).toContain('2894 × 4093');
    expect(w.text()).toContain('Related images');
    expect(w.text()).toContain('same post · 128994201 · 2 pages');
    expect(w.text()).toContain('+ 3 from @yuu_draws on X');
    const tiles = w.findAll('.strip .tile');
    expect(tiles).toHaveLength(5);
    expect(tiles.map((t) => t.text())).toEqual(['p1', 'p2', 'X', 'X', 'X']);
    expect(tiles[0]!.classes()).toContain('cur');
    expect(w.find('.strip .div').exists()).toBe(true);
    expect(w.text()).toContain('8.24 MB · PNG');
    expect(w.text()).toContain('blobs/69/9a/');
    expect(w.text()).toContain('Same image on X');
    expect(w.text()).toContain('phash d=2');
    expect(w.text()).toContain('Kept the pixiv original; the X copy is recorded, not stored.');
    w.unmount();
  });

  it('a tile click or ← → switches the panel to that image', async () => {
    const w = mountAside();
    await w.findAll('.strip .tile')[3]!.trigger('click');
    expect(w.find('.art img').attributes('src')).toBe('http://d/x1/thumb');
    expect(w.find('.badge.dims').text()).toContain('1536 × 2048');
    expect(w.text()).toContain('Open on X');
    expect(w.text()).toContain('new year');
    expect(w.find('.badge.pages').text()).toBe('2 / 3'); // the X thread's three images
    key('ArrowLeft');
    await flushPromises();
    expect(w.find('.art img').attributes('src')).toBe('http://d/sha0/thumb'); // the recorded copy shows the kept bytes
    expect(w.find('.badge.pages').text()).toBe('1 / 3');
    expect(w.text()).toContain('not stored');
    key('ArrowLeft');
    await flushPromises();
    expect(w.find('.badge.pages').text()).toBe('2 / 2');
    w.unmount();
  });

  it('F, the preview and the header button open the viewer on the current image; the viewer moves the panel', async () => {
    const w = mountAside();
    const v = useViewer();
    key('f');
    expect(v.open).toBe(true);
    expect(v.items).toHaveLength(5);
    expect(v.index).toBe(0);
    v.step(1);
    await flushPromises();
    expect(w.findAll('.strip .tile')[1]!.classes()).toContain('cur');
    v.close();
    await w.find('.art').trigger('click');
    expect(v.open).toBe(true);
    expect(v.index).toBe(1);
    w.unmount();
  });

  it('Reveal shows the blob in the desktop app and is disabled in the browser or for a copy that is not stored', async () => {
    setTauri(true);
    const w = mountAside();
    const reveal = w.findAll('.actions .btn')[1]!;
    expect(reveal.attributes('disabled')).toBeUndefined();
    await reveal.trigger('click');
    await flushPromises();
    expect(opener.revealItemInDir).toHaveBeenCalledWith('/lib/blobs/69/9a/sha0.png');
    await w.findAll('.strip .tile')[2]!.trigger('click');
    expect(w.findAll('.actions .btn')[1]!.attributes('disabled')).toBeDefined();
    w.unmount();

    setTauri(false);
    const b = mountAside();
    expect(b.findAll('.actions .btn')[1]!.attributes('disabled')).toBeDefined();
    expect(b.findAll('.actions .btn')[1]!.attributes('title')).toBe('Reveal needs the desktop app');
    b.unmount();
  });

  it('a single stored image: no counter, no strip, and the linked card is absent', () => {
    const w = mountAside(post({ media: [media({ idx: 0 })], linked: [] }));
    expect(w.find('.badge.pages').exists()).toBe(false);
    expect(w.find('.related').exists()).toBe(false);
    expect(w.find('.linked').exists()).toBe(false);
    expect(w.text()).toContain('4182'); // bookmarks stay for the pixiv post
    w.unmount();
  });

  it('× emits close', async () => {
    const w = mountAside();
    await w.find('[aria-label="Close"]').trigger('click');
    expect(w.emitted('close')).toHaveLength(1);
    w.unmount();
  });
});
