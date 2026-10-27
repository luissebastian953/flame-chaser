import type { GalleryItem, GalleryPage, PostDetail, Watch } from '@/lib/types';

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
    origin: 'pending',
    origin_by: null,
    label: null,
    label_source: 'auto',
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
  it('always asks for exactly the kinds the character keeps', async () => {
    vi.mocked(api.get).mockResolvedValueOnce(page([], null));
    const lib = useLibrary();
    await lib.loadGrid('kiana');

    // sent even though nothing narrows it: the daemon may still hold thrown-away kinds before a cleanup
    expect(api.get).toHaveBeenLastCalledWith(
      '/api/gallery/kiana?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled',
    );
  });

  it('a character with its filter off gets every kind; with it on, only what it keeps', async () => {
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

  it('loadCharacters() and loadOrigins() read the backlog counts the status line sums', async () => {
    const c = {
      counts: { identified: 2, unidentified: 1, pending: 0 },
      characters: [{ name: 'raiden_mei', label: 'Raiden Mei', count: 2 }],
      identifier: { enabled: true, available: true, models: true },
    };

    const o = { counts: { ai: 2, human: 9, pending: 1 }, detector: { available: true, models: false } };
    vi.mocked(api.get).mockResolvedValueOnce(c).mockResolvedValueOnce(o);
    const lib = useLibrary();
    await lib.loadCharacters('mei');
    await lib.loadOrigins('mei');

    expect(api.get).toHaveBeenCalledWith('/api/gallery/mei/characters');
    expect(api.get).toHaveBeenCalledWith('/api/gallery/mei/origins');
    expect(lib.characters).toEqual(c);
    expect(lib.origins).toEqual(o);
  });
});

describe('useLibrary label filter', () => {
  const KINDS = 'kinds=illustration%2Cscreencap%2Cunlabeled';

  it('any label by default, so none is sent; never ident, character or origin', async () => {
    vi.mocked(api.get).mockResolvedValueOnce(page([], null));
    const lib = useLibrary();

    expect(lib.label).toBeNull();
    await lib.loadGrid('mei');

    expect(api.get).toHaveBeenLastCalledWith(`/api/gallery/mei?limit=120&${KINDS}`);
    const url = vi.mocked(api.get).mock.lastCall?.[0] ?? '';
    expect(url).not.toMatch(/ident=|character=|origin=/);
  });

  it('setLabel() narrows the query to one label and starts the grid over; null is any again', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce(page(['a'], 'c1'))
      .mockResolvedValueOnce(page(['ai1'], null))
      .mockResolvedValueOnce(page(['a'], null));

    const lib = useLibrary();
    await lib.loadGrid('mei');

    await lib.setLabel('mei', 'ai');
    expect(lib.label).toBe('ai');
    expect(api.get).toHaveBeenLastCalledWith(`/api/gallery/mei?limit=120&${KINDS}&label=ai`);
    expect(lib.grid.items.map((i) => i.sha256)).toEqual(['ai1']); // reset, not appended

    await lib.setLabel('mei', null);
    expect(api.get).toHaveBeenLastCalledWith(`/api/gallery/mei?limit=120&${KINDS}`);
  });

  it('the label rides along with a source: the two are ANDed', async () => {
    vi.mocked(api.get).mockResolvedValue(page([], null));
    const lib = useLibrary();
    lib.source = 'twitter';

    await lib.setLabel('mei', 'non_illust');

    expect(api.get).toHaveBeenLastCalledWith(
      `/api/gallery/mei?limit=120&${KINDS}&label=non_illust&source=twitter`,
    );

    expect(lib.gridQuery('mei').get('label')).toBe('non_illust'); // what a selection list sends too
  });
});

