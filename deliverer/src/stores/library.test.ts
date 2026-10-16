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
    sources: ['pixiv', 'twitter'],
    target: 100,
    kind_filter: true,
    gender: 'any',
    gender_mode: 'full',
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
    kind: null,
    identity: 'pending',
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

    expect(api.get).toHaveBeenLastCalledWith(
      '/api/gallery/kiana?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled',
    );

    expect(lib.grid).toMatchObject({ slug: 'kiana', cursor: 'c1', done: false });
    expect(lib.grid.items.map((i) => i.sha256)).toEqual(['a', 'b']);

    await lib.loadGrid('kiana');

    expect(api.get).toHaveBeenLastCalledWith(
      '/api/gallery/kiana?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled&cursor=c1',
    );

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

    expect(api.get).toHaveBeenLastCalledWith(
      '/api/gallery/s?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled&cursor=k%3D1%26x%2Fy',
    );
  });

  it('starts over for a different slug or with reset=true', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce(page(['a'], 'c1'))
      .mockResolvedValueOnce(page(['z'], null))
      .mockResolvedValueOnce(page(['a2'], 'c2'));

    const lib = useLibrary();
    await lib.loadGrid('one');
    await lib.loadGrid('two');

    expect(api.get).toHaveBeenLastCalledWith(
      '/api/gallery/two?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled',
    );

    expect(lib.grid.items.map((i) => i.sha256)).toEqual(['z']);
    expect(lib.grid.done).toBe(true);

    await lib.loadGrid('two', true);

    expect(api.get).toHaveBeenLastCalledWith(
      '/api/gallery/two?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled',
    );

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

describe('useLibrary kind filter', () => {
  it('defaults to the kept kinds + unlabeled, and always asks for exactly those', async () => {
    vi.mocked(api.get).mockResolvedValueOnce(page([], null));
    const lib = useLibrary();

    expect(lib.show).toEqual(ALL_KIND_FILTERS); // narrowed per character below
    await lib.loadGrid('kiana');

    // sent even when all are on: the daemon may still hold thrown-away kinds before a cleanup
    expect(api.get).toHaveBeenLastCalledWith(
      '/api/gallery/kiana?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled',
    );
  });

  it('setShow() keeps chip order, remembers the choice and starts the grid over', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce(page(['a'], 'c1'))
      .mockResolvedValueOnce(page(['b'], null));

    const lib = useLibrary();
    await lib.loadGrid('kiana');

    await lib.setShow('kiana', ['unlabeled', 'illustration']);
    expect(lib.show).toEqual(['illustration', 'unlabeled']);
    expect(JSON.parse(localStorage.getItem('curio.gallery.show') ?? '[]')).toEqual(lib.show);
    expect(api.get).toHaveBeenLastCalledWith('/api/gallery/kiana?limit=120&kinds=illustration%2Cunlabeled');
    expect(lib.grid.items.map((i) => i.sha256)).toEqual(['b']); // reset, not appended
  });

  it('reads a saved choice at creation and ignores a corrupt one', () => {
    localStorage.setItem('curio.gallery.show', JSON.stringify(['photo']));
    expect(useLibrary().show).toEqual(['photo']);

    setActivePinia(createPinia());
    localStorage.setItem('curio.gallery.show', JSON.stringify(['nonsense']));
    expect(useLibrary().show).toEqual(DEFAULT_KIND_FILTER);
  });

  it('a character with its filter off gets every selected kind; with it on, only what it keeps', async () => {
    vi.mocked(api.get).mockResolvedValue(page([], null));
    const lib = useLibrary();
    lib.watches = [{ ...watch('all'), kind_filter: false }, watch('kept')];

    await lib.loadGrid('all');

    expect(api.get).toHaveBeenLastCalledWith(
      '/api/gallery/all?limit=120&kinds=illustration%2Cscreencap%2Cphoto%2Crender%2Cother%2Cunlabeled',
    );

    await lib.loadGrid('kept');

    expect(api.get).toHaveBeenLastCalledWith(
      '/api/gallery/kept?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled',
    );

    lib.show = ['photo']; // nothing this character holds: fall back to all it can
    await lib.loadGrid('kept', true);

    expect(api.get).toHaveBeenLastCalledWith(
      '/api/gallery/kept?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled',
    );
  });

  it('loadKinds() reads the per-kind counts', async () => {
    const kinds = {
      counts: { illustration: 3, photo: 1, render: 0, screencap: 0, other: 0, unlabeled: 2 },
      labeler: { available: true, models: false },
    };

    vi.mocked(api.get).mockResolvedValueOnce(kinds);
    const lib = useLibrary();
    await lib.loadKinds('kiana');

    expect(api.get).toHaveBeenCalledWith('/api/gallery/kiana/kinds');
    expect(lib.kinds).toEqual(kinds);
  });
});

