import { useViewer } from './viewer';
import type { ViewerItem } from '@/lib/related';

function item(key: string, over: Partial<ViewerItem> = {}): ViewerItem {
  return {
    key,
    sha: key,
    stored: true,
    source: 'pixiv',
    external_id: '1',
    idx: 0,
    page: 1,
    pages: 1,
    title: 't',
    artist_name: 'a',
    artist_handle: 'a',
    permalink: 'https://www.pixiv.net/artworks/1',
    posted_at: null,
    width: 100,
    height: 100,
    bytes: 1,
    ext: 'png',
    path: null,
    variant: 'original',
    linked: false,
    ...over,
  };
}

describe('viewer store', () => {
  it('opens on the given image at fit and wraps while stepping', () => {
    const v = useViewer();
    v.show([item('a'), item('b'), item('c')], 1);
    expect(v.open).toBe(true);
    expect(v.current?.key).toBe('b');
    expect(v.zoom).toBe('fit');
    v.setZoom('two');
    v.step(1);
    expect(v.current?.key).toBe('c');
    expect(v.zoom).toBe('fit'); // a new image starts at fit
    v.step(1);
    expect(v.current?.key).toBe('a');
    v.step(-1);
    expect(v.current?.key).toBe('c');
  });

  it('hands ← → to the page when the set holds one image, and lands on the right end of the next set', () => {
    const v = useViewer();
    const out = vi.fn();
    v.stepOut = out;
    v.show([item('only')]);
    v.step(-1);
    expect(out).toHaveBeenCalledWith(-1);
    expect(v.edge).toBe('last');
    v.replace([item('p1'), item('p2'), item('x', { linked: true })]);
    expect(v.index).toBe(2);
    expect(v.open).toBe(true);
    v.step(1);
    expect(out).toHaveBeenCalledTimes(1); // three images: stepping stays inside
    expect(v.current?.key).toBe('p1');
  });

  it('toggles fit and 1:1 with Space, and clamps the index', () => {
    const v = useViewer();
    v.show([item('a'), item('b')], 9);
    expect(v.index).toBe(1);
    v.toggleZoom();
    expect(v.zoom).toBe('one');
    v.toggleZoom();
    expect(v.zoom).toBe('fit');
    v.go(5);
    expect(v.index).toBe(1);
    v.close();
    expect(v.open).toBe(false);
  });
});
