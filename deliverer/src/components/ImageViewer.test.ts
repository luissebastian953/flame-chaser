import { flushPromises } from '@vue/test-utils';
import ImageViewer from './ImageViewer.vue';
import { mountWithPlugins, setTauri } from '@/test/utils';
import { useViewer } from '@/stores/viewer';
import { nextTick } from 'vue';
import type { ViewerItem } from '@/lib/related';

const opener = { openUrl: vi.fn(async () => {}), revealItemInDir: vi.fn(async () => {}) };
vi.mock('@tauri-apps/plugin-opener', () => opener);

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  mediaUrl: (sha: string, kind = 'thumb') => `http://d/${sha}/${kind}`,
}));

function item(key: string, over: Partial<ViewerItem> = {}): ViewerItem {
  return {
    key,
    sha: key,
    stored: true,
    source: 'pixiv',
    external_id: '128994201',
    idx: 0,
    page: 1,
    pages: 2,
    title: '甘雨 - 新年のご挨拶',
    artist_name: 'yuu',
    artist_handle: 'yuu_draws',
    permalink: 'https://www.pixiv.net/artworks/128994201',
    posted_at: '2026-08-21T10:00:00+00:00',
    width: 2894,
    height: 4093,
    bytes: 8_640_000,
    ext: 'png',
    path: '/lib/blobs/69/9a/sha.png',
    variant: 'original',
    linked: false,
    ...over,
  };
}

const SET = [
  item('p1'),
  item('p2', { idx: 1, page: 2 }),
  item('x', { source: 'twitter', stored: false, path: null, linked: true, pages: 1, ext: 'jpg' }),
];

async function mountViewer(items = SET, index = 0) {
  // the testing pinia exists once mounted; the store is seeded on that one
  const w = mountWithPlugins(ImageViewer, { attachTo: document.body });
  const v = useViewer();
  v.show(items, index);
  await nextTick();
  return { w, v };
}

function key(k: string) {
  window.dispatchEvent(new KeyboardEvent('keydown', { key: k, cancelable: true }));
}

describe('ImageViewer', () => {
  it('names the image, where it is from, its size, and loads the original over loopback', async () => {
    const { w } = await mountViewer();
    expect(w.text()).toContain('甘雨 - 新年のご挨拶');
    expect(w.text()).toContain('yuu_draws · pixiv · 2026-08-21 · p1 of 2');
    expect(w.text()).toContain('2894 × 4093 · 8.24 MB · PNG');
    expect(w.find('img.full').attributes('src')).toBe('http://d/p1/full');
    expect(w.find('img.ph').attributes('src')).toBe('http://d/p1/thumb'); // blurred placeholder until decoded
    expect(w.text()).toContain('1 / 3 related');
    w.unmount();
  });

  it('← → step the set, Esc closes, and the page never sees those keys', async () => {
    const { w, v } = await mountViewer();
    const page = vi.fn();
    window.addEventListener('keydown', page);
    key('ArrowRight');
    expect(v.index).toBe(1);
    key('ArrowLeft');
    key('ArrowLeft');
    expect(v.current?.key).toBe('x');
    key('Escape');
    expect(v.open).toBe(false);
    expect(page).not.toHaveBeenCalled();
    window.removeEventListener('keydown', page);
    w.unmount();
  });

  it('Space, 0 / 1 / 2 and the segment pick the zoom; a recorded copy says so', async () => {
    const { w, v } = await mountViewer(SET, 2);
    expect(w.text()).toContain('recorded only · not stored');
    expect(w.find('img.full').attributes('src')).toBe('http://d/x/full'); // the kept copy's bytes
    key(' ');
    expect(v.zoom).toBe('one');
    key('2');
    expect(v.zoom).toBe('two');
    key('0');
    expect(v.zoom).toBe('fit');
    const seg = w.findAll('.seg button');
    await seg[1]!.trigger('click');
    expect(v.zoom).toBe('one');
    w.unmount();
  });

  it('opens the permalink and reveals the file through the shell; Reveal is off for a copy that is not stored', async () => {
    setTauri(true);
    const { w, v } = await mountViewer();
    const btns = w.findAll('.top .btn');
    await btns[0]!.trigger('click');
    await flushPromises();
    expect(opener.openUrl).toHaveBeenCalledWith('https://www.pixiv.net/artworks/128994201');
    expect(btns[1]!.attributes('disabled')).toBeUndefined();
    await btns[1]!.trigger('click');
    await flushPromises();
    expect(opener.revealItemInDir).toHaveBeenCalledWith('/lib/blobs/69/9a/sha.png');
    v.go(2);
    await flushPromises();
    expect(w.findAll('.top .btn')[1]!.attributes('disabled')).toBeDefined();
    w.unmount();
  });

  it('hides the arrows and the strip for a single image', async () => {
    const { w } = await mountViewer([item('only', { pages: 1 })]);
    expect(w.find('.arrow').exists()).toBe(false);
    expect(w.find('.film').exists()).toBe(false);
    expect(w.text()).not.toContain('p1 of');
    w.unmount();
  });
});
