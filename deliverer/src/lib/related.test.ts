import { linkedStart, megabytes, relatedSet } from './related';
import type { PostDetail, PostMedia } from '@/lib/types';

function media(over: Partial<PostMedia> & { idx: number }): PostMedia {
  return {
    sha256: `sha${over.idx}`,
    state: 'stored',
    dupe_of: null,
    width: 2894,
    height: 4093,
    bytes: 8_640_000,
    ext: 'png',
    path: `/lib/blobs/sh/a${over.idx}/sha${over.idx}.png`,
    source_variant: 'original',
    identity: null,
    ...over,
  };
}

const post: PostDetail = {
  source: 'pixiv',
  external_id: '128994201',
  artist_id: '77',
  artist_name: 'yuu',
  artist_handle: 'yuu_draws',
  title: '甘雨 - 新年のご挨拶',
  caption: '',
  posted_at: '2026-08-21T10:00:00+00:00',
  permalink: 'https://www.pixiv.net/artworks/128994201',
  bookmark_count: 4182,
  state: 'live',
  source_meta: '{}',
  media: [media({ idx: 0 }), media({ idx: 1 }), media({ idx: 2, state: 'rejected', sha256: 'rej' })],
  tags: [],
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
        media({ idx: 1, sha256: 'x1', ext: 'jpg', source_variant: 'orig' }),
        media({ idx: 2, state: 'failed', sha256: null, path: null }),
      ],
    },
  ],
};

describe('relatedSet', () => {
  it('walks the pages first, then the linked post, skipping rows with nothing to show', () => {
    const set = relatedSet(post);

    expect(set.map((it) => it.key)).toEqual([
      'pixiv:128994201:0',
      'pixiv:128994201:1',
      'twitter:1958871220337:0',
      'twitter:1958871220337:1',
    ]);

    expect(set.map((it) => it.linked)).toEqual([false, false, true, true]);
    expect(linkedStart(set)).toBe(2);
  });

  it('labels pages by their index and counts only the shown ones', () => {
    const [p1, p2] = relatedSet(post);
    expect(p1!.page).toBe(1);
    expect(p2!.page).toBe(2);
    expect(p1!.pages).toBe(2);
  });

  it('serves a recorded duplicate from the kept copy and says it is not stored', () => {
    const copy = relatedSet(post)[2]!;
    expect(copy.stored).toBe(false);
    expect(copy.sha).toBe('sha0');
    expect(copy.path).toBeNull();
    expect(copy.source).toBe('twitter');
    expect(copy.permalink).toContain('x.com');
  });

  it('carries what the viewer prints', () => {
    const it = relatedSet(post)[0]!;

    expect(it).toMatchObject({
      title: '甘雨 - 新年のご挨拶',
      artist_handle: 'yuu_draws',
      width: 2894,
      height: 4093,
      ext: 'png',
      variant: 'original',
      path: '/lib/blobs/sh/a0/sha0.png',
    });

    expect(megabytes(it.bytes)).toBe('8.24');
    expect(megabytes(null)).toBe('0.00');
  });

  it('is just the pages when nothing is linked', () => {
    const set = relatedSet({ ...post, linked: [] });
    expect(set).toHaveLength(2);
    expect(linkedStart(set)).toBe(-1);
  });
});
