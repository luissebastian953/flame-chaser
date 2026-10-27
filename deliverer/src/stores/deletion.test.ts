import { combine, useDeletion, mainReason, reasonTone, SMART_DEBOUNCE } from './deletion';
import type { SmartResult } from '@/lib/types';

vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  api: { get: vi.fn(), post: vi.fn() },
}));

const smart: SmartResult = {
  matches: [
    { sha256: 'b', reasons: [{ kind: 'score', score: 0.31 }] },
    { sha256: 'c', reasons: [{ kind: 'other', name: 'sam', label: 'Sam', score: 0.91 }] },
    { sha256: 'd', reasons: [{ kind: 'dupe', distance: 4, keep: 'a' }] },
  ],
  counts: { score: 1, other: 1, dupe: 1, unidentified: 0, kind: 0 },
  primary: 'firefly',
  primary_label: 'Firefly',
  characters: [{ name: 'sam', label: 'Sam', count: 1 }],
  total: 5,
  cutoff: 0.5,
  rule: null,
  identifier: { enabled: true },
};

describe('combine', () => {
  const t1 = { key: 'tag:a', kind: 'tag' as const, value: 'a', label: 'a', shas: ['1', '2', '3'] };
  const t2 = { key: 'tag:b', kind: 'tag' as const, value: 'b', label: 'b', shas: ['3', '4'] };

  it('any = union in first-seen order, all = intersection', () => {
    expect(combine([t1, t2], 'any')).toEqual(['1', '2', '3', '4']);
    expect(combine([t1, t2], 'all')).toEqual(['3']);
    expect(combine([], 'any')).toEqual([]);
  });
});

describe('By image', () => {
  it('toggle marks and unmarks; range fills between the last pick and the target in visual order', () => {
    const del = useDeletion();
    del.enter('ganyu', 'image');
    expect(del.active).toBe(true);
    expect(del.hintSeen).toBe(false);

    del.toggle('b');
    expect(del.effective).toEqual(['b']);
    expect(del.hintSeen).toBe(true);

    del.range(['a', 'b', 'c', 'd', 'e'], 'd');
    expect(del.effective).toEqual(['b', 'c', 'd']);

    del.toggle('c');
    expect(del.effective).toEqual(['b', 'd']);

    del.mark(['a', 'b']);
    expect(del.count).toBe(3);

    del.clear();
    expect(del.count).toBe(0);
    del.exit();
    expect(del.active).toBe(false);
  });
});

describe('By tag', () => {
  it('a chip asks the daemon with the grid filters; the second click drops it; a tile click drops one image', async () => {
    const del = useDeletion();
    del.enter('ganyu', 'tag');
    vi.mocked(api.get).mockResolvedValueOnce({ shas: ['1', '2', '3'] });

    await del.toggleTerm(
      'tag',
      '原神',
      '原神',
      new URLSearchParams({ kinds: 'illustration', source: 'pixiv' }),
      10,
    );

    expect(api.get).toHaveBeenCalledWith(
      '/api/gallery/ganyu/images?kinds=illustration&source=pixiv&tag=%E5%8E%9F%E7%A5%9E',
    );

    expect(del.effective).toEqual(['1', '2', '3']);
    expect(del.everythingPrompt).toBeNull();

    vi.mocked(api.get).mockResolvedValueOnce({ shas: ['3', '4'] });
    await del.toggleTerm('artist', 'pixiv:a', 'Alpha', new URLSearchParams(), 10);
    expect(vi.mocked(api.get).mock.lastCall?.[0]).toBe('/api/gallery/ganyu/images?sel_artist=pixiv%3Aa');
    expect(del.effective).toEqual(['1', '2', '3', '4']);
    expect(del.overlap).toBe(1);
    expect(del.termsOf('3').map((x) => x.label)).toEqual(['原神', 'Alpha']);

    del.setMatch('all');
    expect(del.effective).toEqual(['3']);

    del.setMatch('any');
    del.toggle('2'); // kept back out
    expect(del.effective).toEqual(['1', '3', '4']);
    expect(del.droppedSet.has('2')).toBe(true);
    del.toggle('zzz'); // not a candidate: nothing happens
    expect(del.dropped).toEqual(['2']);

    await del.toggleTerm('tag', '原神', '原神', new URLSearchParams(), 10);
    expect(del.effective).toEqual(['3', '4']);
  });

  it('a label chip selects by sel_label, filtered like the grid', async () => {
    const del = useDeletion();
    del.enter('ganyu', 'tag');
    vi.mocked(api.get).mockResolvedValueOnce({ shas: ['5', '6'] });

    await del.toggleTerm(
      'label',
      'non_illust',
      'Non-Illust',
      new URLSearchParams({ kinds: 'illustration', source: 'pixiv' }),
      10,
    );

    expect(api.get).toHaveBeenCalledWith(
      '/api/gallery/ganyu/images?kinds=illustration&source=pixiv&sel_label=non_illust',
    );

    expect(del.isTerm('label', 'non_illust')).toBe(true);
    expect(del.effective).toEqual(['5', '6']);
  });

  it('a daemon without the route raises an error toast instead of a dead chip', async () => {
    const del = useDeletion();
    del.enter('ganyu', 'tag');
    vi.mocked(api.get).mockRejectedValueOnce(new ApiError(404, 'not_found', 'Not Found'));
    await del.toggleTerm('tag', 'x', 'x', new URLSearchParams(), 10);
    expect(del.terms).toEqual([]);
    const toasts = useToasts();
    expect(toasts.items.map((t) => t.kind)).toEqual(['error']);
  });

  it('a chip that stands for the whole gallery prompts for All', async () => {
    const del = useDeletion();
    del.enter('ganyu', 'tag');
    vi.mocked(api.get).mockResolvedValueOnce({ shas: ['1', '2'] });
    await del.toggleTerm('tag', '甘雨', '甘雨', new URLSearchParams(), 2);
    expect(del.everythingPrompt).toBe('tag:甘雨');
  });
});