describe('useLibrary identity filter', () => {
  const KINDS = 'kinds=illustration%2Cscreencap%2Cunlabeled';

  it('shows everyone by default and then sends no ident filter at all', async () => {
    vi.mocked(api.get).mockResolvedValueOnce(page([], null));
    const lib = useLibrary();

    expect(lib.who).toEqual(IDENT_STATES);
    await lib.loadGrid('mei');

    expect(api.get).toHaveBeenLastCalledWith(`/api/gallery/mei?limit=120&${KINDS}`);
  });

  it('setWho() keeps chip order, remembers the choice and starts the grid over', async () => {
    vi.mocked(api.get).mockResolvedValue(page([], null));
    const lib = useLibrary();

    await lib.setWho('mei', ['pending', 'unidentified']);

    expect(lib.who).toEqual(['unidentified', 'pending']);
    expect(JSON.parse(localStorage.getItem('curio.gallery.who') ?? '[]')).toEqual(lib.who);

    expect(api.get).toHaveBeenLastCalledWith(
      `/api/gallery/mei?limit=120&${KINDS}&ident=unidentified%2Cpending`,
    );

    setActivePinia(createPinia());
    expect(useLibrary().who).toEqual(['unidentified', 'pending']); // read back at creation
  });

  it('a chosen character replaces the state filter; null shows everyone again', async () => {
    vi.mocked(api.get).mockResolvedValue(page([], null));
    const lib = useLibrary();
    lib.who = ['unidentified'];

    await lib.setCharacter('mei', 'raiden_mei');
    expect(api.get).toHaveBeenLastCalledWith(`/api/gallery/mei?limit=120&${KINDS}&character=raiden_mei`);

    await lib.setCharacter('mei', null);
    expect(api.get).toHaveBeenLastCalledWith(`/api/gallery/mei?limit=120&${KINDS}&ident=unidentified`);
  });

  it('loadCharacters() reads the counts and the cast', async () => {
    const c = {
      counts: { identified: 2, unidentified: 1, pending: 0 },
      characters: [{ name: 'raiden_mei', label: 'Raiden Mei', count: 2 }],
      identifier: { enabled: true, available: true, models: true },
    };

    vi.mocked(api.get).mockResolvedValueOnce(c);
    const lib = useLibrary();
    await lib.loadCharacters('mei');

    expect(api.get).toHaveBeenCalledWith('/api/gallery/mei/characters');
    expect(lib.characters).toEqual(c);
  });
});

describe('useLibrary source and order', () => {
  const KINDS = 'kinds=illustration%2Cscreencap%2Cunlabeled';

  it('every source and newest first by default, so neither is sent', async () => {
    vi.mocked(api.get).mockResolvedValue(page([], null));
    const lib = useLibrary();
    await lib.loadGrid('kiana');

    expect(lib.source).toBeNull();
    expect(lib.order).toBe('newest');
    expect(api.get).toHaveBeenLastCalledWith(`/api/gallery/kiana?limit=120&${KINDS}`);
  });

  it('setSource() and setOrder() narrow the query and start the grid over', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce(page(['a'], 'c1'))
      .mockResolvedValueOnce(page(['x'], 'c2'))
      .mockResolvedValueOnce(page(['old'], null))
      .mockResolvedValueOnce(page(['all'], null));

    const lib = useLibrary();
    await lib.loadGrid('kiana');

    await lib.setSource('kiana', 'twitter');
    expect(api.get).toHaveBeenLastCalledWith(`/api/gallery/kiana?limit=120&${KINDS}&source=twitter`);
    expect(lib.grid.items.map((i) => i.sha256)).toEqual(['x']);

    // the newest-first cursor c2 must not be carried into the other order
    await lib.setOrder('kiana', 'oldest');

    expect(api.get).toHaveBeenLastCalledWith(
      `/api/gallery/kiana?limit=120&${KINDS}&source=twitter&order=oldest`,
    );

    expect(lib.grid.items.map((i) => i.sha256)).toEqual(['old']);

    await lib.setSource('kiana', null);
    expect(api.get).toHaveBeenLastCalledWith(`/api/gallery/kiana?limit=120&${KINDS}&order=oldest`);
  });
});

describe('useLibrary loadGrid() concurrency', () => {
  function deferred<T>() {
    let resolve!: (v: T) => void;
    const promise = new Promise<T>((r) => (resolve = r));

    return { promise, resolve };
  }

  it('a load while another is in flight does not fetch the same page twice', async () => {
    const first = deferred<GalleryPage>();
    vi.mocked(api.get).mockReturnValueOnce(first.promise);
    const lib = useLibrary();

    const a = lib.loadGrid('kiana', true); // e.g. a filter change…
    const b = lib.loadGrid('kiana'); // …while the empty grid's sentinel fires
    first.resolve(page(['x', 'y'], 'c1'));
    await Promise.all([a, b]);

    expect(api.get).toHaveBeenCalledTimes(1);
    expect(lib.grid.items.map((i) => i.sha256)).toEqual(['x', 'y']);
  });

  it('a reset drops the page of an older request that lands late', async () => {
    const old = deferred<GalleryPage>();
    const fresh = deferred<GalleryPage>();
    vi.mocked(api.get).mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const lib = useLibrary();

    const a = lib.loadGrid('kiana');
    const b = lib.loadGrid('kiana', true);
    fresh.resolve(page(['new'], null));
    old.resolve(page(['stale'], 'c9'));
    await Promise.all([a, b]);

    expect(lib.grid.items.map((i) => i.sha256)).toEqual(['new']);
    expect(lib.grid).toMatchObject({ cursor: null, done: true, loading: false });
  });
});
