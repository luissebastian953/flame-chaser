import type { GalleryItem, GalleryPage, Watch } from '@/lib/types';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

function watch(slug: string, post_count?: number): Watch {
  return {
    slug,
    label: slug,
    pixiv_tags: [],
    match_terms: [],
    min_bookmarks: 0,
    include_r18: false,
    post_count,
  };
}

function item(sha256: string): GalleryItem {
  return {
    sha256,
    source: 'pixiv',
    external_id: sha256,
    idx: 0,
    width: 1,
    height: 1,
    posted_at: null,
    artist_name: 'a',
    title: 't',
    thumb_url: '',
  };
}

function page(items: string[], next_cursor: string | null): GalleryPage {
  return { items: items.map(item), next_cursor };
}

describe('useLibrary getters', () => {
  it('totalPosts sums post_count, treating missing as 0', () => {
    const lib = useLibrary();

    expect(lib.totalPosts).toBe(0);
    lib.watches = [watch('a', 12), watch('b'), watch('c', 30)];
    expect(lib.totalPosts).toBe(42);
  });
});

describe('useLibrary watches', () => {
  it('saveWatch() posts a new watch and patches an existing one, then reloads', async () => {
    vi.mocked(api.post).mockResolvedValueOnce(watch('new'));
    vi.mocked(api.patch).mockResolvedValueOnce(watch('old'));
    vi.mocked(api.get).mockResolvedValue([watch('new', 1), watch('old', 2)]);
    const lib = useLibrary();

    await lib.saveWatch(watch('new'), true);
    expect(api.post).toHaveBeenCalledWith('/api/watches', watch('new'));

    await lib.saveWatch(watch('old'), false);
    expect(api.patch).toHaveBeenCalledWith('/api/watches/old', watch('old'));

    expect(api.get).toHaveBeenCalledWith('/api/watches');
    expect(lib.totalPosts).toBe(3);
  });

  it('deleteWatch() deletes then reloads', async () => {
    vi.mocked(api.del).mockResolvedValueOnce(undefined);
    vi.mocked(api.get).mockResolvedValueOnce([]);
    const lib = useLibrary();
    lib.watches = [watch('gone', 5)];
    await lib.deleteWatch('gone');

    expect(api.del).toHaveBeenCalledWith('/api/watches/gone');
    expect(lib.watches).toEqual([]);
  });

  it('tagAction() posts the action then refreshes tags and watches together', async () => {
    vi.mocked(api.post).mockResolvedValueOnce(undefined);
    vi.mocked(api.get).mockImplementation(async (path: string) => (path.endsWith('/tags') ? [] : []));
    await useLibrary().tagAction('kiana', '空の律者', 'watch');

    expect(api.post).toHaveBeenCalledWith('/api/watches/kiana/tags', { tag: '空の律者', action: 'watch' });
    expect(api.get).toHaveBeenCalledWith('/api/gallery/kiana/tags');
    expect(api.get).toHaveBeenCalledWith('/api/watches');
  });
});

describe('useLibrary loadGrid() keyset paging', () => {
  it('starts without a cursor and carries the daemon cursor into the next page', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce(page(['a', 'b'], 'c1'))
      .mockResolvedValueOnce(page(['c'], null));

    const lib = useLibrary();

    await lib.loadGrid('kiana');
    expect(api.get).toHaveBeenLastCalledWith('/api/gallery/kiana?limit=120');
    expect(lib.grid).toMatchObject({ slug: 'kiana', cursor: 'c1', done: false });
    expect(lib.grid.items.map((i) => i.sha256)).toEqual(['a', 'b']);

    await lib.loadGrid('kiana');
    expect(api.get).toHaveBeenLastCalledWith('/api/gallery/kiana?limit=120&cursor=c1');
    expect(lib.grid.items.map((i) => i.sha256)).toEqual(['a', 'b', 'c']);
    expect(lib.grid).toMatchObject({ cursor: null, done: true });
  });

  it('stops fetching once the last page was seen', async () => {
    vi.mocked(api.get).mockResolvedValueOnce(page(['a'], null));
    const lib = useLibrary();
    await lib.loadGrid('kiana');
    await lib.loadGrid('kiana');
    await lib.loadGrid('kiana');

    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('passes the cursor through opaque and URL-encoded', async () => {
    vi.mocked(api.get).mockResolvedValueOnce(page([], 'k=1&x/y')).mockResolvedValueOnce(page([], null));
    const lib = useLibrary();
    await lib.loadGrid('s');
    await lib.loadGrid('s');

    expect(api.get).toHaveBeenLastCalledWith('/api/gallery/s?limit=120&cursor=k%3D1%26x%2Fy');
  });

  it('starts over for a different slug or with reset=true', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce(page(['a'], 'c1'))
      .mockResolvedValueOnce(page(['z'], null))
      .mockResolvedValueOnce(page(['a2'], 'c2'));

    const lib = useLibrary();
    await lib.loadGrid('one');
    await lib.loadGrid('two');

    expect(api.get).toHaveBeenLastCalledWith('/api/gallery/two?limit=120');
    expect(lib.grid.items.map((i) => i.sha256)).toEqual(['z']);
    expect(lib.grid.done).toBe(true);

    await lib.loadGrid('two', true);
    expect(api.get).toHaveBeenLastCalledWith('/api/gallery/two?limit=120');
    expect(lib.grid).toMatchObject({ slug: 'two', cursor: 'c2', done: false });
    expect(lib.grid.items.map((i) => i.sha256)).toEqual(['a2']);
  });
});

describe('useLibrary detail', () => {
  it('openDetail() fetches the post and closeDetail() clears it', async () => {
    const detail = { source: 'pixiv', external_id: '1', title: 'x' };
    vi.mocked(api.get).mockResolvedValueOnce(detail);
    const lib = useLibrary();
    await lib.openDetail('pixiv', '1');

    expect(api.get).toHaveBeenCalledWith('/api/posts/pixiv/1');
    expect(lib.detail).toMatchObject(detail);
    lib.closeDetail();
    expect(lib.detail).toBeNull();
  });
});