describe('useLibrary artist filter', () => {
  const KINDS = 'kinds=illustration%2Cscreencap%2Cunlabeled';

  it('all artists by default, so none is sent', async () => {
    vi.mocked(api.get).mockResolvedValueOnce(page([], null));
    const lib = useLibrary();

    expect(lib.artist).toBeNull();
    expect(lib.artists).toEqual([]);
    await lib.loadGrid('mei');

    expect(api.get).toHaveBeenLastCalledWith(`/api/gallery/mei?limit=120&${KINDS}`);
    expect(lib.gridQuery('mei').has('artist')).toBe(false);
  });

  it('setArtist() narrows the query to one source:artist_id key and starts the grid over; null is all again', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce(page(['a'], 'c1'))
      .mockResolvedValueOnce(page(['by1'], null))
      .mockResolvedValueOnce(page(['a'], null));

    const lib = useLibrary();
    await lib.loadGrid('mei');

    await lib.setArtist('mei', 'pixiv:123');
    expect(lib.artist).toBe('pixiv:123');
    expect(api.get).toHaveBeenLastCalledWith(`/api/gallery/mei?limit=120&${KINDS}&artist=pixiv%3A123`);
    expect(lib.grid.items.map((i) => i.sha256)).toEqual(['by1']); // reset, not appended

    await lib.setArtist('mei', null);
    expect(api.get).toHaveBeenLastCalledWith(`/api/gallery/mei?limit=120&${KINDS}`);
  });

  it('the artist rides along with the source and the label: the three are ANDed', async () => {
    vi.mocked(api.get).mockResolvedValue(page([], null));
    const lib = useLibrary();
    lib.source = 'twitter';
    lib.label = 'ai';

    await lib.setArtist('mei', 'twitter:9');

    expect(api.get).toHaveBeenLastCalledWith(
      `/api/gallery/mei?limit=120&${KINDS}&label=ai&source=twitter&artist=twitter%3A9`,
    );

    expect(lib.gridQuery('mei').get('artist')).toBe('twitter:9'); // what a selection list sends too
  });

  it('loadArtists() reads up to 300 artists, most images first, as the daemon orders them', async () => {
    const artists = [
      { source: 'pixiv', artist_id: '1', name: 'A', handle: 'a', count: 9 },
      { source: 'twitter', artist_id: '2', name: 'B', handle: '', count: 3 },
    ];

    vi.mocked(api.get).mockResolvedValueOnce(artists);
    const lib = useLibrary();
    await lib.loadArtists('mei');

    expect(api.get).toHaveBeenCalledWith('/api/gallery/mei/artists?limit=300');
    expect(lib.artists).toEqual(artists);
  });
});

describe('useLibrary setImageLabel()', () => {
  const manual = (sha256: string, label: 'ai' | 'non_illust' | 'unidentified' | null) => ({
    sha256,
    label,
    label_source: 'manual' as const,
  });

  function detail(): PostDetail {
    return {
      source: 'pixiv',
      external_id: '1',
      artist_id: 'a',
      artist_name: 'a',
      artist_handle: 'a',
      title: 't',
      caption: '',
      posted_at: null,
      permalink: '',
      bookmark_count: 0,
      state: 'live',
      source_meta: '{}',
      media: [
        {
          idx: 0,
          sha256: 'a',
          state: 'stored',
          dupe_of: null,
          width: 1,
          height: 1,
          bytes: 1,
          ext: 'png',
          path: null,
          source_variant: '',
          label: null,
          label_source: 'auto',
        },
        {
          idx: 1,
          sha256: 'b',
          state: 'stored',
          dupe_of: null,
          width: 1,
          height: 1,
          bytes: 1,
          ext: 'png',
          path: null,
          source_variant: '',
          label: null,
          label_source: 'auto',
        },
      ],
      tags: [],
      linked: [],
    };
  }

  it('PUTs the label, then patches every grid tile and media row with that sha; the aside stays', async () => {
    vi.mocked(api.get).mockResolvedValueOnce(page(['a', 'b', 'a'], null));
    vi.mocked(api.put).mockResolvedValueOnce(manual('a', 'ai'));
    const lib = useLibrary();
    await lib.loadGrid('mei');
    const d = detail();
    lib.detail = d;

    await lib.setImageLabel('a', 'ai');

    expect(api.put).toHaveBeenCalledWith('/api/images/a/label', { label: 'ai' });

    expect(lib.grid.items.map((i) => [i.label, i.label_source])).toEqual([
      ['ai', 'manual'],
      [null, 'auto'],
      ['ai', 'manual'],
    ]);

    expect(lib.detail?.media.map((m) => [m.label, m.label_source])).toEqual([
      ['ai', 'manual'],
      [null, 'auto'],
    ]);

    expect(lib.detail).toMatchObject({ external_id: d.external_id }); // not closed, not refetched
    expect(api.get).toHaveBeenCalledTimes(1); // the grid is not filtered: no reload
  });

  it('clearing a label sends null; a filtered grid starts over so the filter re-applies', async () => {
    vi.mocked(api.get).mockResolvedValue(page(['a'], null));
    vi.mocked(api.put).mockResolvedValueOnce(manual('a', null));
    const lib = useLibrary();
    await lib.setLabel('mei', 'ai');
    expect(api.get).toHaveBeenCalledTimes(1);

    await lib.setImageLabel('a', null);

    expect(api.put).toHaveBeenCalledWith('/api/images/a/label', { label: null });
    expect(api.get).toHaveBeenCalledTimes(2);

    expect(api.get).toHaveBeenLastCalledWith(
      '/api/gallery/mei?limit=120&kinds=illustration%2Cscreencap%2Cunlabeled&label=ai',
    );
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