describe('Smart', () => {
  it('criteria changes recount after 150 ms; matches are pre-checked and a kept override survives a recount', async () => {
    vi.useFakeTimers();
    const del = useDeletion();
    del.enter('ganyu', 'smart');
    vi.mocked(api.post).mockResolvedValue(smart);

    del.setSmart({ minScore: 0.6 });
    del.setSmart({ dupes: false });
    expect(api.post).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(SMART_DEBOUNCE);
    expect(api.post).toHaveBeenCalledTimes(1);

    expect(api.post).toHaveBeenCalledWith('/api/gallery/ganyu/smart', {
      min_score: 0.6,
      other_character: true,
      dupes: false,
      distance: 6,
      unidentified: false,
      kinds: true,
    });

    expect(del.effective).toEqual(['b', 'c', 'd']);
    del.toggle('c');
    expect(del.effective).toEqual(['b', 'd']);
    await del.loadSmart();
    expect(del.dropped).toEqual(['c']);
    expect(mainReason(del.smartBySha.get('c')!.reasons)?.kind).toBe('other');
    expect(reasonTone({ kind: 'score', score: 0.31 })).toBe('rose');
    expect(reasonTone({ kind: 'score', score: 0.69 })).toBe('amber');
    expect(reasonTone({ kind: 'dupe', distance: 4, keep: 'a' })).toBe('cyan');

    // a cosplay photo named as someone else: the kind is the reason that shows
    const both = mainReason([
      { kind: 'other', name: 'sam', label: 'Sam', score: 0.9 },
      { kind: 'kind', label: 'photo' },
    ]);

    expect(both?.kind).toBe('kind');
    expect(reasonTone(both)).toBe('rose');
    vi.useRealTimers();
  });
});

describe('All, the sheet and the deletion', () => {
  it('loads everything, keeps what a tile click exempts, previews, commits the effective set and can undo', async () => {
    const del = useDeletion();
    del.enter('ganyu', 'all');
    vi.mocked(api.get).mockResolvedValueOnce({ shas: ['1', '2', '3'] });
    await del.loadEverything(new URLSearchParams({ kinds: 'illustration' }));
    expect(api.get).toHaveBeenCalledWith('/api/gallery/ganyu/images?kinds=illustration');
    expect(del.count).toBe(3);
    del.toggle('2');
    expect(del.effective).toEqual(['1', '3']);

    const preview = {
      images: 2,
      bytes: 10,
      by_source: { pixiv: 2 },
      posts: { touched: 2, keep_other: 0, forget: 2 },
      shared: 0,
      whole: false,
      forced_trash: false,
      trash: { count: 0, bytes: 0, oldest: null, days: 30 },
    };

    vi.mocked(api.post).mockResolvedValueOnce(preview);
    await del.openSheet();
    expect(api.post).toHaveBeenCalledWith('/api/gallery/ganyu/delete/preview', { shas: ['1', '3'] });
    expect(del.sheet).toBe(true);
    expect(del.preview).toEqual(preview);

    vi.mocked(api.post).mockResolvedValueOnce({
      batch_id: 'b1',
      images: 2,
      bytes: 10,
      forgotten: 0,
      permanent: false,
    });

    const r = await del.commit({ trash: true, forget: false, confirm: 'Ganyu' });

    expect(api.post).toHaveBeenLastCalledWith('/api/gallery/ganyu/delete', {
      shas: ['1', '3'],
      mode: 'all',
      trash: true,
      forget: false,
      confirm: 'Ganyu',
    });

    expect(r.batch_id).toBe('b1');
    expect(del.lastBatch).toBe('b1');

    vi.mocked(api.post).mockResolvedValueOnce({ images: 2, posts: 0 });
    await del.undo('b1');
    expect(api.post).toHaveBeenLastCalledWith('/api/trash/b1/restore');
    expect(del.lastBatch).toBeNull();
  });
});
